"""
AI governance G3b: the AI impact assessment (AIIA) through the service layer, moved here from Sentinel.

Written out by hand. The classification, dimension and cascade tests are the ones the Sentinel screen's service had
(`tests/test_aiia.py` before the move), with the same assertions. The rest closes what that service did not do:

* a new assessment is filed in a unit, never silently organization wide;
* what an assessment points at (a system, a unit, a RoPA, a DPIA) must be something its writer may open, and a privacy
  record the reader may not open is not named;
* two people editing one assessment do not overwrite each other, and every change is audited;
* an approved assessment is not deleted, and completing one raises one event;
* an assessment in another unit does not exist for a reader or a writer.
"""
import json
import re

import pytest

from core import rbac
from modules.ai_governance import assessments
from tests.test_ai_governance_service import commit, count, fail, user
from tests.test_platform_ownership import PERSONAS, _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401

READERS_AND_WRITERS = (rbac.SUPER_ADMIN, rbac.DPO, rbac.PRIVACY_ANALYST, rbac.COMPLIANCE_MGR, rbac.GRC_OFFICER,
                       rbac.RISK_OWNER, rbac.ORG_ADMIN)
CONFIGURERS = (rbac.SUPER_ADMIN, rbac.DPO, rbac.PRIVACY_ANALYST, rbac.ORG_ADMIN)
OTHERS = (rbac.EMPLOYEE, rbac.EXTERNAL_AUDITOR)


def as_role(world, role, name="dpo_a"):
    return {**world.users[name], "roles": [role], "is_super_admin": 1 if role == rbac.SUPER_ADMIN else 0}


def make(world, name="dpo_a", **fields):
    done = assessments.create_assessment(world.db, user(world, name), {"title": "Churn model", **fields})
    commit(world, done, user(world, name))
    return done["assessment"]


def edit(world, row, changes, name="dpo_a", version=None):
    done = assessments.update_assessment(world.db, user(world, name), row["id"], changes, version or row["version"])
    commit(world, done, user(world, name))
    return done


def audit_actions(world):
    return [r[0] for r in world.db.execute("SELECT action FROM audit_log WHERE action LIKE 'ai_%' ORDER BY id").fetchall()]


# ── Who may read, write and configure ───────────────────────────────────────

@pytest.mark.parametrize("role", READERS_AND_WRITERS)
def test_the_privacy_team_and_the_people_who_review_ai_uses_may_read_and_write(role):
    who = {"roles": [role], "is_super_admin": 1 if role == rbac.SUPER_ADMIN else 0}
    assert rbac.has_capability(who, "ai_assessment.view") and rbac.has_capability(who, "ai_assessment.manage")
    assert rbac.has_capability(who, "ai_assessment.configure") == (role in CONFIGURERS)


@pytest.mark.parametrize("role", OTHERS)
def test_staff_and_outside_auditors_hold_none_of_the_three(role):
    who = {"roles": [role], "is_super_admin": 0}
    for capability in ("ai_assessment.view", "ai_assessment.manage", "ai_assessment.configure"):
        assert not rbac.has_capability(who, capability)


def test_every_operation_checks_its_capability_before_it_looks_at_a_record(world):
    row = make(world)
    staff = user(world, "staff_a")
    fail(lambda: assessments.list_assessments(world.db, staff), 403)
    fail(lambda: assessments.get_assessment(world.db, staff, row["id"]), 403)
    fail(lambda: assessments.create_assessment(world.db, staff, {"title": "x"}), 403)
    fail(lambda: assessments.update_assessment(world.db, staff, row["id"], {"title": "x"}, 1), 403)
    fail(lambda: assessments.delete_assessment(world.db, staff, row["id"]), 403)
    fail(lambda: assessments.list_dimensions(world.db, staff), 403)
    fail(lambda: assessments.save_dimensions(world.db, staff, []), 403)
    fail(lambda: assessments.link_options(world.db, staff, "ropa"), 403)
    # reading is not configuring: a compliance manager reads dimensions and may not change them
    manager = as_role(world, rbac.COMPLIANCE_MGR)
    assert assessments.list_dimensions(world.db, manager)
    fail(lambda: assessments.save_dimensions(world.db, manager, [{"name": "Safety"}]), 403)


