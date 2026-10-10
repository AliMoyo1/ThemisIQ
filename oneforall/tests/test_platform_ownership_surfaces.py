"""What a business-unit-restricted role sees of platform risks, SLA clocks and workflow instances.

Each of the surfaces below used to show a restricted role zeros, or hide the legacy platform risk
register outright, because the three tables had no owner (tests/test_platform_ownership.py is about how
an owner is recorded). The rule under test: the same unit rule as every other scoped table. A NULL unit is
organization wide, anything else must sit inside the caller's own subtree (a parent unit sees its children,
a child does not see its parent), and platform risks additionally need the capability the ERM module
requires. SLA clocks and workflow instances also stay inside the caller's organization.

Expectations are written out by hand from the seed data below, never computed by the code under test, and
every "sees nothing" assertion has a positive twin.
"""
import asyncio
import json

import pytest

import modules.launcher.routes_dashboard as dash
import modules.launcher.routes_reports as reports
import modules.launcher.routes_risks as risks
from modules.launcher.scoped_metrics import scoped_count
from tests.test_platform_ownership import (  # noqa: F401  (world is a fixture, signed_in applies to every test)
    ORG, PERSONAS, _call, _insert, _request, signed_in, world,
)

OTHER_ORG = 2

# What each persona sees of rows tagged with a unit: organization wide ones plus their own subtree.
SEES = {
    "super": {"org", "A", "A1", "B"},
    "dpo_a": {"org", "A", "A1"},
    "dpo_a1": {"org", "A1"},
    "dpo_b": {"org", "B"},
    "dpo_no_unit": {"org"},
    "owner_a": {"org", "A", "A1"},
    "owner_b": {"org", "B"},
    "employee_a": {"org", "A", "A1"},
}
# Platform risks also need erm.risk.view (core/rbac.py): the employee does not have it.
CAN_VIEW_RISKS = {"super", "dpo_a", "dpo_a1", "dpo_b", "dpo_no_unit", "owner_a", "owner_b"}


@pytest.fixture
def seeded(world):
    """The three tables, one row per unit tag, with known states, plus a row of another organization."""
    db, unit = world.db, world.unit
    _insert(db, "organizations", id=OTHER_ORG, name="other", slug="other")

    # platform risks: (tag, likelihood, impact, level, status)
    risk_rows = {"org": (3, 3, "medium", "open"), "A": (5, 4, "critical", "open"),
                 "A1": (4, 3, "high", "open"), "B": (5, 5, "critical", "open")}
    world.risk = {tag: _insert(db, "risk_register", title=f"needle risk {tag}", likelihood=l, impact=i,
                               risk_level=lvl, status=status, source_module="sentinel", business_unit_id=unit[tag])
                  for tag, (l, i, lvl, status) in risk_rows.items()}
    world.risk["A closed"] = _insert(db, "risk_register", title="needle risk A closed", likelihood=5, impact=5,
                                     risk_level="critical", status="closed", business_unit_id=unit["A"])

    sla_def = _insert(db, "sla_definitions", name="SLA", module="sentinel", entity_type="breach")
    # SLA clocks: org met, A open and on time, A1 open and breached, B open and breached
    sla_rows = {"org": ("resolved", 0), "A": ("active", 0), "A1": ("active", 1), "B": ("active", 1)}
    world.sla = {tag: _insert(db, "sla_instances", definition_id=sla_def, org_id=ORG, status=status,
                              breached=breached, entity_module="sentinel", entity_type="breach",
                              resolution_due="2000-01-01 00:00:00", business_unit_id=unit[tag])
                 for tag, (status, breached) in sla_rows.items()}
    world.sla["other org"] = _insert(db, "sla_instances", definition_id=sla_def, org_id=OTHER_ORG, status="active",
                                     breached=1, entity_module="sentinel", entity_type="breach",
                                     resolution_due="2000-01-01 00:00:00")  # no unit, but another organization

    flow_def = _insert(db, "workflow_definitions", name="Flow", steps_json="[]", created_by=world.users["super"]["id"])
    flow_rows = {"org": "completed", "A": "active", "A1": "active", "B": "active"}
    world.flow = {tag: _insert(db, "workflow_instances", definition_id=flow_def, org_id=ORG, status=status,
                               started_by=world.users["super"]["id"], business_unit_id=unit[tag])
                  for tag, status in flow_rows.items()}
    world.flow["other org"] = _insert(db, "workflow_instances", definition_id=flow_def, org_id=OTHER_ORG,
                                      status="active", started_by=world.users["super"]["id"])
    # ERM risks (levels from likelihood x impact) and the appetite they are held against
    for title, category, l, i, tag in (("ERM op A", "operational", 5, 4, "A"), ("ERM op B", "operational", 2, 2, "B")):
        _insert(db, "erm_enterprise_risks", title=title, category=category, likelihood=l, impact=i,
                business_unit_id=unit[tag])
    _insert(db, "erm_risk_appetite", category="operational", max_score=10)
    _insert(db, "erm_risk_appetite", category="strategic", max_score=20)
    return world


