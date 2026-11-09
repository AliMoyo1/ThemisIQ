"""One registry of linkable records (plans/2026-11-relationship-service-fold.md).

Written out by hand, not computed by the code under test:

* links the platform stores under its own spellings (platform/risk_register, erm/enterprise_risk,
  grid/non_conformance) are read as the records they are, through the same scope rule as any other link;
* the platform refuses to store a link to a kind the registry does not know, because nobody could ever see it;
* a GRID finding event links the kind it names;
* the Vault's own link routes follow the Related Items rule: seeing both ends is not enough, the caller must be
  allowed to change one of them, so a read-only External Auditor cannot link or unlink proof;
* deleting an ERM risk removes its links under both spellings.
"""
import pytest

import core.middleware as middleware
from core import rbac
from core.links import create_cross_module_link
from modules.governance import relationships
from tests.test_platform_ownership import _insert, world  # noqa: F401

ERM, PLATFORM_RISK, BREACH, NC, AUDIT = ("erm", "risk"), ("platform", "risk"), ("sentinel", "breach"), ("grid", "nc"), ("grid", "audit")


def _titles(db, user, key, record_id):
    return sorted((l["module"], l["entity_type"], l["title"], l["label"])
                  for l in relationships.list_links(db, user, key, record_id))


# ── Platform links under their stored spellings ─────────────────────────────

def test_an_escalation_stored_as_enterprise_risk_shows_on_both_records(world):
    db, rec = world.db, world.rec
    breach, risk = rec[("breach", "A")], rec[("erm", "A")]
    assert create_cross_module_link("sentinel", "breach", breach, "erm", "enterprise_risk", risk,
                                    relationship="escalated_to", db=db)
    db.commit()
    stored = db.execute("SELECT target_type FROM cross_module_links").fetchone()[0]
    assert stored == "enterprise_risk", "the stored spelling is kept for the code that queries it"

    admin = world.users["super"]
    assert _titles(db, admin, ERM, risk) == [("sentinel", "breach", "needle breach A", "escalated from")]
    assert _titles(db, admin, BREACH, breach) == [("erm", "risk", "ERM risk A", "escalated to")]
    # The other end still has to pass its own module's rule: unit B cannot open the unit A breach or risk.
    assert _titles(db, world.users["owner_b"], ERM, risk) == []
    assert _titles(db, world.users["dpo_b"], BREACH, breach) == []


def test_a_platform_risk_stored_as_risk_register_shows_as_the_platform_risk(world):
    db, breach = world.db, world.rec[("breach", "A")]
    risk = _insert(db, "risk_register", title="needle platform risk", business_unit_id=world.unit["A"])
    assert create_cross_module_link("sentinel", "breach", breach, "platform", "risk_register", risk,
                                    relationship="triggers", db=db)
    db.commit()
    admin = world.users["super"]
    assert _titles(db, admin, PLATFORM_RISK, risk) == [("sentinel", "breach", "needle breach A", "triggered by")]
    assert _titles(db, admin, BREACH, breach) == [("platform", "risk", "needle platform risk", "triggers")]


@pytest.mark.parametrize("source, target", [
    (("grid", "finding"), ("grid", "audit")),           # a remote-audit finding: no registered kind
    (("grid", "audit"), ("platform", "framework")),     # a GRID framework id, not an ARIA framework
    (("grid", "nc"), ("sentinel", "grid_finding")),     # a task pseudo-type
    (("nowhere", "thing"), ("grid", "audit")),
])
def test_the_platform_does_not_store_a_link_nobody_could_see(world, source, target):
    assert create_cross_module_link(*source, 1, *target, 1, db=world.db) is None
    assert world.db.execute("SELECT COUNT(*) FROM cross_module_links").fetchone()[0] == 0


def test_a_major_non_conformance_links_to_its_audit_as_the_non_conformance_it_is(world):
    from core.event_handlers import grid_finding_created_handler
    db, nc, audit = world.db, world.rec[("nc", "A")], world.rec[("audit", "A")]
    grid_finding_created_handler("grid.finding.created", "grid", "non_conformance", nc,
                                 {"title": "NC in unit A", "severity": "major", "audit_id": audit}, None)
    row = db.execute("SELECT source_type, target_type, target_id FROM cross_module_links").fetchone()
    assert tuple(row) == ("non_conformance", "audit", audit)
    assert _titles(db, world.users["super"], AUDIT, audit) == [("grid", "nc", "NC in unit A", "source of")]


