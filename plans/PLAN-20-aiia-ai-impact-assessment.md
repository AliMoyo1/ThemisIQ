# PLAN-20: AIIA — AI Impact Assessments in Sentinel

## Goal

Digitize the "AI Impact Questionnaire.xlsx" as a first-class assessment
type next to DPIAs. Structure (verified from the workbook):

- **Part 1 — system profile**: AI system name, department, owner, system
  description, business process supported, deployment environment
  (on-prem / cloud / hybrid), third-party components (+ details),
  outputs/decisions generated, influences customer or financial
  decisions (y/n), autonomy level (decision-support / human-in-loop /
  automated).
- **Part 2 — impact evaluation**: data categories processed (personal /
  transactional / operational / behavioural), sensitive data (y/n),
  direct + indirect stakeholders, then an impact grid over EIGHT
  dimensions (Financial, Operational, Reputational, Regulatory/Legal,
  Privacy, Security, Ethical/Fairness, Societal) each scored
  likelihood 1-5 × impact 1-5 with a classification, an overall system
  classification, required mitigation measures, and a residual
  classification after mitigation.

Design decisions honoring the user's constraints:
- **The dimension list is data, not code** — a per-tenant editable
  `sentinel_aiia_dimensions` table seeded with the 8. Orgs add or rename
  dimensions without a deploy.
- **Band classification reuses the ERM rating framework** —
  `resolve_band()` against the active framework, so "High" means the
  same thing in ERM and AIIA.
- **Graph-aware** — optional links to an `applications` row (the AI
  system as a T1.1 node), a RoPA, and a DPIA. `business_unit_id` for
  SBU scoping.

## Exact files to touch

1. `oneforall/database.py` — 3 tables in `_SENTINEL_TABLES` + dimension
   seed in `_seed_baseline_data()`
2. `oneforall/modules/sentinel/data_service.py` — CRUD + scoring
3. `oneforall/modules/sentinel/routes.py` — endpoints + SPA page key
4. `oneforall/modules/sentinel/templates/index.html` — nav entry
   "AI Impact (AIIA)" under the Assessments section + editor UI
5. `oneforall/core/rbac.py` — reuse `sentinel.dpia.manage` for writes
   and `module.sentinel.access` for reads (no new capability)
6. `oneforall/tests/test_aiia.py`

## Step-by-step order

### Step 1 — Tables (end of `_SENTINEL_TABLES`, SQLite dialect)

```sql
-- ── Sentinel: AI Impact Assessments (AIIA) ────────────────────────────────
CREATE TABLE IF NOT EXISTS sentinel_aiia (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_number          TEXT UNIQUE NOT NULL,
    title               TEXT NOT NULL,
    ai_system_name      TEXT,
    application_id      INTEGER,
    department          TEXT,
    owner               TEXT,
    system_description  TEXT,
    business_process    TEXT,
    deployment_env      TEXT,
    third_party         INTEGER DEFAULT 0,
    third_party_details TEXT,
    outputs_decisions   TEXT,
    influences_customers INTEGER DEFAULT 0,
    autonomy_level      TEXT DEFAULT 'decision_support',
    data_categories     TEXT,
    sensitive_data      INTEGER DEFAULT 0,
    stakeholders_direct TEXT,
    stakeholders_indirect TEXT,
    overall_classification TEXT,
    mitigation_measures TEXT,
    residual_classification TEXT,
    status              TEXT DEFAULT 'draft',
    ropa_id             INTEGER,
    dpia_id             INTEGER,
    business_unit_id    INTEGER,
    created_by          INTEGER,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sentinel_aiia_dimensions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    order_idx   INTEGER DEFAULT 0,
    is_active   INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sentinel_aiia_impacts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    aiia_id        INTEGER NOT NULL REFERENCES sentinel_aiia(id) ON DELETE CASCADE,
    dimension_name TEXT NOT NULL,
    applicable     INTEGER DEFAULT 1,
    description    TEXT,
    likelihood     INTEGER,
    impact         INTEGER,
    UNIQUE(aiia_id, dimension_name)
);
CREATE INDEX IF NOT EXISTS idx_aiia_impacts ON sentinel_aiia_impacts(aiia_id);
```

Impacts key by `dimension_name` (TEXT, no FK) for the same reason ERM
dimension scores do — renaming/deleting a dimension must never
cascade-destroy historical assessments.

### Step 2 — Seed the 8 dimensions

In `_seed_baseline_data()`, count-gated block inserting: Financial,
Operational, Reputational, Regulatory/Legal, Privacy, Security,
Ethical/Fairness, Societal (order_idx 1..8).

### Step 3 — Data service

