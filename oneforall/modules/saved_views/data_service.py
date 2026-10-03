"""
PLAN-36 P06: saved views and permission-safe bulk actions -- shared
infrastructure, onboarded module by module (Evidence Vault first).

Design (task_plan.md P06's own "Selected model"):
  - A saved view stores owner, optional org-shared flag, module/view key,
    a VALIDATED filter JSON, sort, columns, and a default flag.
  - It never stores SQL, a URL, HTML, or a capability decision.
  - Bulk actions re-authorize every record server-side and return
    per-record outcomes; a visible selection count is never authorization.

Key simplification that makes "malicious filter JSON cannot alter
queries" trivially true rather than something a validator has to get
exactly right: filter_json only ever stores query-PARAMETER names/values
already accepted by the owning module's own existing list route (e.g.
evidence's `category`/`status`/`q`/`module`/`view`, from
modules/evidence/routes.py's `GET /api/items`). There is no SQL-generation
step anywhere in this module. Applying a saved view is purely a client-side
replay of its stored params onto that same endpoint, which already builds
its WHERE clause the safe, parameterized way it always has. A module
registers its own allowed param/sort/column names once (register_view_schema);
this module only ever validates against that allowlist, never interprets
a filter value as anything other than an opaque string to store and hand
back unchanged.
"""
from __future__ import annotations

import json

from core.timeutils import utcnow


class SavedViewError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


_SCHEMAS: dict[tuple[str, str], dict] = {}


def register_view_schema(module: str, view_key: str, *, allowed_params: set[str],
                          sortable_fields: set[str] = frozenset(), available_columns: set[str] = frozenset()) -> None:
    """Call once, at import time, from the module that owns this list view
    (matching modules/readiness/rules.py's @register_rule self-registration
    pattern). allowed_params are query-parameter *names* the owning route
    already accepts -- not SQL column names, and never trusted as one."""
    _SCHEMAS[(module, view_key)] = {
        "allowed_params": set(allowed_params),
        "sortable_fields": set(sortable_fields),
        "available_columns": set(available_columns),
    }


def _schema_or_raise(module: str, view_key: str) -> dict:
    schema = _SCHEMAS.get((module, view_key))
    if schema is None:
        raise SavedViewError("UNKNOWN_VIEW", f"No saved-view schema is registered for {module}/{view_key}.", 422)
    return schema


def _validate_filter_params(schema: dict, filter_params: dict) -> dict:
    if not isinstance(filter_params, dict):
        raise SavedViewError("INVALID_INPUT", "filter_params must be an object.", 422)
    unknown = set(filter_params) - schema["allowed_params"]
    if unknown:
        raise SavedViewError("INVALID_INPUT", f"Unknown filter field(s): {', '.join(sorted(unknown))}.", 422)
    clean = {}
    for k, v in filter_params.items():
        if not isinstance(v, (str, int, float, bool)) or isinstance(v, bool):
            if not isinstance(v, str):
                raise SavedViewError("INVALID_INPUT", f"Filter value for '{k}' must be a plain string.", 422)
        clean[k] = str(v)
    return clean


def _row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    d["filter_params"] = json.loads(d.pop("filter_json") or "{}")
    d["columns"] = json.loads(d.pop("columns_json")) if d.get("columns_json") else None
    return d


