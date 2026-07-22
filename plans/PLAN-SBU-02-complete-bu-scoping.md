# PLAN-SBU-02: Complete BU scoping across the unscoped surfaces

## Leverage rank: 2 of 4 (DO SECOND, after SBU-01). Turns "some modules
## isolate by SBU" into "the platform isolates by SBU" — the trust/security
## closure that makes the multi-SBU promise real. A subsidiary's data leaking
## platform-wide is a demo-killer for the group-company sell.

## Goal / feature

5 of the 6 risk/compliance modules already filter their core lists by
`bu_scope_ids(user)` (ERM, ORM events, BCM plans/BIA, Sentinel, GRID audits).
But several surfaces carry a `business_unit_id` column yet **never filter by
it**, so those records are visible to every user regardless of SBU
assignment. Verified gaps:

| Surface | Table | Column exists (database.py `_COLUMN_MIGRATIONS`) | Filtered today |
|---|---|---|---|
| Task Board | `task_board` | line ~4082 | ❌ NO |
| Evidence Vault | `evidence_items` | line ~4077 | ❌ NO |
| BCM Incidents | `bcm_incidents` | line ~4076 | ❌ NO |
| ORM RCSA | `orm_rcsa_assessments` | line ~4067 | ❌ NO |
| ARIA policies/controls | `aria_documents`, `aria_controls` | lines ~4068-4069 | ❌ NO (see Step 5 — deliberately deferred) |

This plan adds BU-scope filtering to the four clean wins (Task Board,
Evidence, BCM Incidents, ORM RCSA), each mirroring the already-shipped
ERM/ORM pattern exactly. ARIA is handled as an explicitly-deferred sub-item
with rationale, NOT silently skipped.

## The canonical pattern to mirror (already in the codebase)

From `oneforall/modules/orm/data_service.py:27-58` (`list_events`):
```python
def list_events(..., bu_scope=None):
    ...
    if bu_scope is not None:
        ph = ",".join(["%s"] * len(bu_scope))
        where.append(f"(e.business_unit_id IN ({ph}) OR e.business_unit_id IS NULL)")
        params.extend(bu_scope)
```
And the route threads it via `from modules.governance.data_service import bu_scope_ids` then `bu_scope=bu_scope_ids(request.state.user)`.

Two invariants every site must preserve:
- **`bu_scope is None` ⇒ no filter** (super-admins and org-wide users see all).
- **`OR business_unit_id IS NULL`** is included so legacy/unassigned records
  (which is ALL records until they get a BU) remain visible to in-scope users
  rather than vanishing. Do NOT drop this clause.

## Exact files to touch

1. `oneforall/modules/launcher/routes_platform.py` — task_board list query
   (~line 681, `FROM task_board t`) + its stats queries (lines ~872-901).
2. `oneforall/modules/evidence/routes.py` — evidence list query (~line 121,
   `FROM evidence_items e`) + tree/detail scoping.
3. `oneforall/modules/bcm/data_service.py` — `list_incidents()` (~line 504).
4. `oneforall/modules/bcm/routes.py` — the incidents list route that calls it.
5. `oneforall/modules/orm/data_service.py` — `list_rcsa_assessments()`
   (~line 441).
6. `oneforall/modules/orm/routes.py` — the RCSA list route that calls it.
7. `oneforall/tests/test_bu_scoping.py` — NEW test file.

## Step-by-step order

### Step 1 — ORM RCSA (smallest, do first as the template)

1a. `orm/data_service.py` — change `def list_rcsa_assessments():` to
`def list_rcsa_assessments(bu_scope=None):`. In the query, the table alias is
`a`. Insert a WHERE clause before `ORDER BY`:
```python
where = ""
params = []
if bu_scope is not None:
    ph = ",".join(["%s"] * len(bu_scope))
    where = f"WHERE (a.business_unit_id IN ({ph}) OR a.business_unit_id IS NULL) "
    params = list(bu_scope)
```
Splice `{where}` in immediately before `"ORDER BY a.created_at DESC"` and pass
`params` to `db.execute`. (The current query has no WHERE, so this is a clean
insert.)

1b. `orm/routes.py` — find the route calling `ds.list_rcsa_assessments()`
(grep `list_rcsa_assessments`). `bu_scope_ids` is already imported in this
file (used for events). Change the call to
`ds.list_rcsa_assessments(bu_scope=bu_scope_ids(request.state.user))`.

