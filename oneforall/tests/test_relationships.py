"""The relationship service: one registry of linkable records, one scope rule, one way to store a link.

What it must guarantee, written out by hand and not computed by the code under test:

* a record shows up as a related record only to someone who may open it in its owning module (capability and
  business unit), and nothing is said about one they may not open: no title, id or count;
* a link never grants access to its target, and an unknown record and a hidden one answer alike;
* typed verbs join only the kinds they were made for, an application edge needs the AI use link capability
  (or being the application's owner), and a candidate edge stays out of every list until it is confirmed;
* a change is audited by the caller after it commits, never by the service, and the service never commits.
"""
import asyncio
import json
import types

import pytest

import core.middleware as middleware
import modules.launcher.routes_platform as plat
from modules.governance import relationships
from modules.governance.entity_scope import canonical_key, describe_record, describe_records, linkable_keys
from tests.test_platform_ownership import PERSONAS, _call, _insert, _request, signed_in, world  # noqa: F401

APP, ASSET, PROCESS = ("governance", "application"), ("governance", "data_asset"), ("governance", "process")
AIIA, DPIA, AIMS = ("sentinel", "aiia"), ("sentinel", "dpia"), ("orm", "aims")
UNIT_TAGS = ("org", "A", "A1", "B")

# What each persona may open of unit-scoped rows: organization wide ones plus their own subtree.
SUBTREE = {"super": {"org", "A", "A1", "B"}, "dpo_a": {"org", "A", "A1"}, "dpo_a1": {"org", "A1"},
           "dpo_b": {"org", "B"}, "dpo_no_unit": {"org"}, "owner_a": {"org", "A", "A1"},
           "owner_b": {"org", "B"}, "employee_a": {"org", "A", "A1"}}
# Capabilities from core/rbac.py: governance.entities.view is every role; Sentinel access is the DPO and the
# administrator; ORM access is the risk owner and the administrator; the AI impact assessment (ai_assessment.view,
# owned by AI Governance since G3b) is the privacy team and the people who review AI uses, so a risk owner opens it.
OPENS = {
    "governance": {"super", "dpo_a", "dpo_a1", "dpo_b", "dpo_no_unit", "owner_a", "owner_b", "employee_a"},
    "sentinel": {"super", "dpo_a", "dpo_a1", "dpo_b", "dpo_no_unit"},
    "orm": {"super", "owner_a", "owner_b"},
    "ai_assessment": {"super", "dpo_a", "dpo_a1", "dpo_b", "dpo_no_unit", "owner_a", "owner_b"},
}


@pytest.fixture
def graph(world):
    """One application, data asset, process, AIIA, AIMS assessment and AI control per unit tag."""
    db, unit = world.db, world.unit
    world.rec2 = {}
    for tag in UNIT_TAGS:
        owner = world.users["owner_a"]["id"] if tag == "A" else None
        world.rec2[(APP, tag)] = _insert(db, "applications", name=f"needle app {tag}", business_unit_id=unit[tag],
                                         owner_user_id=owner)
        world.rec2[(ASSET, tag)] = _insert(db, "data_assets", name=f"needle asset {tag}", business_unit_id=unit[tag])
        world.rec2[(PROCESS, tag)] = _insert(db, "business_processes", name=f"needle process {tag}",
                                             business_unit_id=unit[tag])
        world.rec2[(AIIA, tag)] = _insert(db, "sentinel_aiia", ref_number=f"AIIA-{tag}", title=f"needle aiia {tag}",
                                          business_unit_id=unit[tag])
        world.rec2[(DPIA, tag)] = _insert(db, "sentinel_dpias", ref_number=f"DPIA-{tag}", title=f"needle dpia {tag}",
                                          business_unit_id=unit[tag])
        world.rec2[(AIMS, tag)] = _insert(db, "aims_assessments", ref=f"AIMS-{tag}", title=f"needle aims {tag}",
                                          business_unit_id=unit[tag])
        world.rec2[(("orm", "ai_control"), tag)] = _insert(
            db, "ai_control_catalogue", ref=f"AC-{tag}", title=f"needle ai control {tag}", business_unit_id=unit[tag])
    world.rec2[(("sentinel", "vendor"), "all")] = _insert(db, "sentinel_vendors", name="needle vendor")
    return world


def _kind_rows(graph, kind):
    return {tag: graph.rec2[(kind, tag)] for tag in UNIT_TAGS}