# ── Creating ────────────────────────────────────────────────────────────────

def test_a_new_assessment_is_a_draft_in_the_authors_unit_with_a_reference_and_an_audit_entry(world):
    done = assessments.create_assessment(world.db, user(world, "dpo_a"), {"title": "Churn model", "ai_system_name": "ChurnGuard"})
    commit(world, done, user(world, "dpo_a"))
    row = done["assessment"]
    assert re.fullmatch(r"AIIA-\d{8}-[A-Z0-9]{5}", row["ref_number"])
    assert (row["status"], row["version"], row["autonomy_level"]) == ("draft", 1, "decision_support")
    assert row["business_unit_id"] == world.unit["A"] and row["created_by"] == user(world, "dpo_a")["id"]
    assert len(row["impacts"]) == 8 and all(i["likelihood"] is None and i["applicable"] for i in row["impacts"]), "one unscored row per dimension"
    assert row["overall_classification"] is None and done["events"] == []
    assert audit_actions(world) == ["ai_assessment_created"]


def test_an_assessment_is_never_filed_organization_wide_by_accident(world):
    app_a1 = _insert(world.db, "applications", name="Child app", business_unit_id=world.unit["A1"], is_active=1)
    world.db.commit()
    assert make(world, "dpo_a")["business_unit_id"] == world.unit["A"], "the author's own unit"
    assert make(world, "dpo_a", application_id=app_a1)["business_unit_id"] == world.unit["A1"], "the system's unit"
    assert make(world, "dpo_a", business_unit_id=world.unit["A1"])["business_unit_id"] == world.unit["A1"], "a chosen unit in scope"
    assert make(world, "dpo_no_unit")["business_unit_id"] is None, "only a person with no unit files it organization wide"


def test_a_title_is_required_and_every_field_is_checked_with_a_sentence(world):
    errors = fail(lambda: assessments.create_assessment(world.db, user(world, "dpo_a"), {"title": "  "}), 422).extra["errors"]
    assert set(errors) == {"title"}
    bad = {"title": "x" * 201, "owner": 5, "deployment_env": "moon", "autonomy_level": "magic", "status": "done",
           "residual_classification": "huge", "data_categories": "Personal", "third_party": "maybe",
           "system_description": "y" * 4001}
    errors = fail(lambda: assessments.create_assessment(world.db, user(world, "dpo_a"), bad), 422).extra["errors"]
    assert set(errors) == set(bad) and all(isinstance(v, str) and v for v in errors.values())
    assert count(world, "sentinel_aiia") == 0, "nothing was stored"
    fail(lambda: assessments.create_assessment(world.db, user(world, "dpo_a"), ["a", "list"]), 422)


def test_control_characters_are_dropped_and_text_is_trimmed(world):
    row = make(world, title="  Churn\x00 model\x07 ", owner="\tPriya\n")
    assert (row["title"], row["owner"]) == ("Churn model", "Priya")


def test_a_score_is_one_to_five_and_a_dimension_must_exist(world):
    for bad in (0, 6, "abc", 2.5, True):
        errors = fail(lambda: assessments.create_assessment(world.db, user(world, "dpo_a"), {
            "title": "x", "impacts": [{"dimension_name": "Financial", "likelihood": bad, "impact": 3}]}), 422).extra["errors"]
        assert "impacts" in errors, bad
    fail(lambda: assessments.create_assessment(world.db, user(world, "dpo_a"), {
        "title": "x", "impacts": [{"dimension_name": "Not a dimension", "likelihood": 1, "impact": 1}]}), 422)
    ok = make(world, impacts=[{"dimension_name": "Financial", "applicable": True, "likelihood": "4", "impact": 2}])
    assert {i["dimension_name"]: i["likelihood"] for i in ok["impacts"]}["Financial"] == 4, "a form may send a number as text"
    assert count(world, "sentinel_aiia") == 1


# ── What an assessment points at ────────────────────────────────────────────

