"""
AI governance G1c: one place decides whether a model call may leave the platform, and records what happened.

What it must guarantee, written out by hand:

* an organization with no approved policy is refused before the provider is contacted;
* an approved policy controls the master switch, provider, feature, data categories and monthly allowance;
* a refusal costs nothing at the provider, is recorded, and tells the person a sentence that names no setting;
* a policy that cannot be read refuses (fail closed), and one organization's policy never touches another's;
* the usage record says who, which feature and how much, and never holds a prompt or an answer.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

import core.ai_client as ai_client
import core.ai_policy as ai_policy
import database

ORG_A, ORG_B = 11, 12
OK_RESULT = {"text": "an answer", "model": "test-model", "input_tokens": 30, "output_tokens": 12}


@pytest.fixture
def world(test_db, monkeypatch):
    """Two approved organizations and a provider that counts contacts."""
    monkeypatch.setattr(ai_policy, "_RECORDING", True)
    monkeypatch.setattr(ai_client, "_provider", lambda: "anthropic")
    monkeypatch.setattr(ai_client, "is_configured", lambda: True)
    contacted = []

    def provider(messages, system, max_tokens, model):
        contacted.append(messages)
        return dict(OK_RESULT)

    monkeypatch.setattr(ai_client, "_dispatch_to_provider", provider)
    test_db.contacted = contacted
    for org_id in (ORG_A, ORG_B):
        ai_policy.save_policy(
            org_id, {"enabled": True, "approval_confirmed": True}, user_id=1,
        )
    yield test_db
    database.set_current_org(None)


def _as(org_id, user_id=None):
    database.set_current_org(org_id, user_id=user_id)


def _save(org_id, policy):
    body = {"enabled": True, "approval_confirmed": True, **policy}
    return ai_policy.save_policy(org_id, body, user_id=1)


def _rows(db, **where):
    sql = "SELECT * FROM ai_usage_log"
    if where:
        sql += " WHERE " + " AND ".join(f"{k} = %s" for k in where)
    return [dict(r) for r in db.execute(sql + " ORDER BY id", tuple(where.values())).fetchall()]


def _call(feature="aria.ask", **kw):
    return ai_client.create_message([{"role": "user", "content": "a question"}], feature=feature, **kw)


# ── No policy or organization fails closed ───────────────────────────────────

def test_an_organization_with_no_policy_is_refused_and_recorded(world):
    world.execute("DELETE FROM settings WHERE key=%s", (f"ai.policy.org{ORG_A}",))
    world.commit()
    _as(ORG_A, user_id=7)
    with pytest.raises(ai_policy.AIPolicyError) as refused:
        _call(sources=["aria/document/3"])
    assert refused.value.reason == "policy_missing"
    assert world.contacted == []
    [row] = _rows(world)
    assert (row["org_id"], row["user_id"], row["feature"], row["provider"], row["status"]) == (
        ORG_A, 7, "aria.ask", "anthropic", "refused")
    assert (row["input_tokens"], row["output_tokens"], row["categories"]) == (0, 0, "business")
    assert json.loads(row["sources"]) == ["aria/document/3"]


def test_a_call_with_no_organization_is_refused_and_recorded(world):
    with pytest.raises(ai_policy.AIPolicyError) as refused:
        _call()
    assert refused.value.reason == "org_unbound"
    assert world.contacted == []
    [row] = _rows(world)
    assert row["org_id"] is None and row["status"] == "refused"


def test_an_unlabelled_call_is_refused_by_an_approved_policy(world):
    _as(ORG_A)
    with pytest.raises(ai_policy.AIPolicyError) as refused:
        ai_client.create_message([{"role": "user", "content": "x"}])
    assert refused.value.reason == "category_not_allowed"
    assert world.contacted == []
    [row] = _rows(world)
    assert (row["feature"], row["categories"]) == ("unlabelled", "unlabelled")


# ── Refusals happen before the provider is contacted ────────────────────────

@pytest.mark.parametrize("policy, feature, reason", [
    ({"enabled": False}, "aria.ask", "disabled"),
    ({"providers": ["ollama"]}, "aria.ask", "provider_not_allowed"),
    ({"blocked_features": ["aria.ask"]}, "aria.ask", "feature_blocked"),
    ({"categories": ["public"]}, "sentinel.ai_chat", "category_not_allowed"),
    ({"categories": ["public", "business"]}, "sentinel.ai_chat", "category_not_allowed"),
    ({"categories": ["business"]}, "evidence.api_evidence_suggest_links", "category_not_allowed"),
    ({"categories": ["business"]}, "", "category_not_allowed"),
    ({"categories": ["business"]}, "not.a_feature", "category_not_allowed"),
])
def test_a_policy_refuses_before_the_provider_is_contacted(world, policy, feature, reason):
    _save(ORG_A, policy)
    _as(ORG_A, user_id=4)
    with pytest.raises(ai_policy.AIPolicyError) as refused:
        _call(feature=feature)
    assert refused.value.reason == reason
    assert world.contacted == [], "nothing left the platform"
    [row] = _rows(world)
    assert (row["status"], row["reason"], row["org_id"], row["user_id"]) == ("refused", reason, ORG_A, 4)
    assert (row["input_tokens"], row["output_tokens"]) == (0, 0)


def test_a_refusal_is_a_runtime_error_with_a_sentence_that_names_no_setting(world):
    ai_policy.save_policy(ORG_A, {"enabled": False})
    _as(ORG_A)
    with pytest.raises(RuntimeError) as refused:  # the callers already handle RuntimeError from the client
        _call()
    message = str(refused.value)
    assert message.endswith(".") and "ai.policy" not in message and str(ORG_A) not in message


@pytest.mark.parametrize("policy, feature", [
    ({"categories": ["public", "business"]}, "aria.ask"),
    ({"categories": ["business"]}, "launcher.api_trainer_ask"),
    ({"categories": ["business", "personal"]}, "sentinel.ai_chat"),
    ({"categories": ["business", "evidence"]}, "evidence.api_evidence_suggest_links"),
    ({"providers": ["anthropic", "ollama"]}, "aria.ask"),
    ({"blocked_features": ["bcm.chat"]}, "aria.ask"),
    ({"monthly_token_budget": 10000}, "aria.ask"),
])
def test_a_call_inside_the_policy_goes_through(world, policy, feature):
    _save(ORG_A, policy)
    _as(ORG_A)
    assert _call(feature=feature) == "an answer"
    assert len(world.contacted) == 1


def test_a_feature_needs_every_category_it_sends(world):
    _save(ORG_A, {"categories": ["business"]})  # personal data is not allowed
    _as(ORG_A)
    assert _call(feature="aria.ask") == "an answer"
    with pytest.raises(ai_policy.AIPolicyError):
        _call(feature="sentinel.ai_assess_breach")


# ── Allowance ───────────────────────────────────────────────────────────────

def _spend(db, org_id, tokens, status="ok"):
    db.execute("INSERT INTO ai_usage_log (org_id, feature, status, input_tokens, output_tokens) VALUES (%s, 'aria.ask', %s, %s, 0)",
               (org_id, status, tokens))
    db.commit()


def test_the_monthly_allowance_stops_calls_once_it_is_used_up(world):
    reservation = ai_client._reservation_size([{"role": "user", "content": "a question"}], "", 2000)
    _save(ORG_A, {"monthly_token_budget": 99 + reservation})
    _as(ORG_A)
    _spend(world, ORG_A, 99)
    assert _call() == "an answer"           # The first conservative reservation fits exactly.
    with pytest.raises(ai_policy.AIPolicyError) as refused:  # The next one does not fit.
        _call()
    assert refused.value.reason == "budget_exhausted"
    assert len(world.contacted) == 1


def test_failed_calls_count_but_refusals_other_organizations_and_old_months_do_not(world):
    reservation = ai_client._reservation_size([{"role": "user", "content": "a question"}], "", 2000)
    _save(ORG_A, {"monthly_token_budget": 500 + reservation})
    _as(ORG_A)
    _spend(world, ORG_A, 500, status="refused")
    _spend(world, ORG_A, 500, status="error")
    _spend(world, ORG_B, 500)
    world.execute("INSERT INTO ai_usage_log (org_id, feature, status, input_tokens, created_at) "
                  "VALUES (%s, 'aria.ask', 'ok', 500, '2000-01-15 10:00:00')", (ORG_A,))
    world.commit()
    assert ai_policy.tokens_used_this_month(ORG_A) == 500
    assert _call() == "an answer"


def test_concurrent_calls_cannot_claim_the_same_organization_allowance(world):
    reservation = ai_client._reservation_size([{"role": "user", "content": "a question"}], "", 2000)
    _save(ORG_A, {"monthly_token_budget": reservation})
    ready = Barrier(2)

    def attempt():
        _as(ORG_A, user_id=7)
        try:
            ready.wait(timeout=10)
            try:
                return ai_policy.authorize("aria.ask", provider="anthropic",
                                           reserve_tokens=reservation)
            except ai_policy.AIPolicyError as refused:
                return refused.reason
        finally:
            database.set_current_org(None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        outcomes = [future.result(timeout=15) for future in futures]

    assert sum(isinstance(result, ai_policy.Ticket) for result in outcomes) == 1
    assert set(result for result in outcomes if isinstance(result, str)) <= {
        "budget_exhausted", "policy_unreadable"}
    assert len(_rows(world, status="reserved")) == 1
    assert world.contacted == []


# ── Fail closed, and isolation ──────────────────────────────────────────────

def test_a_policy_that_cannot_be_read_refuses_the_call(world):
    world.execute("UPDATE settings SET value=%s WHERE key=%s", ("{not json", f"ai.policy.org{ORG_A}"))
    world.commit()
    _as(ORG_A)
    with pytest.raises(ai_policy.AIPolicyError) as refused:
        _call()
    assert refused.value.reason == "policy_unreadable"
    assert world.contacted == []


def test_one_organizations_policy_never_applies_to_another(world):
    ai_policy.save_policy(ORG_A, {"enabled": False})
    _as(ORG_B)
    assert _call() == "an answer"
    _as(ORG_A)
    with pytest.raises(ai_policy.AIPolicyError):
        _call()
    assert [r["org_id"] for r in _rows(world)] == [ORG_B, ORG_A]
    assert ai_policy.get_policy(ORG_B)["enabled"] is True


@pytest.mark.parametrize("invalid", [
    {"providers": ["ollama", "not-a-provider"]},
    {"categories": ["public", "everything"]},
    {"blocked_features": ["aria.ask", "nope.nope"]},
    {"monthly_token_budget": "-5"},
])
def test_an_invalid_policy_is_rejected_without_changing_the_approved_policy(world, invalid):
    before = ai_policy.get_policy(ORG_A)
    with pytest.raises(ValueError):
        _save(ORG_A, invalid)
    assert ai_policy.get_policy(ORG_A) == before


def test_a_policy_with_no_categories_listed_allows_none_and_a_missing_key_allows_all(world):
    _save(ORG_A, {"categories": []})
    _as(ORG_A)
    with pytest.raises(ai_policy.AIPolicyError):
        _call(feature="launcher.api_trainer_ask")
    previous = world.execute("SELECT value FROM settings WHERE key=%s", (f"ai.policy.org{ORG_A}",)).fetchone()
    approved = json.loads(previous["value"])
    approved.pop("categories")
    world.execute("UPDATE settings SET value = %s WHERE key = %s", (json.dumps(approved), f"ai.policy.org{ORG_A}"))
    world.commit()
    assert _call(feature="sentinel.ai_chat") == "an answer"


# ── Outcomes and what is stored ─────────────────────────────────────────────

def test_a_provider_failure_is_recorded_and_still_raised(world, monkeypatch):
    def broken(messages, system, max_tokens, model):
        raise RuntimeError("the provider is down")

    monkeypatch.setattr(ai_client, "_dispatch_to_provider", broken)
    _as(ORG_A)
    with pytest.raises(RuntimeError, match="the provider is down"):
        _call()
    [row] = _rows(world)
    reservation = ai_client._reservation_size([{"role": "user", "content": "a question"}], "", 2000)
    assert (row["status"], row["reason"], row["input_tokens"], row["output_tokens"]) == (
        "error", "RuntimeError", reservation, 0)


def test_the_usage_record_never_holds_a_prompt_or_an_answer(world, monkeypatch):
    monkeypatch.setattr(ai_client, "_dispatch_to_provider",
                        lambda *a: {**OK_RESULT, "text": "SECRET-ANSWER-TEXT"})
    _as(ORG_A)
    ai_client.create_message([{"role": "user", "content": "SECRET-PROMPT-TEXT"}], system="SECRET-SYSTEM", feature="aria.ask")
    everything = json.dumps(_rows(world))
    for secret in ("SECRET-PROMPT-TEXT", "SECRET-ANSWER-TEXT", "SECRET-SYSTEM"):
        assert secret not in everything


def test_a_failure_to_reserve_refuses_before_the_provider_is_contacted(world):
    world.execute("DROP TABLE ai_usage_log")
    world.commit()
    _as(ORG_A)
    with pytest.raises(ai_policy.AIPolicyError) as refused:
        _call()
    assert refused.value.reason == "policy_unreadable"
    assert world.contacted == []


def test_create_message_full_and_web_search_are_under_the_same_policy(world, monkeypatch):
    monkeypatch.setattr(ai_client, "_web_search_to_provider", lambda *a: {**OK_RESULT, "citations": [], "searches_used": 1})
    _as(ORG_A)
    assert ai_client.create_message_full([{"role": "user", "content": "x"}], feature="aria.generate_policy")["text"] == "an answer"
    assert ai_client.create_message_web_search([{"role": "user", "content": "x"}],
                                               feature="erm.scan_emerging_risks_grounded")["searches_used"] == 1
    ai_policy.save_policy(ORG_A, {"enabled": False})
    for call in (lambda: ai_client.create_message_full([{"role": "user", "content": "x"}], feature="aria.generate_policy"),
                 lambda: ai_client.create_message_web_search([{"role": "user", "content": "x"}],
                                                             feature="erm.scan_emerging_risks_grounded")):
        with pytest.raises(ai_policy.AIPolicyError):
            call()
    assert [r["status"] for r in _rows(world)] == ["ok", "ok", "refused", "refused"]


# ── What an AI button shows ─────────────────────────────────────────────────

def test_the_capability_state_says_so_when_the_organization_switched_ai_off(world):
    _as(ORG_A)
    assert ai_client.get_capability_state().state == "available"
    ai_policy.save_policy(ORG_A, {"enabled": False})
    state = ai_client.get_capability_state()
    assert (state.state, state.reason_code) == ("disabled_by_policy", "ai_policy_disabled")
    _save(ORG_A, {"providers": ["ollama"]})
    assert ai_client.get_capability_state().reason_code == "ai_policy_provider_not_allowed"
    _save(ORG_A, {"blocked_features": ["aria.ask"]})
    assert ai_client.get_capability_state().state == "available", "one blocked feature does not switch AI off as a whole"
    _as(ORG_B)
    assert ai_client.get_capability_state().state == "available"


# ── The summary an administrator reads ──────────────────────────────────────

def test_the_usage_summary_counts_this_months_calls_tokens_and_refusals(world):
    _as(ORG_A)
    _call()
    _call(feature="bcm.chat")
    _save(ORG_A, {"blocked_features": ["bcm.chat"]})
    with pytest.raises(ai_policy.AIPolicyError):
        _call(feature="bcm.chat")
    summary = ai_policy.usage_summary(ORG_A)
    assert (summary["calls"], summary["refused"], summary["tokens"]) == (2, 1, 84)
    by = {f["feature"]: f for f in summary["by_feature"]}
    assert by["aria.ask"]["label"] == "Ask ARIA" and by["aria.ask"]["ok"] == 1
    assert by["bcm.chat"]["refused"] == 1
    assert summary["recent_refusals"][0]["reason"] == "feature_blocked"
    assert ai_policy.usage_summary(ORG_B)["calls"] == 0
