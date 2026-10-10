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
    "risk_register": ("platform", "risk"),
    "sla_instances": ("platform", "sla"),
    "workflow_instances": ("platform", "workflow"),
}

# Tables whose rows also belong to one organization, for callers who are not super administrators:
# SQL for the organization of a row ({p} is the table alias prefix, "" or "t.").
_ORG_OF = {
    "task_board": ("COALESCE((SELECT org_id FROM users WHERE id={p}created_by), "
                   "(SELECT org_id FROM users WHERE id={p}assigned_to))"),
    "sla_instances": "{p}org_id",
    "workflow_instances": "COALESCE({p}org_id, (SELECT org_id FROM users WHERE id={p}started_by))",
}


def table_scope(table, user, alias=""):
    """Only whitelisted table names are accepted. Tables nobody owns fail closed."""
    if table in TABLE_KINDS:
        scope, params = entity_scope_sql(TABLE_KINDS[table], user, alias)
        if table in _ORG_OF and not user.get("is_super_admin"):
            org = _ORG_OF[table].format(p=f"{alias}." if alias else "")
            return f"({scope} AND {org} = %s)", [*params, user.get("org_id")]
        return scope, params
    if table == "frameworks":
        allowed = has_capability(user, "module.aria.access") and "aria" in user_modules(user)
        return ("(1 = 1)" if allowed else "(1 = 0)"), []
    if table in {"erm_risk_appetite", "erm_regulatory_obligations"}:
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