def test_an_assessment_can_only_name_what_its_writer_may_open(world):
    mine = _insert(world.db, "applications", name="Visible app", business_unit_id=world.unit["A"], is_active=1)
    hidden = _insert(world.db, "applications", name="Hidden app", business_unit_id=world.unit["B"], is_active=1)
    ropa_b = _insert(world.db, "sentinel_ropa", ref_number="ROPA-B", processing_name="Unit B processing", business_unit_id=world.unit["B"])
    dpia_b = _insert(world.db, "sentinel_dpias", ref_number="DPIA-B", title="Unit B DPIA", business_unit_id=world.unit["B"])
    world.db.commit()
    for field, value in (("application_id", hidden), ("application_id", 987654),
                         ("business_unit_id", world.unit["B"]), ("business_unit_id", 987654),
                         ("ropa_id", ropa_b), ("ropa_id", 987654), ("dpia_id", dpia_b), ("dpia_id", 987654)):
        fail(lambda: assessments.create_assessment(world.db, user(world, "dpo_a"), {"title": "x", field: value}), 400)
    for field, value in (("application_id", "abc"), ("application_id", True), ("ropa_id", [1]), ("business_unit_id", 1.5)):
        errors = fail(lambda: assessments.create_assessment(world.db, user(world, "dpo_a"), {"title": "x", field: value}), 422).extra["errors"]
        assert set(errors) == {field}, "a malformed choice is a field error"
    assert count(world, "sentinel_aiia") == 0
    row = make(world, application_id=str(mine))
    assert row["application_id"] == mine, "a form sends numbers as text"
    for field, value in (("application_id", hidden), ("ropa_id", ropa_b), ("dpia_id", dpia_b), ("business_unit_id", world.unit["B"])):
        fail(lambda: edit(world, row, {field: value}), 400)
    assert edit(world, row, {"application_id": None})["assessment"]["application_id"] is None


def test_a_privacy_record_the_reader_may_not_open_is_not_named(world):
    ropa_b = _insert(world.db, "sentinel_ropa", ref_number="ROPA-B", processing_name="Secret payroll processing", business_unit_id=world.unit["B"])
    dpia_b = _insert(world.db, "sentinel_dpias", ref_number="DPIA-B", title="Secret transfer DPIA", business_unit_id=world.unit["B"])
    ropa_a = _insert(world.db, "sentinel_ropa", ref_number="ROPA-A", processing_name="Own payroll processing", business_unit_id=world.unit["A"])
    org_wide = _insert(world.db, "sentinel_aiia", ref_number="AIIA-X", title="Org wide", business_unit_id=None, ropa_id=ropa_b, dpia_id=dpia_b)
    own = _insert(world.db, "sentinel_aiia", ref_number="AIIA-Y", title="Own", business_unit_id=world.unit["A"], ropa_id=ropa_a)
    world.db.commit()
    shown = assessments.get_assessment(world.db, user(world, "dpo_a"), org_wide)
    assert shown["ropa"] == {"restricted": True} and shown["dpia"] == {"restricted": True}
    assert shown["ropa_id"] is None and shown["dpia_id"] is None
    assert "Secret" not in json.dumps(shown) and "ROPA-B" not in json.dumps(shown)
    changed = edit(world, shown, {"department": "Privacy review"})
    assert changed["assessment"]["ropa_id"] is None and changed["assessment"]["dpia_id"] is None
    stored = world.db.execute("SELECT ropa_id, dpia_id FROM sentinel_aiia WHERE id = %s", (org_wide,)).fetchone()
    assert tuple(stored) == (ropa_b, dpia_b), "an unrelated edit must keep hidden links"
    assert assessments.get_assessment(world.db, user(world, "dpo_a"), own)["ropa"] == {
        "id": ropa_a, "ref": "ROPA-A", "title": "Own payroll processing", "url": f"/sentinel/?open=ropa:{ropa_a}"}
    # A risk owner with assessment access sees a linked privacy record in their own unit.
    assert assessments.get_assessment(world.db, user(world, "owner_a"), own)["ropa"] == {
        "id": ropa_a, "ref": "ROPA-A", "title": "Own payroll processing", "url": f"/sentinel/?open=ropa:{ropa_a}"}
    assert assessments.get_assessment(world.db, user(world, "owner_a"), own)["dpia"] is None, "nothing is linked at all"


