# PLAN-09: Proactive AI Morning Briefing (governance advisories)

## Goal

Roadmap item T2.3, scoped to ship WITHOUT waiting for drift detection
(T2.2). Today every AI feature is user-triggered; the platform never
initiates. This plan adds a daily scheduled job that composes "three
things to know today" per tenant from signals that already exist in the
database — pure SQL first, AI narrative as an optional garnish — writes
them to a `governance_advisories` table, and surfaces them as a briefing
strip at the top of the Command Centre with acknowledge/dismiss.

Signals (all computable with existing data):

| Signal | Source |
|---|---|
| Predictive risk delta vs yesterday | `ai_risk_predictions` (last 2 rows) |
| Evidence expiring within 7 days | `evidence_items.expiry_date` |
| Overdue audits | `grid_audits` end_date in the past, not completed/locked |
| Appetite breaches | reuse `modules/erm/data_service.get_appetite_status()` |
| BCM exercise staleness > 180 days | `bcm_exercises` max date |
| Open critical/major non-conformances | `grid_non_conformances` |

This follows the platform's established "math, not AI" cost principle:
the scoring/selection is deterministic; `core/ai_client` is called at
most once per day per tenant, and only when at least one signal fires
AND an API key is configured.

## Exact files to touch

1. `oneforall/database.py` — `governance_advisories` table (BOTH
   `_SHARED_TABLES` and `_PLATFORM_TABLES`, same dual-block pattern as
   the T1.1 governance tables)
2. `oneforall/core/advisor.py` — new: signal collection + composition
3. `oneforall/modules/launcher/advisory_scheduler.py` — new: daily job
   (clone the structure of `modules/evidence/scheduler.py`)
4. `oneforall/main.py` — start/stop the scheduler in the same lifespan
   hooks where the other 4 schedulers are wired (grep
   `evidence_start` in main.py and mirror all touchpoints)
5. `oneforall/modules/launcher/routes_dashboard.py` — 2 endpoints
6. `oneforall/templates/command_centre.html` — briefing strip
7. `oneforall/tests/test_advisor.py` — new tests

## Step-by-step order

### Step 1 — Table

Add to BOTH `_SHARED_TABLES` and `_PLATFORM_TABLES` (SQLite dialect only;
`_to_pg_schema()` converts):

```sql
-- ── Governance Advisories (proactive daily briefing) ──────────────────────
CREATE TABLE IF NOT EXISTS governance_advisories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    briefing_date   TEXT NOT NULL,
    severity        TEXT DEFAULT 'info',
    signal_key      TEXT NOT NULL,
    title           TEXT NOT NULL,
    detail          TEXT,
    link            TEXT,
    ai_narrative    TEXT,
    acknowledged_by INTEGER,
    acknowledged_at TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(briefing_date, signal_key)
);
CREATE INDEX IF NOT EXISTS idx_advisories_date ON governance_advisories(briefing_date);
```

No FK on acknowledged_by (dual-block ordering convention — see the T1.1
lesson about cross-block REFERENCES).

### Step 2 — core/advisor.py

```python
def collect_signals(db) -> list[dict]:
```

Returns a list of `{signal_key, severity, title, detail, link, score}`.
One try/except per signal so a failing table never kills the briefing.
Signal implementations (verify every column name against database.py
CREATE statements before writing SQL — do NOT trust these sketches):

- `predictive_delta`: last two `ai_risk_predictions` rows ordered by id
  DESC; if latest minus previous >= 5 (percentage points), severity
  `high`, link `/`.
- `evidence_expiring`: COUNT of `evidence_items` with `expiry_date`
  between today and +7 days, `status='current'`; severity `medium`, link
  `/evidence/`.
- `overdue_audits`: COUNT of grid_audits past end_date and not
  completed — READ the actual status values used (`grep "status" in the
  grid_audits CREATE + grid data_service`) instead of guessing; link `/grid/`.
- `appetite_breach`: call
  `modules.erm.data_service.get_appetite_status()` (import inside the
  function to avoid circulars) and count entries it flags as breached —
  READ its return shape first; severity `high`, link `/erm/`.
- `bcm_stale`: max(bcm_exercises date column) older than 180 days (or no
  rows at all); severity `medium`, link `/bcm/`.
- `open_critical_ncs`: COUNT grid_non_conformances severity in
  ('critical','major') AND status not closed (verify real enums);
  severity `high`, link `/grid/`.

`score` = {high:3, medium:2, info:1} for ranking.

```python
def compose_briefing(db, today: str) -> int:
```

- If `SELECT COUNT(*) FROM governance_advisories WHERE briefing_date=%s`
  > 0 → return 0 (idempotent; one briefing per day).
- Collect signals, keep those that fired, sort by score DESC, take top 3.
- Optional narrative: only if at least one signal fired AND
  `settings.ANTHROPIC_API_KEY` (grep `config.py` for the exact attribute
  name) is set — one `core/ai_client` call summarizing the three items in
  <= 80 words; on ANY exception, proceed with `ai_narrative = None`.
