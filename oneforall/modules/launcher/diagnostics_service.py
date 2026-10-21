"""
P02: sanitized administration diagnostics and readiness centre -- the
read-only aggregation service. See task_plan.md P02 for the full spec.

Every probe here is read-only and side-effect-free (P02's own
"Make active probes side-effect-free" rule) and returns the shared
core/capability_state.py vocabulary (P09) wherever a probe has a real
CapabilityState to give, so a degraded/not-configured/unavailable dependency
never turns into a raw exception or a 500 for the whole page.

Platform-vs-org separation (P02's own discovery-gate item): platform-wide
infrastructure (scheduler, backup, preview worker) is only ever computed
for a platform super admin; an organization admin gets only org-scoped
configuration state (their own licensed modules, whether email is
configured) plus the same AI capability state every user can already see
via GET /api/capability-state/ai.
"""
from core.capability_state import CapabilityState, AVAILABLE, degraded, not_configured


def _safe(probe_fn) -> dict:
    """Run one probe; a probe raising must degrade that one entry, never
    fail the whole diagnostics response (P02: "a slow/failed dependency
    must not block the page")."""
    try:
        result = probe_fn()
        if isinstance(result, CapabilityState):
            return result.to_dict()
        return result
    except Exception:
        return degraded("probe_error", "This check could not run. Try again shortly.").to_dict()


def _database_state() -> CapabilityState:
    from database import get_db
    db = get_db()
    try:
        db.execute("SELECT 1").fetchone()
        return CapabilityState(state=AVAILABLE, reason_code="db_ok")
    finally:
        db.close()


def _email_configured_state(org_id) -> CapabilityState:
    """Read the same provider resolution/config used by core.email.send_email."""
    from core.email import _resolve_provider, _smtp_config, _graph_config, _sendgrid_config
    provider = _resolve_provider()
    if provider in ("google", "microsoft_smtp", "smtp"):
        cfg = _smtp_config()
        ready = all(cfg.get(key) for key in ("host", "user", "password", "from"))
    elif provider == "microsoft_graph":
        cfg = _graph_config()
        ready = all(cfg.get(key) for key in ("tenant_id", "client_id", "client_secret", "from_address"))
    elif provider == "sendgrid":
        cfg = _sendgrid_config()
        ready = bool(cfg.get("api_key") and cfg.get("from"))
    else:
        ready = False
    if ready:
        return CapabilityState(state=AVAILABLE, reason_code="email_configured")
    return not_configured(
        "email_not_configured", "Email delivery has not been configured.",
        remediation_route="/admin/email",
    )


def get_diagnostics(user: dict) -> dict:
    from core.ai_client import get_capability_state as ai_state

    result = {
        "database": _safe(_database_state),
        "ai": _safe(ai_state),
        "licensed_modules": user.get("licensed_modules"),
        "email": _safe(lambda: _email_configured_state(user.get("org_id"))),
    }

    if not user.get("is_super_admin") and result["email"].get("remediation_route"):
        result["email"]["remediation_route"] = None

    if user.get("is_super_admin"):
        from modules.grid.scheduler import get_scheduler_status
        from core.backup_status import get_backup_freshness
        from modules.aria.policy_preview import get_worker_heartbeat_state

        from core.capability_metrics import frequency
        result["platform"] = {
            "scheduler": _safe(get_scheduler_status),
            "backup": _safe(get_backup_freshness),
            "aria_preview_worker": _safe(get_worker_heartbeat_state),
            "capability_state_frequency": _safe(frequency),
        }

    return result
