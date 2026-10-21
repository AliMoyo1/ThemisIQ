"""
AI governance G1b: event delivery that survives a crash and a failing handler.

The bus used to run handlers once, inside emit(). A handler that failed, or a process that died after the source
change was committed but before emit(), left the event half done with nothing to retry it. These tests pin the
replacement: per-handler delivery rows, a retry schedule that ends in a dead letter an administrator can retry,
an enqueue that commits with the source change, and a sweeper that is safe to run from several processes.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.events as events
import database
from modules.launcher import routes_super_admin

PAST = "2000-01-01 00:00:00"


@pytest.fixture(autouse=True)
def _isolated_handler_registry(monkeypatch):
    """Each test registers handlers under an event type it invents; copy the registry so none leaks."""
    monkeypatch.setattr(events, "_handlers", dict(events._handlers))


def _row(db, event_id):
    return db.execute("SELECT * FROM events WHERE id=%s", (event_id,)).fetchone()


def _deliveries(db, event_id):
    return {r["handler"]: dict(r) for r in db.execute(
        "SELECT * FROM event_deliveries WHERE event_id=%s", (event_id,)).fetchall()}


def _make_due(event_id):
    db = database.get_db()
    try:
        db.execute("UPDATE events SET next_attempt_at=%s WHERE id=%s", (PAST, event_id))
        db.commit()
    finally:
        db.close()


def _handler_names(event_type):
    return [key for key, _ in events._handler_keys(event_type)]


# ── per-handler retry ───────────────────────────────────────────────────────

def test_a_retry_runs_only_the_handlers_that_have_not_succeeded(test_db):
    event_type = "test.g1b.partial_retry"
    runs = {"steady": 0, "flaky": 0}

    def steady(**kw):
        runs["steady"] += 1

    def flaky(**kw):
        runs["flaky"] += 1
        if runs["flaky"] == 1:
            raise RuntimeError("first attempt fails")

    events.on(event_type)(steady)
    events.on(event_type)(flaky)

    event_id = events.emit(event_type, "test")
    row = _row(test_db, event_id)
    assert row["status"] == "failed"
    assert row["attempts"] == 1
    assert "first attempt fails" in row["last_error"]
    assert row["next_attempt_at"] > events._now(), "the retry is scheduled in the future"
    deliveries = _deliveries(test_db, event_id)
    assert {d["status"] for d in deliveries.values() if "steady" in d["handler"]} == {"ok"}
    assert {d["status"] for d in deliveries.values() if "flaky" in d["handler"]} == {"failed"}

    assert events.deliver_pending()["delivered"] == 0, "a retry that is not due yet is left alone"
    _make_due(event_id)
    assert events.deliver_pending()["delivered"] == 1

    assert runs == {"steady": 1, "flaky": 2}, "the handler that had succeeded did not run a second time"
    row = _row(test_db, event_id)
    assert row["status"] == "processed"
    assert row["next_attempt_at"] is None
    assert row["last_error"] is None


def test_a_handler_that_keeps_failing_is_dead_lettered_after_the_attempt_cap(test_db):
    event_type = "test.g1b.dead_letter"
    calls = []

    def always_fails(**kw):
        calls.append(1)
        raise RuntimeError("downstream is down")

    events.on(event_type)(always_fails)

    event_id = events.emit(event_type, "test")
    for _ in range(events.MAX_ATTEMPTS - 1):
        assert _row(test_db, event_id)["status"] == "failed"
        _make_due(event_id)
        events.deliver_pending()

    row = _row(test_db, event_id)
    assert len(calls) == events.MAX_ATTEMPTS
    assert row["status"] == "dead"
    assert row["attempts"] == events.MAX_ATTEMPTS
    assert row["dead_lettered_at"] is not None
    assert row["next_attempt_at"] is None
    assert "downstream is down" in row["last_error"]

    # A dead event is parked: neither the sweeper nor a replay runs its handlers again.
    _make_due(event_id)
    assert events.deliver_pending() == {"delivered": 0, "failed": 0, "dead": 0, "skipped": 0}
    assert events.deliver(event_id) == "dead"
    assert len(calls) == events.MAX_ATTEMPTS
    assert [e["id"] for e in events.list_dead()] == [event_id]


def test_a_dead_event_can_be_retried_once_the_cause_is_fixed(test_db):
    event_type = "test.g1b.retry_dead"
    state = {"fixed": False, "good": 0}

    def good(**kw):
        state["good"] += 1

    def depends_on_fix(**kw):
        if not state["fixed"]:
            raise RuntimeError("not fixed yet")

    events.on(event_type)(good)
    events.on(event_type)(depends_on_fix)

    event_id = events.emit(event_type, "test")
    for _ in range(events.MAX_ATTEMPTS - 1):
        _make_due(event_id)
        events.deliver_pending()
    assert _row(test_db, event_id)["status"] == "dead"

    assert events.retry_dead(event_id + 999) is False
    state["fixed"] = True
    assert events.retry_dead(event_id) is True
    row = _row(test_db, event_id)
    assert (row["status"], row["attempts"], row["dead_lettered_at"]) == ("pending", 0, None)

    assert events.deliver_pending()["delivered"] == 1
    assert _row(test_db, event_id)["status"] == "processed"
    assert state["good"] == 1, "the handler that had already succeeded did not run again"
    assert events.retry_dead(event_id) is False, "only a dead event can be retried"
    assert events.list_dead() == []


def test_two_handlers_with_the_same_name_get_distinct_delivery_keys(test_db):
    event_type = "test.g1b.same_name"
    events.on(event_type)(lambda **kw: None)
    events.on(event_type)(lambda **kw: None)
    keys = _handler_names(event_type)
    assert len(keys) == len(set(keys)) == 2
    assert keys[1].endswith("#2")


# ── enqueue: the event commits with the source change ───────────────────────

def test_an_enqueued_event_rolls_back_with_the_source_change(test_db):
    event_type = "test.g1b.enqueue_rollback"
    calls = []
    events.on(event_type)(lambda **kw: calls.append(1))

    db = database.get_db()
    try:
        event_id = events.enqueue(db, event_type, "test", "thing", 7, {"k": "v"})
        db.rollback()  # the source change failed after the event was written
    finally:
        db.close()
    assert test_db.execute("SELECT COUNT(*) FROM events WHERE id=%s", (event_id,)).fetchone()[0] == 0
    assert events.deliver_pending()["delivered"] == 0
    assert calls == []


def test_an_enqueued_event_survives_a_caller_that_never_delivers_it(test_db):
    event_type = "test.g1b.enqueue_crash"
    seen = []
    events.on(event_type)(lambda **kw: seen.append((kw["entity_type"], kw["entity_id"], kw["payload"], kw["event_id"])))

    db = database.get_db()
    try:
        event_id = events.enqueue(db, event_type, "test", "thing", 7, {"k": "v"})
        db.commit()
    finally:
        db.close()
    # The process died here: the source change and the event are committed, nothing was delivered.
    assert _row(test_db, event_id)["status"] == "pending"
    assert seen == []
    assert events.deliver_pending()["delivered"] == 0, "the caller gets a short grace to deliver it itself"

    _make_due(event_id)
    assert events.deliver_pending() == {"delivered": 1, "failed": 0, "dead": 0, "skipped": 0}
    assert seen == [("thing", 7, {"k": "v"}, event_id)]
    assert _row(test_db, event_id)["status"] == "processed"
    assert events.deliver_pending()["delivered"] == 0, "delivered once, not again"


def test_enqueue_with_a_dedup_key_returns_the_existing_event(test_db):
    db = database.get_db()
    try:
        first = events.enqueue(db, "test.g1b.dedup", "test", dedup_key="dk-enqueue-1")
        db.commit()
        again = events.enqueue(db, "test.g1b.dedup", "test", dedup_key="dk-enqueue-1")
        db.commit()
    finally:
        db.close()
    assert again == first
    assert test_db.execute("SELECT COUNT(*) FROM events WHERE dedup_key='dk-enqueue-1'").fetchone()[0] == 1


# ── lease: no double delivery ───────────────────────────────────────────────

def test_an_event_being_delivered_is_not_picked_up_by_the_sweeper(test_db):
    event_type = "test.g1b.lease"
    calls = []
    nested = {}

    def slow_handler(**kw):
        calls.append(1)
        nested["counts"] = events.deliver_pending()  # a sweep that runs while emit() is still delivering

    events.on(event_type)(slow_handler)
    event_id = events.emit(event_type, "test")

    assert len(calls) == 1
    assert nested["counts"]["delivered"] == 0
    assert _row(test_db, event_id)["status"] == "processed"


def test_only_one_claim_succeeds_for_a_due_event(test_db):
    event_id = events.emit("test.g1b.claim", "test")
    db = database.get_db()
    try:
        db.execute("UPDATE events SET status='failed', next_attempt_at=%s WHERE id=%s", (PAST, event_id))
        db.commit()
    finally:
        db.close()
    assert events._claim(event_id) is True
    assert events._claim(event_id) is False, "the lease holds for the next sweeper"


def test_events_stored_before_this_design_are_never_replayed_by_the_sweeper(test_db):
    event_type = "test.g1b.legacy"
    calls = []
    events.on(event_type)(lambda **kw: calls.append(1))
    # What the previous bus left behind: a failed event with no retry schedule.
    db = database.get_db()
    try:
        event_id = database.insert_returning_id(
            db, "INSERT INTO events (event_type, source_module, status) VALUES (%s, %s, %s)",
            (event_type, "test", "failed"))
        db.commit()
    finally:
        db.close()
    assert events.deliver_pending()["delivered"] == 0
    assert calls == []
    assert _row(test_db, event_id)["status"] == "failed"


# ── emit never lets delivery trouble reach the source operation ─────────────

def test_emit_returns_the_event_id_even_when_delivery_cannot_start(test_db, monkeypatch):
    def broken(event_id):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(events, "deliver", broken)
    event_id = events.emit("test.g1b.broken_delivery", "test")
    assert event_id is not None
    row = _row(test_db, event_id)
    assert row["status"] == "pending" and row["next_attempt_at"] is not None, "the sweeper will deliver it"


def test_a_clean_emit_leaves_nothing_for_the_sweeper(test_db):
    event_type = "test.g1b.clean"
    events.on(event_type)(lambda **kw: None)
    event_id = events.emit(event_type, "test")
    row = _row(test_db, event_id)
    assert (row["status"], row["next_attempt_at"], row["attempts"]) == ("processed", None, 0)
    assert events.deliver_pending()["delivered"] == 0


# ── webhooks ────────────────────────────────────────────────────────────────

def test_the_webhook_handoff_is_not_repeated_when_only_a_handler_failed(test_db, monkeypatch):
    import core.webhooks as webhooks

    event_type = "test.g1b.webhook_once"
    handoffs = []
    monkeypatch.setattr(webhooks, "dispatch_event_background", lambda **kw: handoffs.append(kw["event_type"]))
    state = {"calls": 0}

    def fails_once(**kw):
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("boom")

    events.on(event_type)(fails_once)
    event_id = events.emit(event_type, "test")
    assert _row(test_db, event_id)["status"] == "failed"
    _make_due(event_id)
    events.deliver_pending()

    assert _row(test_db, event_id)["status"] == "processed"
    assert handoffs == [event_type], "the external system hears about the event once"


def test_a_failed_webhook_handoff_is_retried(test_db, monkeypatch):
    import core.webhooks as webhooks

    event_type = "test.g1b.webhook_retry"
    state = {"calls": 0}

    def handoff(**kw):
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("pool is down")

    monkeypatch.setattr(webhooks, "dispatch_event_background", handoff)
    event_id = events.emit(event_type, "test")
    assert _row(test_db, event_id)["status"] == "failed"
    _make_due(event_id)
    events.deliver_pending()
    assert _row(test_db, event_id)["status"] == "processed"
    assert state["calls"] == 2


# ── tenant context ──────────────────────────────────────────────────────────

def test_the_sweeper_runs_a_handler_inside_the_events_own_organization(test_db):
    event_type = "test.g1b.tenant"
    seen = []
    events.on(event_type)(lambda **kw: seen.append((database.get_current_org(), kw["org_id"])))

    db = database.get_db()
    try:
        db.execute("INSERT INTO organizations (id, name, slug, status) VALUES (41, 'Acme', 'acme', 'active')")
        event_id = events.enqueue(db, event_type, "test", org_id=41)
        db.commit()
    finally:
        db.close()
    assert _row(test_db, event_id)["org_id"] == 41

    _make_due(event_id)
    events.deliver_pending()
    assert seen == [(41, 41)]
    assert database.get_current_org() is None, "the sweeper leaves no tenant bound behind"


def test_emit_stores_the_organization_it_was_given(test_db):
    event_id = events.emit("test.g1b.org", "test", org_id=99)
    assert _row(test_db, event_id)["org_id"] == 99


# ── the platform operator's view of dead events ─────────────────────────────

@pytest.fixture
def operator_client(monkeypatch):
    """The super-admin router with the session lookup replaced by whoever the test says is calling."""
    caller = {"user": None}

    async def fake_user(request):
        return caller["user"]

    monkeypatch.setattr(routes_super_admin, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(routes_super_admin.router)
    return TestClient(app, follow_redirects=False), caller


def _dead_event(test_db):
    event_type = "test.g1b.operator"
    events.on(event_type)(lambda **kw: (_ for _ in ()).throw(RuntimeError("still broken")))
    event_id = events.emit(event_type, "test")
    for _ in range(events.MAX_ATTEMPTS - 1):
        _make_due(event_id)
        events.deliver_pending()
    assert _row(test_db, event_id)["status"] == "dead"
    return event_id


def test_the_dead_event_routes_are_for_the_platform_operator_only(test_db, operator_client):
    client, caller = operator_client
    event_id = _dead_event(test_db)

    caller["user"] = {"id": 5, "org_id": 1, "is_super_admin": 0}
    assert client.get("/super-admin/api/events/dead").status_code == 403
    assert client.post(f"/super-admin/api/events/{event_id}/retry").status_code == 403
    assert _row(test_db, event_id)["status"] == "dead", "a refused retry changed nothing"

    caller["user"] = None
    assert client.get("/super-admin/api/events/dead").status_code == 303


def test_the_operator_lists_and_retries_a_dead_event(test_db, operator_client):
    client, caller = operator_client
    event_id = _dead_event(test_db)
    caller["user"] = {"id": 1, "org_id": None, "is_super_admin": 1}

    listed = client.get("/super-admin/api/events/dead")
    assert listed.status_code == 200
    assert [e["id"] for e in listed.json()] == [event_id]
    assert "still broken" in listed.json()[0]["last_error"]

    assert client.post(f"/super-admin/api/events/{event_id + 999}/retry").status_code == 404
    assert client.post(f"/super-admin/api/events/{event_id}/retry").status_code == 200
    assert _row(test_db, event_id)["status"] == "pending"
    assert client.get("/super-admin/api/events/dead").json() == []
