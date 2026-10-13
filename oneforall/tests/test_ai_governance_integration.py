"""
AI governance G2: the existing modules an AI use is built on.

* Governance applications, data assets and business processes are read, changed and deleted only inside the caller's
  business unit (they used to be listed in full for every role, and changed or deleted by id from any unit);
* an application with an AI profile, an assessment, a request or a link is retired, never deleted, and an edit that does
  not mention the active flag no longer brings a retired one back;
* the Evidence Vault can attach proof to an application, and the proof shows on that application's Evidence tab;
* a business unit that still has AI use requests is not deleted.
"""
import json

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.middleware as middleware
from modules.ai_governance import service, workspace
from modules.ai_governance.routes import router as ai_router
from modules.evidence.routes import router as evidence_router
from modules.governance import data_service as governance_ds
from modules.governance.routes import router as governance_router
from tests.test_platform_ownership import PERSONAS, _insert, world  # noqa: F401


@pytest.fixture
def http(world, monkeypatch):
    who = {"name": "dpo_a"}

    async def current_user(request):
        return world.users[who["name"]]

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    app = FastAPI()
    app.include_router(governance_router)
    app.include_router(evidence_router)
    app.include_router(ai_router)
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False, follow_redirects=False)

    def call(method, path, name="dpo_a", **kwargs):
        who["name"] = name
        return getattr(client, method)(path, **kwargs)

    call.world = world
    return call


def _records(world):
    ids = {}
    for tag in ("A", "B"):
        ids[("app", tag)] = _insert(world.db, "applications", name=f"App {tag}", business_unit_id=world.unit[tag], is_active=1)
        ids[("asset", tag)] = _insert(world.db, "data_assets", name=f"Asset {tag}", business_unit_id=world.unit[tag], is_active=1)
        ids[("process", tag)] = _insert(world.db, "business_processes", name=f"Process {tag}", business_unit_id=world.unit[tag], is_active=1)
    ids[("app", "org")] = _insert(world.db, "applications", name="App org", business_unit_id=None, is_active=1)
    return ids


# GOVERNANCE_MANAGE is held by the compliance manager, GRC officer, risk owner, org admin and super admin; the personas
# here that hold it are owner_a / owner_b (risk owners) and super.

@pytest.mark.parametrize("kind, path, mine, theirs", [
    ("app", "/governance/api/applications", "App A", "App B"),
    ("asset", "/governance/api/data-assets", "Asset A", "Asset B"),
    ("process", "/governance/api/business-processes", "Process A", "Process B")])
def test_the_lists_hold_only_the_callers_unit_and_the_organization_wide_records(http, kind, path, mine, theirs):
    _records(http.world)
    http.world.db.commit()
    names = {r["name"] for r in http("get", path, name="employee_a").json()}
    assert mine in names and theirs not in names
    assert theirs in {r["name"] for r in http("get", path, name="owner_b").json()}, "and unit B's own people do see it"
    everything = {r["name"] for r in http("get", path, name="super").json()}
    assert {mine, theirs} <= everything
    assert http("get", f"{path}?bu_id={http.world.unit['B']}", name="employee_a").json() == [], "asking for another unit is not a way in"


def test_an_application_in_another_unit_cannot_be_changed_or_deleted_by_id(http):
    world = http.world
    ids = _records(world)
    world.db.commit()
    body = {"name": "Renamed", "business_unit_id": world.unit["B"]}
    assert http("put", f"/governance/api/applications/{ids[('app', 'B')]}", name="owner_a", json=body).status_code == 404
    assert http("delete", f"/governance/api/applications/{ids[('app', 'B')]}", name="owner_a").status_code == 404
    assert world.db.execute("SELECT name FROM applications WHERE id = %s", (ids[("app", "B")],)).fetchone()[0] == "App B"
    assert http("put", f"/governance/api/applications/{ids[('app', 'A')]}", name="owner_a", json={"name": "Renamed A"}).status_code == 200
    for kind, path in (("asset", "data-assets"), ("process", "business-processes")):
        assert http("put", f"/governance/api/{path}/{ids[(kind, 'B')]}", name="owner_a", json={"name": "x"}).status_code == 404, kind
        assert http("delete", f"/governance/api/{path}/{ids[(kind, 'B')]}", name="owner_a").status_code == 404, kind


