"""
The breach notification clock says what it is counted from, and never runs without a trigger
(plans/2026-10-governance-rework/03 section 6). Every deadline is indicative: it counts from the recorded discovery date by
the configured rule, and a privacy specialist decides the legal trigger and obligation.
"""
import pytest

from modules.sentinel import data_service as sds
from modules.sentinel.jurisdictions import breach_clock


def test_no_discovery_date_means_no_clock_whatever_the_regulation():
    for regulation in ("GDPR", "South Africa POPIA", "Unknown Act", None):
        clock = breach_clock(regulation, None)
        assert clock["state"] == "no_trigger" and clock["hours"] is None and "not recorded" in clock["label"]
    assert breach_clock("GDPR", "")["state"] == "no_trigger"


def test_a_regulation_with_no_rule_gets_no_deadline_instead_of_a_guess():
    clock = breach_clock("Atlantis Privacy Act", "2026-10-01")
    assert clock["state"] == "no_rule" and clock["hours"] is None
    assert "Atlantis Privacy Act" in clock["label"] and "no deadline is calculated" in clock["label"]


def test_an_as_soon_as_practicable_regulation_has_no_fixed_hours():
    for regulation in ("South Africa POPIA", "Canada PIPEDA", "India DPDP"):
        clock = breach_clock(regulation, "2026-10-01")
        assert clock["state"] == "asap" and clock["hours"] is None
        assert "internal target, not a legal deadline" in clock["label"]


@pytest.mark.parametrize("regulation, hours", [("GDPR", 72), ("Brazil LGPD", 48), ("Japan APPI", 720), ("Zimbabwe CDPA", 72)])
def test_a_fixed_rule_is_indicative_and_names_what_it_is_counted_from(regulation, hours):
    clock = breach_clock(regulation, "2026-10-01 08:30:00")
    assert clock["state"] == "indicative" and clock["hours"] == hours
    assert clock["basis"] == f"{hours} hours after the recorded discovery date under {regulation}"
    assert "privacy specialist confirms the legal trigger" in clock["label"]


def _breach(db, **cols):
    cols = {"ref_number": "BR-T1", "title": "Mailbox exposure", **cols}
    cur = db.execute(f"INSERT INTO sentinel_breaches ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                     tuple(cols.values()))
    db.commit()
    return cur.lastrowid


def test_a_breach_row_carries_its_clock(test_db):
    with_date = _breach(test_db, ref_number="BR-1", regulation="GDPR", discovery_date="2026-10-01")
    without = _breach(test_db, ref_number="BR-2", regulation="GDPR")
    assert sds.get_breach(with_date)["clock"]["state"] == "indicative"
    assert sds.get_breach(without)["clock"]["state"] == "no_trigger"


def test_an_edited_discovery_date_or_regulation_moves_the_deadline_and_a_cleared_date_removes_it(test_db):
    bid = _breach(test_db, regulation="GDPR", discovery_date="2026-10-01", notify_deadline="2026-10-04 00:00:00")
    sds.update_breach(bid, {"discovery_date": "2026-10-10"})
    assert sds.get_breach(bid)["notify_deadline"] == "2026-10-13 00:00:00"
    sds.update_breach(bid, {"regulation": "Brazil LGPD"})
    assert sds.get_breach(bid)["notify_deadline"] == "2026-10-12 00:00:00", "48 hours under LGPD"
    sds.update_breach(bid, {"title": "Mailbox exposure, updated"})
    assert sds.get_breach(bid)["notify_deadline"] == "2026-10-12 00:00:00", "an unrelated edit leaves the clock alone"
    sds.update_breach(bid, {"discovery_date": ""})
    row = sds.get_breach(bid)
    assert row["notify_deadline"] is None and row["clock"]["state"] == "no_trigger"
    sds.update_breach(bid, {"discovery_date": "2026-10-20", "notify_deadline": "2026-10-21 12:00:00"})
    assert sds.get_breach(bid)["notify_deadline"] == "2026-10-21 12:00:00", "an explicit deadline is kept as given"