# ── The Vault's own link routes ─────────────────────────────────────────────

@pytest.fixture
def vault(world, monkeypatch):
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from modules.evidence.routes import router as evidence_router

    auditor_id = 50
    world.users["auditor_a"] = {"id": auditor_id, "username": "auditor_a", "org_id": 1,
                                "business_unit_id": world.unit["A"], "is_super_admin": 0,
                                "roles": [rbac.EXTERNAL_AUDITOR]}
    _insert(world.db, "users", id=auditor_id, username="auditor_a", email="auditor_a@example.test",
            full_name="auditor_a", password_hash="x", org_id=1, business_unit_id=world.unit["A"])
    world.item = _insert(world.db, "evidence_items", title="needle proof", status="current", org_id=1,
                         business_unit_id=world.unit["A"])
    who = {"name": "super"}

    async def current_user(request):
        return world.users[who["name"]]

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    app = FastAPI()
    app.include_router(evidence_router)
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False)

    def call(method, path, name, **kwargs):
        who["name"] = name
        return getattr(client, method)(path, **kwargs)

    world.call = call
    return world


def _live_links(db):
    return db.execute("SELECT COUNT(*) FROM evidence_links WHERE deleted_at IS NULL").fetchone()[0]


def test_an_external_auditor_who_sees_both_ends_cannot_link_or_unlink_proof(vault):
    audit = vault.rec[("audit", "A")]
    body = {"module": "grid", "entity_type": "audit", "entity_id": audit}
    path = f"/evidence/api/items/{vault.item}/links"

    item_path = f"/evidence/api/items/{vault.item}"
    assert vault.call("get", item_path, "auditor_a").json()["can_link"] is False, "the drawer hides Link and Unlink"
    assert vault.call("get", item_path, "employee_a").json()["can_link"] is True

    refused = vault.call("post", path, "auditor_a", json=body)
    assert refused.status_code == 403, refused.text
    assert _live_links(vault.db) == 0

    made = vault.call("post", path, "super", json=body)
    assert made.status_code == 201, made.text
    link_id = made.json()["id"]
    assert vault.call("delete", f"/evidence/api/links/{link_id}", "auditor_a").status_code == 403
    assert _live_links(vault.db) == 1
    assert vault.call("delete", f"/evidence/api/links/{link_id}", "super").status_code == 200
    assert _live_links(vault.db) == 0


def test_an_external_auditor_cannot_file_proof_against_a_record_at_upload(vault):
    audit = vault.rec[("audit", "A")]
    refused = vault.call("post", "/evidence/api/items", "auditor_a",
                         data={"title": "auditor upload", "link_module": "grid", "link_entity_type": "audit",
                               "link_entity_id": str(audit)},
                         files={"file": ("note.txt", b"proof", "text/plain")})
    assert refused.status_code == 403, refused.text
    assert vault.db.execute("SELECT COUNT(*) FROM evidence_items WHERE title = 'auditor upload'").fetchone()[0] == 0


def test_the_vault_picker_finds_a_non_conformance_under_either_spelling(vault):
    for entity_type in ("nc", "non_conformance"):
        found = vault.call("get", f"/evidence/api/search-entities?module=grid&entity_type={entity_type}&q=NC",
                           "super")
        assert found.status_code == 200, (entity_type, found.text)
        assert [r["name"] for r in found.json()] == ["NC in unit A"], entity_type
    assert vault.call("get", "/evidence/api/search-entities?module=grid&entity_type=finding", "super").status_code == 400


# ── Deleting an ERM risk ────────────────────────────────────────────────────

def test_deleting_an_erm_risk_removes_its_links_under_both_spellings(world):
    from modules.erm import data_service
    db, breach, risk = world.db, world.rec[("breach", "A")], world.rec[("erm", "A")]
    create_cross_module_link("sentinel", "breach", breach, "erm", "enterprise_risk", risk, db=db)
    create_cross_module_link("erm", "risk", risk, "sentinel", "breach", breach, db=db)
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM cross_module_links").fetchone()[0] == 2
    data_service.delete_enterprise_risk(risk)
    assert db.execute("SELECT COUNT(*) FROM cross_module_links").fetchone()[0] == 0
