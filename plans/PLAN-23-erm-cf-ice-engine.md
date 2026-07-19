# PLAN-23: ERM Contributing Factors + ICE Scoring Engine (backend core)

## Status: OPEN

## Goal

Implement the data model and scoring engine for the redesigned ERM module
(source: `ERM Module.xmind` mind map, 2026-07-17): contributing factors
(root causes, CF001 numbering), ICE control scoring (0-90% in 10% steps),
frozen IRR at first discovery, EMV-i / EMV-r monetary exposure, LoA / LoR,
RRR (residual risk rating), auto-assigned risk reference numbers, organisational
pillars, and a score-history table for the future trajectory graph.

This plan is BACKEND ONLY (schema, data service, routes, tests). The UI ships
in PLAN-24. Constraint from the user: keep all existing ERM tables and extend
them; replace the old effectiveness rating pathway with ICE scoring.

## The ICE scoring convention (single documented resolution)

The mind map says literally: "we get the average of all the scores which is
our LoA and we multiply it by the IRR and get our residual risk score". Taken
literally with LoA = average ICE percentage, a 90% (excellent) control would
give RRR = 0.9 x IRR, which is backwards. But the mind map's own multiplier
table (0% = factor 1.0 ... 90% = factor 0.1, factor multiplied by inherent to
get residual) plus its EMV-r definition ("actual amount at risk after
controls") force the correct reading. Because average-of-multipliers equals
1 minus average-of-ICE-fractions, both readings produce the same RRR number;
only the label differs. Adopt this convention everywhere and never deviate:

- `ice_score`: INTEGER percent per control link. Allowed values exactly
  0, 10, 20, 30, 40, 50, 60, 70, 80, 90 or NULL (not yet scored).
- multiplier per control = (100 - ice_score) / 100.0
- LoA (Level of Assurance) percent = round(average of ice_score over all
  linked controls of the risk WHERE ice_score IS NOT NULL)
- LoR (Level of Risk) fraction = 1.0 - (LoA / 100.0)
  (mathematically identical to the average multiplier)
- IRR (Inherent Risk Rating) = likelihood x impact frozen at risk creation
- RRR (Residual Risk Rating) = round(LoR x IRR, 1)  [REAL, 1 decimal]
- EMV-r = round(LoR x emv_inherent, 2) when emv_inherent is set, else NULL
- RRR >= 15 means high risk (dashboard threshold, PLAN-26)
- CF-level assurance (for PLAN-25 treatment suggestion) = average ice_score
  of controls where risk_controls.cf_id = that CF; Accept is suggested at
  CF assurance >= 70

Worked example to reuse in tests: risk L4 x I5 gives IRR 20. Two controls
scored ICE 70 and ICE 90: LoA = 80, LoR = 0.2, RRR = 4.0,
residual_score = 4. With emv_inherent 500000: emv_residual = 100000.

## Residual precedence ladder (rewrite of recompute_residual_for_risk)

Highest wins. This REPLACES the T1.4 ladder in
`oneforall/modules/erm/data_service.py` (function at line ~664):

1. ICE path: at least one linked control has ice_score NOT NULL.
   loa_pct, rrr, emv_residual computed per the convention above.
   residual_score = int(round(rrr)) so every existing band/badge display
   keeps working.
2. Manual override: residual_likelihood AND residual_impact both set (and no
   control has an ICE score). residual_score = RL x RI (unchanged behavior),
   rrr = float(RL x RI), loa_pct = NULL, emv_residual = NULL.
3. T1.3 auto path: linked controls exist with rows in
   control_effectiveness_scores but none has an ICE score and no override.
   Keep the existing weighted mean, but multiply against IRR, not current
   L x I: rrr = round(irr_score x (1 - weighted_eff/100), 1),
   residual_score = int(round(rrr)), loa_pct = round(weighted_eff),
   emv_residual = round((1 - weighted_eff/100) x emv_inherent, 2) if
   emv_inherent set.
4. Default (no controls, no override): LoA = 0, LoR = 1.0, rrr = irr_score,
   residual_score = irr_score, emv_residual = emv_inherent. This is a
   deliberate semantic change from T1.4 (which left residual NULL): under
   the new model an unassessed risk's starting point IS its IRR.

The legacy `control_effectiveness` column keeps being written by path 3 only
(unchanged meaning). The legacy `effectiveness_rating` column (1-5 integer)
is retired from writes: remove the string "effectiveness_rating" from the
writable field list in `update_enterprise_risk` (data_service.py line ~728).
Never drop the column. The Excel import mapping that targets it
(data_service.py lines ~1923, ~2211) may remain; create_enterprise_risk's
INSERT ignores it anyway.

## Files to touch (exact)

1. `oneforall/database.py`
2. `oneforall/modules/erm/data_service.py`
3. `oneforall/modules/erm/routes.py`
4. `oneforall/core/event_handlers.py` (auto-elevation insert, see Step 5b)
5. `oneforall/modules/governance/data_service.py`
6. `oneforall/modules/governance/templates/index.html` (one dropdown)
7. `oneforall/tests/test_erm_ice_engine.py` (NEW)
8. `plans/README.md` (mark plan status when done)

## Step-by-step order

### Step 0: create `plans/PLAN-23-active.md` and log every change to it as you go.

### Step 1: database.py - three new tables

Append inside the `_ERM_ORM_TABLES` string, immediately BEFORE the
`risk_controls` table definition (search for "Risk ↔ Control bridge",
line ~3524). Write SQLite dialect only; `_to_pg_schema()` auto-converts
(AUTOINCREMENT, datetime('now'), REAL):

```sql
-- ── ERM v2: Contributing Factors (root causes per risk) ────────────────
CREATE TABLE IF NOT EXISTS erm_contributing_factors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id     INTEGER NOT NULL REFERENCES erm_enterprise_risks(id) ON DELETE CASCADE,
    cf_ref      TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(risk_id, cf_ref)
);
CREATE INDEX IF NOT EXISTS idx_erm_cf_risk ON erm_contributing_factors(risk_id);

-- ── ERM v2: Risk score history (trajectory graph source) ───────────────
CREATE TABLE IF NOT EXISTS erm_risk_score_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id       INTEGER NOT NULL REFERENCES erm_enterprise_risks(id) ON DELETE CASCADE,
    irr           INTEGER,
    rrr           REAL,
    loa_pct       INTEGER,
    emv_inherent  REAL,
    emv_residual  REAL,
    recorded_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_erm_score_hist_risk ON erm_risk_score_history(risk_id);

-- ── ERM v2: Organisational pillars (per-tenant editable catalogue) ─────
CREATE TABLE IF NOT EXISTS erm_pillars (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL UNIQUE,
    description      TEXT,
    business_unit_id INTEGER,
    is_active        INTEGER DEFAULT 1,
    created_at       TEXT DEFAULT (datetime('now'))
);
```

### Step 2: database.py - column migrations

Append to `_COLUMN_MIGRATIONS` directly after the entry
`("erm_enterprise_risks", "control_effectiveness", ...)` (line ~3776):

```python
# ── ERM v2 (PLAN-23): CF + ICE + IRR/RRR/EMV columns ─────────────────
("erm_enterprise_risks", "risk_ref",        "TEXT DEFAULT NULL"),
("erm_enterprise_risks", "irr_score",       "INTEGER DEFAULT NULL"),
("erm_enterprise_risks", "loa_pct",         "INTEGER DEFAULT NULL"),
("erm_enterprise_risks", "rrr",             "REAL DEFAULT NULL"),
("erm_enterprise_risks", "emv_inherent",    "REAL DEFAULT NULL"),
("erm_enterprise_risks", "emv_residual",    "REAL DEFAULT NULL"),
("erm_enterprise_risks", "impacted_pillar", "TEXT DEFAULT NULL"),
("risk_controls",        "cf_id",           "INTEGER DEFAULT NULL"),
("risk_controls",        "ice_score",       "INTEGER DEFAULT NULL"),
("canonical_controls",   "p2st2_category",  "TEXT DEFAULT NULL"),
```

### Step 3: database.py - seeds and backfill in `_seed_baseline_data`

Add a new block after the existing ERM seed blocks (search for the risk
library seed block). Three parts, all idempotent, all wrapped in the same
try/except style used by neighbouring blocks:

a) Pillar seeds, count-gated exactly like other catalogues:
```python
existing = conn.execute("SELECT COUNT(*) FROM erm_pillars").fetchone()[0]
if existing == 0:
    for name, desc in [
        ("People", "Workforce, culture, skills and safety"),
        ("Financial", "Revenue, cost, liquidity and capital"),
        ("Operational Excellence", "Processes, delivery and quality"),
        ("Customer", "Customer trust, service and retention"),
        ("Technology & Innovation", "Systems, data and innovation capacity"),
        ("Reputation & Brand", "Public image and stakeholder confidence"),
    ]:
        conn.execute(
            "INSERT INTO erm_pillars (name, description) VALUES (%s,%s)",
            (name, desc))
```

