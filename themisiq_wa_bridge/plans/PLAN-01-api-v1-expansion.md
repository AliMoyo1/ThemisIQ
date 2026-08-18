# PLAN-01: Expand REST API v1 (Phase-1 read endpoints + per-module key scopes)

## Goal

Give ThemisIQ's public API everything the WhatsApp assistant (and any other integration) needs for the read-only MVP:

1. Six new read-only endpoints: `/api/v1/dpias`, `/api/v1/dsrs`, `/api/v1/kris`, `/api/v1/risk-summary`, `/api/v1/documents` (+ `/api/v1/documents/{doc_id}`), `/api/v1/overview`.
2. Per-module API key scopes (DPIA measure M2, least privilege): a key can be limited to `sentinel`, `erm`, `aria`, `grid` instead of all-modules read.
3. Admin UI checkboxes to pick module scopes when creating a key.

Everything stays read-only (GET only). No writes.

## Files to touch

- `oneforall\modules\launcher\routes_api_v1.py` (main work)
- `oneforall\modules\launcher\routes_admin.py` (key creation accepts module scopes)
- `oneforall\modules\launcher\templates\admin_api_keys.html` (scope checkboxes)
- `oneforall\tests\test_api_v1.py` (new file)

## Reference: real table schemas (verified in database.py, do not invent columns)

- `sentinel_dpias`: id, ref_number, title, department, owner, status (default 'draft'), risk_level, regulation, created_at, updated_at
- `sentinel_dsr`: id, ref_number, requester_name, requester_email, request_type, regulation, received_date, deadline_date, status (default 'open'), created_at
- `sentinel_breaches`: already served by the existing `/api/v1/breaches`
- `erm_enterprise_risks`: id, title, category, likelihood, impact, status, treatment, board_visibility, review_date
- `erm_kris`: id, name, current_value, threshold_warn, threshold_crit, unit, frequency, status, trend, last_updated
- `aria_documents`: id, doc_id (TEXT unique), framework, control_ref, title, doc_type, version, status, owner, review_date, body
- `risk_register` (cross-module, used by existing `/api/v1/risks`)

## Steps in order

### Step 1: Add module scoping helpers to routes_api_v1.py

In `routes_api_v1.py`, directly AFTER the existing function `_has_read_scope`, add:

```python
def _scope_set(scopes_str: str) -> set[str]:
    return {s.strip() for s in (scopes_str or "").split(",") if s.strip()}


def _allows_module(scopes_str: str, module: str) -> bool:
    """Legacy plain 'read' grants every module. Granular keys carry
    'read' plus 'read:<module>' entries and only get those modules."""
    scopes = _scope_set(scopes_str)
    granular = {s for s in scopes if s.startswith("read:")}
    if not granular:
        return "read" in scopes
    return ("read:" + module) in granular


def _require_module(module: str):
    """Dependency factory: authenticates the key AND checks module scope."""
    async def _dep(key=Depends(_require_read_key)):
        if not _allows_module(key.get("scopes", ""), module):
            raise HTTPException(status_code=403,
                                detail=f"API key not scoped for module '{module}'")
        return key
    return _dep
```

### Step 2: Apply module scopes to the three existing endpoints

Change the dependency on each existing endpoint (keep everything else identical):

- `list_risks`: change `_key=Depends(_require_read_key)` to `_key=Depends(_require_module("erm"))`
- `list_audits`: change to `_key=Depends(_require_module("grid"))`
- `list_breaches`: change to `_key=Depends(_require_module("sentinel"))`

### Step 3: Add the six new endpoints

Append to the END of `routes_api_v1.py`:

