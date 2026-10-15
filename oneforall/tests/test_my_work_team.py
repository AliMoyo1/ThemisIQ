"""
My Work, "My team's": the work assigned to each person in the units the viewer heads
(plans/2026-10-governance-rework/04 section 3 and 11 step 6).

Expectations are written by hand. The rules under test: a team is the active people of the units the viewer heads (and
the units below them) that lie inside the viewer's own scope; only work assigned to a person is counted against them; an
item is shown only inside the viewer's own unit scope; a title from a module the viewer may not open is counted and not
named. Every "is not" has a positive twin.
"""
import asyncio
import json
import types
from datetime import timedelta

import pytest

import core.middleware as middleware
from core import rbac
from core.timeutils import utcnow
from modules.launcher import my_work_service as svc

# Bind the router's names to the real functions at collection time (the fixture below replaces get_current_user).
from modules.launcher import routes_my_work as _routes  # noqa: E402,F401

ORG = 1


def _insert(db, table, **cols):
    cur = db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                     tuple(cols.values()))
    db.commit()
    return cur.lastrowid


def _day(offset: int) -> str:
    return (utcnow() + timedelta(days=offset)).strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    async def current_user(request):
        return request.state.user

    monkeypatch.setattr(middleware, "get_current_user", current_user)


@pytest.fixture
def world(test_db):
    """Unit P with children C1 and C2, C1 with a child C1a, and a separate unit S; people in each."""
    db = test_db
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (1, 'org', 'org')")
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (2, 'other', 'other')")
    db.commit()
    unit = {"P": _insert(db, "business_units", name="Unit P", is_active=1)}
    unit["C1"] = _insert(db, "business_units", name="Unit C1", is_active=1, parent_id=unit["P"])
    unit["C2"] = _insert(db, "business_units", name="Unit C2", is_active=1, parent_id=unit["P"])
    unit["C1a"] = _insert(db, "business_units", name="Unit C1a", is_active=1, parent_id=unit["C1"])
    unit["S"] = _insert(db, "business_units", name="Unit S", is_active=1)

    people = {}

    def person(name, role, tag, active=1, org=ORG, super_admin=0):
        uid = _insert(db, "users", username=name, email=f"{name}@example.test", full_name=name.replace("_", " ").title(),
                      password_hash="x", org_id=org, business_unit_id=unit[tag], is_active=active,
                      is_super_admin=super_admin)
        _insert(db, "user_roles", user_id=uid, role_key=role)
        people[name] = {"id": uid, "username": name, "full_name": name.replace("_", " ").title(), "org_id": org,
                        "business_unit_id": unit[tag], "is_super_admin": bool(super_admin), "roles": [role]}

    person("head_p", rbac.COMPLIANCE_MGR, "P")
    person("head_c1", rbac.EMPLOYEE, "C1")
    person("solo", rbac.EMPLOYEE, "P")
    person("m1", rbac.AUDIT_LEAD, "C1")
    person("m1a", rbac.EMPLOYEE, "C1a")
    person("m2", rbac.EMPLOYEE, "C2")
    person("m3", rbac.EMPLOYEE, "S")
    person("gone", rbac.EMPLOYEE, "C1", active=0)
    person("outsider", rbac.EMPLOYEE, "C1", org=2)
    db.execute("UPDATE business_units SET head_user_id = %s WHERE id = %s", (people["head_p"]["id"], unit["P"]))
    db.execute("UPDATE business_units SET head_user_id = %s WHERE id = %s", (people["head_c1"]["id"], unit["C1"]))
    db.commit()

    def task(title, assignee, due=None, unit_tag=None, creator=None):
        return _insert(db, "task_board", title=title, status="todo", assigned_to=people[assignee]["id"],
                       created_by=people[creator or assignee]["id"], due_date=due,
                       business_unit_id=unit[unit_tag] if unit_tag else None)

    return types.SimpleNamespace(db=db, unit=unit, people=people, task=task)


def _named(member) -> list:
    return [i["title"] for i in member["overdue"]]


def _by_name(result) -> dict:
    return {m["name"]: m for m in result["members"]}


# ── Who is on the team ──────────────────────────────────────────────────────

def test_a_team_is_the_active_people_of_the_units_the_viewer_heads_and_the_units_below(world):
    result = svc.get_team_work(world.people["head_p"])
    assert result["is_manager"] is True
    assert sorted(m["name"] for m in result["members"]) == ["Head C1", "M1", "M1A", "M2", "Solo"]
    assert result["total_members"] == 5 and result["truncated"] is False
    assert [u["name"] for u in result["units"]] == ["Unit P", "Unit C1", "Unit C2", "Unit C1a"]
    # not the viewer, not a person of another unit, not an inactive person, not a person of another organization
    names = [m["name"] for m in result["members"]]
    for absent in ("Head P", "M3", "Gone", "Outsider"):
        assert absent not in names

    child = svc.get_team_work(world.people["head_c1"])
    assert sorted(m["name"] for m in child["members"]) == ["M1", "M1A"], "the head of C1 sees C1 and C1a only"
    assert {m["unit"] for m in child["members"]} == {"Unit C1", "Unit C1a"}