def test_a_record_cannot_be_filed_or_moved_into_a_unit_the_caller_does_not_belong_to(http):
    world = http.world
    ids = _records(world)
    world.db.commit()
    assert http("post", "/governance/api/applications", name="owner_a", json={"name": "New", "business_unit_id": world.unit["B"]}).status_code == 400
    assert http("put", f"/governance/api/applications/{ids[('app', 'A')]}", name="owner_a", json={"name": "x", "business_unit_id": world.unit["B"]}).status_code == 400
    assert http("post", "/governance/api/applications", name="owner_a", json={"name": "New", "business_unit_id": world.unit["A1"]}).status_code == 201
    assert http("post", "/governance/api/data-assets", name="owner_a", json={"name": "New", "business_unit_id": world.unit["B"]}).status_code == 400
    assert http("post", "/governance/api/business-processes", name="owner_a", json={"name": "New", "business_unit_id": world.unit["B"]}).status_code == 400


# ── Retire, never delete ────────────────────────────────────────────────────

def test_an_application_with_ai_records_is_refused_a_delete_and_told_to_retire_it(http):
    world = http.world
    app = _insert(world.db, "applications", name="Has history", business_unit_id=world.unit["A"], is_active=1)
    world.db.commit()
    assert http("delete", f"/governance/api/applications/{app}", name="owner_a").status_code == 200, "nothing points at it: it can go"
    for reason, make in (
        ("an AI profile", lambda a: service.create_profile(world.db, world.users["super"], a, {})),
        ("AI impact assessments", lambda a: _insert(world.db, "sentinel_aiia", ref_number="AIIA-X", title="X", application_id=a)),
        ("AI management assessments", lambda a: _insert(world.db, "aims_assessments", ref="AIMS-X", title="X", application_id=a)),
        ("data assets", lambda a: _insert(world.db, "data_assets", name="D", application_id=a)),
        ("related items", lambda a: _insert(world.db, "cross_module_links", source_module="governance", source_type="application",
                                           source_id=a, target_module="governance", target_type="process", target_id=1)),
    ):
        target = _insert(world.db, "applications", name=f"Held by {reason}", business_unit_id=world.unit["A"], is_active=1)
        make(target)
        world.db.commit()
        refused = http("delete", f"/governance/api/applications/{target}", name="owner_a")
        assert refused.status_code == 409 and reason in refused.json()["detail"] and "Retire it instead" in refused.json()["detail"]
        assert world.db.execute("SELECT COUNT(*) FROM applications WHERE id = %s", (target,)).fetchone()[0] == 1


def test_a_request_that_became_an_application_also_keeps_it_from_being_deleted(http):
    world = http.world
    row = service.create_draft(world.db, world.users["employee_a"], {
        "name": "From a request", "purpose": "p", "deployment": "internal_build", "data_categories": ["public"], "intended_users": "all"})["intake"]
    world.db.commit()
    service.submit(world.db, world.users["employee_a"], row["id"], 1)
    world.db.commit()
    done = service.approve(world.db, world.users["dpo_a"], row["id"], 2, new_application={})
    world.db.commit()
    assert http("delete", f"/governance/api/applications/{done['application_id']}", name="owner_a").status_code == 409


def test_an_edit_that_does_not_mention_the_active_flag_leaves_a_retired_application_retired(http):
    world = http.world
    app = _insert(world.db, "applications", name="Old", business_unit_id=world.unit["A"], is_active=1)
    service.create_profile(world.db, world.users["super"], app, {})
    service.retire(world.db, world.users["dpo_a"], app, "Contract ended.")
    world.db.commit()
    assert http("put", f"/governance/api/applications/{app}", name="owner_a", json={"name": "Old, renamed"}).status_code == 200
    row = world.db.execute("SELECT name, is_active, retired_reason FROM applications WHERE id = %s", (app,)).fetchone()
    assert (row["name"], row["is_active"], row["retired_reason"]) == ("Old, renamed", 0, "Contract ended.")


