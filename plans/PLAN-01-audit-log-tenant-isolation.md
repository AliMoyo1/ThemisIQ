# PLAN-01: Fix audit_log tenant isolation (cross-org activity leak)

## Goal

Recent-activity views (Command Centre, user dashboard, ARIA, GRID, Sentinel)
currently show audit_log rows from ALL organisations. Two defects combine:

1. **Read side:** 6 query sites select from `audit_log` with no `org_id`
   filter. PostgreSQL RLS hides other orgs from normal users, but
   super_admin bypasses RLS by design, and SQLite (dev) has no RLS at all.
2. **Write side:** GRID's `log_activity()` inserts audit rows WITHOUT
   `org_id`, so those rows are invisible to normal org users on PG (RLS
   filters them out) and unattributable everywhere else.

After this fix: every module-level activity view shows only the current
org's rows; GRID writes are stamped with org_id; historical NULL rows are
backfilled. The admin audit page (`routes_admin.py`) intentionally keeps
showing everything to super_admin — do NOT change that file.

## Exact files to touch

1. `oneforall/database.py` — add a public `get_current_org()` getter + a
   backfill migration in `_seed_baseline_data()`
2. `oneforall/modules/grid/data_service.py` — `log_activity()` (line ~1615)
   and `list_activity()` (line ~1624)
3. `oneforall/modules/sentinel/data_service.py` — `list_audit()` (line ~811)
4. `oneforall/modules/launcher/routes_dashboard.py` — Command Centre recent
   activity (line ~239) and user dashboard activity (line ~627)
5. `oneforall/modules/aria/routes.py` — two activity queries (lines ~293
   and ~2272)
6. `oneforall/tests/` — one new regression test file

Do NOT touch `oneforall/modules/launcher/routes_admin.py`.

## Step-by-step order

### Step 1 — Add the org getter to database.py

Find (around line 61):

```python
def set_current_org(org_id: "int | None", is_super_admin: bool = False):
```

Immediately AFTER that whole function, add:

```python
def get_current_org() -> "int | None":
    """Return the org_id bound to the current request context (None outside a request)."""
    return _current_org_id.get()
```

`_current_org_id` already exists at line ~47. Do not create a second
ContextVar.

### Step 2 — Fix the GRID write side

In `oneforall/modules/grid/data_service.py`, the import line at the top of
the file currently imports from `database`. Add `get_current_org` to that
import list.

Replace `log_activity` (currently at line ~1615):

```python
def log_activity(user_id, action, entity_type, entity_id, details=None):
    db = get_db()
    try:
        db.execute("INSERT INTO audit_log (user_id, action, module, entity_type, entity_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
            (user_id, action, "grid", entity_type, entity_id, json.dumps(details) if details else None))
        db.commit()
    finally:
        db.close()
```

with:

```python
def log_activity(user_id, action, entity_type, entity_id, details=None):
    db = get_db()
    try:
        db.execute("INSERT INTO audit_log (user_id, action, module, entity_type, entity_id, details, org_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (user_id, action, "grid", entity_type, entity_id, json.dumps(details) if details else None, get_current_org()))
        db.commit()
    finally:
        db.close()
```

### Step 3 — Fix the GRID read side

In the same file, replace `list_activity` (line ~1624):

```python
def list_activity(limit=50):
    db = get_db()
    try:
        org_id = get_current_org()
        sql = ("SELECT a.*, u.full_name AS user_name FROM audit_log a "
               "LEFT JOIN users u ON a.user_id=u.id WHERE a.module='grid' ")
        params = []
        if org_id is not None:
            sql += "AND a.org_id=%s "
            params.append(org_id)
        sql += "ORDER BY a.created_at DESC LIMIT %s"
        params.append(limit)
        return _dicts(db.execute(sql, tuple(params)).fetchall())
    finally:
        db.close()
```

### Step 4 — Fix Sentinel read side

In `oneforall/modules/sentinel/data_service.py`, add `get_current_org` to
the `database` import at the top. Then find `list_audit` (line ~811) whose
query is:

```python
"SELECT * FROM audit_log WHERE module='sentinel' ORDER BY created_at DESC LIMIT %s",
```

Apply the same pattern as Step 3: read `org_id = get_current_org()`, append
`AND org_id=%s` to the WHERE when `org_id is not None`, build params
accordingly.

### Step 5 — Fix Command Centre + user dashboard

In `oneforall/modules/launcher/routes_dashboard.py`:

**Site A (line ~239-242):** READ the surrounding 15 lines first to get the
full statement. The query ends with:

```python
"FROM audit_log al ORDER BY al.created_at DESC LIMIT 6"
```

These are routes: get the org from the logged-in user, not the ContextVar
(both work, but the user dict is already available):

```python
org_id = request.state.user.get("org_id")
```

