"""
The business continuity and privacy dashboards read through the viewer's scope and never invent a number
(plans/2026-10-governance-rework/04 section 2, acceptance scenario 2).

The BCM dashboard used to count every unit's records for everyone, and both pages showed a made up set of records when a read
failed. Expectations are written by hand from the seed data below; every "sees nothing" assertion has a positive twin.
"""
import json
import re
import pathlib

import pytest

from core import rbac
from modules.bcm import dashboard_metrics as bcm
from modules.sentinel import dashboard_metrics as sentinel
from tests.test_platform_ownership import ORG, _insert, signed_in, world  # noqa: F401


def _person(world, role, tag, uid):
    return {"id": uid, "username": f"{role}_{tag}", "org_id": ORG, "business_unit_id": world.unit.get(tag),
            "is_super_admin": 0, "roles": [role]}


@pytest.fixture
def continuity(world):
    db, unit = world.db, world.unit
    bia_a1 = _insert(db, "bcm_bia_records", process_name="Payroll", business_unit_id=unit["A"])
    _insert(db, "bcm_bia_records", process_name="Billing", business_unit_id=unit["A"])
    _insert(db, "bcm_bia_records", process_name="Secret B process", business_unit_id=unit["B"])
    plan_a = _insert(db, "bcm_plans", title="Plan A", business_unit_id=unit["A"], status="approved")
    _insert(db, "bcm_plans", title="Plan B one", business_unit_id=unit["B"], status="draft")
    _insert(db, "bcm_plans", title="Plan B two", business_unit_id=unit["B"], status="approved")
    _insert(db, "bcm_bia_plan_links", bia_id=bia_a1, plan_id=plan_a)
    _insert(db, "bcm_incidents", title="Outage A", business_unit_id=unit["A"], status="open", severity="high")
    _insert(db, "bcm_exercises", title="Tabletop A", business_unit_id=unit["A"], status="completed")
    _insert(db, "bcm_exercises", title="Drill A", business_unit_id=unit["A"], status="scheduled")
    _insert(db, "bcm_exercises", title="Secret B drill", business_unit_id=unit["B"], status="completed")
    return world


def test_the_dashboard_counts_only_what_the_viewer_may_open(continuity):
    a = bcm.stats(_person(continuity, rbac.BCM_MANAGER, "A", 301))
    m = a["metrics"]
    assert (m["bcm.bia_with_plan"]["state"], m["bcm.bia_with_plan"]["value"]) == ("measured", 50)
    assert m["bcm.bia_with_plan"]["detail"] == {"unit": "percent", "covered": 1, "total": 2}
    assert m["bcm.plans"]["value"] == 1 and m["bcm.plans"]["detail"]["approved"] == 1
    assert m["bcm.active_incidents"]["value"] == 1
    assert (m["bcm.exercises_completed"]["value"], m["bcm.exercises_completed"]["detail"]["total"]) == (50, 2)
    assert [p["title"] for p in a["plan_status"]] == ["Plan A"]
    assert {i["title"] for i in a["active_incidents"]} == {"Outage A"}
    assert "Secret B" not in json.dumps(a)

    b = bcm.stats(_person(continuity, rbac.BCM_MANAGER, "B", 302))
    assert b["metrics"]["bcm.plans"]["value"] == 2 and b["metrics"]["bcm.bia_with_plan"]["detail"]["total"] == 1
    assert b["metrics"]["bcm.bia_with_plan"]["value"] == 0, "a measured zero: one analysis, no plan linked"
    assert {i["title"] for i in b["active_incidents"]} == {"Incident B"}
    assert "Outage A" not in json.dumps(b)

    whole = bcm.stats({**_person(continuity, rbac.SUPER_ADMIN, None, 303), "is_super_admin": 1})
    assert whole["metrics"]["bcm.plans"]["value"] == 3 and whole["metrics"]["bcm.bia_with_plan"]["detail"]["total"] == 3


def test_a_person_without_continuity_access_is_sent_nothing(continuity):
    got = bcm.stats(_person(continuity, rbac.DPO, "A", 304))
    assert got["metrics"] == {} and got["plan_status"] is None and got["active_incidents"] is None