def create_saved_view(db, actor: dict, *, module: str, view_key: str, name: str,
                       filter_params: dict | None = None, sort_field: str | None = None,
                       sort_dir: str = "asc", columns: list[str] | None = None,
                       shared: bool = False, is_default: bool = False) -> dict:
    schema = _schema_or_raise(module, view_key)
    if not (name or "").strip():
        raise SavedViewError("INVALID_INPUT", "A view name is required.", 422)
    clean_filters = _validate_filter_params(schema, filter_params or {})
    if sort_field is not None and sort_field not in schema["sortable_fields"]:
        raise SavedViewError("INVALID_INPUT", f"'{sort_field}' is not a sortable field for this view.", 422)
    if sort_dir not in ("asc", "desc"):
        raise SavedViewError("INVALID_INPUT", "sort_dir must be 'asc' or 'desc'.", 422)
    if columns is not None:
        unknown_cols = set(columns) - schema["available_columns"]
        if unknown_cols:
            raise SavedViewError("INVALID_INPUT", f"Unknown column(s): {', '.join(sorted(unknown_cols))}.", 422)

    now = utcnow().isoformat()
    if is_default:
        db.execute(
            "UPDATE saved_views SET is_default=0 WHERE owner_user_id=%s AND module=%s AND view_key=%s",
            (actor["id"], module, view_key),
        )
    db.execute(
        "INSERT INTO saved_views (owner_user_id, org_id, module, view_key, name, shared, filter_json, "
        "sort_field, sort_dir, columns_json, is_default, created_at, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (actor["id"], actor["org_id"], module, view_key, name.strip(), int(bool(shared)),
         json.dumps(clean_filters), sort_field, sort_dir,
         json.dumps(columns) if columns is not None else None, int(bool(is_default)), now, now),
    )
    db.commit()
    view_id = db.execute(
        "SELECT id FROM saved_views WHERE owner_user_id=%s AND module=%s AND view_key=%s ORDER BY id DESC LIMIT 1",
        (actor["id"], module, view_key),
    ).fetchone()["id"]
    return get_saved_view(db, actor, view_id)


