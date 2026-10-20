"""
A task handed to someone else, by an edit or by a bulk assignment, tells the new assignee in the app and by email
(plans/2026-10-governance-rework/14). Until now only creating a task did. A group of tasks is one message, and the person
who made the change is never told. Every "is not told" has a positive twin.
"""
import asyncio
import json
import types
from datetime import timedelta

import pytest

import core.middleware as middleware
from core import email as mail
from core import email_outbox as outbox
from core.timeutils import utcnow

# Bind the router's names to the real functions at collection time (the fixture below replaces get_current_user).
from modules.launcher import routes_platform as _routes  # noqa: E402,F401

ORG = 1


def _insert(db, table, **cols):
    cur = db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                     tuple(cols.values()))
    db.commit()
    return cur.lastrowid


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    async def current_user(request):
        return request.state.user

    monkeypatch.setattr(middleware, "get_current_user", current_user)


class Provider:
    def __init__(self):
        self.calls = []

    def __call__(self, *, to, subject, body_html, body_text=None):
        self.calls.append({"to": to, "subject": subject, "text": body_text, "html": body_html})
        return {"status": mail.STATUS_ACCEPTED, "ok": True, "provider": "fake"}


@pytest.fixture
def provider(monkeypatch):
    fake = Provider()
    monkeypatch.setattr(mail, "send_email", fake)
    monkeypatch.setenv("APP_URL", "https://app.themisiq.net")
    return fake


@pytest.fixture
def desk(test_db):
    db = test_db
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (1, 'org', 'org')")
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (2, 'other', 'other')")
    db.commit()
    people = {}
    for name, org in (("alice", ORG), ("bob", ORG), ("carol", ORG), ("outsider", 2)):
        uid = _insert(db, "users", username=name, email=f"{name}@example.test", full_name=name.title(),
                      password_hash="x", org_id=org)
        _insert(db, "user_roles", user_id=uid, role_key="employee")
        people[name] = {"id": uid, "username": name, "full_name": name.title(), "org_id": org, "business_unit_id": None,
                        "is_super_admin": False, "roles": ["employee"]}

    def task(title, owner="alice", assignee="alice", due="2026-12-01"):
        return _insert(db, "task_board", title=title, status="todo", created_by=people[owner]["id"],
                       assigned_to=people[assignee]["id"] if assignee else None, due_date=due)

    return types.SimpleNamespace(db=db, people=people, task=task)


def _request(user, payload):
    request = types.SimpleNamespace(state=types.SimpleNamespace(user=user), url=types.SimpleNamespace(path="/api/tasks"),
                                    query_params={}, client=None, headers={})

    async def _json():
        return payload

    request.json = _json
    return request


def _call(coro):
    response = asyncio.run(coro)
    return response.status_code, json.loads(response.body)


def _update(desk, who, task_id, payload):
    from modules.launcher import routes_platform as plat
    return _call(plat.api_task_update(_request(desk.people[who], payload), task_id))


def _bulk(desk, who, ids, updates):
    from modules.launcher import routes_platform as plat
    return _call(plat.api_tasks_bulk_update(_request(desk.people[who], {"ids": ids, "updates": updates})))


def _notices(desk, who):
    return [dict(r) for r in desk.db.execute(
        "SELECT title, message, link FROM notifications WHERE user_id = %s AND module = 'task' ORDER BY id",
        (desk.people[who]["id"],)).fetchall()]


def _outbox(desk, who=None):
    rows = [dict(r) for r in desk.db.execute("SELECT * FROM email_outbox ORDER BY id").fetchall()]
    return [r for r in rows if who is None or r["recipient_user_id"] == desk.people[who]["id"]]


# ── An edit that hands a task over ──────────────────────────────────────────

def test_handing_a_task_to_someone_tells_them_in_the_app_and_by_email_and_not_the_person_who_did_it(desk):
    task = desk.task("Renew the supplier register")
    status, _ = _update(desk, "alice", task, {"assigned_to": desk.people["bob"]["id"]})
    assert status == 200
    assert [n["title"] for n in _notices(desk, "bob")] == ["Task assigned to you: Renew the supplier register"]
    assert _notices(desk, "alice") == []
    (row,) = _outbox(desk, "bob")
    assert row["template_key"] == "action.assigned" and row["priority"] == "action" and row["route"] == "/tasks"
    assert json.loads(row["fields_json"]) == {"due": "2026-12-01", "kind": "task", "reference": f"TK-{task}"}
    assert "Renew the supplier register" not in json.dumps(row), "no title in the email"
    assert _outbox(desk, "alice") == []


