"""
P09: consistent capability/dependency state vocabulary.

Goal (task_plan.md P09): replace ambiguous missing buttons and generic
failures with a truthful, platform-wide state vocabulary, so a caller can
tell "you're not allowed" from "nobody has set this up yet" from "it's
down right now" -- and so every module says so the same way instead of
each inventing its own ad-hoc shape.

This is infrastructure only: the six canonical states and the object shape
that carries them. Callers apply it; nothing in this file inspects request
context. Wiring it into ARIA authoring/preview/AI, ERM horizon scan, email,
connectors, exports, and external conversion (task_plan.md P09's own list
of where to apply it first) is separate, incremental work -- see
progress.md for exactly what's wired so far and what remains named-pending.
"""
from dataclasses import dataclass, field
from typing import Optional

# The six canonical states (task_plan.md P09), in the order a UI should
# prefer when more than one could technically apply (e.g. a feature that is
# both not-configured AND forbidden for this user should say FORBIDDEN --
# telling an unauthorized caller "also, nobody configured this yet" leaks
# platform configuration state to someone who isn't entitled to know it).
AVAILABLE = "available"
DISABLED_BY_POLICY = "disabled_by_policy"
NOT_CONFIGURED = "not_configured"
DEGRADED = "degraded"
FORBIDDEN = "forbidden"
UNAVAILABLE_IN_TIER = "unavailable_in_tier"

ALL_STATES = (
    AVAILABLE, DISABLED_BY_POLICY, NOT_CONFIGURED, DEGRADED, FORBIDDEN, UNAVAILABLE_IN_TIER,
)

# One safe, generic, translatable message per state. Never a raw exception,
# a config key name, or anything else that could leak implementation detail
# -- matches the same "safe generic fallback" discipline api_client.js
# already applies to a 500 (T06, findings.md F08).
_DEFAULT_MESSAGES = {
    AVAILABLE: "",
    DISABLED_BY_POLICY: "This feature is turned off for your organization.",
    NOT_CONFIGURED: "This feature has not been set up yet.",
    DEGRADED: "This feature is temporarily unavailable. Please try again shortly.",
    FORBIDDEN: "You do not have permission to use this feature.",
    UNAVAILABLE_IN_TIER: "This feature is not included in your current plan.",
}

# Only DEGRADED is safe to retry automatically -- the other non-available
# states won't resolve themselves by trying again.
_RETRYABLE = {DEGRADED}


@dataclass(frozen=True)
class CapabilityState:
    """What a route/service returns instead of silently omitting a button
    or throwing a generic error. `reason_code` is for logs/analytics
    (task_plan.md P09's "add analytics for state frequency" step) and must
    never itself be sensitive; `message` is what the user sees;
    `remediation_route` is an optional link (e.g. "/admin/email" for
    NOT_CONFIGURED email) -- omit it rather than pointing an unauthorized
    caller at an admin page they can't use, per P09's own
    "do not reveal ... through state reasons" rule.
    """
    state: str
    reason_code: str
    message: str = ""
    remediation_route: Optional[str] = None
    retryable: bool = False

    def __post_init__(self):
        if self.state not in ALL_STATES:
            raise ValueError(f"Unknown capability state: {self.state!r}")

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "reason_code": self.reason_code,
            "message": self.message or _DEFAULT_MESSAGES[self.state],
            "remediation_route": self.remediation_route,
            "retryable": self.retryable,
        }


def available() -> CapabilityState:
    return CapabilityState(state=AVAILABLE, reason_code="ok")


def disabled_by_policy(reason_code: str, message: str = "") -> CapabilityState:
    return CapabilityState(state=DISABLED_BY_POLICY, reason_code=reason_code, message=message)


def not_configured(reason_code: str, message: str = "", remediation_route: Optional[str] = None) -> CapabilityState:
    return CapabilityState(
        state=NOT_CONFIGURED, reason_code=reason_code, message=message, remediation_route=remediation_route,
    )


def degraded(reason_code: str, message: str = "") -> CapabilityState:
    return CapabilityState(state=DEGRADED, reason_code=reason_code, message=message, retryable=True)


def forbidden(reason_code: str = "forbidden") -> CapabilityState:
    """No message/remediation params on purpose -- a forbidden response
    must never hint at WHY (e.g. "not configured for your org") to a caller
    who isn't entitled to know it exists at all (task_plan.md P09's own
    "forbidden and not-configured are never conflated" acceptance line, and
    the more general "do not reveal cross-tenant/sensitive state" rule)."""
    return CapabilityState(state=FORBIDDEN, reason_code=reason_code)


def unavailable_in_tier(reason_code: str, message: str = "") -> CapabilityState:
    return CapabilityState(state=UNAVAILABLE_IN_TIER, reason_code=reason_code, message=message)