def list_saved_views(db, actor: dict, module: str, view_key: str) -> list[dict]:
    """Own views plus org-shared views from anyone else -- shared is
    read-only visibility, never implicit edit/delete rights (enforced in
    update/delete_saved_view by owner_user_id, not by this query)."""
    rows = db.execute(
        "SELECT * FROM saved_views WHERE module=%s AND view_key=%s AND org_id=%s "
        "AND (owner_user_id=%s OR shared=1) ORDER BY is_default DESC, name ASC",
        (module, view_key, actor["org_id"], actor["id"]),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_saved_view(db, actor: dict, view_id: int) -> dict | None:
    row = db.execute(
        "SELECT * FROM saved_views WHERE id=%s AND org_id=%s AND (owner_user_id=%s OR shared=1)",
        (view_id, actor["org_id"], actor["id"]),
    ).fetchone()
    return _row_to_dict(row)


def _owned_view_or_raise(db, actor: dict, view_id: int) -> dict:
    row = db.execute(
        "SELECT * FROM saved_views WHERE id=%s AND org_id=%s AND owner_user_id=%s",
        (view_id, actor["org_id"], actor["id"]),
    ).fetchone()
    if row is None:
        raise SavedViewError("NOT_FOUND", "Saved view not found.", 404)
    return _row_to_dict(row)


def update_saved_view(db, actor: dict, view_id: int, **fields) -> dict:
    """Owner-only -- a shared view is read-only to everyone else (task_plan.md's
    own 'restrict sharing/editing/deletion by owner')."""
    view = _owned_view_or_raise(db, actor, view_id)
    schema = _schema_or_raise(view["module"], view["view_key"])

    name = fields.get("name", view["name"])
    if not (name or "").strip():
        raise SavedViewError("INVALID_INPUT", "A view name is required.", 422)
    filter_params = fields.get("filter_params", view["filter_params"])
    clean_filters = _validate_filter_params(schema, filter_params)
    sort_field = fields.get("sort_field", view["sort_field"])
    if sort_field is not None and sort_field not in schema["sortable_fields"]:
        raise SavedViewError("INVALID_INPUT", f"'{sort_field}' is not a sortable field for this view.", 422)
    sort_dir = fields.get("sort_dir", view["sort_dir"])
    if sort_dir not in ("asc", "desc"):
        raise SavedViewError("INVALID_INPUT", "sort_dir must be 'asc' or 'desc'.", 422)
    columns = fields.get("columns", view["columns"])
    if columns is not None:
        unknown_cols = set(columns) - schema["available_columns"]
        if unknown_cols:
            raise SavedViewError("INVALID_INPUT", f"Unknown column(s): {', '.join(sorted(unknown_cols))}.", 422)
    shared = fields.get("shared", view["shared"])
    is_default = fields.get("is_default", view["is_default"])

    now = utcnow().isoformat()
    if is_default:
        db.execute(
            "UPDATE saved_views SET is_default=0 WHERE owner_user_id=%s AND module=%s AND view_key=%s AND id != %s",
            (actor["id"], view["module"], view["view_key"], view_id),
        )
    db.execute(
        "UPDATE saved_views SET name=%s, shared=%s, filter_json=%s, sort_field=%s, sort_dir=%s, "
        "columns_json=%s, is_default=%s, updated_at=%s WHERE id=%s",
        (name.strip(), int(bool(shared)), json.dumps(clean_filters), sort_field, sort_dir,
         json.dumps(columns) if columns is not None else None, int(bool(is_default)), now, view_id),
    )
    db.commit()
    return get_saved_view(db, actor, view_id)


def delete_saved_view(db, actor: dict, view_id: int) -> None:
    _owned_view_or_raise(db, actor, view_id)
    db.execute("DELETE FROM saved_views WHERE id=%s", (view_id,))
    db.commit()


# ─────────────────────────────────────────────────────────────────────────
# Permission-safe bulk actions
# ─────────────────────────────────────────────────────────────────────────

def execute_bulk_action(db, actor: dict, *, module: str, action_name: str, record_ids: list,
                         authorize_fn, execute_fn, atomic: bool = False,
                         idempotency_key: str | None = None) -> dict:
    """Generic bulk-action engine. Never trusts the posted id list as its
    own authorization (task_plan.md: "a visible selection count is not
    authorization") -- authorize_fn(db, actor, record_id) -> (ok: bool,
    reason: str|None) is called once per id before execute_fn(db, actor,
    record_id) ever runs for that id.

    atomic=False (default, "best-effort"): every id is independently
    authorized and, if authorized, executed; one failure never blocks
    another id. Returns which ids were applied and which were skipped
    (with a reason), so a partial failure is visible and the caller can
    retry just the skipped ones.
    atomic=True: if ANY id fails authorization, nothing is executed at
    all (all ids reported skipped with each one's own reason) -- for an
    action where a partial application would be actively wrong, not just
    incomplete.

    idempotency_key, when given, makes a retried call with the same key
    (scoped to org+module+action_name) return the original result instead
    of re-executing -- this is what the caller should pass from the
    client's Idempotency-Key header (static/js/api_client.js already sends
    one; no route previously consumed it)."""
    if idempotency_key:
        existing = db.execute(
            "SELECT result_json FROM bulk_action_runs WHERE org_id=%s AND module=%s AND action_name=%s "
            "AND idempotency_key=%s",
            (actor["org_id"], module, action_name, idempotency_key),
        ).fetchone()
        if existing:
            result = json.loads(existing["result_json"])
            result["idempotent_replay"] = True
            return result

    authorized, skipped = [], []
    for rid in record_ids:
        ok, reason = authorize_fn(db, actor, rid)
        if ok:
            authorized.append(rid)
        else:
            skipped.append({"id": rid, "reason": reason or "Not authorized."})

    applied = []
    if not (atomic and skipped):
        for rid in authorized:
            db.execute("SAVEPOINT bulk_action_item")
            try:
                execute_fn(db, actor, rid)
                db.execute("RELEASE SAVEPOINT bulk_action_item")
                applied.append(rid)
            except Exception:
                db.execute("ROLLBACK TO SAVEPOINT bulk_action_item")
                db.execute("RELEASE SAVEPOINT bulk_action_item")
                skipped.append({"id": rid, "reason": "Could not apply this action. Retry or contact support."})
    elif atomic and skipped:
        # Atomic + at least one authorization failure: apply nothing: every
        # id that *would* have been authorized is reported skipped too, so
        # the caller sees the whole batch was refused, not silently ignored.
        for rid in authorized:
            skipped.append({"id": rid, "reason": "Not applied: another id in this atomic batch was not authorized."})

    result = {"applied": applied, "skipped": skipped, "idempotent_replay": False}

    now = utcnow().isoformat()
    db.execute(
        "INSERT INTO audit_log (user_id, username, module, action, entity_type, entity_id, details, org_id) "
        "VALUES (%s,%s,%s,%s,'bulk_action',0,%s,%s)",
        (actor["id"], actor.get("username", ""), module, action_name,
         f"{len(applied)} of {len(record_ids)} record(s) applied, {len(skipped)} skipped", actor["org_id"]),
    )
    if idempotency_key:
        db.execute(
            "INSERT INTO bulk_action_runs (idempotency_key, org_id, module, action_name, actor_id, "
            "result_json, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (idempotency_key, actor["org_id"], module, action_name, actor["id"], json.dumps(result), now),
        )
    db.commit()
    return result