def _count(world, name, table, condition=""):
    return scoped_count(world.db, world.users[name], table, condition)


# ── The shared rule ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", list(PERSONAS))
def test_platform_risks_follow_unit_and_capability(seeded, name):
    expected = len(SEES[name] & {"org", "A", "A1", "B"}) if name in CAN_VIEW_RISKS else 0
    assert _count(seeded, name, "risk_register", "status != 'closed'") == expected
    if name in CAN_VIEW_RISKS:
        assert expected > 0  # the positive twin: an empty answer would prove nothing


@pytest.mark.parametrize("name", list(PERSONAS))
def test_sla_clocks_and_workflow_instances_follow_unit_and_organization(seeded, name):
    """Only a sign-in is needed, so the employee sees them too; another organization's rows never show."""
    visible = len(SEES[name])
    assert _count(seeded, name, "sla_instances") == visible + (1 if name == "super" else 0)
    assert _count(seeded, name, "workflow_instances") == visible + (1 if name == "super" else 0)
    assert visible > 0


def test_a_parent_unit_sees_its_children_and_a_child_does_not_see_its_parent(seeded):
    assert _count(seeded, "dpo_a", "sla_instances", "breached = 1") == 1       # A1's clock
    assert _count(seeded, "dpo_a1", "sla_instances", "status = 'active' AND breached = 0") == 0  # A's, its parent's
    assert _count(seeded, "dpo_a", "sla_instances", "status = 'active' AND breached = 0") == 1


# ── The Command Centre cards ────────────────────────────────────────────────

# Written out by hand from the seed data. sla: met = resolved without a breach, breached = any breached clock,
# at_risk = open and not breached, pct = met / (met + breached). risk_counts: platform + ERM, open only.
CARDS = {
    "dpo_a":       dict(sla=(1, 1, 1, 50), flows=2, breaches=1, risks=(2, 1, 2, 0), overdue_sla=2, overdue_count=1),
    "dpo_a1":      dict(sla=(1, 1, 0, 50), flows=1, breaches=0, risks=(0, 1, 1, 0), overdue_sla=1, overdue_count=1),
    "dpo_b":       dict(sla=(1, 1, 0, 50), flows=1, breaches=0, risks=(1, 0, 1, 1), overdue_sla=1, overdue_count=1),
    "dpo_no_unit": dict(sla=(1, 0, 0, 100), flows=0, breaches=0, risks=(0, 0, 1, 0), overdue_sla=0, overdue_count=0),
    "owner_a":     dict(sla=(1, 1, 1, 50), flows=2, breaches=1, risks=(2, 1, 2, 0), overdue_sla=2, overdue_count=1),
    "owner_b":     dict(sla=(1, 1, 0, 50), flows=1, breaches=0, risks=(1, 0, 1, 1), overdue_sla=1, overdue_count=1),
    "employee_a":  dict(sla=(1, 1, 1, 50), flows=2, breaches=0, risks=(0, 0, 0, 0), overdue_sla=2, overdue_count=1),
}
# Whole-organization breaches of appetite seen from each persona's visible ERM risks (operational: 20 > 10 in unit A)
APPETITE = {"dpo_a": 1, "dpo_a1": 0, "dpo_b": 0, "dpo_no_unit": 0, "owner_a": 1, "owner_b": 0, "employee_a": 0}


