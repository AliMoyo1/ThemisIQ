"""
Canonical vendor dedup tests.

Guards the cross-module identity layer against:
  - duplicate-name registrations across casing/whitespace
  - races where two writers create the same canonical record
"""
import pytest
from database import IntegrityError

from core.vendor_link import ensure_canonical


def test_new_vendor_gets_an_id(test_db):
    cid = ensure_canonical(test_db, "Acme Corp")
    test_db.commit()
    assert cid is not None
    assert cid > 0


def test_same_name_returns_same_id(test_db):
    a = ensure_canonical(test_db, "Acme Corp")
    b = ensure_canonical(test_db, "Acme Corp")
    test_db.commit()
    assert a == b


def test_dedup_is_case_and_whitespace_insensitive(test_db):
    a = ensure_canonical(test_db, "Acme Corp")
    b = ensure_canonical(test_db, "  ACME corp  ")
    test_db.commit()
    assert a == b


def test_empty_name_returns_none(test_db):
    assert ensure_canonical(test_db, "") is None
    assert ensure_canonical(test_db, "   ") is None


def test_contact_email_filled_in_on_second_call(test_db):
    cid = ensure_canonical(test_db, "Acme Corp")  # no email
    ensure_canonical(test_db, "Acme Corp", "ops@acme.test")
    test_db.commit()
    row = test_db.execute(
        "SELECT contact_email FROM canonical_vendors WHERE id=?", (cid,)
    ).fetchone()
    assert row["contact_email"] == "ops@acme.test"


def test_race_simulated_via_direct_duplicate_insert(test_db):
    """If a second writer wins the race, ensure_canonical recovers the row."""
    test_db.execute(
        "INSERT INTO canonical_vendors (name) VALUES (?)", ("Acme Corp",)
    )
    test_db.commit()
    # Simulate ensure_canonical losing the race: a duplicate INSERT will fail
    # against the UNIQUE index. The function must catch and return the existing id.
    cid = ensure_canonical(test_db, "Acme Corp")
    assert cid is not None
    # Only one row exists.
    rows = test_db.execute(
        "SELECT COUNT(*) AS c FROM canonical_vendors WHERE lower(trim(name))='acme corp'"
    ).fetchone()
    assert rows["c"] == 1


def test_unique_index_blocks_raw_duplicate_inserts(test_db):
    """Sanity check that the UNIQUE index is actually present."""
    test_db.execute("INSERT INTO canonical_vendors (name) VALUES (?)", ("Beta Ltd",))
    test_db.commit()
    with pytest.raises(IntegrityError):
        test_db.execute("INSERT INTO canonical_vendors (name) VALUES (?)", ("beta ltd",))
        test_db.commit()
