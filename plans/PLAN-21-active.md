# PLAN-21: AI controls catalogue + AIMS/ORAAT risk engine in ORM - active tracking (2026-07-19)

## Status: COMPLETE (verification passed)

## Goal
See plans/PLAN-21-ai-controls-catalogue-aims-engine.md for full spec.
Digitize the AI controls taxonomy (96 controls, editable in-app) + the
AIMS risk register (objectives, EMV, IRR, multi-control linkage with
ICE, per-pillar aggregation, residual rating/EMV, treatments) + ORAAT
mode (control-centric variant). Scoring convention: ice_score INTEGER
percent {0,10,...,90} (higher = stronger, matching PLAN-23's ERM ICE
convention exactly, not the legacy sheets' inverted 1-10 scale).

## Changes log

### Step 0: Create active plan file
- [x] plans/PLAN-21-active.md

### Step 1: Extraction script
- [x] scripts/extract_ai_controls.py (openpyxl, normalizes dirty pillar
      values: splits on "/" takes first segment, maps "System"->"Systems")
- [x] Ran against C:\Users\isadmin\Downloads\Taxonomy.xlsx: exactly 96
      rows extracted, all pillar values land in {People, Process,
      Systems, Technology, Tools} (People 15, Process 63, Systems 10,
      Technology 5, Tools 3)
- [x] seeds/ai_controls_seed.json generated (not committed to git --
      only the user commits, per standing rule; file exists on disk
      ready to be committed alongside the rest of this plan)
- [x] py_compile clean

### Step 2: database.py
- [x] ai_control_catalogue / aims_assessments / aims_risks /
      aims_risk_controls tables (appended to _ERM_ORM_TABLES; NOTE this
      is the same blob PLAN-20's sentinel_aiia tables landed in too --
      harmless, the Python variable name is organizational only, all
      blobs get executed together at init time regardless of name)
- [x] DEVIATION (per the plan's own "ALIGNMENT WITH ERM v2 ICE" section,
      which explicitly supersedes the earlier raw-SQL snippet in the same
      doc): aims_risk_controls stores `ice_score` INTEGER percent
      {0,10,...,90}, NOT `ice_factor` REAL 0.0-1.0. ice_factor is derived
      at read/compute time as (100-ice_score)/100.0, matching PLAN-23's
      ERM ICE convention exactly so ORM/AIMS is born converged, not a
      third dialect.
- [x] catalogue seed hook in _seed_baseline_data() (count-gated on
      ai_control_catalogue, reads the committed
      seeds/ai_controls_seed.json, never the xlsx; missing-file path
      logs a warning and leaves the catalogue empty rather than crashing
      startup)
- [x] BUG CAUGHT AND FIXED before it could ship: my first draft of the
      missing-file warning branch called `logging.getLogger(__name__)`
      but database.py has no top-level `import logging` (confirmed via
      grep) -- would have raised NameError the first time a fresh clone
      without the seed JSON hit that branch. Fixed with a local
      `import logging as _logging`, matching this file's existing
      local-import convention for seed-block dependencies.
- [x] py_compile clean
- [x] fresh SQLite smoke test: all 4 tables created (10/10/22/15
      columns), catalogue seeded with exactly 96 rows, source='built_in'
      confirmed on sample rows

### Step 3: data_service.py
- [x] catalogue CRUD (delete refuses when referenced -- built_in OR
      linked -- deactivate instead; reimplemented `_next_catalogue_ref`/
      `_next_aims_ref` locally in orm/data_service.py rather than
      cross-importing ERM's `_next_ref`, since RCSA -- the module the
      plan said to mirror -- turned out not to actually use a formatted
      ref generator at all)
- [x] AIMS assessment/risk/risk-control CRUD (`_AIMS_RISK_FIELDS` /
      `_AIMS_RC_FIELDS` tuples, `_TREATMENTS` validation, cascade delete
      of risk_controls before risk deletion)
- [x] compute_aims_risk() - the one scoring function: irr = L*I,
      mean_factor over linked controls' (100-ice_score)/100 (1.0 when
      unlinked), residual_rating = round(irr*mean_factor,2),
      residual_emv = round(emv_inherent*mean_factor,2) (same multiplier
      for both, per the plan's convention note -- the source sheets use
      opposite directions for rating vs EMV, which is the sheet's bug,
      not replicated here). per_pillar buckets each linked control under
      its catalogue row's pillar, falling back to the risk's own
      impacted_pillar only for controls with no catalogue link.
- [x] get_aims_aggregation() - one row per risk, computed + SUM(treatment_cost)
- [x] py_compile clean