1c. **RCSA detail/risk endpoints:** the assessment detail route
(`get_rcsa_assessment`) should 404 when the assessment's `business_unit_id`
is outside scope. Add, in the detail route, after fetching:
```python
scope = bu_scope_ids(request.state.user)
if scope is not None and a.get("business_unit_id") is not None and a["business_unit_id"] not in scope:
    raise HTTPException(404)
```
Mirror the existing ERM detail guard (`erm/routes.py:140-142`).

### Step 2 — BCM Incidents

2a. `bcm/data_service.py` — change `def list_incidents(status=None, limit=200):`
to add `bu_scope=None`. Rebuild the function to compose WHERE dynamically
(currently it branches on `status`):
```python
def list_incidents(status=None, limit=200, bu_scope=None):
    db = get_db()
    try:
        where, params = [], []
        if status:
            where.append("status=%s"); params.append(status)
        if bu_scope is not None:
            ph = ",".join(["%s"] * len(bu_scope))
            where.append(f"(business_unit_id IN ({ph}) OR business_unit_id IS NULL)")
            params.extend(bu_scope)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        return _dicts(db.execute(
            f"SELECT * FROM bcm_incidents {clause} ORDER BY created_at DESC LIMIT %s",
            params + [limit]).fetchall())
    finally:
        db.close()
```
2b. `bcm/routes.py` — grep `list_incidents`; `bu_scope_ids` is already
imported here (used for plans/BIA). Thread
`bu_scope=bu_scope_ids(request.state.user)` into every call. Add the same
404-out-of-scope guard to the incident detail route.

### Step 3 — Task Board (`launcher/routes_platform.py`)

The task list query is at ~line 681 (`FROM task_board t`). This file may NOT
yet import `bu_scope_ids` — add `from modules.governance.data_service import bu_scope_ids`
at the top with the other imports.

3a. In the list route, compute `scope = bu_scope_ids(request.state.user)`.
Add to the query's WHERE (the query already has filters — append):
```python
if scope is not None:
    ph = ",".join(["%s"] * len(scope))
    # confirm the alias — the query uses `t`
    query += f" AND (t.business_unit_id IN ({ph}) OR t.business_unit_id IS NULL)"
    params.extend(scope)
```
3b. **Task stats** (lines ~872-901): the status-count and overdue-count
queries also need the same scope filter, otherwise the stat badges will
disagree with the visible list (a classic partial-migration bug this repo has
fought before — see the framework slice). Apply the `business_unit_id IN
(...) OR IS NULL` clause to each stat query too. If a stat query has no alias,
use the bare column name.
3c. **Task detail / update / delete** by id: add the scope guard so a user
cannot open/mutate a task in another SBU by guessing its id. Fetch the task's
`business_unit_id` and 404 if `scope is not None and bu not in scope and bu is
not None`.

### Step 4 — Evidence Vault (`evidence/routes.py`)

The list query is at ~line 121 (`FROM evidence_items e`). Add
`from modules.governance.data_service import bu_scope_ids` if not present.
4a. In the list route, add the scope clause (alias `e`) to the WHERE, same
pattern.
4b. **Evidence detail / download / delete** by id (`evidence_items WHERE id
= %s` at lines 279, 379, 415, 475): add the scope guard on fetch so a
subsidiary's evidence file cannot be downloaded cross-SBU by id. This matters
MORE for evidence than for lists (it is file content). Do NOT skip the
by-id endpoints here.
4c. **Evidence tree / parent-child** (lines 600-620): if a child's
`business_unit_id` differs from an in-scope parent, keep it simple — scope on
the record being requested; do not try to re-scope the whole tree walk. Note
this as a known limitation in the code comment.

### Step 5 — ARIA (DEFERRED — document, do NOT implement in this plan)

ARIA is architecturally different: it has **no `data_service.py`**; all DB
access is inline in `modules/aria/routes.py` (the document list query is at
~line 833, `FROM aria_documents WHERE 1=1`), and there are ~30 scattered
`aria_documents`/`aria_controls` queries. Also, policies/controls are often
**intentionally org-wide** (a group-level infosec policy applies to every
SBU), so blanket BU-filtering could hide policies that SHOULD be visible.

