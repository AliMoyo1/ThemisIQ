# PLAN-03: Make task board and ERM workflow transitions concurrency-safe

## Status: COMPLETE (2026-07-15)

Commit: `Make ERM workflow and task board updates concurrency-safe`
Files changed: `modules/erm/data_service.py`, `modules/launcher/routes_platform.py`, `tests/test_concurrency_guards.py`
110/110 tests passing.

## Goal

Two confirmed read-then-write races (the last open HIGH item from the
pre-launch bug audit):

1. **ERM workflow** — `transition_workflow()` in
   `oneforall/modules/erm/data_service.py:1523` reads `workflow_step`,
   validates the transition against that stale value, then writes
   unconditionally. Two concurrent requests can both validate against the
   same starting step, producing duplicate history rows and allowing the
   step-skip guard to be bypassed (A reads "draft", B advances to
   "identified", A then writes "identified" again — or worse, validates a
   jump against the stale step).
2. **Task board** — `api_task_update()` (routes_platform.py:733) and
   `api_tasks_bulk_update()` (routes_platform.py:774) check permissions
   with a SELECT and then UPDATE in a second statement. Between the two
   statements the task can be reassigned or deleted (TOCTOU), and
   drag-drop double-fires can interleave.

Fix pattern for both: **single conditional UPDATE with a rowcount check**
(optimistic concurrency). No SELECT FOR UPDATE — it does not exist on
SQLite and this codebase runs both engines.

## Exact files to touch

1. `oneforall/modules/erm/data_service.py` — `transition_workflow()` (line ~1523)
2. `oneforall/modules/launcher/routes_platform.py` — `api_task_update()`
   (line ~733) and `api_tasks_bulk_update()` (line ~774)
3. `oneforall/tests/test_concurrency_guards.py` — new test file

## Step-by-step order

### Step 1 — Rewrite transition_workflow with a compare-and-swap UPDATE

Replace the body of `transition_workflow` so that:

1. The read/validate part stays exactly as-is (lines 1527-1541).
2. The UPDATE becomes conditional on the step still being what we read,
   using `COALESCE` so a NULL step matches "draft":

```python
        step_status_map = {
            "closed":   "closed",
            "treated":  "mitigated",
            "assessed": "under_review",
        }
        new_status = step_status_map.get(to_step)
        if new_status:
            cur = db.execute(
                "UPDATE erm_enterprise_risks SET workflow_step=%s, status=%s, updated_at=%s "
                "WHERE id=%s AND COALESCE(workflow_step,'draft')=%s",
                (to_step, new_status, _now(), risk_id, from_step)
            )
        else:
            cur = db.execute(
                "UPDATE erm_enterprise_risks SET workflow_step=%s, updated_at=%s "
                "WHERE id=%s AND COALESCE(workflow_step,'draft')=%s",
                (to_step, _now(), risk_id, from_step)
            )
        if cur.rowcount == 0:
            db.rollback()
            raise ValueError(
                "Risk was updated by someone else — reload and try again"
            )
        db.execute(
            "INSERT INTO erm_risk_workflow_history (risk_id, from_step, to_step, changed_by, notes) "
            "VALUES (%s,%s,%s,%s,%s)", (risk_id, from_step, to_step, user_id, notes)
        )
        db.commit()
        return to_step
```

Note the ORDER CHANGE: the history INSERT currently happens BEFORE the
UPDATE (line 1542). It must move AFTER the successful conditional update,
so a lost race writes no phantom history row.

### Step 2 — Fold the permission predicate into the task UPDATE

In `api_task_update()` (routes_platform.py:733): keep the existing
pre-read (it produces the correct 404 vs 403 error), but make the UPDATE
itself carry the same predicate so the permission cannot go stale between
the two statements. Replace lines 764-768:

```python
        if fields:
            fields.append("updated_at = CURRENT_TIMESTAMP")
            params.append(tid)
            sql = f"UPDATE task_board SET {', '.join(fields)} WHERE id = %s"
            if not is_admin:
                sql += " AND (created_by = %s OR assigned_to = %s)"
                params.extend([uid, uid])
            cur = db.execute(sql, params)
            db.commit()
            if cur.rowcount == 0:
                return _JSONResp({"error": "Task changed or was removed — refresh and retry."}, 409)
```

