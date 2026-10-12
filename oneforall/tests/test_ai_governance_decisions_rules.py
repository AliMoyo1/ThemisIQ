"""
AI governance G4: the pure rules of a decision. What state a use is in is derived from the latest approval and the use
as it is now, never stored; a digest of what a decider was shown changes whenever anything in it does; and the
description of what changed since an approval names the change and nothing else.
"""
import pytest

from modules.ai_governance import decisions

TODAY = "2026-10-11"
CURRENT = {"fingerprint": "fp1", "tier": "lower"}


def standing(**over):
    return {"status": "approved", "expires_at": None, "revoked_at": None, "profile_fingerprint": "fp1", "tier": "lower", **over}


# ── State ───────────────────────────────────────────────────────────────────

def test_a_use_with_no_decision_has_none_and_a_waiting_request_is_a_separate_fact():
    assert decisions.derive_state(None, CURRENT, TODAY) == {"state": "none", "reasons": [], "waiting": False}
    assert decisions.derive_state(None, CURRENT, TODAY, waiting=True)["waiting"] is True


@pytest.mark.parametrize("status", ["approved", "approved_with_conditions"])
def test_an_approval_that_still_describes_the_use_reads_as_approved(status):
    got = decisions.derive_state(standing(status=status, expires_at="2027-01-01"), CURRENT, TODAY)
    assert got["state"] == status and got["reasons"] == []


def test_a_rejection_stays_a_rejection_and_a_revocation_overrides_an_otherwise_good_approval():
    assert decisions.derive_state(standing(status="rejected"), CURRENT, TODAY)["state"] == "rejected"
    assert decisions.derive_state(standing(revoked_at="2026-10-01 10:00:00"), CURRENT, TODAY)["state"] == "revoked"


def test_an_approval_past_its_date_is_expired_on_the_day_after_and_not_before():
    assert decisions.derive_state(standing(expires_at="2026-10-11"), CURRENT, TODAY)["state"] == "approved"
    got = decisions.derive_state(standing(expires_at="2026-10-10"), CURRENT, TODAY)
    assert got["state"] == "expired" and "2026-10-10" in got["reasons"][0]


def test_a_change_to_a_covered_fact_the_tier_or_expired_proof_each_name_themselves():
    fact = decisions.derive_state(standing(profile_fingerprint="old"), CURRENT, TODAY)
    assert fact["state"] == "needs_re_review" and fact["reasons"] == ["A fact the decision covered has changed."]
    tier = decisions.derive_state(standing(tier="moderate"), CURRENT, TODAY)
    assert tier["state"] == "needs_re_review" and "moderate to lower" in tier["reasons"][0]
    proof = decisions.derive_state(standing(), CURRENT, TODAY, proof_expired=True)
    assert proof["state"] == "needs_re_review" and "Proof" in proof["reasons"][0]
    both = decisions.derive_state(standing(profile_fingerprint="old", tier="moderate"), CURRENT, TODAY, proof_expired=True)
    assert len(both["reasons"]) == 3


def test_an_expired_approval_is_expired_even_if_the_use_also_changed():
    got = decisions.derive_state(standing(expires_at="2026-01-01", profile_fingerprint="old"), CURRENT, TODAY)
    assert got["state"] == "expired" and len(got["reasons"]) == 1


# ── The digest ──────────────────────────────────────────────────────────────

MANIFEST = {"profile": {"version": 2, "fingerprint": "fp1", "tier": "lower", "facts": {"purpose": "Summaries"}},
            "checklist": {"steps": [{"key": "vendor", "title": "Provider review", "effective": "required", "state": "in_progress"}],
                          "unresolved": ["vendor"]},
            "assessments": [{"id": 1, "ref": "AIIA-1", "status": "draft", "version": 1}],
            "proof": [{"id": 5, "expires": "2027-01-01"}]}


def test_the_digest_is_stable_for_the_same_facts_whatever_the_key_order_and_moves_with_any_fact():
    shuffled = {k: MANIFEST[k] for k in reversed(list(MANIFEST))}
    assert decisions.brief_hash(MANIFEST) == decisions.brief_hash(shuffled)
    assert len(decisions.brief_hash(MANIFEST)) == 32
    for change in (lambda m: m["profile"]["facts"].update(purpose="Other"),
                   lambda m: m["checklist"]["steps"][0].update(state="complete"),
                   lambda m: m["assessments"][0].update(status="completed"),
                   lambda m: m["proof"].clear()):
        import copy
        changed = copy.deepcopy(MANIFEST)
        change(changed)
        assert decisions.brief_hash(changed) != decisions.brief_hash(MANIFEST)


def test_proof_in_a_manifest_expires_on_the_day_after_its_date():
    assert decisions.proof_expired_in(MANIFEST, "2027-01-01") is False
    assert decisions.proof_expired_in(MANIFEST, "2027-01-02") is True
    assert decisions.proof_expired_in(None, TODAY) is False
    assert decisions.proof_expired_in({"proof": [{"id": 1, "expires": None}]}, TODAY) is False


# ── What changed ────────────────────────────────────────────────────────────

def test_changes_since_names_each_difference_and_nothing_more():
    import copy
    new = copy.deepcopy(MANIFEST)
    assert decisions.changes_since(MANIFEST, new) == []
    new["profile"]["facts"]["purpose"] = "Something else"
    new["profile"]["tier"] = "moderate"
    new["checklist"]["steps"][0]["state"] = "complete"
    new["assessments"][0]["status"] = "completed"
    new["assessments"].append({"id": 2, "ref": "AIIA-2", "status": "draft", "version": 1})
    new["proof"].append({"id": 6, "expires": None})
    lines = decisions.changes_since(MANIFEST, new)
    assert "The purpose changed." in lines
    assert "The tier changed from lower to moderate." in lines
    assert "Provider review: in progress then, complete now." in lines
    assert "AIIA-1 changed (draft then, completed now)." in lines
    assert "A new assessment, AIIA-2, was added." in lines
    assert "The proof held for the AI controls changed." in lines


def test_a_manifest_with_no_assessments_access_is_compared_without_failing():
    new = {**MANIFEST, "assessments": {"state": "no_access"}}
    old = {**MANIFEST, "assessments": {"state": "no_access"}}
    assert decisions.changes_since(old, new) == []
    assert decisions.changes_since(MANIFEST, new) == []


def test_what_was_recorded_after_the_signing_reopens_an_otherwise_good_approval_and_names_itself():
    fact = "An evaluation failed or did not finish after the decision was signed."
    got = decisions.derive_state(standing(), CURRENT, TODAY, signals=[fact])
    assert got["state"] == "needs_re_review" and got["reasons"] == [fact]
    assert decisions.derive_state(standing(), CURRENT, TODAY, signals=())["state"] == "approved"
    assert decisions.derive_state(standing(status="rejected"), CURRENT, TODAY, signals=[fact])["state"] == "rejected"
    assert decisions.derive_state(standing(expires_at="2026-01-01"), CURRENT, TODAY, signals=[fact])["state"] == "expired"
