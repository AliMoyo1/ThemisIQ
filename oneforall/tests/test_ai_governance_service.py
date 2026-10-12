"""
AI governance G2: intake, the AI profile, the inventory and the workspace, through the service layer.

What must hold, written out by hand and not computed by the code under test:

* staff describe a use and never write `applications`; only a reviewer promotes a request, and doing it twice, or two
  reviewers at once, still makes one application;
* a request is the author's, and a reviewer's only inside their business unit; to anyone else it does not exist;
* an answer that is stale (someone else changed it) is refused rather than overwritten;
* the inventory and every tab show a record only to someone who may open it in its own module, and say which of
  "nothing here", "not yours to see" and "could not be read" applies;
* retiring keeps everything; a decision about tier needs a reason and approves nothing.
"""
import json

import pytest

import modules.ai_governance.handlers  # noqa: F401  (registers the event handlers)
from core import events, rbac
from modules.ai_governance import rules, service, workspace
from modules.ai_governance.service import ServiceError
from modules.governance import relationships
from tests.test_platform_ownership import PERSONAS, _insert, world  # noqa: F401

APP = ("governance", "application")
GOOD = {"name": "Ticket summarizer", "purpose": "Summarize support tickets", "deployment": "vendor_service",
        "provider_name": "Acme AI", "data_categories": ["internal"], "intended_users": "Support agents"}
FULL = {**GOOD, "affected_people": ["none"], "autonomy": "assist_only", "affects_decisions": False, "external_access": False}


def commit(world, result=None, user=None):
    """What a route does after a successful step: commit, audit, deliver the events."""
    world.db.commit()
    if result is not None and user is not None:
        service.audit(user, result)
        service.deliver(result)
    return result


def user(world, name):
    return world.users[name]


def draft(world, name, answers=None, **kw):
    result = service.create_draft(world.db, user(world, name), {**GOOD, **(answers or {})}, **kw)
    commit(world, result, user(world, name))
    return result["intake"]


def submitted(world, name="employee_a", answers=None):
    row = draft(world, name, answers)
    result = service.submit(world.db, user(world, name), row["id"], row["version"])
    commit(world, result, user(world, name))
    return result["intake"]


def approve_new(world, intake, reviewer="dpo_a", **extra):
    result = service.approve(world.db, user(world, reviewer), intake["id"], intake["version"],
                            new_application=extra.pop("new_application", {}), **extra)
    commit(world, result, user(world, reviewer))
    return result


def count(world, table, where="1=1", params=()):
    return world.db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]


def apps(world):
    """Applications made by the test: a fresh database already holds one seeded 'Manual Process'."""
    return count(world, "applications", "name != %s", ("Manual Process",))


def fail(call, status):
    with pytest.raises(ServiceError) as caught:
        call()
    assert caught.value.status == status, (caught.value.status, caught.value.message)
    return caught.value


@pytest.fixture
def roles(world):
    """The personas' roles in the table the notification handler reads."""
    for index, (name, (role, _)) in enumerate(PERSONAS.items(), start=1):
        world.db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)", (index, role))
    world.db.commit()
    return world


# ── Drafts ──────────────────────────────────────────────────────────────────

def test_a_new_draft_starts_in_the_authors_unit_with_the_author_as_owner(world):
    row = draft(world, "employee_a")
    assert (row["status"], row["version"]) == ("draft", 1)
    assert row["answers"]["business_unit_id"] == world.unit["A"] and row["answers"]["owner_user_id"] == user(world, "employee_a")["id"]
    assert apps(world) == 0, "describing a use writes no application"


def test_the_same_idempotency_key_returns_the_draft_already_made(world):
    first = draft(world, "employee_a", idempotency_key="form-1")
    again = service.create_draft(world.db, user(world, "employee_a"), GOOD, idempotency_key="form-1")
    commit(world)
    assert again["created"] is False and again["intake"]["id"] == first["id"]
    assert count(world, "ai_use_intake_requests") == 1
    other = service.create_draft(world.db, user(world, "owner_a"), GOOD, idempotency_key="form-1")  # a different person
    assert other["created"] is True


@pytest.mark.parametrize("key", ["has space", "x" * 81, "semi;colon", "café"])
def test_a_bad_idempotency_key_is_refused(world, key):
    fail(lambda: service.create_draft(world.db, user(world, "employee_a"), GOOD, idempotency_key=key), 400)


def test_a_draft_needs_nothing_but_each_answer_is_checked(world):
    assert service.create_draft(world.db, user(world, "employee_a"), {})["created"]
    error = fail(lambda: service.create_draft(world.db, user(world, "employee_a"), {"deployment": "magic"}), 422)
    assert "deployment" in error.extra["errors"]


def test_a_unit_outside_the_authors_scope_is_refused(world):
    fail(lambda: service.create_draft(world.db, user(world, "employee_a"), {**GOOD, "business_unit_id": world.unit["B"]}), 400)
    row = service.create_draft(world.db, user(world, "employee_a"), {**GOOD, "business_unit_id": world.unit["A1"]})["intake"]
    assert row["business_unit_id"] == world.unit["A1"], "a unit below their own is fine"


def test_an_owner_must_be_an_active_person_of_the_organization(world):
    world.db.execute("INSERT INTO organizations (id, name, slug) VALUES (2, 'other', 'other')")
    stranger = _insert(world.db, "users", username="stranger", email="s@example.test", full_name="Stranger", password_hash="x", org_id=2)
    gone = _insert(world.db, "users", username="gone", email="g@example.test", full_name="Gone", password_hash="x", org_id=1, is_active=0)
    for owner in (stranger, gone, 9999):
        fail(lambda: service.create_draft(world.db, user(world, "employee_a"), {**GOOD, "owner_user_id": owner}), 400)


