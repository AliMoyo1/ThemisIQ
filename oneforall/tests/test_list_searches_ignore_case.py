"""Search boxes in the module lists match whatever case the user types, and treat % and _ literally.

Plain LIKE ignores ASCII case on SQLite but is case sensitive on PostgreSQL, where production runs,
so a user typing "iso 27001" found nothing when the data said "ISO 27001" (finding H3 in
PG_MIGRATION_AUDIT.md), and a typed % or _ acted as a wildcard on both. The plain SQLite suite cannot
see either, so every test here switches SQLite to case_sensitive_like, which makes plain LIKE behave
as PostgreSQL does: a search that does not lowercase both sides fails here too.

Only boxes where a person types free text are covered. LIKE on system generated markers (tags such as
aria_doc_id=..., task titles, constant patterns) and on dropdown filters keeps its exact meaning.
"""
import asyncio
import json
import types

import pytest

import core.middleware as middleware
import modules.aria.routes as aria_routes
import modules.bcm.data_service as bcm_ds
import modules.erm.data_service as erm_ds
import modules.launcher.routes_admin as admin_routes
import modules.sentinel.data_service as sentinel_ds

ADMIN = {"id": 1, "username": "admin", "org_id": None, "business_unit_id": None,
         "is_super_admin": 1, "roles": ["super_admin"]}


@pytest.fixture(autouse=True)
def postgres_like(test_db, monkeypatch):
    """Every connection opened from here on compares LIKE the way PostgreSQL does."""
    import database

    real_connect = database.sqlite3.connect

    def connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.execute("PRAGMA case_sensitive_like = ON")
        return conn

    monkeypatch.setattr(database.sqlite3, "connect", connect)
    test_db.execute("PRAGMA case_sensitive_like = ON")


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    async def current_user(request):
        return ADMIN

    monkeypatch.setattr(middleware, "get_current_user", current_user)


def _insert(db, table, **cols):
    cur = db.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        tuple(cols.values()),
    )
    db.commit()
    return cur.lastrowid


# (list function, table, searched column, other columns a row needs)
SENTINEL_LISTS = [
    (sentinel_ds.list_ropa, "sentinel_ropa", "processing_name", {"ref_number": "R-{n}"}),
    (sentinel_ds.list_dpias, "sentinel_dpias", "title", {"ref_number": "D-{n}"}),
    (sentinel_ds.list_aiias, "sentinel_aiia", "title", {"ref_number": "A-{n}"}),
    (sentinel_ds.list_breaches, "sentinel_breaches", "title", {"ref_number": "B-{n}"}),
    (sentinel_ds.list_dsrs, "sentinel_dsr", "requester_name", {"ref_number": "S-{n}"}),
    (sentinel_ds.list_vendors, "sentinel_vendors", "name", {}),
    (sentinel_ds.list_consent, "sentinel_consent", "subject_name", {"purpose": "Marketing"}),
    (sentinel_ds.list_policies, "sentinel_policies", "title", {}),
    (sentinel_ds.list_training, "sentinel_training", "staff_name", {"title": "Induction"}),
]


def _seed_two(db, table, column, extra):
    """One row whose searched column holds 'Quartz 5% Ledger' and a decoy that a wildcard 5% would also hit."""
    ids = []
    for n, value in enumerate(("Quartz 5% Ledger", "Quartz 50 Ledger"), start=1):
        fixed = {k: v.format(n=n) if isinstance(v, str) else v for k, v in extra.items()}
        ids.append(_insert(db, table, **{column: value}, **fixed))
    return ids


@pytest.mark.parametrize("fn, table, column, extra", SENTINEL_LISTS,
                         ids=[entry[1] for entry in SENTINEL_LISTS])
def test_sentinel_list_search_ignores_case_and_treats_wildcards_literally(test_db, fn, table, column, extra):
    hit, decoy = _seed_two(test_db, table, column, extra)
    assert [r["id"] for r in fn(search="quartz 5% ledger")] == [hit]
    assert [r["id"] for r in fn(search="QUARTZ 5%")] == [hit], "a typed % is not a wildcard"
    assert {r["id"] for r in fn(search="quartz")} == {hit, decoy}


def test_erm_risk_statement_tag_search_ignores_case(test_db):
    hit = _insert(test_db, "erm_risk_statements", category="Cyber", cause="c", event="e", consequence="q",
                  tags="Cyber,Ransomware")
    _insert(test_db, "erm_risk_statements", category="Cyber", cause="c", event="e", consequence="q",
            tags="supply-chain")
    assert [r["id"] for r in erm_ds.list_statements(tags="ransomware")] == [hit]


def test_bcm_document_chunk_search_ignores_case(test_db):
    doc = _insert(test_db, "bcm_documents", title="Plan")
    hit = _insert(test_db, "bcm_document_chunks", document_id=doc, chunk_index=0, content="Quartz recovery steps")
    _insert(test_db, "bcm_document_chunks", document_id=doc, chunk_index=1, content="Unrelated text")
    assert [r["id"] for r in bcm_ds.search_chunks(["QUARTZ", "recovery"])] == [hit]


def _request(query=None):
    return types.SimpleNamespace(state=types.SimpleNamespace(user=ADMIN), url=types.SimpleNamespace(path="/x"),
                                 query_params=query or {})


def test_aria_document_list_search_ignores_case(test_db, monkeypatch):
    shown = {}
    monkeypatch.setattr(aria_routes, "_aria_render", lambda request, template, ctx, **kw: shown.update(ctx))
    # Legacy unmanaged documents (no organization) are visible to everyone.
    _insert(test_db, "aria_documents", doc_id="DOC-1", framework="ISO 27001", title="Quartz Access Policy",
            policy_workflow_managed=0)
    _insert(test_db, "aria_documents", doc_id="DOC-2", framework="ISO 27001", title="Backup Policy",
            policy_workflow_managed=0)
    asyncio.run(aria_routes.documents_page(_request(), search="quartz access"))
    assert [d["doc_id"] for d in shown["docs"]] == ["DOC-1"]


def test_aria_framework_control_search_ignores_case(test_db, monkeypatch):
    shown = {}
    monkeypatch.setattr(aria_routes, "_aria_render", lambda request, template, ctx, **kw: shown.update(ctx))
    fw = _insert(test_db, "frameworks", name="Search framework")
    _insert(test_db, "controls", framework_id=fw, ref="Q.1", name="Quartz key rotation")
    _insert(test_db, "controls", framework_id=fw, ref="Q.2", name="Password length")
    asyncio.run(aria_routes.framework_detail(_request(), fw, search="QUARTZ KEY"))
    assert [c["ref"] for c in shown["controls"]] == ["Q.1"]


def test_audit_log_filters_ignore_case(test_db):
    hit = _insert(test_db, "audit_log", username="Alice.Smith", action="Exported Quartz Report", module="platform")
    _insert(test_db, "audit_log", username="bob", action="Logged in", module="platform")
    for query in ({"action": "quartz report"}, {"user": "alice.smith"}):
        body = json.loads(asyncio.run(admin_routes.admin_api_logs(_request(query))).body)
        assert [row["id"] for row in body["logs"]] == [hit], query
