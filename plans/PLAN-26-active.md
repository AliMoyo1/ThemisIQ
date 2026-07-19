# PLAN-26: ERM Dashboard v2 - active tracking (2026-07-19)

## Status: COMPLETE

## Goal
See plans/PLAN-26-erm-dashboard-v2.md for full spec. High-RRR watchlist,
posture averages (IRR/RRR/LoA/LoR), EMV-i/r/a totals, trajectory graph from
score history, filter bar (category/pillar/BU/period), and the decided
appetite-vs-residual-exposure semantics change (3 sites).

## Changes log

### Step 0: Create active plan file
- [x] plans/PLAN-26-active.md

### Step 1: data_service.py - posture stats
- [x] _posture_where(filters) helper
- [x] get_dashboard_stats(filters=None) gains posture key (_get_posture_stats)
- [x] trajectory bucketing in Python (no strftime/to_char); period filter narrows the 24mo window

### Step 1b: appetite residual semantics (3 sites)
- [x] get_dashboard_stats appetite_breaches query -> COALESCE(e.rrr, e.likelihood*e.impact)
- [x] get_appetite_status: all 3 likelihood*impact sites -> COALESCE(rrr, likelihood*impact)
- [x] core/event_handlers.py appetite checks (_check_and_emit_appetite_breach, erm_risk_closed_checks_appetite)
- [x] UI tooltip: ermRenderAppetitePanel category row + Appetite page subtitle

### Step 2: routes.py - GET /api/dashboard filters
- [x] category/business_unit_id/pillar/period query params
- [x] period -> date_from translation (year/quarter/month)
- [x] business_unit_id int-cast guarded, 400 on invalid
- [x] confirmed GET /governance/api/business-units exists, governance.entities.view = all roles

### Step 3: UI - dashboard section
- [x] Filter bar (Category/Pillar/Business Unit/Period) - dashCatFilter/dashPillarFilter/dashBuFilter/dashPeriodFilter
- [x] Risk posture KPI row (6-7 cards via statCards())
- [x] High-risk watchlist panel (ermRenderWatchlist)
- [x] Trajectory SVG polyline chart (ermRenderTrajectory, ~30 lines)
- [x] Wire into ermLoadDashboard() (query string + 3 renderer calls)
- [x] ermPopulateCategoryFilters extended for dashCatFilter/dashPillarFilter
- [x] ermPopulateBuFilter (silent-skip pattern) wired into init IIFE
- [x] JS syntax verified via node --check

### Step 4: tests - oneforall/tests/test_erm_dashboard_v2.py
- [x] 6 test cases, all passing in isolation on first run

### Step 5: verify
- [x] py_compile clean on database.py, modules/erm/data_service.py, modules/erm/routes.py, core/event_handlers.py, tests/test_erm_dashboard_v2.py
- [x] full pytest: 142/142 passing (zero regressions; new file's 6 cases included)
- [x] live browser pass (see below)
- [x] update plans/README.md

## Bug found and fixed during live verification

**`ermLoadDashboard` was not exposed on `window`.** Every new filter select
uses an inline `onchange="ermLoadDashboard()"` attribute, which Chrome
evaluates in the *global* scope — but the function was declared as a plain
`async function ermLoadDashboard(){...}` local to the SPA's enclosing IIFE
(unlike e.g. `window.ermRenderRegister=function(){...}`, which the
pre-existing register-page category filter already relied on for the exact
same reason). Every filter change silently threw
`ermLoadDashboard is not defined` in the console and did nothing. Fixed by
changing the declaration to `window.ermLoadDashboard=async function(){...}`,
matching the codebase's established pattern for every other inline-onchange
target. Verified safe: every other reference to `ermLoadDashboard()` in the
file lives inside a callback (router dispatch, setTimeout, setInterval) that
only executes after the whole script has run once, so the switch from a
hoisted declaration to an assignment introduces no ordering hazard.

## Live browser verification (2026-07-19)

Used a temporary `_plan26_verify` super_admin account (created only after
asking the user for fresh authorization, since the earlier "next 2 plans"
grant from the PLAN-24/25 session was already consumed; created and fully
deleted afterward). Restarted the AegisGRC preview server first to load the
new code.

1. Dashboard loaded with the new filter bar (Category/Pillar/Business
   Unit/Period - all 4 selects populated correctly, including Business
   Unit via a real `GET /governance/api/business-units` call returning
   "Company"), the Risk Posture KPI row, High-Risk Watchlist, and Risk
   Trajectory panel, all below the legacy (unfiltered) hero stats.
2. Watchlist showed RSK-0017 and RSK-0018 (both pre-existing "AI
   Predictive Alert" risks at RRR 16). Clicking a watchlist row opened the
   real risk drawer for RSK-0017, confirming matching RRR 16 in the
   Assessment section and even a live "Above appetite (Operational Risk)"
   tag from the PLAN-25 Treatments footer - cross-confirming PLAN-25 and
   PLAN-26 agree on the same risk.
3. Trajectory showed "Not enough history yet" by default (correct: no
   >=2-month spread in this dataset yet).
4. **Bug found and fixed** (see above) while testing the Period filter.
5. After the fix: created a backdated test risk (id 269, L5xI5, `created_at`
   force-set to 100 days ago via direct SQL). With Period = All time, it
   correctly appeared in the watchlist (RSK-0022, RRR 25) and pulled the
   posture averages up (avg_irr 17.8, avg_rrr 17.5). Switching Period to
   "Last month" correctly excluded it - averages reverted to the exact
   pre-backdated values (17.4 / 16) and it disappeared from the watchlist.
   This proves the filter genuinely narrows the result set, not just that
   the query string is sent.
6. Created a second test risk (id 270), linked an existing canonical
   control, scored it ICE 20 then (1.5s later) ICE 60 - two real score-
   history rows a few seconds apart. Confirmed via a category-filtered
   dashboard fetch that both rows bucketed into a single `"2026-07"` entry
   (avg_rrr 18.3, avg_irr 25), and confirmed live in the browser that the
   Trajectory panel correctly showed "Not enough history yet" for that
   filtered view despite 2 underlying history rows existing - proving the
   `buckets.length < 2` guard operates on bucket count, not raw row count.
7. Cleanup: deleted risk 269 and 270 via the API. Discovered a third risk
   (id 271, "Data Breach Risk: PLAN26 Trajectory Test") had been silently
   auto-elevated as a side effect of creating risk 270 - deleted it too.
   Confirmed the open-risk count returned to exactly 20 (the pre-test
   baseline) with zero orphaned `risk_controls`/`erm_risk_score_history`
   rows for any of the three ids. Deleted the temp verify user + role
   grant; confirmed the final user list matches the original 4 users
   (admin, compliance, dpo, bcm).

No console errors traced to this plan's changes after the fix (aside from
the same pre-existing, unrelated `/api/command-centre/stats` 500 noted
during PLAN-23/24 verification).
