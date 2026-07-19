# PLAN-21: AI controls catalogue + AIMS/ORAAT risk engine in ORM

## Goal

Digitize the two ISO 42001 workbooks as a living system inside ORM:

1. **AI controls catalogue** (from "Taxonomy.xlsx": 96 controls AIC1-96,
   each with a description and a pillar tag People / Process / Systems /
   Technology / Tools). Per-tenant, fully EDITABLE in-app — the user's
   explicit requirement that the catalogue "shouldn't be locked in".
2. **AIMS risk register** (from "AIMS Risk Assessment and Treatment
   .xlsx"): risks tied to strategic + AI objectives, monetary exposure
   (EMV), inherent rating (IRR = L×I on the 5×5 scale), multiple linked
   catalogue controls each carrying an ICE factor, per-pillar
   aggregation, computed residual rating and residual EMV, treatments
   (Accept/Mitigate/Share/Avoid/Exploit) with action steps, cost,
   owners, due dates, and target/appetite/tolerance thresholds.
3. **ORAAT mode** (from "ISO42001 Operational Risk Assessment and
   Treatment..xlsx"): the control-centric variant — one row per Annex-A
   control with in-scope / implemented flags, risk-to-control
   description, ICE 1-10, and residual = IRR × (ICE/10).

This is the deepest integration in the batch. It deliberately rhymes
with what exists: the assessment→risks→controls shape mirrors ORM RCSA
(orm_rcsa_assessments/risks/controls), the impacted-pillar dropdown is
fed by the ERM rating framework's impact dimensions (Revenue, EBITDA,
Total Assets, Brand Damage, Regulatory/Legal, Customer Operations,
Environment — the workbook's pillar list IS the OmniContact dimension
list already seeded), and the residual math is one multiplier model.

## THE SCORING CONVENTION (read before writing any formula)

The source workbooks are internally inconsistent: the AIMS aggregation
sheet computes residual RATING as `IRR × mean(ICE)` but residual EMV as
`EMV × (1 − mean(ICE))` — opposite directions in the same row. This
plan fixes ONE convention and documents it in code:

- `ice_factor` per linked control ∈ [0.0, 1.0] = the REMAINING-risk
  multiplier. 0.1 = very strong control (10% of risk remains), 1.0 = no
  effect. ORAAT's 1-10 input maps as `factor = score / 10`.
- Per risk: `mean_factor = average(ice_factor of linked controls)`
  (unlinked risk → 1.0).
- `residual_rating = round(irr × mean_factor, 2)`
- `residual_emv = round(emv_inherent × mean_factor, 2)`

Both residuals use the SAME multiplier. When importing/copying numbers
from the legacy sheets, expect residual EMV to differ from the sheet —
that is the sheet's bug, not ours. State this in a code comment above
the computation.

## ALIGNMENT WITH ERM v2 ICE (decided 2026-07-18, read with PLAN-23)

Round 6 (PLAN-23) introduced the platform-wide ICE convention in ERM:
control effectiveness is entered as a PERCENT in {0,10,...,90}, higher =
stronger, and the remaining-risk multiplier is (100 - ice)/100. The
convention above is mathematically identical (this plan's `mean_factor`
IS PLAN-23's LoR; residual_rating = IRR x LoR; residual_emv =
EMV x LoR), so the ENGINE stays exactly as specified. What changes is
the INPUT ENCODING, so ORM/AIMS is born converged with ERM instead of
becoming a third dialect:

- Store and collect control effectiveness as `ice_score` INTEGER percent
  in {0,10,...,90}, higher = stronger (same dropdown as ERM PLAN-24).
  Derive `ice_factor = (100 - ice_score) / 100.0` internally; all
  formulas above are unchanged after that substitution.
- Legacy ORAAT 1-10 sheet values map on import as
  `ice_score = 100 - score*10` (sheet 1 -> 90 strongest, sheet 10 -> 0
  none); this lands exactly on the allowed steps. Document the mapping in
  the importer.
- Never present a scale where a LOW number means a STRONG control; that
  inversion between modules is the auditor-facing inconsistency this
  alignment exists to prevent.
- Catalogue pillar tags: this plan's normalized set {People, Process,
  Systems, Technology, Tools} stays as-is for the catalogue itself, but
  when seeding/mirroring into canonical_controls.p2st2_category
  (PLAN-23 column) map to the singular canonical set {People, Process,
  System, Technology, Tool} from the mind map's P2sT2 definition.
- ORM RCSA's existing 1-5 control_effectiveness is NOT changed by this
  plan; its convergence onto ICE is the queued PLAN-29 (Round 7).

## Exact files to touch

1. `oneforall/database.py` — 4 tables in `_ERM_ORM_TABLES` + catalogue
   seed hook
2. `oneforall/scripts/extract_ai_controls.py` — NEW one-off extractor
3. `oneforall/seeds/ai_controls_seed.json` — generated output (committed)
4. `oneforall/modules/orm/data_service.py` — catalogue CRUD + AIMS CRUD
   + computation