def test_only_a_person_who_may_submit_can_start_a_draft(world):
    outsider = {**user(world, "employee_a"), "roles": [rbac.EXTERNAL_AUDITOR]}
    fail(lambda: service.create_draft(world.db, outsider, GOOD), 403)


def test_a_draft_is_saved_with_the_version_the_person_was_looking_at(world):
    row = draft(world, "employee_a")
    saved = service.save_draft(world.db, user(world, "employee_a"), row["id"], {"purpose": "Changed"}, row["version"])
    commit(world)
    assert saved["intake"]["version"] == 2 and saved["intake"]["answers"]["purpose"] == "Changed"
    assert saved["intake"]["answers"]["name"] == "Ticket summarizer", "an answer not sent is kept"
    stale = fail(lambda: service.save_draft(world.db, user(world, "employee_a"), row["id"], {"purpose": "Lost"}, row["version"]), 409)
    assert stale.extra["current_version"] == 2
    fail(lambda: service.save_draft(world.db, user(world, "employee_a"), row["id"], {"purpose": "x"}, None), 400)


def test_nobody_but_the_author_can_edit_or_see_a_draft(world):
    row = draft(world, "employee_a")
    for other in ("owner_a", "dpo_a"):  # even a reviewer of the same unit cannot touch a draft that is not theirs
        fail(lambda: service.save_draft(world.db, user(world, other), row["id"], {"purpose": "x"}, 1), 404)
        fail(lambda: service.submit(world.db, user(world, other), row["id"], 1), 404)
    assert service.get_intake(world.db, user(world, "employee_a"), row["id"])["id"] == row["id"]


# ── Submitting ──────────────────────────────────────────────────────────────

def test_submitting_needs_the_required_answers_and_names_what_is_missing(world):
    row = draft(world, "employee_a", {"purpose": None, "intended_users": None})
    error = fail(lambda: service.submit(world.db, user(world, "employee_a"), row["id"], 1), 422)
    assert error.extra["missing"] == ["purpose", "intended_users"] and "purpose" in error.message
    assert service.get_intake(world.db, user(world, "employee_a"), row["id"])["status"] == "draft"


def test_a_submitted_request_is_screened_and_an_event_is_stored_with_it(world):
    result_row = submitted(world)
    assert result_row["status"] == "submitted" and result_row["submitted_at"]
    stored = world.db.execute("SELECT provisional_tier, tier_rule_version FROM ai_use_intake_requests WHERE id = %s", (result_row["id"],)).fetchone()
    assert (stored["provisional_tier"], stored["tier_rule_version"]) == ("needs_review", "v1"), "unanswered questions are never 'lower'"
    event = world.db.execute("SELECT event_type, status FROM events WHERE event_type = %s", (events.AI_USE_SUBMITTED,)).fetchone()
    assert event["status"] == "processed"


def test_submitting_again_changes_nothing_and_a_submitted_request_cannot_be_edited(world):
    row = submitted(world)
    again = service.submit(world.db, user(world, "employee_a"), row["id"], row["version"])
    commit(world)
    assert again["already"] is True and again["events"] == []
    assert count(world, "events", "event_type = %s", (events.AI_USE_SUBMITTED,)) == 1
    fail(lambda: service.save_draft(world.db, user(world, "employee_a"), row["id"], {"purpose": "x"}, row["version"]), 409)


def test_two_submits_with_the_same_version_store_one_event(world):
    row = draft(world, "employee_a")
    first = service.submit(world.db, user(world, "employee_a"), row["id"], row["version"])
    world.db.commit()
    second = service.submit(world.db, user(world, "employee_a"), row["id"], row["version"])
    assert second["already"] is True and first["events"] and not second["events"]


# ── Who can see a request ───────────────────────────────────────────────────

@pytest.mark.parametrize("name, sees", [
    ("employee_a", True), ("dpo_a", True), ("owner_a", True), ("super", True),
    ("dpo_a1", False), ("dpo_b", False), ("owner_b", False), ("dpo_no_unit", False)])
def test_a_request_is_visible_to_its_author_and_to_reviewers_in_its_unit_only(world, name, sees):
    row = submitted(world)
    if name == "employee_a":
        assert service.get_intake(world.db, user(world, name), row["id"])["id"] == row["id"]
        return
    if sees:
        assert service.get_intake(world.db, user(world, name), row["id"])["id"] == row["id"]
        assert [r["id"] for r in service.review_queue(world.db, user(world, name))] == [row["id"]]
    else:
        fail(lambda: service.get_intake(world.db, user(world, name), row["id"]), 404)
        assert service.review_queue(world.db, user(world, name)) == []


def test_an_organization_wide_request_reaches_every_reviewer_of_the_organization(world):
    org_wide = draft(world, "dpo_no_unit")
    result = service.submit(world.db, user(world, "dpo_no_unit"), org_wide["id"], 1)
    commit(world, result, user(world, "dpo_no_unit"))
    for name in ("dpo_no_unit", "super", "dpo_a", "dpo_b", "dpo_a1"):  # NULL is organization wide: every reviewer of the organization
        assert [r["id"] for r in service.review_queue(world.db, user(world, name))] == [org_wide["id"]], name


def test_the_queue_needs_the_review_capability(world):
    fail(lambda: service.review_queue(world.db, user(world, "employee_a")), 403)
    fail(lambda: service.approve(world.db, user(world, "employee_a"), 1, 1, new_application={}), 403)


def test_my_requests_lists_only_my_own(world):
    mine, theirs = draft(world, "employee_a"), draft(world, "owner_a")
    assert [r["id"] for r in service.list_mine(world.db, user(world, "employee_a"))] == [mine["id"]]
    assert [r["id"] for r in service.list_mine(world.db, user(world, "owner_a"))] == [theirs["id"]]
    assert service.list_mine(world.db, user(world, "employee_a"))[0]["author_name"] == "employee_a"


