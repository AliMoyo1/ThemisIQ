# PLAN-27: ERM Objectives Registry + Pillars Admin - active tracking (2026-07-19)

## Status: COMPLETE

## Goal
See plans/PLAN-27-erm-objectives-pillars.md for full spec. Objectives
registry (strategic/standard/departmental) with hierarchy rules, risk
linkage (objective_id + risk_context), pillar CRUD to complete PLAN-23's
read-only endpoint, and an Objectives & Pillars admin UI.

## Changes log

### Step 0: Create active plan file
- [x] plans/PLAN-27-active.md

### Step 1: database.py
- [x] erm_objectives table (inserted after erm_pillars, auto-converted to PG)
- [x] erm_enterprise_risks.objective_id + risk_context column migrations
- [x] verified against a fresh SQLite DB: table + both columns created correctly

### Step 2: data_service.py
- [x] list_objectives / create_objective / update_objective / archive_objective
- [x] _validate_objective helper (hierarchy rules)
- [x] create_pillar / update_pillar / deactivate_pillar
- [x] list_pillars gains include_inactive param (default False, backward compatible)
- [x] create_enterprise_risk / update_enterprise_risk: objective_id + risk_context (+ _validate_risk_linkage)
- [x] get_enterprise_risk: objective_title + strategic_objective_title (2-level self-join)
- [x] py_compile clean

### Step 3: routes.py
- [x] GET/POST/PUT objectives + archive endpoint
- [x] GET (include_inactive)/POST/PUT pillars + deactivate endpoint
- [x] "objectives" added to _SPA_PAGES
- [x] py_compile clean

### Step 4: UI
- [x] New "objectives" SPA page (Objectives & Pillars admin): nav link gated on
      can_manage_frameworks, _SPA_PAGES/_routes/_crumbs/switch wired, objectives
      table (grouped strategic/standard/departmental with type badges), pillars
      list, add/edit modals for both, archive/deactivate actions
- [x] Risk modal: Risk Context select + Objective select (optgroup by type,
      client-side filtered via ermFilterObjectiveOptions, always includes the
      currently-linked objective even if archived/filtered out by type)
- [x] Drawer: risk_context badge + "{objective} supporting {strategic obj}" line
- [x] Dashboard filter: Objective select added to filter bar + _posture_where +
      GET /api/dashboard objective_id param (int-cast guarded, 400 on invalid)
- [x] ERM_OBJECTIVES fetched once at boot in ermLoadFramework() (same pattern as ERM_PILLARS)
- [x] JS syntax verified via node --check; Python files compile clean

### Step 5: tests - oneforall/tests/test_erm_objectives.py
- [x] 6 test cases, all passing in isolation on first run

### Step 6: verify
- [x] py_compile clean on database.py, modules/erm/data_service.py, modules/erm/routes.py, core/event_handlers.py, tests/test_erm_objectives.py
- [x] full pytest: 148/148 passing (zero regressions; new file's 6 cases included)
- [x] live browser pass (see below)
- [x] update plans/README.md

## Live browser verification (2026-07-19)

Used a temporary `_plan27_verify` super_admin account (created only after
asking the user for fresh authorization, since the PLAN-26 grant was scoped
to that plan specifically; created and fully deleted afterward). Restarted
the AegisGRC preview server first to load the new code.

1. Navigated directly to `/erm/objectives`: nav link "Objectives & Pillars"
   correctly gated on `can_manage_frameworks`, page renders an empty
   Objectives table with a helpful empty state, and the Pillars list shows
   all 6 seeded pillars (Customer, Financial, Operational Excellence,
   People, Reputation & Brand, Technology & Innovation) each with
   Edit/Deactivate.
2. Created a strategic objective "Grow ARR" via the modal - confirmed
   Parent/Standard Ref fields are hidden for the default "Strategic" type
   (`objToggleTypeFields`). Saved successfully, shown with a purple
   "Strategic" badge.
3. Created a standard objective "ISMS: protect customer data": switching
   Type to "Standard" correctly revealed both the "Supports (Strategic
   Objective)" select (listing only "Grow ARR", confirming the
   strategic-only filter) and the "Standard Ref" input. Set standard_ref
   "ISO 27001" and parent "Grow ARR". Saved successfully, table showed
   Standard Ref "ISO 27001" and Supports "Grow ARR".
4. Created "PLAN27 Chain Verification Risk" (L3xI4=12) via the register's
   Add Risk modal: set Risk Context = Strategic (confirmed the Objective
   select re-filtered live via `ermFilterObjectiveOptions` to show
   strategic+standard objectives), selected Objective = "ISMS: protect
   customer data". Saved successfully (RSK-0023, score 12, HIGH).
5. Opened the risk's drawer: confirmed the Details grid shows a "Risk
   Context: Strategic" badge and an "Objective: ISMS: protect customer
   data supporting Grow ARR" line - the exact support-chain text the plan
   asked for. Also incidentally confirmed the PLAN-25/26 integrations
   still work on this new risk (Assessment strip, Treatments section
   showing "Within appetite (Strategic Risk)").
6. Confirmed the register still renders normally throughout (no
   regressions to existing rows/counts).
7. Cleanup: deleted risk 273 via `DELETE /erm/api/risks/273` (confirmed
   zero orphaned `erm_risk_dimension_scores`/`erm_risk_score_history` rows
   afterward). Deleted the two test objectives via direct SQL (the app
   only exposes archive, by design, but full removal is the right test-
   cleanup action so no trace of test data remains) - confirmed
   `erm_objectives` back to 0 rows. Register count returned to 21 open
   risks (the exact pre-test baseline). Deleted the temp verify user +
   role grant; confirmed the final user list matches the original 4 users
   (admin, compliance, dpo, bcm).

No console errors traced to this plan's changes.