Decision for this plan: **do not scope ARIA here.** Instead, add a one-line
`# TODO(SBU): ARIA documents/controls are not BU-scoped — org-wide by design;
revisit if per-SBU policy libraries are required` comment above the list
query at `aria/routes.py:833`, and record the deferral in the plan log. A
proper ARIA scoping effort needs its own plan (extract a data_service layer
first, then decide the org-wide-vs-scoped policy semantics with the user).
Bundling it here would balloon the change and risk hiding group policies.

### Step 6 — tests (`oneforall/tests/test_bu_scoping.py`)

Use the `test_db` fixture. For EACH of the four scoped surfaces (RCSA,
incidents, tasks, evidence), write a test that:
1. Creates two BUs: `bu_a` and `bu_b` (siblings, no parent link between them).
2. Inserts three records: one with `business_unit_id = bu_a`, one with
   `bu_b`, one with `NULL`.
3. Calls the list function with `bu_scope=[bu_a]` and asserts it returns the
   `bu_a` record AND the `NULL` record, but NOT the `bu_b` record.
4. Calls with `bu_scope=None` and asserts all three come back.

Plus one integration test:
5. `test_end_to_end_scope` — create parent BU `P` with child `C`; a record
   under `C`; call the list function with
   `bu_scope=bu_scope_ids({"business_unit_id": P_id, "is_super_admin": 0})`
   and assert the record under `C` IS visible (rollup: a P-scoped user sees
   C's records). This ties the filter to the real scope helper.

Run the full suite afterward — confirm the pre-existing scoped modules (ERM,
ORM events, Sentinel, GRID, BCM plans) still pass unchanged.

## Edge cases a weaker model would miss

- **Keep `OR business_unit_id IS NULL`.** Until SBU-01 has assigned BUs to
  records, EVERY record has NULL. Dropping the NULL clause would make an
  in-scope user see NOTHING, breaking the app for scoped users on day one.
- **Scope the STATS as well as the LIST** (Task Board especially). Mismatched
  stat badges vs. visible rows is a real, previously-hit bug class in this
  repo. Every count query on the same page must use the same scope.
- **Scope the by-id detail/download/delete endpoints, not just the lists.**
  A list filter alone still lets a user open `GET /evidence/{id}` for another
  SBU's file by guessing the id (IDOR). The by-id guards are the actual
  security boundary; the list filter is UX. Evidence downloads and task
  mutation are the highest-risk by-id paths — do not skip them.
- **`bu_scope_ids` returns None for super-admins and unassigned users** — the
  `if scope is not None` guard must wrap BOTH the list clause and every by-id
  guard, or you will 404 super-admins out of their own data.
- **Alias correctness.** Each query uses a specific alias (`a`, `e`, `t`) or
  none. Using the wrong alias (or an alias on a query that has none) is a SQL
  error. Read each query and match the alias exactly; for un-aliased queries
  use the bare column `business_unit_id`.
- **`routes_platform.py` and `evidence/routes.py` likely do NOT import
  `bu_scope_ids` yet** — add the import. `bcm/routes.py`, `orm/routes.py`,
  `erm/routes.py` already do.
- **Placeholder style is `%s` everywhere** (the app normalizes for
  SQLite/PG). Do not use `?`.
- **ARIA is deferred on purpose, not forgotten.** If a reviewer asks "why is
  ARIA still unscoped," the TODO comment + this section are the answer. Do
  not quietly add half-working ARIA scoping.

## Acceptance criteria (verifiable)

1. `python -m pytest tests/test_bu_scoping.py` — all tests pass, covering the
   four surfaces + the rollup integration test.
2. Full suite: no regressions vs. the current passing count.
3. Manual: assign temp user `alice` to SBU `bu_a` (via SBU-01's UI). Create
   one task, one evidence item, one BCM incident, one RCSA assessment under
   `bu_b` (a different SBU) as an admin. Log in as `alice`: none of the four
   `bu_b` records appear in her lists, and hitting each `bu_b` record's by-id
   URL returns 404 — while `bu_a`-owned and NULL-owned records DO appear.
4. As a super-admin (scope None): all records on all four surfaces are
   visible, stats match the lists.
5. `grep -rn "TODO(SBU)" modules/aria/routes.py` shows the deferral marker
   (proves ARIA was consciously deferred, not missed).
6. On each affected page, the summary stat counts equal the number of rows
   actually shown for the logged-in user (no stat/list mismatch).
```
