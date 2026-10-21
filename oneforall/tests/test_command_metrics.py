"""
The Command Centre numbers carry their state (plans/2026-10-governance-rework/04 section 2).

A number that could not be read is `unavailable`, never a zero; a number with nothing to measure is `not_measured`, never a
good looking 100 per cent; a sum that lost a source is `partial` and names it; a module the viewer may not open sends no metric
at all. Expectations are written by hand from the seed data of tests/test_platform_ownership_surfaces.py.
"""
import pytest

from core import metric_registry as registry
from modules.launcher import command_metrics as cm
from tests.test_platform_ownership import _insert, signed_in, world  # noqa: F401
from tests.test_platform_ownership_surfaces import http, seeded  # noqa: F401


def test_the_cards_carry_their_state_and_agree_with_the_figures_they_replace(http):
    body = http("get", "/api/command-centre/stats").json()
    metrics = body["metrics"]
    sla = metrics["cc.sla_on_time"]
    assert (sla["state"], sla["value"]) == ("measured", 50)
    assert sla["detail"] == {"unit": "percent", "met": 1, "breached": 1, "at_risk": 1}
    assert metrics["cc.workflows_active"]["value"] == body["workflow_active"] == 2
    assert metrics["cc.appetite_breaches"]["value"] == body["erm_appetite_breaches"] == 1
    assert metrics["cc.appetite_breaches"]["detail"]["categories"] >= 1, "every category that has a limit is the denominator"
    assert metrics["cc.open_risks"]["detail"] == body["risk_counts"] == {"critical": 2, "high": 1, "medium": 2, "low": 0}
    assert metrics["cc.open_risks"]["value"] == 5
    for key, metric in metrics.items():
        assert metric["definition"] and metric["window"], key
        assert metric["state"] != "unavailable", (key, "the seeded sources are all readable")


def test_every_metric_the_cards_use_is_registered_with_a_definition_and_a_drilldown_or_a_reason(http):
    body = http("get", "/api/command-centre/stats").json()
    for key, metric in body["metrics"].items():
        d = registry.get(key.split(":")[0])
        assert metric["label"] == d.label and metric["definition"] == d.definition, key
        assert d.drilldown or not d.exact, f"{key}: no list and no admission that there is none"
    assert body["health"], "module health is sent as metrics too"
    assert {h["key"].split(":")[0] for h in body["health"]} == {"cc.module_health"}


def test_the_controls_card_never_counts_documentation_as_implementation(world):
    fw = _insert(world.db, "frameworks", name="ISO 27001")
    for ref, status in (("A.1", "Implemented"), ("A.2", "Approved"), ("A.3", "Not Started")):
        _insert(world.db, "controls", framework_id=fw, ref=ref, name=ref, status=status)
    got = cm.build(world.db, world.users["super"])["metrics"]["cc.controls_implemented"]
    assert (got["state"], got["value"]) == ("measured", 33)
    assert got["detail"] == {"unit": "percent", "implemented": 1, "total": 3, "approved_not_implemented": 1}


def test_nothing_to_measure_is_not_measured_and_never_a_good_looking_hundred(world):
    world.db.execute("DELETE FROM erm_risk_appetite")  # a new database is seeded with default limits
    world.db.commit()
    built = cm.build(world.db, world.users["super"])
    metrics = built["metrics"]
    assert metrics["cc.controls_implemented"]["state"] == "not_measured"
    assert metrics["cc.controls_implemented"]["value"] is None and metrics["cc.controls_implemented"]["action"]
    assert metrics["cc.appetite_breaches"]["state"] == "not_measured", "no category has a limit"
    assert metrics["cc.sla_on_time"]["state"] == "not_measured" and metrics["cc.sla_on_time"]["value"] is None
    health = {h["detail"]["module"]: h for h in built["health"]}
    assert health["aria"]["state"] == "not_measured", "no controls: not 100 per cent"
    assert health["bcm"]["state"] == "not_measured"
    assert health["sentinel"]["state"] == "measured" and health["sentinel"]["value"] == 0, "four breaches, none closed"


def test_a_source_that_fails_is_unavailable_and_a_sum_that_lost_one_is_partial(world, monkeypatch):
    real = cm.scoped_count

    def flaky(db, user, table, condition="", params=()):
        if table == "sla_instances":
            raise RuntimeError("the clocks table could not be read")
        return real(db, user, table, condition, params)

    monkeypatch.setattr(cm, "scoped_count", flaky)
    metrics = cm.build(world.db, world.users["super"])["metrics"]
    overdue = metrics["cc.overdue_actions"]
    assert overdue["state"] == "partial" and overdue["sources"] == {"available": ["tasks"], "missing": ["service clocks"]}
    assert metrics["cc.sla_on_time"]["state"] == "unavailable" and metrics["cc.sla_on_time"]["value"] is None
    assert "not a count of zero" in metrics["cc.sla_on_time"]["note"]
    assert metrics["cc.bcm_active_incidents"]["state"] == "measured", "the other sources still work"


def test_a_module_the_viewer_may_not_open_sends_no_metric_at_all(world):
    metrics = cm.build(world.db, world.users["employee_a"])["metrics"]
    assert "cc.open_breaches" not in metrics and "cc.critical_high_risks" not in metrics
    assert "cc.workflows_active" in metrics, "an employee may still see what is for everyone"
    keys = {h["detail"]["module"] for h in cm.build(world.db, world.users["employee_a"])["health"]}
    assert "sentinel" not in keys


def test_every_registered_drilldown_is_a_page_of_the_application():
    import main
    from starlette.routing import Match
    paths = {}
    for key, d in registry.REGISTRY.items():
        if d.drilldown:
            paths[key] = d.drilldown.split("?")[0].split("#")[0] or "/"
    missing = {}
    for key, path in paths.items():
        scope = {"type": "http", "path": path, "method": "GET", "root_path": "", "query_string": b"", "headers": []}
        if not any(route.matches(scope)[0] == Match.FULL for route in main.app.routes):
            missing[key] = path
    assert missing == {}