def _stats(world, name):
    status, body = _call(dash.api_command_centre_stats(_request(world.users[name])))
    assert status == 200
    return body


@pytest.mark.parametrize("name", list(CARDS))
def test_the_sla_card_counts_the_visible_clocks(seeded, name):
    met, breached, at_risk, pct = CARDS[name]["sla"]
    assert _stats(seeded, name)["sla"] == {"pct": pct, "met": met, "at_risk": at_risk, "breached": breached}


@pytest.mark.parametrize("name", list(CARDS))
def test_the_workflow_card_counts_the_visible_active_instances(seeded, name):
    assert _stats(seeded, name)["workflow_active"] == CARDS[name]["flows"]


@pytest.mark.parametrize("name", list(CARDS))
def test_the_appetite_card_judges_only_the_risks_the_viewer_can_see(seeded, name):
    assert _stats(seeded, name)["erm_appetite_breaches"] == APPETITE[name]


@pytest.mark.parametrize("name", list(CARDS))
def test_the_risk_register_widget_counts_platform_and_enterprise_risks_in_scope(seeded, name):
    critical, high, medium, low = CARDS[name]["risks"]
    assert _stats(seeded, name)["risk_counts"] == {"critical": critical, "high": high, "medium": medium, "low": low}


@pytest.mark.parametrize("name", list(CARDS))
def test_overdue_sla_clocks_are_listed_and_counted_for_the_viewer(seeded, name):
    body = _stats(seeded, name)
    listed = {row["id"] for row in body["overdue_items"] if row["id"].startswith("SLA-")}
    expected_tags = {"dpo_a": {"A", "A1"}, "dpo_a1": {"A1"}, "dpo_b": {"B"}, "dpo_no_unit": set(),
                     "owner_a": {"A", "A1"}, "owner_b": {"B"}, "employee_a": {"A", "A1"}}[name]
    assert listed == {f"SLA-{seeded.sla[tag]}" for tag in expected_tags}
    assert body["overdue_count"] == CARDS[name]["overdue_count"]
    assert f"SLA-{seeded.sla['other org']}" not in listed


def test_the_restricted_payload_still_has_every_key_the_page_reads(seeded):
    """Same keys as the super administrator's, so the page needs no special case."""
    assert set(_stats(seeded, "dpo_a")) == set(_stats(seeded, "super"))


# ── My dashboard (the API behind the same figures) ──────────────────────────

def _mine(world, name):
    status, body = _call(dash.api_my_dashboard_data(_request(world.users[name])))
    assert status == 200
    return body


# platform risks by level, open only (what the super administrator's `risks` key means), per persona
PLATFORM_LEVELS = {
    "dpo_a": {"critical": 1, "high": 1, "medium": 1}, "owner_a": {"critical": 1, "high": 1, "medium": 1},
    "dpo_a1": {"high": 1, "medium": 1}, "dpo_b": {"critical": 1, "medium": 1}, "owner_b": {"critical": 1, "medium": 1},
    "dpo_no_unit": {"medium": 1}, "employee_a": {},
}
ACTIVE_BREACHES = {"dpo_a": 1, "owner_a": 1, "dpo_a1": 1, "dpo_b": 1, "owner_b": 1, "dpo_no_unit": 0, "employee_a": 1}


@pytest.mark.parametrize("name", list(PLATFORM_LEVELS))
def test_my_dashboard_reports_the_visible_active_breaches_and_platform_risks(seeded, name):
    body = _mine(seeded, name)
    assert body["sla_breaches"] == ACTIVE_BREACHES[name]
    assert body["risks"] == PLATFORM_LEVELS[name]


# ── Reports ─────────────────────────────────────────────────────────────────

def _report(world, name, kind):
    return reports._report_result(world.db, world.users[name], kind)


# total tracked, active, breached, resolved
SLA_REPORT = {"dpo_a": (3, 2, 1, 1), "owner_a": (3, 2, 1, 1), "employee_a": (3, 2, 1, 1), "dpo_a1": (2, 1, 1, 1),
              "dpo_b": (2, 1, 1, 1), "owner_b": (2, 1, 1, 1), "dpo_no_unit": (1, 0, 0, 1)}


