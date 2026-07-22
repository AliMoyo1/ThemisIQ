# PLAN-SBU-03: Group rollup dashboard (per-SBU posture for the parent-org monitor)

## Leverage rank: 3 of 4 (DO THIRD). The visible payoff for the exact persona
## the user described — "users under [the group] who monitor the SBUs." Once
## SBspaced-01 assigns users and SBU-02 enforces isolation, this is the screen
## that makes multi-SBU worth buying: one group CGRCO seeing every subsidiary's
## risk/compliance posture side by side, with drill-down.

## Goal / feature

A new **"Group View" / SBU rollup** surface that, for a user whose scope spans
multiple business units (a root-BU user or a `GRC_OFFICER` with org-wide
access), renders one card/row per SBU in their subtree showing that SBU's
posture at a glance:
- Enterprise risks: total + count in Critical/High band
- Open operational events / open BCM incidents
- Open audit non-conformances (GRID)
- Open data breaches (Sentinel)
- Overdue items (SLA + tasks)
- A composite "attention" flag (red/amber/green)

Each card links (drill-down) into that SBU by carrying a `?bu=<id>` filter
into the relevant module (honored by SBU-04's BU filter, or degrade
gracefully to the module root if SBU-04 is not yet built).

This directly answers "Econet has EconetAI, EcoCash, Infraco … and users
under Econet who monitor the SBUs": the group monitor lands here and sees all
three subsidiaries' postures in one view.

## Prerequisites

- **SBU-01 must be done** (users actually assigned to BUs, or the view has
  nothing meaningful to roll up — though it still works structurally on the
  BU tree alone).
- SBU-02 recommended (so the drill-down actually isolates), but not strictly
  required for this view to render.

## Exact files to touch

1. `oneforall/modules/governance/data_service.py` — add
   `get_sbu_rollup(user)` returning per-BU posture rows.
2. `oneforall/modules/governance/routes.py` — add
   `GET /governance/api/sbu-rollup` (gated `governance.entities.view`).
3. `oneforall/modules/governance/templates/index.html` — add a "Group View"
   tab (or a dedicated top card) that fetches and renders the rollup.
   ALTERNATIVE placement: the Command Centre (`templates/command_centre.html`)
   — see "Placement decision" below.
4. `oneforall/tests/test_sbu_rollup.py` — NEW.

## Placement decision (make this call explicitly)

Two options; pick ONE and note it in the plan log:
- **Option A (recommended): a "Group View" tab in the Governance SPA.** Lowest
  risk, self-contained, sits next to the BU tree it summarizes, and the
  Governance module is exactly where an org-structure monitor already works.
- Option B: a rollup strip on the Command Centre, shown only to multi-BU
  users. Higher visibility but touches the busiest page and its already-dense
  stats logic. Defer to a follow-up.
This plan implements **Option A**.

## Step-by-step order

### Step 1 — `get_sbu_rollup(user)` in `governance/data_service.py`

Add near `get_governance_summary`. Logic:
```python
def get_sbu_rollup(user: dict) -> list[dict]:
    """One posture row per business unit in the caller's scope subtree.
    Super-admins / org-wide users get every active BU. Scoped users get
    their own BU + descendants (via bu_scope_ids)."""
    scope = bu_scope_ids(user)  # None => all
    db = get_db()
    try:
        bus = _dicts(db.execute(
            "SELECT id, name, code, parent_id FROM business_units WHERE is_active=1 ORDER BY name"
        ).fetchall())
        if scope is not None:
            bus = [b for b in bus if b["id"] in scope]
        rows = []
        for b in bus:
            bid = b["id"]
            def c(sql):
                try:
                    return db.execute(sql, (bid,)).fetchone()[0] or 0
                except Exception:
                    return 0
            rows.append({
                **b,
                "risks_total":   c("SELECT COUNT(*) FROM erm_enterprise_risks WHERE business_unit_id=%s AND status != 'closed'"),
                "risks_high":    c("SELECT COUNT(*) FROM erm_enterprise_risks WHERE business_unit_id=%s AND status != 'closed' AND likelihood*impact >= 15"),
                "orm_open":      c("SELECT COUNT(*) FROM orm_events WHERE business_unit_id=%s AND status NOT IN ('resolved','closed')"),
                "incidents_open":c("SELECT COUNT(*) FROM bcm_incidents WHERE business_unit_id=%s AND status IN ('open','responding')"),
                "breaches_open": c("SELECT COUNT(*) FROM sentinel_breaches WHERE business_unit_id=%s AND status != 'closed'"),
                "grid_ncs_open": c("SELECT COUNT(*) FROM grid_audits WHERE business_unit_id=%s"),  # placeholder; refine to NC table if present
            })
        return rows
    finally:
        db.close()
```
NOTE: verify each column name against the real schema before finalizing —
e.g. confirm `bcm_incidents.status` values (`open`/`responding`), the ERM
"high band" cutoff (this repo migrated off hardcoded cutoffs to
`resolve_band()`; if a framework is active, prefer counting rows whose
`qualitative_score` band is in {critical, high} rather than `likelihood*impact
>= 15`). Read `erm/data_service.py` `get_active_framework_matrix`/`resolve_band`
and reuse them for band accuracy rather than reintroducing a hardcoded
cutoff (the repo deliberately removed those — do not regress it).

