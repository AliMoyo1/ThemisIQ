# PLAN-23: ERM Contributing Factors + ICE Scoring Engine - active tracking (2026-07-18)

## Status: COMPLETE (2026-07-19)

## Goal
See plans/PLAN-23-erm-cf-ice-engine.md for full spec. Backend-only: CF
tables, ICE scoring, frozen IRR, EMV, risk refs, pillars, score history.

## Changes log

### Step 0: Create active plan file
- [x] plans/PLAN-23-active.md

### Step 1: database.py - three new tables
- [x] erm_contributing_factors
- [x] erm_risk_score_history
- [x] erm_pillars

### Step 2: database.py - column migrations
- [x] 10 new columns across erm_enterprise_risks, risk_controls, canonical_controls

### Step 3: database.py - seeds and backfill
- [x] Pillar seeds (6 pillars, count-gated)
- [x] IRR backfill (idempotent)
- [x] risk_ref backfill (idempotent, Python loop)

### Step 4: data_service.py - engine rewrite
- [x] ICE_ALLOWED constant
- [x] _next_ref helper
- [x] _ice_rollup helper
- [x] recompute_residual_for_risk rewrite (4-tier ladder)
- [x] _snapshot_history helper
- [x] create_enterprise_risk: CF + IRR + ref + EMV
- [x] _save_contributing_factors / _get_contributing_factors
- [x] update_enterprise_risk: CF + EMV + pillar + frozen fields
- [x] get_enterprise_risk: attach contributing_factors
- [x] delete_enterprise_risk: cleanup CFs + history
- [x] list_risk_controls: extend SELECT
- [x] set_control_assessment (new)
- [x] suggest_ice_for_control (new)
- [x] list_pillars (new)
- [x] list_contributing_factors / add_contributing_factor / update_contributing_factor / delete_contributing_factor / get_cf_risk_id (new, support routes)

### Step 5: routes.py - new endpoints
- [x] GET /api/risks/{risk_id}/cfs
- [x] POST /api/risks/{risk_id}/cfs
- [x] PUT /api/cfs/{cf_id}
- [x] DELETE /api/cfs/{cf_id}
- [x] PUT /api/risks/{risk_id}/controls/{control_id}
- [x] GET /api/risks/{risk_id}/controls/{control_id}/suggest-ice
- [x] GET /api/pillars
- [x] extend POST controls link endpoint with cf_id/ice_score
- [x] BU scoping on CF/ICE endpoints (_check_risk_scope helper)

### Step 5b: event_handlers.py auto-elevation
- [x] _insert_erm_risk gets risk_ref + irr_score + recompute call

### Step 6: governance p2st2_category
- [x] create_canonical_control + update: p2st2_category field
- [x] list_canonical_controls: returns the column automatically (cc.*)
- [x] index.html: P2sT2 dropdown in control modal (form-row-3, load + save wired)

### Step 7: tests
- [ ] tests/test_erm_ice_engine.py (10 cases)

### Step 8: verification
- [x] py_compile all touched files: clean (database.py, modules/erm/data_service.py,
      modules/erm/routes.py, core/event_handlers.py, modules/governance/data_service.py,
      tests/test_erm_ice_engine.py)
- [x] full pytest suite: 148/148 pass (including 10/10 new ICE-engine tests)
- [x] live browser pass (temp super_admin user `_plan23_verify`, created and deleted
      afterward with explicit user authorization since auto-mode's safety classifier
      blocks unilateral account creation):
      - POST /erm/api/risks (L4/I5, emv_inherent 500000, 2 CFs): risk_ref RSK-0020,
        irr_score 20, rrr 20.0, residual_score 20, CF001/CF002 with correct refs.
      - Linked 2 real canonical controls, set ICE 70 then 90: loa_pct 80, rrr 4.0,
        residual_score 4, emv_residual 100000 -- exact match to the plan's worked
        example.
      - PUT with {likelihood:1, irr_score:999}: irr_score stayed 20 (frozen),
        inherent_score correctly became 5, rrr stayed 4.0 (ICE tier still governs).
      - Invalid ICE 45 rejected with 400 and the exact allowed-values message.
      - GET .../controls: ice_score/p2st2_category/cf_ref all returned correctly.
      - GET /erm/api/pillars: all 6 seeded pillars returned.
      - Test risk, both test controls, and the temp user all deleted and confirmed
        gone afterward (404 on the risk, back to the original 4 real users).
- [x] update plans/README.md Round 6 table
- [ ] commit -- not yet done; awaiting explicit user go-ahead per standing git safety rule

## Drive-by fixes discovered during verification (unrelated to PLAN-23's own scope,
but blocking its "full suite green" acceptance criterion)

1. **Pre-existing test-isolation bug** (`tests/conftest.py`): `core/advisor.py`
   lazy-imports `modules.erm.data_service` inside a function body. When
   `tests/test_advisor.py` (which patches `database.get_db` to a throwaway stub
   for its own fixture) happens to trigger that lazy import first, `erm_ds.get_db`
   permanently freezes onto the stub for the rest of the pytest process -- a
   later restore of `database.get_db` does not fix an already-bound name in a
   different module. Confirmed via `git stash` that this reproduces on the clean
   master baseline (test_ropa_dpia_link.py fails the same way), so it predates
   PLAN-23. Fixed by pre-importing `modules.erm.data_service` and
   `modules.governance.data_service` at the top of conftest.py, before any test
   fixture can run.
2. **Schema drift** (`tests/test_governance_controls.py`): its hand-rolled
   in-memory schema for `canonical_controls`, `risk_controls`, and
   `erm_enterprise_risks` was missing the new PLAN-23 columns/tables
   (p2st2_category, cf_id, ice_score, irr_score, rrr, loa_pct, emv_inherent,
   emv_residual, risk_ref, impacted_pillar, erm_contributing_factors,
   erm_risk_score_history). Updated to match the real schema.
