"""Explicit row scopes for cross-module dashboards and generated reports."""

import hashlib
import json

from core.rbac import has_capability, user_modules, user_capabilities
from modules.governance.data_service import bu_scope_ids
from modules.governance.entity_scope import entity_scope_sql


TABLE_KINDS = {
    "controls": ("aria", "control"),
    "grid_audits": ("grid", "audit"),
    "grid_non_conformances": ("grid", "nc"),
    "grid_controls": ("grid", "control"),
    "sentinel_ropa": ("sentinel", "ropa"),
    "sentinel_dpias": ("sentinel", "dpia"),
    "sentinel_breaches": ("sentinel", "breach"),
    "sentinel_dsr": ("sentinel", "dsr"),
    "bcm_plans": ("bcm", "plan"),
    "bcm_incidents": ("bcm", "incident"),
    "bcm_exercises": ("bcm", "exercise"),
    "erm_enterprise_risks": ("erm", "risk"),
    "orm_events": ("orm", "event"),
    "evidence_items": ("evidence", "item"),
    "task_board": ("platform", "task"),
}


def table_scope(table, user, alias=""):
    """Only whitelisted table names are accepted. Unowned aggregates fail closed."""
    if table == "task_board":
        scope, params = entity_scope_sql(("platform", "task"), user, alias)
        if user.get("is_super_admin"):
            return scope, params
        prefix = f"{alias}." if alias else ""
        org = (f"COALESCE((SELECT org_id FROM users WHERE id={prefix}created_by), "
               f"(SELECT org_id FROM users WHERE id={prefix}assigned_to)) = %s")
        return f"({scope} AND {org})", [*params, user.get("org_id")]
    if table in TABLE_KINDS:
        return entity_scope_sql(TABLE_KINDS[table], user, alias)
    if table == "frameworks":
        allowed = has_capability(user, "module.aria.access") and "aria" in user_modules(user)
        return ("(1 = 1)" if allowed else "(1 = 0)"), []
    if table in {"risk_register", "sla_instances", "workflow_instances",
                 "erm_risk_appetite", "erm_regulatory_obligations"}:
        return ("(1 = 1)" if user.get("is_super_admin") else "(1 = 0)"), []
    raise ValueError(f"No cross-module scope for {table}")


def scoped_count(db, user, table, condition="", params=()):
    scope, scope_params = table_scope(table, user)
    where = f"{scope} AND ({condition})" if condition else scope
    return db.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {where}",
        [*scope_params, *params],
    ).fetchone()[0]


def run_scope_key(user):
    """Saved results become unreadable after an access or BU subtree change."""
    payload = {
        "id": user["id"],
        "org": user.get("org_id"),
        "super": bool(user.get("is_super_admin")),
        "units": bu_scope_ids(user),
        "modules": sorted(user_modules(user)),
        "capabilities": sorted(user_capabilities(user)),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return f"user:{user['id']}:{digest}"
