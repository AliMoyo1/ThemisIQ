"""The cross-module vendor views show each module's section only to a user who may open that
module's vendor records (PLAN-37 Appendix A finding 3).

get_cross_module_profile used to take no user at all: the BCM route (open to every BCM role,
including employees) returned the Sentinel DPA profile with its AI assessment text and the GRID
audit findings, and the platform vendor directory (any signed-in user) returned the same. Each
section now needs what that module's own vendor routes require, and a flag that depends on a
section the viewer cannot open is dropped instead of guessed (a hidden record would otherwise
read as "no audit exists").
"""
import asyncio
import json
import types

import pytest

import core.middleware as middleware
import modules.bcm.routes as bcm_routes
import modules.grid.routes as grid_routes
import modules.launcher.routes_vendors as vendor_routes
import modules.sentinel.routes as sentinel_routes
from core import rbac
from core.vendor_link import get_cross_module_profile, get_vendor_directory

SECRETS = {
    "sentinel": ("SECRET-AI-ASSESSMENT", "SECRET-SERVICES"),
    "grid": ("SECRET-FINDINGS", "SECRET-ACTION"),
    "bcm": ("SECRET-SLA",),
}
# Written from core/rbac.py: grid.vendor.manage = super admin + audit lead; sentinel.vendor.manage =
# super admin + DPO; module.bcm.access covers employees too.
PERSONAS = {
    "super": (rbac.SUPER_ADMIN, {"sentinel", "grid", "bcm"}),
    "dpo": (rbac.DPO, {"sentinel"}),
    "audit_lead": (rbac.AUDIT_LEAD, {"grid"}),
    "employee": (rbac.EMPLOYEE, {"bcm"}),
    "bcm_manager": (rbac.BCM_MANAGER, {"bcm"}),
}


def _user(name):
    role, _ = PERSONAS[name]
    return {"id": 1, "username": name, "org_id": None, "business_unit_id": None,
            "is_super_admin": 1 if role == rbac.SUPER_ADMIN else 0, "roles": [role]}


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    async def current_user(request):
        return request.state.user

    monkeypatch.setattr(middleware, "get_current_user", current_user)


def _insert(db, table, **cols):
    cur = db.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        tuple(cols.values()),
    )
    db.commit()
    return cur.lastrowid


@pytest.fixture
def vendor(test_db):
    """One company present in all three modules: expired DPA, weak audit score, critical tier 1."""
    cid = _insert(test_db, "canonical_vendors", name="Acme Cloud")
    sen = _insert(test_db, "sentinel_vendors", name="Acme Cloud", canonical_id=cid, dpa_status="expired",
                  ai_assessment="SECRET-AI-ASSESSMENT", services="SECRET-SERVICES")
    grid = _insert(test_db, "grid_vendors", name="Acme Cloud", canonical_id=cid, risk_level="high")
    _insert(test_db, "grid_vendor_assessments", vendor_id=grid, score=40, assessment_date="2026-09-01",
            findings="SECRET-FINDINGS", action_required="SECRET-ACTION")
    bcm = _insert(test_db, "bcm_vendors", name="Acme Cloud", canonical_id=cid, criticality="critical",
                  tier=1, sla="SECRET-SLA")
    return types.SimpleNamespace(db=test_db, cid=cid, sen=sen, grid=grid, bcm=bcm)


def _leaked(payload, sections):
    """The module sections whose secret text appears anywhere in the payload."""
    text = json.dumps(payload)
    return {m for m, words in SECRETS.items() if any(w in text for w in words) and m not in sections}


@pytest.mark.parametrize("name", list(PERSONAS))
def test_profile_holds_only_the_sections_the_viewer_may_open(vendor, name):
    allowed = PERSONAS[name][1]
    profile = get_cross_module_profile(vendor.db, vendor.cid, _user(name))
    assert set(profile["modules"]) == allowed
    assert _leaked(profile, allowed) == set()
    for module in allowed:  # the sections they may open really are there
        assert any(w in json.dumps(profile["modules"][module]) for w in SECRETS[module]), module


LOW_SCORE = "Low compliance audit score (40%)"
DPA_EXPIRED = "DPA has expired"


def test_flags_are_computed_only_from_sections_the_viewer_can_open(vendor):
    def messages(name):
        return [f["msg"] for f in get_cross_module_profile(vendor.db, vendor.cid, _user(name))["flags"]]

    everything = messages("super")
    assert len(everything) == 2 and LOW_SCORE in everything[0] and DPA_EXPIRED in everything[1]
    only_privacy = messages("dpo")
    assert len(only_privacy) == 1 and DPA_EXPIRED in only_privacy[0]
    only_audit = messages("audit_lead")
    assert len(only_audit) == 1 and LOW_SCORE in only_audit[0]
    # A BCM-only viewer must not be told "no DPA" or "no audit": they cannot see whether one exists.
    assert messages("employee") == []
    assert messages("bcm_manager") == []


def test_a_missing_record_is_still_reported_to_a_viewer_who_can_see_the_module(vendor):
    vendor.db.execute("DELETE FROM grid_vendor_assessments")
    vendor.db.execute("DELETE FROM grid_vendors")
    vendor.db.commit()
    both = {**_user("super")}
    messages = [f["msg"] for f in get_cross_module_profile(vendor.db, vendor.cid, both)["flags"]]
    assert "High-criticality vendor has no compliance audit in Audit" in messages
    assert not any("audit score" in m for m in messages)


@pytest.mark.parametrize("name", list(PERSONAS))
def test_directory_shows_only_the_sections_and_coverage_the_viewer_may_open(vendor, name):
    allowed = PERSONAS[name][1]
    (record,) = get_vendor_directory(vendor.db, _user(name))
    for module in ("sentinel", "grid", "bcm"):
        assert bool(record[module]) is (module in allowed), module
    assert record["coverage"] == len(allowed)
    assert _leaked(record, allowed) == set()
    if name == "super":
        assert record["risk_flag"] == "critical"
    elif name == "employee":
        assert record["risk_flag"] is None, "the tier 1 and DPA test needs Privacy, which they cannot open"


# ── Every route passes the caller through ───────────────────────────────────

def _request(user):
    return types.SimpleNamespace(state=types.SimpleNamespace(user=user),
                                 url=types.SimpleNamespace(path="/x"), query_params={})


def _body(coro):
    return json.loads(asyncio.run(coro).body)


def test_the_module_routes_and_the_platform_routes_apply_the_same_rule(vendor):
    employee = _user("employee")
    assert set(_body(bcm_routes.api_vendor_cross_module(_request(employee), vendor.bcm))["modules"]) == {"bcm"}
    assert set(_body(vendor_routes.api_vendor_profile(_request(employee), vendor.cid))["modules"]) == {"bcm"}

    audit_lead = _user("audit_lead")
    assert set(_body(grid_routes.api_vendor_cross_module(_request(audit_lead), vendor.grid))["modules"]) == {"grid"}

    dpo = _user("dpo")
    assert set(_body(sentinel_routes.api_vendor_cross_module(_request(dpo), vendor.sen))["modules"]) == {"sentinel"}

    listing = _body(vendor_routes.api_vendor_directory(_request(employee)))
    assert [bool(v["sentinel"]) for v in listing["items"]] == [False]
    assert [bool(v["grid"]) for v in listing["items"]] == [False]
    assert [bool(v["bcm"]) for v in listing["items"]] == [True]
