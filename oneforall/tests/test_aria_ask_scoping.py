"""
Ask ARIA: tenancy lives in the search index itself.

The index (aria_ask_index) is one table. The sources of its control and risk
chunks (controls, aria_risks) have no org column, so before scoping existed
nothing stopped one organization's control or risk text from reaching another
organization's prompt, and search() took the top k across everyone before the
document-only post-filter ran, so other tenants' documents crowded a user's own
out of the results. These tests pin the rule that the INDEX carries org_id and
business_unit_id and search() filters on them in SQL, before ranking and the
top-k cut:

  * another org's text never reaches the retrieved chunks, the prompt sent to
    the model, or the citations;
  * another org's chunks cannot crowd the asker's own out of the top k;
  * the SQL pre-filter admits exactly what policy_access.document_read_ok does;
  * the live-row document check still runs after the pre-filter;
  * an index built before scoping existed is upgraded.

Every exclusion assertion is paired with a positive one (the asker DOES get
their own content), so an empty result can never pass for isolation. A failed
query raises and ask() reports an outage; it used to be swallowed into an empty
result, which looked exactly like "no policy covers this".

PostgreSQL is not exercised here (no server in the test environment). Its query
assembly is covered with a recording stub; the PG DDL and upgrade statements
need a real PostgreSQL run before release.
"""
import asyncio
import json
import re
import sqlite3
import types

import pytest

from database import tenant_context
from modules.aria import ask_service
from modules.aria.policy_access import document_read_ok

ORG_A, ORG_B = 1, 2
BU_A, BU_A_OTHER, BU_A_CHILD, BU_B = 100, 101, 102, 200


# ── Seeding helpers ─────────────────────────────────────────────────────────

def _add_user(db, uid, name, org_id, bu_id, super_admin=0):
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, "
        "org_id, business_unit_id, is_super_admin) VALUES (%s,%s,%s,%s,'x',%s,%s,%s)",
        (uid, name, f"{name}@x.com", name, org_id, bu_id, super_admin),
    )
    db.commit()
    row = db.execute(
        "SELECT id, username, full_name, org_id, business_unit_id, "
        "COALESCE(is_super_admin,0) AS is_super_admin FROM users WHERE id=%s", (uid,),
    ).fetchone()
    actor = dict(row)
    actor["roles"] = []
    return actor


@pytest.fixture
def world(test_db):
    """Two organizations, one user each, an empty current-shape index."""
    for org_id in (ORG_A, ORG_B):
        test_db.execute(
            "INSERT INTO organizations (id, name, slug) VALUES (%s,%s,%s)",
            (org_id, f"org{org_id}", f"org-{org_id}"),
        )
    for bu_id, name, parent in ((BU_A, "A-Finance", None), (BU_A_OTHER, "A-Ops", None),
                                (BU_A_CHILD, "A-Finance-Audit", BU_A), (BU_B, "B-Treasury", None)):
        test_db.execute(
            "INSERT INTO business_units (id, name, parent_id, is_active) VALUES (%s,%s,%s,1)",
            (bu_id, name, parent),
        )
    test_db.commit()
    alice = _add_user(test_db, 1, "alice", ORG_A, BU_A)
    bob = _add_user(test_db, 2, "bob", ORG_B, BU_B)
    ask_service.init_index()
    return types.SimpleNamespace(db=test_db, alice=alice, bob=bob)


def _doc(db, doc_id, org_id, bu_id, body, framework="ISO 27001"):
    """A scoped, unmanaged document, indexed from its own source row."""
    db.execute(
        "INSERT INTO aria_documents (doc_id, framework, title, body, org_id, "
        "business_unit_id, policy_workflow_managed, status, owner) "
        "VALUES (%s,%s,%s,%s,%s,%s,0,'Approved','owner')",
        (doc_id, framework, f"Title {doc_id}", body, org_id, bu_id),
    )
    db.commit()
    ask_service.reindex_document(doc_id)


def _risk(db, risk_id, description, org_id):
    """aria_risks has no org column, so the indexing tenant is the only owner."""
    db.execute(
        "INSERT INTO aria_risks (risk_id, framework, description, category, owner, "
        "mitigation, status) VALUES (%s,'ISO 27001',%s,'Cyber','owner','Offline backups','Open')",
        (risk_id, description),
    )
    db.commit()
    if org_id is None:
        ask_service.reindex_risk(risk_id)
    else:
        with tenant_context(org_id, f"org-{org_id}"):
            ask_service.reindex_risk(risk_id)