- INSERT rows (the UNIQUE constraint makes concurrent double-runs safe;
  use the codebase's ON CONFLICT DO NOTHING idiom).
- For `today` use the same date-string convention as the rest of the
  codebase: `utcnow().strftime("%Y-%m-%d")` via `core.timeutils`.

### Step 3 — Scheduler

`modules/launcher/advisory_scheduler.py`: copy the skeleton of
`modules/evidence/scheduler.py` exactly (BackgroundScheduler, CronTrigger,
`get_db_background`, `start_scheduler` / `stop_scheduler` functions,
module-level `_scheduler` guard). Cron: daily 05:30 UTC (before the
evidence job at 09:00). The job body: open db, call
`compose_briefing(db, today)`, log the count, close db in `finally`.

Wire into `main.py` exactly like the evidence scheduler: there are TWO
touchpoints (startup around line ~191, shutdown around line ~254) — grep
`evidence_start` and `evidence_stop` and mirror both, wrapped in the same
try/except style.

### Step 4 — Endpoints

In `routes_dashboard.py`:

- `GET /api/advisories/today` (`@require_auth` equivalent used by
  neighboring endpoints — copy their decorator): rows for today's
  briefing_date, unacknowledged first. Also, if NO rows exist for today
  yet (server started after 05:30, or first install), call
  `compose_briefing` inline once — lazily self-healing, and the UNIQUE
  key keeps it idempotent.
- `POST /api/advisories/{aid}/ack`: set acknowledged_by = current user,
  acknowledged_at = now; 404 if missing.

### Step 5 — Command Centre strip

In `command_centre.html`: a dismissible "Today's briefing" card ABOVE the
stat tiles: severity dot, title, detail, "Open" link (each advisory's
`link`), Acknowledge button per item. Fetch on load; hide the card
entirely when the API returns zero rows or all rows acknowledged. Match
the existing stat-card CSS classes; render via the page's existing esc()
helper (grep for one; add if absent).

### Step 6 — Tests + verify

`tests/test_advisor.py`:
1. Seed one expiring evidence item; `collect_signals` includes
   `evidence_expiring`.
2. `compose_briefing` twice for the same date → second call returns 0
   and row count unchanged.
3. Signals never raise: drop/rename nothing — instead call
   `collect_signals` against the intact schema and assert it returns a
   list (the per-signal try/except is exercised naturally in dev where
   ai_risk_predictions may be empty).
Cleanup all inserted rows.

Live: start app, hit `GET /api/advisories/today` (triggers lazy compose),
open Command Centre, see the strip, acknowledge one item, reload — it
stays acknowledged. Commit:
`Add proactive daily governance briefing (advisories engine + Command Centre strip)`.

## Edge cases a weaker model would miss

- **Schedulers only serve the DEFAULT tenant schema.** `get_db_background`
  binds to the default search_path; every existing scheduler (evidence,
  grid, sentinel, bcm) has this same limitation. Do NOT attempt to
  iterate tenant schemas in this plan — that is a platform-wide change.
  The lazy compose in `GET /api/advisories/today` is what makes
  multi-tenant work correctly TODAY: it runs inside a real request whose
  `get_db()` carries the caller's tenant schema, so each tenant
  self-composes on first dashboard load of the day. This is the designed
  behavior, not a fallback — say so in code comments.
- **The 05:30 job and a 05:31 dashboard load can race** — both may call
  compose_briefing for the same date. The `UNIQUE(briefing_date,
  signal_key)` + ON CONFLICT DO NOTHING makes the second writer a no-op.
  Do not "optimize away" the constraint.
- **AI call budget:** narrative is once per briefing (per tenant per
  day), never per signal, never on ack/read paths. If the AI call takes
  >20s or raises, the briefing still lands without narrative — wrap with
  a hard try/except, no retries.
- **Empty-database day one:** zero signals fire → zero rows → the
  Command Centre hides the card. `compose_briefing` must still return 0
  without inserting a placeholder row — otherwise the UNIQUE key blocks
  real signals appearing later the same day. (This is why idempotency
  checks COUNT for the date only after signal collection finds
  something: order the check as written in Step 2.)
  CORRECTION — keep the early-exit COUNT check FIRST as written, but
  only INSERT when signals fired; a day with zero signals inserts
  nothing and later dashboard loads re-attempt compose. Implement
  exactly that: early COUNT check, then collect, then insert-if-any.
- **`get_appetite_status()` opens its own db connection** — do not pass
  it your open `db`; call it as-is and tolerate its exceptions.
- **Date boundaries:** briefing_date is UTC. A user in UTC+2 at 01:00
  local sees "yesterday's" briefing — acceptable; do not add timezone
  logic.
- **Severity strings drive UI colors** — validate to the fixed set
  {'high','medium','info'} at insert time so the frontend map never
  misses.

## Acceptance criteria

1. Fresh DB + one expiring evidence item: first dashboard load creates
   advisories; the strip renders; ack persists across reload.
2. `compose_briefing` is idempotent per date (test 2 passes).
3. With no ANTHROPIC_API_KEY set, briefings still generate (ai_narrative
   NULL) and no AI call is attempted (assert via log or by the key check
   short-circuiting).
4. Scheduler starts and stops cleanly: app startup logs the new job,
   shutdown does not hang.
5. Full pytest suite green; py_compile clean on all touched files.