# ── Returning, rejecting ────────────────────────────────────────────────────

def test_a_returned_request_goes_back_to_its_author_who_changes_it_and_sends_it_again(world):
    row = submitted(world)
    fail(lambda: service.return_to_author(world.db, user(world, "dpo_a"), row["id"], "  ", row["version"]), 422)
    back = service.return_to_author(world.db, user(world, "dpo_a"), row["id"], "Say who the provider is.", row["version"])
    commit(world, back, user(world, "dpo_a"))
    assert back["intake"]["status"] == "returned" and back["intake"]["review_note"] == "Say who the provider is."
    edited = service.save_draft(world.db, user(world, "employee_a"), row["id"], {"provider_name": "Acme AI Ltd"}, back["intake"]["version"])
    again = service.submit(world.db, user(world, "employee_a"), row["id"], edited["intake"]["version"])
    commit(world, again, user(world, "employee_a"))
    assert again["intake"]["status"] == "submitted" and again["intake"]["review_note"] is None


def test_a_stale_review_is_refused_and_tells_the_reviewer_what_changed(world):
    row = submitted(world)
    service.return_to_author(world.db, user(world, "dpo_a"), row["id"], "Not enough.", row["version"])
    world.db.commit()
    stale = fail(lambda: service.reject(world.db, user(world, "owner_a"), row["id"], "No.", row["version"]), 409)
    assert stale.extra["status_now"] == "returned"


def test_a_rejected_request_is_final(world):
    row = submitted(world)
    fail(lambda: service.reject(world.db, user(world, "dpo_a"), row["id"], "", row["version"]), 422)
    rejected = service.reject(world.db, user(world, "dpo_a"), row["id"], "Out of scope.", row["version"])
    commit(world, rejected, user(world, "dpo_a"))
    assert rejected["intake"]["status"] == "rejected"
    fail(lambda: service.submit(world.db, user(world, "employee_a"), row["id"], rejected["intake"]["version"]), 409)
    fail(lambda: service.approve(world.db, user(world, "dpo_a"), row["id"], rejected["intake"]["version"], new_application={}), 409)


# ── Promoting into the inventory ────────────────────────────────────────────

def test_accepting_a_request_creates_one_application_and_its_profile(world):
    row = submitted(world, answers=FULL)
    assert apps(world) == 0
    done = approve_new(world, row, new_application={"vendor_name": "Acme AI", "criticality": "high"})
    app = world.db.execute("SELECT * FROM applications WHERE id = %s", (done["application_id"],)).fetchone()
    assert (app["name"], app["is_active"], app["criticality"], app["business_unit_id"], app["owner_user_id"]) == (
        "Ticket summarizer", 1, "high", world.unit["A"], user(world, "employee_a")["id"])
    assert app["vendor_id"] and app["application_type"] == "AI system"
    profile = service.get_profile(world.db, user(world, "dpo_a"), done["application_id"])
    assert (profile["purpose"], profile["provider_note"], profile["data_categories"], profile["tier"]) == (
        "Summarize support tickets", "Acme AI", ["internal"], "lower")
    assert done["intake"]["status"] == "approved" and done["intake"]["application_id"] == done["application_id"]


def test_accepting_the_same_request_twice_or_at_once_still_makes_one_application(world):
    row = submitted(world)
    first = approve_new(world, row)
    again = service.approve(world.db, user(world, "dpo_a"), row["id"], row["version"], new_application={})
    world.db.commit()
    assert again["already"] is True and again["application_id"] == first["application_id"] and again["created_application"] is False
    # a second reviewer who was looking at the same version, a moment later
    later = service.approve(world.db, user(world, "owner_a"), row["id"], row["version"], new_application={})
    assert later["application_id"] == first["application_id"]
    assert apps(world) == 1 and count(world, "ai_use_profiles") == 1


def test_a_step_that_fails_after_the_claim_leaves_the_request_waiting(world):
    row = submitted(world)
    fail(lambda: service.approve(world.db, user(world, "dpo_a"), row["id"], row["version"],
                                 new_application={"owner_user_id": 9999}), 400)
    world.db.rollback()  # the route rolls back; nothing of the half-done step stays
    assert service.get_intake(world.db, user(world, "dpo_a"), row["id"])["status"] == "submitted"
    assert apps(world) == 0 and count(world, "ai_use_profiles") == 0


def test_accepting_can_link_an_application_that_already_exists(world):
    existing = _insert(world.db, "applications", name="Existing tool", business_unit_id=world.unit["A"], is_active=1)
    row = submitted(world)
    done = service.approve(world.db, user(world, "dpo_a"), row["id"], row["version"], application_id=existing)
    commit(world, done, user(world, "dpo_a"))
    assert done["application_id"] == existing and done["created_application"] is False
    assert apps(world) == 1
    assert service.get_profile(world.db, user(world, "dpo_a"), existing)["purpose"] == "Summarize support tickets"


def test_linking_needs_a_visible_application_without_a_profile(world):
    hidden = _insert(world.db, "applications", name="Unit B tool", business_unit_id=world.unit["B"], is_active=1)
    taken = _insert(world.db, "applications", name="Has profile", business_unit_id=world.unit["A"], is_active=1)
    first = submitted(world)
    fail(lambda: service.approve(world.db, user(world, "dpo_a"), first["id"], first["version"], application_id=hidden), 404)
    fail(lambda: service.approve(world.db, user(world, "dpo_a"), first["id"], first["version"], application_id=987654), 404)
    second = approve_new(world, submitted(world, answers={"name": "Other"}))
    error = fail(lambda: service.approve(world.db, user(world, "dpo_a"), first["id"], first["version"],
                                         application_id=second["application_id"]), 409)
    assert error.extra["application_id"] == second["application_id"]
    fail(lambda: service.approve(world.db, user(world, "dpo_a"), first["id"], first["version"]), 400)
    fail(lambda: service.approve(world.db, user(world, "dpo_a"), first["id"], first["version"], application_id=taken, new_application={}), 400)


