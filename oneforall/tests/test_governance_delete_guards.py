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


def _owned_by(db, table, unit):
    """A row of `table` that carries the unit as its owner."""
    if table == "risk_register":
        return _insert(db, table, title="Owned risk", business_unit_id=unit)
    if table == "sla_instances":
        definition = _insert(db, "sla_definitions", name="SLA", module="sentinel", entity_type="breach")
        return _insert(db, table, definition_id=definition, business_unit_id=unit)
    definition = _insert(db, "workflow_definitions", name="Flow", steps_json="[]")
    return _insert(db, table, definition_id=definition, business_unit_id=unit)


@pytest.mark.parametrize("table", ["risk_register", "sla_instances", "workflow_instances"])
def test_a_unit_that_owns_a_risk_a_clock_or_a_workflow_cannot_be_deleted(test_db, table):
    """These rows carry their owner's unit now; deleting it used to be a foreign key error, not a refusal."""
    bu = _insert(test_db, "business_units", name="Owner")
    _owned_by(test_db, table, bu)
    assert gov.delete_business_unit(bu) is False
    assert _exists(test_db, "business_units", bu)


def test_a_business_unit_with_children_cannot_be_deleted(test_db):
    parent = _insert(test_db, "business_units", name="Parent")
    _insert(test_db, "business_units", name="Child", parent_id=parent)
    assert gov.delete_business_unit(parent) is False
    assert _exists(test_db, "business_units", parent)


def _foreign_keys_to_business_units(db):
    """(table, column) for every foreign key that points at a business unit, read from the live schema."""
    return {
        (row[0], row[1])
        for row in db.execute(
            'SELECT m.name, f."from" FROM sqlite_master m, pragma_foreign_key_list(m.name) f '
            "WHERE m.type = 'table' AND f.\"table\" = 'business_units'"
        ).fetchall()
    }


def test_every_foreign_key_to_a_business_unit_is_checked_before_a_delete(test_db):
    """The list in delete_business_unit is kept by hand, and a table missing from it turns a refusal into a
    foreign key error (a 500). The schema says what must be on the list, so a table added later fails here."""
    in_schema = _foreign_keys_to_business_units(test_db) - {("business_units", "parent_id")}  # children: counted first
    assert in_schema, "the schema scan found no foreign keys to business_units"
    unchecked = in_schema - set(gov._BU_REFERENCES)
    assert not unchecked, f"delete_business_unit does not check {sorted(unchecked)}"


@pytest.mark.parametrize("table, column, other_column", [
    ("user_business_unit_assignments", "business_unit_id", None),
    ("business_unit_transfers", "from_business_unit_id", "to_business_unit_id"),
    ("business_unit_transfers", "to_business_unit_id", "from_business_unit_id"),
])
def test_a_unit_that_only_history_names_cannot_be_deleted(test_db, table, column, other_column):
    """Assignments and transfers record who sat where and when, and they outlive the move. Their foreign keys
    forbid the delete and removing those rows would erase the record, so the unit stays (deactivate it)."""
    unit = _insert(test_db, "business_units", name="Past")
    org = _insert(test_db, "organizations", name="Org", slug="org", status="active")
    user = _insert(test_db, "users", username="mover", email="mover@example.test", full_name="Mover",
                   password_hash="x", org_id=org)
    row = {"org_id": org, "user_id": user, column: unit}
    if other_column:
        row[other_column] = _insert(test_db, "business_units", name="Present")
    if table == "user_business_unit_assignments":
        row.update(valid_from="2026-01-01", valid_until="2026-06-01", status="ended")
    else:
        row.update(effective_at="2026-06-01", reason="Moved")
    _insert(test_db, table, **row)
    assert gov.delete_business_unit(unit) is False
    assert _exists(test_db, "business_units", unit)


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