b) IRR backfill, runs every startup, matches zero rows once done:
```python
conn.execute(
    "UPDATE erm_enterprise_risks "
    "SET irr_score = COALESCE(inherent_score, likelihood*impact, 9) "
    "WHERE irr_score IS NULL")
```

c) risk_ref backfill: SELECT id FROM erm_enterprise_risks WHERE risk_ref IS
NULL ORDER BY id, then per row UPDATE risk_ref = 'RSK-' + zero-padded
4-digit sequence continuing from the current maximum (see edge cases for
how to derive the maximum). Loop in Python, not one SQL statement.

### Step 4: data_service.py - engine rewrite

All in `oneforall/modules/erm/data_service.py`:

a) Module constant near the top:
```python
ICE_ALLOWED = {0, 10, 20, 30, 40, 50, 60, 70, 80, 90}
```

b) `_next_ref(db, table, column, prefix, pad, where_sql="", params=())`:
generic helper returning the next zero-padded ref. It must SELECT all
existing values for the column (with optional WHERE for per-risk scoping),
parse the integer suffix of well-formed values, take max+1 (start at 1).
Used for risk_ref ('RSK-', pad 4), cf_ref ('CF', pad 3, scoped
WHERE risk_id=%s).

c) `_ice_rollup(db, risk_id)`: returns dict
`{scored: bool, loa_pct: int|None, lor: float|None}` from
`SELECT ice_score FROM risk_controls WHERE risk_id=%s AND ice_score IS NOT NULL`.

