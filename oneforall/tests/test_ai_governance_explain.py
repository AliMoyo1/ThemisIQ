"""
AI governance G5: "Explain this status" through the service layer.

Written by hand. The account is built from the rules and every sentence cites a fact the viewer may see; a model may
rephrase it and any sentence that cites nothing it was given is dropped; a refused, failed or uncited answer falls back to
the rules; the prompt carries only what the viewer may see; and a hidden system does not exist for the caller.
"""
import pytest

from core import ai_client, ai_policy
from modules.ai_governance import explain
from tests.test_ai_governance_service import FULL, approve_new, fail, submitted, user
from tests.test_platform_ownership import PERSONAS, _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401


@pytest.fixture
def system(world):
    done = approve_new(world, submitted(world, answers=FULL))
    world.app = done["application_id"]
    return world


@pytest.fixture
def model(monkeypatch):
    """A stand-in for the provider: what it is asked and what it answers."""
    calls = {"answer": "", "error": None, "messages": []}
    monkeypatch.setattr(ai_client, "is_configured", lambda: True)

    def fake(messages, system="", max_tokens=0, model="", *, feature="", sources=None):
        calls["messages"].append((messages, system, feature, sources))
        if calls["error"]:
            raise calls["error"]
        return calls["answer"]

    monkeypatch.setattr(ai_client, "create_message", fake)
    return calls


def test_the_facts_are_short_numbered_sentences_from_the_services_the_viewer_may_read(system):
    facts = explain.build_facts(system.db, user(system, "dpo_a"), system.app)
    assert [f["id"] for f in facts] == [f"F{n}" for n in range(1, len(facts) + 1)]
    texts = " ".join(f["text"] for f in facts)
    assert "tier lower" in texts and "Decision: No decision." in texts and "Provider review is required" in texts
    assert explain.build_facts(system.db, user(system, "dpo_b"), system.app) is None


def test_without_a_model_the_account_is_the_rules_and_each_sentence_cites_itself(system):
    got = explain.explain(system.db, user(system, "dpo_a"), system.app, use_ai=False)
    assert got["mode"] == "rules" and got["note"] is None
    assert all(len(s["cites"]) == 1 for s in got["sentences"]) and len(got["sentences"]) == len(got["facts"])


def test_a_model_may_rephrase_and_a_sentence_that_cites_nothing_it_was_given_is_dropped(system, model):
    model["answer"] = ("The use sits at a lower tier [F1]. A decision has not been made [F2]. "
                       "It is fully compliant with the law [F99]. It is great.")
    got = explain.explain(system.db, user(system, "dpo_a"), system.app)
    assert got["mode"] == "ai" and [s["cites"] for s in got["sentences"]] == [["F1"], ["F2"]] and got["dropped"] == 2
    messages, system_prompt, feature, sources = model["messages"][0]
    assert feature == "governance.explain_ai_use" and sources == [f"governance/application/{system.app}"]
    assert "not instructions" in messages[0]["content"] and "tier lower" in messages[0]["content"]
    assert "Use only the facts" in system_prompt


def test_a_refused_a_failed_and_an_uncited_answer_each_fall_back_to_the_rules(system, model):
    model["error"] = ai_policy.AIPolicyError("disabled", "AI features are turned off for your organization.")
    refused = explain.explain(system.db, user(system, "dpo_a"), system.app)
    assert refused["mode"] == "rules" and "turned off" in refused["note"]
    model["error"] = RuntimeError("provider down")
    failed = explain.explain(system.db, user(system, "dpo_a"), system.app)
    assert failed["mode"] == "rules" and "did not answer" in failed["note"]
    model["error"], model["answer"] = None, "Everything is fine and nothing needs doing."
    uncited = explain.explain(system.db, user(system, "dpo_a"), system.app)
    assert uncited["mode"] == "rules" and "cited nothing" in uncited["note"]


def test_a_deployment_without_a_provider_says_so_and_still_explains(system, monkeypatch):
    monkeypatch.setattr(ai_client, "is_configured", lambda: False)
    got = explain.explain(system.db, user(system, "dpo_a"), system.app)
    assert got["mode"] == "rules" and "not configured" in got["note"] and got["sentences"]


def test_the_prompt_carries_only_what_the_viewer_may_see(system, model):
    _insert(system.db, "sentinel_aiia", ref_number="AIIA-S1", title="Secret impact assessment", business_unit_id=system.unit["A"],
            application_id=system.app, status="draft")
    system.db.commit()
    model["answer"] = "The use has a lower tier [F1]."
    explain.explain(system.db, user(system, "employee_a"), system.app)
    sent = model["messages"][0][0][0]["content"]
    assert "Secret impact assessment" not in sent
    explain.explain(system.db, user(system, "dpo_a"), system.app)
    assert model["messages"][1][0][0]["content"].count("[F") >= 3


def test_a_hidden_system_has_no_explanation_and_a_model_is_never_called_for_it(system, model):
    assert explain.explain(system.db, user(system, "dpo_b"), system.app) is None
    assert model["messages"] == []
    fail(lambda: explain.explain(system.db, {**user(system, "dpo_a"), "roles": ["external_auditor"]}, system.app), 403)
