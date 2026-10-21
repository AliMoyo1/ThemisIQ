"""
PLAN-36 P09: consistent capability/dependency state vocabulary
(core/capability_state.py). Applied first to AI (core/ai_client.py's new
get_capability_state()), one of task_plan.md P09's own named first areas
(ARIA authoring/preview/AI).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.capability_state import (
    CapabilityState, available, disabled_by_policy, not_configured, degraded,
    forbidden, unavailable_in_tier, AVAILABLE, NOT_CONFIGURED, FORBIDDEN, DEGRADED,
)


def test_available_has_no_message_or_remediation():
    state = available()
    d = state.to_dict()
    assert d["state"] == AVAILABLE
    assert d["message"] == ""
    assert d["remediation_route"] is None
    assert d["retryable"] is False


def test_forbidden_never_carries_a_message_or_remediation():
    """Red proof (temporarily allowing forbidden() to accept a message
    param): a caller passing a message here would leak "why" to someone not
    entitled to know -- this test exists specifically to keep that
    impossible via the function signature itself, not just by convention."""
    state = forbidden()
    d = state.to_dict()
    assert d["state"] == FORBIDDEN
    assert d["message"] == "You do not have permission to use this feature."
    assert d["remediation_route"] is None


def test_forbidden_signature_has_no_message_parameter():
    """Structural proof that forbidden() cannot be called with a custom
    message at all -- not just that nobody happens to pass one today."""
    import inspect
    sig = inspect.signature(forbidden)
    assert "message" not in sig.parameters
    assert "remediation_route" not in sig.parameters


def test_only_degraded_is_retryable():
    for factory in (available, lambda: disabled_by_policy("x"), lambda: not_configured("x"),
                    forbidden, lambda: unavailable_in_tier("x")):
        assert factory().retryable is False
    assert degraded("x").retryable is True


def test_unknown_state_is_rejected():
    with pytest.raises(ValueError):
        CapabilityState(state="not_a_real_state", reason_code="x")


def test_not_configured_carries_remediation_route_through():
    state = not_configured("missing_key", message="No key set.", remediation_route="/admin/ai")
    d = state.to_dict()
    assert d["state"] == NOT_CONFIGURED
    assert d["message"] == "No key set."
    assert d["remediation_route"] == "/admin/ai"


def test_ai_capability_state_reports_not_configured_when_no_key(monkeypatch):
    import core.ai_client as ai_client
    monkeypatch.setattr(ai_client, "is_configured", lambda: False)
    monkeypatch.setattr(ai_client, "_provider", lambda: "anthropic")

    state = ai_client.get_capability_state()
    assert state.state == NOT_CONFIGURED
    assert state.reason_code == "ai_provider_key_missing"


def test_ai_capability_state_reports_available_when_key_present(monkeypatch):
    """Red proof (temporarily forcing get_capability_state to always return
    not_configured()): this assertion fails with the wrong state."""
    import core.ai_client as ai_client
    monkeypatch.setattr(ai_client, "is_configured", lambda: True)

    state = ai_client.get_capability_state()
    assert state.state == AVAILABLE