```python
_OPEN_EXCLUDED = {
    "dpias": ("completed", "approved", "closed", "rejected"),
    "dsrs": ("completed", "closed", "rejected"),
}


def _list_query(db, table: str, columns: str, where_parts: list, params: list,
                order_by: str, limit: int, offset: int) -> dict:
    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    total = db.execute(
        f"SELECT COUNT(*) FROM {table} {where_clause}", tuple(params)
    ).fetchone()[0]
    rows = db.execute(
        f"SELECT {columns} FROM {table} {where_clause}"
        f" ORDER BY {order_by} LIMIT %s OFFSET %s",
        tuple(params + [limit, offset]),
    ).fetchall()
    return {"data": [dict(r) for r in rows], "total": total,
            "limit": limit, "offset": offset}


@router.get("/dpias", summary="List DPIAs")
async def list_dpias(
    status: Optional[str] = Query(None, description="Exact status, or 'open' for all not completed/approved/closed/rejected"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    _key=Depends(_require_module("sentinel")),
):
    where, params = [], []
    if status == "open":
        placeholders = ",".join(["%s"] * len(_OPEN_EXCLUDED["dpias"]))
        where.append(f"status NOT IN ({placeholders})")
        params.extend(_OPEN_EXCLUDED["dpias"])
    elif status:
        where.append("status=%s")
        params.append(status)
    db = get_db()
    try:
        return _list_query(db, "sentinel_dpias",
            "id, ref_number, title, department, owner, status, risk_level,"
            " regulation, created_at, updated_at",
            where, params, "updated_at DESC", limit, offset)
    finally:
        db.close()


@router.get("/dsrs", summary="List data subject requests (PII-minimised)")
async def list_dsrs(
    status: Optional[str] = Query(None, description="Exact status, or 'open'"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    _key=Depends(_require_module("sentinel")),
):
    where, params = [], []
    if status == "open":
        placeholders = ",".join(["%s"] * len(_OPEN_EXCLUDED["dsrs"]))
        where.append(f"status NOT IN ({placeholders})")
        params.extend(_OPEN_EXCLUDED["dsrs"])
    elif status:
        where.append("status=%s")
        params.append(status)
    db = get_db()
    try:
        # DPIA M6 data minimisation: requester_name / requester_email are
        # deliberately NOT returned over the API.
        return _list_query(db, "sentinel_dsr",
            "id, ref_number, request_type, regulation, received_date,"
            " deadline_date, status, created_at",
            where, params, "deadline_date ASC", limit, offset)
    finally:
        db.close()


@router.get("/kris", summary="List KRIs with breach level")
async def list_kris(
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    _key=Depends(_require_module("erm")),
):
    db = get_db()
    try:
        result = _list_query(db, "erm_kris",
            "id, name, current_value, threshold_warn, threshold_crit, unit,"
            " frequency, status, trend, last_updated",
            ["status=%s"], ["active"], "name ASC", limit, offset)
    finally:
        db.close()
    for k in result["data"]:
        cur, warn, crit = k.get("current_value"), k.get("threshold_warn"), k.get("threshold_crit")
        level = "ok"
        if cur is not None and crit is not None and cur >= crit:
            level = "critical"
        elif cur is not None and warn is not None and cur >= warn:
            level = "warning"
        k["breach_level"] = level
    return result


@router.get("/risk-summary", summary="Enterprise risk summary")
async def risk_summary(_key=Depends(_require_module("erm"))):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT status, COUNT(*) AS n FROM erm_enterprise_risks GROUP BY status"
        ).fetchall()
        by_status = {r["status"]: r["n"] for r in rows}
        open_avg = db.execute(
            "SELECT AVG(likelihood * impact) FROM erm_enterprise_risks WHERE status='open'"
        ).fetchone()[0]
        top = db.execute(
            "SELECT id, title, category, likelihood, impact,"
            " (likelihood * impact) AS score"
            " FROM erm_enterprise_risks WHERE status='open'"
            " ORDER BY score DESC LIMIT 5"
        ).fetchall()
    finally:
        db.close()
    return {
        "open": by_status.get("open", 0),
        "by_status": by_status,
        "average_open_score": round(open_avg, 1) if open_avg is not None else None,
        "top_risks": [dict(r) for r in top],
    }


@router.get("/documents", summary="List ARIA documents (metadata only)")
async def list_documents(
    status: Optional[str] = Query(None),
    framework: Optional[str] = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    _key=Depends(_require_module("aria")),
):
    where, params = [], []
    if status:
        where.append("status=%s")
        params.append(status)
    if framework:
        where.append("framework=%s")
        params.append(framework)
    db = get_db()
    try:
        return _list_query(db, "aria_documents",
            "id, doc_id, framework, control_ref, title, doc_type, version,"
            " status, owner, review_date, updated_at",
            where, params, "updated_at DESC", limit, offset)
    finally:
        db.close()


@router.get("/documents/{doc_id}", summary="Get one ARIA document")
async def get_document(
    doc_id: str,
    include_body: bool = Query(False, description="Include body text (truncated to 8000 chars)"),
    _key=Depends(_require_module("aria")),
):
    db = get_db()
    try:
        row = db.execute(
            "SELECT id, doc_id, framework, control_ref, title, doc_type,"
            " version, status, owner, approver, effective_date, review_date,"
            " body FROM aria_documents WHERE doc_id=%s OR id=%s",
            (doc_id, doc_id if doc_id.isdigit() else -1),
        ).fetchone()
    finally:
        db.close()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    doc = dict(row)
    if include_body:
        doc["body"] = (doc.get("body") or "")[:8000]
    else:
        doc.pop("body", None)
    return doc


@router.get("/overview", summary="Cross-module compliance overview")
async def overview(_key=Depends(_require_read_key)):
    """Aggregate counts. Requires only base read scope, but each block is
    included ONLY if the key is scoped for that module."""
    scopes = _key.get("scopes", "")
    out: dict = {}
    db = get_db()
    try:
        if _allows_module(scopes, "sentinel"):
            out["open_breaches"] = db.execute(
                "SELECT COUNT(*) FROM sentinel_breaches WHERE status='open'").fetchone()[0]
            out["open_dsrs"] = db.execute(
                "SELECT COUNT(*) FROM sentinel_dsr WHERE status NOT IN ('completed','closed','rejected')").fetchone()[0]
            out["open_dpias"] = db.execute(
                "SELECT COUNT(*) FROM sentinel_dpias WHERE status NOT IN ('completed','approved','closed','rejected')").fetchone()[0]
        if _allows_module(scopes, "erm"):
            out["open_enterprise_risks"] = db.execute(
                "SELECT COUNT(*) FROM erm_enterprise_risks WHERE status='open'").fetchone()[0]
            out["kris_breaching"] = db.execute(
                "SELECT COUNT(*) FROM erm_kris WHERE status='active' AND threshold_warn IS NOT NULL"
                " AND current_value >= threshold_warn").fetchone()[0]
        if _allows_module(scopes, "grid"):
            out["open_risks_register"] = db.execute(
                "SELECT COUNT(*) FROM risk_register WHERE status='open'").fetchone()[0]
    finally:
        db.close()
    if not out:
        raise HTTPException(status_code=403, detail="Key has no module scopes")
    return out
```

