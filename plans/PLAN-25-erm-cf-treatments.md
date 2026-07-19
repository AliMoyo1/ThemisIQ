# PLAN-25: ERM Per-CF Treatments (TR numbers, Exploit, EMV-a, Accept rule)

## Status: OPEN (requires PLAN-23; PLAN-24 strongly recommended first)

## Goal

One treatment record per contributing factor, per the mind map: auto-assigned
treatment numbers (TR001 pairs with CF001), five treatment options including
Exploit, the Accept auto-suggestion rule (CF assurance >= 70%), EMV-a
(money required to apply the treatment), treatment owner, due date, and
interdependencies. The legacy risk-level `treatment` / `treatment_plan`
columns stay untouched as a summary fallback.

## Files to touch (exact)

1. `oneforall/database.py` (one table)
2. `oneforall/modules/erm/data_service.py`
3. `oneforall/modules/erm/routes.py`
4. `oneforall/modules/erm/templates/index.html`
5. `oneforall/tests/test_erm_treatments.py` (NEW)
6. `plans/README.md`

## Step-by-step order

### Step 0: create `plans/PLAN-25-active.md`; log every change as you go.

### Step 1: database.py - table

Append inside `_ERM_ORM_TABLES` directly after the
`erm_contributing_factors` table added by PLAN-23:

```sql
-- ── ERM v2: Per-CF risk treatments ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS erm_cf_treatments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id           INTEGER NOT NULL REFERENCES erm_enterprise_risks(id) ON DELETE CASCADE,
    cf_id             INTEGER NOT NULL REFERENCES erm_contributing_factors(id) ON DELETE CASCADE,
    tr_ref            TEXT NOT NULL,
    treatment_option  TEXT DEFAULT 'mitigate',
    action_steps      TEXT,
    emv_a             REAL,
    owner_id          INTEGER REFERENCES users(id),
    due_date          TEXT,
    status            TEXT DEFAULT 'open',
    interdependencies TEXT,
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now')),
    UNIQUE(cf_id)
);
CREATE INDEX IF NOT EXISTS idx_erm_cf_treat_risk ON erm_cf_treatments(risk_id);
```

Valid treatment_option values (app-level, no CHECK constraint per codebase
convention): mitigate, accept, avoid, transfer, exploit.
Valid status values: open, in_progress, complete.

### Step 2: data_service.py - treatment functions

a) `_cf_assurance(db, cf_id)`: average ice_score over
`risk_controls WHERE cf_id=%s AND ice_score IS NOT NULL`; returns
rounded int or None when no scored control.

b) `ensure_treatments_for_risk(db, risk_id)`: for every CF of the risk
without a treatment row, INSERT one with:
- tr_ref: 'TR' + the same 3-digit numeric suffix as the CF's cf_ref
  (CF002 gets TR002). If the cf_ref suffix cannot be parsed, fall back to
  `_next_ref` over the risk's tr_refs.
- treatment_option: 'accept' when `_cf_assurance` >= 70, else 'mitigate'.
- status 'open'. Does not commit (caller commits).

c) `list_treatments(risk_id)`: opens its own connection, calls
ensure_treatments_for_risk, commits, then returns treatments joined with
cf_ref + cf description + owner full_name + cf_assurance + a computed
`suggested_option` field ('accept' when assurance >= 70 else 'mitigate')
and `overdue` boolean (due_date < today and status != 'complete').

d) `update_treatment(treatment_id, data)`: writable fields exactly
treatment_option, action_steps, emv_a, owner_id, due_date, status,
interdependencies. Validate treatment_option and status against the value
lists (raise ValueError). emv_a: None or float >= 0. Sets updated_at.
Returns a dict including `warning` set to
"Accept selected while CF assurance is below 70%" when the caller sets
treatment_option accept and `_cf_assurance` is None or < 70; empty
otherwise.

e) `get_risk_emv_a_total(db, risk_id)`: SUM(emv_a) over the risk's
treatments, None-safe. Attach `emv_a_total` in `get_enterprise_risk`.

### Step 3: routes.py - endpoints

- `GET /api/risks/{risk_id}/treatments` (erm.risk.view): list_treatments;
  404 when risk missing.
- `PUT /api/treatments/{treatment_id}` (erm.risk.manage): body passthrough
  to update_treatment; ValueError maps to 400; response includes warning.

No POST and no DELETE: rows are auto-created per CF and die with their CF
(cascade). Document this in the endpoint docstrings.

### Step 4: UI - drawer Treatment section

In the risk drawer (index.html, after the Assessment section from
PLAN-24): a "Treatment" section that fetches
`/erm/api/risks/{id}/treatments` and renders one card per row:

- Header: tr_ref chip + cf_ref + CF description (esc()).
- Option select (5 options, capitalised labels) with the suggestion badge:
  when suggested_option is 'accept' and current option differs, show
  "Suggested: Accept (assurance {cf_assurance}%)".