### Step 3 — Same fold for the bulk endpoint

In `api_tasks_bulk_update()`: the ownership pre-SELECT (lines 806-813)
stays (it powers the "No accessible tasks" error), but append the same
ownership predicate to the final UPDATE (line 818-819):

```python
        sql = f"UPDATE task_board SET {', '.join(fields)} WHERE id IN ({placeholders})"
        if not is_admin:
            sql += " AND (created_by = %s OR assigned_to = %s)"
            params.extend([uid, uid])
        db.execute(sql, params)
```

READ the full function first — `params` already had the ids appended at
line 817; the ownership params must come AFTER the ids to match the SQL
placeholder order. Verify the final params order matches the SQL exactly:
SET-values, then ids, then uid, uid.

### Step 4 — Tests

Create `oneforall/tests/test_concurrency_guards.py` (copy the path/bootstrap
style from an existing test file in the same directory):

Test 1 — stale-step transition raises:
1. Insert a risk with `workflow_step='draft'` directly via `get_db()`.
2. Call `transition_workflow(risk_id, "identified", user_id=1)` — passes.
3. Simulate the race: call the module-internal path with a stale
   expectation by directly executing the conditional UPDATE with
   `from_step='draft'` (now stale) and assert `rowcount == 0`.
4. Assert `erm_risk_workflow_history` has exactly ONE row for the risk.
5. Delete the test risk + history rows.

Test 2 — non-owner task update hits the predicate:
1. Insert a task with `created_by=1, assigned_to=1`.
2. Run the conditional UPDATE SQL with `uid=99999` (not owner, not admin)
   and assert `rowcount == 0`.
3. Clean up the task row.

### Step 5 — Verify and commit

- `python -m py_compile` on both touched files.
- `python -m pytest oneforall/tests/ -x` — all green.
- Live smoke: start the app, open ERM, advance a test risk one workflow
  step in the drawer; open the task board and drag a card between columns.
  Both must still work (the guards must be invisible in the happy path).
- One commit: `Make ERM workflow and task board updates concurrency-safe`.

## Edge cases a weaker model would miss

- **`cur.rowcount` semantics differ per driver but both work here:**
  sqlite3 and psycopg2 both report affected rows for UPDATE. But the
  db wrapper's `execute()` must RETURN the cursor for this to work —
  verify by reading `_SqliteConnWrapper.execute` / `_PgConnWrapper.execute`
  in `database.py` first. If the wrapper returns something without
  `.rowcount`, add the property pass-through there instead of changing
  the call sites.
- **`COALESCE(workflow_step,'draft')`** — the existing code maps NULL to
  "draft" in Python (`risk["workflow_step"] or "draft"`). The SQL guard
  must replicate that or every first transition on a fresh risk fails.
- **History INSERT must move after the guard.** If you leave it before
  the UPDATE and the guard fires, `db.rollback()` un-does it — but only
  if the rollback actually happens before `db.close()`. Keep the explicit
  `db.rollback()` in the failure branch; do not rely on close-time
  rollback semantics, which differ between the two wrappers.
- **Backward transitions are allowed by design** (returns/revisions —
  see B22 fix note). The guard only checks the step hasn't changed, not
  direction. Do not add a direction check.
- **Bulk endpoint param ordering** — the SET-clause params, the id list,
  and the ownership uids must appear in `params` in exactly the order
  their placeholders appear in the SQL string. Getting this wrong fails
  silently on SQLite (binds wrong values) rather than erroring.
- **409, not 500, on conflict** — the task endpoint returns a structured
  JSON error so the frontend drag-drop can refetch. Do not raise.
- **Do not wrap these in explicit BEGIN** — the wrappers already run in
  transaction-per-commit mode; adding nested BEGIN breaks the PG wrapper.

## Acceptance criteria

1. Both new tests pass; full suite still green.
2. Happy-path UX unchanged: workflow advance works in the ERM drawer;
   task drag-drop works on the board.
3. Direct-SQL race simulation (stale step) affects 0 rows and produces no
   history row.
4. `grep -n "rowcount" oneforall/modules/erm/data_service.py
   oneforall/modules/launcher/routes_platform.py` shows the three guard
   sites.