# ── The registry and the describe helpers ───────────────────────────────────

def test_every_linkable_kind_has_a_title_a_table_and_a_deep_link():
    from modules.governance.entity_scope import _KINDS
    keys = linkable_keys()
    assert len(keys) >= 30
    for key in keys:
        kind = _KINDS[key]
        assert kind.table and kind.title and kind.url.startswith("/"), key


def test_the_grid_non_conformance_spelling_is_the_same_kind():
    assert canonical_key("grid", "non_conformance") == ("grid", "nc") == canonical_key(" GRID ", "NC")
    assert canonical_key("nowhere", "thing") == ("nowhere", "thing")


@pytest.mark.parametrize("name", list(SUBTREE))
@pytest.mark.parametrize("kind, module", [(APP, "governance"), (ASSET, "governance"), (PROCESS, "governance"),
                                          (AIIA, "ai_assessment"), (AIMS, "orm"), (("orm", "ai_control"), "orm")])
def test_describe_returns_exactly_the_records_the_persona_may_open(graph, name, kind, module):
    rows = _kind_rows(graph, kind)
    found = describe_records(graph.db, kind, list(rows.values()), graph.users[name])
    expected_tags = SUBTREE[name] if name in OPENS[module] else set()
    assert set(found) == {rows[tag] for tag in expected_tags}, (name, kind)
    for tag in expected_tags:
        assert found[rows[tag]]["title"].startswith("needle"), (name, kind, tag)


def test_describe_gives_a_deep_link_and_never_an_error_for_bad_input(graph):
    app = graph.rec2[(APP, "org")]
    shown = describe_record(graph.db, APP, app, graph.users["super"])
    assert shown == {"title": "needle app org", "url": f"/ai-governance/systems/{app}"}
    assert describe_record(graph.db, APP, 987654, graph.users["super"]) is None
    assert describe_records(graph.db, APP, ["x", None, -1, 0, 2 ** 40], graph.users["super"]) == {}
    assert describe_records(graph.db, ("nowhere", "thing"), [1], graph.users["super"]) == {}
    assert describe_records(graph.db, ("platform", "task"), [1], graph.users["super"]) == {}


def test_a_policy_link_carries_the_policy_reference_url_encoded(world):
    doc = _insert(world.db, "aria_documents", doc_id="DOC 1/A", title="Policy", framework="ISO 27001", org_id=1,
                  business_unit_id=world.unit["A"], policy_workflow_managed=0)
    shown = describe_record(world.db, ("aria", "document"), doc, world.users["super"])
    assert shown["url"] == "/aria/documents?open=DOC%201%2FA"


# ── Creating, listing and removing links ────────────────────────────────────

def _link(graph, user, source, target, verb="related", **kw):
    """create_link, committed the way a route does it. Returns (result or None, error or None)."""
    try:
        result = relationships.create_link(graph.db, user, source, target, verb, **kw)
    except relationships.LinkError as error:
        graph.db.rollback()
        return None, error
    graph.db.commit()
    return result, None


def _ref(graph, kind, tag):
    return (*kind, graph.rec2[(kind, tag)])


def test_a_visible_pair_links_once_and_each_side_reads_the_right_label(graph):
    user = graph.users["dpo_a"]
    aiia, app = _ref(graph, AIIA, "A"), _ref(graph, APP, "A")
    made, error = _link(graph, user, aiia, app, "assesses")
    assert error is None and made["created"] and made["audit"][0] == "link_create"
    again, _ = _link(graph, user, aiia, app, "assesses")
    assert again["link_id"] == made["link_id"] and not again["created"] and again["audit"] is None

    from_aiia = relationships.list_links(graph.db, user, AIIA, aiia[2])
    from_app = relationships.list_links(graph.db, user, APP, app[2])
    assert [(l["label"], l["direction"], l["title"]) for l in from_aiia] == [("assesses", "outgoing", "needle app A")]
    assert [(l["label"], l["direction"], l["title"]) for l in from_app] == [("assessed by", "incoming", "needle aiia A")]
    assert from_app[0]["provenance"] == "manual" and from_app[0]["status"] == "confirmed"
    assert from_app[0]["url"] == f"/ai-governance/assessments/{aiia[2]}"


