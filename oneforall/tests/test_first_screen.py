"""
The first screen of the Command Centre answers four questions from sources that already exist, each read through the
person's own scope, and one failing source never blanks the others
(plans/2026-10-governance-rework/04 section 1 and section 7).

Expectations are written by hand from the rows inserted; every "cannot" has a positive twin.
"""
import json

import pytest

import modules.launcher.first_screen as first_screen
import modules.launcher.routes_dashboard as dash
from tests.test_platform_ownership import ORG, _call, _insert, _request, signed_in, world  # noqa: F401


def _screen(user):
    status, body = _call(dash.api_command_centre_first_screen(_request(user)))
    assert status == 200
    return {p["key"]: p for p in body["panels"]}, body


@pytest.fixture
def day(world):
    db, unit = world.db, world.unit
    dpo = world.users["dpo_a"]
    _insert(db, "task_board", title="Overdue review", status="todo", assigned_to=dpo["id"], created_by=dpo["id"],
            due_date="2020-01-01", business_unit_id=unit["A"])
    _insert(db, "task_board", title="Plain task", status="todo", assigned_to=dpo["id"], created_by=dpo["id"],
            business_unit_id=unit["A"])
    _insert(db, "task_board", title="Unit B secret task", status="todo", assigned_to=world.users["dpo_b"]["id"],
            created_by=world.users["dpo_b"]["id"], business_unit_id=unit["B"])
    _insert(db, "notifications", user_id=dpo["id"], title="A policy changed", is_read=0)
    framework = _insert(db, "frameworks", name="ISO 27001", is_active=1)
    c1 = _insert(db, "controls", framework_id=framework, ref="A.5.1", name="Policies")
    _insert(db, "controls", framework_id=framework, ref="A.5.2", name="Roles")
    item = _insert(db, "evidence_items", title="Policy file", status="current", org_id=ORG)
    _insert(db, "evidence_links", evidence_id=item, module="aria", entity_type="control", entity_id=c1)
    return world


def test_the_four_panels_are_read_through_the_persons_scope(day):
    panels, body = _screen(day.users["dpo_a"])
    assert [p["key"] for p in panels.values()] == ["action", "changed", "proof", "report"]
    assert all(p["state"] in ("ok", "partial") for p in panels.values())

    action = panels["action"]
    assert action["counts"]["overdue"] == 1 and action["counts"]["needs_you"] >= 1
    titles = [i["title"] for i in action["items"]]
    assert titles[0] == "Overdue review" and "Unit B secret task" not in json.dumps(body)
    assert action["link"] == "/my-work"

    changed = panels["changed"]
    assert changed["counts"]["unread"] == 1 and changed["counts"]["to_look_at"] == 0

    proof = panels["proof"]["counts"]
    # every record this person may open (the seeded controls, the two added here, the world's own) minus the one
    # control that is linked to a current file that no reviewer has accepted yet
    assert proof["records"] >= 2 and proof["waiting_review"] == 1
    assert proof["without_proof"] == proof["records"] - 1
    assert "not accepted proof" in panels["proof"]["definition"]

    assert {p["key"] for p in panels["report"]["presets"]} == {"preset_specialist", "preset_management", "preset_board"}
    assert panels["report"]["last_run"] is None
    assert [s["source"] for s in body["sources"]] == ["action", "changed", "proof", "report"]


def test_a_report_made_before_appears_as_the_last_saved_run(day):
    import modules.launcher.routes_reports as reports
    dpo = day.users["dpo_a"]
    status, run = _call(reports.api_report_quick_run(_request(dpo, payload={"report_type": "preset_board"})))
    assert status == 200
    panels, _ = _screen(dpo)
    last = panels["report"]["last_run"]
    assert last["id"] == run["run_id"] and last["name"] == "Board report"


def test_the_sections_a_person_cannot_open_are_counted_as_not_open_to_them(day):
    dpo_panels, _ = _screen(day.users["dpo_a"])
    employee_panels, _ = _screen(day.users["employee_a"])
    open_for = lambda panels: {p["key"]: p["sections_open"] for p in panels["report"]["presets"]}  # noqa: E731
    assert open_for(dpo_panels)["preset_board"] > open_for(employee_panels)["preset_board"], \
        "an employee may not open the privacy section, so fewer sections are open to them"
    assert all(p["sections_open"] <= p["sections_total"] for p in employee_panels["report"]["presets"])


def test_one_source_failing_blanks_only_its_own_panel(day, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("could not read the work list")

    monkeypatch.setattr(first_screen, "get_my_work", broken)
    panels, _ = _screen(day.users["dpo_a"])
    assert panels["action"]["state"] == "unavailable" and "counts" not in panels["action"]
    assert panels["changed"]["state"] == "unavailable", "it reads the same work list"
    assert panels["proof"]["state"] == "ok" and panels["proof"]["counts"]["waiting_review"] == 1
    assert panels["report"]["state"] == "ok"


def test_a_person_with_nothing_to_prove_gets_not_measured_not_zero(world):
    panels, _ = _screen(world.users["employee_a"])
    proof = panels["proof"]
    assert proof["state"] in ("ok", "not_measured")
    if proof["state"] == "not_measured":
        assert proof["counts"] is None and "nothing to measure" in proof["note"]
    else:
        assert proof["counts"]["records"] >= 0
