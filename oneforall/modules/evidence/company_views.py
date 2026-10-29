"""Within-tenant filing and browsing scopes for the Evidence Vault.

Business units are access scopes, not legal-company identities. Cross-tenant
company views must use explicit group publications instead of this service.
"""

from fastapi import HTTPException

from core.rbac import has_capability
from modules.evidence.scope import evidence_scope_sql
from modules.governance.data_service import bu_scope_ids


def can_file_org_wide(user: dict) -> bool:
    return bool(user.get("org_id") and not user.get("business_unit_id")
                and has_capability(user, "evidence.file.org_wide"))


def active_units(db, user: dict) -> list[dict]:
    """Only names in the caller's active unit subtree may reach the UI."""
    if not user.get("org_id"):
        return []
    ids = bu_scope_ids(user) or []
    if not ids or ids == [-1]:
        return []
    marks = ",".join(["%s"] * len(ids))
    rows = db.execute(
        f"SELECT id, name, parent_id FROM business_units WHERE is_active=1 AND id IN ({marks}) ORDER BY name, id",
        ids,
    ).fetchall()
    return [dict(row) for row in rows]


def selected_unit(db, user: dict, raw: str, *, for_filing: bool = False):
    """Validate an exact unit or organization-wide selection without an ID oracle."""
    if raw == "organization":
        if for_filing and not can_file_org_wide(user):
            raise HTTPException(404, "Filing scope not found")
        return None
    if raw.startswith("unit:") and raw[5:].isdigit():
        unit_id = int(raw[5:])
        if unit_id > 0 and any(row["id"] == unit_id for row in active_units(db, user)):
            return unit_id
    raise HTTPException(404, "Filing scope not found")


def facets(db, user: dict) -> dict:
    """Counts and labels from the same visible library rows as the list."""
    if not user.get("org_id"):
        return {"organization": None, "units": [], "can_file_org_wide": False}
    scope, params = evidence_scope_sql(user)
    counts = db.execute(
        "SELECT e.business_unit_id, COUNT(*) AS n FROM evidence_items e "
        f"WHERE {scope} AND e.status NOT IN ('archived','superseded') "
        "GROUP BY e.business_unit_id", params,
    ).fetchall()
    by_unit = {row["business_unit_id"]: row["n"] for row in counts}
    org = db.execute("SELECT id, name FROM organizations WHERE id=%s AND status='active'",
                     (user["org_id"],)).fetchone()
    if not org:
        return {"organization": None, "units": [], "can_file_org_wide": False}
    units = active_units(db, user)
    return {
        "organization": {"id": org["id"], "name": org["name"],
                         "count": sum(by_unit.values()), "organization_wide": by_unit.get(None, 0)},
        "units": [{"id": row["id"], "name": row["name"],
                   "parent_id": row["parent_id"], "count": by_unit.get(row["id"], 0)} for row in units],
        "can_file_org_wide": can_file_org_wide(user),
    }