@pytest.mark.parametrize("name", list(SLA_REPORT))
def test_the_sla_report_counts_the_visible_clocks(seeded, name):
    total, active, breached, resolved = SLA_REPORT[name]
    assert _report(seeded, name, "sla_performance") == {
        "total_tracked": total, "active": active, "breached": breached, "resolved": resolved}


# critical risks, high risks, active breaches in the executive brief
BRIEF = {"dpo_a": (1, 1, 1), "owner_a": (1, 1, 1), "dpo_a1": (0, 1, 1), "dpo_b": (1, 0, 1), "owner_b": (1, 0, 1),
         "dpo_no_unit": (0, 0, 0), "employee_a": (0, 0, 1)}


@pytest.mark.parametrize("name", list(BRIEF))
def test_the_executive_brief_includes_the_visible_platform_risks_and_clocks(seeded, name):
    critical, high, breaches = BRIEF[name]
    brief = _report(seeded, name, "executive_brief")
    assert (brief["risks_critical"], brief["risks_high"], brief["sla_breaches"]) == (critical, high, breaches)


@pytest.mark.parametrize("name", list(CARDS))
def test_the_risk_report_the_widget_and_the_register_page_agree(seeded, name):
    """One answer to 'how many open risks at each level can I see', on every surface."""
    report = _report(seeded, name, "risk_report")
    widget = _stats(seeded, name)["risk_counts"]
    status, page = _call(risks.api_risk_stats(_request(seeded.users[name])))
    assert status == 200
    assert report["by_level"] == widget == page["by_level"]
    assert report["total_open"] == page["total"] == sum(widget.values())
    assert report["by_module"] == page["by_module"] or not sum(widget.values())


def test_the_risk_report_lists_platform_and_enterprise_risks_by_score(seeded):
    report = _report(seeded, "dpo_a", "risk_report")
    assert report["total_open"] == 5 and report["by_module"] == {"sentinel": 3, "erm": 2}
    titles = [r["title"] for r in report["top_risks"]]
    assert set(titles) == {"needle risk A", "needle risk A1", "needle risk org", "ERM op A", "ERM risk A"}
    assert "needle risk B" not in titles and "needle risk A closed" not in titles
    scores = {"needle risk A": 20, "ERM op A": 20, "needle risk A1": 12, "needle risk org": 9, "ERM risk A": 9}
    assert [scores[t] for t in titles] == sorted(scores.values(), reverse=True)


# ── The risk register page ──────────────────────────────────────────────────

def _listed(world, name, **query):
    status, body = _call(risks.api_risks_list(_request(world.users[name], query)))
    assert status == 200
    return body


PLATFORM_TITLES = {
    "dpo_a": {"needle risk org", "needle risk A", "needle risk A1", "needle risk A closed"},
    "owner_a": {"needle risk org", "needle risk A", "needle risk A1", "needle risk A closed"},
    "dpo_a1": {"needle risk org", "needle risk A1"},
    "dpo_b": {"needle risk org", "needle risk B"}, "owner_b": {"needle risk org", "needle risk B"},
    "dpo_no_unit": {"needle risk org"}, "employee_a": set(),
}


@pytest.mark.parametrize("name", list(PLATFORM_TITLES))
def test_the_register_lists_the_platform_risks_in_scope(seeded, name):
    items = _listed(seeded, name)["items"]
    assert {r["title"] for r in items if r["register_source"] == "platform"} == PLATFORM_TITLES[name]


def test_the_register_filters_still_apply_inside_the_scope(seeded):
    open_only = _listed(seeded, "dpo_a", status="open")["items"]
    assert "needle risk A closed" not in {r["title"] for r in open_only}
    by_module = _listed(seeded, "dpo_a", module="sentinel")["items"]
    assert {r["register_source"] for r in by_module} == {"platform"}
    assert {r["title"] for r in by_module} == PLATFORM_TITLES["dpo_a"] - {"needle risk A closed"}  # it has no module


def _detail(world, name, rid):
    from fastapi import HTTPException
    try:
        return _call(risks.api_risk_get(_request(world.users[name]), rid))
    except HTTPException as refused:
        return refused.status_code, {"error": refused.detail}