def test_a_person_who_heads_no_unit_has_no_team_view(world):
    result = svc.get_team_work(world.people["solo"])
    assert result == {"is_manager": False, "units": [], "members": [], "total_members": 0, "truncated": False}


def test_heading_a_unit_outside_your_own_scope_does_not_open_it(world):
    world.db.execute("UPDATE business_units SET head_user_id = %s WHERE id = %s",
                     (world.people["m3"]["id"], world.unit["C2"]))
    world.db.commit()
    # m3 belongs to unit S and heads C2, which is not in S's subtree
    assert svc.get_team_work(world.people["m3"])["is_manager"] is False


def test_an_inactive_unit_is_not_part_of_the_team(world):
    world.db.execute("UPDATE business_units SET is_active = 0 WHERE id = %s", (world.unit["C2"],))
    world.db.commit()
    result = svc.get_team_work(world.people["head_p"])
    assert "M2" not in [m["name"] for m in result["members"]]


# ── What is counted ─────────────────────────────────────────────────────────

def test_each_person_has_four_counts_and_their_oldest_overdue_items_in_order(world):
    t = world.task
    t("Overdue 30 days", "m1", _day(-30))
    t("Overdue 3 days", "m1", _day(-3))
    t("Due in 5 days", "m1", _day(5))
    t("Due in 90 days", "m1", _day(90))
    t("Asked of Mo Two", "m2", creator="m1")       # created by m1, assigned to m2: m1 waits, m2 acts
    t("Done long ago", "m1", _day(-60))            # overwritten below to done
    world.db.execute("UPDATE task_board SET status = 'done' WHERE title = 'Done long ago'")
    world.db.commit()

    result = svc.get_team_work(world.people["head_p"])
    m1 = _by_name(result)["M1"]
    assert m1["counts"] == {"overdue": 2, "due_soon": 1, "needs_my_action": 1, "waiting_on_others": 1}
    assert _named(m1) == ["Overdue 30 days", "Overdue 3 days"], "oldest first"
    assert m1["overdue"][0]["due_date"] == _day(-30) and m1["overdue"][0]["source"] == "Platform"
    assert m1["overdue"][0]["link"].startswith("/tasks?open=")
    assert m1["overdue_not_listed"] == 0 and m1["overdue_not_named"] == 0 and m1["incomplete"] is False

    m2 = _by_name(result)["M2"]
    assert m2["counts"] == {"overdue": 0, "due_soon": 0, "needs_my_action": 1, "waiting_on_others": 0}
    assert result["totals"] == {"overdue": 2, "due_soon": 1, "needs_my_action": 2, "waiting_on_others": 1}
    assert [m["name"] for m in result["members"]][0] == "M1", "the person with the most overdue is first"


def test_only_five_overdue_items_are_named_and_the_rest_are_counted(world):
    for i in range(8):
        world.task(f"Late {i}", "m1", _day(-10 - i))
    m1 = _by_name(svc.get_team_work(world.people["head_p"]))["M1"]
    assert m1["counts"]["overdue"] == 8 and len(m1["overdue"]) == 5
    assert m1["overdue_not_listed"] == 3 and m1["overdue_not_named"] == 0
    assert m1["overdue"][0]["title"] == "Late 7", "the oldest first"


def test_notifications_and_shared_queues_are_not_counted_against_anyone(world):
    db = world.db
    _insert(db, "notifications", user_id=world.people["m1"]["id"], module="platform", title="Unread note",
            message="x", link="/tasks")
    _insert(db, "evidence_items", title="Expired evidence", status="current", expiry_date=_day(-2), org_id=ORG,
            business_unit_id=world.unit["C1"])
    # the person's own list does show both, which is why the team view must not
    own = svc.get_my_work(world.people["m1"])
    own_titles = [i["title"] for sec in own["sections"].values() for i in sec]
    assert any("Expired evidence" in t for t in own_titles) and "Unread note" in own_titles

    m1 = _by_name(svc.get_team_work(world.people["head_p"]))["M1"]
    assert m1["counts"] == {"overdue": 0, "due_soon": 0, "needs_my_action": 0, "waiting_on_others": 0}


# ── Whose scope an item is read through ─────────────────────────────────────

