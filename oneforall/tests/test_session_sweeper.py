"""Expired session sweeper (core/session_sweeper.py, core.auth.cleanup_expired_sessions).

sessions.expires_at is TEXT holding naive UTC isoformat() strings, so the rows below use that exact shape and a fixed
clock: a same-day row that expired hours ago is the case a datetime('now') comparison (space instead of 'T') gets wrong.
Uses the standard conftest test_db fixture (fresh, fully migrated SQLite per test).
"""
import inspect
import logging
import time
from datetime import datetime, timedelta

import pytest

import database
from core import auth, session_sweeper
from core.timeutils import utcnow

NOW = datetime(2026, 10, 21, 12, 0, 0)
# (token, user key, expires_at, mfa_pending) for a mix of users, formats and MFA pending logins
EXPIRED = [
    ("a-long-ago", "a", "2026-01-01T00:00:00.123456", 0),
    ("a-same-day", "a", "2026-10-21T08:00:00", 0),
    ("a-just-expired", "a", "2026-10-21T11:59:59.999999", 0),
    ("b-yesterday", "b", "2026-10-20T23:59:59", 0),
    ("b-mfa-expired", "b", "2026-10-21T11:50:00", 1),
]
LIVE = [
    ("a-later-today", "a", "2026-10-21T18:00:00", 0),
    ("a-tomorrow", "a", "2026-10-22T09:00:00.500000", 0),
    ("b-next-second", "b", "2026-10-21T12:00:01", 0),
    ("b-mfa-live", "b", "2026-10-21T12:10:00", 1),
]


def _user(db, username):
    db.execute(
        "INSERT INTO users (username, email, full_name, password_hash) VALUES (%s,%s,%s,%s)",
        (username, f"{username}@example.com", username.title(), "x"),
    )
    db.commit()
    return db.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()["id"]


def _session(db, token, user_id, expires_at, mfa_pending=0):
    db.execute(
        "INSERT INTO sessions (token, user_id, expires_at, mfa_pending) VALUES (%s,%s,%s,%s)",
        (token, user_id, expires_at, mfa_pending),
    )
    db.commit()


def _tokens(db):
    return {r["token"] for r in db.execute("SELECT token FROM sessions").fetchall()}


@pytest.fixture
def seeded(test_db, monkeypatch):
    """Two users with expired and live sessions, and the auth clock stopped at NOW."""
    monkeypatch.setattr(auth, "utcnow", lambda: NOW)
    users = {"a": _user(test_db, "sweep_a"), "b": _user(test_db, "sweep_b")}
    for token, who, expires_at, mfa in EXPIRED + LIVE:
        _session(test_db, token, users[who], expires_at, mfa)
    return test_db


def test_cleanup_removes_only_expired_rows_of_every_user(seeded):
    removed = auth.cleanup_expired_sessions()

    assert removed == len(EXPIRED)
    assert _tokens(seeded) == {token for token, *_ in LIVE}


def test_run_once_purges_and_returns_the_count(seeded):
    assert session_sweeper.run_once() == len(EXPIRED)
    assert _tokens(seeded) == {token for token, *_ in LIVE}


def test_run_once_skips_while_another_worker_holds_the_lease(test_db):
    uid = _user(test_db, "lease_user")
    _session(test_db, "old", uid, "2000-01-01T00:00:00")
    assert database.try_acquire_scheduler_lock(test_db, session_sweeper._LOCK_NAME, 60) is True  # the other worker

    assert session_sweeper.run_once() == 0
    assert _tokens(test_db) == {"old"}

    # a worker that died holding the lease must not block the purge for good
    test_db.execute(
        "UPDATE scheduler_locks SET locked_until='2000-01-01T00:00:00' WHERE lock_name=%s",
        (session_sweeper._LOCK_NAME,),
    )
    test_db.commit()
    assert session_sweeper.run_once() == 1
    assert _tokens(test_db) == set()


def test_run_once_logs_a_failure_instead_of_raising(test_db, monkeypatch, caplog):
    def boom():
        raise RuntimeError("database went away")

    monkeypatch.setattr(session_sweeper, "cleanup_expired_sessions", boom)
    with caplog.at_level(logging.ERROR, logger="oneforall.session_sweeper"):
        assert session_sweeper.run_once() == 0
    assert "Session purge failed" in caplog.text


def test_scheduler_purges_at_startup_and_then_hourly(test_db):
    uid = _user(test_db, "sched_user")
    _session(test_db, "old", uid, (utcnow() - timedelta(hours=2)).isoformat())
    _session(test_db, "live", uid, (utcnow() + timedelta(hours=2)).isoformat())

    session_sweeper.start_scheduler()
    try:
        assert session_sweeper._scheduler.get_job("expired_session_purge").trigger.interval == timedelta(hours=1)
        deadline = time.time() + 10
        while "old" in _tokens(test_db) and time.time() < deadline:
            time.sleep(0.05)
        assert _tokens(test_db) == {"live"}, "the first run did not wait for the first hourly tick"
    finally:
        session_sweeper.stop_scheduler()


def test_the_app_starts_and_stops_the_sweeper():
    """main.py swallows a scheduler that fails to start with a log line, so only this guard notices the wiring gone."""
    import main

    assert "core.session_sweeper import start_scheduler" in inspect.getsource(main.startup)
    assert "core.session_sweeper import stop_scheduler" in inspect.getsource(main.shutdown)