Note the FastAPI dependency object: in `overview`, rename the parameter to `_key=Depends(_require_read_key)` and read scopes from it exactly as written (the dependency returns `dict(row)`).

### Step 4: Admin key creation accepts module scopes

In `routes_admin.py`, find the API key creation endpoint (anchor: `@router.post("/api/admin/api-keys", status_code=201)`). It currently builds a scopes value before the INSERT. Modify it so:

```python
    allowed_modules = {"sentinel", "erm", "aria", "grid"}
    requested = data.get("modules") or []
    if not isinstance(requested, list):
        requested = []
    mods = [m for m in requested if m in allowed_modules]
    scopes = "read"
    if mods:
        scopes = ",".join(["read"] + ["read:" + m for m in sorted(mods)])
```

and pass `scopes` into the existing INSERT in place of the current scopes value. Do not change the hashing, prefix, or response shape.

### Step 5: Admin UI checkboxes

In `templates\admin_api_keys.html`, find the key-creation form/modal (anchor: the input for the key name). Add below the name field:

```html
<div style="margin:10px 0;">
  <label style="display:block;font-size:11px;margin-bottom:6px;">Module scopes (leave all unticked for full read access)</label>
  <label><input type="checkbox" class="key-scope" value="sentinel"> Sentinel (privacy)</label>
  <label><input type="checkbox" class="key-scope" value="erm"> ERM (risk)</label>
  <label><input type="checkbox" class="key-scope" value="aria"> ARIA (documents)</label>
  <label><input type="checkbox" class="key-scope" value="grid"> GRID (audit)</label>
</div>
```

Then find the JS that POSTs to `/api/admin/api-keys` and add to its JSON body:

```js
modules: Array.from(document.querySelectorAll('.key-scope:checked')).map(c => c.value),
```

Match the page's existing styling classes rather than inventing new CSS. Escape nothing here; values are fixed literals.

### Step 6: Tests

