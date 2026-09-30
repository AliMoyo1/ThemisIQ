"""
PLAN-36 T08 ("Test multi-tab or concurrent behavior for approval,
task/update, and idempotent actions where race conditions matter").

The "approval" case already has real, thread-based coverage --
tests/test_aria_policy_approvals.py::test_two_concurrent_deciders_exactly_one_wins
-- proving ARIA's decide_approval() optimistic lock_version guard lets
exactly one of two simultaneous decisions win. ERM's workflow transitions
have an equivalent conditional-UPDATE guard keyed on workflow_step
(tests/test_concurrency_guards.py::test_workflow_stale_step_leaves_no_history).

This file is the "task/update" case: modules/launcher/routes_platform.py's
`api_task_update` (PUT /api/tasks/{tid}) has no such guard -- its UPDATE's
WHERE clause only re-checks existence and ownership
(`WHERE id=%s AND (created_by=%s OR assigned_to=%s)`), never a prior field
value, so `cur.rowcount` can only be 0 if the row vanished or ownership
changed, never because someone else's concurrent write already changed the
row. This test proves, with two genuinely concurrent real HTTP requests
against the live app (not a simulated single-threaded race), exactly what
that means in practice: both requests succeed, and the second one to commit
silently wins -- there is no conflict response and no way for either caller
to know their own write may have just been discarded. This is a factual
characterization of current behavior for the team to accept or harden, not
an assertion that 409-on-conflict is required here the way it is for a
formal approval decision.
"""
import concurrent.futures

import database
import httpx
import pytest


def _login(base_url: str, username: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=10)
    get_resp = client.get("/login")
    csrf = get_resp.cookies.get("csrf_token")
    resp = client.post("/login", data={
        "username": username, "password": password, "csrf_token": csrf,
    })
    assert resp.status_code in (302, 303), f"login POST did not redirect: {resp.status_code}"
    assert resp.headers.get("location") != "/login", "login rejected the credentials"
    return client


def test_two_concurrent_task_updates_both_succeed_last_write_silently_wins(
    live_app, synthetic_tenant
):
    creds = synthetic_tenant["users"]["super_admin"]
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO task_board (title, status, created_by, assigned_to) "
            "VALUES ('Concurrency Probe Task', 'todo', %s, %s)",
            (creds["user_id"], creds["user_id"]),
        )
        db.commit()
        tid = db.execute(
            "SELECT id FROM task_board WHERE title='Concurrency Probe Task'"
        ).fetchone()["id"]
    finally:
        db.close()

    results = []

    def _update(new_status: str):
        client = _login(live_app, creds["username"], creds["password"])
        try:
            resp = client.put(f"/api/tasks/{tid}", json={"status": new_status})
            results.append((new_status, resp.status_code))
        finally:
            client.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_update, "in_progress"),
            pool.submit(_update, "done"),
        ]
        for f in futures:
            f.result()

    statuses = {status_code for _, status_code in results}
    assert statuses == {200}, (
        f"expected both concurrent updates to report success (current, unguarded "
        f"behavior) -- got {results}. If this now fails because one leg returns "
        f"409, api_task_update has gained a conflict guard; update this test's "
        f"docstring and assertions to match, don't just loosen them."
    )

    db = database.get_db()
    try:
        final_status = db.execute(
            "SELECT status FROM task_board WHERE id=%s", (tid,)
        ).fetchone()["status"]
    finally:
        db.close()
    assert final_status in ("in_progress", "done"), (
        "the row must land on one of the two written values, not be corrupted"
    )