def test_a_platform_risk_opens_for_the_units_that_may_see_it_and_for_nobody_else(seeded):
    ids = seeded.risk
    for name, opens, shut in (("dpo_a", ("A", "A1", "org"), ("B",)), ("dpo_a1", ("A1", "org"), ("A", "B")),
                              ("dpo_b", ("B", "org"), ("A", "A1")), ("super", ("A", "A1", "B", "org"), ()),
                              ("employee_a", (), ("A", "A1", "B", "org"))):
        for tag in opens:
            status, body = _detail(seeded, name, ids[tag])
            assert status == 200 and body["title"] == f"needle risk {tag}", (name, tag)
        for tag in shut:
            assert _detail(seeded, name, ids[tag])[0] == 404, (name, tag)


def _search(world, name, term):
    from modules.launcher import routes_platform as plat
    status, body = _call(plat.api_global_search(_request(world.users[name], {"q": term})))
    assert status == 200
    return {r["title"] for r in body["results"] if (r["module"], r["type"]) == ("platform", "risk")}


@pytest.mark.parametrize("name", list(PLATFORM_TITLES))
def test_topbar_search_finds_the_platform_risks_in_scope(seeded, name):
    assert _search(seeded, name, "needle risk") == PLATFORM_TITLES[name]


def test_writes_to_the_register_stay_with_the_super_administrator(seeded):
    for name in ("dpo_a", "owner_a", "employee_a"):
        request = _request(seeded.users[name], payload={"status": "closed"})
        assert _call(risks.api_risk_update(request, seeded.risk["A"]))[0] == 403
        assert _call(risks.api_risk_delete(_request(seeded.users[name]), seeded.risk["A"]))[0] == 403
    assert seeded.db.execute("SELECT status FROM risk_register WHERE id = %s", (seeded.risk["A"],)).fetchone()[0] == "open"


def _update(world, rid, **body):
    from fastapi import HTTPException
    try:
        return _call(risks.api_risk_update(_request(world.users["super"], payload=body), rid))
    except HTTPException as refused:
        return refused.status_code, {"error": refused.detail}


def test_a_super_administrator_can_move_a_risk_to_a_unit_or_back_to_organization_wide(seeded):
    unit = seeded.unit
    assert _update(seeded, seeded.risk["org"], business_unit_id=unit["B"])[0] == 200
    assert _detail(seeded, "dpo_b", seeded.risk["org"])[0] == 200 and _detail(seeded, "dpo_a", seeded.risk["org"])[0] == 404
    assert _update(seeded, seeded.risk["org"], business_unit_id=None)[0] == 200
    assert _detail(seeded, "dpo_a", seeded.risk["org"])[0] == 200


@pytest.mark.parametrize("bad", [999999, "abc", 0, True])
def test_a_risk_cannot_be_moved_to_a_unit_that_does_not_exist(seeded, bad):
    assert _update(seeded, seeded.risk["A"], business_unit_id=bad)[0] == 400
    assert seeded.db.execute("SELECT business_unit_id FROM risk_register WHERE id = %s",
                             (seeded.risk["A"],)).fetchone()[0] == seeded.unit["A"]


# ── Every other way in or out of the register honours the owner ─────────────

def _remove_entry(world, name, tag):
    from fastapi import HTTPException
    from modules.erm import routes as erm_routes
    try:
        response = asyncio.run(erm_routes.api_register_entry_delete(_request(world.users[name]), world.risk[tag]))
        return response.status_code
    except HTTPException as refused:
        return refused.status_code


def _exists(world, tag):
    return world.db.execute("SELECT 1 FROM risk_register WHERE id = %s", (world.risk[tag],)).fetchone() is not None


def test_the_erm_screen_cannot_delete_a_platform_risk_outside_the_callers_unit(seeded):
    assert _remove_entry(seeded, "owner_a", "B") == 404 and _exists(seeded, "B")
    assert _remove_entry(seeded, "owner_b", "A") == 404 and _exists(seeded, "A")
    assert _remove_entry(seeded, "owner_a", "A1") == 200 and not _exists(seeded, "A1")   # its own subtree
    assert _remove_entry(seeded, "owner_b", "B") == 200 and not _exists(seeded, "B")
    assert _remove_entry(seeded, "super", "A") == 200 and not _exists(seeded, "A")


