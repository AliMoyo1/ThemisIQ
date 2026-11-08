"""Evidence counts outside the Vault count current proof the viewer may open
(plans/2026-11-vault-current-proof-policy-layout.md, 1b), and ERM risk control routes keep the unit boundary.

Current proof is the Vault's definition (modules/evidence/proof.py): a live link to the current version of an item
that has not expired and that no reviewer returned, rejected or ruled out of scope.
"""
import asyncio
import types
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

import core.middleware as middleware
import modules.aria.routes as aria
import modules.erm.data_service as erm_ds
import modules.erm.routes as erm_routes

ADMIN = {"id": 1, "username": "admin", "org_id": None, "business_unit_id": None, "is_super_admin": 1,
         "roles": ["super_admin"]}
PAST = (date.today() - timedelta(days=1)).isoformat()
FUTURE = (date.today() + timedelta(days=30)).isoformat()


def _insert(db, table, **cols):
    cur = db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                     tuple(cols.values()))
    db.commit()
    return cur.lastrowid


def _proofs(db, module, entity_type, entity_id, org_id=None):
    """One item of each lapsed kind plus one current, all linked to the same record. Exactly one should count."""
    def item(title, link_review=None, **cols):
        cols = {"status": "current", "org_id": org_id, **cols}
        eid = _insert(db, "evidence_items", title=title, **cols)
        _insert(db, "evidence_links", evidence_id=eid, module=module, entity_type=entity_type, entity_id=entity_id,
                review_status=link_review)
    item("Current, expires later", expiry_date=FUTURE)
    item("Expired", expiry_date=PAST)
    item("Replaced", status="superseded")
    item("Archived", status="archived")
    item("Rejected by a reviewer", link_review="rejected")
    item("Returned by a reviewer", link_review="returned")


@pytest.fixture
def user_state(monkeypatch):
    state = {"user": ADMIN}

    async def fake_current_user(request):
        return state["user"]

    monkeypatch.setattr(middleware, "get_current_user", fake_current_user)
    return state


def _request(user):
    return types.SimpleNamespace(state=types.SimpleNamespace(user=user), url=types.SimpleNamespace(path="/x"),
                                 query_params={})


@pytest.fixture
def aria_page(monkeypatch, user_state):
    seen = {}
    monkeypatch.setattr(aria, "_aria_render", lambda request, template, context, active_section="": seen.update(context))
    return seen


def test_aria_control_and_framework_counts_skip_lapsed_files(test_db, aria_page):
    fw = _insert(test_db, "frameworks", name="Proof Framework", is_active=1)
    ctrl = _insert(test_db, "controls", framework_id=fw, ref="PF-1", name="PF-1")
    _proofs(test_db, "aria", "control", ctrl)

    asyncio.run(aria.framework_detail(_request(ADMIN), fw))
    assert {c["ref"]: c["evidence_count"] for c in aria_page["controls"]} == {"PF-1": 1}

    aria_page.clear()
    asyncio.run(aria.frameworks_list(_request(ADMIN)))
    counts = {f["name"]: f["evidence_count"] for f in aria_page["fw_list"]}
    assert counts["Proof Framework"] == 1


def test_erm_risk_control_count_skips_lapsed_files(test_db):
    risk = _insert(test_db, "erm_enterprise_risks", title="Data loss")
    control = _insert(test_db, "canonical_controls", title="Backups")
    _insert(test_db, "risk_controls", risk_id=risk, control_id=control)
    _proofs(test_db, "grid", "canonical_control", control)
    assert [c["evidence_count"] for c in erm_ds.list_risk_controls(risk)] == [1]


def test_erm_risk_control_count_follows_the_viewers_vault_scope(test_db):
    org = _insert(test_db, "organizations", name="o", slug="o", plan="enterprise", status="active")
    unit_a = _insert(test_db, "business_units", name="A", code="A", is_active=1)
    unit_b = _insert(test_db, "business_units", name="B", code="B", is_active=1)
    risk = _insert(test_db, "erm_enterprise_risks", title="Outage")
    control = _insert(test_db, "canonical_controls", title="Failover")
    _insert(test_db, "risk_controls", risk_id=risk, control_id=control)
    for title, unit in (("Unit A drill", unit_a), ("Unit B drill", unit_b), ("Group drill", None)):
        eid = _insert(test_db, "evidence_items", title=title, status="current", org_id=org, business_unit_id=unit)
        _insert(test_db, "evidence_links", evidence_id=eid, module="grid", entity_type="canonical_control",
                entity_id=control)
    viewer = {"id": 7, "username": "ro", "org_id": org, "business_unit_id": unit_a, "is_super_admin": 0,
              "roles": ["risk_owner"]}
    assert [c["evidence_count"] for c in erm_ds.list_risk_controls(risk, viewer)] == [2]


@pytest.mark.parametrize("call", ["list", "link", "unlink", "suggest"])
def test_erm_risk_control_routes_refuse_another_units_risk(test_db, user_state, call):
    org = _insert(test_db, "organizations", name="o", slug="o", plan="enterprise", status="active")
    unit_a = _insert(test_db, "business_units", name="A", code="A", is_active=1)
    unit_b = _insert(test_db, "business_units", name="B", code="B", is_active=1)
    risk = _insert(test_db, "erm_enterprise_risks", title="Unit B risk", business_unit_id=unit_b)
    control = _insert(test_db, "canonical_controls", title="Patch")
    _insert(test_db, "risk_controls", risk_id=risk, control_id=control)
    viewer = {"id": 7, "username": "ro", "org_id": org, "business_unit_id": unit_a, "is_super_admin": 0,
              "roles": ["risk_owner"]}
    user_state["user"] = viewer
    request = _request(viewer)

    async def body():
        return {"control_id": control}

    request.json = body
    request.body = lambda: asyncio.sleep(0, result=b'{"control_id": %d}' % control)
    handlers = {
        "list": lambda: erm_routes.api_risk_controls_list(request, risk),
        "link": lambda: erm_routes.api_risk_control_link(request, risk),
        "unlink": lambda: erm_routes.api_risk_control_unlink(request, risk, control),
        "suggest": lambda: erm_routes.api_risk_control_suggest_ice(request, risk, control),
    }
    with pytest.raises(HTTPException) as refused:
        asyncio.run(handlers[call]())
    assert refused.value.status_code == 404
    still = test_db.execute("SELECT COUNT(*) FROM risk_controls WHERE risk_id=%s", (risk,)).fetchone()[0]
    assert still == 1, "nothing changed on the other unit's risk"