def test_nothing_recorded_is_not_measured_and_a_failed_read_is_unavailable(world, monkeypatch):
    manager = _person(world, rbac.BCM_MANAGER, "A", 305)
    empty = bcm.stats(manager)["metrics"]
    assert empty["bcm.bia_with_plan"]["state"] == "not_measured" and empty["bcm.bia_with_plan"]["value"] is None
    assert empty["bcm.exercises_completed"]["state"] == "not_measured" and empty["bcm.exercises_completed"]["action"]
    assert empty["bcm.plans"]["state"] == "measured" and empty["bcm.plans"]["value"] == 0, "no plan is a count of zero"

    real = bcm.scoped_count

    def failing(db, user, table, condition="", params=()):
        if table == "bcm_plans":
            raise RuntimeError("could not read plans")
        return real(db, user, table, condition, params)

    monkeypatch.setattr(bcm, "scoped_count", failing)
    broken = bcm.stats(manager)
    assert broken["metrics"]["bcm.plans"]["state"] == "unavailable" and broken["metrics"]["bcm.plans"]["value"] is None
    assert broken["plans"] is None, "not a zero"
    assert broken["metrics"]["bcm.active_incidents"]["state"] == "measured"


def test_the_board_narrative_is_given_figures_and_never_a_title(continuity):
    stats = bcm.stats(_person(continuity, rbac.BCM_MANAGER, "A", 306))
    given = json.dumps(bcm.for_narrative(stats))
    assert "Plan A" not in given and "Outage A" not in given and "Tabletop A" not in given
    assert '"bcm.plans"' in given


# ── Privacy ─────────────────────────────────────────────────────────────────

@pytest.fixture
def privacy(world):
    db, unit = world.db, world.unit
    p1 = _insert(db, "business_processes", name="Onboarding", business_unit_id=unit["A"], is_active=1)
    p2 = _insert(db, "business_processes", name="Payroll run", business_unit_id=unit["A"], is_active=1)
    p3 = _insert(db, "business_processes", name="Unit B secret process", business_unit_id=unit["B"], is_active=1)
    _insert(db, "business_processes", name="Retired process", business_unit_id=unit["A"], is_active=0)
    ropa_a = _insert(db, "sentinel_ropa", ref_number="RP-A", processing_name="Onboarding records", business_unit_id=unit["A"])
    ropa_b = _insert(db, "sentinel_ropa", ref_number="RP-B", processing_name="Unit B records", business_unit_id=unit["B"])

    def link(process, ropa, status="confirmed"):
        _insert(db, "cross_module_links", source_module="sentinel", source_type="ropa", source_id=ropa,
                target_module="governance", target_type="process", target_id=process, relationship="records",
                provenance="manual", status=status)
    link(p1, ropa_a)
    link(p3, ropa_b)
    link(p2, ropa_b)  # unit A's process is connected to a record unit A cannot open
    _insert(db, "sentinel_dsr", ref_number="DSR-1", requester_name="Jane Subject", request_type="access",
            status="open", business_unit_id=unit["A"])
    _insert(db, "sentinel_dsr", ref_number="DSR-2", requester_name="Pat Subject", request_type="erasure",
            status="completed", business_unit_id=unit["A"])
    _insert(db, "sentinel_dsr", ref_number="DSR-B", requester_name="B Subject", request_type="access",
            status="in_progress", business_unit_id=unit["B"])
    return world


def test_coverage_counts_a_process_only_through_a_record_the_viewer_may_open(privacy):
    a = sentinel.stats(privacy.users["dpo_a"])["metrics"]
    cov = a["sentinel.ropa_coverage"]
    assert (cov["state"], cov["value"]) == ("measured", 50), "two active processes are visible, one has a record the viewer may open"
    assert cov["detail"] == {"unit": "percent", "covered": 1, "total": 2}, "the link to a hidden record does not count"
    assert a["sentinel.ropa_records"]["value"] == 1
    b = sentinel.stats(privacy.users["dpo_b"])["metrics"]
    assert b["sentinel.ropa_coverage"]["detail"] == {"unit": "percent", "covered": 1, "total": 1}
    whole = sentinel.stats(privacy.users["super"])["metrics"]["sentinel.ropa_coverage"]
    active = privacy.db.execute("SELECT COUNT(*) FROM business_processes WHERE is_active = 1").fetchone()[0]
    assert whole["detail"] == {"unit": "percent", "covered": 3, "total": active}, "super: every active process"
    assert active >= 3