def _control(db, ref, name, org_id):
    fw_id = db.execute("SELECT id FROM frameworks WHERE name='GDPR'").fetchone()["id"]
    db.execute(
        "INSERT INTO controls (framework_id, ref, name, description, category, owner) "
        "VALUES (%s,%s,%s,'Quarterly recovery drills','Resilience','owner')",
        (fw_id, ref, name),
    )
    db.commit()
    cid = db.execute(
        "SELECT id FROM controls WHERE framework_id=%s AND ref=%s", (fw_id, ref)
    ).fetchone()["id"]
    with tenant_context(org_id, f"org-{org_id}"):
        ask_service.reindex_control(cid)


# ── Model stub ──────────────────────────────────────────────────────────────

class _Model:
    """Replaces ask_service._call_ai. Records everything sent to the model and
    'cites' every title it was shown, so a leaked chunk surfaces in citations."""

    def __init__(self):
        self.calls = []

    async def __call__(self, system, user_msg, max_tokens=4000, messages=None):
        self.calls.append({"system": system, "user_msg": user_msg, "messages": messages})
        cites = [{"title": t, "content_type": "x"}
                 for t in re.findall(r"title=(.+?) \| section=", user_msg)]
        return "Stub answer.\n```json\n" + json.dumps(cites) + "\n```", {}


def _ask(monkeypatch, question, user, **kw):
    model = _Model()
    monkeypatch.setattr(ask_service, "_call_ai", model)
    result = asyncio.run(ask_service.ask(question, user=user, **kw))
    return result, model


def _sent(model):
    """Everything the model was given: system prompt, prompt, message history."""
    return "\n".join(
        str(c["system"]) + str(c["user_msg"]) + json.dumps(c["messages"]) for c in model.calls
    )


# ── Another org's text never reaches the prompt, citations or answer ────────

def test_asker_never_receives_the_other_orgs_risks_or_controls(world, monkeypatch):
    db = world.db
    _risk(db, "RISK-A1", "ALPHARISK ransomware could encrypt payment servers", ORG_A)
    _risk(db, "RISK-B1", "BRAVORISK ransomware could encrypt treasury systems", ORG_B)
    _control(db, "A.1", "ALPHACTL ransomware recovery drills", ORG_A)
    _control(db, "B.1", "BRAVOCTL ransomware recovery drills", ORG_B)

    for asker, own, other in (
        (world.alice, ("ALPHARISK", "ALPHACTL"), ("BRAVORISK", "BRAVOCTL", "RISK-B1")),
        (world.bob, ("BRAVORISK", "BRAVOCTL"), ("ALPHARISK", "ALPHACTL", "RISK-A1")),
    ):
        result, model = _ask(monkeypatch, "What is our ransomware risk?", asker)
        sent, returned = _sent(model), json.dumps(result)
        assert len(model.calls) == 1 and result["chunks_retrieved"] == 2
        for text in own:
            assert text in sent, f"{asker['username']} must still get their own {text}"
        for text in other:
            assert text not in sent, f"{text} leaked into the prompt sent to the model"
            assert text not in returned, f"{text} leaked into the answer or citations"


# ── Scope applies before the top-k cut ──────────────────────────────────────

def test_other_orgs_documents_cannot_crowd_out_the_askers_own(world, monkeypatch):
    db = world.db
    for i in range(10):
        _doc(db, f"DOC-B{i:02d}", ORG_B, BU_B, "backup backup backup backup restore backup BRAVODOC")
    _doc(db, "DOC-A01", ORG_A, BU_A,
         "This long policy covers training, onboarding, travel, visitors, parking and, "
         "once, backup procedures ALPHADOC " + " ".join(["filler"] * 120))

    # Precondition: this really is a crowd-out. Unscoped, org B fills the top 8.
    unscoped = db.execute(
        "SELECT content_id FROM aria_ask_index WHERE aria_ask_index MATCH 'backup*' "
        "ORDER BY bm25(aria_ask_index) LIMIT 8"
    ).fetchall()
    assert "DOC-A01" not in {r["content_id"] for r in unscoped}

    assert [c["content_id"] for c in ask_service.search("backup", user=world.alice)] == ["DOC-A01"]

    result, model = _ask(monkeypatch, "backup", world.alice)
    sent = _sent(model)
    assert result["covered"] and "ALPHADOC" in sent
    assert "BRAVODOC" not in sent and "BRAVODOC" not in json.dumps(result)


