# PLAN-13: Compliance Drift Detection + Manual Regulatory Inbox (T2.2 + T4.2-lite)

## Goal

Two approved roadmap items that only work as a pair (user decision
2026-07-04: External Context Layer ships as a MANUAL inbox, no paid
feeds):

1. **Regulatory Inbox (T4.2-lite):** an admin surface where the CGRCO or
   platform team posts regulatory updates by hand — framework, effective
   date, summary, affected control refs. This is the data source.
2. **Drift Detection (T2.2):** a nightly job that deterministically
   matches open inbox entries against the tenant's frameworks and
   controls, and turns matches into actionable `task_board` items
   ("Review control A.5.1 against ISO 27001 amendment X"). AI is used at
   most once per inbox entry to draft a summary, only when a key is
   configured — matching itself is pure string logic (the platform's
   established "math, not AI" principle).

No dependency on Tier 1 — this works entirely off the EXISTING
`frameworks` and `controls` tables and can ship any time.

## Exact files to touch

1. `oneforall/database.py` — `regulatory_updates` table (BOTH
   `_SHARED_TABLES` and `_PLATFORM_TABLES`, the T1.1 dual-block pattern)
2. `oneforall/modules/governance/data_service.py` — inbox CRUD + the
   drift matcher
3. `oneforall/modules/governance/routes.py` — inbox endpoints + manual
   "run drift check now" endpoint
4. `oneforall/modules/governance/templates/index.html` — "Regulatory
   Inbox" tab (the governance SPA already has the tab pattern)
