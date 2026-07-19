# PLAN-26: ERM Dashboard v2 (RRR watchlist, EMV totals, trajectory, filters)

## Status: OPEN (requires PLAN-23; best after PLAN-24 and PLAN-25)

## Goal

Deliver the mind map's dashboard: high-risk watchlist (RRR >= 15), overall
averages (IRR, RRR, LoA, LoR, control effectiveness), EMV-i / EMV-r / EMV-a
totals, a risk trajectory graph from the score-history table, and a filter
bar (category, business unit, pillar, period). This is where "measurable and
comparable results over time" becomes visible.

## Files to touch (exact)

1. `oneforall/modules/erm/data_service.py` (get_dashboard_stats at ~1404,
   get_appetite_status, plus one new helper)
2. `oneforall/core/event_handlers.py` (two appetite checks, Step 1b)
3. `oneforall/modules/erm/routes.py` (GET /api/dashboard passes filters
   through; endpoint at line ~67)
4. `oneforall/modules/erm/templates/index.html` (dashboard page section +
   ermLoadDashboard at ~776)
5. `oneforall/tests/test_erm_dashboard_v2.py` (NEW)
6. `plans/README.md`

## Step-by-step order

### Step 0: create `plans/PLAN-26-active.md`; log every change as you go.

### Step 1: data_service - posture stats

a) New helper `_posture_where(filters)` returning (where_sql, params) built
from optional filters: category, business_unit_id, impacted_pillar,
date_from, date_to (created_at range, ISO strings). Base clause always
excludes closed: `e.status != 'closed'`. Compose with AND; parameterised
%s only, never string interpolation of values.

b) Extend `get_dashboard_stats(filters=None)` (keep the existing payload
keys untouched; the function signature gains one optional argument
defaulting to None so all existing callers keep working). Add a new
`posture` key:

```python
"posture": {
    "avg_irr":  ...,   # AVG(irr_score) over filtered open risks
    "avg_rrr":  ...,   # AVG(rrr) WHERE rrr IS NOT NULL
    "avg_loa":  ...,   # AVG(loa_pct) WHERE loa_pct IS NOT NULL
    "avg_lor":  ...,   # 100 - avg_loa when avg_loa is not None else None
    "emv_i_total": ..., # SUM(emv_inherent)
    "emv_r_total": ..., # SUM(emv_residual)
    "emv_a_total": ..., # SUM over erm_cf_treatments joined to filtered risks
    "control_effectiveness": ...,  # AVG(ice_score) over risk_controls of
                                   # filtered risks WHERE ice_score IS NOT NULL
    "high_rrr": [ {id, risk_ref, title, category, rrr, irr_score,
                   loa_pct, owner_name} ... ],  # rrr >= 15, ORDER BY rrr
                                                # DESC, LIMIT 10
    "trajectory": [ {"month": "2026-07", "avg_rrr": 12.3,
                     "avg_irr": 18.0} ... ],    # last 24 months ascending
}
```

All averages rounded to 1 decimal; sums to 2; None when no qualifying rows
(never 0 unless a real 0 exists). emv_a_total joins
`erm_cf_treatments t JOIN erm_enterprise_risks e ON e.id=t.risk_id` with
the same where clause. If PLAN-25 has not shipped yet, guard the emv_a
query with try/except returning None (table may not exist on that branch).

c) Trajectory: do NOT use strftime or to_char in SQL (SQLite vs PG
divergence). SELECT recorded_at, rrr, irr FROM erm_risk_score_history for
risk_ids matching the filter (JOIN on the risks table with the same where)
and recorded_at within the last 24 months, then bucket by
`recorded_at[:7]` in Python and average per bucket. Return months sorted
ascending. When a period filter narrows the range (see Step 2), bucket the
narrowed range only.

### Step 1b: appetite compares residual exposure (decided 2026-07-18)

Appetite now measures the risk position AFTER controls, matching the
mind map's placement of Risk Appetite under Treatment. The comparison
expression everywhere becomes
`COALESCE(e.rrr, e.likelihood*e.impact) > a.max_score`. Because PLAN-23
tier 4 sets rrr = irr_score for unassessed risks, their breach results
are IDENTICAL to the old inherent math; breaches only start clearing as
controls actually get ICE-scored. Three sites, all changed in this step:

a) `get_dashboard_stats` appetite_breaches query (data_service ~1417):
   swap `(e.likelihood*e.impact)` for the COALESCE form.
b) `get_appetite_status` (grep the function name in data_service):
   replace EVERY likelihood*impact expression feeding current_max_score
   and the breached flag with the same COALESCE form, including inside
   MAX() aggregates.
c) `core/event_handlers.py` appetite checks at ~146 and ~2644:
   `MAX(likelihood*impact)` becomes
   `MAX(COALESCE(rrr, likelihood*impact))`.

Use rrr (REAL), never residual_score, in these comparisons: rounding
residual_score can flip borderline breaches (rrr 12.4 vs max_score 12
must breach). COALESCE is portable across SQLite and PG.

UI: in ermRenderAppetitePanel (~830) and the appetite page header, label
the gauge value "residual exposure vs appetite" (tooltip is enough) so
the basis change is visible. No other UI change.

`GET /api/dashboard` (line ~67): read optional query params category,
business_unit_id (int), pillar, period. period is one of: empty, 'year',
'quarter', 'month'; translate to date_from = today minus 365/90/30 days
respectively (UTC, ISO date string) and leave date_to None. Assemble the
filters dict and pass to ds.get_dashboard_stats(filters). Invalid
business_unit_id (non-int) returns 400.

### Step 3: UI - dashboard section

In the dashboard page markup (the section ermLoadDashboard populates):