def test_framework_filter_fallback_stays_scoped(world):
    _doc(world.db, "DOC-B1", ORG_B, BU_B, "encryption standard BRAVODOC", framework="SOC 2")
    _doc(world.db, "DOC-A1", ORG_A, BU_A, "encryption standard ALPHADOC", framework="ISO 27001")
    # Only org B has a SOC 2 document, so for alice the filtered query is empty
    # and the search widens to every framework. It must stay inside her scope.
    chunks = ask_service.search("encryption", framework_filter="SOC 2", user=world.alice)
    assert [c["content_id"] for c in chunks] == ["DOC-A1"]


# ── The SQL pre-filter equals document_read_ok ──────────────────────────────

@pytest.mark.parametrize("who", ["alice", "bob", "super_admin", "no_bu", "no_org"])
def test_sql_scope_admits_exactly_what_document_read_ok_admits(world, who):
    db = world.db
    actors = {
        "alice": world.alice,
        "bob": world.bob,
        "super_admin": _add_user(db, 3, "root", ORG_A, None, super_admin=1),
        "no_bu": _add_user(db, 4, "nobu", ORG_A, None),
        "no_org": _add_user(db, 5, "noorg", None, None),
    }
    docs = [
        ("DOC-1", ORG_A, BU_A), ("DOC-2", ORG_A, BU_A_OTHER), ("DOC-3", ORG_A, None),
        ("DOC-4", ORG_B, BU_B), ("DOC-5", ORG_B, None), ("DOC-6", None, None),
        ("DOC-7", ORG_A, BU_A_CHILD),
    ]
    for doc_id, org_id, bu_id in docs:
        _doc(db, doc_id, org_id, bu_id, "zebra stripes")

    actor = actors[who]
    expected = set()
    for doc_id, _org, _bu in docs:
        live = dict(db.execute(
            "SELECT org_id, business_unit_id, policy_workflow_managed "
            "FROM aria_documents WHERE doc_id=%s", (doc_id,)).fetchone())
        if document_read_ok(actor, live):
            expected.add(doc_id)

    got = {c["content_id"] for c in ask_service.search("zebra", k=50, user=actor)}
    assert expected, "every persona can read at least the legacy document"
    assert got == expected


def test_live_document_row_is_still_checked_after_the_sql_pre_filter(world, monkeypatch):
    db = world.db
    _doc(db, "DOC-MOVED", ORG_A, BU_A, "quarterly ALPHAMOVED review")
    _doc(db, "DOC-GONE", ORG_A, BU_A, "quarterly ALPHAGONE review")
    _doc(db, "DOC-OK", ORG_A, BU_A, "quarterly ALPHAOK review")
    # The index stamps are now stale: one document moved to a unit outside
    # alice's scope, one was deleted. The index still admits both chunks.
    db.execute("UPDATE aria_documents SET business_unit_id=%s WHERE doc_id='DOC-MOVED'", (BU_A_OTHER,))
    db.execute("DELETE FROM aria_documents WHERE doc_id='DOC-GONE'")
    db.commit()
    assert {c["content_id"] for c in ask_service.search("quarterly", user=world.alice)} == {
        "DOC-MOVED", "DOC-GONE", "DOC-OK"}

    result, model = _ask(monkeypatch, "quarterly review", world.alice)
    sent = _sent(model)
    assert "ALPHAOK" in sent
    assert "ALPHAMOVED" not in sent and "ALPHAGONE" not in sent


def test_no_actor_gets_nothing_and_the_model_is_never_called(world, monkeypatch):
    _doc(world.db, "DOC-A1", ORG_A, BU_A, "backup procedures")
    assert ask_service.search("backup") == []
    assert ask_service.search("backup", user=None) == []
    result, model = _ask(monkeypatch, "backup", None)
    assert result["covered"] is False and result["chunks_retrieved"] == 0
    assert model.calls == []


# ── What gets stamped, and by whom ──────────────────────────────────────────

def test_documents_take_scope_from_the_source_and_controls_and_risks_from_the_tenant(world):
    db = world.db
    _doc(db, "DOC-SCOPED", ORG_A, BU_A, "stamp one")
    _doc(db, "DOC-LEGACY", None, None, "stamp two")
    _risk(db, "RISK-A1", "ALPHARISK stamp three", ORG_A)
    _risk(db, "RISK-UNBOUND", "UNBOUNDRISK stamp four", None)
    _control(db, "A.1", "ALPHACTL stamp five", ORG_A)

    stamps = {
        (r["content_type"], r["content_id"]): (r["org_id"], r["business_unit_id"])
        for r in db.execute("SELECT content_type, content_id, org_id, business_unit_id FROM aria_ask_index")
    }
    assert stamps[("document", "DOC-SCOPED")] == (ORG_A, BU_A)
    assert stamps[("document", "DOC-LEGACY")] == (None, None)
    assert stamps[("risk", "RISK-A1")] == (ORG_A, None)
    assert stamps[("risk", "RISK-UNBOUND")] == (None, None)
    assert [v for k, v in stamps.items() if k[0] == "control"] == [(ORG_A, None)]