def test_a_reviewer_cannot_place_an_application_in_a_unit_they_cannot_see(world):
    row = submitted(world)
    fail(lambda: service.approve(world.db, user(world, "dpo_a"), row["id"], row["version"],
                                 new_application={"business_unit_id": world.unit["B"]}), 400)
    world.db.rollback()
    assert apps(world) == 0


def test_a_tier_the_reviewer_adopts_needs_a_reason_and_is_kept_apart_from_the_provisional_one(world):
    row = submitted(world, answers=FULL)
    fail(lambda: service.approve(world.db, user(world, "dpo_a"), row["id"], row["version"], new_application={}, adopted_tier="elevated"), 422)
    world.db.rollback()
    fail(lambda: service.approve(world.db, user(world, "dpo_a"), row["id"], row["version"], new_application={}, adopted_tier="needs_review", tier_reason="x" * 5), 422)
    world.db.rollback()
    done = approve_new(world, row, adopted_tier="moderate", tier_reason="Vendor sees ticket text.")
    profile = service.get_profile(world.db, user(world, "dpo_a"), done["application_id"])
    assert (profile["provisional_tier"], profile["adopted_tier"], profile["tier"]) == ("lower", "moderate", "moderate")
    assert profile["adopted_tier_reason"] == "Vendor sees ticket text." and profile["adopted_by"] == user(world, "dpo_a")["id"]


def test_the_audit_records_each_step_and_notes_a_reviewer_who_accepts_their_own_request(world):
    row = submitted(world, "dpo_a")
    approve_new(world, row, reviewer="dpo_a")
    actions = [(r["action"], r["details"]) for r in world.db.execute(
        "SELECT action, details FROM audit_log WHERE module = 'ai_governance' ORDER BY id").fetchall()]
    assert [a for a, _ in actions] == ["ai_use_draft_created", "ai_use_submitted", "ai_use_approved", "application_created", "ai_profile_created"]
    assert "accepted their own request" in dict(actions)["ai_use_approved"]


# ── The profile ─────────────────────────────────────────────────────────────

@pytest.fixture
def system(world):
    """An accepted AI use in unit A, and the profile as the reviewer sees it."""
    row = submitted(world, answers=FULL)
    done = approve_new(world, row)
    world.app = done["application_id"]
    return world


def test_a_profile_is_visible_only_inside_the_unit_of_its_application(system):
    for name, sees in (("dpo_a", True), ("employee_a", True), ("owner_a", True), ("dpo_a1", False), ("dpo_b", False), ("dpo_no_unit", False), ("super", True)):
        shown = service.get_profile(system.db, user(system, name), system.app)
        assert (shown is not None) == sees, name


def test_a_reviewer_edits_the_profile_and_the_tier_is_read_again(system):
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    edited = service.update_profile(system.db, user(system, "dpo_a"), system.app, {"data_categories": ["personal"], "external_access": True}, profile["version"])
    commit(system, edited, user(system, "dpo_a"))
    assert edited["profile"]["tier"] == "moderate" and edited["profile"]["version"] == profile["version"] + 1
    assert {r["rule"] for r in edited["profile"]["tier_reasons"]} == {"M1", "M2"}
    material = system.db.execute("SELECT status FROM events WHERE event_type = %s", (events.AI_USE_MATERIAL_CHANGE,)).fetchone()
    assert material["status"] == "processed", "a covered fact changed, so a later decision can tell"


def test_a_change_to_a_fact_no_decision_covers_is_not_material(system):
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    edited = service.update_profile(system.db, user(system, "dpo_a"), system.app, {"human_oversight": "The team lead"}, profile["version"])
    commit(system, edited, user(system, "dpo_a"))
    assert edited["events"] == [] and edited["profile"]["fingerprint"] == profile["fingerprint"]
    assert count(system, "events", "event_type = %s", (events.AI_USE_MATERIAL_CHANGE,)) == 0


def test_an_edit_keeps_the_adopted_tier_and_refuses_a_stale_version(system):
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    adopted = service.adopt_tier(system.db, user(system, "dpo_a"), system.app, "elevated", "Customer facing.", profile["version"])
    commit(system, adopted, user(system, "dpo_a"))
    fail(lambda: service.update_profile(system.db, user(system, "dpo_a"), system.app, {"purpose": "x"}, profile["version"]), 409)
    fresh = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    edited = service.update_profile(system.db, user(system, "dpo_a"), system.app, {"autonomy": "decide_automatically", "affected_people": ["customers"]}, fresh["version"])
    assert edited["profile"]["provisional_tier"] == "elevated" and edited["profile"]["adopted_tier"] == "elevated"
    fail(lambda: service.adopt_tier(system.db, user(system, "dpo_a"), system.app, "lower", "", edited["profile"]["version"]), 422)
    fail(lambda: service.adopt_tier(system.db, user(system, "dpo_a"), system.app, "needs_review", "because", edited["profile"]["version"]), 422)
    fail(lambda: service.adopt_tier(system.db, user(system, "dpo_a"), system.app, "lower", "because", 1), 409)


