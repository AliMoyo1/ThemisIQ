"""Removed evidence links are not counted outside the Vault.

Unlinking evidence is a soft delete: the unlink route in modules/evidence/routes.py sets
evidence_links.deleted_at and keeps the row. Each reader below must count only links where
deleted_at IS NULL. Every test builds live and removed links and asserts both sides, so a
query that breaks and returns nothing cannot pass by accident (the effectiveness and ARIA
list queries swallow errors).
"""
import asyncio
import json
import types
from datetime import date, timedelta

import pytest

import core.middleware as middleware
import modules.aria.routes as aria
import modules.bcm.routes as bcm
import modules.erm.data_service as erm_ds
import modules.governance.effectiveness as eff
import modules.grid.data_service as grid_ds

REMOVED_AT = "2026-01-01 00:00:00"
ADMIN = {"id": 1, "username": "admin", "org_id": None, "business_unit_id": None,
         "is_super_admin": 1, "roles": ["super_admin"]}


@pytest.fixture
def as_admin(monkeypatch):
    async def fake_current_user(request):
        return ADMIN

    monkeypatch.setattr(middleware, "get_current_user", fake_current_user)


@pytest.fixture
def aria_page(monkeypatch, as_admin):
    """The template context an ARIA page would render; the template itself is not rendered."""
    seen = {}

    def capture(request, template, context, active_section=""):
        seen.update(context)

    monkeypatch.setattr(aria, "_aria_render", capture)
    return seen


def _call(handler, *args):
    request = types.SimpleNamespace(
        state=types.SimpleNamespace(user=ADMIN),
        url=types.SimpleNamespace(path="/x"),
        query_params={},
    )
    return asyncio.run(handler(request, *args))


def _insert(db, table, **cols):
    cur = db.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        tuple(cols.values()),
    )
    db.commit()
    return cur.lastrowid


def _evidence(db, title, module, entity_type, entity_id, removed=False, **item_cols):
    """A current evidence item with one link to the entity; the link is soft deleted if removed."""
    item = _insert(db, "evidence_items", title=title, status="current", **item_cols)
    _insert(db, "evidence_links", evidence_id=item, module=module, entity_type=entity_type,
            entity_id=entity_id, deleted_at=REMOVED_AT if removed else None)
    return item


def _control(db, title):
    return _insert(db, "canonical_controls", title=title)


# -- Control effectiveness score (governance/effectiveness.py) ---------------------------------

def test_effectiveness_evidence_uploaded_ignores_a_removed_link(test_db):
    kept, unlinked = _control(test_db, "kept"), _control(test_db, "unlinked")
    _evidence(test_db, "Kept evidence", "grid", "canonical_control", kept)
    _evidence(test_db, "Unlinked evidence", "grid", "canonical_control", unlinked, removed=True)

    assert eff._score_one_control(test_db, kept)["evidence_uploaded"] == 1
    assert eff._score_one_control(test_db, unlinked)["evidence_uploaded"] == 0


def test_effectiveness_evidence_valid_ignores_a_removed_expiring_link(test_db):
    soon = (date.today() + timedelta(days=3)).isoformat()
    healthy, expiring, tidied = (_control(test_db, n) for n in ("healthy", "expiring", "tidied"))
    _evidence(test_db, "Healthy", "grid", "canonical_control", healthy)
    _evidence(test_db, "Expiring", "grid", "canonical_control", expiring, expiry_date=soon)
    # A live healthy link plus a removed link to an item that expires inside the 7 day window.
    _evidence(test_db, "Healthy too", "grid", "canonical_control", tidied)
    _evidence(test_db, "Expiring but unlinked", "grid", "canonical_control", tidied,
              removed=True, expiry_date=soon)

    valid = {name: eff._score_one_control(test_db, cid)["evidence_valid"]
             for name, cid in (("healthy", healthy), ("expiring", expiring), ("tidied", tidied))}
    assert valid == {"healthy": 1, "expiring": 0, "tidied": 1}


# -- ERM risk controls (erm/data_service.py list_risk_controls) --------------------------------

def test_erm_risk_control_evidence_count_ignores_removed_links(test_db):
    risk = _insert(test_db, "erm_enterprise_risks", title="Data loss")
    for title, removed_flags in (("Live only", [False]), ("Removed only", [True]),
                                 ("Live and removed", [False, True])):
        control = _control(test_db, title)
        _insert(test_db, "risk_controls", risk_id=risk, control_id=control)
        for n, removed in enumerate(removed_flags):
            _evidence(test_db, f"{title} {n}", "grid", "canonical_control", control, removed=removed)

    counts = {c["control_title"]: c["evidence_count"] for c in erm_ds.list_risk_controls(risk)}
    assert counts == {"Live only": 1, "Removed only": 0, "Live and removed": 1}


