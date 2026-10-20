"""
AI governance G4: decisions on an AI use, through the service layer.

Written out by hand. The owner or a reviewer asks; someone else decides; what was decided on is frozen with the decision
and a later change never edits it; an approval cannot go ahead over an unresolved required step without a recorded
reason; two deciders cannot both win; and a system the caller may not open does not exist for them.
"""
import json
from datetime import datetime, timezone

import pytest

from core import ai_rollout, rbac
from modules.ai_governance import decisions, evaluations, guidance, service
from modules.ai_governance.service import ServiceError
from tests.test_ai_governance_service import FULL, approve_new, commit, count, fail, submitted, user
from tests.test_platform_ownership import PERSONAS, _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401


def as_role(world, role, name="dpo_a"):
    return {**world.users[name], "roles": [role], "is_super_admin": 1 if role == rbac.SUPER_ADMIN else 0}


@pytest.fixture
def system(world):
    """An accepted use in unit A owned by employee_a (tier lower; the provider review is its one required step)."""
    done = approve_new(world, submitted(world, answers=FULL))
    world.app = done["application_id"]
    profile = service.get_profile(world.db, user(world, "dpo_a"), world.app)
    service.update_profile(world.db, user(world, "dpo_a"), world.app,
                           {"sponsor_user_id": user(world, "dpo_a")["id"], "jurisdictions": ["ZW"]},
                           profile["version"])
    evaluations.record_run(world.db, user(world, "dpo_a"), world.app, {
        "name": "Citation check", "test_set_name": "citations", "test_set_version": "v1",
        "rubric_version": "v1", "subject_version": "assistant v1", "evaluator": "deterministic",
        "status": "completed", "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "scores": {"citation_validity": 100}, "thresholds": {"citation_validity": 95},
        "cases_total": 1, "cases_failed": 0, "retention": "summary",
    })
    world.db.commit()
    return world


def resolve_provider_review(world):
    done = guidance.set_step_not_applicable(world.db, user(world, "dpo_a"), world.app, "vendor", "Built by us under licence.")
    commit(world, done, user(world, "dpo_a"))


def ask(world, name="employee_a", note=None):
    done = decisions.request_decision(world.db, user(world, name), world.app, note)
    commit(world, done, user(world, name))
    return done["decision"]


def brief(world, name="owner_a"):
    return decisions.get_brief(world.db, user(world, name), world.app)


def decide(world, row, outcome, name="owner_a", **kw):
    kw.setdefault("brief", brief(world, name)["hash"])
    kw.setdefault("expected_version", row["version"])
    done = decisions.decide(world.db, user(world, name), row["id"], outcome, **kw)
    commit(world, done, user(world, name))
    return done


def audit_actions(world):
    return [r[0] for r in world.db.execute("SELECT action FROM audit_log WHERE action LIKE 'ai_decision%' OR action LIKE 'ai_condition%' ORDER BY id").fetchall()]


def event_types(world):
    return [r[0] for r in world.db.execute("SELECT event_type FROM events WHERE event_type LIKE 'ai_use.decision%' ORDER BY id").fetchall()]


# ── Asking ──────────────────────────────────────────────────────────────────

def test_the_owner_asks_once_and_asking_again_returns_the_same_request(system):
    first = decisions.request_decision(system.db, user(system, "employee_a"), system.app, "Ready for the pilot.")
    commit(system, first, user(system, "employee_a"))
    assert first["created"] is True and first["decision"]["status"] == "proposed" and first["decision"]["version"] == 1
    assert first["decision"]["request_note"] == "Ready for the pilot." and len(first["events"]) == 1
    again = decisions.request_decision(system.db, user(system, "employee_a"), system.app)
    assert again["created"] is False and again["decision"]["id"] == first["decision"]["id"] and again["events"] == []
    assert count(system, "ai_use_decisions") == 1
    assert event_types(system) == ["ai_use.decision_requested"] and audit_actions(system) == ["ai_decision_requested"]


def test_a_reviewer_may_ask_and_other_staff_may_not(system):
    stranger = as_role(system, rbac.EMPLOYEE)  # may open the system, owns nothing, reviews nothing
    fail(lambda: decisions.request_decision(system.db, stranger, system.app), 403)
    row = ask(system, "dpo_a")
    assert row["requested_by"] == "dpo_a"