def test_the_gap_list_names_only_processes_the_viewer_may_open_and_without_a_record(privacy):
    from database import get_db
    db = get_db()
    try:
        gaps = sentinel.coverage_gaps(db, privacy.users["dpo_a"])
        assert [g["name"] for g in gaps] == ["Payroll run"]
        assert "secret" not in json.dumps(gaps).lower()
        assert sentinel.coverage_gaps(db, privacy.users["employee_a"]) is None
    finally:
        db.close()


def test_a_proposed_link_is_not_coverage(privacy):
    ropa_a = privacy.db.execute("SELECT id FROM sentinel_ropa WHERE ref_number = 'RP-A'").fetchone()[0]
    payroll = privacy.db.execute("SELECT id FROM business_processes WHERE name = 'Payroll run'").fetchone()[0]
    _insert(privacy.db, "cross_module_links", source_module="sentinel", source_type="ropa", source_id=ropa_a,
            target_module="governance", target_type="process", target_id=payroll, relationship="records",
            provenance="system_candidate", status="candidate")
    cov = sentinel.stats(privacy.users["dpo_a"])["metrics"]["sentinel.ropa_coverage"]
    assert cov["detail"]["covered"] == 1


def test_no_business_process_means_coverage_is_not_measured(world):
    got = sentinel.stats(world.users["dpo_a"])["metrics"]["sentinel.ropa_coverage"]
    assert got["state"] == "not_measured" and got["value"] is None and got["action"]


def test_requests_and_counts_follow_the_viewer_and_never_carry_a_made_up_row(privacy):
    a = sentinel.stats(privacy.users["dpo_a"])
    dsr = a["metrics"]["sentinel.dsr_open"]
    assert dsr["value"] == 1 and dsr["detail"] == {"open": 1, "in_progress": 0, "completed": 1, "total": 2}
    assert {r["id"] for r in a["dsr_items"]} == {"DSR-1", "DSR-2"}
    assert all("priority" not in r for r in a["dsr_items"]), "no priority is recorded, so none is shown"
    assert "DSR-B" not in json.dumps(a) and "DSR-2026-041" not in json.dumps(a)
    employee = sentinel.stats(privacy.users["employee_a"])
    assert employee["metrics"] == {} and employee["dsr_items"] is None


def test_a_failed_source_is_unavailable_never_zero(privacy, monkeypatch):
    real = sentinel.scoped_count

    def failing(db, user, table, condition="", params=()):
        if table == "sentinel_dsr":
            raise RuntimeError("could not read requests")
        return real(db, user, table, condition, params)

    monkeypatch.setattr(sentinel, "scoped_count", failing)
    got = sentinel.stats(privacy.users["dpo_a"])["metrics"]
    assert got["sentinel.dsr_open"]["state"] == "unavailable" and got["sentinel.dsr_open"]["value"] is None
    assert got["sentinel.ropa_records"]["state"] == "measured"


# ── No page carries sample data any more ────────────────────────────────────

SAMPLES = ["HQ Business Continuity Plan", "Data centre cooling failure", "DSR-2026-041", "CloudHost Ltd",
           "ISO 27001 · ISO 9001", "Sarah Chen", "James Wilson", "ACT-001", "Vendor SaaS outage"]


@pytest.mark.parametrize("path", ["templates/command_centre.html", "modules/bcm/templates/index.html",
                                  "modules/sentinel/templates/index.html"])
def test_no_dashboard_template_carries_sample_data_or_a_fallback_object(path):
    text = (pathlib.Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
    assert not re.search(r"\b(?:var|const|let)\s+fallback\s*=", text), path
    for sample in SAMPLES:
        assert sample not in text, (path, sample)
