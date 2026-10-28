"""
The read-only inventory for plans 19 and 20 (scripts/inventory_group_oversight.py).

It must report counts and organization or business-unit names only, never a person's name, email, record title or file
name, and it must be unable to write.
"""
import importlib.util
import pathlib

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "inventory_group_oversight.py"
spec = importlib.util.spec_from_file_location("inventory_group_oversight", SCRIPT)
inv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inv)

SECRET_NAME = "Tendai Moyo"
SECRET_EMAIL = "tendai.moyo@example.test"
SECRET_TITLE = "EcoCash confidential settlement policy"


def _seed(db):
    unit = lambda name: db.execute("SELECT id FROM business_units WHERE name=%s", (name,)).fetchone()["id"]  # noqa: E731
    db.execute("INSERT INTO business_units (name) VALUES ('Econet Group')")
    db.execute("INSERT INTO business_units (name, parent_id) VALUES ('EcoCash', %s)", (unit("Econet Group"),))
    db.execute("INSERT INTO business_units (name, parent_id) VALUES ('Finance', %s)", (unit("EcoCash"),))
    db.commit()
    finance = unit("Finance")
    db.execute("INSERT INTO users (id, username, email, full_name, password_hash) VALUES (1,'tm',%s,%s,'x')",
               (SECRET_EMAIL, SECRET_NAME))
    db.execute("INSERT INTO sentinel_dsr (ref_number, requester_name, requester_email, description) "
               "VALUES ('D-1', %s, %s, 'Please delete my data')", (SECRET_NAME, SECRET_EMAIL))
    db.execute("INSERT INTO sentinel_dsr (ref_number, requester_name) VALUES ('D-2', '')")
    db.execute("INSERT INTO evidence_items (title, business_unit_id) VALUES (%s, NULL)", (SECRET_TITLE,))
    db.execute("INSERT INTO evidence_items (title, business_unit_id) VALUES ('Group wide charter', NULL)")
    db.execute("INSERT INTO evidence_items (title, business_unit_id) VALUES ('Finance procedure', %s)", (finance,))
    first = db.execute("SELECT id FROM evidence_items WHERE title=%s", (SECRET_TITLE,)).fetchone()["id"]
    db.execute("INSERT INTO evidence_items (title, parent_id, business_unit_id) VALUES ('EcoCash settlement v2', %s, NULL)", (first,))
    db.commit()


def test_the_inventory_counts_what_is_there(test_db):
    _seed(test_db)
    data = inv.inventory_one(test_db, sqlite=True)
    assert {"Econet Group", "EcoCash", "Finance"} <= set(data["units"]["names"])
    assert data["units"]["max_depth"] == 2 and "Econet Group" in data["units"]["roots"]
    assert data["personal"]["sentinel_dsr.requester_name"] == 1, "an empty string is not a value"
    assert data["personal"]["sentinel_dsr.requester_email"] == 1
    assert data["personal"]["users.email"] == 1
    assert data["free_text"]["sentinel_dsr.description"] == 1
    ev = data["evidence"]
    assert (ev["items"], ev["no_unit"], ev["families"], ev["versions_in_chains"]) == (4, 3, 3, 1)
    assert ev["no_unit_mentioning_a_name"]["ecocash"] == 2, "no-unit items that mention a unit name are narrowing candidates"
    assert data["row_counts"]["sentinel_dsr"] == 2


def test_the_output_never_contains_a_person_a_title_or_a_file_name(test_db, capsys):
    _seed(test_db)
    inv.print_inventory("test", inv.inventory_one(test_db, sqlite=True))
    out = capsys.readouterr().out
    for secret in (SECRET_NAME, SECRET_EMAIL, SECRET_TITLE, "Please delete my data", "settlement"):
        assert secret not in out, secret
    assert "EcoCash" in out and "sentinel_dsr.requester_email: 1" in out


def test_it_refuses_anything_but_a_select(test_db):
    for statement in ("DELETE FROM users", "UPDATE users SET email='x'", "INSERT INTO users (id) VALUES (9)"):
        with pytest.raises(ValueError):
            inv._count(test_db, statement)
    with pytest.raises(ValueError):
        inv._ident("users; DROP TABLE users")


def test_a_missing_table_is_reported_as_absent_not_as_an_error(test_db):
    cols = inv.existing_columns(test_db, None, sqlite=True)
    cols.pop("sentinel_dsr", None)
    assert "sentinel_dsr.requester_name" not in inv.personal_columns(test_db, cols)