def test_the_system_an_assessment_names_is_shown_only_to_those_who_may_open_it(world):
    app = _insert(world.db, "applications", name="Unit B churn model", business_unit_id=world.unit["B"], is_active=1)
    org_wide = _insert(world.db, "sentinel_aiia", ref_number="AIIA-Z", title="Org wide", business_unit_id=None, application_id=app)
    world.db.commit()
    hidden = assessments.get_assessment(world.db, user(world, "dpo_a"), org_wide)
    assert hidden["application"] == {"restricted": True} and hidden["application_id"] is None
    shown = assessments.get_assessment(world.db, user(world, "dpo_b"), org_wide)["application"]
    assert shown == {"id": app, "name": "Unit B churn model", "url": f"/ai-governance/systems/{app}"}
    listed = assessments.list_assessments(world.db, user(world, "dpo_a"))["items"][0]
    assert listed["application"] == {"restricted": True} and listed["application_id"] is None
    assert "Unit B churn" not in json.dumps(listed)


# ── Classification (the tests the Sentinel service had) ─────────────────────

def test_the_classification_is_the_active_frameworks_band_for_the_highest_product(world):
    from modules.erm.data_service import get_active_framework_matrix, resolve_band
    row = make(world, impacts=[
        {"dimension_name": "Financial", "applicable": 1, "likelihood": 5, "impact": 5},
        {"dimension_name": "Operational", "applicable": 1, "likelihood": 2, "impact": 2},
        {"dimension_name": "Privacy", "applicable": 1, "likelihood": 1, "impact": 1}])
    assert row["overall_classification"] == resolve_band(get_active_framework_matrix(world.db), 5, 5)
    scored = {i["dimension_name"]: i for i in row["impacts"]}
    assert (scored["Financial"]["likelihood"], scored["Financial"]["impact"]) == (5, 5)


def test_the_classification_is_unrated_when_no_framework_is_active(world):
    world.db.execute("UPDATE erm_risk_frameworks SET is_active = 0")
    world.db.commit()
    row = make(world, impacts=[{"dimension_name": "Financial", "applicable": 1, "likelihood": 5, "impact": 5}])
    assert row["overall_classification"] == "unrated"


def test_a_dimension_ruled_out_does_not_count_but_keeps_its_notes(world):
    from modules.erm.data_service import get_active_framework_matrix, resolve_band
    row = make(world, impacts=[
        {"dimension_name": "Financial", "applicable": 0, "likelihood": 5, "impact": 5, "description": "Not a money use"},
        {"dimension_name": "Operational", "applicable": 1, "likelihood": 2, "impact": 2}])
    assert row["overall_classification"] == resolve_band(get_active_framework_matrix(world.db), 2, 2)
    scored = {i["dimension_name"]: i for i in row["impacts"]}
    assert scored["Financial"]["applicable"] is False and scored["Financial"]["likelihood"] == 5
    assert scored["Financial"]["description"] == "Not a money use"


def test_renaming_a_dimension_carries_its_scored_history(world):
    row = make(world, impacts=[{"dimension_name": "Financial", "applicable": 1, "likelihood": 4, "impact": 3}])
    dims = {d["name"]: d for d in assessments.list_dimensions(world.db, user(world, "dpo_a"))}
    done = assessments.save_dimensions(world.db, user(world, "dpo_a"), [{"id": dims["Financial"]["id"], "name": "Financial exposure", "order_idx": 1, "is_active": True}])
    commit(world, done, user(world, "dpo_a"))
    scored = {i["dimension_name"]: i for i in assessments.get_assessment(world.db, user(world, "dpo_a"), row["id"])["impacts"]}
    assert "Financial" not in scored and (scored["Financial exposure"]["likelihood"], scored["Financial exposure"]["impact"]) == (4, 3)
    assert "ai_dimensions_changed" in audit_actions(world)