5. `oneforall/modules/evidence/scheduler.py` — nightly hook (same
   pattern as PLAN-11's; independent of it)
6. `oneforall/tests/test_regulatory_drift.py` — new tests

## Step-by-step order

### Step 1 — Table (both blocks)

```sql
-- ── Regulatory Inbox (T4.2-lite): manually posted regulatory updates ──────
CREATE TABLE IF NOT EXISTS regulatory_updates (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    framework_name      TEXT NOT NULL,
    title               TEXT NOT NULL,
    summary             TEXT,
    source_url          TEXT,
    effective_date      TEXT,
    affected_refs       TEXT,
    severity            TEXT DEFAULT 'info',
    status              TEXT DEFAULT 'open',
    ai_summary          TEXT,
    matched_count       INTEGER,
    processed_at        TEXT,
    created_by          INTEGER,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_regupd_status ON regulatory_updates(status);
```

`affected_refs` is a comma-separated list of control refs as typed by
the admin (e.g. `A.5.1, A.8.12`). `status`: open → processed →
dismissed. Bare INTEGER created_by (dual-block convention, no FK).

### Step 2 — Inbox CRUD

In `modules/governance/data_service.py`, copy the exact shape of the
existing entity functions (e.g. applications):
`list_regulatory_updates(status=None)`,
`create_regulatory_update(data)`, `update_regulatory_update(rid, data)`,
`delete_regulatory_update(rid)`, plus
`dismiss_regulatory_update(rid)` (status='dismissed', updated_at=now).
Validate `severity` to `{'info','medium','high'}` and `status` to
`{'open','processed','dismissed'}` at write time.

In `routes.py`: GET list (`governance.entities.view`), POST/PUT/DELETE +
POST `/api/regulatory-updates/{rid}/dismiss`
(`governance.entities.manage`) — copy the applications endpoints
verbatim, adjusting names.

### Step 3 — The drift matcher

In `modules/governance/data_service.py`:

```python
def run_drift_check(db, update_id=None) -> dict:
    """Match open regulatory updates against frameworks/controls and
    create review tasks. Deterministic; returns {updates: n, tasks: n}."""
```

Per open update (or just `update_id`):

1. **Framework match** — case-insensitive exact match of
   `framework_name` against `frameworks.name`; if none,
   `difflib.get_close_matches(cutoff=0.6)` over all framework names
   (import difflib; the ERM Excel import at
   `modules/erm/data_service.py` ~1920 already uses this pattern —
   READ it and reuse the idiom). No match → mark the update
   `matched_count=0`, still `processed`, and create ONE generic task
   ("Review regulatory update: {title} — no matching framework found").
2. **Control match** — split `affected_refs` on commas, strip
   whitespace; for each ref,
   `SELECT id, ref, name FROM controls WHERE framework_id=%s AND lower(trim(ref))=lower(trim(%s))`.
   (READ the `controls` CREATE at database.py ~1400 first and confirm
   the name column — it is `name` there, not `title`.)
3. **Task creation** — one `task_board` row per matched control,
   idempotent: before inserting, check for an existing open task with
   the same composite title. Copy the `_task_exists` idempotency
   pattern from `modules/evidence/scheduler.py` (title-LIKE guard).
   Task fields: module='governance', entity_type='regulatory_update',
   entity_id=update id, title
   `"REGULATORY: Review {ref} against {framework_name} — {title}"`
   (truncate to the task title length limit — READ task_board's
   title column and the sanitizers in routes_platform.py:747),
   priority 'high' when update severity is 'high' else 'medium'.
4. **Optional AI summary** — only if `ai_summary` is NULL, the
   update matched at least one control, and the Anthropic key is
   configured (grep `config.py` for the exact settings attribute; copy
   the presence-check idiom from an existing AI call site). One call:
   "Summarize what changed and what a control owner should check", <=
   120 words, stored to `ai_summary`. Hard try/except — failure leaves
   NULL and continues.
5. Mark the update `status='processed'`, `matched_count`,
   `processed_at`. Commit once at the end of the whole run.

Route: POST `/api/regulatory-updates/run-drift`
(`governance.entities.manage`) calling `run_drift_check(db)` — the
"run now" button, and the thing that makes the feature usable on
tenants where the scheduler does not reach (see edge cases).

### Step 4 — Nightly hook

In `modules/evidence/scheduler.py`'s daily job, add the same guarded
block shape as PLAN-11 Step 4:

```python
    try:
        from modules.governance.data_service import run_drift_check
        res = run_drift_check(db)
        log.info("Drift check: %s updates, %s tasks", res["updates"], res["tasks"])
    except Exception as e:
        log.warning("Drift check failed: %s", e)
```

### Step 5 — Inbox tab UI

In `modules/governance/templates/index.html`, add a "Regulatory Inbox"
tab following the exact existing tab pattern (tab button, `tab-view`
div, loader function, add/edit modal):

- Table: Title, Framework, Severity chip, Effective date, Status chip,
  Matched (count), Actions (Edit / Dismiss / Delete for managers).
- Add/Edit modal fields: framework_name (free text with a datalist of
  existing framework names — fetch once from a small
  `GET /api/regulatory-frameworks` helper that returns
  `SELECT name FROM frameworks`, or reuse an existing frameworks list
  endpoint if one exists — grep first), title, summary, source_url,
  effective_date (date input), affected_refs (text, placeholder
  "A.5.1, A.8.12"), severity select.
- Toolbar: status filter + "Run drift check" button (managers only)
  that POSTs run-drift and toasts the returned counts.
- Detail row expansion or tooltip showing `ai_summary` when present.
- Update `get_governance_summary()` + the stat cards row with an
  "Open Reg. Updates" count.

### Step 6 — Tests + verify + commit

`tests/test_regulatory_drift.py`:
1. Create an update whose framework matches a seeded framework
   (`"ISO 27001:2022"` is always seeded — see `_EXPECTED_FRAMEWORKS`
   in database.py) with one `affected_refs` value matching a real
   seeded control ref (READ the controls seed to pick a real ref; if
   controls are seeded empty in tests, insert one control row
   directly). Run `run_drift_check` → 1 task created, update
   processed, matched_count 1.
2. Run again → 0 new tasks (idempotent), update stays processed.
3. Unmatchable framework name → generic task, matched_count 0.
4. Dismissed updates are never processed.
Cleanup: delete created updates + tasks.

Then `py_compile`, full pytest, live pass: create an inbox entry via
the tab → Run drift check → task appears on the Task Board with the
REGULATORY title → dismiss flow works. Commit:
`Add Regulatory Inbox and deterministic compliance drift detection`.

## Edge cases a weaker model would miss

- **The nightly scheduler only reaches the default tenant schema**
  (established platform limitation — see PLAN-09's identical note).
  The "Run drift check" button is therefore a first-class feature,
  not a debug tool: tenant admins trigger their own runs. Do not
  attempt cross-schema iteration.
- **Idempotency keys off the task TITLE** — if you truncate titles
  (Step 3), truncate BEFORE the existence check too, or every run
  creates duplicates whose full titles differ only past the cut.
- **`affected_refs` may be empty** — then the update produces the one
  generic framework-level task (when the framework matched), not
  zero output. An update with neither refs nor a framework match must
  still end `processed` so it doesn't re-run forever.
- **Two inbox entries citing the same control** must yield two tasks
  (different titles include different update titles) — the
  idempotency guard is per (update, ref), which the composite title
  encodes. Don't "deduplicate" across updates.
- **`controls.ref` values contain dots** (`A.5.1`) — never use LIKE
  matching on refs (dot-adjacent refs like A.5.1 vs A.5.12 would
  cross-match); the exact lower/trim equality in Step 2 is required.
- **`frameworks` here is the COMPLIANCE frameworks table** — not
  `erm_risk_frameworks` (rating frameworks). The Slice 1/2 naming
  warning applies; grep targets must be the launcher/ARIA `frameworks`
  table.
- **AI summary is per-update, once** — keyed on `ai_summary IS NULL`,
  so re-running drift never re-bills. Editing an update does NOT
  clear ai_summary; only a manager deleting/re-creating does.
- **Severity → priority mapping must go through the task board's
  accepted priority set** (`{"critical","high","medium","low"}` per
  routes_platform.py:752) — 'info' maps to 'medium', never pass
  'info' through.
- **The datalist of framework names is a hint, not validation** —
  admins may post updates for frameworks the tenant hasn't adopted
  yet; the matcher handles no-match gracefully by design.

## Acceptance criteria

1. All 4 tests pass; full suite green.
2. Live: inbox entry → run → REGULATORY task visible on the Task
   Board; second run creates nothing new.
3. Update with a bogus framework still ends processed with one
   generic task.
4. With no ANTHROPIC key configured, the run completes with
   `ai_summary` NULL and no exception in logs.
5. Governance summary cards show the open-updates count; tab CRUD
   round-trips (create, edit, dismiss, delete).
