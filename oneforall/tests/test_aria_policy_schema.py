"""
PLAN-35 T01: schema, migration, and legacy-readiness tests.

Covers: fresh creation, repeated/idempotent migration, preservation of
existing aria_documents data across a re-migration, the schema-readiness
check, the document-number sequence allocator, and the dry-run repair
report's org/owner/version classification (including malformed legacy
version values, which must be reported, never silently reset).
"""
import database
from database import aria_policy_workflow_schema_ready
from scripts.prepare_aria_policy_workflow import (
    build_report,
    ensure_document_number_sequence,
    apply_org_id,
)


# ─────────────────────────────────────────────────────────────────────────
# Fresh creation
# ─────────────────────────────────────────────────────────────────────────

def test_fresh_db_has_all_new_tables(test_db):
    tables = {r[0] for r in test_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'aria_%'"
    ).fetchall()}
    for expected in (
        "aria_policy_drafts", "aria_policy_versions", "aria_document_approvals",
        "aria_document_number_sequence", "aria_policy_publication_jobs",
    ):
        assert expected in tables, f"missing table {expected}"


def test_fresh_db_has_all_new_columns(test_db):
    for table, column in (
        ("aria_documents", "org_id"),
        ("aria_documents", "owner_user_id"),
        ("aria_documents", "current_policy_version_id"),
        ("aria_documents", "policy_workflow_managed"),
        ("aria_documents", "archived_at"),
        ("aria_documents", "lock_version"),
        ("aria_doc_templates", "org_id"),
        ("aria_doc_templates", "business_unit_id"),
        ("aria_doc_templates", "is_active"),
        ("aria_doc_templates", "file_sha256"),
        ("evidence_items", "aria_policy_version_id"),
        ("grid_evidence_files", "aria_policy_version_id"),
    ):
        # Must not raise -- column exists.
        test_db.execute(f"SELECT {column} FROM {table} LIMIT 0")


def test_schema_readiness_check_passes_on_fresh_db(test_db):
    ready, missing = aria_policy_workflow_schema_ready(test_db)
    assert ready is True
    assert missing == []


def test_schema_readiness_check_reports_missing_table(test_db):
    test_db.execute("DROP TABLE aria_policy_publication_jobs")
    test_db.commit()
    ready, missing = aria_policy_workflow_schema_ready(test_db)
    assert ready is False
    assert "table:aria_policy_publication_jobs" in missing


# ─────────────────────────────────────────────────────────────────────────
# Repeated / idempotent migration, preservation of existing data
# ─────────────────────────────────────────────────────────────────────────

def test_repeated_init_db_is_idempotent_and_preserves_data(test_db, monkeypatch):
    test_db.execute(
        "INSERT INTO aria_documents (doc_id, framework, title, version, status, owner) "
        "VALUES ('DOC-0001', 'ISO 27001', 'Access Control Policy', '1.0', 'Approved', 'Jane Doe')"
    )
    test_db.commit()

    # Re-run the full migration against the same on-disk DB file.
    database.init_db()
    database.init_db()  # twice: must not error or duplicate anything

    row = test_db.execute(
        "SELECT title, version, status, owner FROM aria_documents WHERE doc_id='DOC-0001'"
    ).fetchone()
    assert dict(row) == {
        "title": "Access Control Policy", "version": "1.0",
        "status": "Approved", "owner": "Jane Doe",
    }
    count = test_db.execute(
        "SELECT COUNT(*) FROM aria_documents WHERE doc_id='DOC-0001'"
    ).fetchone()[0]
    assert count == 1, "repeated migration must not duplicate existing rows"

    ready, missing = aria_policy_workflow_schema_ready(test_db)
    assert ready is True and missing == []


# ─────────────────────────────────────────────────────────────────────────
# Document number sequence allocator
# ─────────────────────────────────────────────────────────────────────────