Rewrite the query so that when `org_id is not None` it becomes
`... FROM audit_log al WHERE al.org_id=%s ORDER BY al.created_at DESC LIMIT 6`
with `(org_id,)` params; otherwise leave it unfiltered.

**Site B (line ~627-630):** same treatment. READ the surrounding lines
first — this query already has a JOIN (`LEFT JOIN users u ...`) and may
already have a WHERE clause. If a WHERE exists, append
`AND al.org_id=%s`; if none exists, add `WHERE al.org_id=%s`.

### Step 6 — Fix ARIA read sites

In `oneforall/modules/aria/routes.py`, lines ~293 and ~2272, both queries
start `SELECT al.*, u.full_name FROM audit_log al ...`. READ each full
statement first. Both already filter `al.module='aria'` (verify). Add
`AND al.org_id=%s` using `request.state.user.get("org_id")`, only when it
is not None, following the same conditional-params pattern as Step 3.

### Step 7 — Backfill historical NULL org rows

In `oneforall/database.py`, inside `_seed_baseline_data(conn)`, add this
block at the END of the function (before its final line), following the
same try/except style used by the other seed blocks:

```python
    # ── Backfill audit_log.org_id from the acting user (idempotent) ─────────
    # GRID's log_activity() historically inserted without org_id; those rows
    # are invisible to org users under RLS. After the first run this UPDATE
    # matches zero rows.
    try:
        conn.execute(
            "UPDATE audit_log SET org_id = ("
            "SELECT u.org_id FROM users u WHERE u.id = audit_log.user_id) "
            "WHERE audit_log.org_id IS NULL AND audit_log.user_id IS NOT NULL"
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
```

### Step 8 — Regression test

Create `oneforall/tests/test_audit_org_isolation.py`:

```python
"""Regression: audit_log activity queries must scope to the current org."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import get_db, set_current_org, get_current_org


def test_get_current_org_roundtrip():
    set_current_org(42)
    assert get_current_org() == 42
    set_current_org(None)
    assert get_current_org() is None


def test_grid_log_activity_stamps_org():
    from modules.grid import data_service as gds
    set_current_org(999)
    gds.log_activity(None, "test_org_stamp", "test", 0, None)
    set_current_org(None)
    db = get_db()
    try:
        row = db.execute(
            "SELECT org_id FROM audit_log WHERE action='test_org_stamp' "
            "ORDER BY id DESC LIMIT 1").fetchone()
        assert row is not None
        assert row[0] == 999
        db.execute("DELETE FROM audit_log WHERE action='test_org_stamp'")
        db.commit()
    finally:
        db.close()
```

Match the import/bootstrapping style of the existing files in
`oneforall/tests/` — READ one of them first and copy its conftest/path
setup if it differs from the above.

## Edge cases a weaker model would miss

- **Do not filter when org_id is None.** Dev SQLite users and legacy
  super_admins have `org_id = NULL`. Filtering `WHERE org_id = NULL` in SQL
  never matches (NULL comparison), which would blank every dashboard in
  dev. That is why every site uses the conditional-params pattern.
- **`routes_admin.py` must stay unscoped.** The platform admin audit page
  is the one place super_admin is supposed to see everything. If you touch
  lines 465/471/479/534 there, you have broken a feature, not fixed a bug.
- **The seed backfill runs on a connection that bypasses RLS**
  (`init_db()` uses `get_db_bypass_rls()`), so the UPDATE can see NULL-org
  rows. Do not move the backfill into a normal request path — RLS would
  hide the rows it needs to fix.
- **Params must stay a tuple** — `db.execute(sql, params_list)` works in
  this codebase only via `tuple(params)`; passing a bare list is
  inconsistent with surrounding style.
- **aria/routes.py queries are multi-line triple-quoted SQL** — match the
  exact existing whitespace when editing or the Edit tool will fail;
  always Read the file section before editing.
- **grid data_service has no `request`** — that is why the ContextVar
  getter exists. Do not try to thread a `request` parameter through
  data_service signatures; other callers (schedulers, event handlers)
  don't have one.
- **`log_audit()` in core/middleware.py already handles org_id
  correctly** (line ~541) — do not "fix" it.

## Acceptance criteria

1. `python -m py_compile` passes on all 5 touched Python files.
2. `python -m pytest oneforall/tests/ -x` — every pre-existing test still
   passes, plus the 2 new tests pass.
3. Grep check: `grep -rn "FROM audit_log" oneforall/modules/` shows an
   org_id condition (or documented conditional) at all sites EXCEPT
   `routes_admin.py`.
4. Manual: start the app (`python -m uvicorn main:app` from `oneforall/`),
   log in, open Command Centre — recent activity renders without errors.
   Open GRID and Sentinel activity tabs — both render.
5. On PG (VPS, post-deploy): rows previously showing NULL org in
   `SELECT COUNT(*) FROM audit_log WHERE org_id IS NULL AND user_id IS NOT NULL`
   drop to 0 after one app restart.