def test_a_hidden_a_missing_a_profileless_and_a_retired_system_cannot_be_put_forward(system):
    fail(lambda: decisions.request_decision(system.db, user(system, "dpo_b"), system.app), 404)
    fail(lambda: decisions.request_decision(system.db, user(system, "employee_a"), 987654), 404)
    plain = _insert(system.db, "applications", name="No profile", business_unit_id=system.unit["A"], is_active=1,
                    owner_user_id=user(system, "employee_a")["id"])
    system.db.commit()
    fail(lambda: decisions.request_decision(system.db, user(system, "employee_a"), plain), 409)
    retired = service.retire(system.db, user(system, "dpo_a"), system.app, "Contract ended.")
    commit(system, retired, user(system, "dpo_a"))
    fail(lambda: decisions.request_decision(system.db, user(system, "employee_a"), system.app), 409)
    assert count(system, "ai_use_decisions") == 0


# ── The brief ───────────────────────────────────────────────────────────────

def test_the_brief_shows_what_is_unresolved_and_its_digest_follows_the_facts(system):
    first = brief(system)
    assert first["needs_override"] is True and [u["key"] for u in first["unresolved"]] == ["vendor"]
    assert first["manifest"]["profile"]["tier"] == "lower" and len(first["hash"]) == 32
    assert brief(system)["hash"] == first["hash"], "asking twice gives the same digest"
    resolve_provider_review(system)
    second = brief(system)
    assert second["needs_override"] is False and second["unresolved"] == [] and second["hash"] != first["hash"]


def test_a_hidden_use_has_no_brief(system):
    assert decisions.get_brief(system.db, user(system, "dpo_b"), system.app) is None
    assert decisions.get_decisions(system.db, user(system, "dpo_b"), system.app) is None


# ── Deciding ────────────────────────────────────────────────────────────────

def test_a_decider_approves_a_resolved_request_and_the_decision_is_frozen_with_what_it_was_signed_on(system):
    resolve_provider_review(system)
    row = ask(system)
    done = decide(system, row, "approve", rationale="Low tier, provider reviewed.", expires_at="2999-01-01")
    got = done["decision"]
    assert got["status"] == "approved" and got["decided_by"] == "owner_a" and got["expires_at"] == "2999-01-01"
    assert got["version"] == 2 and got["separation_enforced"] is True and got["override_reason"] is None
    assert got["profile_version"] and got["rule_version"] == "v1" and len(got["manifest_hash"]) == 32
    assert len(done["events"]) == 1 and event_types(system) == ["ai_use.decision_requested", "ai_use.decision_made"]
    assert audit_actions(system) == ["ai_decision_requested", "ai_decision_made"]
    signed = decisions.get_decision(system.db, user(system, "owner_a"), row["id"])["manifest"]
    assert signed["checklist"]["unresolved"] == [] and signed["application"]["name"] == "Ticket summarizer"
    state = decisions.get_decisions(system.db, user(system, "owner_a"), system.app)
    assert state["state"]["state"] == "approved" and state["latest"]["id"] == row["id"] and state["open_request"] is None


def test_an_approval_over_an_unresolved_required_step_needs_a_recorded_reason(system):
    row = ask(system)
    fail(lambda: decide(system, row, "approve", rationale="Fine."), 422)
    fail(lambda: decide(system, row, "approve", rationale="Fine.", override_reason="ok"), 422)
    assert count(system, "ai_use_decisions", "status = 'proposed'") == 1, "nothing was decided"
    done = decide(system, row, "approve", rationale="Fine.", override_reason="The provider review is booked for next week.")
    assert done["decision"]["override_reason"].startswith("The provider review")
    assert "ai_decision_override" in audit_actions(system)
    fail(lambda: decisions.decide(system.db, user(system, "owner_a"), row["id"], "approve", rationale="x",
                                  override_reason="because", brief=brief(system)["hash"], expected_version=1), 409)


def test_an_override_reason_is_refused_when_nothing_is_unresolved(system):
    resolve_provider_review(system)
    row = ask(system)
    fail(lambda: decide(system, row, "approve", override_reason="Not needed but here it is."), 422)


