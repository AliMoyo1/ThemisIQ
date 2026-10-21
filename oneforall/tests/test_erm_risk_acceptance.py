"""A risk acceptance is a dated, independent decision over frozen source facts."""

from datetime import timedelta

import pytest

from core.timeutils import utcnow
from modules.erm import acceptance
from tests.test_platform_ownership import _insert, signed_in, world  # noqa: F401


def _payload():
    today = utcnow().date()
    return {
        "reason": "Residual exposure cannot be removed this quarter",
        "alternatives": "Reduce the service scope or fund another control",
        "scope_note": "Unit A payroll service only",
        "review_on": (today + timedelta(days=14)).isoformat(),
        "expires_on": (today + timedelta(days=30)).isoformat(),
    }


def _owned_risk(world):
    risk_id = world.rec[("erm", "A")]
    world.db.execute(
        "UPDATE erm_enterprise_risks SET owner_id=%s, likelihood=3, impact=4 WHERE id=%s",
        (world.users["owner_a"]["id"], risk_id),
    )
    world.db.commit()
    return risk_id


def test_owner_proposes_and_an_independent_decider_approves_frozen_scope(world):
    risk_id = _owned_risk(world)
    proposal_id = acceptance.propose(world.users["owner_a"], risk_id, _payload())
    proposal = acceptance.detail(world.users["owner_a"], proposal_id)
    assert proposal["status"] == "submitted"
    assert proposal["source_snapshot"]["current_score"] == 12

    with pytest.raises(PermissionError):
        acceptance.decide(world.users["owner_a"], proposal_id, {
            "decision": "approved", "note": "Self approval", "version": proposal["version"]})

    assert acceptance.decide(world.users["super"], proposal_id, {
        "decision": "approved", "note": "Temporary approval with review", "version": proposal["version"]}) == "approved"
    approved = acceptance.detail(world.users["owner_a"], proposal_id)
    assert approved["effective_status"] == "approved"
    assert [event["to_status"] for event in approved["events"]] == ["submitted", "approved"]


def test_a_changed_risk_requires_a_new_review_and_hidden_unit_stays_hidden(world):
    risk_id = _owned_risk(world)
    proposal_id = acceptance.propose(world.users["owner_a"], risk_id, _payload())
    with pytest.raises(LookupError):
        acceptance.detail(world.users["owner_b"], proposal_id)
    world.db.execute("UPDATE erm_enterprise_risks SET likelihood=5 WHERE id=%s", (risk_id,))
    world.db.commit()
    with pytest.raises(acceptance.AcceptanceConflict):
        acceptance.decide(world.users["super"], proposal_id, {
            "decision": "approved", "note": "Old facts", "version": 1})
    assert acceptance.detail(world.users["owner_a"], proposal_id)["status"] == "submitted"


def test_only_one_submitted_proposal_can_stand_for_a_risk(world):
    risk_id = _owned_risk(world)
    acceptance.propose(world.users["owner_a"], risk_id, _payload())
    with pytest.raises(acceptance.AcceptanceConflict):
        acceptance.propose(world.users["owner_a"], risk_id, _payload())