### Step 2 — route (`governance/routes.py`)
```python
@router.get("/api/sbu-rollup")
@require_capability("governance.entities.view")
async def api_sbu_rollup(request: Request):
    return JSONResponse(ds.get_sbu_rollup(request.state.user))
```

### Step 3 — "Group View" tab (`governance/templates/index.html`)
3a. Add tab button (in `.gov-tabs`), shown to everyone with view access (the
data is already scope-limited server-side, so a single-SBU user simply sees
one card — their own):
```html
<button class="gov-tab" data-tab="group" onclick="govSwitchTab('group')">Group View</button>
```
3b. Add the panel:
```html
<div class="tab-view" id="tab-group">
  <div id="rollupCards" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px">
    <div style="color:var(--muted);padding:24px">Loading…</div>
  </div>
</div>
```
3c. JS: lazy-load on first switch (same pattern as SBU-01's People tab). Each
card shows the BU name/code, the metrics, and an "attention" colour:
- red if `risks_high > 0 OR incidents_open > 0 OR breaches_open > 0`
- amber if `risks_total > 0 OR orm_open > 0`
- green otherwise
Each metric that has a natural module links out (e.g. risks → `/erm/?bu=<id>`).
Use the existing `esc()` helper.

### Step 4 — tests (`oneforall/tests/test_sbu_rollup.py`)
1. `test_rollup_scoped_to_subtree` — parent `P`, children `C1`, `C2`, plus an
   unrelated `X`. A user with `business_unit_id=P` → rollup returns rows for
   P, C1, C2 but NOT X.
2. `test_rollup_super_admin_sees_all` — `is_super_admin=1` → every active BU.
3. `test_rollup_counts` — insert 2 non-closed high-band risks under C1 →
   that card's `risks_high == 2`; a closed risk is excluded.
4. `test_rollup_single_sbu_user` — a user assigned to a leaf BU gets exactly
   one row (their own).

## Edge cases a weaker model would miss

- **Scope the rollup itself.** A single-SBU user must NOT see other SBUs'
  posture here — filter `bus` by `bu_scope_ids(user)` (None ⇒ all). This is a
  governance surface; leaking sibling-SBU numbers to a subsidiary user is the
  same isolation failure SBU-02 fixes elsewhere.
- **Do not reintroduce hardcoded risk-band cutoffs.** The repo migrated every
  band decision to `resolve_band()`/the active framework matrix on purpose. If
  you count "high risks" with `likelihood*impact >= 15`, you diverge from what
  the ERM dashboard shows. Reuse the framework matrix so the rollup agrees
  with ERM's own numbers.
- **Each COUNT wrapped in try/except returning 0.** Some tables may not exist
  in every deployment/migration state (the codebase does this everywhere —
  e.g. `get_governance_summary`). One missing table must not 500 the whole
  rollup.
- **NULL-BU records are NOT attributed to any SBU card.** These per-BU counts
  use `business_unit_id = %s` (exact match), which correctly excludes
  org-wide/unassigned records. That is intended: the rollup is per-SBU, and
  org-wide items belong to no single SBU. (Optionally add a summary "Org-wide
  / Unassigned" pseudo-card counting `business_unit_id IS NULL` — nice-to-have,
  flag it, don't block on it.)
- **N BUs × M count queries** is fine for realistic N (tens of SBUs) but note
  it is O(N·M) queries. For a tenant with hundreds of BUs this would need a
  GROUP BY rewrite; add a code comment noting the current approach is chosen
  for clarity and is adequate below ~50 BUs.
- **Drill-down links must degrade gracefully.** If SBU-04 (the BU filter) is
  not built yet, `/erm/?bu=<id>` simply lands on the ERM root (the query param
  is ignored) — still useful, not broken. Do not make the rollup depend on
  SBU-04.

## Acceptance criteria (verifiable)

1. As a super-admin: Governance → "Group View" shows one card per active BU
   with live counts; a BU with high-band risks shows the red attention state.
2. As a user assigned to a parent SBU with two children: the view shows
   exactly three cards (parent + two children), and none belonging to a
   sibling/unrelated SBU.
3. As a user assigned to a leaf SBU: exactly one card (their own).
4. The card counts match what the corresponding module shows for that SBU
   (e.g. the ERM register filtered to that BU shows the same non-closed and
   high-band totals).
5. `python -m pytest tests/test_sbu_rollup.py` passes; full suite unaffected.
6. No console errors; the tab lazy-loads (network call fires only on first
   switch to "Group View").
```