def test_a_role_without_the_manage_capability_cannot_delete_platform_risks_at_all(seeded):
    assert _remove_entry(seeded, "dpo_a", "A") == 403 and _exists(seeded, "A")


def _bulk_export(world, name, kind):
    from modules.launcher import routes_platform as plat
    response = asyncio.run(plat.api_bulk_export(_request(world.users[name]), kind))
    return response.status_code, json.loads(response.body)


@pytest.mark.parametrize("kind", ["risks", "controls", "evidence", "ropa", "frameworks"])
def test_bulk_export_dumps_whole_tables_so_only_the_administrator_who_may_import_can_use_it(seeded, kind):
    """It used to need only a sign-in: an employee could download every risk, control, RoPA record and evidence row."""
    for name in ("dpo_a", "owner_a", "employee_a", "dpo_no_unit"):
        status, body = _bulk_export(seeded, name, kind)
        assert status == 403 and body == {"error": "Forbidden"}, (name, kind)
    status, body = _bulk_export(seeded, "super", kind)
    assert status == 200 and isinstance(body, list)


def test_the_administrators_risk_export_still_has_every_row(seeded):
    status, body = _bulk_export(seeded, "super", "risks")
    assert status == 200 and {r["title"] for r in body} >= {"needle risk A", "needle risk B", "needle risk org"}


# ── Through the routers (handler-level tests skip routing, which is where shadowed routes hide) ──────

@pytest.fixture
def http(seeded, monkeypatch):
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    import core.middleware as middleware
    from modules.launcher.routes import router as launcher_router

    who = {"name": "dpo_a"}

    async def current_user(request):
        return seeded.users[who["name"]]

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    app = FastAPI()
    app.include_router(launcher_router)
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False)

    def call(method, path, name="dpo_a", **kwargs):
        who["name"] = name
        return getattr(client, method)(path, **kwargs)

    return call


def test_the_restored_figures_arrive_through_the_real_routes(http):
    stats = http("get", "/api/command-centre/stats").json()
    assert stats["sla"] == {"pct": 50, "met": 1, "at_risk": 1, "breached": 1}
    assert stats["workflow_active"] == 2 and stats["erm_appetite_breaches"] == 1
    assert stats["risk_counts"] == {"critical": 2, "high": 1, "medium": 2, "low": 0}
    mine = http("get", "/api/my-dashboard/data").json()
    assert mine["sla_breaches"] == 1 and mine["risks"] == {"critical": 1, "high": 1, "medium": 1}
    page = http("get", "/api/risks/stats").json()
    assert page["total"] == 5 and page["by_level"] == stats["risk_counts"]


def test_the_register_routes_apply_the_unit_rule(http, seeded):
    listed = http("get", "/api/risks").json()
    assert {r["title"] for r in listed["items"] if r["register_source"] == "platform"} == PLATFORM_TITLES["dpo_a"]
    assert http("get", f"/api/risks/{seeded.risk['A1']}").status_code == 200
    assert http("get", f"/api/risks/{seeded.risk['B']}").status_code == 404
    assert http("get", f"/api/risks/{seeded.risk['A']}", name="dpo_b").status_code == 404
    assert http("get", f"/api/risks/{seeded.risk['A']}", name="employee_a").status_code == 404
    found = http("get", "/api/search", params={"q": "needle risk"}).json()["results"]
    assert {r["title"] for r in found if (r["module"], r["type"]) == ("platform", "risk")} == PLATFORM_TITLES["dpo_a"]


def test_the_register_can_only_be_written_by_the_super_administrator_through_the_routes(http, seeded):
    body = {"title": "Planted", "business_unit_id": seeded.unit["B"]}
    assert http("post", "/api/risks", json=body).status_code == 403
    assert http("put", f"/api/risks/{seeded.risk['A']}", json={"status": "closed"}).status_code == 403
    assert http("delete", f"/api/risks/{seeded.risk['A']}").status_code == 403
    assert http("post", "/api/risks", name="super", json=body).status_code == 201


def test_bulk_export_is_closed_to_everyone_but_the_administrator_through_the_routes(http):
    for name in ("dpo_a", "owner_a", "employee_a"):
        assert http("get", "/api/bulk/export/risks", name=name).status_code == 403, name
    assert http("get", "/api/bulk/export/risks", name="super").status_code == 200