def test_rebuild_all_stamps_what_it_indexes_for_the_rebuilding_tenant(world, monkeypatch):
    db = world.db
    db.execute(
        "INSERT INTO aria_risks (risk_id, framework, description, category, owner, mitigation, status) "
        "VALUES ('RISK-1','ISO 27001','SHAREDRISK ransomware exposure','Cyber','o','m','Open')")
    for doc_id, org_id, bu_id, mark in (("DOC-A", ORG_A, BU_A, "ALPHADOC"), ("DOC-B", ORG_B, BU_B, "BRAVODOC")):
        db.execute(
            "INSERT INTO aria_documents (doc_id, framework, title, body, org_id, business_unit_id, "
            "policy_workflow_managed, status, owner) VALUES (%s,'ISO 27001',%s,%s,%s,%s,0,'Approved','o')",
            (doc_id, doc_id, f"ransomware playbook {mark}", org_id, bu_id))
    db.commit()

    with tenant_context(ORG_A, "org-a"):
        assert ask_service.rebuild_all() == 3

    # Documents keep their own org. The risk table has no owner column, so the
    # tenant that ran the rebuild owns the chunk: org B does not get it.
    alice_sent = _sent(_ask(monkeypatch, "ransomware", world.alice)[1])
    assert "SHAREDRISK" in alice_sent and "ALPHADOC" in alice_sent and "BRAVODOC" not in alice_sent
    bob_sent = _sent(_ask(monkeypatch, "ransomware", world.bob)[1])
    assert "BRAVODOC" in bob_sent and "SHAREDRISK" not in bob_sent and "ALPHADOC" not in bob_sent


# ── Index shape and upgrade ─────────────────────────────────────────────────

def test_pre_scoping_sqlite_index_is_upgraded_and_rebuildable(test_db):
    test_db.executescript(
        "CREATE VIRTUAL TABLE aria_ask_index USING fts5(content_type, content_id, title, "
        "section, body, owner, framework, control_ref, url_path, tokenize = 'porter unicode61');"
    )
    test_db.execute(
        "INSERT INTO aria_ask_index (content_type, content_id, title, section, body, owner, "
        "framework, control_ref, url_path) VALUES ('risk','RISK-OLD','t','s','b','o','f','c','/u')"
    )
    test_db.commit()

    ask_service.init_index()
    cols = {r["name"] for r in test_db.execute("PRAGMA table_info(aria_ask_index)").fetchall()}
    assert {"org_id", "business_unit_id"} <= cols

    ask_service.init_index()  # idempotent once upgraded
    test_db.execute("INSERT INTO aria_risks (risk_id, framework, description) VALUES ('R1','ISO','rebuilt risk')")
    test_db.commit()
    assert ask_service.rebuild_index() == 1
    cols = {r["name"] for r in test_db.execute("PRAGMA table_info(aria_ask_index)").fetchall()}
    assert {"org_id", "business_unit_id"} <= cols


def test_both_index_ddls_declare_the_scope_columns():
    for ddl in (ask_service._FTS_DDL_SQLITE, ask_service._FTS_DDL_PG):
        assert "org_id" in ddl and "business_unit_id" in ddl


# ── PostgreSQL query assembly (no server available in tests) ────────────────

class _RecordingDb:
    def __init__(self, fail_first=False):
        self.calls, self.fail_first = [], fail_first

    def execute(self, sql, params=None):
        self.calls.append((sql, tuple(params or ())))
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("boom")
        return types.SimpleNamespace(fetchall=lambda: [])


def test_pg_queries_are_scoped_before_ranking_and_every_placeholder_has_a_param(world):
    scope_sql, scope_params = ask_service._scope_sql(world.alice)
    db = _RecordingDb()
    ask_service._search_pg(db, "alpha:*", 8, "ISO 27001", scope_sql, scope_params)

    assert len(db.calls) == 2, "framework-filtered query, then the unfiltered fallback"
    for sql, params in db.calls:
        assert sql.count("%s") == len(params)
        assert scope_sql in sql
        assert sql.index(scope_sql) < sql.index("ORDER BY") < sql.index("LIMIT")
        assert params[:2] == ("alpha:*", "alpha:*")
        assert params[2:2 + len(scope_params)] == tuple(scope_params)
        assert params[-1] == 8
    assert db.calls[0][1][-2] == "ISO 27001"


