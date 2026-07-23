"""
Tests for PLAN-33 Phase 3: bulk user creation from an Excel sheet.

Covers modules/launcher/_user_import.py's parse_users_excel() (preview) and
bulk_create_users() (commit) directly, mirroring the ERM risk-register
importer's own test approach: build a real in-memory .xlsx with openpyxl,
run it through the parser, and assert on the returned preview payload --
plus the commit function's org-scoping and per-row error isolation.

Uses the standard conftest test_db fixture (fresh, fully-migrated SQLite
per test).
"""
import io
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl


def _create_user(db, username="tester", org_id=None):
    db.execute(
        "INSERT INTO users (username, email, full_name, password_hash, org_id) VALUES (%s,%s,%s,%s,%s)",
        (username, f"{username}@example.com", username.title(), "x", org_id),
    )
    db.commit()
    return db.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()["id"]


def _create_org(db, slug):
    db.execute("INSERT INTO organizations (name, slug) VALUES (%s, %s)", (slug.title(), slug))
    db.commit()
    return db.execute("SELECT id FROM organizations WHERE slug=%s", (slug,)).fetchone()["id"]


def _build_workbook(rows, headers=None):
    headers = headers or ["Full Name", "Email", "Username (optional)", "Roles (comma-separated)", "Business Unit (SBU)"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_users_excel_basic_row(test_db):
    from modules.launcher._user_import import parse_users_excel

    file_bytes = _build_workbook([
        ["Jane Doe", "jane.doe@example.com", "", "employee", ""],
    ])
    result = parse_users_excel(file_bytes, is_super=False, caller_org_id=1)
    assert "error" not in result
    assert result["summary"]["total"] == 1
    row = result["rows"][0]
    assert row["full_name"] == "Jane Doe"
    assert row["email"] == "jane.doe@example.com"
    assert row["username"] == "jane.doe"
    assert row["roles"] == ["employee"]
    assert not row.get("error")
    assert not row.get("duplicate_email")


def test_parse_users_excel_flags_invalid_email(test_db):
    from modules.launcher._user_import import parse_users_excel

    file_bytes = _build_workbook([
        ["Bad Email Guy", "not-an-email", "", "employee", ""],
    ])
    result = parse_users_excel(file_bytes, is_super=False, caller_org_id=1)
    row = result["rows"][0]
    assert row["error"] == "invalid_email"
    assert result["summary"]["invalid"] == 1


def test_parse_users_excel_flags_duplicate_against_existing_db_user(test_db):
    from modules.launcher._user_import import parse_users_excel

    _create_user(test_db, "existing_user")
    # existing_user's email is existing_user@example.com per _create_user
    file_bytes = _build_workbook([
        ["Existing User", "existing_user@example.com", "", "employee", ""],
    ])
    result = parse_users_excel(file_bytes, is_super=False, caller_org_id=1)
    row = result["rows"][0]
    assert row["duplicate_email"] is True
    assert result["summary"]["duplicates"] == 1


def test_parse_users_excel_fuzzy_matches_business_unit(test_db):
    from modules.launcher._user_import import parse_users_excel
    from modules.governance.data_service import create_business_unit

    create_business_unit({"name": "Ecocash"})
    file_bytes = _build_workbook([
        ["Tino M", "tino@example.com", "", "employee", "Eco-cash"],  # slightly misspelled
    ])
    result = parse_users_excel(file_bytes, is_super=False, caller_org_id=1)
    row = result["rows"][0]
    assert row["business_unit_raw"] == "Eco-cash"
    bu_info = result["bu_map"]["Eco-cash"]
    assert bu_info["matched"] == "Ecocash"
    assert bu_info["confidence"] == "fuzzy"
    assert row["business_unit_id"] == bu_info["bu_id"]


def test_parse_users_excel_drops_unrecognized_and_super_admin_roles(test_db):
    from modules.launcher._user_import import parse_users_excel

    file_bytes = _build_workbook([
        ["Rolo Test", "rolo@example.com", "", "employee, super_admin, made_up_role", ""],
    ])
    result = parse_users_excel(file_bytes, is_super=False, caller_org_id=1)
    row = result["rows"][0]
    assert row["roles"] == ["employee"]
    assert any("made_up_role" in w for w in result["warnings"])
    assert any("Super Administrator" in w for w in result["warnings"])


def test_bulk_create_users_creates_with_bu_and_roles(test_db):
    from modules.launcher._user_import import parse_users_excel, bulk_create_users
    from modules.governance.data_service import create_business_unit

    bu_id = create_business_unit({"name": "Infraco"})
    org_id = _create_org(test_db, "bulk-create-org")
    admin_uid = _create_user(test_db, "bulk_admin", org_id=org_id)

    file_bytes = _build_workbook([
        ["New Person", "new.person@example.com", "", "employee", "Infraco"],
    ])
    preview = parse_users_excel(file_bytes, is_super=False, caller_org_id=org_id)
    admin = {"id": admin_uid, "org_id": org_id, "is_super_admin": 0}
    result = bulk_create_users(preview["rows"], admin)

    assert result["created"] == 1, result["errors"]
    assert result["skipped"] == 0
    assert len(result["credentials"]) == 1
    assert result["credentials"][0]["username"] == "new.person"

    row = test_db.execute(
        "SELECT org_id, business_unit_id, must_change_password FROM users WHERE username=%s",
        ("new.person",),
    ).fetchone()
    assert row["org_id"] == org_id
    assert row["business_unit_id"] == bu_id
    assert row["must_change_password"] == 1

    role_rows = test_db.execute(
        "SELECT role_key FROM user_roles WHERE user_id=(SELECT id FROM users WHERE username=%s)",
        ("new.person",),
    ).fetchall()
    assert [r["role_key"] for r in role_rows] == ["employee"]


def test_bulk_create_users_org_admin_forced_into_own_org(test_db):
    """An org-scoped admin's import must always land in their own org,
    regardless of any Organization column/override -- PLAN-30 org scoping."""
    from modules.launcher._user_import import parse_users_excel, bulk_create_users

    org_a = _create_org(test_db, "import-org-a")
    _create_org(test_db, "import-org-b")
    admin_uid = _create_user(test_db, "org_a_import_admin", org_id=org_a)

    file_bytes = _build_workbook([
        ["Org Scoped User", "scoped@example.com", "", "employee", ""],
    ])
    preview = parse_users_excel(file_bytes, is_super=False, caller_org_id=org_a)
    admin = {"id": admin_uid, "org_id": org_a, "is_super_admin": 0}
    # Even if a malicious org_override were supplied, bulk_create_users must
    # ignore it for a non-super caller.
    result = bulk_create_users(preview["rows"], admin, org_overrides={"": 999999})

    assert result["created"] == 1, result["errors"]
    row = test_db.execute(
        "SELECT org_id FROM users WHERE email=%s", ("scoped@example.com",)
    ).fetchone()
    assert row["org_id"] == org_a


def test_bulk_create_users_skips_duplicates_and_invalid_rows(test_db):
    from modules.launcher._user_import import parse_users_excel, bulk_create_users

    org_id = _create_org(test_db, "skip-dup-org")
    admin_uid = _create_user(test_db, "skip_dup_admin", org_id=org_id)
    _create_user(test_db, "dup_target", org_id=org_id)
    file_bytes = _build_workbook([
        ["Good Row", "good.row@example.com", "", "employee", ""],
        ["Dup Row", "dup_target@example.com", "", "employee", ""],
        ["Bad Row", "not-an-email", "", "employee", ""],
    ])
    preview = parse_users_excel(file_bytes, is_super=False, caller_org_id=org_id)
    admin = {"id": admin_uid, "org_id": org_id, "is_super_admin": 0}
    result = bulk_create_users(preview["rows"], admin)

    assert result["created"] == 1, result["errors"]
    assert result["skipped"] == 2
    assert len(result["credentials"]) == 1
    assert result["credentials"][0]["username"] == "good.row"