def test_flipping_the_flag_from_governance_keeps_the_retirement_record_true(http):
    world = http.world
    app = _insert(world.db, "applications", name="Flip", business_unit_id=world.unit["A"], is_active=1)
    world.db.commit()
    http("put", f"/governance/api/applications/{app}", name="owner_a", json={"name": "Flip", "is_active": 0})
    row = world.db.execute("SELECT is_active, retired_reason, retired_at FROM applications WHERE id = %s", (app,)).fetchone()
    assert row["is_active"] == 0 and row["retired_reason"] and row["retired_at"]
    http("put", f"/governance/api/applications/{app}", name="owner_a", json={"name": "Flip", "is_active": 1})
    row = world.db.execute("SELECT is_active, retired_reason, retired_at, retired_by FROM applications WHERE id = %s", (app,)).fetchone()
    assert (row["is_active"], row["retired_reason"], row["retired_at"], row["retired_by"]) == (1, None, None, None)


def test_a_business_unit_with_ai_requests_is_deactivated_not_deleted(world):
    row = service.create_draft(world.db, world.users["employee_a"], {"name": "x"})["intake"]
    world.db.commit()
    assert row["business_unit_id"] == world.unit["A"]
    assert governance_ds.delete_business_unit(world.unit["A"]) is False


# ── Proof attached in the Vault shows on the application ────────────────────

def test_evidence_attached_to_an_application_in_the_vault_shows_on_its_evidence_tab(http):
    world = http.world
    app = _insert(world.db, "applications", name="Chat assistant", business_unit_id=world.unit["A"], is_active=1)
    hidden = _insert(world.db, "applications", name="Unit B assistant", business_unit_id=world.unit["B"], is_active=1)
    service.create_profile(world.db, world.users["super"], app, {})
    item = _insert(world.db, "evidence_items", title="Vendor penetration test", status="current", org_id=1, business_unit_id=world.unit["A"])
    world.db.commit()
    attached = http("post", f"/evidence/api/items/{item}/links", name="dpo_a",
                    json={"module": "governance", "entity_type": "application", "entity_id": app})
    assert attached.status_code == 201, attached.text
    refused = http("post", f"/evidence/api/items/{item}/links", name="dpo_a",
                   json={"module": "governance", "entity_type": "application", "entity_id": hidden})
    assert refused.status_code == 404, "an application the person cannot open is not a link target"
    tab = workspace.get_tab(world.db, world.users["dpo_a"], app, "evidence")
    assert [i["title"] for i in tab["sections"][0]["items"]] == ["Vendor penetration test"]
    specs = json.dumps([{"module": "governance", "entity_type": "application", "entity_id": app},
                        {"module": "governance", "entity_type": "application", "entity_id": hidden}])
    resolved = http("get", "/evidence/api/resolve-links", name="dpo_a", params={"evidence_id": item, "links": specs})
    assert resolved.status_code == 200
    by_id = {r["entity_id"]: r for r in resolved.json()}
    assert (by_id[app]["name"], by_id[app]["url"]) == ("Chat assistant", f"/ai-governance/systems/{app}")
    assert (by_id[hidden]["name"], by_id[hidden]["url"]) == (None, None), "a hidden application gives no title"


# ── "Uses AI or embedded AI?" on a vendor and a process ─────────────────────