def test_the_person_who_asked_and_the_owner_may_not_decide_unless_separation_is_off(system):
    resolve_provider_review(system)
    row = ask(system, "dpo_a")                      # a reviewer asked
    owner_as_decider = {**user(system, "employee_a"), "roles": [rbac.GRC_OFFICER]}  # the owner, with the right to decide
    fail(lambda: decisions.decide(system.db, owner_as_decider, row["id"], "approve", brief=brief(system)["hash"],
                                  expected_version=1), 403)
    fail(lambda: decisions.decide(system.db, user(system, "dpo_a"), row["id"], "approve", brief=brief(system, "dpo_a")["hash"],
                                  expected_version=1), 403)
    state = decisions.get_decisions(system.db, user(system, "dpo_a"), system.app)
    assert state["can"]["decide"] is False and "Someone other" in state["can"]["decide_blocked"]
    ai_rollout.set_separation(user(system, "dpo_a")["org_id"], False)
    done = decide(system, row, "approve", name="dpo_a")
    assert done["decision"]["separation_enforced"] is False and "ai_decision_unseparated" in audit_actions(system)


def test_only_a_decider_may_decide_and_only_one_who_may_open_the_system(system):
    resolve_provider_review(system)
    row = ask(system)
    fail(lambda: decisions.decide(system.db, user(system, "employee_a"), row["id"], "approve", brief="x", expected_version=1), 403)
    fail(lambda: decisions.decide(system.db, user(system, "owner_b"), row["id"], "approve", brief="x", expected_version=1), 404)
    fail(lambda: decisions.decide(system.db, user(system, "owner_a"), 987654, "approve", brief="x", expected_version=1), 404)


def test_an_approval_signed_on_a_brief_that_has_since_moved_is_refused_and_stores_nothing(system):
    resolve_provider_review(system)
    row = ask(system)
    shown = brief(system)["hash"]
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    edited = service.update_profile(system.db, user(system, "dpo_a"), system.app, {"purpose": "A different purpose"}, profile["version"])
    commit(system, edited, user(system, "dpo_a"))
    error = fail(lambda: decisions.decide(system.db, user(system, "owner_a"), row["id"], "approve", brief=shown,
                                          expected_version=row["version"]), 409)
    assert error.extra.get("brief_changed") is True
    assert count(system, "ai_use_decisions", "status = 'proposed'") == 1


def test_approving_with_conditions_names_them_and_an_expiry_must_be_a_later_date(system):
    resolve_provider_review(system)
    row = ask(system)
    fail(lambda: decide(system, row, "approve_with_conditions"), 422)
    fail(lambda: decide(system, row, "approve", conditions=[{"text": "Review monthly"}]), 422)
    fail(lambda: decide(system, row, "approve_with_conditions", conditions=["Review monthly"], expires_at="2000-01-01"), 422)
    fail(lambda: decide(system, row, "approve_with_conditions", conditions=["x"]), 422)
    fail(lambda: decide(system, row, "approve_with_conditions", conditions=[f"Condition {n}" for n in range(21)]), 422)
    done = decide(system, row, "approve_with_conditions", rationale="Pilot only.", expires_at="2999-06-30",
                  conditions=["Human review of every output", {"text": "Report incidents within a day", "due_date": "2999-03-01"}])
    got = done["decision"]
    assert got["status"] == "approved_with_conditions" and [c["text"] for c in got["conditions"]] == [
        "Human review of every output", "Report incidents within a day"]
    assert got["conditions"][1]["due_date"] == "2999-03-01" and all(c["status"] == "open" for c in got["conditions"])


def test_a_return_and_a_rejection_need_a_reason_and_neither_stands_as_an_approval(system):
    row = ask(system)
    fail(lambda: decide(system, row, "return"), 422)
    fail(lambda: decide(system, row, "reject", rationale=" "), 422)
    fail(lambda: decide(system, row, "return", rationale="More detail please.", expires_at="2999-01-01"), 422)
    returned = decide(system, row, "return", rationale="Name the data the vendor sees.")
    assert returned["decision"]["status"] == "returned"
    state = decisions.get_decisions(system.db, user(system, "owner_a"), system.app)
    assert state["state"]["state"] == "none" and state["can"]["request"] is True, "a return closes the request, it does not decide"
    again = ask(system)
    rejected = decide(system, again, "reject", rationale="The provider does not meet our requirements.")
    assert rejected["decision"]["status"] == "rejected"
    assert decisions.get_decisions(system.db, user(system, "owner_a"), system.app)["state"]["state"] == "rejected"


