# PLAN-25: ERM Per-CF Treatments - active tracking (2026-07-19)

## Status: COMPLETE

## Goal
See plans/PLAN-25-erm-cf-treatments.md for full spec. One treatment record
per contributing factor: auto-assigned TR refs paired with CF refs, 5
treatment options including Exploit, Accept-at-70%-assurance suggestion,
EMV-a, owner, due date, interdependencies.

## Changes log

### Step 0: Create active plan file
- [x] plans/PLAN-25-active.md

### Step 1: database.py
- [x] erm_cf_treatments table (inserted after erm_contributing_factors, auto-converted to PG via _to_pg_schema)

### Step 2: data_service.py
- [x] TREATMENT_OPTIONS / TREATMENT_STATUSES constants
- [x] _cf_assurance
- [x] ensure_treatments_for_risk
- [x] list_treatments
- [x] update_treatment
- [x] get_risk_emv_a_total + wire into get_enterprise_risk (emv_a_total field)
- [x] _save_contributing_factors: explicit DELETE FROM erm_cf_treatments on CF delete
- [x] delete_contributing_factor: same explicit delete (2nd CF-delete code path)
- [x] delete_enterprise_risk: explicit DELETE FROM erm_cf_treatments

### Step 3: routes.py
- [x] GET /api/risks/{risk_id}/treatments
- [x] PUT /api/treatments/{treatment_id} (+ get_treatment_risk_id helper for BU-scope check)

### Step 4: UI - drawer Treatment section
- [x] Treatment cards (option/action_steps/emv_a/owner/due_date/status/interdependencies)
- [x] Suggestion badge, OVERDUE chip, EMV-a total footer, appetite status chip
- [x] JS syntax verified via node --check on extracted script block

### Step 5: tests
- [x] oneforall/tests/test_erm_treatments.py (7 cases, all passing in isolation)

### Step 6: verify
- [x] py_compile clean on database.py, modules/erm/data_service.py, modules/erm/routes.py, tests/test_erm_treatments.py
- [x] full pytest: 136/136 passing (zero regressions; new file's 7 cases included)
- [x] live browser pass (see below)
- [x] update plans/README.md

## Live browser verification (2026-07-19)

Used a temporary `_plan25_verify` super_admin account (created and fully
deleted afterward, per the user's standing pre-authorization for this
session). Restarted the AegisGRC preview server first to load the new code
and confirmed `erm_cf_treatments` was created on startup.

1. Created "PLAN25 Treatments Worked Example" via the API (title, likelihood
   4, one dimension score of 5 for Overall Impact MAX=5, EMV-i 500000, two
   contributing factors) - same L4xI5=IRR 20 shape as the PLAN-24 worked
   example. Register showed RSK-0021, score 20, CRITICAL.
2. Linked 2 pre-existing canonical controls ("AI explainability", "AI impact
   assessment" - ids 71/67, not created by this session) to CF001 at ICE
   70% and 90%. Confirmed via the drawer's Assessment section: RRR 4, EMV-r
   $100,000, CF001 "80% ASSURANCE" - matching PLAN-24's worked example
   exactly.
3. Opened the drawer and scrolled to the new "Treatments" section: two
   cards rendered, TR001/CF001 ("Root cause A") and TR002/CF002 ("Root
   cause B"). TR001's treatment_option was already "Accept" - confirms
   ensure_treatments_for_risk's Accept-at-70%-assurance rule fired
   correctly at row-creation time (both controls were already scored before
   the treatments were ever fetched/created). TR002 (no scored controls)
   defaulted to "Mitigate".
4. To specifically verify the "Suggested: Accept" badge (which only shows
   when the current option differs from the live suggestion), changed
   TR001's option to Exploit, set EMV-a to 20000, and set the due date to
   2026-07-18 (yesterday, since today is 2026-07-19), then clicked Save.
   Confirmed: the card re-rendered showing treatment_option "Exploit",
   EMV-A "20000", due date "18/07/2026", an **OVERDUE** chip, and a
   "Suggested: Accept (assurance 80%)" badge (now visible since option no
   longer matches the suggestion) - exactly the Step 6 acceptance script.
5. Confirmed the footer reads **"EMV-a total: $20,000"**.
6. Confirmed the legacy risk-level "Treatment" section (Strategy: Mitigate,
   "No treatment plan recorded.") above the new Treatments section is
   completely unchanged - the per-CF treatments are additive, not a
   replacement.
7. Confirmed via `grep` that only one `/api/treatments` route exists
   (`PUT /api/treatments/{treatment_id}`) - no POST or DELETE.
8. Cleanup: deleted risk 267 via `DELETE /erm/api/risks/267`. Verified zero
   orphaned rows in `erm_cf_treatments`, `erm_contributing_factors`, and
   `risk_controls` for that risk_id, and confirmed both pre-existing
   canonical controls (ids 71, 67) were untouched. Deleted the temp verify
   user + role grant via direct SQL; confirmed the final user list matches
   the original 4 users (admin, compliance, dpo, bcm). Register count
   returned to 30 (the baseline after PLAN-24's own cleanup).

Not yet committed - awaiting explicit user go-ahead per standing
instruction (never commit unless explicitly asked).