def test_an_unknown_record_and_a_hidden_one_get_the_same_refusal(graph):
    user = graph.users["dpo_a"]
    app = _ref(graph, APP, "A")
    hidden_b = _ref(graph, AIIA, "B")
    missing = (*AIIA, 987654)
    refused = [_link(graph, user, hidden_b, app, "assesses")[1], _link(graph, user, missing, app, "assesses")[1],
               _link(graph, user, app, hidden_b, "related")[1], _link(graph, user, app, missing, "related")[1]]
    assert {(e.status, e.message) for e in refused} == {(404, "Entity not found.")}
    assert graph.db.execute("SELECT COUNT(*) FROM cross_module_links").fetchone()[0] == 0


def test_the_other_end_and_the_record_itself_are_left_out_for_someone_who_cannot_open_them(graph):
    admin, dpo_a, dpo_b = graph.users["super"], graph.users["dpo_a"], graph.users["dpo_b"]
    app_a, app_b = _ref(graph, APP, "A"), _ref(graph, APP, "B")
    aiia_a = _ref(graph, AIIA, "A")
    assert _link(graph, admin, aiia_a, app_a, "assesses")[1] is None
    assert _link(graph, admin, _ref(graph, AIIA, "B"), app_a, "assesses")[1] is None   # unit B's AIIA on A's app
    seen_by_a = relationships.list_links(graph.db, dpo_a, APP, app_a[2])
    assert [l["title"] for l in seen_by_a] == ["needle aiia A"], "unit B's AIIA is not mentioned to unit A"
    assert relationships.list_links(graph.db, dpo_b, APP, app_a[2]) == [], "unit B may not open unit A's app"
    assert relationships.list_links(graph.db, dpo_b, APP, app_b[2]) == []
    assert relationships.list_links(graph.db, dpo_a, APP, 987654) == []
    assert relationships.list_links(graph.db, dpo_a, ("nowhere", "thing"), 1) == []


def test_typed_verbs_join_only_the_kinds_they_were_made_for(graph):
    admin = graph.users["super"]
    app, asset, process = _ref(graph, APP, "org"), _ref(graph, ASSET, "org"), _ref(graph, PROCESS, "org")
    aiia, dpia, aims = _ref(graph, AIIA, "org"), _ref(graph, DPIA, "org"), _ref(graph, AIMS, "org")
    vendor = (*("sentinel", "vendor"), graph.rec2[(("sentinel", "vendor"), "all")])
    for source, target, verb in ((app, asset, "uses_data"), (app, vendor, "provided_by"), (app, process, "supports"),
                                 (aiia, app, "assesses"), (dpia, app, "assesses"), (aims, app, "covers")):
        made, error = _link(graph, admin, source, target, verb)
        assert error is None, (verb, error and error.message)
    for source, target, verb in ((asset, app, "uses_data"), (aiia, asset, "assesses"), (aims, app, "assesses"),
                                 (app, aims, "covers"), (process, vendor, "provided_by")):
        error = _link(graph, admin, source, target, verb)[1]
        assert error is not None and error.status == 400, (verb, source, target)
    assert _link(graph, admin, app, process, "no_such_verb")[1].message == "Unknown relationship"
    assert _link(graph, admin, app, app, "depends_on")[1].message == "Cannot link an entity to itself."


def test_an_application_edge_needs_the_ai_use_link_capability_or_ownership(graph):
    app_a = _ref(graph, APP, "A")            # owned by owner_a
    asset_a = _ref(graph, ASSET, "A")
    for name, allowed in (("employee_a", False), ("dpo_a", True), ("owner_a", True), ("owner_b", False)):
        made, error = _link(graph, graph.users[name], app_a, asset_a, "uses_data")
        if name == "owner_b":
            assert error.status == 404, "owner_b cannot even open unit A's application"
            continue
        assert (error is None) is allowed, name
        if error:
            assert (error.status, error.message) == (403, "Access denied.")
        if made:
            relationships.remove_link(graph.db, graph.users["super"], made["link_id"])
            graph.db.commit()