### Step 3.5: tests - oneforall/tests/test_aims_engine.py
- [x] 5 test cases written and passing (5/5):
      test_convention_worked_example, test_unlinked_risk_full_residual,
      test_catalogue_delete_refused_when_linked (also asserts per_pillar
      buckets a catalogue-linked control under its own pillar, not the
      risk's impacted_pillar fallback), test_oraat_legacy_ice_score_10_input,
      test_fresh_db_seeds_96_catalogue_controls
- [x] BUG CAUGHT in the plan's own hand-typed test data: the plan's Step 6
      spec says "residual_rating 10.63" for the convention case (IRR 25,
      mean_factor 0.425), but Python's actual `round(25*0.425, 2)` is
      **10.62** -- confirmed via a throwaway script before writing the
      assertion. 0.425 is not exactly representable in binary floating
      point, so 25*0.425 lands a hair off the mathematical 10.625 before
      rounding. mean_factor (0.425), residual_emv (850000.0), and the
      full ORAAT case (ice_score_10=1 -> factor 0.1 -> residual 2.5) all
      matched the plan's stated values exactly -- only this one figure
      was off. Trusted the empirically-verified value (10.62) over the
      hand-typed one, per the plan's own "(Pin YOUR computed values by
      hand.)" instruction and this session's established practice
      (PLAN-28's grounded-citation test, PLAN-20's resolve_band test) of
      computing expected values via the real function rather than a
      hardcoded guess.

