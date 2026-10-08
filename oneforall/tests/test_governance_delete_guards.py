"""Deleting a business unit or department checks what still points at it, and a failed check stops the delete.

delete_business_unit and delete_department count the rows that reference the record in a list of
tables, and refuse to delete while any exist. The check skipped a table on ANY error ("the table may
not exist in an older schema"), so a lock timeout or a permission error on a table that does exist let
the delete go ahead and left orphaned references. Only a table or column that is really absent may be
skipped now; every other failure surfaces.
"""
import sqlite3

import pytest

import modules.governance.data_service as gov


def _insert(db, table, **cols):
    cur = db.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        tuple(cols.values()),
    )
    db.commit()
    return cur.lastrowid


def _exists(db, table, row_id):
    return db.execute(f"SELECT 1 FROM {table} WHERE id=%s", (row_id,)).fetchone() is not None


class _FailsOn:
    """A connection that fails any statement mentioning `needle`, like a lock timeout would."""

    def __init__(self, real, needle):
        self._real, self._needle = real, needle

    def execute(self, sql, params=None):
        if self._needle in sql:
            raise sqlite3.OperationalError("database is locked")
        return self._real.execute(sql, params) if params is not None else self._real.execute(sql)

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def failing(monkeypatch, test_db):
    import database

    def install(needle):
        monkeypatch.setattr(gov, "get_db", lambda: _FailsOn(database.get_db(), needle))

    return install


def test_a_business_unit_that_is_still_referenced_cannot_be_deleted(test_db):
    bu = _insert(test_db, "business_units", name="Referenced")
    _insert(test_db, "sentinel_ropa", ref_number="R-1", processing_name="Payroll", business_unit_id=bu)
    assert gov.delete_business_unit(bu) is False
    assert _exists(test_db, "business_units", bu)


def test_a_table_missing_from_an_older_schema_is_skipped(test_db):
    bu = _insert(test_db, "business_units", name="Unreferenced")
    test_db.execute("DROP TABLE data_assets")
    test_db.commit()
    assert gov.delete_business_unit(bu) is True
    assert not _exists(test_db, "business_units", bu)


def test_any_other_failure_in_the_business_unit_check_stops_the_delete(test_db, failing):
    bu = _insert(test_db, "business_units", name="Checked")
    failing("FROM sentinel_ropa")
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        gov.delete_business_unit(bu)
    assert _exists(test_db, "business_units", bu), "an unchecked delete must not go ahead"


def test_a_department_that_is_still_referenced_cannot_be_deleted(test_db):
    dept = _insert(test_db, "departments", name="Referenced")
    _insert(test_db, "applications", name="Payroll app", department_id=dept)
    assert gov.delete_department(dept) is False
    assert _exists(test_db, "departments", dept)


def test_any_failure_in_the_department_check_stops_the_delete(test_db, failing):
    dept = _insert(test_db, "departments", name="Checked")
    failing("FROM business_processes")
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        gov.delete_department(dept)
    assert _exists(test_db, "departments", dept)