def test_a_candidate_edge_stays_out_of_every_list_until_it_is_confirmed(graph):
    reviewer, other = graph.users["dpo_a"], graph.users["dpo_a1"]
    aiia, app = _ref(graph, AIIA, "A1"), _ref(graph, APP, "A1")
    made, _ = _link(graph, reviewer, aiia, app, "assesses", provenance="system_candidate")
    row = graph.db.execute("SELECT status, confirmed_by, provenance FROM cross_module_links WHERE id = %s",
                           (made["link_id"],)).fetchone()
    assert tuple(row) == ("candidate", None, "system_candidate")
    assert relationships.list_links(graph.db, reviewer, APP, app[2]) == []
    shown = relationships.list_links(graph.db, reviewer, APP, app[2], include_candidates=True)
    assert [l["status"] for l in shown] == ["candidate"]

    relationships.set_link_status(graph.db, other, made["link_id"], "confirmed")
    graph.db.commit()
    assert [l["status"] for l in relationships.list_links(graph.db, reviewer, APP, app[2])] == ["confirmed"]
    confirmed = graph.db.execute("SELECT confirmed_by FROM cross_module_links WHERE id = %s", (made["link_id"],)).fetchone()
    assert confirmed[0] == other["id"]

    relationships.set_link_status(graph.db, reviewer, made["link_id"], "rejected")
    graph.db.commit()
    assert relationships.list_links(graph.db, reviewer, APP, app[2], include_candidates=True) == []
    revived, _ = _link(graph, reviewer, aiia, app, "assesses")
    assert revived["link_id"] == made["link_id"] and revived["created"], "a person linking a rejected edge confirms it"
    with pytest.raises(relationships.LinkError):
        relationships.set_link_status(graph.db, reviewer, made["link_id"], "maybe")


def test_a_link_made_before_provenance_was_recorded_still_shows_as_confirmed_legacy(graph):
    a, b = graph.rec2[(APP, "org")], graph.rec2[(ASSET, "org")]
    _insert(graph.db, "cross_module_links", source_module="governance", source_type="application", source_id=a,
            target_module="governance", target_type="data_asset", target_id=b, relationship="related")
    shown = relationships.list_links(graph.db, graph.users["employee_a"], APP, a)
    assert [(l["provenance"], l["status"]) for l in shown] == [("legacy", "confirmed")]


def test_links_stored_under_the_other_spelling_of_a_kind_are_found(graph):
    nc = _insert(graph.db, "grid_non_conformances", audit_id=_insert(graph.db, "grid_audits", name="Audit org"),
                 title="needle nc")
    app = graph.rec2[(APP, "org")]
    _insert(graph.db, "cross_module_links", source_module="grid", source_type="non_conformance", source_id=nc,
            target_module="governance", target_type="application", target_id=app, relationship="affects")
    admin = graph.users["super"]
    assert [l["title"] for l in relationships.list_links(graph.db, admin, ("grid", "nc"), nc)] == ["needle app org"]
    assert [l["title"] for l in relationships.list_links(graph.db, admin, APP, app)] == ["needle nc"]


def test_removing_a_link_is_for_its_maker_an_administrator_or_an_application_edge_reviewer(graph):
    maker, stranger, admin = graph.users["dpo_a"], graph.users["employee_a"], graph.users["super"]
    app, process = _ref(graph, APP, "A"), _ref(graph, PROCESS, "A")
    made, _ = _link(graph, maker, app, process, "supports")
    with pytest.raises(relationships.LinkError) as refused:
        relationships.remove_link(graph.db, stranger, made["link_id"])
    assert refused.value.status == 403
    with pytest.raises(relationships.LinkError) as hidden:
        relationships.remove_link(graph.db, graph.users["dpo_b"], made["link_id"])
    assert (hidden.value.status, hidden.value.message) == (404, "Link not found."), "unit B cannot tell it exists"
    reviewer_removes = relationships.remove_link(graph.db, graph.users["owner_a"], made["link_id"])
    assert reviewer_removes["audit"][0] == "link_delete"
    graph.db.commit()
    assert graph.db.execute("SELECT COUNT(*) FROM cross_module_links").fetchone()[0] == 0
    with pytest.raises(relationships.LinkError):
        relationships.remove_link(graph.db, admin, made["link_id"])


def test_the_service_never_commits_and_audit_is_the_callers_to_write_after_the_commit(graph):
    user = graph.users["dpo_a"]
    result = relationships.create_link(graph.db, user, _ref(graph, AIIA, "A"), _ref(graph, APP, "A"), "assesses")
    graph.db.rollback()
    assert graph.db.execute("SELECT COUNT(*) FROM cross_module_links").fetchone()[0] == 0
    assert graph.db.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'link_create'").fetchone()[0] == 0
    relationships.audit(user, result)   # a rolled back change would not reach here; this is the committed path
    assert graph.db.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'link_create'").fetchone()[0] == 1
    relationships.audit(user, None)
    relationships.audit(user, {"audit": None})


