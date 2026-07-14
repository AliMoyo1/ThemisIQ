# PLAN-11: Governance Graph T1.3 — Control Effectiveness Engine

## PREREQUISITE — do not start until PLAN-05 (T1.2) is implemented

This plan reads `canonical_controls`, `risk_controls`, and the
`canonical_control_id` columns that PLAN-05 creates. If
`grep -n "canonical_controls" oneforall/database.py` returns nothing,
STOP and execute PLAN-05 first.

## Goal

Roadmap T1.3 (approved: "Tier 1 in full"). Today every effectiveness
value in the platform is manually typed and never reacts to reality.
This plan makes control effectiveness a **derived, living score
(0-100)** per canonical control, recomputed automatically from seven
deterministic factors when audits complete, incidents occur, evidence
expires, or nightly. No manual editing of the score — it is computed,
not entered. This is the roadmap's self-described "single
highest-leverage delivery" because T1.4 (residual risk) and T3.4
(health score) both consume it.

Factor model (weights configurable per tenant, defaults from the
approved spec):

| Factor | Default weight | Deterministic source |
|---|---|---|
| evidence_uploaded | 20 | any evidence linked to the control's module rows |
| evidence_valid | 15 | fraction of linked evidence not expired |
| audit_passed | 20 | no OPEN critical/major NC in audits containing the control |
| tested_recently | 15 | `last_tested_at` within `test_frequency_days` |
| owner_reviewed | 10 | owner assigned AND control row updated in last 180 days |
| automated | 10 | automation field: automated=full, semi=half |
| no_recent_incidents | 10 | no ORM events in 30d on risks this control mitigates |

## Exact files to touch

1. `oneforall/database.py` — 1 new table (`_ERM_ORM_TABLES`, end)
2. `oneforall/core/effectiveness.py` — NEW: the engine (pure logic + db)
3. `oneforall/core/event_handlers.py` — 2 recompute triggers
4. `oneforall/modules/evidence/scheduler.py` — nightly recompute hook
5. `oneforall/modules/governance/data_service.py` +
   `modules/governance/templates/index.html` — show the score in the
   Controls tab (PLAN-05 built this tab)
6. `oneforall/modules/erm/data_service.py` — include effectiveness in
   `list_risk_controls()` output (PLAN-05 built this function)
7. `oneforall/tests/test_effectiveness_engine.py` — new tests

## Step-by-step order

### Step 1 — Table

At the END of `_ERM_ORM_TABLES` in database.py (after PLAN-05's
`risk_controls`), add (SQLite dialect only — `_to_pg_schema()` converts):

```sql
-- ── Control Effectiveness scores (T1.3) — append-only history ─────────────
CREATE TABLE IF NOT EXISTS control_effectiveness_scores (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    control_id          INTEGER NOT NULL,
    evidence_uploaded   REAL DEFAULT 0,
    evidence_valid      REAL DEFAULT 0,
    audit_passed        REAL DEFAULT 0,
    tested_recently     REAL DEFAULT 0,
    owner_reviewed      REAL DEFAULT 0,
    automated           REAL DEFAULT 0,
    no_recent_incidents REAL DEFAULT 0,
    score               REAL NOT NULL,
    computed_at         TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ces_control ON control_effectiveness_scores(control_id, computed_at DESC);
```

Append-only on purpose: history powers T2.3's "effectiveness dropped
>= 10%" signal. No FK on control_id (cross-block convention). Latest
row per control = current score.

### Step 2 — The engine (`core/effectiveness.py`)

```python
"""Control Effectiveness Engine (T1.3): derives a 0-100 score per
canonical control from seven deterministic factors. Scores are
computed, never hand-edited."""
```

**`get_weights(db) -> dict`** — read the `settings` table key
`ce_weights` (JSON). Parse with try/except; if missing, unparsable, or
the values do not sum to 100, return the default dict
`{"evidence_uploaded": 20, "evidence_valid": 15, "audit_passed": 20,
"tested_recently": 15, "owner_reviewed": 10, "automated": 10,
"no_recent_incidents": 10}`.