Copy the DPIA function family's shape exactly (READ create_dpia /
update_dpia / get_dpia / list_dpias first): `list_aiias`, `get_aiia`
(attaches `impacts` child rows joined against active dimensions, plus
any orphaned scored rows), `create_aiia`, `update_aiia`, `delete_aiia`
(explicit child delete), plus `list_aiia_dimensions` /
`save_aiia_dimensions` (upsert list with rename support: rename =
UPDATE name on the dimension row AND
`UPDATE sentinel_aiia_impacts SET dimension_name=%s WHERE dimension_name=%s`
so history follows).

Scoring inside create/update: for each applicable impact row compute
band via `resolve_band()` — import
`from modules.erm.data_service import get_active_framework_matrix, resolve_band`
INSIDE the function (cross-module import at module top risks cycles).
`overall_classification` = the band of the HIGHEST likelihood×impact
product among applicable rows (ties → first). Residual classification
stays a manual select (the questionnaire treats it as judgment).

Ref numbers: mirror the DPIA ref generator (grep it) with prefix `AIIA-`.

### Step 4 — Endpoints + SPA page

Endpoints under `/sentinel/api/aiias` mirroring the DPIA set (list,
detail, POST, PUT, DELETE) plus `GET/PUT /api/aiia-dimensions`
(PUT gated `sentinel.dpia.manage`). Add the SPA page key the same way
existing Sentinel pages register (grep the Sentinel `_SPA_PAGES`
equivalent and router switch).

### Step 5 — UI

Nav: "AI Impact (AIIA)" in the ASSESSMENTS sidebar group (below
Legitimate Interest — find that nav markup and copy the row).
List view: table (ref, title, system, autonomy badge, overall
classification band chip using the ERM band colors already cached in
Sentinel? — if Sentinel does not cache ERM bands, color chips with the
existing risk_level chip styles instead; do NOT invent new colors).
Editor: tabs matching the DPIA editor pattern (Basics = Part 1 fields;
Impacts = grid of dimension rows with applicable toggle, description,
L and I selects, live band chip; Mitigation = measures + residual
select; Review = status + links to RoPA/DPIA/application via dropdowns
fed by existing list endpoints). A "Manage dimensions" modal (managers
only) with add/rename/deactivate rows.

### Step 6 — Tests + verify

`tests/test_aiia.py`:
1. Create AIIA with 3 applicable impacts (5×5, 2×2, 1×1) → overall
   classification equals `resolve_band(5,5)`'s band.
2. Rename a dimension → historical impact rows follow.
3. Delete AIIA → impacts cascade.
4. Dimension deactivate → excluded from new forms, historical rows
   still returned by get_aiia.
Live pass: create from the UI end-to-end, link a RoPA, verify band
chips match ERM's Rating Guide colors for the same L×I. Cleanup.

## Edge cases a weaker model would miss

- **`resolve_band` needs an open db + the matrix fetched once** — fetch
  the matrix once per create/update call, never per impact row, and
  never at import time.
- **No active ERM framework** (deactivated by an admin mid-edit) →
  `get_active_framework_matrix` returns empty dicts; resolve_band then
  returns its fallback. Guard: if the matrix is empty, store
  classification `'unrated'` rather than the fallback band, and render
  it as a muted chip.
- **Applicable=0 rows keep their L/I values** (the questionnaire lets
  you un-tick without losing data) but are EXCLUDED from the overall
  classification.
- **Dimension rename collision** — renaming "Security" to an existing
  "Privacy" must be rejected (409) or the UNIQUE(aiia_id,
  dimension_name) constraint corrupts merges silently on PG
  (ON CONFLICT swallows) — check name uniqueness app-side first.
- **`sentinel_aiia_dimensions` has no seed for EXISTING tenants** if
  the count-gate sees other seeded Sentinel data — the gate must count
  THIS table only (`SELECT COUNT(*) FROM sentinel_aiia_dimensions`).
- **The DPIA link is optional and one-way here** — do not touch
  `sentinel_dpias.ai_assessment` (a free-text column used by an
  existing AI feature; grep before assuming it is free).
- **BU scoping**: include `business_unit_id` in create/update payload
  handling now; actual filter enforcement arrives with PLAN-18 Part B —
  do not implement scoping twice.

## Acceptance criteria

1. All 4 tests pass; full suite green; py_compile clean.
2. Live: full questionnaire round-trip (Part 1 + 8-dimension grid +
   mitigation + residual) persists and reloads correctly.
3. Overall classification chip matches the ERM Rating Guide band for
   the same L×I pair.
4. Dimensions are editable in-app: add a 9th dimension, it appears on
   the next new AIIA; rename one, history follows.
5. AIIA list shows band chips and links; RoPA/DPIA/application
   dropdowns populate from existing endpoints.