d) Rewrite `recompute_residual_for_risk(db, risk_id)` to the 4-tier
precedence ladder above. It must now SELECT likelihood, impact,
residual_likelihood, residual_impact, irr_score, emv_inherent, rrr FROM the
risk row; compute per the ladder; UPDATE residual_score, rrr, loa_pct,
emv_residual, control_effectiveness in one statement; then call
`_snapshot_history(db, risk_id, ...)` (below) only when the new rrr differs
from the previously stored rrr by more than 0.05 or the old rrr was NULL.
Caller commits (unchanged contract).

e) `_snapshot_history(db, risk_id, irr, rrr, loa_pct, emv_i, emv_r)`:
single INSERT into erm_risk_score_history.

f) `create_enterprise_risk`: before the INSERT, pop
`contributing_factors` (list) from data; compute
`irr = int(clamped L) * int(clamped I)`; generate risk_ref via `_next_ref`.
Extend the INSERT column list with risk_ref, irr_score, emv_inherent,
impacted_pillar (values from data, emv_inherent None-safe float). After the
INSERT and after `_save_dimension_scores`, call
`_save_contributing_factors(db, new_id, cf_list)` then
`recompute_residual_for_risk(db, new_id)` so rrr initialises to IRR.
Single commit at the end covers everything.

g) `_save_contributing_factors(db, risk_id, cf_list)`: ref-preserving
replace. For each entry `{id?, description}`: if id present and belongs to
this risk, UPDATE description + updated_at; if id absent, INSERT with
cf_ref = `_next_ref(... 'CF', 3, scoped to risk)`. Any existing CF row of
the risk whose id is NOT in the submitted list is DELETEd, and
`UPDATE risk_controls SET cf_id=NULL WHERE cf_id=%s` runs first for each
deleted CF. Skip entries with empty stripped description.

