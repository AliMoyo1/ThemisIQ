# Launcher — Command Centre, Admin, Platform Tools

The shell module. Owns the Command Centre overview, cross-module dashboards,
platform-wide admin, the unified vendor directory, the task board, and the
workflow engine.

## Mounts

- `/` — Command Centre overview (`command_centre.html`).
- `/vendors` — Cross-module vendor directory.
- `/tasks`, `/workflows`, `/reports`, `/calendar`, `/analytics` — platform tools.
- `/admin/users`, `/admin/audit-log`, `/admin/frameworks`, `/admin/email`,
  `/admin/api-keys`, `/admin/webhooks` — capability-gated admin.
- `/login`, `/logout`, `/change-password` — auth flows.
- `/api/command-centre/stats` — cross-module aggregates JSON.

## Files

| File | Role |
|---|---|
| `routes.py` | Mounts sub-routers, exposes a few shell routes |
| `routes_auth.py` | login/logout/password-change |
| `routes_dashboard.py` | Command Centre overview + stats API |
| `routes_admin.py` | User management, audit log, email, API keys, webhooks |
| `routes_platform.py` | tasks/workflows/reports/calendar/analytics |
| `routes_risks.py` | Cross-module risk register page |
| `routes_frameworks.py` | Framework admin |
| `routes_vendors.py` | `/vendors` page + canonical directory API |
| `_route_helpers.py` | Shared template loaders, `require_auth`, `_require_cap`, `shell_ctx`, csrf helpers |

## Key templates

- `templates/command_centre.html` (in `oneforall/templates/`) — Command Centre overview. Has its own sidebar.
- `platform_base.html` — Sidebar shell for platform sub-pages (risk register, tasks, workflows…).
- `vendor_directory.html` — SPA for `/vendors`.

## Notes

- The sidebar nav exists in two places (`command_centre.html` and
  `platform_base.html`). Changes must be mirrored in both until refactored.
- `routes_vendors.py` calls `core.vendor_link.ensure_canonical` and
  `get_vendor_directory`; do not duplicate that logic here.
