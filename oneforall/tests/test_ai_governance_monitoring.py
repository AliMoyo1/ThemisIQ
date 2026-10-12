"""
AI governance G5: the Monitoring tab says, for each source, whether it reports something to look at, reports all is as it
should be, has nothing because nothing is measured, is not open to the viewer, or could not be read. Silence is never health.
"""
import pytest

from modules.ai_governance import evaluations, monitoring, regulation, service
from modules.governance import relationships
from tests.test_ai_governance_evaluations import RUN
from tests.test_ai_governance_service import FULL, approve_new, commit, fail, submitted, user
from tests.test_platform_ownership import PERSONAS, _insert, world  # noqa: F401


@pytest.fixture
def system(world):
    done = approve_new(world, submitted(world, answers=FULL))
    world.app = done["application_id"]
    return world


def states(world, name="dpo_a"):
    got = monitoring.get_monitoring(world.db, user(world, name), world.app)
    return {s["source"]: s["state"] for s in got["sources"]}, got


def test_a_new_use_measures_nothing_and_says_so_per_source(system):
    got, full = states(system, "dpo_a")
    assert got == {"decision": "not_measured", "evaluations": "not_measured", "controls": "no_access", "proof": "no_access",
                   "incidents": "not_measured", "regulation": "not_measured"}
    assert full["attention"] == [] and full["unavailable"] == []
    risk_owner, _ = states(system, "owner_a")
    assert risk_owner["controls"] == "not_measured" and risk_owner["proof"] == "not_measured"


def test_a_hidden_use_has_no_monitoring(system):
    assert monitoring.get_monitoring(system.db, user(system, "dpo_b"), system.app) is None
    fail(lambda: monitoring.get_monitoring(system.db, {**user(system, "dpo_a"), "roles": ["external_auditor"]}, system.app), 403)


def test_a_failed_run_a_stale_run_and_a_passed_one_read_differently(system):
    commit(system, evaluations.record_run(system.db, user(system, "dpo_a"), system.app, RUN), user(system, "dpo_a"))
    got, full = states(system)
    assert got["evaluations"] == "ok"
    commit(system, evaluations.record_run(system.db, user(system, "dpo_a"), system.app,
                                          {**RUN, "name": "Worse", "scores": {"citation_validity": 70}}), user(system, "dpo_a"))
    got, full = states(system)
    assert got["evaluations"] == "attention" and "evaluations" in full["attention"]
    item = next(s for s in full["sources"] if s["source"] == "evaluations")["items"][0]
    assert "Failed" in item["detail"] and "assistant 2026-09" in item["detail"]


def test_a_linked_incident_and_a_confirmed_change_are_attention_and_name_nothing_the_viewer_may_not_open(system):
    incident = _insert(system.db, "bcm_incidents", title="Model outage", business_unit_id=system.unit["A"])
    system.db.commit()
    made = relationships.create_link(system.db, user(system, "super"), ("bcm", "incident", incident),
                                     ("governance", "application", system.app), "affects")
    system.db.commit()
    assert made
    got, full = states(system, "owner_a")
    assert got["incidents"] == "attention"
    named = next(s for s in full["sources"] if s["source"] == "incidents")["items"]
    assert [i["title"] for i in named] == ["Model outage"]

    update_id = _insert(system.db, "regulatory_updates", framework_name="EU AI Act", title="Change", status="open")
    system.db.commit()
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    commit(system, service.update_profile(system.db, user(system, "dpo_a"), system.app, {"jurisdictions": ["EU"]}, profile["version"]),
           user(system, "dpo_a"))
    commit(system, regulation.refresh(system.db, user(system, "dpo_a")), user(system, "dpo_a"))
    item = regulation.list_queue(system.db, user(system, "dpo_a"))["items"][0]
    commit(system, regulation.review(system.db, user(system, "dpo_a"), item["id"], "confirm", None, item["version"]), user(system, "dpo_a"))
    got, _ = states(system, "dpo_a")
    assert got["regulation"] == "attention" and update_id


def test_a_source_that_cannot_be_read_is_unavailable_not_clean(system, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("table is gone")
    monkeypatch.setattr(evaluations, "list_runs", broken)
    got, full = states(system)
    assert got["evaluations"] == "unavailable" and full["unavailable"] == ["evaluations"]
    assert got["decision"] == "not_measured", "the other sources are still read"