**`compute_factors(db, control_id) -> dict`** — one sub-query per
factor, each returning a fraction 0.0-1.0, each wrapped in its own
try/except returning 0.0 on error (a broken factor must never kill the
engine). Before writing each query, READ the real schema:

- Resolve the control's module rows first:
  `SELECT id FROM aria_controls WHERE canonical_control_id=%s` and the
  same for `grid_controls` — these lists drive factors 1-3.
- *evidence_uploaded*: 1.0 if any `evidence_links` row matches one of
  those module rows. READ existing evidence_links INSERT call sites
  (grep `evidence_links` in `modules/`) to learn the exact
  `(module, entity_type)` string pairs used for controls — do not
  guess them.
- *evidence_valid*: over the linked evidence ids, fraction with
  `expiry_date IS NULL OR expiry_date >= <today>` and
  `status='current'`. Zero linked evidence → 0.0 (not 1.0 — absence of
  evidence is not validity).
- *audit_passed*: find audits containing the control's grid rows
  (`grid_controls.audit_id`), then 0.0 if any
  `grid_non_conformances` row on those audits has severity in the
  critical/major set AND an open status — READ the actual enum
  strings used (grep `_NC_STATUSES` / severity values in
  grid/data_service.py) rather than assuming. No grid rows at all →
  0.5 (unaudited ≠ failed; document this constant).
- *tested_recently*: `canonical_controls.last_tested_at` within
  `test_frequency_days` (NULL frequency → 90). NULL last_tested_at → 0.0.
- *owner_reviewed*: `owner_user_id IS NOT NULL` AND `updated_at`
  within 180 days → 1.0, owner set but stale → 0.5, no owner → 0.0.
- *automated*: automation == 'automated' → 1.0, 'semi' → 0.5, else 0.0.
- *no_recent_incidents*: risks linked via `risk_controls` →
  `orm_events` with `erm_risk_id` in that set, created in last 30
  days, severity critical/major (READ orm_events severity values) →
  any found = 0.0 else 1.0. No linked risks → 1.0.

**`compute_control_effectiveness(db, control_id) -> float`** —
factors × weights, sum, round to 1dp, INSERT one history row, return
the score. Does NOT commit (caller commits).

