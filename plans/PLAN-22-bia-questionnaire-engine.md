# PLAN-22: BIA questionnaire engine in BCM

## Goal

Digitize "BIA Questionnaire.xlsx" (ISO 22301-style) on top of the
existing thin `bcm_bia_records` table (database.py:2158 — currently just
RTO/RPO plus three 1-5 impact integers). Verified questionnaire
structure:

- **Part 1**: activity/general info (org, activity name, responsible
  person, key tasks, legal/contractual obligations, deadlines), then TWO
  impact-over-time grids scored at 2h / 4h / 24h / 48h / 1 week:
  - General impact rows (scored 1-3: marginal / acceptable / high):
    reputation loss, client reactions, impact on other activities,
    health+safety/environment, backlog difficulty.
  - Financial impact rows (money amounts): legal penalties, contractual
    penalties, revenue loss from potential clients, revenue loss from
    existing clients, additional expenses.
- **Part 2**: workload (peak periods, peak volume, minimum acceptable
  level post-disaster, resume-by period) and recovery resources by
  category (people, applications/databases, electronic data, paper
  data, IT/communications equipment, communication channels, other) —
  each resource with specifics, amount, single-point-of-failure flag,
  and needed-after bucket (immediately / 1h / 4h / 24h / 2d / 1wk).

Design decisions honoring "not locked in":
- **Impact ROW LABELS and RESOURCE CATEGORIES are data** — seeded
  defaults, per-record addable rows, so orgs adapt the questionnaire
  without deploys.
- **Time buckets stay fixed at five generic columns** (b1..b5) with
  LABELS stored per tenant in the `settings` table
  (`bia.bucket_labels`, default `["2 hours","4 hours","24 hours",
  "48 hours","1 week"]`) — renameable without schema churn.
- **RTO suggestion, not dictation**: the earliest bucket where any
  general-impact row scores 3 (high) becomes the SUGGESTED RTO; the
  user confirms or overrides the existing `rto_hours` field.
- SBU/graph aware: `business_unit_id` + optional link to a
  `business_processes` row (T1.1) on the BIA record.

## Exact files to touch

1. `oneforall/database.py` — 2 child tables + column migrations on
   `bcm_bia_records`
2. `oneforall/modules/bcm/data_service.py` — extended BIA CRUD +
   RTO suggestion
3. `oneforall/modules/bcm/routes.py` — extend existing BIA endpoints
   (READ them first; BCM has a BIA CRUD already)
4. `oneforall/modules/bcm/templates/index.html` — tabbed BIA editor
5. `oneforall/tests/test_bia_questionnaire.py`

## Step-by-step order

### Step 1 — Schema

Column migrations (`_COLUMN_MIGRATIONS`):

```python
        # ── BIA questionnaire (ISO 22301) ──────────────────────────────────────
        ("bcm_bia_records", "key_tasks",            "TEXT"),
        ("bcm_bia_records", "obligations",          "TEXT"),
        ("bcm_bia_records", "deadlines",            "TEXT"),
        ("bcm_bia_records", "peak_periods",         "TEXT"),
        ("bcm_bia_records", "peak_workload",        "TEXT"),
        ("bcm_bia_records", "min_acceptable_level", "TEXT"),
        ("bcm_bia_records", "resume_period",        "TEXT"),
        ("bcm_bia_records", "suggested_rto_hours",  "INTEGER"),
        ("bcm_bia_records", "business_process_id",  "INTEGER"),
]
```

(`business_unit_id` on this table already exists from T1.1's migration
list — verify, do not duplicate.)

New tables at the end of `_BCM_TABLES`:

```sql
CREATE TABLE IF NOT EXISTS bcm_bia_impact_rows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bia_id      INTEGER NOT NULL REFERENCES bcm_bia_records(id) ON DELETE CASCADE,
    section     TEXT NOT NULL,
    label       TEXT NOT NULL,
    description TEXT,
    b1 REAL, b2 REAL, b3 REAL, b4 REAL, b5 REAL,
    order_idx   INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_bia_impact_rows ON bcm_bia_impact_rows(bia_id);
CREATE TABLE IF NOT EXISTS bcm_bia_resources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bia_id      INTEGER NOT NULL REFERENCES bcm_bia_records(id) ON DELETE CASCADE,
    category    TEXT NOT NULL,
    name        TEXT NOT NULL,
    specifics   TEXT,
    amount      TEXT,
    single_point_of_failure INTEGER DEFAULT 0,
    needed_after TEXT DEFAULT 'immediately',
    notes       TEXT,
    order_idx   INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_bia_resources ON bcm_bia_resources(bia_id);
```

`section` ∈ {'general','financial'}; general rows hold scores 1-3 in
b1..b5, financial rows hold money amounts — same columns, different
semantics, disambiguated by section. `needed_after` validated against
{'immediately','1h','4h','24h','2d','1w','other'}.

### Step 2 — Default row templates

Module-level constants in `bcm/data_service.py` (used when creating a
NEW BIA — they become editable rows, not fixed schema):

```python
_BIA_GENERAL_ROWS = ["Loss of reputation on the market", "Clients' reactions",
    "Impact on other activities", "Health, safety and environmental impacts",
    "Difficulty catching up on backlog"]
_BIA_FINANCIAL_ROWS = ["Legal penalties", "Contractual penalties",
    "Loss of revenue from potential clients", "Loss of revenue from existing clients",
    "Additional expenses (repairs, maintenance, etc.)"]
_BIA_RESOURCE_CATEGORIES = ["People", "Applications / databases",
    "Electronic data (outside applications)", "Paper data",
    "IT and communications equipment", "Communication channels", "Other equipment"]
```