# ── The bounded neighbourhood ───────────────────────────────────────────────

def test_a_neighbourhood_is_bounded_and_never_steps_through_a_hidden_record(graph):
    admin, dpo_a = graph.users["super"], graph.users["dpo_a"]
    app, asset, process = _ref(graph, APP, "A"), _ref(graph, ASSET, "A"), _ref(graph, PROCESS, "A")
    hidden_asset = _ref(graph, ASSET, "B")
    far = _ref(graph, PROCESS, "org")
    _link(graph, admin, app, asset, "uses_data")
    _link(graph, admin, app, hidden_asset, "uses_data")
    _link(graph, admin, hidden_asset, far, "related")   # reachable only THROUGH unit B's asset
    _link(graph, admin, asset, process, "related")
    one = relationships.neighbours(graph.db, dpo_a, APP, app[2], depth=1)
    assert {n["title"] for n in one["nodes"]} == {"needle app A", "needle asset A"}
    two = relationships.neighbours(graph.db, dpo_a, APP, app[2], depth=2)
    assert {n["title"] for n in two["nodes"]} == {"needle app A", "needle asset A", "needle process A"}
    assert "needle asset B" not in json.dumps(two) and "needle process org" not in json.dumps(two)
    assert len(two["edges"]) == 2
    everything = relationships.neighbours(graph.db, admin, APP, app[2], depth=9)
    assert {n["title"] for n in everything["nodes"]} >= {"needle process org"}
    capped = relationships.neighbours(graph.db, admin, APP, app[2], depth=3, limit=2)
    assert len(capped["nodes"]) == 2 and capped["truncated"]
    assert relationships.neighbours(graph.db, graph.users["dpo_b"], APP, app[2]) == {
        "nodes": [], "edges": [], "truncated": False}


# ── Through the routes ──────────────────────────────────────────────────────

@pytest.fixture
def http(graph, monkeypatch):
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from modules.launcher.routes import router as launcher_router

    who = {"name": "dpo_a"}

    async def current_user(request):
        return graph.users[who["name"]]

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    app = FastAPI()
    app.include_router(launcher_router)
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False)

    def call(method, path, name="dpo_a", **kwargs):
        who["name"] = name
        return getattr(client, method)(path, **kwargs)

    return call


def test_the_routes_create_list_graph_confirm_and_remove_with_the_right_codes(graph, http):
    app, aiia = graph.rec2[(APP, "A")], graph.rec2[(AIIA, "A")]
    body = {"source_module": "sentinel", "source_type": "aiia", "source_id": aiia,
            "target_module": "governance", "target_type": "application", "target_id": app, "relationship": "assesses"}
    created = http("post", "/api/links", json=body)
    assert created.status_code == 201
    link_id = created.json()["link_id"]
    assert http("post", "/api/links", json=body).status_code == 200

    listed = http("get", f"/api/links/governance/application/{app}").json()
    assert [(l["label"], l["title"], l["provenance"]) for l in listed] == [("assessed by", "needle aiia A", "manual")]
    graph_view = http("get", f"/api/links/governance/application/{app}/graph?depth=1").json()
    assert {n["title"] for n in graph_view["nodes"]} == {"needle app A", "needle aiia A"}
    assert http("get", f"/api/links/governance/application/{app}", name="dpo_b").json() == []

    wrong_pair = dict(body, source_module="sentinel", source_type="dsr", source_id=1)
    assert http("post", "/api/links", json=wrong_pair).status_code == 404       # not a record they may open
    assert http("post", "/api/links", json=dict(body, relationship="assesses", target_id=987654)).status_code == 404
    assert http("post", "/api/links", json=dict(body, source_type="nothing")).status_code == 400
    assert http("post", f"/api/links/{link_id}/status", json={"status": "rejected"}).status_code == 200
    assert http("get", f"/api/links/governance/application/{app}").json() == []
    assert http("delete", f"/api/links/{link_id}", name="employee_a").status_code == 404   # cannot open the AIIA
    assert http("delete", f"/api/links/{link_id}").status_code == 200
    actions = [r[0] for r in graph.db.execute("SELECT action FROM audit_log WHERE action LIKE 'link_%' ORDER BY id").fetchall()]
    assert actions == ["link_create", "link_rejected", "link_delete"]
