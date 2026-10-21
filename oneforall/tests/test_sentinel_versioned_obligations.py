"""Only approved jurisdiction cards with sourced triggers run a clock."""
from datetime import datetime, timezone

import pytest

from modules.sentinel import obligations


def _id(db, table, **columns):
    result = db.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(['%s'] * len(columns))})",
        tuple(columns.values()))
    db.commit()
    return result.lastrowid


def _setup(db):
    org = _id(db, "organizations", name="Pilot", slug="pilot")
    uid = _id(db, "users", username="dpo", email="dpo@example.test",
              full_name="DPO", password_hash="x", org_id=org)
    bid = _id(db, "sentinel_breaches", ref_number="BR-1", title="Pilot breach")
    return {"id": uid, "org_id": org, "roles": ["dpo"]}, bid


def _independent_dpo(db, user):
    uid = _id(db, "users", username="second_dpo", email="second_dpo@example.test",
              full_name="Second DPO", password_hash="x", org_id=user["org_id"])
    return {"id": uid, "org_id": user["org_id"], "roles": ["dpo"]}


def _card(key="EXAMPLE", **changes):
    return {"jurisdiction_key": key, "notice_type": "authority",
            "source_title": "Reviewed legal source", "source_url": "https://example.org/rule",
            "rule_summary": "Pilot interpretation", "trigger_definition": "Recorded discovery",
            "timezone": "UTC", "deadline_hours": 48, "effective_from": "2026-01-01", **changes}


def test_draft_missing_trigger_and_multiple_approved_clocks(test_db):
    user, breach = _setup(test_db)
    approver = _independent_dpo(test_db, user)
    first = obligations.create_card(_card(), user)
    draft_obligation = obligations.add_obligation(breach, {"rule_card_id": first,
        "applicability": "applies", "trigger_at": "2026-10-16T12:00:00+00:00",
        "trigger_source": "Confirmed discovery recorded by privacy specialist"}, user)
    now = datetime(2026, 10, 16, 13, tzinfo=timezone.utc)
    assert obligations.list_obligations(breach, user, now=now)[0]["clock"] == {
        "state": "awaiting_rule_approval", "deadline_at": None, "authoritative": False}
    obligations.approve_card(first, approver)
    first_clock = obligations.list_obligations(breach, user, now=now)[0]["clock"]
    assert first_clock["state"] == "running" and first_clock["authoritative"]
    assert first_clock["deadline_at"] == "2026-10-18T12:00:00+00:00"

    second = obligations.create_card(_card(key="SECOND", deadline_hours=24), user)
    obligations.approve_card(second, approver)
    obligations.add_obligation(breach, {"rule_card_id": second,
        "applicability": "applies", "trigger_source": "Pending discovery confirmation"}, user)
    clocks = [item["clock"]["state"] for item in obligations.list_obligations(breach, user, now=now)]
    assert clocks == ["running", "missing_trigger"]
    second_obligation = obligations.list_obligations(breach, user, now=now)[1]["id"]
    obligations.decide_obligation(second_obligation, "deferred", "Awaiting confirmed discovery time", user)
    obligations.update_obligation_facts(second_obligation, {
        "applicability": "applies", "trigger_at": "2026-10-16T13:00:00+00:00",
        "trigger_source": "Confirmed in incident log by privacy team"}, user)
    revised = obligations.list_obligations(breach, user, now=now)[1]
    assert revised["clock"]["state"] == "running" and revised["decision"] == "pending"
    assert test_db.execute("SELECT COUNT(*) FROM sentinel_obligation_history "
                           "WHERE obligation_id=%s", (second_obligation,)).fetchone()[0] == 2
    assert draft_obligation > 0


def test_card_approval_is_dpo_only_and_version_is_immutable(test_db):
    user, _ = _setup(test_db)
    approver = _independent_dpo(test_db, user)
    first = obligations.create_card(_card(), user)
    with pytest.raises(PermissionError):
        obligations.approve_card(first, {"id": user["id"], "org_id": user["org_id"],
                                         "roles": ["privacy_analyst"]})
    with pytest.raises(LookupError, match="independent approval"):
        obligations.approve_card(first, user)
    obligations.approve_card(first, approver)
    with pytest.raises(LookupError):
        obligations.approve_card(first, approver)
    second = obligations.create_card(_card(deadline_hours=72), user)
    versions = [item["version"] for item in obligations.list_cards(user)]
    assert (first, second) != (second, first) and versions == [2, 1]


def test_trigger_must_be_timezone_aware(test_db):
    user, breach = _setup(test_db)
    card = obligations.create_card(_card(), user)
    with pytest.raises(ValueError, match="timezone"):
        obligations.add_obligation(breach, {"rule_card_id": card,
            "trigger_at": "2026-10-16T12:00:00"}, user)