def test_an_edit_that_hands_nothing_over_tells_nobody(desk):
    task = desk.task("Review the access list", assignee="bob")
    bob, alice = desk.people["bob"]["id"], desk.people["alice"]["id"]
    assert _update(desk, "alice", task, {"assigned_to": bob})[0] == 200, "the same person again"
    assert _update(desk, "alice", task, {"priority": "high", "title": "Review the access list now"})[0] == 200
    assert _notices(desk, "bob") == [] and _outbox(desk, "bob") == [], "unchanged, or another field only"
    assert _update(desk, "alice", task, {"assigned_to": alice})[0] == 200, "taking it back for herself"
    assert _notices(desk, "alice") == [] and _outbox(desk) == [], "the person who did it is not told, and nobody else is"

    fresh = desk.task("Own task", assignee="alice")
    assert _update(desk, "alice", fresh, {"assigned_to": alice})[0] == 200
    assert _notices(desk, "alice") == [] and _outbox(desk, "alice") == [], "giving it to yourself is not news"


def test_a_task_given_away_taken_back_and_given_again_is_told_each_time(desk, monkeypatch):
    task = desk.task("Hand over twice")
    bob = desk.people["bob"]["id"]
    moment = {"now": utcnow()}
    monkeypatch.setattr("core.timeutils.utcnow", lambda: moment["now"])
    _update(desk, "alice", task, {"assigned_to": bob})
    _update(desk, "bob", task, {"assigned_to": desk.people["alice"]["id"]})
    moment["now"] += timedelta(minutes=10)
    _update(desk, "alice", task, {"assigned_to": bob})
    assert len(_outbox(desk, "bob")) == 2, "a hand over is its own message"
    assert len(_outbox(desk, "alice")) == 1


def test_a_person_who_may_not_edit_the_task_hands_nothing_over(desk):
    task = desk.task("Not carol's", owner="alice", assignee="alice")
    status, body = _update(desk, "carol", task, {"assigned_to": desk.people["carol"]["id"]})
    assert status == 403
    assert _outbox(desk) == [] and _notices(desk, "carol") == []
    status, body = _update(desk, "alice", task, {"assigned_to": desk.people["outsider"]["id"]})
    assert status == 400 and "organization" in body["error"]
    assert _outbox(desk) == []


# ── A bulk assignment ───────────────────────────────────────────────────────

def test_a_group_of_tasks_is_one_message_and_only_the_tasks_that_changed_hands_are_counted(desk, provider):
    mine = [desk.task(f"Mine {i}") for i in range(2)]
    already = desk.task("Already bob's", assignee="bob", owner="alice")
    status, body = _bulk(desk, "alice", [*mine, already], {"assigned_to": desk.people["bob"]["id"]})
    assert status == 200 and body["updated"] == 3
    assert [n["title"] for n in _notices(desk, "bob")] == ["2 tasks assigned to you"]
    (row,) = _outbox(desk, "bob")
    assert row["template_key"] == "tasks.assigned" and json.loads(row["fields_json"]) == {"count": 2}
    assert row["source_type"] == "task_batch" and row["route"] == "/tasks"
    assert _outbox(desk, "alice") == []

    outbox.deliver_due(desk.db)
    (call,) = provider.calls
    assert call["to"] == "bob@example.test" and "2 task(s) are assigned to you" in call["text"]
    assert "https://app.themisiq.net/tasks" in call["text"] and "Mine 0" not in call["text"] + call["html"]


def test_one_task_in_a_bulk_assignment_is_told_as_a_task_and_none_changed_is_told_to_nobody(desk):
    only = desk.task("The only one")
    stays = desk.task("Stays with bob", assignee="bob")
    status, _ = _bulk(desk, "alice", [only, stays], {"assigned_to": desk.people["bob"]["id"]})
    assert status == 200
    (row,) = _outbox(desk, "bob")
    assert row["template_key"] == "action.assigned" and row["source_id"] == only
    assert [n["title"] for n in _notices(desk, "bob")] == ["Task assigned to you: The only one"]

    before = len(_outbox(desk))
    status, _ = _bulk(desk, "alice", [only, stays], {"assigned_to": desk.people["bob"]["id"]})
    assert status == 200 and len(_outbox(desk)) == before, "already his: nothing to tell"


def test_a_bulk_change_of_something_else_tells_nobody_and_the_bulk_route_keeps_its_permissions(desk):
    tasks = [desk.task(f"T{i}") for i in range(3)]
    status, body = _bulk(desk, "alice", tasks, {"priority": "high"})
    assert status == 200 and body["updated"] == 3 and _outbox(desk) == [] and _notices(desk, "bob") == []
    # carol owns none of them: nothing is updated, nothing is sent
    status, body = _bulk(desk, "carol", tasks, {"assigned_to": desk.people["carol"]["id"]})
    assert status == 403 and _outbox(desk) == []