h) `update_enterprise_risk`: pop `contributing_factors` like
dimension_scores and apply via `_save_contributing_factors`; add
`emv_inherent` and `impacted_pillar` to the writable field list; REMOVE
`effectiveness_rating` from the writable field list; explicitly
`data.pop("irr_score", None)` and `data.pop("risk_ref", None)` so a client
can never overwrite them; when emv_inherent or contributing_factors or any
score field changed, call `recompute_residual_for_risk` before commit.

i) `get_enterprise_risk`: also attach
`risk["contributing_factors"] = _get_contributing_factors(db, risk_id)`
(each with id, cf_ref, description, control_count, cf_loa_pct computed via
one grouped query over risk_controls).

j) `delete_enterprise_risk`: add explicit
`DELETE FROM erm_contributing_factors WHERE risk_id=%s` and
`DELETE FROM erm_risk_score_history WHERE risk_id=%s` alongside the
existing cleanup DELETEs.

k) `list_risk_controls`: extend the SELECT with rc.cf_id, rc.ice_score,
cf.cf_ref AS cf_ref (LEFT JOIN erm_contributing_factors cf ON
cf.id = rc.cf_id) and cc.p2st2_category.

l) New `set_control_assessment(risk_id, control_id, ice_score, cf_id)`:
validates ice_score is None or in ICE_ALLOWED (raise ValueError otherwise);
if cf_id given, verify the CF row belongs to risk_id (raise ValueError
otherwise); UPDATE risk_controls SET ice_score=%s, cf_id=%s WHERE
risk_id=%s AND control_id=%s; then recompute_residual_for_risk; commit;
return the refreshed risk dict.