def test_the_review_cadence_sets_the_next_review_and_marking_reviewed_moves_it(system):
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    fail(lambda: service.update_profile(system.db, user(system, "dpo_a"), system.app, {"purpose": "x", "review_cadence_months": 0}, profile["version"]), 422)
    edited = service.update_profile(system.db, user(system, "dpo_a"), system.app, {"purpose": "x", "review_cadence_months": 6}, profile["version"])
    assert edited["profile"]["next_review_at"] and edited["profile"]["review_cadence_months"] == 6
    system.db.execute("UPDATE ai_use_profiles SET next_review_at = '2000-01-01' WHERE application_id = %s", (system.app,))
    reviewed = service.mark_reviewed(system.db, user(system, "dpo_a"), system.app)
    assert reviewed["profile"]["next_review_at"] > "2026-01-01"


def test_only_a_reviewer_may_change_a_profile_and_a_hidden_one_does_not_exist(system):
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    fail(lambda: service.update_profile(system.db, user(system, "employee_a"), system.app, {"purpose": "x"}, profile["version"]), 403)
    fail(lambda: service.adopt_tier(system.db, user(system, "employee_a"), system.app, "lower", "because", profile["version"]), 403)
    fail(lambda: service.update_profile(system.db, user(system, "dpo_b"), system.app, {"purpose": "x"}, profile["version"]), 404)
    fail(lambda: service.mark_reviewed(system.db, user(system, "dpo_b"), system.app), 404)
    fail(lambda: service.retire(system.db, user(system, "dpo_b"), system.app, "because"), 404)


def test_a_profile_can_be_added_to_an_application_that_has_none(world):
    plain = _insert(world.db, "applications", name="Plain app", business_unit_id=world.unit["A"], is_active=1)
    created = service.create_profile(world.db, user(world, "dpo_a"), plain, {"purpose": "Search", "data_categories": ["public"]})
    commit(world, created, user(world, "dpo_a"))
    assert created["profile"]["purpose"] == "Search" and created["profile"]["tier"] == "needs_review"
    fail(lambda: service.create_profile(world.db, user(world, "dpo_a"), plain, {}), 409)
    fail(lambda: service.create_profile(world.db, user(world, "dpo_b"), plain, {}), 404)


# ── Retiring ────────────────────────────────────────────────────────────────

def test_retiring_keeps_the_application_and_takes_it_out_of_the_active_inventory(system):
    fail(lambda: service.retire(system.db, user(system, "dpo_a"), system.app, " "), 422)
    retired = service.retire(system.db, user(system, "dpo_a"), system.app, "Contract ended.")
    commit(system, retired, user(system, "dpo_a"))
    row = system.db.execute("SELECT is_active, retired_reason, retired_by FROM applications WHERE id = %s", (system.app,)).fetchone()
    assert (row["is_active"], row["retired_reason"], row["retired_by"]) == (0, "Contract ended.", user(system, "dpo_a")["id"])
    assert count(system, "ai_use_profiles") == 1, "its history stays"
    assert workspace.list_systems(system.db, user(system, "dpo_a"))["total"] == 0
    assert workspace.list_systems(system.db, user(system, "dpo_a"), state="retired")["total"] == 1
    fail(lambda: service.retire(system.db, user(system, "dpo_a"), system.app, "Again."), 409)
    restored = service.restore(system.db, user(system, "dpo_a"), system.app)
    commit(system, restored, user(system, "dpo_a"))
    assert workspace.list_systems(system.db, user(system, "dpo_a"))["total"] == 1
    fail(lambda: service.restore(system.db, user(system, "dpo_a"), system.app), 409)


# ── Duplicate suggestions ───────────────────────────────────────────────────

def test_a_use_that_may_already_exist_is_suggested_with_the_reason(world):
    same = _insert(world.db, "applications", name="Ticket Summarizer", business_unit_id=world.unit["A"], is_active=1)
    similar = _insert(world.db, "applications", name="Ticket Summarizer Pro", business_unit_id=world.unit["A"], is_active=1)
    provider = _insert(world.db, "applications", name="Totally different", business_unit_id=world.unit["A"], is_active=1,
                       vendor_id=_insert(world.db, "canonical_vendors", name="Acme AI"))
    _insert(world.db, "applications", name="Ticket Summarizer (old)", business_unit_id=world.unit["A"], is_active=0)
    _insert(world.db, "applications", name="Ticket Summarizer Unit B", business_unit_id=world.unit["B"], is_active=1)
    found = service.find_duplicates(world.db, user(world, "employee_a"), "ticket summarizer", "acme ai")
    assert [(f["id"], f["reason"]) for f in found] == [(same, "Same name"), (similar, "Similar name"), (provider, "Same provider")]
    assert service.find_duplicates(world.db, user(world, "employee_a"), "ab") == []
    assert service.find_duplicates(world.db, user(world, "employee_a"), "zzz unlike") == []
    hidden = service.find_duplicates(world.db, user(world, "dpo_b"), "ticket summarizer")
    assert [f["name"] for f in hidden] == ["Ticket Summarizer Unit B"], "a unit B reviewer sees unit B's, never unit A's"


def test_the_reviewers_search_for_an_application_to_link_is_scoped_and_skips_ai_uses(world):
    visible = _insert(world.db, "applications", name="Payroll system", business_unit_id=world.unit["A"], is_active=1)
    _insert(world.db, "applications", name="Payroll hidden", business_unit_id=world.unit["B"], is_active=1)
    already = _insert(world.db, "applications", name="Payroll AI", business_unit_id=world.unit["A"], is_active=1)
    service.create_profile(world.db, user(world, "dpo_a"), already, {})
    world.db.commit()
    assert [a["name"] for a in service.search_applications(world.db, user(world, "dpo_a"), "payroll")] == ["Payroll system"]
    assert service.search_applications(world.db, user(world, "dpo_a"), "p") == []
    fail(lambda: service.search_applications(world.db, user(world, "employee_a"), "payroll"), 403)
    assert visible


