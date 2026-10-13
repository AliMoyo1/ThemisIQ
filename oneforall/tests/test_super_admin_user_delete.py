"""Super admin deletion of an organization user (routes_super_admin.delete_org_user).

The clean-up reassigns or removes the user's rows table by table and tolerates a table that an older
schema does not have. That tolerance used to be a bare `except: pass`, which on PostgreSQL also threw
away the reassignments made before it (tests/test_postgres_init.py covers that on a real server). Here:
the same route on SQLite, with a missing table, a log line for it, and the other organization untouched.
"""
import asyncio
import json
import logging
import types

import pytest

import modules.launcher.routes_super_admin as super_admin

ROOT = {"id": 99, "username": "root", "org_id": None, "business_unit_id": None, "is_super_admin": 1,
        "roles": ["super_admin"]}


def _insert(db, table, **cols):
    cur = db.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        tuple(cols.values()),
    )
    db.commit()
    return cur.lastrowid


@pytest.fixture(autouse=True)
def as_root(monkeypatch):
    async def current_user(request):
        return ROOT

    monkeypatch.setattr(super_admin, "get_current_user", current_user)


def _delete(org_id, user_id):
    request = types.SimpleNamespace(state=types.SimpleNamespace(user=ROOT),
                                    url=types.SimpleNamespace(path="/x"), query_params={})
    response = asyncio.run(super_admin.delete_org_user(request, org_id, user_id))
    return response.status_code, json.loads(response.body)


def _world(db):
    org = _insert(db, "organizations", name="Del org", slug="del-org")
    other = _insert(db, "organizations", name="Other org", slug="other-org")
    doomed = _insert(db, "users", username="doomed", email="doomed@example.test", full_name="Doomed",
                     password_hash="x", org_id=org)
    bystander = _insert(db, "users", username="bystander", email="by@example.test", full_name="By",
                        password_hash="x", org_id=other)
    event = _insert(db, "events", event_type="test.event", source_module="platform", created_by=doomed)
    _insert(db, "notifications", user_id=doomed, module="platform", title="n", message="m")
    _insert(db, "user_roles", user_id=doomed, role_key="employee")
    return org, other, doomed, bystander, event


def test_deleting_a_user_reassigns_their_history_and_removes_what_they_owned(test_db):
    org, _, doomed, _, event = _world(test_db)
    assert _delete(org, doomed) == (200, {"ok": True})
    assert test_db.execute("SELECT 1 FROM users WHERE id=%s", (doomed,)).fetchone() is None
    assert test_db.execute("SELECT created_by FROM events WHERE id=%s", (event,)).fetchone()[0] is None
    assert test_db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=%s", (doomed,)).fetchone()[0] == 0
    assert test_db.execute("SELECT COUNT(*) FROM user_roles WHERE user_id=%s", (doomed,)).fetchone()[0] == 0


def test_a_table_missing_from_an_older_schema_is_skipped_and_logged(test_db, caplog):
    org, _, doomed, _, event = _world(test_db)
    test_db.execute("DROP TABLE grid_share_links")
    test_db.commit()
    with caplog.at_level(logging.WARNING, logger="oneforall.best_effort"):
        assert _delete(org, doomed) == (200, {"ok": True})
    assert test_db.execute("SELECT created_by FROM events WHERE id=%s", (event,)).fetchone()[0] is None
    assert any("grid_share_links" in r.getMessage() for r in caplog.records)


def test_a_user_of_another_organization_is_not_found_and_not_touched(test_db):
    org, other, doomed, bystander, _ = _world(test_db)
    status, body = _delete(org, bystander)
    assert status == 404 and "error" in body
    assert test_db.execute("SELECT 1 FROM users WHERE id=%s", (bystander,)).fetchone() is not None
