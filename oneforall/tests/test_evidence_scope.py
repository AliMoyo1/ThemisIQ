"""Shared evidence visibility and search predicates (design/evidence-vault/PHASE-1A.md, T1)."""
import types

import pytest

from core.sql_like import MAX_SEARCH_CHARS
from modules.evidence.scope import current_library_sql, evidence_scope_sql, evidence_search_sql


def _org(db, slug):
    db.execute(
        "INSERT INTO organizations (name, slug, plan, status) VALUES (%s,%s,'enterprise','active')",
        (slug, slug),
    )
    db.commit()
    return db.execute("SELECT id FROM organizations WHERE slug=%s", (slug,)).fetchone()["id"]


def _bu(db, code, parent_id=None):
    db.execute(
        "INSERT INTO business_units (name, code, parent_id, is_active) VALUES (%s,%s,%s,1)",
        (code, code, parent_id),
    )
    db.commit()
    return db.execute("SELECT id FROM business_units WHERE code=%s", (code,)).fetchone()["id"]


def _item(db, title, org_id, bu_id=None, **cols):
    fields = {"title": title, "org_id": org_id, "business_unit_id": bu_id, "status": "current", **cols}
    db.execute(
        f"INSERT INTO evidence_items ({', '.join(fields)}) VALUES ({', '.join(['%s'] * len(fields))})",
        tuple(fields.values()),
    )
    db.commit()


def _visible(db, user):
    sql, params = evidence_scope_sql(user)
    rows = db.execute(f"SELECT e.title FROM evidence_items e WHERE {sql}", params).fetchall()
    return {r["title"] for r in rows}


def _found(db, term):
    sql, params = evidence_search_sql(term)
    rows = db.execute(f"SELECT e.title FROM evidence_items e WHERE {sql}", params).fetchall()
    return {r["title"] for r in rows}


@pytest.fixture
def world(test_db):
    org1, org2 = _org(test_db, "o1"), _org(test_db, "o2")
    parent = _bu(test_db, "P")
    child = _bu(test_db, "C", parent)
    sibling = _bu(test_db, "S")
    _item(test_db, "org1-wide", org1)
    _item(test_db, "org1-parent", org1, parent)
    _item(test_db, "org1-child", org1, child)
    _item(test_db, "org1-sibling", org1, sibling)
    _item(test_db, "org2-wide", org2)
    _item(test_db, "no-org", None)
    return types.SimpleNamespace(org1=org1, org2=org2, parent=parent, child=child, sibling=sibling)


def test_super_admin_sees_every_row(test_db, world):
    got = _visible(test_db, {"is_super_admin": 1})
    assert got == {"org1-wide", "org1-parent", "org1-child", "org1-sibling", "org2-wide", "no-org"}


def test_user_without_an_org_sees_nothing(test_db, world):
    assert _visible(test_db, {"is_super_admin": 0, "org_id": None, "business_unit_id": None}) == set()


def test_org_user_without_a_business_unit_sees_only_org_wide_rows(test_db, world):
    assert _visible(test_db, {"org_id": world.org1, "business_unit_id": None}) == {"org1-wide"}


def test_business_unit_user_sees_own_subtree_and_org_wide_rows_only(test_db, world):
    assert _visible(test_db, {"org_id": world.org1, "business_unit_id": world.parent}) == {
        "org1-wide", "org1-parent", "org1-child",
    }
    assert _visible(test_db, {"org_id": world.org1, "business_unit_id": world.child}) == {
        "org1-wide", "org1-child",
    }


def test_another_orgs_rows_are_never_visible(test_db, world):
    assert _visible(test_db, {"org_id": world.org2, "business_unit_id": None}) == {"org2-wide"}


def test_alias_must_be_a_plain_identifier():
    with pytest.raises(ValueError):
        evidence_scope_sql({"is_super_admin": 1}, "e; DROP TABLE evidence_items")
    with pytest.raises(ValueError):
        evidence_search_sql("x", "e)--")
    with pytest.raises(ValueError):
        current_library_sql("e OR 1=1")


def test_default_library_hides_archived_and_superseded(test_db):
    for status in ("current", "expired", "archived", "superseded"):
        _item(test_db, status, None, status=status)
    rows = test_db.execute(
        f"SELECT e.title FROM evidence_items e WHERE {current_library_sql()}"
    ).fetchall()
    assert {r["title"] for r in rows} == {"current", "expired"}


def test_search_matches_any_case_in_title_filename_tags_and_description(test_db):
    _item(test_db, "Access Review Q3", None)
    _item(test_db, "unrelated one", None, file_name="Backup_Report.PDF")
    _item(test_db, "unrelated two", None, tags="iso27001,Policy")
    _item(test_db, "unrelated three", None, description="Quarterly Penetration Test summary")
    assert _found(test_db, "access review") == {"Access Review Q3"}
    assert _found(test_db, "BACKUP_report.pdf") == {"unrelated one"}
    assert _found(test_db, "POLICY") == {"unrelated two"}
    assert _found(test_db, "penetration") == {"unrelated three"}


def test_percent_underscore_and_the_escape_character_in_a_query_are_literal(test_db):
    for title in ("100% complete", "plain title", "a_b", "axb", "wow!"):
        _item(test_db, title, None)
    assert _found(test_db, "%") == {"100% complete"}
    assert _found(test_db, "a_b") == {"a_b"}
    assert _found(test_db, "!") == {"wow!"}


def test_blank_search_adds_no_constraint():
    assert evidence_search_sql("") == ("(1 = 1)", [])
    assert evidence_search_sql("   ") == ("(1 = 1)", [])


def test_search_term_length_is_capped():
    _, params = evidence_search_sql("x" * 1000)
    assert {len(p) for p in params} == {MAX_SEARCH_CHARS + 2}


def test_search_sql_lowercases_both_sides_and_declares_its_escape():
    # Case-insensitivity must not depend on the engine's default LIKE (case sensitive on PostgreSQL).
    sql, params = evidence_search_sql("Abc")
    assert sql.count("LOWER(") == 8
    assert "ESCAPE '!'" in sql
    assert params == ["%Abc%"] * 4