5. `oneforall/modules/orm/routes.py` — endpoints + SPA pages
6. `oneforall/modules/orm/templates/index.html` — "AI Risk (AIMS)" +
   "AI Controls" pages
7. `oneforall/core/rbac.py` — reuse `orm.event.manage`-tier: gate writes
   behind existing `orm.kri.manage`-style capability — READ the orm.*
   block and pick the manage capability used by RCSA endpoints; reuse it
8. `oneforall/tests/test_aims_engine.py`

## Step-by-step order

### Step 1 — Extraction script (run once, commit the JSON)

`scripts/extract_ai_controls.py`: openpyxl-read
`C:\Users\isadmin\Downloads\Taxonomy.xlsx` Sheet1 (cols: #, Ref,
Control, Pillar), FULL untruncated text, normalize pillar values to the
set {People, Process, Systems, Technology, Tools} (the sheet contains
`Process/Systems`, `Process/Tools`, `Systems ` with whitespace — split
on `/`, take the FIRST, strip), dump
`seeds/ai_controls_seed.json` as
`[{"ref":"AIC1","title":…,"pillar":"People"}, …]` (title = first
sentence or first 120 chars of the control text; full text →
"description"). Run it, verify 96 entries, commit the JSON. The app
never reads the xlsx.

### Step 2 — Tables (end of `_ERM_ORM_TABLES`)

```sql
CREATE TABLE IF NOT EXISTS ai_control_catalogue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ref         TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT,
    pillar      TEXT DEFAULT 'Process',
    source      TEXT DEFAULT 'custom',
    is_active   INTEGER DEFAULT 1,
    business_unit_id INTEGER,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_aicc_ref ON ai_control_catalogue(lower(trim(ref)));
CREATE TABLE IF NOT EXISTS aims_assessments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ref         TEXT UNIQUE NOT NULL,
    title       TEXT NOT NULL,
    mode        TEXT DEFAULT 'aims',
    status      TEXT DEFAULT 'draft',
    eval_date   TEXT,
    business_unit_id INTEGER,
    created_by  INTEGER,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS aims_risks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id       INTEGER NOT NULL REFERENCES aims_assessments(id) ON DELETE CASCADE,
    ref                 TEXT,
    strategic_objective TEXT,
    ai_objective        TEXT,
    risk_description    TEXT NOT NULL,
    contributing_factors TEXT,
    impacted_pillar     TEXT,
    likelihood          INTEGER DEFAULT 5,
    impact              INTEGER DEFAULT 5,
    emv_inherent        REAL,
    risk_owner          TEXT,
    rr_target           REAL,
    rr_appetite         REAL,
    rr_tolerance        REAL,
    catalogue_control_id INTEGER,
    in_scope            INTEGER DEFAULT 1,
    implemented         INTEGER DEFAULT 0,
    scope_justification TEXT,
    status              TEXT DEFAULT 'open',
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_aims_risks_assessment ON aims_risks(assessment_id);
CREATE TABLE IF NOT EXISTS aims_risk_controls (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id             INTEGER NOT NULL REFERENCES aims_risks(id) ON DELETE CASCADE,
    catalogue_control_id INTEGER,
    control_detail      TEXT,
    evidence            TEXT,
    control_owner       TEXT,
    ice_factor          REAL DEFAULT 1.0,
    treatment           TEXT DEFAULT 'mitigate',
    action_steps        TEXT,
    treatment_cost      REAL DEFAULT 0,
    responsible         TEXT,
    interdependency     TEXT,
    due_date            TEXT,
    status              TEXT DEFAULT 'open',
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_aims_rc_risk ON aims_risk_controls(risk_id);
```

`aims_risks.catalogue_control_id / in_scope / implemented /
scope_justification` serve ORAAT mode (control-centric rows); NULL in
AIMS mode. IRR is computed `likelihood × impact`, not stored.

### Step 3 — Catalogue seed

In `_seed_baseline_data()`, count-gated on `ai_control_catalogue`:
`json.load` the committed `seeds/ai_controls_seed.json` (resolve the
path relative to the database.py file, matching how other seed assets
are located — grep `os.path` usage in the seeds area; if none, use
`Path(__file__).parent / "seeds" / "ai_controls_seed.json"`), insert
with `source='built_in'`. Wrap in the standard try/except; a missing
JSON file must log a warning, never crash startup.

### Step 4 — Data service

Catalogue: `list_ai_controls(pillar=None, include_inactive=False)`,
`create/update/delete_ai_control` (delete refuses when referenced by
`aims_risk_controls`; deactivate instead). Pillar validated against
{People, Process, Systems, Technology, Tools}.

AIMS: assessment CRUD (ref generator `AIMS-{n}` mirroring RCSA's — READ
how RCSA generates refs); risk CRUD; risk-control link CRUD
(`ice_factor` clamped `max(0.0, min(1.0, float(v)))`; accept an
`ice_score_10` input alias → divide by 10).