m) New `suggest_ice_for_control(control_id)`: read the T1.3 score via
`modules.governance.effectiveness.get_control_score`; if no row, treat
score as 0. suggested = min(90, (score // 10) * 10). Return
`{"suggested_ice": suggested, "auto_score": score, "factors": {...}}`
with the 7 factor values when present. Pure math, no AI call (the AI
narrative variant is PLAN-24).

### Step 5: routes.py - new endpoints

Place after the existing risk-control endpoints (line ~190), following the
same decorator + `_json_body` + capability patterns:

- `GET  /api/risks/{risk_id}/cfs` (erm.risk.view): list CFs with
  control_count and cf_loa_pct.
- `POST /api/risks/{risk_id}/cfs` (erm.risk.manage): body {description};
  404 when the risk does not exist; returns {id, cf_ref}.
- `PUT  /api/cfs/{cf_id}` (erm.risk.manage): body {description}.
- `DELETE /api/cfs/{cf_id}` (erm.risk.manage): NULLs risk_controls.cf_id
  for that CF first, then deletes the CF row.
- `PUT  /api/risks/{risk_id}/controls/{control_id}` (erm.risk.manage):
  body {ice_score, cf_id}; wraps set_control_assessment; a ValueError maps
  to HTTP 400 with the message.
- `GET  /api/risks/{risk_id}/controls/{control_id}/suggest-ice`
  (erm.risk.view): wraps suggest_ice_for_control.
- `GET  /api/pillars` (erm.risk.view): SELECT active pillars ordered by
  name (add a tiny list_pillars() to data_service).

Also extend the existing POST link endpoint (line ~170) to accept optional
`cf_id` and `ice_score` in the body, validated exactly like
set_control_assessment, passed through to `link_risk_control` (add the two
optional parameters there; keep default None so existing callers work).

BU scoping: the CF and ICE endpoints operate on a risk the caller must be
allowed to see. Mirror the scope pattern from the GET risk detail endpoint
(routes.py lines ~99-101, `bu_scope_ids` + business_unit_id check) on
`POST /api/risks/{risk_id}/cfs` and the ICE PUT; the cf_id-addressed
endpoints resolve the CF's risk_id first and apply the same check.

### Step 5b: auto-elevation handlers get refs and IRR

`oneforall/core/event_handlers.py` `_insert_erm_risk` (line ~1934) inserts
ERM risks with raw SQL, bypassing create_enterprise_risk. It is called by
the GRID finding, BCM risk, BCM incident, and Sentinel breach elevation
handlers, so auto-elevated risks would otherwise have no risk_ref,
irr_score, or rrr until the next app restart runs the backfill. Fix inside
`_insert_erm_risk`, immediately after `insert_returning_id` succeeds:

```python
from modules.erm.data_service import _next_ref, recompute_residual_for_risk
ref = _next_ref(db, "erm_enterprise_risks", "risk_ref", "RSK-", 4)
db.execute(
    "UPDATE erm_enterprise_risks SET risk_ref=%s, irr_score=%s, "
    "inherent_score=%s WHERE id=%s",
    (ref, int(likelihood) * int(impact), int(likelihood) * int(impact), cur))
recompute_residual_for_risk(db, cur)
```

Import INSIDE the function (the lazy-import pattern
modules/governance/effectiveness.py line ~198 already uses) to avoid a
circular import at module load. Keep it inside the existing try/except so
an elevation never fails on ref generation; the startup backfill remains
the safety net.

### Step 6: governance p2st2_category plumbing

In `oneforall/modules/governance/data_service.py`:
`create_canonical_control` (line ~597) and its update twin gain
`p2st2_category` in their field lists; `list_canonical_controls`
(line ~574) already SELECTs * or explicit columns, ensure the new column is
returned. In `oneforall/modules/governance/templates/index.html`, add a
select with the 6 options: empty, People, Process, System, Technology,
Tool to the control add/edit modal, and send it in the save payload.
Valid values are exactly: People, Process, System, Technology, Tool
(the P2sT2 framework from the mind map). NOTE: PLAN-21 (AI controls
catalogue) is still open; when it executes, its catalogue seeds should set
p2st2_category too. Do not build a second control library here:
canonical_controls IS the P2sT2 library.

### Step 7: tests - `oneforall/tests/test_erm_ice_engine.py`

Use the `test_db` fixture (fresh migrated SQLite per test, see
tests/conftest.py). Call data_service functions directly, mirroring
tests/test_ropa_dpia_link.py style. Required cases:

1. create risk L4 I5: irr_score 20, risk_ref matches RSK-\d{4}, rrr == 20.0
   (default path), residual_score == 20, one history row.
2. link 2 canonical controls, set ICE 70 and 90: loa_pct 80, rrr 4.0,
   residual_score 4, emv_residual == 100000 when emv_inherent 500000.
3. ice_score 0 counts as scored: single control ICE 0 gives loa_pct 0,
   rrr == irr (via ICE path, loa 0), NOT the default path.
4. invalid ICE 45 raises ValueError; ICE 90 accepted; ICE None clears.
5. IRR frozen: update likelihood to 1; irr_score still 20 while
   inherent_score becomes 5 x impact accordingly.
6. override path: no ICE anywhere, residual_likelihood 2 and
   residual_impact 3 set: residual_score 6; then setting one ICE flips to
   the ICE path and ignores the override.
7. contributing factors: save two CFs, refs CF001 CF002; delete the first
   via _save_contributing_factors omission; refs of survivors unchanged;
   linked risk_controls.cf_id cleared; a new CF gets CF003 (not CF002,
   max+1 rule).
8. cf validation: set_control_assessment with a cf_id belonging to a
   different risk raises ValueError.
9. delete risk removes its CFs and history rows.
10. history snapshots: repeated recompute with unchanged rrr adds no new
    row; an ICE change adds exactly one.

### Step 8: verification and wrap-up

- `python -m py_compile` on all touched .py files.
- Full pytest suite from repo root: all pre-existing tests plus the new
  file green.
- Live pass: start the app, create a risk in the ERM UI (old UI is fine,
  PLAN-24 not required): confirm via
  `GET /erm/api/risks/{id}` that risk_ref, irr_score, rrr appear. Clean up
  the test risk.
- Update plans/README.md Round 6 table. One focused commit.

## Edge cases a weaker model would miss

- ICE 0 is a VALID score and is falsy in Python. Every check must be
  `ice_score is not None`, never `if ice_score:`. Same for loa_pct 0 and
  rrr 0.0. Test 3 exists to catch this.
- Ref sequences must derive from MAX existing numeric suffix + 1, never
  COUNT + 1: after deleting CF001 of CF001..CF002, the next CF must be
  CF003. COUNT+1 would mint a duplicate CF002 and violate
  UNIQUE(risk_id, cf_ref).
- Parse ref suffixes defensively: values that do not match the expected
  prefix + digits pattern must be skipped, not crash int().
- SQL placeholders are %s in this codebase (a wrapper translates for
  SQLite). Never write ?.
- Write schema in SQLite dialect only; _to_pg_schema() converts REAL and
  datetime('now') automatically. Do not add a second PG copy.
- SQLite ALTER TABLE ADD COLUMN cannot add a column with a non-constant
  default: the migration strings above use constant defaults only. Keep it
  that way.
- recompute_residual_for_risk must never commit (callers commit); the
  T1.3 cascade in modules/governance/effectiveness.py line ~199 calls it
  mid-transaction.
- Rounding: round only at the very end of each formula. Store rrr as REAL
  with one decimal; residual_score stays INTEGER for band compatibility.
- update_enterprise_risk must pop irr_score and risk_ref from incoming
  data BEFORE building the field list, or a malicious PUT could rewrite
  frozen values.
- The history-change comparison must treat NULL old rrr as changed and use
  abs(new - old) > 0.05, never equality on floats.
- _save_contributing_factors must clear risk_controls.cf_id BEFORE
  deleting a CF row; there is no FK cascade between those two tables on
  SQLite databases created before this plan (the column arrives via ALTER
  TABLE without a foreign key).
- The backfill in _seed_baseline_data runs on BOTH init_db and
  provision_tenant_schema paths; keep it idempotent (WHERE ... IS NULL)
  and never count-gate it with the pillar seed gate.
- emit() events in routes must not be added inside data_service (project
  convention: events fire from routes).
- Excel import (bulk_import_risks) calls create_enterprise_risk per row:
  after this plan every imported risk automatically gets risk_ref and
  irr_score. Do not special-case the importer. Note: the importer's
  "Control Effectiveness" column maps to effectiveness_rating
  (data_service.py ~1923, ~2211), which the create INSERT has never
  included, so that column was already silently dropped before this plan;
  behavior unchanged, do not try to route it into ICE (it is per-risk,
  ICE is per-control).
- Semantic shift to state in the commit message: once ANY linked control
  has an ice_score, the T1.3 auto-effectiveness engine no longer moves
  that risk's residual (ladder tier 1 wins). The T1.3 cascade still calls
  recompute_residual_for_risk on evidence/audit changes; it recomputes to
  the same ICE-derived values and the 0.05 change gate keeps the history
  table quiet. Risks with no ICE scores keep the T1.3-driven behavior via
  tier 3.
- The appetite engine (event_handlers.py lines ~146 and ~2644, plus
  get_dashboard_stats) compares likelihood x impact against max_score.
  It stays INHERENT-based in THIS plan. The switch to residual
  (COALESCE(rrr, likelihood*impact)) was decided 2026-07-18 and ships as
  PLAN-26 Step 1b; do not implement it here or the PLAN-26 regression
  tests lose their baseline.

## Acceptance criteria (verify each)

- [ ] All 10 test cases above pass; full suite green.
- [ ] Fresh SQLite DB init creates the 3 tables and all 10 new columns.
- [ ] Existing dev DB migrates in place on restart with no traceback and
      the backfills populate irr_score and risk_ref for every legacy row,
      unique refs, no gaps in coverage.
- [ ] Worked example numbers reproduce exactly (IRR 20, LoA 80, RRR 4.0,
      EMV-r 100000).
- [ ] PUT /erm/api/risks/{id} with body {"irr_score": 1} does not change
      irr_score.
- [ ] GET /erm/api/pillars returns the 6 seeded pillars.
- [ ] Auto-elevation path: insert a test GRID finding elevation (or call
      _insert_erm_risk directly in a test) and confirm the created ERM
      risk has risk_ref, irr_score, and rrr set without an app restart.
- [ ] py_compile clean; no console errors on app start.