def test_an_item_outside_the_viewers_unit_scope_is_neither_named_nor_counted(world):
    db = world.db
    # a person with unlimited reach (a platform administrator who sits in C1) has a task in S and one in C1
    person_id = _insert(db, "users", username="wide", email="wide@example.test", full_name="Wide Reach",
                        password_hash="x", org_id=ORG, business_unit_id=world.unit["C1"], is_super_admin=1)
    _insert(db, "user_roles", user_id=person_id, role_key=rbac.SUPER_ADMIN)
    for title, tag in (("Task in S", "S"), ("Task in C1", "C1"), ("Task for everyone", None)):
        _insert(db, "task_board", title=title, status="todo", assigned_to=person_id, created_by=person_id,
                due_date=_day(-4), business_unit_id=world.unit[tag] if tag else None)

    wide = _by_name(svc.get_team_work(world.people["head_c1"]))["Wide Reach"]
    assert sorted(_named(wide)) == ["Task for everyone", "Task in C1"], "the unit S task is not for this viewer"
    assert wide["counts"]["overdue"] == 2

    # the same task is visible to a viewer whose scope contains S
    db.execute("UPDATE business_units SET head_user_id = %s WHERE id = %s", (world.people["m3"]["id"], world.unit["S"]))
    db.execute("UPDATE users SET business_unit_id = %s WHERE id = %s", (world.unit["S"], person_id))
    db.commit()
    seen = _by_name(svc.get_team_work(world.people["m3"]))["Wide Reach"]
    assert "Task in S" in _named(seen)


def test_a_title_from_a_module_the_viewer_may_not_open_is_counted_and_not_named(world):
    db = world.db
    audit = _insert(db, "grid_audits", name="Audit C1", business_unit_id=world.unit["C1"],
                    lead_id=world.people["m1"]["id"])
    nc = _insert(db, "grid_non_conformances", audit_id=audit, title="Unpatched server", severity="major",
                 status="open", assigned_to=world.people["m1"]["id"], due_date=_day(-6))
    world.task("Plain task", "m1", _day(-2))

    # a compliance manager may open GRID: named, with the link
    allowed = _by_name(svc.get_team_work(world.people["head_p"]))["M1"]
    assert allowed["counts"]["overdue"] == 2 and allowed["overdue_not_named"] == 0
    assert [i["link"] for i in allowed["overdue"] if i["source"] == "GRID"] == [f"/grid/?open=nc:{nc}"]
    assert "Audit finding: Unpatched server" in _named(allowed)

    # an employee who heads the unit may not: counted, never named
    denied = _by_name(svc.get_team_work(world.people["head_c1"]))["M1"]
    assert denied["counts"]["overdue"] == 2
    assert _named(denied) == ["Plain task"] and denied["overdue_not_named"] == 1
    assert "Unpatched server" not in json.dumps(denied)


# ── Large teams ─────────────────────────────────────────────────────────────

def test_a_large_team_is_cut_at_the_limit_and_a_unit_can_be_chosen(world):
    for i in range(27):
        _insert(world.db, "users", username=f"zz_extra_{i:02d}", email=f"zz{i}@example.test",
                full_name=f"Zz Extra {i:02d}", password_hash="x", org_id=ORG, business_unit_id=world.unit["C1"])
    result = svc.get_team_work(world.people["head_c1"])
    assert result["total_members"] == 29 and len(result["members"]) == svc.TEAM_LIMIT == 25
    assert result["truncated"] is True

    narrowed = svc.get_team_work(world.people["head_c1"], world.unit["C1a"])
    assert [m["name"] for m in narrowed["members"]] == ["M1A"] and narrowed["truncated"] is False
    assert narrowed["unit_id"] == world.unit["C1a"]

    with pytest.raises(ValueError):
        svc.get_team_work(world.people["head_c1"], world.unit["S"])


# ── The route ───────────────────────────────────────────────────────────────

def _request(user, query=None):
    return types.SimpleNamespace(state=types.SimpleNamespace(user=user), url=types.SimpleNamespace(path="/api/x"),
                                 query_params=query or {}, client=None, headers={})


def _call(coro):
    response = asyncio.run(coro)
    return response.status_code, json.loads(response.body)


def test_the_route_answers_a_manager_and_a_person_without_a_team(world):
    from modules.launcher import routes_my_work as routes
    world.task("Late", "m1", _day(-3))
    status, body = _call(routes.api_my_work_team(_request(world.people["head_p"])))
    assert status == 200 and body["is_manager"] is True
    assert _by_name(body)["M1"]["counts"]["overdue"] == 1
    status, body = _call(routes.api_my_work_team(_request(world.people["solo"])))
    assert status == 200 and body["is_manager"] is False and body["members"] == []


def test_the_route_refuses_a_bad_or_foreign_unit(world):
    from modules.launcher import routes_my_work as routes
    manager = world.people["head_c1"]
    status, body = _call(routes.api_my_work_team(_request(manager, {"unit_id": "abc"})))
    assert status == 422 and "number" in body["error"]
    status, body = _call(routes.api_my_work_team(_request(manager, {"unit_id": str(world.unit["S"])})))
    assert status == 422 and "not one of yours" in body["error"]
    status, body = _call(routes.api_my_work_team(_request(manager, {"unit_id": str(world.unit["C1a"])})))
    assert status == 200 and [m["name"] for m in body["members"]] == ["M1A"]
