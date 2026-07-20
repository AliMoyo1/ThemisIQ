# PLAN-20: AIIA - AI Impact Assessments in Sentinel - active tracking (2026-07-19)

## Status: COMPLETE

## Goal
See plans/PLAN-20-aiia-ai-impact-assessment.md for full spec. Digitize the
AI Impact Questionnaire as a first-class assessment type in Sentinel:
Part 1 system profile, Part 2 eight-dimension impact grid scored via the
ERM rating framework's resolve_band(), editable dimensions, optional
links to RoPA/DPIA/application.

## Changes log

### Step 0: Create active plan file
- [x] plans/PLAN-20-active.md

### Step 1: database.py
- [x] sentinel_aiia / sentinel_aiia_dimensions / sentinel_aiia_impacts tables
      (appended to end of _SENTINEL_TABLES, before line "risk_controls" close)
- [x] seed 8 dimensions in _seed_baseline_data() (count-gated on
      sentinel_aiia_dimensions specifically, inserted right after the
      jurisdiction-config seed block)
- [x] py_compile clean

### Step 2: data_service.py
- [x] list_aiias / get_aiia / create_aiia / update_aiia / delete_aiia
- [x] list_aiia_dimensions / save_aiia_dimensions (rename propagates onto
      historical impact rows; name-collision raises ValueError -> 409 at
      the route layer; upsert semantics, not destructive full-sync)
- [x] scoring via resolve_band() on highest L*I among applicable rows,
      'unrated' when no active ERM framework (never resolve_band's own
      'moderate' fallback); matrix fetched once per call, cross-module
      import inside the function body (no import-time cycle)
- [x] AIIA- ref number generator (_gen_ref, matches DPIA convention)
- [x] py_compile clean

### Step 3: routes.py
- [x] /sentinel/api/aiias CRUD (module.sentinel.access reads,
      sentinel.dpia.manage writes, per plan's explicit split) +
      /api/aiia-dimensions GET/PUT (ValueError -> 409 on rename collision)
- [x] "aiia" added to _SPA_PAGES
- [x] py_compile clean

### Step 4: UI
- [x] Nav entry under Assessments (below Legitimate Interest)
- [x] List view: ref/title/system/autonomy badge/classification chip
      (reuses existing badge-low/medium/high/critical classes only, no
      new colors; 'unrated' renders as a muted italic label, not a badge)
      /status/actions
- [x] Editor drawer (Basics/Impacts/Mitigation/Review tabs), mirrors the
      DPIA ropa-drawer pattern exactly
- [x] Manage dimensions modal (uses Sentinel's own .modal-overlay/.modal-box
      convention, not ERM's .erm-modal-overlay -- confirmed via grep
      before assuming)
- [x] DEVIATION: no live per-row band chip while editing the Impacts
      grid (spec asked for one). Sentinel caches no ERM framework/band
      data client-side (confirmed via grep, zero hits for ERM_FRAMEWORK
      in this file) and reintroducing a hardcoded flat L*I cutoff just
      for a live preview would contradict the very reason PLAN-23
      replaced flat cutoffs with resolve_band() in ERM. The list view
      and the drawer's Mitigation-tab summary both show the real
      server-computed (resolve_band-based) classification after save;
      only the live-while-typing preview is skipped.
- [x] JS syntax verified via node --check

### Step 5: tests - oneforall/tests/test_aiia.py
- [x] 7 test cases (expanded from the plan's 4 minimum): classification
      matches resolve_band() on the real seeded OmniContact framework
      (not a hardcoded band string), unrated when no framework active,
      inapplicable rows excluded from the classification product, rename
      follows history, rename collision raises ValueError, cascade
      delete, deactivate excludes from new-form dimension list but
      history survives on the existing record
- [x] all 7 pass; py_compile clean

### Step 6: verify
- [x] py_compile clean on all 5 touched Python files + test file
- [x] full pytest: 163/163 passing (156 pre-existing + 7 new), 0 regressions
- [x] live browser pass (temp super_admin `_plan20_verify`, id 14):
  - Nav: confirmed "AI Impact (AIIA)" link present under Assessments,
    below Legitimate Interest, correctly wired to /sentinel/aiia.
  - Note: first navigation to /sentinel/aiia 404'd because the running
    dev server's --reload watcher only picked up the database.py change
    and not routes.py/data_service.py/index.html (uvicorn quirk, not an
    app bug) -- a full server restart fixed it immediately, confirmed by
    re-grepping the running file content matched source before restart.
  - Created "Customer churn prediction model" / "ChurnGuard AI": filled
    Basics, selected data categories via chip picker, scored Financial
    dimension at L5xI5 in the Impacts grid, left Mitigation blank, saved.
  - List view showed ref AIIA-20260719-NKLV3, autonomy badge "Decision
    Support", **Overall Classification "Critical"** -- confirmed this
    exactly matches resolve_band(5,5) against the live seeded OmniContact
    framework (same value the test suite asserts programmatically).
  - Reopened via Edit: Basics fields reloaded correctly; Impacts tab
    showed Financial retaining L=5/I=5 and the other 7 dimensions
    correctly present but unscored (placeholder rows); Mitigation tab
    showed the "Overall Classification: Critical" panel for the saved
    record.
  - Manage Dimensions modal: renamed "Security" -> "InfoSec" and
    deactivated "Societal", saved with no error. Verified directly in
    the DB: the rename correctly propagated onto the (unscored)
    sentinel_aiia_impacts row for that dimension, and the deactivated
    Societal row was NOT deleted (is_active=0, row intact) --
    confirming both the rename-follows-history and
    deactivate-preserves-history behaviors work live, not just in
    pytest.
  - Deleted the AIIA via a real DELETE HTTP call (not just the pytest
    path): 200 {"ok": true}, confirmed 0 rows left in both
    sentinel_aiia and sentinel_aiia_impacts.
  - Cleanup: reverted the dimension catalogue to its original seeded
    state (Security renamed back, Societal reactivated) since this is
    shared reference data, not scoped test data. Deleted temp user
    `_plan20_verify` (id 14) and every row referencing it found via a
    schema scan for `REFERENCES users` (user_roles, sessions,
    audit_log, notifications -- 1 row each). Final state confirmed:
    0 sentinel_aiia rows, all 8 dimensions back to their seeded
    names/active state, users back to the original 4
    (admin/compliance/dpo/bcm).
- [x] update plans/README.md

## Deviation notes (see also inline notes in Steps 2-4 above)
- Capability split (module.sentinel.access reads / sentinel.dpia.manage
  writes) follows the plan's explicit instruction, not a verbatim copy
  of DPIA's own gating (which uses sentinel.dpia.manage for reads too).
- No live per-row band chip while editing the Impacts grid (see Step 4
  deviation note) -- Sentinel has no client-side ERM framework/band
  cache, and reintroducing a hardcoded flat cutoff for a "preview"
  would contradict the resolve_band() migration work from Round 6.
  The server-computed classification is shown correctly after save,
  in both the list view and the drawer's Mitigation tab.