**`recompute_for_controls(db, control_ids) -> int`** — loop + commit
once. **`recompute_all(db) -> int`** — all active canonical control
ids, then delete history older than 90 days
(`DELETE FROM control_effectiveness_scores WHERE computed_at < ...`
using the codebase's `sql_date_offset` helper).

**`get_current_scores(db, control_ids=None) -> dict`** — latest row
per control via
`SELECT ... WHERE id IN (SELECT MAX(id) FROM control_effectiveness_scores GROUP BY control_id)`
(MAX(id) is safe because the table is append-only).

**`residual_hook(db, control_id)`** — module-level no-op function with
a docstring saying PLAN-12 replaces its body. Call it at the end of
`compute_control_effectiveness`. This is the T1.4 integration seam.

### Step 3 — Event triggers

In `core/event_handlers.py`, following the existing `@on(...)` handler
style exactly (imports at top, try/except inside, background db):

- `@on(<the GRID audit-completed constant>)` — READ `core/events.py`
  for the exact constant name — resolve the audit's grid_controls'
  canonical ids and `recompute_for_controls`.
- `@on(<the ORM event-logged constant>)` — if the payload/entity has
  an `erm_risk_id`, find that risk's controls via `risk_controls` and
  recompute them.

Both handlers: import `core.effectiveness` inside the function body
(avoids import cycles at module load — match how other handlers do
cross-module imports; verify by reading two existing handlers).

### Step 4 — Nightly recompute

In `modules/evidence/scheduler.py`, at the end of the existing daily
job function, add a guarded block:

```python
    try:
        from core.effectiveness import recompute_all
        n = recompute_all(db)
        log.info("Effectiveness recompute: %s controls", n)
    except Exception as e:
        log.warning("Effectiveness recompute failed: %s", e)
```

(The evidence job is the natural home: evidence expiry is the factor
that decays daily.) Confirm the job's `db` is still open at that point
by reading the function's structure first; if it closes earlier, open
a fresh `get_db_background()` in the block.

### Step 5 — Surface the score

- Governance Controls tab (PLAN-05): `list_canonical_controls()` gains
  a per-row `effectiveness` value via `get_current_scores()`; the
  table gets an "Effectiveness" column rendering `—` when no score yet,
  else a colored percent (>=80 green, 50-79 amber, <50 red — reuse the
  badge classes PLAN-05's tab already has).
- ERM drawer: `list_risk_controls()` includes each control's current
  score; the Linked Controls section shows it next to each name.

### Step 6 — Tests + verify + commit

`tests/test_effectiveness_engine.py`:
1. Weights fallback: garbage JSON in settings → defaults returned.
2. Full-marks scenario: insert a canonical control (automated,
   owner set, tested today), linked evidence (no expiry), no NCs, no
   incidents → score == 100.0 minus the audit_passed half-credit if no
   grid rows (compute the exact expected value BY HAND from your
   factor implementation and pin it — e.g. unaudited gives
   audit_passed 0.5 → 90.0).
3. Decay scenario: same control with the evidence expired → score
   drops by exactly the evidence_valid weight (15).
4. History: two computes → two rows; `get_current_scores` returns the
   newer.
Cleanup all rows.

Then `py_compile` all touched files, full pytest, live browser pass
(Controls tab shows percentages; expire an evidence item's date via
the vault UI, run the recompute manually in a shell, reload → score
dropped). Commit:
`Add Control Effectiveness Engine (T1.3): derived scores, event triggers, nightly recompute`.

## Edge cases a weaker model would miss

- **Half-credit constants (unaudited 0.5, stale owner 0.5) must be
  named module constants with comments** — auditors will ask where
  numbers come from; magic literals inside SQL loops are unacceptable
  in a GRC product.
- **`MAX(id) GROUP BY control_id` is only correct because the table is
  append-only** — if someone later adds UPDATE paths, latest-by-id
  breaks. State this in the table's SQL comment (already included in
  Step 1's DDL comment).
- **Event handlers run synchronously on emit** (core/events.py) — a
  slow recompute inside a handler blocks the user's save. Keep the
  per-control recompute O(few queries); never call `recompute_all`
  from a handler.
- **Import cycles**: `core/event_handlers.py` importing
  `core.effectiveness` at module top can cycle through database/event
  imports. Import inside the handler function body (Step 3).
- **A control with zero graph connections still gets a score**
  (automated/owner/tested factors are intrinsic). That is correct —
  do not skip unlinked controls in `recompute_all`.
- **Fractions vs points:** `compute_factors` returns 0.0-1.0 per
  factor; the weight multiplication happens ONCE in
  `compute_control_effectiveness`. Do not bake weights into factors
  or tenant weight changes will silently not apply.
- **The history prune must not delete each control's latest row** —
  prune with
  `AND id NOT IN (SELECT MAX(id) FROM control_effectiveness_scores GROUP BY control_id)`.
- **`settings` table is per-tenant** (it is in `_PLATFORM_TABLES`), so
  per-tenant weights work automatically through `get_db()` — do not
  build a separate weights table.

## Acceptance criteria

1. All 4 tests pass with hand-pinned expected scores; full suite green.
2. Live: expiring linked evidence measurably lowers the control's
   score after recompute; completing the manual recompute path logs a
   count.
3. Governance Controls tab and ERM Linked Controls both display live
   percentages.
4. `grep -n "residual_hook" oneforall/core/effectiveness.py` shows the
   PLAN-12 seam exists and is called.
5. Event handler smoke: logging an ORM event against a linked risk
   creates a new history row for that control.
