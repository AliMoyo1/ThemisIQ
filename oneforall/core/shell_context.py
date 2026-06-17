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
        "license_status": _license_status(user),
    }