# -- ARIA framework pages (aria/routes.py) -----------------------------------------------------

def _aria_framework(db):
    """One framework with RF-1 (one live and one removed link) and RF-2 (one removed link)."""
    fw = _insert(db, "frameworks", name="Regression Framework", is_active=1)
    ctrl = {ref: _insert(db, "controls", framework_id=fw, ref=ref, name=ref) for ref in ("RF-1", "RF-2")}
    _evidence(db, "Live", "aria", "control", ctrl["RF-1"])
    _evidence(db, "Removed on the same control", "aria", "control", ctrl["RF-1"], removed=True)
    _evidence(db, "Removed on another control", "aria", "control", ctrl["RF-2"], removed=True)
    return fw


def test_aria_framework_list_evidence_count_ignores_removed_links(test_db, aria_page):
    fw = _aria_framework(test_db)
    _call(aria.frameworks_list)
    row = next(f for f in aria_page["fw_list"] if f["id"] == fw)
    assert row["evidence_count"] == 1


def test_aria_framework_detail_control_evidence_count_ignores_removed_links(test_db, aria_page):
    fw = _aria_framework(test_db)
    _call(aria.framework_detail, fw)
    counts = {c["ref"]: c["evidence_count"] for c in aria_page["controls"]}
    assert counts == {"RF-1": 1, "RF-2": 0}


# -- BCM detail pages (bcm/routes.py) ----------------------------------------------------------

def test_bcm_plan_detail_lists_only_live_evidence(test_db, as_admin):
    plan = _insert(test_db, "bcm_plans", title="Continuity plan")
    _evidence(test_db, "Live plan evidence", "bcm", "plan", plan)
    _evidence(test_db, "Removed plan evidence", "bcm", "plan", plan, removed=True)

    body = json.loads(_call(bcm.api_plan_detail, plan).body)
    assert [e["title"] for e in body["evidence"]] == ["Live plan evidence"]
    assert body["evidence_count"] == 1


def test_bcm_incident_detail_lists_only_live_evidence(test_db, as_admin):
    incident = _insert(test_db, "bcm_incidents", title="Data centre outage")
    _evidence(test_db, "Live incident evidence", "bcm", "incident", incident)
    _evidence(test_db, "Removed incident evidence", "bcm", "incident", incident, removed=True)

    body = json.loads(_call(bcm.api_incident_detail, incident).body)
    assert [e["title"] for e in body["evidence"]] == ["Live incident evidence"]
    assert body["evidence_count"] == 1


# -- GRID attach (grid/data_service.py attach_vault_item_to_grid_control) ----------------------
# Its "already linked" check decides whether to create a link, so a removed link must not satisfy it.

def _grid_control(db):
    audit = _insert(db, "grid_audits", name="Regression audit")
    return _insert(db, "grid_controls", audit_id=audit, name="Regression control")


def _link_counts(db, item, control):
    """(live, total) evidence_links rows from the item to the GRID control."""
    where = "evidence_id=%s AND module='grid' AND entity_type='control' AND entity_id=%s"
    live = db.execute(f"SELECT COUNT(*) FROM evidence_links WHERE {where} AND deleted_at IS NULL",
                      (item, control)).fetchone()[0]
    total = db.execute(f"SELECT COUNT(*) FROM evidence_links WHERE {where}", (item, control)).fetchone()[0]
    return live, total


def test_grid_attach_creates_a_live_link_when_the_old_link_was_removed(test_db):
    control = _grid_control(test_db)
    item = _evidence(test_db, "Policy pack", "grid", "control", control, removed=True)

    assert grid_ds.attach_vault_item_to_grid_control(control, item, None) is not None
    # One live link again, and the removed row stays as the audit trail.
    assert _link_counts(test_db, item, control) == (1, 2)


def test_grid_attach_does_not_duplicate_a_live_link(test_db):
    control = _grid_control(test_db)
    item = _evidence(test_db, "Policy pack", "grid", "control", control)

    assert grid_ds.attach_vault_item_to_grid_control(control, item, None) is not None
    assert _link_counts(test_db, item, control) == (1, 1)
