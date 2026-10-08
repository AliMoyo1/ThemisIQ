"""Failures the code chooses to tolerate must still be visible, and must not cost more than they should.

swallowed(where)
    Call it first inside an `except` block that carries on. It logs the current exception at
    WARNING with its traceback, so a tolerated failure shows up in the logs instead of vanishing.

attempt(db, where)
    Run one optional database step so that its failure undoes only itself. On PostgreSQL the
    connection wrapper rolls the WHOLE transaction back when a statement fails, which would also
    throw away everything the caller had written before the step; a savepoint keeps that work.

is_missing_relation(exc)
    True for "this table or column does not exist" (an older schema), and nothing else. A guard
    that may skip a table must skip only for that reason: any other error has to surface.
"""
import logging
from contextlib import contextmanager

log = logging.getLogger("oneforall.best_effort")

_PG_MISSING = {"42P01", "42703"}  # undefined_table, undefined_column
_SQLITE_MISSING = ("no such table", "no such column")


def swallowed(where: str) -> None:
    log.warning("%s failed and was skipped", where, exc_info=True)


def is_missing_relation(exc: BaseException) -> bool:
    if getattr(exc, "pgcode", None) in _PG_MISSING:
        return True
    return type(exc).__name__ == "OperationalError" and str(exc).lower().startswith(_SQLITE_MISSING)


@contextmanager
def attempt(db, where: str):
    db.execute("SAVEPOINT best_effort_step")
    try:
        yield
    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT best_effort_step")
        db.execute("RELEASE SAVEPOINT best_effort_step")
        swallowed(where)
    else:
        db.execute("RELEASE SAVEPOINT best_effort_step")