def test_a_dimension_name_that_already_exists_is_refused_whatever_its_case(world):
    dims = {d["name"]: d for d in assessments.list_dimensions(world.db, user(world, "dpo_a"))}
    fail(lambda: assessments.save_dimensions(world.db, user(world, "dpo_a"), [{"id": dims["Operational"]["id"], "name": "financial"}]), 409)
    assert {d["name"] for d in assessments.list_dimensions(world.db, user(world, "dpo_a"))} == set(dims), "nothing changed"
    fail(lambda: assessments.save_dimensions(world.db, user(world, "dpo_a"), [{"name": "x" * 101}]), 422)
    fail(lambda: assessments.save_dimensions(world.db, user(world, "dpo_a"), [{"name": "  "}]), 422)
    fail(lambda: assessments.save_dimensions(world.db, user(world, "dpo_a"), [{"name": f"Extra {n}"} for n in range(60)]), 422)


def test_a_deactivated_dimension_leaves_new_forms_but_old_scores_survive(world):
    row = make(world, impacts=[{"dimension_name": "Societal", "applicable": 1, "likelihood": 3, "impact": 3}])
    dims = {d["name"]: d for d in assessments.list_dimensions(world.db, user(world, "dpo_a"))}
    commit(world, assessments.save_dimensions(world.db, user(world, "dpo_a"), [{"id": dims["Societal"]["id"], "name": "Societal", "is_active": False}]),
           user(world, "dpo_a"))
    assert "Societal" not in [d["name"] for d in assessments.list_dimensions(world.db, user(world, "dpo_a"), include_inactive=False)]
    assert "Societal" in [d["name"] for d in assessments.list_dimensions(world.db, user(world, "dpo_a"))]
    kept = {i["dimension_name"]: i for i in assessments.get_assessment(world.db, user(world, "dpo_a"), row["id"])["impacts"]}
    assert kept["Societal"]["likelihood"] == 3 and kept["Societal"]["active"] is False
    assert "Societal" not in [i["dimension_name"] for i in make(world)["impacts"]], "a new form does not offer it"


# ── Reading and listing ─────────────────────────────────────────────────────

def test_an_assessment_in_another_unit_does_not_exist_for_a_reader_or_a_writer(world):
    theirs = make(world, "dpo_b", title="Theirs")["id"]
    assert assessments.get_assessment(world.db, user(world, "dpo_a"), theirs) is None
    fail(lambda: assessments.update_assessment(world.db, user(world, "dpo_a"), theirs, {"title": "Hijacked"}, 1), 404)
    fail(lambda: assessments.delete_assessment(world.db, user(world, "dpo_a"), theirs), 404)
    assert world.db.execute("SELECT title FROM sentinel_aiia WHERE id = %s", (theirs,)).fetchone()["title"] == "Theirs"
    assert assessments.list_assessments(world.db, user(world, "dpo_a"))["total"] == 0
    assert assessments.list_assessments(world.db, user(world, "dpo_b"))["total"] == 1


def test_a_parent_unit_reaches_a_childs_assessment_and_a_child_does_not_reach_its_parents(world):
    child = make(world, "dpo_a1", title="Child")["id"]
    parent = make(world, "dpo_a", title="Parent")["id"]
    assert assessments.get_assessment(world.db, user(world, "dpo_a"), child)["title"] == "Child"
    assert assessments.get_assessment(world.db, user(world, "dpo_a1"), parent) is None
    fail(lambda: assessments.update_assessment(world.db, user(world, "dpo_a1"), parent, {"title": "x"}, 1), 404)


def test_an_organization_wide_assessment_is_open_to_every_unit_and_a_super_administrator_sees_all(world):
    legacy = _insert(world.db, "sentinel_aiia", ref_number="AIIA-OLD", title="Filed before units", business_unit_id=None)
    make(world, "dpo_b", title="Unit B")
    world.db.commit()
    row = assessments.get_assessment(world.db, user(world, "dpo_a"), legacy)
    assert row["title"] == "Filed before units" and row["version"] == 1 and row["data_categories"] == []
    assert {i["title"] for i in assessments.list_assessments(world.db, user(world, "dpo_a"))["items"]} == {"Filed before units"}
    assert assessments.list_assessments(world.db, user(world, "super"))["total"] == 2


