"""PLAN-36 P09: safe dependency states derived from the same gates as actions."""
from core.capability_state import (
    available, disabled_by_policy, forbidden, not_configured,
    unavailable_in_tier,
)
from core.rbac import has_capability


def _gate(user, capability, module=None):
    if not has_capability(user, capability):
        return forbidden()
    licensed = user.get("licensed_modules")
    if module and not user.get("is_super_admin") and licensed is not None and module not in licensed:
        return unavailable_in_tier("module_not_licensed")
    return None


def aria_authoring_state(user):
    gate = _gate(user, "aria.policy.create", "aria")
    if gate:
        return gate
    from modules.aria.policy_access import policy_authoring_enabled_for
    if not policy_authoring_enabled_for(user.get("org_id")):
        return disabled_by_policy("aria_authoring_disabled")
    return available()


def aria_ai_state(user):
    gate = _gate(user, "aria.policy.generate_ai", "aria")
    if gate:
        return gate
    from modules.aria.policy_access import policy_authoring_enabled_for
    if not policy_authoring_enabled_for(user.get("org_id")):
        return disabled_by_policy("aria_authoring_disabled")
    from core.ai_client import get_capability_state
    return get_capability_state()


def aria_conversion_state(user):
    gate = _gate(user, "aria.policy.create", "aria")
    if gate:
        return gate
    from modules.aria.policy_access import policy_authoring_enabled_for
    if not policy_authoring_enabled_for(user.get("org_id")):
        return disabled_by_policy("aria_authoring_disabled")
    from modules.aria.policy_preview import get_worker_heartbeat_state
    return get_worker_heartbeat_state()


def horizon_scan_state(user):
    gate = _gate(user, "erm.ai.use", "erm")
    if gate:
        return gate
    from core.ai_client import is_configured, _provider
    if not is_configured():
        return not_configured("ai_provider_key_missing")
    if _provider() not in ("anthropic", "openrouter"):
        return not_configured("horizon_web_search_not_configured")
    return available()


def aria_export_state(user):
    gate = _gate(user, "aria.documents.export", "aria")
    return gate or available()


def email_state(user):
    gate = _gate(user, "platform.manage_users")
    if gate:
        return gate
    from modules.launcher.diagnostics_service import _email_configured_state
    return _email_configured_state(user.get("org_id"))


def connector_state(user, name):
    gate = _gate(user, "platform.manage_users")
    if gate:
        return gate
    if name not in ("slack", "teams", "whatsapp"):
        raise ValueError("Unknown connector")
    from modules.launcher.routes_admin import _connectors_get_setting
    from core.capability_state import degraded
    try:
        configured = bool(_connectors_get_setting(name + "_webhook_url"))
    except Exception:
        return degraded("connector_check_failed")
    if configured:
        return available()
    return not_configured("connector_not_configured", remediation_route="/admin/connectors")
