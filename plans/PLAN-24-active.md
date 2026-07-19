# PLAN-24: ERM Assessment Workspace UI - active tracking (2026-07-19)

## Status: COMPLETE

## Goal
See plans/PLAN-24-erm-assessment-workspace.md for full spec. Surface the
PLAN-23 engine in the ERM SPA: CF + EMV-i + pillar in the risk form,
per-control ICE scoring grouped by CF in the drawer, live LoA/LoR/RRR/EMV-r,
P2sT2 filtering, AI ICE suggestion, risk_ref + RRR in register and CSV.

## Changes log

### Step 0: Create active plan file
- [x] plans/PLAN-24-active.md

### Step 1: boot data
- [x] ERM_PILLARS fetched once, module-level array (fetched inside ermLoadFramework())

### Step 2: risk modal additions
- [x] Impacted Pillar select (rsk_pillar)
- [x] EMV-i input (rsk_emvi)
- [x] Contributing factors repeater (rsk_cfs div, ermCfRowHtml/ermAddCfRow)
- [x] IRR display (edit mode)
- [x] ermSaveRisk: collect contributing_factors + impacted_pillar + emv_inherent

### Step 3: drawer assessment section
- [x] risk_ref + IRR chips, LoA/LoR/RRR/EMV-r summary strip (ermRenderAssessSummary)
- [x] group controls by CF (ermRenderAssessGroups)
- [x] ICE select + CF reassign select + Suggest button + evidence chip per control
- [x] evidence_count in list_risk_controls SELECT
- [x] ICE/CF change handler (window.ermChangeControlAssessment: PUT + re-render, no page reload)
- [x] Suggest button wiring (window.ermSuggestIce)

### Step 4: control link modal
- [x] P2sT2 chip filter (ermSetP2st2Filter)
- [x] CF select + initial ICE select
- [x] ermDoLinkControl sends cf_id/ice_score

### Step 5: register + CSV
- [x] Ref column + RRR column in register table
- [x] risk_ref in client-side filter
- [x] CSV export: 6 new columns (risk_ref, irr_score, loa_pct, rrr, emv_inherent, emv_residual)

### Step 6: AI ICE narrative
- [x] suggest_ice_rationale in ai_service.py
- [x] suggest-ice endpoint: ai=1 param wiring, wrapped in try/except

### Step 7: verify
- [x] py_compile clean on all touched files
- [x] full pytest: 148/148 passing (zero regressions)
- [x] live browser pass (worked example end to end, see below)
- [x] update plans/README.md

## Bugs found and fixed during implementation (pre-existing, not introduced by this plan)

1. **`get_unified_register()` never selected `risk_ref`/`rrr`** from
   `erm_enterprise_risks` despite the frontend needing them for the new Ref/RRR
   columns. Fixed by adding `e.risk_ref, e.rrr` to the SELECT.
2. **CSV export queried the wrong table with a latent bug**: `/api/export/csv`
   only queried the generic `risk_register` stub table (missing all full ERM
   enterprise risks) and selected a nonexistent `name` column (real column is
   `title`). Rewrote to query both `erm_enterprise_risks` (aliased
   `title AS name`, plus the 6 new fields) and `risk_register` (stub rows, new
   fields blank).
3. **Evidence deep-link**: the plan's own spec assumed an `entity_type`/
   `entity_id` URL filter on the evidence module that does not exist (verified
   by reading `evidence_index.html`'s JS). Corrected to the real `?module=erm`
   precedent with an honest tooltip instead of a broken promise.
4. **`evidence_links.deleted_at`**: plan text assumed this column existed for
   a soft-delete filter in the evidence_count subquery; verified against the
   real schema and found no such column. Removed the predicate before it could
   cause a runtime SQL error.

## Live browser verification (2026-07-19)

Used a temporary `_plan2425_verify` super_admin account (created and fully
deleted afterward, per user's standing pre-authorization for this session).

1. Created "PLAN24 Worked Example Risk": Impacted Pillar = Technology &
   Innovation, EMV-i = 500000, 2 contributing factors (CF001 "Root cause A",
   CF002 "Root cause B"), Likelihood 4, Financial Exposure dimension = 5
   (Overall Impact MAX = 5). Saved successfully; register showed RSK-0020,
   score 20, CRITICAL.
2. Opened the drawer: Assessment section rendered risk_ref RSK-0020, IRR 20,
   and the LoA/LoR/RRR/EMV-r strip correctly defaulted to LoA 0% / LoR 100% /
   RRR 20 / EMV-r $500,000 (4-tier ladder falling back to IRR with zero
   controls linked, per PLAN-23).
3. Linked control "A.6 AI explainability" to CF001 at ICE 70%. Strip updated
   to LoA 70% / LoR 30% / RRR 6 / EMV-r $150,000 (20 x 0.3, 500000 x 0.3).
4. Linked a 2nd control "A.2 AI impact assessment" to CF001 at ICE 90%. Strip
   updated to **LoA 80% / LoR 20% / RRR 4 / EMV-r $100,000** - exact match to
   the plan's worked example (average of 70/90 = 80% CF assurance).
5. Set the first control's ICE to 0%: strip correctly showed a real computed
   **LoA 45% / LoR 55% / RRR 11 / EMV-r $275,000** (average of 0/90), not a
   "not yet scored" null state - confirms the strict-null-check edge case
   works as designed.
6. Reset ICE back to 70%/90%. Tested P2sT2 filter chips in the Link Control
   modal: "Process" and "Technology" chips both correctly filtered to "No
   controls match" (no seeded canonical controls have p2st2_category set
   yet - a data gap, not a bug), and "All" correctly restored the full list.
7. Exported CSV via direct fetch to `/erm/api/export/csv`: confirmed header
   row includes `risk_ref,irr_score,loa_pct,rrr,emv_inherent,emv_residual` and
   the RSK-0020 data row has correct values
   (`RSK-0020,20,80,4.0,500000.0,100000.0`).
8. Cleanup: deleted risk 265 via `DELETE /erm/api/risks/265` (risk_controls
   rows cascade-deleted per the existing `ON DELETE CASCADE` FK, confirmed
   register count returned to 29 risks). Deleted the temp verify user + role
   grant via direct SQL; confirmed final user list matches the original 4
   users (admin, compliance, dpo, bcm).

No console errors traced to this plan's changes. One pre-existing, unrelated
console error (`/api/command-centre/stats` 500 due to a `NameError` in
`modules/launcher/routes_dashboard.py`) was observed again - same bug found
during PLAN-23 verification, out of scope here.

Not yet committed - awaiting explicit user go-ahead per standing instruction.