### Step 4: routes.py
- [x] /orm/api/ai-controls full CRUD (GET list/detail gated
      module.orm.access; POST/PUT/DELETE gated orm.event.manage; pillar
      validation errors -> 400, delete-refusal ValueError -> 409 matching
      Sentinel's AIIA dimension-rename-collision precedent, not ERM's
      blanket 400 -- 409 Conflict is the more correct code for "can't
      delete due to a conflicting reference/state")
- [x] /orm/api/aims full CRUD: assessments, risks, risk<->control links,
      aggregation JSON + CSV export (mirrors RCSA's URL shape and gating
      exactly: /aims/{id}, /aims/{id}/risks, /aims/risks/{id},
      /aims/risks/{id}/controls, /aims/controls/{id})
- [x] _SPA_PAGES extended with "ai-controls" and "aims"
- [x] py_compile clean

### Step 5: UI (modules/orm/templates/index.html)
- [x] Nav links: "AI Controls" and "AI Risk (AIMS)" under RCSA
- [x] Upgraded shared apiFetch() to parse the JSON body's `detail` field
      on error responses (previously threw a bare "API 409" with no
      message) -- matches ERM's already-improved apiFetch precedent.
      Necessary so the catalogue delete-refusal reason (built-in vs
      linked) actually reaches the user instead of a generic toast.
      Confirmed no existing ORM code reads e.message, so this is a
      backward-compatible upgrade, not a behavior change for old callers.
- [x] AI Controls Catalogue page: pillar filter chips, show/hide
      deactivated toggle, add/edit modal (ref read-only once created --
      editing an existing ref would silently NULL it out via PUT
      omission logic otherwise), per-row activate/deactivate toggle,
      delete only offered when source != built_in and link_count == 0
- [x] AI Risk (AIMS) page: assessments list (mode badge AIMS/ORAAT,
      stats strip) -> assessment drawer (risk register grid, colored
      residual chip vs target/appetite/tolerance thresholds, CSV export
      link) -> risk detail drawer (computed panel: IRR/mean
      factor/residual rating+chip/residual EMV; per-pillar mitigation
      mini-bars computed as (1-mean_factor) since factor is remaining-risk,
      not strength; linked-controls table) -> risk-control link modal
      (catalogue picker grouped by pillar via optgroup, ICE % select PLUS
      a legacy ORAAT 1-10 fallback input that sends ice_score_10 and lets
      the backend's existing precedence resolve it, treatment/owner/cost/
      due date/evidence/status)
- [x] Extracted the <script> block and syntax-checked it with `node
      --check` after stripping Jinja {{ }}/{% %} markup -- clean

### Step 6: full test suite + verify
- [x] py_compile clean: database.py, modules/orm/data_service.py,
      modules/orm/routes.py
- [x] full pytest: 168 passed (163 prior + 5 new test_aims_engine.py),
      zero regressions

### Step 7: live browser verification -- COMPLETE, 2 real bugs found and fixed
Temp super_admin account (`_plan21_verify`) created via direct DB insert
(bcrypt hash via core.auth.hash_password, role_key='super_admin'), used to
log into the real running dev server (AegisGRC launch config, port 8080)
and drive every new page/endpoint over real HTTP.

**AI Controls Catalogue page**: pillar filter chips confirmed working
(clicked Technology, list correctly narrowed to AIC27/36/64/66...). Created
a custom control ("Test Custom Control Alpha", Systems pillar) -> got
`ref="AIC97"`, confirming `_next_catalogue_ref` correctly continues past
the 96 seeded rows. Attempted DELETE on a built-in control (AIC1) directly
against the API -> got the exact expected 409 + message "Built-in controls
cannot be deleted. Deactivate instead." Deactivate/reactivate cycle on the
custom control confirmed via PUT is_active 0/1 round-trip.

**AIMS assessment -> risk -> controls flow**: created assessment
"PLAN21 Verification Assessment" (mode=aims) -> got ref "AIMS-1". Added one
risk (L5xI5, EMV 2,000,000, thresholds target/appetite/tolerance 5/10/15)
-> risk detail drawer showed IRR 25, Mean Factor 100%, Residual 25, EMV
$2.0M with zero controls linked (full-exposure default, matches the
unlinked-risk test). Linked 3 controls one at a time through the real
modal: AIC1 (People) at ICE 70%, AIC22 (Systems, built-in) at ICE 40%,
AIC97 (Systems, custom) via the **legacy ORAAT 1-10 input** (typed "2" ->
confirmed stored as ice_score=80, i.e. 100-2*10). Final computed panel:
Mean Factor 37% (0.3+0.6+0.2)/3=0.3667 -> round(*100)=37, Residual Rating
9.17 (25*0.3667=9.1667->9.17), Residual EMV $733.3K
(2,000,000*0.3667=733,333.33) -- every figure hand-verified against the
formula and exactly correct. Per-pillar mitigation bars: People "1 ctrl,
70%", Systems "2 ctrl, 60%" (correctly merges the built-in AIC22 AND the
custom AIC97 into one Systems bucket via each control's own catalogue
pillar, not the risk's `impacted_pillar` fallback, which was Technology).

**Bug 1 (found + fixed): CSV export 403'd for every user, including
super_admin.** My new `GET /api/aims/{id}/aggregation/csv` endpoint was
gated `@require_capability("orm.event.view")`, copied directly from the
existing `GET /api/export/csv` (ORM events) endpoint at routes.py:576.
Grepped core/rbac.py and confirmed `orm.event.view` is **not a registered
capability key at all** -- `has_capability()` denies unconditionally on an
unknown key (rbac.py:260-261, "Unknown capability -- deny"), so the
pre-existing ORM events CSV export has been silently 403ing for everyone
this whole time too. That endpoint predates this plan and is out of scope
to fix here (flagged separately, not touched). Fixed my own endpoint by
switching to `module.orm.access` (matches every other GET in this file).
Confirmed 200 after a server restart (uvicorn --reload picked up the file
change per its log but continued serving 403 on two subsequent requests --
same reload-flakiness already seen in PLAN-20; a full stop+restart made it
serve the fix).

**Bug 2 (found + fixed): every AIMS risk's `ref` column was permanently
NULL.** The plan's own spec says the risk register grid and the
aggregation CSV should show a `ref` column, but no ref-generator was ever
wired into `create_aims_risk` (I had built `_next_aims_ref` for
assessments and `_next_catalogue_ref` for controls, but nothing for
individual risks). Confirmed via the live CSV export showing a blank first
column. RCSA has no precedent for this (its risks have no ref column at
all), so there was nothing to copy. Added `_next_risk_ref(db,
assessment_id)` in modules/orm/data_service.py -- same max-existing-suffix
+1 pattern as the other two generators, but scoped to `assessment_id` so
each assessment's risks number independently starting at "R1" (not a
single global counter). Wired into `create_aims_risk`. Added
`test_risk_ref_auto_generated_per_assessment` to test_aims_engine.py
(6th test) confirming both same-assessment sequencing (R1, R2) and
cross-assessment independence (a second assessment's first risk is also
R1, not R3). Re-ran full pytest after both fixes: 169 passed.

**Cleanup**: deleted the extra ref-generation-check risk, the main risk
(cascaded its 3 control links), the assessment, and the now-unlinked custom
control (AIC97) -- all via real HTTP DELETE through the app. Deleted the
temp user and its sessions/user_roles/audit_log rows via direct DB
statements. Final DB state confirmed: 4 users (back to original count),
0 aims_assessments, 0 aims_risks, 0 aims_risk_controls, 96
ai_control_catalogue rows all source='built_in', 0 custom rows, no
'plan21' username remaining.

Not committed -- per standing rule, commit only on explicit user instruction.
