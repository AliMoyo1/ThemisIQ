"""Tolerated failures stay visible, and a tolerated database step no longer takes the rest of the
transaction with it (core/best_effort.py).

About ninety places catch a database error and carry on. Two things were wrong with that:

* nothing was logged, so a widget, a notification or an integrity alert could fail for months unseen;
* on PostgreSQL the connection wrapper rolls the WHOLE transaction back when a statement fails, so
  a "skip this table" step silently discarded every write the caller had made before it.
"""
import logging
import sqlite3

import pytest

from core.best_effort import attempt, is_missing_relation, swallowed


def test_swallowed_logs_the_current_exception_with_its_traceback(caplog):
    with caplog.at_level(logging.WARNING, logger="oneforall.best_effort"):
        try:
            raise ValueError("boom")
        except Exception:
            swallowed("dashboard widget: open tasks")
    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert "dashboard widget: open tasks" in record.getMessage()
    assert record.exc_info and record.exc_info[0] is ValueError


def test_attempt_keeps_the_callers_earlier_work_when_one_step_fails(test_db, caplog):
    test_db.execute("INSERT INTO frameworks (name) VALUES ('kept before the failure')")  # uncommitted
    with caplog.at_level(logging.WARNING, logger="oneforall.best_effort"):
        with attempt(test_db, "optional cleanup of a table that is gone"):
            test_db.execute("UPDATE no_such_table SET created_by = NULL")
        with attempt(test_db, "optional step that works"):
            test_db.execute("INSERT INTO frameworks (name) VALUES ('kept after the failure')")
    test_db.commit()

    names = {r["name"] for r in test_db.execute("SELECT name FROM frameworks").fetchall()}
    assert {"kept before the failure", "kept after the failure"} <= names
    assert any("optional cleanup of a table that is gone" in r.getMessage() for r in caplog.records)


def test_attempt_does_not_hide_a_connection_that_is_gone():
    """If even the rollback to the savepoint fails (a dead connection), that must surface."""

    class Gone:
        def execute(self, sql, params=None):
            if not sql.startswith("SAVEPOINT"):
                raise RuntimeError("connection lost")

    with pytest.raises(RuntimeError, match="connection lost"):
        with attempt(Gone(), "step"):
            raise sqlite3.OperationalError("step failed")


@pytest.mark.parametrize("message, expected", [
    ("no such table: grid_share_links", True),
    ("no such column: created_by", True),
    ("database is locked", False),
    ("UNIQUE constraint failed: users.email", False),
])
def test_is_missing_relation_recognises_only_an_absent_table_or_column_on_sqlite(message, expected):
    assert is_missing_relation(sqlite3.OperationalError(message)) is expected
    assert is_missing_relation(ValueError(message)) is False
