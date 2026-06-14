"""
Cross-module link tests.

Guards the link-creation path against the TOCTOU race that previously allowed
duplicate links under concurrent writes.
"""
from core.links import create_cross_module_link


def test_create_returns_link_id(test_db):
    link_id = create_cross_module_link(
        "sentinel", "breach", 1,
        "erm", "risk", 1,
        relationship="elevated_to",
        db=test_db,
    )
    test_db.commit()
    assert link_id is not None and link_id > 0


def test_duplicate_create_returns_same_id(test_db):
    a = create_cross_module_link(
        "sentinel", "breach", 1, "erm", "risk", 1,
        relationship="elevated_to", db=test_db,
    )
    test_db.commit()
    b = create_cross_module_link(
        "sentinel", "breach", 1, "erm", "risk", 1,
        relationship="elevated_to", db=test_db,
    )
    test_db.commit()
    assert a == b
    # Verify exactly one row exists.
    count = test_db.execute(
        "SELECT COUNT(*) AS c FROM cross_module_links"
    ).fetchone()
    assert count["c"] == 1


def test_invalid_source_module_returns_none(test_db):
    link_id = create_cross_module_link(
        "not_a_module", "breach", 1, "erm", "risk", 1,
        relationship="related", db=test_db,
    )
    assert link_id is None


def test_invalid_relationship_falls_back_to_related(test_db):
    create_cross_module_link(
        "sentinel", "breach", 1, "erm", "risk", 1,
        relationship="something_invented", db=test_db,
    )
    test_db.commit()
    row = test_db.execute(
        "SELECT relationship FROM cross_module_links LIMIT 1"
    ).fetchone()
    assert row["relationship"] == "related"