def test_two_deciders_cannot_both_win_and_a_stale_version_is_refused(system):
    resolve_provider_review(system)
    row = ask(system)
    shown = brief(system)["hash"]
    fail(lambda: decisions.decide(system.db, user(system, "owner_a"), row["id"], "approve", brief=shown, expected_version="1"), 400)
    first = decisions.decide(system.db, user(system, "owner_a"), row["id"], "approve", brief=shown, expected_version=1)
    commit(system, first, user(system, "owner_a"))
    late = fail(lambda: decisions.decide(system.db, user(system, "super"), row["id"], "reject", rationale="No.",
                                         brief=shown, expected_version=1), 409)
    assert late.extra["status_now"] == "approved"
    assert decisions.get_decision(system.db, user(system, "owner_a"), row["id"])["status"] == "approved"


def test_a_stale_request_version_is_refused_before_anything_is_checked_against_the_use(system):
    resolve_provider_review(system)
    row = ask(system)
    error = fail(lambda: decisions.decide(system.db, user(system, "owner_a"), row["id"], "approve", brief=brief(system)["hash"],
                                          expected_version=7), 409)
    assert error.extra["current_version"] == 1


# ── After the decision ──────────────────────────────────────────────────────

def _approved(world, **kw):
    resolve_provider_review(world)
    row = ask(world)
    return row, decide(world, row, "approve", rationale="Approved for use.", **kw)["decision"]


def test_a_change_to_a_covered_fact_opens_a_re_review_and_leaves_the_signed_decision_exactly_as_it_was(system):
    row, signed = _approved(system, expires_at="2999-01-01")
    before = system.db.execute("SELECT * FROM ai_use_decisions WHERE id = %s", (row["id"],)).fetchone()
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    edited = service.update_profile(system.db, user(system, "dpo_a"), system.app, {"data_categories": ["personal"]}, profile["version"])
    commit(system, edited, user(system, "dpo_a"))
    state = decisions.get_decisions(system.db, user(system, "owner_a"), system.app)
    assert state["state"]["state"] == "needs_re_review" and state["state"]["label"] == "Needs re-review"
    assert any("covered has changed" in r for r in state["state"]["reasons"])
    assert state["latest"]["id"] == row["id"] and state["latest"]["status"] == "approved"
    after = system.db.execute("SELECT * FROM ai_use_decisions WHERE id = %s", (row["id"],)).fetchone()
    assert dict(after) == dict(before), "the signed record was not touched"
    shown = brief(system)
    assert any("purpose" in c or "tier" in c or "data categories" in c for c in shown["changed_since_standing"])
    queue = decisions.list_queue(system.db, user(system, "owner_a"))
    assert [r["application_id"] for r in queue["re_reviews"]] == [system.app]


def test_an_approval_past_its_expiry_reads_as_expired(system):
    row, _ = _approved(system, expires_at="2999-01-01")
    system.db.execute("UPDATE ai_use_decisions SET expires_at = '2000-01-01' WHERE id = %s", (row["id"],))
    system.db.commit()
    state = decisions.get_decisions(system.db, user(system, "owner_a"), system.app)["state"]
    assert state["state"] == "expired" and state["label"] == "Approval expired"


def test_proof_the_decision_relied_on_expiring_opens_a_re_review(system):
    row, _ = _approved(system)
    manifest = json.loads(system.db.execute("SELECT manifest FROM ai_use_decisions WHERE id = %s", (row["id"],)).fetchone()[0])
    manifest["proof"] = [{"id": 1, "title": "Oversight procedure", "version": 1, "expired": False, "verified": True, "expires": "2000-01-01"}]
    system.db.execute("UPDATE ai_use_decisions SET manifest = %s WHERE id = %s", (json.dumps(manifest), row["id"]))
    system.db.commit()
    state = decisions.get_decisions(system.db, user(system, "owner_a"), system.app)["state"]
    assert state["state"] == "needs_re_review" and any("Proof" in r for r in state["reasons"])