a) Filter bar above the stat cards: selects for Category (taxonomy names,
reuse the source ermPopulateCategoryFilters uses at ~2851), Pillar
(ERM_PILLARS from PLAN-24), Business Unit (fetch `/governance/api/business-units`
if that endpoint exists; check modules/governance/routes.py for the exact
path and skip the select silently when unavailable), and Period (All time,
Last 12 months, Last quarter, Last month). On change, call
ermLoadDashboard() which now appends the query string.

b) "Risk posture" KPI row: six metric cards (Avg IRR, Avg RRR, LoA %,
LoR %, EMV-i total, EMV-r total) plus a seventh small card EMV-a total
when not null. Render "-" for null. Reuse the existing statCards() helper
at ~708.

c) High-risk watchlist panel: table of posture.high_rrr rows (ref, title,
category, RRR red bold, owner), each row clicking through to
ermOpenRiskDrawer(id). Empty state: "No risks at RRR 15 or above".

d) Trajectory chart: inline SVG polyline (no chart library; the codebase
has none). Two series: avg_rrr solid line, avg_irr muted dashed line.
X axis: month labels every 3rd bucket, Y axis 0-25 fixed. Below 2 data
points, render the panel with text "Not enough history yet" instead of a
line. Keep it under ~60 lines of JS in one function
`ermRenderTrajectory(buckets)`.

e) Wire into ermLoadDashboard(): read d.posture, call the three renderers,
guard every element lookup with null checks (the function currently
follows that pattern; keep it).

### Step 4: tests - `oneforall/tests/test_erm_dashboard_v2.py`

Direct data_service calls on test_db:

1. Seed 3 risks via create_enterprise_risk with known L/I/EMV and ICE
   scores producing one risk at RRR >= 15 (e.g. L5 I5, single control
   ICE 30: RRR 17.5): posture.high_rrr contains exactly it; averages match
   hand-computed values.
2. Filters: category filter narrows averages; unmatched category returns
   None averages and empty high_rrr.
3. Trajectory: insert history rows across 3 synthetic months directly via
   SQL, verify 3 ascending buckets with correct means.
4. No risks at all: every posture value None or empty list, no exception.
5. Existing payload keys (total_risks, critical, appetite_breaches...)
   unchanged for a no-filter call (regression guard for the old
   dashboard cards). Exception: appetite_breaches values may legitimately
   differ where risks have ICE scores; assert key PRESENCE here and test
   the value semantics in test 6.
6. Appetite residual semantics: seed an appetite category with
   max_score 12; risk A at L5 I5 with no controls (rrr defaults 25)
   breaches, exactly as the old math would; score one control on risk A
   at ICE 70 (rrr 7.5): breach clears; risk B at L4 I4 unassessed
   (rrr 16) still breaches. Assert the event-handler path too by calling
   the check expression directly against the test DB.

### Step 5: verify

- py_compile + full pytest.
- Live browser: dashboard shows the posture row and watchlist for the
  PLAN-24/25 test risk; change Period to Last month and watch numbers
  update; trajectory renders after making two ICE changes a few seconds
  apart (two history rows, same month: still one bucket, so ALSO verify
  the "Not enough history" branch by filtering). Clean up test risks.
- Update plans/README.md. One focused commit.

## Edge cases a weaker model would miss

- AVG over zero rows returns NULL from SQL; keep it None in JSON, and the
  UI must print "-", never NaN or 0 (0 would misreport real posture).
- avg_lor derives from avg_loa in Python; do not average (100 - loa) in
  SQL and then also compute 100 - avg_loa (double transformation bug).
- The filter where-clause must be shared by EVERY posture query in the
  same call or panels will disagree with each other (the exact partial
  migration bug the framework slice fought).
- Legacy dashboard counters intentionally stay UNFILTERED; only the
  posture block responds to filters. State this in a code comment so a
  future reader does not "fix" it.
- Month bucketing via recorded_at[:7] assumes ISO timestamps; PG returns
  datetime objects through the wrapper in some paths: coerce with
  str(recorded_at)[:7].
- SVG polyline points need Y inversion (SVG y grows downward) and a fixed
  0-25 domain so IRR and RRR share the scale honestly.
- period=quarter means last 90 days, not calendar quarter; label the UI
  option "Last quarter (90 days)" to avoid the ambiguity.
- Query params arrive as strings; business_unit_id must be int-cast inside
  a try/except returning 400, not a naked int().
- The dashboard endpoint is hit on every SPA load: keep the posture block
  to a bounded number of queries (one per metric group, no per-risk loop).
- The executive dashboard (get_executive_dashboard, data_service ~1857)
  and the heatmap intentionally stay band/inherent-based in this plan;
  posture (RRR/EMV) and bands are different lenses and may show different
  severities for the same risk. State this in a code comment so it is not
  mistaken for the partial-migration bug.
- Freebie to verify, not build: the AI board report endpoint calls
  get_dashboard_stats() with no arguments, so after this plan the
  narrative generator automatically receives the posture block in its
  stats payload. Confirm the prompt serialization does not choke on the
  nested dict; optionally mention RRR posture in the narrative prompt.

## Acceptance criteria

- [ ] All 6 test cases pass; suite green; py_compile clean.
- [ ] Appetite breaches now clear when ICE scoring brings rrr within
      max_score, and unassessed risks report byte-identical breach
      results to the pre-plan behavior.
- [ ] Watchlist threshold is exactly rrr >= 15 (15.0 included).
- [ ] Old dashboard cards render identical values with and without the
      plan applied (regression test 5 proves the payload; eyeball the UI).
- [ ] Filters change posture numbers and watchlist coherently in the live
      pass.
- [ ] Trajectory renders with >= 2 buckets and falls back gracefully below
      that.
