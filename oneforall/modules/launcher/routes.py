"""
One For All — Launcher routes aggregator.

Combines all launcher sub-routers into a single `router` object
that main.py imports as `launcher_router`.
"""
from fastapi import APIRouter

from modules.launcher.routes_auth import router as auth_router
from modules.launcher.routes_dashboard import router as dashboard_router
from modules.launcher.routes_admin import router as admin_router
from modules.launcher.routes_frameworks import router as frameworks_router
from modules.launcher.routes_risks import router as risks_router
from modules.launcher.routes_workflows import router as workflows_router
from modules.launcher.routes_reports import router as reports_router
from modules.launcher.routes_platform import router as platform_router
from modules.launcher.routes_vendors import router as vendors_router

router = APIRouter()

# Auth & session management (login, logout, change-password, /api/auth/me)
router.include_router(auth_router)

# Launcher home & role-specific dashboard
router.include_router(dashboard_router)

# Admin: user management, audit logs, API keys, webhooks
router.include_router(admin_router)

# Unified framework management & cross-module links
router.include_router(frameworks_router)

# Cross-module risk register
router.include_router(risks_router)

# Workflow engine, SLA engine, communication templates
router.include_router(workflows_router)

# Reporting engine
router.include_router(reports_router)

# Calendar, analytics, bulk ops, task board, notifications,
# search, trainer, reminders
router.include_router(platform_router)

# Cross-module vendor directory
router.include_router(vendors_router)
