"""
PLAN-35 T11 review findings: core/events.py's emit() dedup_key handling and
per-event status.

Two related P1/P2 findings, both about the same root cause -- the event
row is committed before handlers run, and each handler independently
wrote the shared status column:

  P1: a crash (or a handler failure with no other recovery path) between
      the commit and the handler loop finishing left a permanently
      un-processed event that every future dedup_key replay treated as
      "already delivered" and skipped forever, without ever running a
      single handler.
  P2: with more than one handler, a later handler's success overwrote an
      earlier handler's failure in the shared status column, hiding it
      from anything reading events.status later (e.g. the ARIA
      publication-status endpoint's event_handler_status field).

Fixed together: status is now computed once, after the whole handler loop
finishes, from the combined outcome; and a dedup_key replay only
short-circuits when that combined status is 'processed' -- otherwise it
reruns delivery against the existing event id instead of returning it
untouched.
"""
import pytest

import core.events as events


@pytest.fixture(autouse=True)
def _isolated_handler_registry(monkeypatch):
    """Each test registers handlers under a unique event_type string it
    invents, so this never needs to interact with any real handler in
    core/event_handlers.py -- but copy the registry anyway so a test
    mutating it can't leak a stray entry into a later test in the same
    process."""
    monkeypatch.setattr(events, "_handlers", dict(events._handlers))


def test_a_dedup_key_replay_after_full_success_does_not_rerun_handlers(test_db):
    event_type = "test.t11.success_replay"
    calls = []
    events.on(event_type)(lambda **kw: calls.append(1))

    first_id = events.emit(event_type, "test", dedup_key="dk-success-1")
    assert len(calls) == 1
    status = test_db.execute("SELECT status FROM events WHERE id=%s", (first_id,)).fetchone()["status"]
    assert status == "processed"

    second_id = events.emit(event_type, "test", dedup_key="dk-success-1")
    assert second_id == first_id
    assert len(calls) == 1  # not rerun


def test_a_dedup_key_replay_after_a_handler_failure_reruns_delivery(test_db):
    """The P1 fix: a row that exists but never reached 'processed' (a
    handler raised, or -- in the crash case this models -- the process
    died before the status write landed) must be retried on replay, not
    treated as already delivered."""
    event_type = "test.t11.failure_replay"
    calls = []

    def flaky(**kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("simulated handler failure on first attempt")

    events.on(event_type)(flaky)

    first_id = events.emit(event_type, "test", dedup_key="dk-retry-1")
    assert len(calls) == 1
    status = test_db.execute("SELECT status FROM events WHERE id=%s", (first_id,)).fetchone()["status"]
    assert status == "failed"

    second_id = events.emit(event_type, "test", dedup_key="dk-retry-1")
    assert second_id == first_id  # same event row, not a new one
    assert len(calls) == 2  # handler really did run again
    status = test_db.execute("SELECT status FROM events WHERE id=%s", (first_id,)).fetchone()["status"]
    assert status == "processed"  # the second attempt succeeded


def test_status_reflects_the_whole_loop_not_the_last_handler(test_db):
    """P2: a later handler's success must not hide an earlier handler's
    failure in the shared status column."""
    event_type = "test.t11.mixed_outcome"

    def failing(**kw):
        raise RuntimeError("first handler fails")

    def succeeding(**kw):
        pass

    events.on(event_type)(failing)
    events.on(event_type)(succeeding)

    event_id = events.emit(event_type, "test")
    status = test_db.execute("SELECT status FROM events WHERE id=%s", (event_id,)).fetchone()["status"]
    assert status == "failed"


def test_status_reaches_processed_even_with_zero_registered_handlers(test_db):
    """An event type nothing has registered a handler for must still reach
    a terminal 'processed' state -- otherwise it would sit at 'pending'
    forever, and every future dedup_key replay would treat it as
    never-delivered and re-dispatch webhooks indefinitely."""
    event_id = events.emit("test.t11.no_handlers", "test", dedup_key="dk-no-handlers")
    status = test_db.execute("SELECT status FROM events WHERE id=%s", (event_id,)).fetchone()["status"]
    assert status == "processed"

    replay_id = events.emit("test.t11.no_handlers", "test", dedup_key="dk-no-handlers")
    assert replay_id == event_id


def test_concurrent_duplicate_insert_still_defers_to_the_winner(test_db, monkeypatch):
    """Unchanged pre-existing behavior: a real IntegrityError race (two
    genuinely concurrent emits for the same dedup_key both past the
    initial SELECT) must still let the losing call's insert fail, roll
    back, and return the winner's id without running handlers itself --
    this path is untouched by the P1/P2 fix and must stay that way."""
    event_type = "test.t11.integrity_race"
    calls = []
    events.on(event_type)(lambda **kw: calls.append(1))

    real_insert_returning_id = events.insert_returning_id
    call_count = {"n": 0}

    def flaky_insert(db, sql, params):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Simulate: another connection committed the same dedup_key
            # between our SELECT and our INSERT.
            db2 = events.get_db()
            try:
                db2.execute(
                    "INSERT INTO events (event_type, source_module, dedup_key) VALUES (%s,%s,%s)",
                    (event_type, "test", "dk-race-1"),
                )
                db2.commit()
            finally:
                db2.close()
            raise events.IntegrityError("UNIQUE constraint failed: events.dedup_key")
        return real_insert_returning_id(db, sql, params)

    monkeypatch.setattr(events, "insert_returning_id", flaky_insert)
    winner_id = events.emit(event_type, "test", dedup_key="dk-race-1")
    assert winner_id is not None
    assert len(calls) == 0  # the losing call never ran handlers itself