def test_the_list_filters_pages_and_never_treats_a_typed_wildcard_as_one(world):
    app = _insert(world.db, "applications", name="Linked app", business_unit_id=world.unit["A"], is_active=1)
    world.db.commit()
    a = make(world, title="Quartz 5% Ledger", ai_system_name="Ledger bot", application_id=app, status="completed")
    b = make(world, title="Quartz 50 Ledger", ai_system_name="Other", status="draft")
    done = assessments.list_assessments(world.db, user(world, "dpo_a"), q="QUARTZ 5%")
    assert [i["id"] for i in done["items"]] == [a["id"]], "a typed % is just a character, and case does not matter"
    assert {i["id"] for i in assessments.list_assessments(world.db, user(world, "dpo_a"), q="quartz")["items"]} == {a["id"], b["id"]}
    assert [i["id"] for i in assessments.list_assessments(world.db, user(world, "dpo_a"), q="ledger bot")["items"]] == [a["id"]], "system name"
    assert [i["id"] for i in assessments.list_assessments(world.db, user(world, "dpo_a"), q=a["ref_number"].lower())["items"]] == [a["id"]]
    assert [i["id"] for i in assessments.list_assessments(world.db, user(world, "dpo_a"), status="completed")["items"]] == [a["id"]]
    assert [i["id"] for i in assessments.list_assessments(world.db, user(world, "dpo_a"), application_id=app)["items"]] == [a["id"]]
    assert [i["id"] for i in assessments.list_assessments(world.db, user(world, "dpo_a"), linked="none")["items"]] == [b["id"]]
    assert [i["id"] for i in assessments.list_assessments(world.db, user(world, "dpo_a"), linked="any")["items"]] == [a["id"]]
    paged = assessments.list_assessments(world.db, user(world, "dpo_a"), page=2, page_size=1)
    assert (paged["total"], paged["pages"], len(paged["items"]), paged["page"]) == (2, 2, 1, 2)
    for bad in ({"status": "gone"}, {"linked": "maybe"}, {"page_size": 0}, {"page_size": 101}, {"classification": "x" * 60}):
        fail(lambda: assessments.list_assessments(world.db, user(world, "dpo_a"), **bad), 400)


def test_the_list_says_what_the_viewer_may_do(world):
    assert assessments.list_assessments(world.db, user(world, "dpo_a"))["can"] == {"manage": True, "configure": True}
    manager = as_role(world, rbac.COMPLIANCE_MGR)
    assert assessments.list_assessments(world.db, manager)["can"] == {"manage": True, "configure": False}


# ── Changing ────────────────────────────────────────────────────────────────

def test_an_update_changes_only_what_it_names_and_bumps_the_version(world):
    row = make(world, owner="Priya", department="Data", mitigation_measures="Review monthly")
    done = edit(world, row, {"title": "Churn model v2"})
    new = done["assessment"]
    assert (new["title"], new["owner"], new["department"], new["mitigation_measures"], new["version"]) == (
        "Churn model v2", "Priya", "Data", "Review monthly", 2)
    assert audit_actions(world) == ["ai_assessment_created", "ai_assessment_updated"]


def test_two_people_editing_one_assessment_do_not_overwrite_each_other(world):
    row = make(world)
    edit(world, row, {"title": "One"})
    stale = fail(lambda: edit(world, row, {"title": "Two"}), 409)
    assert stale.extra["current_version"] == 2
    assert world.db.execute("SELECT title FROM sentinel_aiia WHERE id = %s", (row["id"],)).fetchone()["title"] == "One"
    for missing in (None, "2", True):
        fail(lambda: assessments.update_assessment(world.db, user(world, "dpo_a"), row["id"], {"title": "x"}, missing), 400)


def test_a_status_must_be_one_of_the_four_and_a_change_is_audited(world):
    row = make(world)
    fail(lambda: edit(world, row, {"status": "finished"}), 422)
    done = edit(world, row, {"status": "in_progress"})
    assert done["assessment"]["status"] == "in_progress" and done["events"] == []
    assert audit_actions(world) == ["ai_assessment_created", "ai_assessment_updated", "ai_assessment_status_changed"]