def test_a_revocation_needs_a_reason_applies_once_and_only_to_an_approval(system):
    row, _ = _approved(system)
    fail(lambda: decisions.revoke(system.db, user(system, "owner_a"), row["id"], " "), 422)
    fail(lambda: decisions.revoke(system.db, as_role(system, rbac.EMPLOYEE, "employee_a"), row["id"],
                                  "No longer accurate."), 403)
    done = decisions.revoke(system.db, user(system, "owner_a"), row["id"], "The provider changed its terms.")
    commit(system, done, user(system, "owner_a"))
    assert event_types(system)[-1] == "ai_use.decision_revoked" and audit_actions(system)[-1] == "ai_decision_revoked"
    fail(lambda: decisions.revoke(system.db, user(system, "owner_a"), row["id"], "Again."), 409)
    got = decisions.get_decisions(system.db, user(system, "owner_a"), system.app)
    assert got["state"]["state"] == "revoked" and got["latest"]["revoked_reason"] == "The provider changed its terms."
    assert got["can"]["revoke"] is False and got["can"]["request"] is True
    rejected_row = ask(system)
    rejected = decide(system, rejected_row, "reject", rationale="Not after revocation.")["decision"]
    fail(lambda: decisions.revoke(system.db, user(system, "owner_a"), rejected["id"], "Cannot revoke a rejection."), 409)


def test_a_request_can_be_withdrawn_by_who_asked_and_then_asked_again(system):
    row = ask(system)
    stranger = as_role(system, rbac.EMPLOYEE)
    fail(lambda: decisions.withdraw(system.db, stranger, row["id"]), 403)
    done = decisions.withdraw(system.db, user(system, "employee_a"), row["id"])
    commit(system, done, user(system, "employee_a"))
    assert system.db.execute("SELECT status FROM ai_use_decisions WHERE id = %s", (row["id"],)).fetchone()[0] == "withdrawn"
    fail(lambda: decisions.withdraw(system.db, user(system, "employee_a"), row["id"]), 409)
    assert ask(system)["id"] != row["id"]


def test_conditions_are_met_and_reopened_by_the_owner_or_a_reviewer_without_touching_the_decision(system):
    resolve_provider_review(system)
    row = ask(system)
    done = decide(system, row, "approve_with_conditions", rationale="Pilot.", conditions=["Review monthly"])
    cid = done["decision"]["conditions"][0]["id"]
    signed = system.db.execute("SELECT manifest_hash, status, version FROM ai_use_decisions WHERE id = %s", (row["id"],)).fetchone()
    stranger = as_role(system, rbac.EMPLOYEE)
    fail(lambda: decisions.set_condition(system.db, stranger, cid, True), 403)
    fail(lambda: decisions.set_condition(system.db, user(system, "dpo_b"), cid, True), 404)
    fail(lambda: decisions.set_condition(system.db, user(system, "employee_a"), cid, "yes"), 422)
    met = decisions.set_condition(system.db, user(system, "employee_a"), cid, True, "First review held on the 3rd.")
    commit(system, met, user(system, "employee_a"))
    shown = decisions.get_decisions(system.db, user(system, "employee_a"), system.app)["latest"]["conditions"][0]
    assert shown["status"] == "met" and shown["met_by"] == "employee_a" and shown["note"].startswith("First review")
    reopened = decisions.set_condition(system.db, user(system, "dpo_a"), cid, False)
    commit(system, reopened, user(system, "dpo_a"))
    assert decisions.get_decisions(system.db, user(system, "dpo_a"), system.app)["latest"]["conditions"][0]["status"] == "open"
    after = system.db.execute("SELECT manifest_hash, status, version FROM ai_use_decisions WHERE id = %s", (row["id"],)).fetchone()
    assert tuple(after) == tuple(signed)
    assert audit_actions(system)[-2:] == ["ai_condition_met", "ai_condition_reopened"]


# ── Who sees what ───────────────────────────────────────────────────────────

