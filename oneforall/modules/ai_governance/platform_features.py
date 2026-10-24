"""Operator oversight of ThemisIQ's registered first party AI call sites.

The registry is the source of feature identity and declared data categories.
Only operator notes live in the public platform schema. Usage is aggregated
from metadata logs in each tenant schema and never returns customer content.
Callers open the public connection and commit mutations themselves.
"""
import re
from datetime import date, datetime

from config import settings
from core.ai_declarations import declaration
from core.ai_policy import CATEGORIES, FEATURES
from core.rbac import has_capability
from core.timeutils import utcnow
from modules.ai_governance.service import ServiceError


CAPABILITY = "ai_governance.platform.manage"
DEPLOYMENTS = ("in_service", "paused", "retired")
LIMITS = {"owner": 160, "provider_note": 500, "known_limitations": 2000, "incident_path": 1000}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _require(user):
    if not user or not user.get("is_super_admin") or not has_capability(user, CAPABILITY):
        raise ServiceError(403, "Access denied.")


def _require_public(db):
    if settings.is_postgres() and db.execute("SELECT current_schema() AS name").fetchone()["name"] != "public":
        raise RuntimeError("Platform AI feature oversight requires the public schema.")


def _version(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ServiceError(422, "Send the current record version.")
    return value


def _date(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ServiceError(422, "Review due must be a date in YYYY-MM-DD format.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ServiceError(422, "Review due must be a real calendar date.") from None
    return value


def _text(raw, field):
    if not isinstance(raw, str):
        raise ServiceError(422, f"{field.replace('_', ' ').capitalize()} must be text.")
    value = _CONTROL.sub("", raw).strip()
    if len(value) > LIMITS[field]:
        raise ServiceError(422, f"{field.replace('_', ' ').capitalize()} must be {LIMITS[field]} characters or fewer.")
    return value


def _stamp(value):
    if value is None:
        return None
    return value.isoformat(sep=" ") if isinstance(value, datetime) else str(value)


def _usage_rows(db, org_id=None):
    where = " WHERE org_id = %s" if org_id is not None else ""
    params = (org_id,) if org_id is not None else ()
    return db.execute(
        "SELECT feature, status, COUNT(*) AS calls, MAX(created_at) AS last_at "
        "FROM ai_usage_log" + where + " GROUP BY feature, status", params,
    ).fetchall()


def _merge_usage(totals, rows):
    for row in rows:
        key = row["feature"]
        if key not in FEATURES:
            continue
        entry = totals.setdefault(key, {"successful": 0, "refused": 0, "errors": 0, "last_used_at": None})
        count = int(row["calls"])
        status = row["status"]
        if status == "ok":
            entry["successful"] += count
            at = _stamp(row["last_at"])
            if at and (entry["last_used_at"] is None or at > entry["last_used_at"]):
                entry["last_used_at"] = at
        elif status == "refused":
            entry["refused"] += count
        else:
            entry["errors"] += count


def _usage_totals(db):
    """Public history and each tenant log, using one connection for the whole read."""
    totals = {}
    _merge_usage(totals, _usage_rows(db))
    if not settings.is_postgres():
        return totals  # SQLite has one database, with no tenant schemas.
    orgs = db.execute("SELECT id, slug FROM organizations").fetchall()
    for org in orgs:
        slug = org["slug"]
        if not slug or slug == "public":
            continue
        db.set_tenant(slug)
        try:
            # A tenant with no local log must not fall back to public and
            # count the same shared rows for a second time.
            schema = db.execute("SELECT current_schema() AS name").fetchone()["name"]
            local = db.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = 'ai_usage_log'",
                (schema,),
            ).fetchone()
            if schema != "public" and local:
                _merge_usage(totals, _usage_rows(db, org["id"]))
        finally:
            db.set_tenant("public")
    return totals


def _review_state(row, today):
    if row is None:
        return "not_reviewed"
    due = row["review_due"]
    if due and str(due)[:10] < today:
        return "overdue"
    if row["last_reviewed_at"] is None:
        return "not_reviewed"
    return "reviewed"


def list_features(db, user):
    _require(user)
    _require_public(db)
    notes = {row["feature_key"]: row for row in db.execute("SELECT * FROM platform_ai_features").fetchall()}
    usage = _usage_totals(db)
    reviewer_ids = sorted({row["last_reviewed_by"] for row in notes.values() if row["last_reviewed_by"]})
    reviewers = {}
    if reviewer_ids:
        rows = db.execute(
            "SELECT id, full_name FROM users WHERE id IN (" + ",".join(["%s"] * len(reviewer_ids)) + ")",
            reviewer_ids,
        ).fetchall()
        reviewers = {row["id"]: row["full_name"] for row in rows}
    today = utcnow().date().isoformat()
    items = []
    for key, (label, categories) in FEATURES.items():
        row = notes.get(key)
        record = dict(row) if row else {}
        deployment = record.get("deployment") or "in_service"
        items.append({
            "key": key, "label": label, "categories": list(categories),
            "category_labels": [CATEGORIES.get(category, category) for category in categories],
            "declaration": declaration(key),
            "owner": record.get("owner") or "", "provider_note": record.get("provider_note") or "",
            "known_limitations": record.get("known_limitations") or "",
            "incident_path": record.get("incident_path") or "",
            "deployment": deployment,
            "review_due": str(record["review_due"])[:10] if record.get("review_due") else None,
            "last_reviewed_at": _stamp(record.get("last_reviewed_at")),
            "last_reviewed_by": record.get("last_reviewed_by"),
            "last_reviewed_by_name": reviewers.get(record.get("last_reviewed_by")),
            "updated_at": _stamp(record.get("updated_at")),
            "version": int(record["version"]) if row else 0,
            "review_state": _review_state(row, today),
            "usage": usage.get(key, {"successful": 0, "refused": 0, "errors": 0, "last_used_at": None}),
        })
    return {"items": items, "count": len(items), "usage_scope": "All tenant schemas and public history"}


def save_notes(db, user, feature_key, raw, expected_version):
    _require(user)
    _require_public(db)
    if feature_key not in FEATURES:
        raise ServiceError(404, "Feature not found.")
    if not isinstance(raw, dict):
        raise ServiceError(422, "Send a record of feature notes.")
    version = _version(expected_version)
    values = {field: _text(raw.get(field), field) for field in LIMITS}
    deployment = raw.get("deployment")
    if deployment not in DEPLOYMENTS:
        raise ServiceError(422, "Choose a valid deployment state.")
    due = _date(raw.get("review_due"))
    now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    params = (values["owner"], values["provider_note"], values["known_limitations"],
              values["incident_path"], deployment, due)
    if version:
        current = db.execute("SELECT * FROM platform_ai_features WHERE feature_key = %s", (feature_key,)).fetchone()
        if not current or int(current["version"]) != version:
            raise ServiceError(409, "This record changed. Reload it before saving.")
        unchanged = (all((current[field] or "") == values[field] for field in LIMITS)
                     and current["deployment"] == deployment
                     and (str(current["review_due"])[:10] if current["review_due"] else None) == due)
        if unchanged:
            return {"feature_key": feature_key, "version": version, "created": False}
    if version == 0:
        changed = db.execute(
            "INSERT INTO platform_ai_features (feature_key, owner, provider_note, known_limitations, "
            "incident_path, deployment, review_due, version, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s) "
            "ON CONFLICT (feature_key) DO NOTHING", (feature_key, *params, now),
        ).rowcount
        new_version = 1
    else:
        changed = db.execute(
            "UPDATE platform_ai_features SET owner = %s, provider_note = %s, known_limitations = %s, "
            "incident_path = %s, deployment = %s, review_due = %s, last_reviewed_at = NULL, "
            "last_reviewed_by = NULL, version = version + 1, updated_at = %s "
            "WHERE feature_key = %s AND version = %s", (*params, now, feature_key, version),
        ).rowcount
        new_version = version + 1
    if changed != 1:
        raise ServiceError(409, "This record changed. Reload it before saving.")
    return {"feature_key": feature_key, "version": new_version,
            "audit": [("platform_feature_notes_saved", "platform_ai_feature", 0, feature_key)]}


def mark_reviewed(db, user, feature_key, expected_version):
    _require(user)
    _require_public(db)
    if feature_key not in FEATURES:
        raise ServiceError(404, "Feature not found.")
    version = _version(expected_version)
    row = db.execute("SELECT * FROM platform_ai_features WHERE feature_key = %s", (feature_key,)).fetchone()
    if not row:
        raise ServiceError(422, "Save the feature notes before marking a review complete.")
    if int(row["version"]) != version:
        raise ServiceError(409, "This record changed. Reload it before marking the review complete.")
    if any(not row[field] for field in LIMITS) or not row["review_due"]:
        raise ServiceError(422, "Record the owner, provider, limitations, incident path and next review date first.")
    if str(row["review_due"])[:10] <= utcnow().date().isoformat():
        raise ServiceError(422, "Choose a future date for the next review.")
    now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    changed = db.execute(
        "UPDATE platform_ai_features SET last_reviewed_at = %s, last_reviewed_by = %s, "
        "version = version + 1, updated_at = %s WHERE feature_key = %s AND version = %s",
        (now, user["id"], now, feature_key, version),
    ).rowcount
    if changed != 1:
        raise ServiceError(409, "This record changed. Reload it before marking the review complete.")
    return {"feature_key": feature_key, "version": version + 1, "last_reviewed_at": now,
            "audit": [("platform_feature_reviewed", "platform_ai_feature", 0, feature_key)]}