def test_a_vendor_or_process_said_to_use_ai_reaches_the_reviewers_until_a_use_covers_it(http):
    world = http.world
    vendor = _insert(world.db, "canonical_vendors", name="Acme Cloud")
    other = _insert(world.db, "canonical_vendors", name="Quiet Co")
    process = _insert(world.db, "business_processes", name="Claims triage", business_unit_id=world.unit["A"], is_active=1)
    hidden = _insert(world.db, "business_processes", name="Unit B triage", business_unit_id=world.unit["B"], is_active=1)
    world.db.commit()
    assert http("put", f"/ai-governance/api/flags/vendor/{vendor}", name="employee_a", json={"answer": "yes"}).status_code == 403
    assert http("put", f"/ai-governance/api/flags/vendor/{vendor}", name="dpo_a", json={"answer": "maybe"}).status_code == 422
    assert http("put", f"/ai-governance/api/flags/vendor/{vendor}", name="dpo_a", json={"answer": "yes", "note": "Chat assistant"}).status_code == 200
    assert http("put", f"/ai-governance/api/flags/vendor/{other}", name="dpo_a", json={"answer": "no"}).status_code == 200
    assert http("put", f"/ai-governance/api/flags/process/{process}", name="owner_a", json={"answer": "unknown"}).status_code == 200
    assert http("put", f"/ai-governance/api/flags/process/{hidden}", name="owner_a", json={"answer": "yes"}).status_code == 404
    assert http("put", "/ai-governance/api/flags/vendor/987654", name="dpo_a", json={"answer": "yes"}).status_code == 404
    assert http("put", f"/ai-governance/api/flags/team/{process}", name="dpo_a", json={"answer": "yes"}).status_code == 404

    queue = http("get", "/ai-governance/api/flags", name="dpo_a").json()["items"]
    assert [(i["kind"], i["name"], i["answer"]) for i in queue] == [("vendor", "Acme Cloud", "yes"), ("process", "Claims triage", "unknown")]
    assert queue[0]["register_url"] == "/ai-governance/register?source=vendor:%d&name=Acme%%20Cloud" % vendor
    assert http("get", "/ai-governance/api/flags", name="employee_a").status_code == 403

    # an AI use that names the vendor takes it off the list
    app = _insert(world.db, "applications", name="Acme chat", business_unit_id=world.unit["A"], vendor_id=vendor, is_active=1)
    service.create_profile(world.db, world.users["super"], app, {})
    world.db.commit()
    assert [i["name"] for i in http("get", "/ai-governance/api/flags", name="dpo_a").json()["items"]] == ["Claims triage"]
    # so does an edge between the process and an AI use
    from modules.governance import relationships
    relationships.create_link(world.db, world.users["dpo_a"], ("governance", "application", app), ("governance", "process", process), "supports")
    world.db.commit()
    assert http("get", "/ai-governance/api/flags", name="dpo_a").json()["items"] == []
    audited = world.db.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'uses_ai_set'").fetchone()[0]
    assert audited == 3


def test_a_request_started_from_a_flag_remembers_where_it_came_from_and_leaves_the_queue_while_open(http):
    world = http.world
    vendor = _insert(world.db, "canonical_vendors", name="Beta Vendor")
    world.db.commit()
    http("put", f"/ai-governance/api/flags/vendor/{vendor}", name="dpo_a", json={"answer": "yes"})
    page = http("get", f"/ai-governance/register?source=vendor:{vendor}&name=Beta%20Vendor", name="employee_a")
    assert page.status_code == 200 and f'"vendor:{vendor}"' in page.text and '"Beta Vendor"' in page.text
    ignored = http("get", "/ai-governance/register?source=vendor:abc&name=x", name="employee_a")
    assert 'sourceRef: ""' in ignored.text, "a source that is not vendor:N or process:N is dropped"
    row = http("post", "/ai-governance/api/requests", name="employee_a",
               json={"answers": {"name": "Beta"}, "source_ref": f"vendor:{vendor}"})
    assert row.status_code == 201 and row.json()["intake"]["source_ref"] == f"vendor:{vendor}"
    assert http("get", "/ai-governance/api/flags", name="dpo_a").json()["items"] == [], "someone is already on it"
    assert http("post", "/ai-governance/api/requests", name="employee_a", json={"answers": {}, "source_ref": "vendor:abc"}).status_code == 400