def test_number_sequence_initializes_past_highest_existing_doc_id(test_db):
    for doc_id in ("DOC-0003", "DOC-0011", "DOC-0007"):
        test_db.execute(
            "INSERT INTO aria_documents (doc_id, framework, title, version, status) "
            "VALUES (%s, 'ISO 27001', 'x', '1.0', 'Draft')", (doc_id,),
        )
    test_db.commit()

    next_value = ensure_document_number_sequence(test_db)
    assert next_value == 12  # one past DOC-0011

    row = test_db.execute(
        "SELECT next_value FROM aria_document_number_sequence WHERE id=1"
    ).fetchone()
    assert row[0] == 12


def test_number_sequence_never_rewinds_on_rerun(test_db):
    test_db.execute(
        "INSERT INTO aria_document_number_sequence (id, next_value) VALUES (1, 50)"
    )
    test_db.commit()
    # No DOC-* rows exist, so the highest-suffix scan alone would want to
    # reset to 1 -- the allocator must never move backwards.
    next_value = ensure_document_number_sequence(test_db)
    assert next_value == 50


# ─────────────────────────────────────────────────────────────────────────
# Dry-run repair report: org/owner/version classification
# ─────────────────────────────────────────────────────────────────────────

def _make_org(db, org_id, slug):
    db.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (%s, %s, %s)",
        (org_id, slug, slug),
    )


def _make_user(db, user_id, username, full_name, org_id=None):
    db.execute(
        "INSERT INTO users (id, username, full_name, email, password_hash, org_id) "
        "VALUES (%s, %s, %s, %s, 'x', %s)",
        (user_id, username, full_name, f"{username}@example.com", org_id),
    )


def test_report_flags_no_organization_exists(test_db):
    test_db.execute(
        "INSERT INTO aria_documents (doc_id, framework, title, version, status, owner) "
        "VALUES ('DOC-0001', 'ISO 27001', 't', '1.0', 'Draft', 'Jane Doe')"
    )
    test_db.commit()
    report = build_report(test_db)
    assert report["organizations"] == []
    entry = report["unresolved"][0]
    assert "NO_ORGANIZATION_EXISTS" in entry["problems"]


def test_report_resolves_clean_single_org_row(test_db):
    _make_org(test_db, 1, "econet")
    _make_user(test_db, 1, "jdoe", "Jane Doe", org_id=1)
    test_db.execute(
        "INSERT INTO aria_documents (doc_id, framework, title, version, status, owner) "
        "VALUES ('DOC-0001', 'ISO 27001', 't', '1.0', 'Draft', 'Jane Doe')"
    )
    test_db.commit()
    report = build_report(test_db)
    assert report["unresolved"] == []
    assert report["resolvable_count"] == 1
    assert report["resolvable"][0]["doc_id"] == "DOC-0001"


def test_report_flags_ambiguous_owner(test_db):
    _make_org(test_db, 1, "econet")
    _make_user(test_db, 1, "jdoe1", "Jane Doe", org_id=1)
    _make_user(test_db, 2, "jdoe2", "Jane Doe", org_id=1)
    test_db.execute(
        "INSERT INTO aria_documents (doc_id, framework, title, version, status, owner) "
        "VALUES ('DOC-0001', 'ISO 27001', 't', '1.0', 'Draft', 'Jane Doe')"
    )
    test_db.commit()
    report = build_report(test_db)
    assert "OWNER_AMBIGUOUS_MULTIPLE_USERS_MATCH" in report["unresolved"][0]["problems"]


def test_report_flags_unmatched_and_blank_owner(test_db):
    _make_org(test_db, 1, "econet")
    test_db.executemany(
        "INSERT INTO aria_documents (doc_id, framework, title, version, status, owner) "
        "VALUES (%s, 'ISO 27001', 't', '1.0', 'Draft', %s)",
        [("DOC-0001", "Nobody Real"), ("DOC-0002", "")],
    )
    test_db.commit()
    report = build_report(test_db)
    by_id = {e["doc_id"]: e["problems"] for e in report["unresolved"]}
    assert "OWNER_NO_USER_MATCH" in by_id["DOC-0001"]
    assert "OWNER_BLANK" in by_id["DOC-0002"]