def test_the_queue_lists_open_requests_in_scope_and_names_nothing_outside_it(system):
    row = ask(system)
    mine = decisions.list_queue(system.db, user(system, "owner_a"))
    assert [r["id"] for r in mine["requests"]] == [row["id"]] and mine["can_decide"] is True
    assert mine["requests"][0]["name"] == "Ticket summarizer" and mine["requests"][0]["requested_by"] == "employee_a"
    other = decisions.list_queue(system.db, user(system, "dpo_b"))
    assert other["requests"] == [] and other["re_reviews"] == []
    child = decisions.list_queue(system.db, user(system, "dpo_a1"))
    assert child["requests"] == [], "a child unit does not see its parent's system"
    assert decisions.list_queue(system.db, user(system, "super"))["requests"][0]["id"] == row["id"]


def test_a_manifest_names_a_record_only_to_a_viewer_who_may_open_it(system):
    aiia = _insert(system.db, "sentinel_aiia", ref_number="AIIA-D1", title="Secret impact assessment",
                   business_unit_id=system.unit["A"], application_id=system.app, status="completed")
    system.db.commit()
    resolve_provider_review(system)
    row = ask(system)
    decide(system, row, "approve", rationale="Approved.")
    seen = decisions.get_decision(system.db, user(system, "owner_a"), row["id"])["manifest"]["assessments"]
    assert seen[0]["id"] == aiia and seen[0]["title"] == "Secret impact assessment" and seen[0]["restricted"] is False
    fail(lambda: decisions.get_decision(system.db, user(system, "staff_a"), row["id"]), 403)
    fail(lambda: decisions.get_decision(system.db, user(system, "dpo_b"), row["id"]), 404)
    frozen = json.loads(system.db.execute(
        "SELECT manifest FROM ai_use_decisions WHERE id = %s", (row["id"],)).fetchone()[0])
    hidden = decisions.present_manifest(system.db, user(system, "dpo_b"), frozen)
    assert "Secret impact assessment" not in json.dumps(hidden)
    assert hidden["assessments"][0] == {"restricted": True}
    assert "AIIA-D1" not in json.dumps(hidden)


def test_manifest_removes_hidden_record_metadata_and_nested_mapping_ids(system):
    hidden_ropa = _insert(system.db, "sentinel_ropa", ref_number="SECRET-ROPA",
                          processing_name="Hidden processing", business_unit_id=system.unit["B"])
    hidden_control = _insert(system.db, "ai_control_catalogue", ref="SECRET-CTRL",
                             title="Hidden control", business_unit_id=system.unit["B"])
    visible_control = _insert(system.db, "ai_control_catalogue", ref="VISIBLE-CTRL",
                              title="Visible control", business_unit_id=system.unit["A"])
    hidden_proof = _insert(system.db, "evidence_items", title="Hidden proof", org_id=1,
                           business_unit_id=system.unit["B"])
    system.db.commit()
    frozen = {
        "checklist": {"steps": [{"records": [{"ref": ["sentinel", "ropa", hidden_ropa],
                                            "status": "approved", "updated_at": "2026-10-01"}]}]},
        "assessments": [],
        "controls": [{"id": hidden_control, "ref": "SECRET-CTRL", "implemented": True,
                      "mapped_to": [501], "proof": {"current": 1}},
                     {"id": visible_control, "ref": "VISIBLE-CTRL", "implemented": True,
                      "mapped_to": [502], "proof": {"current": 1}}],
        "proof": [{"id": hidden_proof, "version": 2, "verified": True}],
    }
    shown = decisions.present_manifest(system.db, user(system, "owner_a"), frozen)
    assert shown["checklist"]["steps"][0]["records"] == [{"restricted": True}]
    assert shown["controls"][0] == {"restricted": True}
    assert shown["proof"] == [{"restricted": True}]
    assert shown["controls"][1]["title"] == "Visible control"
    assert "mapped_to" not in shown["controls"][1] and "proof" not in shown["controls"][1]


def test_a_decision_in_a_hidden_system_is_a_404_for_every_read(system):
    row = ask(system)
    fail(lambda: decisions.get_decision(system.db, user(system, "dpo_b"), row["id"]), 404)
    fail(lambda: decisions.withdraw(system.db, user(system, "dpo_b"), row["id"]), 404)
    fail(lambda: decisions.revoke(system.db, user(system, "owner_b"), row["id"], "Because."), 404)