# ── Events and who is told ──────────────────────────────────────────────────

def _notified(world, event_type=None):
    rows = world.db.execute("SELECT n.user_id, n.title, n.link, u.username FROM notifications n JOIN users u ON u.id = n.user_id "
                            "WHERE n.module = 'ai_governance' ORDER BY n.id").fetchall()
    return [(r["username"], r["title"], r["link"]) for r in rows]


def test_a_submission_tells_the_reviewers_who_may_see_it_and_nobody_else(roles):
    submitted(roles)
    told = {name for name, _, _ in _notified(roles)}
    assert told == {"dpo_a", "owner_a"}, "reviewers of unit A; not the author, not other units, not a reviewer with no unit"


def test_delivering_the_same_event_twice_tells_nobody_twice(roles):
    row = submitted(roles)
    event = roles.db.execute("SELECT id FROM events WHERE event_type = %s", (events.AI_USE_SUBMITTED,)).fetchone()["id"]
    before = len(_notified(roles))
    roles.db.execute("UPDATE events SET status = 'pending' WHERE id = %s", (event,))
    roles.db.execute("DELETE FROM event_deliveries WHERE event_id = %s", (event,))
    roles.db.commit()
    events.deliver(event)
    assert len(_notified(roles)) == before and row["id"]


def test_the_author_hears_what_the_reviewer_decided_and_where_to_go_next(roles):
    row = submitted(roles)
    returned = service.return_to_author(roles.db, user(roles, "dpo_a"), row["id"], "Add the provider.", row["version"])
    commit(roles, returned, user(roles, "dpo_a"))
    again = service.submit(roles.db, user(roles, "employee_a"), row["id"], returned["intake"]["version"])
    commit(roles, again, user(roles, "employee_a"))
    done = service.approve(roles.db, user(roles, "dpo_a"), row["id"], again["intake"]["version"], new_application={})
    commit(roles, done, user(roles, "dpo_a"))
    for_author = [(t, l) for name, t, l in _notified(roles) if name == "employee_a"]
    assert for_author == [("Your AI use request needs changes", f"/ai-governance/requests/{row['id']}"),
                          ("Your AI use request was accepted", f"/ai-governance/systems/{done['application_id']}")]
    assert not [n for n in _notified(roles) if n[0] == "dpo_a" and "accepted" in n[1]], "the reviewer is not told of their own decision"


# ── The inventory ───────────────────────────────────────────────────────────

@pytest.fixture
def inventory(world):
    """AI uses in unit A, A1, B and the whole organization, each with a profile."""
    rows = {}
    for tag, owner in (("A", "owner_a"), ("A1", None), ("B", "owner_b"), ("org", None)):
        app = _insert(world.db, "applications", name=f"Use {tag}", business_unit_id=world.unit[tag], is_active=1,
                      owner_user_id=user(world, owner)["id"] if owner else None)
        service.create_profile(world.db, user(world, "super"), app, {**FULL, "purpose": f"Purpose {tag}"})
        rows[tag] = app
    world.db.commit()
    world.apps = rows
    return world


@pytest.mark.parametrize("name, tags", [
    ("super", {"A", "A1", "B", "org"}), ("dpo_a", {"A", "A1", "org"}), ("employee_a", {"A", "A1", "org"}),
    ("dpo_a1", {"A1", "org"}), ("dpo_b", {"B", "org"}), ("dpo_no_unit", {"org"})])
def test_the_inventory_lists_exactly_the_uses_the_person_may_open(inventory, name, tags):
    listed = workspace.list_systems(inventory.db, user(inventory, name), page_size=100)
    assert {i["id"] for i in listed["items"]} == {inventory.apps[t] for t in tags}
    assert listed["total"] == len(tags), "the count is the visible count"


def test_the_inventory_needs_the_view_capability(inventory):
    outsider = {**user(inventory, "employee_a"), "roles": [rbac.EXTERNAL_AUDITOR]}
    fail(lambda: workspace.list_systems(inventory.db, outsider), 403)


def test_filters_narrow_the_list_and_never_widen_it(inventory):
    me = user(inventory, "dpo_a")
    assert workspace.list_systems(inventory.db, me, q="purpose a")["total"] == 2   # "Purpose A" and "Purpose A1"
    assert workspace.list_systems(inventory.db, me, owner_id=user(inventory, "owner_a")["id"])["total"] == 1
    assert workspace.list_systems(inventory.db, me, owner_id=user(inventory, "owner_b")["id"])["total"] == 0, "unit B's owner is a filter, not a way in"
    assert workspace.list_systems(inventory.db, me, bu_id=inventory.unit["B"])["total"] == 0
    assert workspace.list_systems(inventory.db, me, tier="lower")["total"] == 3
    assert workspace.list_systems(inventory.db, me, tier="elevated")["total"] == 0
    assert workspace.list_systems(inventory.db, me, state="needs_action")["total"] == 2, "uses with no owner"
    inventory.db.execute("UPDATE ai_use_profiles SET next_review_at = '2000-01-01' WHERE application_id = %s", (inventory.apps["A"],))
    assert [i["name"] for i in workspace.list_systems(inventory.db, me, state="review_due")["items"]] == ["Use A"]
    assert "Review due" in workspace.list_systems(inventory.db, me, q="Use A", sort="review")["items"][0]["needs_action"]


def test_the_list_is_paged_sorted_and_bounded(inventory):
    me = user(inventory, "super")
    first = workspace.list_systems(inventory.db, me, page_size=3, sort="name")
    second = workspace.list_systems(inventory.db, me, page_size=3, page=2, sort="name")
    assert (first["total"], first["pages"], len(first["items"]), len(second["items"])) == (4, 2, 3, 1)
    assert [i["name"] for i in first["items"] + second["items"]] == ["Use A", "Use A1", "Use B", "Use org"]
    for bad in ({"page_size": 0}, {"page_size": 101}, {"sort": "owner"}, {"state": "gone"}, {"tier": "high"}, {"capability_type": "magic"}):
        fail(lambda: workspace.list_systems(inventory.db, me, **bad), 400)
    assert workspace.list_systems(inventory.db, me, page=-4)["page"] == 1