def test_pg_search_raises_on_a_failed_query_instead_of_running_the_fallback(world):
    """A failed filtered query is an outage: it propagates, and the wider fallback does not run."""
    scope_sql, scope_params = ask_service._scope_sql(world.alice)
    db = _RecordingDb(fail_first=True)
    with pytest.raises(RuntimeError):
        ask_service._search_pg(db, "alpha:*", 8, "ISO 27001", scope_sql, scope_params)
    assert len(db.calls) == 1


# ── A failed search is an outage, not "no policy covers this" ───────────────

def test_search_raises_when_the_query_fails(world):
    world.db.execute("DROP TABLE aria_ask_index")
    world.db.commit()
    with pytest.raises(sqlite3.OperationalError):
        ask_service.search("backup", user=world.alice)


def test_ask_reports_a_failed_search_as_an_outage_and_does_not_log_it_as_uncovered(world, monkeypatch):
    _doc(world.db, "DOC-A1", ORG_A, BU_A, "backup procedures")

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ask_service, "_search_sqlite", broken)
    result, model = _ask(monkeypatch, "backup", world.alice)

    assert result["success"] is False and result["covered"] is False
    assert "temporarily unavailable" in result["error"]
    assert result["log_id"] is None and model.calls == []
    assert world.db.execute("SELECT COUNT(*) FROM aria_ask_log").fetchone()[0] == 0


# ── scripts/rebuild_ask_index.py ────────────────────────────────────────────

def test_rebuild_script_rebuilds_the_one_sqlite_index_and_refuses_a_slug(world, capsys):
    from scripts import rebuild_ask_index

    _doc(world.db, "DOC-A1", ORG_A, BU_A, "script probe policy")
    world.db.execute("DELETE FROM aria_ask_index")
    world.db.commit()

    assert rebuild_ask_index.main([]) == 0
    assert capsys.readouterr().out.startswith("all: ")
    assert world.db.execute(
        "SELECT COUNT(*) FROM aria_ask_index WHERE content_id='DOC-A1'"
    ).fetchone()[0] == 1
    with pytest.raises(SystemExit) as refused:
        rebuild_ask_index.main(["--slug", "org-1"])
    assert refused.value.code == 2


def test_rebuild_script_keeps_going_after_one_tenant_fails_and_says_so(monkeypatch, capsys):
    from database import get_current_tenant
    from scripts import rebuild_ask_index

    monkeypatch.setattr(rebuild_ask_index.settings, "is_postgres", lambda: True)
    monkeypatch.setattr(rebuild_ask_index, "list_active_tenants", lambda: [(1, "alpha"), (2, "beta")])

    def rebuild_all():
        if get_current_tenant() == "alpha":
            raise RuntimeError("alpha is broken")
        return 7

    monkeypatch.setattr(rebuild_ask_index, "rebuild_all", rebuild_all)

    assert rebuild_ask_index.main([]) == 1
    printed = capsys.readouterr()
    assert printed.out.strip() == "beta: 7 chunks"
    assert "alpha: FAILED: alpha is broken" in printed.err
    assert rebuild_ask_index.main(["--slug", "gamma"]) == 2


# ── The Ask page header count ───────────────────────────────────────────────

def test_the_ask_page_counts_only_the_chunks_the_viewer_may_retrieve(world, monkeypatch):
    import core.middleware as middleware
    import modules.aria.routes as aria_routes

    _doc(world.db, "DOC-A1", ORG_A, BU_A, "alpha policy")
    _doc(world.db, "DOC-B1", ORG_B, BU_B, "bravo policy")
    _doc(world.db, "DOC-B2", ORG_B, BU_B, "bravo second policy")

    async def current_user(request):
        return request.state.user

    shown = {}
    monkeypatch.setattr(middleware, "get_current_user", current_user)
    monkeypatch.setattr(aria_routes, "_aria_render", lambda request, template, ctx, **kw: shown.update(ctx))

    for who, expected in ((world.alice, 1), (world.bob, 2)):
        user = {**who, "roles": ["employee"]}  # any role with ARIA access
        request = types.SimpleNamespace(state=types.SimpleNamespace(user=user),
                                        url=types.SimpleNamespace(path="/aria/ask"), query_params={})
        asyncio.run(aria_routes.ask_page(request))
        assert shown["total_indexed"] == expected, user["username"]
        assert ask_service.indexed_count(user) == expected
