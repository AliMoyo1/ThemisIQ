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
from core.rbac import user_modules as _user_modules, has_capability


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
    }