def test_a_search_with_wildcards_matches_them_literally(inventory):
    me = user(inventory, "super")
    assert workspace.list_systems(inventory.db, me, q="%")["total"] == 0
    assert workspace.list_systems(inventory.db, me, q="_")["total"] == 0


def test_the_filter_choices_name_only_what_the_person_may_open(inventory):
    choices = workspace.filter_choices(inventory.db, user(inventory, "dpo_a"))
    assert {o["name"] for o in choices["owners"]} == {"owner_a"} and {u["name"] for u in choices["business_units"]} == {"Unit A", "Unit A1"}
    assert "Unit B" not in json.dumps(choices) and "owner_b" not in json.dumps(choices)


# ── The workspace ───────────────────────────────────────────────────────────

def test_the_workspace_opens_for_a_visible_use_and_not_for_a_hidden_one(inventory):
    shown = workspace.get_system(inventory.db, user(inventory, "dpo_a"), inventory.apps["A"])
    assert shown["application"]["name"] == "Use A" and shown["profile"]["purpose"] == "Purpose A" and shown["can"]["review"] is True
    assert workspace.get_system(inventory.db, user(inventory, "dpo_a"), inventory.apps["B"]) is None
    assert workspace.get_system(inventory.db, user(inventory, "dpo_a"), 987654) is None
    assert workspace.get_tab(inventory.db, user(inventory, "dpo_a"), inventory.apps["B"], "assessments") is None
    fail(lambda: workspace.get_tab(inventory.db, user(inventory, "dpo_a"), inventory.apps["A"], "secrets"), 404)
    assert workspace.get_system(inventory.db, user(inventory, "employee_a"), inventory.apps["A"])["can"]["review"] is False


def test_an_application_with_no_profile_still_opens_and_offers_to_add_one(world):
    plain = _insert(world.db, "applications", name="Plain", business_unit_id=world.unit["A"], is_active=1)
    shown = workspace.get_system(world.db, user(world, "dpo_a"), plain)
    assert shown["profile"] is None and shown["next_actions"][0]["text"].startswith("Name an owner")
    assert any("AI profile" in a["text"] for a in shown["next_actions"])


def test_the_next_steps_follow_what_is_missing(inventory):
    shown = workspace.get_system(inventory.db, user(inventory, "dpo_a"), inventory.apps["A1"])
    assert [a["text"] for a in shown["next_actions"]] == ["Name an owner for this use."]


@pytest.fixture
def tabs(inventory):
    """Linked records of every kind, in the unit of the use and in another unit."""
    db, unit, app = inventory.db, inventory.unit, inventory.apps["A"]
    inventory.aiia = _insert(db, "sentinel_aiia", ref_number="AIIA-1", title="Impact of Use A", business_unit_id=unit["A"], application_id=app, status="draft")
    _insert(db, "sentinel_aiia", ref_number="AIIA-B", title="Hidden impact", business_unit_id=unit["B"], application_id=app, status="draft")
    inventory.dpia = _insert(db, "sentinel_dpias", ref_number="DPIA-1", title="DPIA for Use A", business_unit_id=unit["A"])
    inventory.aims = _insert(db, "aims_assessments", ref="AIMS-1", title="AI management A", business_unit_id=unit["A"], application_id=app)
    inventory.asset = _insert(db, "data_assets", name="Ticket archive", business_unit_id=unit["A"], application_id=app, classification="internal", contains_pii=1)
    _insert(db, "data_assets", name="Other unit asset", business_unit_id=unit["B"], application_id=app)
    inventory.process = _insert(db, "business_processes", name="Support desk", business_unit_id=unit["A"])
    inventory.vendor = _insert(db, "canonical_vendors", name="Acme AI")
    db.execute("UPDATE applications SET vendor_id = %s WHERE id = %s", (inventory.vendor, app))
    inventory.item = _insert(db, "evidence_items", title="Vendor SOC 2", status="current", business_unit_id=unit["A"], org_id=1, version=2, expiry_date="2000-01-01")
    inventory.hidden_item = _insert(db, "evidence_items", title="Unit B proof", status="current", business_unit_id=unit["B"], org_id=1)
    for item in (inventory.item, inventory.hidden_item):
        _insert(db, "evidence_links", evidence_id=item, module="governance", entity_type="application", entity_id=app)
    dpo = user(inventory, "dpo_a")
    for source, target, verb in ((("sentinel", "dpia", inventory.dpia), ("governance", "application", app), "assesses"),
                                 (("governance", "application", app), ("governance", "process", inventory.process), "supports")):
        relationships.create_link(db, dpo, source, target, verb)
    db.commit()
    inventory.app = app
    return inventory


def _items(tab, section=None):
    sections = tab["sections"]
    section = next(s for s in sections if s["title"] == section) if section else sections[0]
    return section["state"], [i["title"] for i in section["items"]]


def test_the_assessments_tab_shows_linked_assessments_the_viewer_may_open(tabs):
    tab = workspace.get_tab(tabs.db, user(tabs, "dpo_a"), tabs.app, "assessments")
    assert _items(tab, "AI impact assessments") == ("ok", ["AIIA-1: Impact of Use A"])
    assert _items(tab, "Privacy assessments linked to this use") == ("ok", ["DPIA for Use A"])
    assert "Hidden impact" not in json.dumps(tab)