Create `oneforall\tests\test_api_v1.py` with at least:

1. `_allows_module` unit tests: `"read"` allows every module; `"read,read:sentinel"` allows only sentinel; `""` allows nothing.
2. Request without `X-API-Key` to `/api/v1/dpias` returns 401.
3. With a seeded key scoped `read,read:erm`: `/api/v1/kris` returns 200 and `/api/v1/dpias` returns 403.
4. `/api/v1/dsrs` response contains no `requester_name` or `requester_email` keys.
5. `/api/v1/dpias?status=open` excludes a row seeded with status `completed`.

Follow the pattern in `oneforall\tests\test_auth.py` / `conftest.py` for app + DB setup.

## Edge cases a weaker model would miss

1. **Legacy keys must keep working.** Existing keys have scopes `read`. The `_allows_module` rule (no granular entries means full read) preserves them. Do not require `read:<module>` on old keys.
2. **PII minimisation on DSRs is deliberate** (DPIA M6). Never add `requester_name`/`requester_email` to the list endpoint, even though the table has them.
3. **`%s` placeholders always**, even for the `NOT IN (...)` lists: build the right number of `%s` from the tuple length as shown. Never f-string values into SQL.
4. **No `datetime('now')` in new SQL.** It is SQLite-only; production is PostgreSQL. The queries above avoid DB-side time entirely.
5. **Tenant context ordering.** `_require_read_key` calls `set_current_tenant(slug)` and each endpoint opens `get_db()` AFTER the dependency has run, so queries hit the right schema. Do not open a db handle at module import time or before the dependency.
6. **`get_document` accepts either the text `doc_id` or numeric id.** The `doc_id.isdigit()` guard prevents passing a non-numeric string to an integer comparison on PostgreSQL (which would raise a type error, unlike SQLite).
7. **KRI breach level semantics:** higher value = worse is assumed (thresholds are ceilings). If `current_value`, `threshold_warn`, or `threshold_crit` is NULL, treat as `ok`; the `is not None` guards do that. Do not use `if cur and warn` (a value of 0 would be falsy).
8. **`overview` degrades by scope** instead of failing: a sentinel-only key gets only the sentinel counts. Only when NO module is allowed does it 403.
9. **`AVG(...)` returns NULL on an empty table.** Guard before `round()` as shown.
10. **Do not touch `_require_read_key`'s last_used_at update or the key hashing** (`PBKDF2` with `SECRET_KEY` salt). Changing the salt logic silently invalidates every issued key.
11. **`Optional` is already imported** in the file; `Depends`, `Query`, `HTTPException` too. Do not re-import or shadow them.
12. **Body truncation on documents** (8000 chars) keeps WhatsApp/LLM payloads bounded and limits leak blast radius. Keep it.

## Acceptance criteria (verify each)

1. `GET /api/v1/dpias` without a key returns 401 JSON.
2. Create a key in Admin with only `sentinel` ticked. Confirm the DB row's scopes value is exactly `read,read:sentinel`.
3. With that key: `/api/v1/dpias`, `/api/v1/dsrs`, `/api/v1/breaches` return 200; `/api/v1/kris`, `/api/v1/risks`, `/api/v1/documents` return 403 with a message naming the missing module.
4. Create a key with nothing ticked: all endpoints return 200 (legacy full read).
5. `/api/v1/dsrs?status=open` returns rows sorted by deadline ascending and contains no requester name or email fields.
6. `/api/v1/kris` rows each include `breach_level` in {ok, warning, critical}, and a KRI with `current_value >= threshold_crit` shows `critical`.
7. `/api/v1/risk-summary` returns `open`, `by_status`, `average_open_score`, `top_risks` (max 5, sorted by score descending).
8. `/api/v1/documents/{doc_id}` returns 404 for an unknown id and omits `body` unless `include_body=true`.
9. `/api/v1/overview` with a sentinel-only key returns only the three sentinel counts.
10. The interactive docs at `/docs` show all new endpoints under the "REST API v1" tag.
11. `pytest oneforall/tests/test_api_v1.py` passes, and the previously existing tests still pass.
12. On the PostgreSQL VPS (after deploy), `curl -H "X-API-Key: <key>" https://themisiq.net/api/v1/overview` returns JSON, proving no SQLite-only SQL slipped in.