def test_completing_an_assessment_raises_one_event_and_a_later_step_raises_none(world):
    row = make(world, application_id=None)
    done = edit(world, row, {"status": "completed"})
    assert len(done["events"]) == 1
    event = world.db.execute("SELECT event_type, source_entity_id FROM events WHERE id = %s", (done["events"][0],)).fetchone()
    assert (event[0], event[1]) == ("ai_assessment.completed", row["id"])
    again = edit(world, done["assessment"], {"status": "approved"})
    assert again["events"] == [], "it was already complete"
    back = edit(world, again["assessment"], {"status": "draft"})
    final = edit(world, back["assessment"], {"status": "completed"})
    assert len(final["events"]) == 1, "completed again after being reopened"


def test_linking_and_unlinking_a_system_is_audited(world):
    app = _insert(world.db, "applications", name="Linked app", business_unit_id=world.unit["A"], is_active=1)
    world.db.commit()
    row = make(world)
    linked = edit(world, row, {"application_id": app})
    assert linked["assessment"]["application_id"] == app
    unlinked = edit(world, linked["assessment"], {"application_id": None})
    assert unlinked["assessment"]["application_id"] is None
    assert audit_actions(world).count("ai_assessment_linked") == 2


def test_a_user_who_may_not_write_cannot_change_an_assessment_they_can_read(world):
    row = make(world)
    auditor = as_role(world, rbac.EXTERNAL_AUDITOR)
    fail(lambda: assessments.update_assessment(world.db, auditor, row["id"], {"title": "x"}, 1), 403)
    assert assessments.get_assessment(world.db, as_role(world, rbac.RISK_OWNER), row["id"])["title"] == "Churn model"


# ── Deleting ────────────────────────────────────────────────────────────────

def test_deleting_removes_the_assessment_and_its_impact_rows_and_is_audited(world):
    row = make(world, impacts=[{"dimension_name": "Financial", "applicable": 1, "likelihood": 2, "impact": 2}])
    assert count(world, "sentinel_aiia_impacts", "aiia_id = %s", (row["id"],)) == 1
    commit(world, assessments.delete_assessment(world.db, user(world, "dpo_a"), row["id"]), user(world, "dpo_a"))
    assert count(world, "sentinel_aiia", "id = %s", (row["id"],)) == 0
    assert count(world, "sentinel_aiia_impacts", "aiia_id = %s", (row["id"],)) == 0
    assert audit_actions(world)[-1] == "ai_assessment_deleted"
    fail(lambda: assessments.delete_assessment(world.db, user(world, "dpo_a"), row["id"]), 404)


def test_an_approved_assessment_is_not_deleted(world):
    row = make(world, status="approved")
    error = fail(lambda: assessments.delete_assessment(world.db, user(world, "dpo_a"), row["id"]), 409)
    assert "approved" in error.message.lower() and count(world, "sentinel_aiia", "id = %s", (row["id"],)) == 1
    edit(world, row, {"status": "in_progress"})
    assessments.delete_assessment(world.db, user(world, "dpo_a"), row["id"])


# ── The pickers ─────────────────────────────────────────────────────────────

def test_the_pickers_offer_only_privacy_records_the_writer_may_open_found_by_typing(world):
    mine = _insert(world.db, "sentinel_ropa", ref_number="ROPA-A", processing_name="Payroll run", business_unit_id=world.unit["A"])
    _insert(world.db, "sentinel_ropa", ref_number="ROPA-B", processing_name="Payroll abroad", business_unit_id=world.unit["B"])
    dpia = _insert(world.db, "sentinel_dpias", ref_number="DPIA-A", title="Payroll transfer", business_unit_id=world.unit["A"])
    world.db.commit()
    found = assessments.link_options(world.db, user(world, "dpo_a"), "ropa", "PAYROLL")
    assert found == [{"id": mine, "ref": "ROPA-A", "title": "Payroll run"}]
    assert [r["id"] for r in assessments.link_options(world.db, user(world, "dpo_a"), "dpia")] == [dpia], "empty search lists the first few"
    assert assessments.link_options(world.db, user(world, "dpo_a"), "ropa", "%") == [], "a wildcard is just a character"
    assert [r["id"] for r in assessments.link_options(world.db, user(world, "owner_a"), "ropa", "payroll")] == [mine]
    fail(lambda: assessments.link_options(world.db, user(world, "dpo_a"), "vendor", "x"), 400)
