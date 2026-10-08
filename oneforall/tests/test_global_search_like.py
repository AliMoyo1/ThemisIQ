"""Topbar global search matches the same rows on SQLite and PostgreSQL.

Plain LIKE ignores ASCII case on SQLite but is case sensitive on PostgreSQL, and a user's own
% and _ are wildcards on both, so the plain SQLite suite cannot see the difference. Every test
here runs with SQLite's case_sensitive_like switched on, which makes plain LIKE behave as it does
on PostgreSQL: a block that does not lowercase both sides fails here too.
"""
import asyncio
import json
import types

import pytest

import core.middleware as middleware
import modules.launcher.routes_platform as plat
from core.sql_like import ci_like, like_pattern

USER = {"id": 1, "username": "searcher", "org_id": None, "business_unit_id": None,
        "is_super_admin": 1, "roles": ["super_admin"]}


@pytest.fixture(autouse=True)
def postgres_like(monkeypatch):
    """Connections the route opens compare LIKE the way PostgreSQL does."""
    real_get_db = plat.get_db

    def get_db():
        db = real_get_db()
        db.execute("PRAGMA case_sensitive_like = ON")
        return db

    monkeypatch.setattr(plat, "get_db", get_db)


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    async def current_user(request):
        return request.state.user

    monkeypatch.setattr(middleware, "get_current_user", current_user)


def _blocks(framework_id):
    """(table, searched columns, (module, type) of its results, other columns a row needs)."""
    return [
        ("controls", ("name", "ref"), ("aria", "control"), {"framework_id": framework_id}),
        ("aria_documents", ("title", "doc_id"), ("aria", "document"), {"framework": "ISO 27001"}),
        ("sentinel_ropa", ("processing_name", "ref_number"), ("sentinel", "ropa"), {}),
        ("grid_audits", ("name",), ("grid", "audit"), {}),
        ("bcm_plans", ("title",), ("bcm", "plan"), {}),
        ("risk_register", ("title",), ("platform", "risk"), {}),
        ("sentinel_breaches", ("title", "ref_number"), ("sentinel", "breach"), {}),
        ("sentinel_dpias", ("title", "ref_number"), ("sentinel", "dpia"), {}),
        ("sentinel_dsr", ("requester_name", "ref_number"), ("sentinel", "dsr"), {}),
        ("sentinel_vendors", ("name",), ("sentinel", "vendor"), {}),
        ("erm_enterprise_risks", ("title",), ("erm", "risk"), {}),
        ("erm_regulatory_obligations", ("regulation_name", "obligation"), ("erm", "obligation"),
         {"regulator": "Regulator"}),
        ("orm_events", ("title",), ("orm", "event"), {}),
        ("orm_kris", ("name",), ("orm", "kri"), {}),
    ]


def _seed(db, hit, miss):
    """Insert, for every searched column, one row holding `hit` there and one decoy holding `miss`.

    Returns the (module, type, id) of the rows a search for `hit` must find, and nothing else."""
    db.execute("INSERT INTO frameworks (name) VALUES ('Search framework')")
    framework_id = db.execute("SELECT id FROM frameworks WHERE name = 'Search framework'").fetchone()[0]
    expected, n = set(), 0
    for table, columns, (module, kind), extra in _blocks(framework_id):
        for column in columns:
            for is_hit, value in ((True, hit), (False, miss)):
                n += 1
                row = {c: f"filler {n}" for c in columns} | extra | {column: value}
                cur = db.execute(
                    f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join(['%s'] * len(row))})",
                    tuple(row.values()),
                )
                if is_hit:
                    expected.add((module, kind, cur.lastrowid))
    db.commit()
    return expected


def _found(term, user=USER):
    request = types.SimpleNamespace(
        state=types.SimpleNamespace(user=user),
        url=types.SimpleNamespace(path="/api/search"),
        query_params={"q": term},
    )
    body = json.loads(asyncio.run(plat.api_global_search(request)).body)
    return {(r["module"], r["type"], r["id"]) for r in body["results"]}


def test_the_fixture_makes_plain_like_case_sensitive_as_on_postgres(test_db):
    test_db.execute("INSERT INTO sentinel_vendors (name) VALUES ('Acme Payroll')")
    test_db.commit()
    db = plat.get_db()
    try:
        plain = db.execute("SELECT COUNT(*) FROM sentinel_vendors WHERE name LIKE %s", ("%acme%",))
        lowered = db.execute("SELECT COUNT(*) FROM sentinel_vendors WHERE LOWER(name) LIKE LOWER(%s)", ("%ACME%",))
        assert plain.fetchone()[0] == 0
        assert lowered.fetchone()[0] == 1
    finally:
        db.close()


def test_every_block_matches_in_any_case_on_every_searched_column(test_db):
    expected = _seed(test_db, "Annual Quartz Ledger", "Annual Marble Ledger")
    assert len(expected) == 21  # 14 blocks, 21 searched columns
    for term in ("quartz ledger", "QUARTZ LEDGER", "qUaRtZ lEdGeR"):
        assert _found(term) == expected, term


@pytest.mark.parametrize("hit, miss, term", [
    ("Limit 5% breach", "Limit 50 breach", "5%"),
    ("case a_b", "case axb", "a_b"),
    ("wow! moment", "wow moment", "wow!"),
    ("path c:\\temp", "path c:temp", "c:\\temp"),
], ids=["percent", "underscore", "escape-character", "backslash"])
def test_wildcards_and_escape_characters_in_the_term_are_literal(test_db, hit, miss, term):
    expected = _seed(test_db, hit, miss)
    assert _found(term) == expected


def test_aria_documents_keep_their_organization_scope(test_db):
    for org_id in (1, 2):
        test_db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,%s,%s)",
                        (org_id, f"org{org_id}", f"org{org_id}"))
    ids = {}
    for name, org_id, managed in (("own", 1, 1), ("other", 2, 1), ("legacy", None, 0)):
        ids[name] = test_db.execute(
            "INSERT INTO aria_documents (doc_id, framework, title, org_id, policy_workflow_managed) "
            "VALUES (%s,'ISO 27001',%s,%s,%s)",
            (f"DOC-{name}", f"Scoped policy {name}", org_id, managed),
        ).lastrowid
    test_db.commit()
    user = {**USER, "org_id": 1, "is_super_admin": 0}
    documents = {i for module, kind, i in _found("SCOPED POLICY", user) if kind == "document"}
    assert documents == {ids["own"], ids["legacy"]}


def test_like_pattern_makes_the_users_own_wildcards_literal():
    assert like_pattern("50%_!") == "%50!%!_!!%"
    assert like_pattern("  padded  ") == "%padded%"
    assert like_pattern("x" * 500) == "%" + "x" * 200 + "%"


def test_ci_like_accepts_plain_columns_only():
    assert ci_like("name") == "LOWER(name) LIKE LOWER(%s) ESCAPE '!'"
    assert ci_like("c.ref") == "LOWER(c.ref) LIKE LOWER(%s) ESCAPE '!'"
    for bad in ("", "1name", "a.b.c", "na me", "name--", "name) OR (1=1", "name; DROP TABLE users"):
        with pytest.raises(ValueError):
            ci_like(bad)