def test_the_assessments_tab_says_so_when_the_viewer_has_no_right_to_privacy_records(tabs):
    tab = workspace.get_tab(tabs.db, user(tabs, "employee_a"), tabs.app, "assessments")
    assert [s["state"] for s in tab["sections"]] == ["no_access"] and "AIIA-1" not in json.dumps(tab) and "Impact of Use A" not in json.dumps(tab)


def test_the_risks_tab_shows_management_assessments_and_says_no_access_to_those_without_the_module(tabs):
    owner = workspace.get_tab(tabs.db, user(tabs, "owner_a"), tabs.app, "risks_controls")
    assert _items(owner, "AI management assessments") == ("ok", ["AIMS-1: AI management A"])
    dpo = workspace.get_tab(tabs.db, user(tabs, "dpo_a"), tabs.app, "risks_controls")
    assert dpo["sections"][0]["state"] == "no_access"


def test_the_data_and_vendors_tab_shows_provider_assets_and_processes_in_scope(tabs):
    tab = workspace.get_tab(tabs.db, user(tabs, "dpo_a"), tabs.app, "data_vendors")
    assert _items(tab, "Provider") == ("ok", ["Acme AI"])
    assert _items(tab, "Data it uses") == ("ok", ["Ticket archive"])
    assert _items(tab, "Processes it supports") == ("ok", ["Support desk"])
    assert "Other unit asset" not in json.dumps(tab)
    asset = next(s for s in tab["sections"] if s["title"] == "Data it uses")["items"][0]
    assert asset["status"] == "internal" and asset["subtitle"] == "Contains personal data"


def test_the_evidence_tab_shows_attached_items_with_expiry_and_hides_other_units_proof(tabs):
    tab = workspace.get_tab(tabs.db, user(tabs, "dpo_a"), tabs.app, "evidence")
    [item] = tab["sections"][0]["items"]
    assert (item["title"], item["status"], item["subtitle"]) == ("Vendor SOC 2", "Expired", "Version 2, expires 2000-01-01")
    assert "Unit B proof" not in json.dumps(tab)
    nothing = workspace.get_tab(tabs.db, user(tabs, "dpo_b"), tabs.apps["org"], "evidence")
    assert nothing["sections"][0]["state"] == "empty"


def test_the_decisions_and_monitoring_tabs_say_plainly_that_nothing_is_recorded_or_measured(tabs):
    decisions_tab = workspace.get_tab(tabs.db, user(tabs, "dpo_a"), tabs.app, "decisions")
    assert decisions_tab["state"] == "ok"
    assert decisions_tab["sections"][0]["note"] == "No decision has been recorded for this use."
    assert decisions_tab["sections"][0]["items"] == []
    monitoring_tab = workspace.get_tab(tabs.db, user(tabs, "dpo_a"), tabs.app, "monitoring")
    assert monitoring_tab["state"] == "ok"
    assert any(section["state"] == "not_measured" for section in monitoring_tab["sections"])


def test_the_activity_tab_lists_what_was_done_to_the_use(system):
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    edited = service.update_profile(system.db, user(system, "dpo_a"), system.app, {"purpose": "Changed"}, profile["version"])
    commit(system, edited, user(system, "dpo_a"))
    tab = workspace.get_tab(system.db, user(system, "dpo_a"), system.app, "activity")
    assert "AI profile edited" in _items(tab)[1] and "Accepted into the inventory" in _items(tab)[1]


def test_a_source_that_fails_is_unavailable_and_never_shown_as_empty(tabs, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("the table is gone")
    monkeypatch.setattr(relationships, "list_links", broken)
    tab = workspace.get_tab(tabs.db, user(tabs, "dpo_a"), tabs.app, "assessments")
    states = {s["title"]: s["state"] for s in tab["sections"]}
    assert states["AI impact assessments"] == "ok" and states["Privacy assessments linked to this use"] == "unavailable"
    assert "may not be" in tab["sections"][1]["note"]


# ── Linking from the workspace ──────────────────────────────────────────────

def test_the_link_kinds_come_from_the_rules_the_service_enforces(world):
    kinds = workspace.link_kinds()
    assert {"verb": "assesses", "label": "assessed by", "direction": "incoming", "module": "sentinel", "type": "aiia"} in kinds
    assert {"verb": "uses_data", "label": "uses data", "direction": "outgoing", "module": "governance", "type": "data_asset"} in kinds
    for k in kinds:
        source, target = ((k["module"], k["type"]), APP) if k["direction"] == "incoming" else (APP, (k["module"], k["type"]))
        assert (source, target) in relationships.PAIR_RULES[k["verb"]], k


def test_link_candidates_are_the_records_of_that_kind_the_viewer_may_open(tabs):
    found = workspace.link_candidates(tabs.db, user(tabs, "dpo_a"), tabs.app, "assesses", "sentinel", "aiia")
    assert [c["title"] for c in found] == ["Impact of Use A"]
    assert workspace.link_candidates(tabs.db, user(tabs, "dpo_a"), tabs.app, "assesses", "sentinel", "aiia", q="hidden") == []
    assert [c["title"] for c in workspace.link_candidates(tabs.db, user(tabs, "dpo_b"), tabs.apps["org"], "assesses", "sentinel", "aiia")] == ["Hidden impact"]
    fail(lambda: workspace.link_candidates(tabs.db, user(tabs, "dpo_a"), tabs.app, "assesses", "grid", "audit"), 400)
    fail(lambda: workspace.link_candidates(tabs.db, user(tabs, "dpo_a"), tabs.apps["B"], "assesses", "sentinel", "aiia"), 404)
    assert workspace.link_candidates(tabs.db, user(tabs, "employee_a"), tabs.app, "assesses", "sentinel", "aiia") == [],         "someone with no right to privacy records is offered none"