**`compute_aims_risk(db, risk_id) -> dict`** — the single scoring
function implementing THE CONVENTION above, returning
`{irr, mean_factor, residual_rating, residual_emv, per_pillar}` where
`per_pillar` = for each of the 5 pillars: mean ice_factor + control
count (join through the catalogue for pillar; controls with NULL
catalogue link count under their risk's `impacted_pillar`).

**`get_aims_aggregation(db, assessment_id)`** — one row per risk
reproducing the workbook's Aggregation Sheet: ref, objectives, risk,
emv_inherent, irr, per-pillar factor+count columns, mean_factor,
residual_rating, residual_emv, total treatment_cost.

### Step 5 — Endpoints + UI

Endpoints under `/orm/api/ai-controls` and `/orm/api/aims/...`
mirroring the RCSA endpoint family (READ it first). UI: two new ORM SPA
pages following the RCSA pages' pattern:
- **AI Controls** — filterable table (pillar chips), add/edit modal,
  deactivate; built_in rows editable but NOT deletable.
- **AI Risk (AIMS)** — assessments list (mode badge AIMS/ORAAT) → risk
  register grid (ref, objectives, risk, pillar, IRR chip, residual chip,
  EMV columns, control count) → risk drawer: risk fields + linked
  controls table (catalogue picker + ICE slider 0-1 with 1-10 helper,
  treatment select from {accept, mitigate, share, avoid, exploit},
  action steps, cost, owner, due date) + computed panel (IRR →
  mean factor → residual rating vs target/appetite/tolerance chips —
  green when residual <= target, amber <= tolerance, red above) +
  per-pillar mini-bars. CSV export of the aggregation.

### Step 6 — Tests + verify

`tests/test_aims_engine.py`:
1. Convention: risk L5×I5 EMV 2,000,000 with controls at factors
   0.3/0.6/0.6/0.2 → mean 0.425, residual_rating 10.63,
   residual_emv 850,000. (Pin YOUR computed values by hand.)
2. Unlinked risk → mean_factor 1.0, residual == inherent.
3. Catalogue delete refused when linked; deactivate works.
4. ORAAT: ice_score_10 input 1 → factor 0.1 → residual 2.5 for IRR 25
   (matches the source sheet's own example).
5. Seed: fresh DB loads 96 catalogue rows.
Live pass: build one AIMS assessment with 1 risk + 3 controls in the
UI, verify the computed panel and aggregation CSV. Cleanup.

## Edge cases a weaker model would miss

- **The two workbooks disagree on residual direction** — the convention
  section exists because of it. Do not "fix" the formula to match the
  legacy EMV column; the code comment must explain the deviation or
  the customer will file a bug against the correct number.
- **Pillar strings in the xlsx are dirty** (`Process/Systems`,
  trailing spaces, `Systems` vs `System`) — the extractor normalizes;
  the app validates. Map `System` → `Systems` explicitly.
- **`extract_ai_controls.py` runs on the DEV machine once** — the app
  reads only the committed JSON. Never make startup read from
  `C:\Users\...\Downloads`.
- **built_in catalogue rows are editable but undeletable** — orgs must
  be able to reword controls (the "not locked in" requirement) yet the
  seed must survive as a base; deactivate covers removal.
- **Clamp ICE at write time, not read time** — a 7.5 typed into a 0-1
  field would silently make residual larger than inherent everywhere
  downstream.
- **IRR is derived, never stored** — storing it invites drift when L/I
  change. Same for residuals: compute on read (registers are small),
  do not persist computed values in this slice.
- **`impacted_pillar` dropdown is data-driven**: feed it from the
  ACTIVE ERM framework's impact dimensions
  (`GET /erm/api/framework/active` client-side — already cached
  pattern), NOT a hardcoded list. Falls back to a text input when no
  framework is active.
- **ON DELETE CASCADE relies on `_run_pg_fk_cascades` for PG** — the
  inline REFERENCES here get auto-named constraints; verify cascade
  behavior on SQLite (works when PRAGMA foreign_keys is on — grep the
  wrapper for the pragma; if off, add explicit child deletes in
  delete functions, matching the RCSA delete pattern).
- **Treatment enum includes `share` and `exploit`** (the workbook's
  key) — wider than ERM's four; validate against the 5-value set here
  only, do not touch ERM's enum.

## Acceptance criteria

1. All 5 tests pass with hand-pinned numbers; full suite green.
2. Fresh DB seeds exactly 96 built_in catalogue rows, all with clean
   pillar values from the 5-value set.
3. Live: risk drawer shows IRR, mean factor, residual rating and EMV
   consistent with the convention; target/appetite/tolerance chips
   color correctly on either side of the thresholds.
4. Aggregation CSV columns match the workbook's Aggregation Sheet
   (per-pillar factors + counts + residuals).
5. Catalogue is editable in-app (add, rename, re-pillar, deactivate) and
   built_in rows refuse deletion with a clear 409 message.