def test_report_flags_malformed_version_without_resetting_it(test_db):
    """Section 4.8 item 10: a non-N.M legacy version must be reported, not
    silently reset to 1.0."""
    _make_org(test_db, 1, "econet")
    _make_user(test_db, 1, "jdoe", "Jane Doe", org_id=1)
    test_db.execute(
        "INSERT INTO aria_documents (doc_id, framework, title, version, status, owner) "
        "VALUES ('DOC-0001', 'ISO 27001', 't', 'v2-draft', 'Draft', 'Jane Doe')"
    )
    test_db.commit()
    report = build_report(test_db)
    entry = report["unresolved"][0]
    assert "VERSION_NOT_N_DOT_M" in entry["problems"]

    # The report itself must never have written anything back.
    row = test_db.execute(
        "SELECT version FROM aria_documents WHERE doc_id='DOC-0001'"
    ).fetchone()
    assert row[0] == "v2-draft"


def test_report_flags_multiple_organizations_as_ambiguous(test_db):
    _make_org(test_db, 1, "econet")
    _make_org(test_db, 2, "omni")
    test_db.execute(
        "INSERT INTO aria_documents (doc_id, framework, title, version, status, owner) "
        "VALUES ('DOC-0001', 'ISO 27001', 't', '1.0', 'Draft', '')"
    )
    test_db.commit()
    report = build_report(test_db)
    entry = report["unresolved"][0]
    assert "ORG_AMBIGUOUS_MULTIPLE_EXIST" in entry["problems"]


def test_already_managed_rows_are_excluded_from_the_report(test_db):
    """A row already adopted (policy_workflow_managed=1) is not this
    report's concern even if its owner/version would otherwise look messy."""
    test_db.execute(
        "INSERT INTO aria_documents "
        "(doc_id, framework, title, version, status, owner, policy_workflow_managed) "
        "VALUES ('DOC-0001', 'ISO 27001', 't', 'garbage', 'Draft', '', 1)"
    )
    test_db.commit()
    report = build_report(test_db)
    assert report["resolvable"] == []
    assert report["unresolved"] == []


# ─────────────────────────────────────────────────────────────────────────
# Explicit-mapping apply path (never a default write action)
# ─────────────────────────────────────────────────────────────────────────

def test_apply_org_id_only_touches_resolvable_null_org_rows(test_db):
    _make_org(test_db, 1, "econet")
    _make_user(test_db, 1, "jdoe", "Jane Doe", org_id=1)
    test_db.execute(
        "INSERT INTO aria_documents (doc_id, framework, title, version, status, owner) "
        "VALUES ('DOC-0001', 'ISO 27001', 't', '1.0', 'Draft', 'Jane Doe')"
    )
    test_db.execute(
        "INSERT INTO aria_documents (doc_id, framework, title, version, status, owner) "
        "VALUES ('DOC-0002', 'ISO 27001', 't', 'bad-version', 'Draft', 'Jane Doe')"
    )
    test_db.commit()
    report = build_report(test_db)

    n = apply_org_id(test_db, 1, report)
    assert n == 1

    row1 = test_db.execute(
        "SELECT org_id FROM aria_documents WHERE doc_id='DOC-0001'"
    ).fetchone()
    assert row1[0] == 1
    row2 = test_db.execute(
        "SELECT org_id FROM aria_documents WHERE doc_id='DOC-0002'"
    ).fetchone()
    assert row2[0] is None, "an unresolved row must never be written to"


def test_apply_org_id_refuses_when_multiple_organizations_exist(test_db):
    _make_org(test_db, 1, "econet")
    _make_org(test_db, 2, "omni")
    test_db.execute(
        "INSERT INTO aria_documents (doc_id, framework, title, version, status, owner) "
        "VALUES ('DOC-0001', 'ISO 27001', 't', '1.0', 'Draft', '')"
    )
    test_db.commit()
    report = build_report(test_db)
    try:
        apply_org_id(test_db, 1, report)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_apply_org_id_refuses_nonexistent_organization(test_db):
    _make_org(test_db, 1, "econet")
    report = build_report(test_db)
    try:
        apply_org_id(test_db, 999, report)
        assert False, "expected ValueError"
    except ValueError:
        pass
