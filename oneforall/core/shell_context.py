"""
Shell context helper — provides the template variables needed by the unified
icon sidebar (included in all module templates via _icon_sidebar.html).

Usage in a route:
    from core.shell_context import shell_ctx

    @router.get("/")
    async def my_page(request: Request):
        return templates.TemplateResponse(request, "index.html", {
            "user": request.state.user,
            **shell_ctx(request, active_module="grid"),
        })
"""
import datetime as _dt
import logging

from config import settings
from core import ai_rollout
from core.rbac import user_modules as _user_modules, has_capability

_log = logging.getLogger("oneforall.shell_ctx")


def _license_status(user) -> dict:
    """Return licence renewal status for the user's org, or {} when not applicable."""
    if not settings.is_postgres():
        return {}
    org_id = user.get("org_id")
    if not org_id:
        return {}
    try:
        from database import get_db
        db = get_db()
        try:
            lic = db.execute(
                "SELECT valid_until FROM licenses WHERE org_id = %s "
                "ORDER BY id DESC LIMIT 1",
                (org_id,),
            ).fetchone()
        finally:
            db.close()
    except Exception as exc:
        _log.warning("Licence lookup failed: %s", exc)
        return {}

    if not lic or not lic["valid_until"]:
        return {}

    raw = lic["valid_until"]
    try:
        if isinstance(raw, _dt.datetime):
            end = raw.date()
        elif isinstance(raw, _dt.date):
            end = raw
        else:
            end = _dt.date.fromisoformat(str(raw)[:10])
    except Exception:
        return {}

    today = _dt.date.today()
    days = (end - today).days
    if days > 30:
        return {}
    return {
        "valid_until": end.isoformat(),
        "days_remaining": days,
        "expired": days < 0,
    }


def _ai_return_id(request) -> str:
    """The AI system a person came from (`aig_return`), only when it is a plain number, so it is safe in a link."""
    params = getattr(request, "query_params", None)
    value = params.get("aig_return", "") if params is not None else ""
    return value if value.isdigit() and len(value) <= 9 else ""


def shell_ctx(request, active_module: str = "platform",
              active_section: str = "", show_sidebar: bool = True) -> dict:
    """Return the dict of context variables the unified shell templates need."""
    user = request.state.user
    return {
        "user": user,
        "user_modules": _user_modules(user),
        "active_module": active_module,
        "active_section": active_section,
        "show_sidebar": show_sidebar,
        "is_admin": has_capability(user, "platform.manage_users"),
        "is_super_admin": bool(user.get("is_super_admin")),
        "can_manage_ai_policy": has_capability(user, "ai_governance.policy.manage"),
        "can_ai_use": has_capability(user, "ai_use.view") and ai_rollout.is_enabled(user.get("org_id")),
        "can_ai_pack": has_capability(user, "ai_pack.receive") and ai_rollout.is_enabled(user.get("org_id")),
        "can_ai_literacy": has_capability(user, "ai_literacy.take") and ai_rollout.is_enabled(user.get("org_id")),
        # Super administrators can open AI Governance while an organization's rollout switch is off.
        "can_ai_admin_nav": bool(user.get("is_super_admin")) and has_capability(user, "ai_use.view"),
        "ai_return_id": _ai_return_id(request) if has_capability(user, "ai_use.view") else "",
        "can_view_audit_log": has_capability(user, "platform.view_audit_log"),
        "can_governance_view": has_capability(user, "governance.entities.view"),
        "can_org_admin": has_capability(user, "platform.manage_org_users")
            and not has_capability(user, "platform.manage_users"),
        "can_governance_settings": has_capability(user, "governance.bu.assign")
            and not has_capability(user, "platform.manage_users")
            and not has_capability(user, "platform.manage_org_users"),
        "license_status": _license_status(user),
        "posthog_api_key": settings.POSTHOG_API_KEY,
        "posthog_host": settings.POSTHOG_HOST,
    }