### Step 3 — Data service

READ the existing BIA functions in `bcm/data_service.py` first (create/
update/get/list/delete). Then:

- `create_bia(...)`: after inserting the record, bulk-insert the 10
  default impact rows (5 general + 5 financial, order_idx sequential).
- `get_bia(id)`: attach `impact_rows` (ordered) and `resources`
  (grouped by category client-side; return flat ordered list) and the
  bucket labels (`_get_bucket_labels(db)` reading the settings key with
  the default fallback).
- Row CRUD: `save_bia_impact_rows(db_or_id, bia_id, rows)` —
  delete-and-reinsert (rows carry no history), validating section and
  clamping general-section scores to 0-3.
  `add/update/delete_bia_resource(...)` — per-row CRUD (resources are
  many; full reinsert would be wasteful and lose ids mid-edit).
- `suggest_rto(rows, bucket_hours=[2,4,24,48,168]) -> int|None`: first
  bucket index where ANY general row's score >= 3 → its hours; None if
  never. Store into `suggested_rto_hours` on every impact-row save; do
  NOT touch `rto_hours` (user-owned).
- `delete_bia`: explicit child deletes (match the module's existing
  explicit-delete convention rather than relying on cascades).

### Step 4 — Endpoints

Extend the existing BIA endpoints (same file, same capability
`bcm.bia.manage`): the GET detail now returns children + bucket labels;
add `PUT /api/bia/{id}/impact-rows` (full row list),
`POST/PUT/DELETE /api/bia/{id}/resources[/{rid}]`, and
`GET/PUT /api/bia/bucket-labels` (PUT gated `bcm.bia.manage`, writes
the settings key after validating exactly 5 non-empty labels).

### Step 5 — UI

The BCM SPA's BIA editor becomes tabbed (follow the module's existing
tab pattern — grep how another BCM page does tabs):

- **Details** — existing fields + the new Part-1/Part-2 text fields +
  business process dropdown (from `/governance/api/business-processes`)
  + RTO field with a "Suggested: Nh" hint chip beside it (click to
  apply) when `suggested_rto_hours` is set.
- **Impact over time** — two grids (General 1-3 selects; Financial
  number inputs) with bucket labels as column headers, add-row and
  delete-row controls, description per row. Legend: "1 marginal ·
  2 acceptable · 3 high".
- **Recovery resources** — grouped by category with add-resource rows
  (category select from the constants + free "Other"), SPOF checkbox,
  needed-after select.

Save actions call the respective endpoints; the suggested-RTO chip
refreshes after impact-row save from the PUT response.

### Step 6 — Tests + verify

`tests/test_bia_questionnaire.py`:
1. create_bia seeds exactly 10 default impact rows.
2. `suggest_rto`: scores [1,2,2,2,2] on a row → None; a row with b3=3
   → 24; two rows where the earliest 3 is b1 → 2.
3. Resource CRUD round-trip + SPOF flag persists.
4. delete_bia removes children.
5. Bucket labels: invalid PUT (4 labels) rejected; custom labels
   returned by get_bia.
Live pass: full questionnaire entry in the UI, suggested RTO appears
after scoring a 3, apply-chip copies it into RTO. Cleanup.

## Edge cases a weaker model would miss

- **General vs financial rows share columns with different meanings** —
  the UI must render selects for general and number inputs for
  financial; server-side clamp applies ONLY to section='general'
  (clamping a $50,000 financial figure to 3 destroys data).
- **The 1-3 scale is the questionnaire's own** (marginal/acceptable/
  high) — do not "upgrade" it to 1-5 for consistency with risk scores;
  the RTO suggestion threshold (>=3) depends on it.
- **suggested_rto vs rto_hours separation is the feature** — the
  system never writes the user's RTO. Overwriting it turns a
  suggestion into silent data loss on every grid edit.
- **1 week = 168 hours** in the bucket-hours map (not 40, not 120).
- **Existing BIA rows predate the children** — get_bia must not assume
  rows exist; the editor shows an "Add standard rows" button when a
  legacy BIA has zero impact rows (calls a small endpoint that inserts
  the defaults idempotently — count-gated per bia_id).
- **Bucket labels are per-tenant, not per-BIA** — changing them
  relabels EVERY BIA's columns; the settings PUT must warn in the UI
  copy ("applies to all BIAs").
- **Delete-and-reinsert for impact rows loses nothing** (no FKs point
  at them) but resources are row-CRUD because a reinsert would churn
  ids mid-editing session.
- **`business_process_id` is a bare INTEGER** (cross-block reference
  convention); render the process name via LEFT JOIN in get_bia, and
  tolerate deleted processes (NULL name → show "—").
- **BCM's data_service uses the module's own commit/close idiom** —
  READ two existing functions and copy exactly; this module was the
  subject of past `?`-placeholder fixes, so use `%s` placeholders
  throughout.

## Acceptance criteria

1. All 5 tests pass; full suite green; py_compile clean.
2. Live: complete questionnaire round-trip; grids persist and reload;
   suggested RTO appears/updates correctly and only fills RTO on
   explicit apply.
3. Custom bucket labels show as grid headers after the settings PUT.
4. Legacy BIA (created pre-change) opens without errors and can adopt
   the standard rows via the button.
5. A BIA linked to a business process shows the process name; deleting
   the process leaves the BIA intact.