- Textarea action_steps; number input emv_a (min 0, label
  "EMV-a: treatment cost (USD)"); owner select (reuse the users list the
  drawer already loads or fetch `/erm/api/users`); date input due_date
  (red "OVERDUE" chip when overdue); status select; text input
  interdependencies.
- A single Save button per card doing the PUT, then toast; when the
  response carries a warning, show it as a warning toast.
- Below the cards a footer line: "EMV-a total: {sum}" and the appetite
  status for the risk's category taken from the already-loaded appetite
  data if present in the drawer scope, otherwise fetch
  `/erm/api/appetite/status` and match on category (silent skip on
  failure).

Register table: nothing. Dashboard EMV-a total ships in PLAN-26.

### Step 5: tests - `oneforall/tests/test_erm_treatments.py`

Using test_db fixture and direct data_service calls:

1. risk with CF001 + CF002: ensure_treatments creates TR001 + TR002, both
   status open, option mitigate when no ICE anywhere.
2. CF with avg ICE 70 (single control at 70): ensured treatment option is
   accept; CF at 60 stays mitigate.
3. tr_ref pairing survives CF deletion: delete CF001 (via
   _save_contributing_factors omission), its treatment row is gone
   (cascade or explicit), CF002's treatment still TR002; a new CF003 gets
   TR003.
4. update_treatment rejects option 'ignore' and status 'done' with
   ValueError; accepts exploit.
5. accept-below-70 warning returned; accept-at-70 no warning.
6. emv_a sums into get_enterprise_risk emv_a_total; negative emv_a
   rejected.
7. list_treatments is idempotent (second call creates no duplicates;
   UNIQUE(cf_id) also guards this).

### Step 6: verify

- py_compile + full pytest.
- Live browser: on the PLAN-24 test risk shape (2 CFs, ICE 70/90), open
  Treatment section: two cards, CF001 card suggests Accept; set option
  exploit + EMV-a 20000 + due date yesterday: OVERDUE chip appears and
  EMV-a total reads $20,000. Clean up the test risk.
- Update plans/README.md. One focused commit.

## Edge cases a weaker model would miss

- SQLite databases created BEFORE this plan get the table via CREATE TABLE
  IF NOT EXISTS on startup (it is inside _ERM_ORM_TABLES which runs every
  init); PG tenants get it through the same shared schema block. No
  _COLUMN_MIGRATIONS entry is needed for a brand-new table.
- The ON DELETE CASCADE on cf_id only fires when SQLite foreign_keys
  pragma is on; this codebase enables it in get_db, but
  _save_contributing_factors (PLAN-23) deletes CFs explicitly, so ALSO add
  an explicit `DELETE FROM erm_cf_treatments WHERE cf_id=%s` there when
  this plan lands (defensive double-delete is idempotent).
- delete_enterprise_risk: add explicit
  `DELETE FROM erm_cf_treatments WHERE risk_id=%s` alongside the other
  cleanup statements.
- Assurance None (no scored controls) must suggest mitigate, not accept,
  and must not crash the >= 70 comparison (None comparison TypeError).
- ensure_treatments must never overwrite an existing row's option: the
  suggestion is only applied at row creation; afterwards it is display
  metadata (suggested_option field). A user's explicit choice always
  survives recomputes.
- emv_a of 0 is valid (treatment costs nothing); only negative is
  rejected. Strict None checks again.
- due_date string comparison: compare ISO date strings, consistent with
  the codebase's other date comparisons (no datetime parsing).
- ValueError from update_treatment must not leave a half-applied UPDATE:
  validate everything BEFORE executing SQL.
- Appetite math is not touched in this plan: the strip DISPLAYS the
  category's appetite status from the existing endpoint. The decision
  (2026-07-18) is that appetite compares RESIDUAL exposure via
  COALESCE(rrr, likelihood*impact); that change ships as PLAN-26
  Step 1b. If PLAN-26 has already landed, the strip reflects residual
  automatically since it reads the same endpoint; either way, build
  nothing appetite-related here.
- The existing AI suggest-treatment endpoint keeps writing the legacy
  risk-level treatment/treatment_plan fields; that remains the risk-level
  summary. Do not point it at per-CF treatments in this plan.
- No task_board tasks or email reminders are created for due/overdue
  treatments in this slice; the OVERDUE chip is UI-only. The platform has
  the event-bus plus scheduler infrastructure for this later; note it as
  a follow-up, do not build it here.
- Interdependencies is narrative TEXT. Entity-to-entity linking already
  exists platform-wide via cross_module_links and the Related Items
  drawer section (PLAN-07, shipped); do not build a second linking
  mechanism inside treatments.

## Acceptance criteria

- [ ] All 7 test cases pass; suite green; py_compile clean.
- [ ] TR refs pair with CF refs and survive CF deletions per test 3.
- [ ] Live browser script in Step 6 verified with a screenshot-worthy
      drawer (two cards, suggestion badge, overdue chip, EMV-a total).
- [ ] No POST/DELETE treatment endpoints exist.
- [ ] Legacy treatment/treatment_plan columns unchanged and still visible
      wherever they were before.
