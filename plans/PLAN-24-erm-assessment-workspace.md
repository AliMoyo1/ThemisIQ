# PLAN-24: ERM Assessment Workspace UI (identification + ICE assessment)

## Status: OPEN (requires PLAN-23 committed first)

## Goal

Surface the PLAN-23 engine in the ERM SPA: contributing factors and EMV-i /
pillar / IRR in the risk form, per-control ICE scoring grouped by CF in the
risk drawer, live LoA / LoR / RRR / EMV-r readouts, P2sT2 filtering in the
control picker, AI ICE suggestion, risk_ref chips, and RRR in the register
and CSV export. After this plan a user can run the full mind-map assessment
loop end to end in the browser.

## Files to touch (exact)

1. `oneforall/modules/erm/templates/index.html` (main work)
2. `oneforall/modules/erm/routes.py` (CSV export columns; AI suggest-ice)
3. `oneforall/modules/erm/ai_service.py` or whichever module is imported as
   `ai` at the top of routes.py (one new function; check the import line
   first and edit THAT file)
4. `plans/README.md`

## Reference anchors in index.html (line numbers approximate, grep the names)

- `ermOpenRiskModal` at ~2445, `ermSaveRisk` at ~2551
- Risk drawer builder: `window.ermOpenRiskDrawer` region ~957-1398 with
  linked-controls fetch at ~1362 and `dCard(label,val)` helper at ~1228
- Control link modal: `ermOpenLinkControlModal` ~1409,
  `ermDoLinkControl` ~1462, `ermFilterLinkControls` ~1440
- Register renderer: `ermLoadRegister` region ~895-1192
- Boot framework fetch: `ermLoadFramework` ~684
- CSV export endpoint: routes.py `GET /api/export/csv` ~958

## Step-by-step order

### Step 0: create `plans/PLAN-24-active.md`; log every change as you go.

### Step 1: boot data

In `ermLoadFramework` (or directly after its call site), fetch
`/erm/api/pillars` once into a module-level `ERM_PILLARS` array (empty
array on failure; never block the SPA on it).

### Step 2: risk modal additions (ermOpenRiskModal + ermSaveRisk)

Insert after the Category / Sub-category form-row:

- Impacted Pillar: select id `rsk_pillar`, options: empty "-- None --" plus
  ERM_PILLARS names, preselect existing.impacted_pillar.
- EMV-i (USD): input type number min 0 step 1000 id `rsk_emvi`, value
  existing.emv_inherent or empty. Label exactly
  "EMV-i: inherent amount at risk (USD)".
- Contributing factors repeater: div id `rsk_cfs` rendering one row per
  existing.contributing_factors entry: readonly ref chip (cf_ref or "new"),
  a text input class `cf-desc-input` with data-cfid attribute when the
  entry has an id, and a remove button that deletes the row from the DOM.
  Below it an "+ Add contributing factor" button appending an empty row.
  When creating a new risk, start with ONE empty row (mind-map rule:
  every risk should have at least one contributing factor). Do not
  hard-block saving with zero CFs; warn via toast and proceed.
- IRR display (edit mode only): a muted, non-editable line under the
  Likelihood input: "IRR locked at first assessment: {irr_score}". Do NOT
  render an input for it.

In `ermSaveRisk`: collect
`contributing_factors = [{id: parseInt(el.dataset.cfid)||undefined,
description: value.trim()}]` skipping empty descriptions; add
`impacted_pillar` and `emv_inherent: parseFloat(rsk_emvi.value)||null` to
the data object. The backend (PLAN-23) handles create-vs-update of CFs.

### Step 3: drawer assessment section

Rework the linked-controls block (fetch at ~1362) into an "Assessment"
section:

- Header row: risk_ref chip (monospace pill), IRR chip
  ("IRR {irr_score}"), and a summary strip of four values pulled from the
  risk object: LoA {loa_pct}%, LoR {100-loa_pct}%, RRR {rrr} (red when
  rrr >= 15), EMV-r {emv_residual formatted as USD}. When loa_pct is null
  show "LoA not yet scored" instead of 0 percent (0 is a real score,
  null is unscored: check strictly for null).
- Group the controls list by cf_ref: one sub-header per CF
  ("CF001: {description}" with its cf_loa_pct when present) and an
  "Unassigned" group for rows with null cf_id.
- Each control row gains: an ICE select (options: "--" for null then 0%,
  10% ... 90%) preselected from c.ice_score using strict null check; an
  optional CF reassignment select (risk's CFs plus Unassigned); a
  "Suggest" button; and an evidence chip (mind-map requirement: evidence
  per control). Extend list_risk_controls' SELECT with a correlated
  subquery `(SELECT COUNT(*) FROM evidence_links el WHERE
  el.entity_type='canonical_control' AND el.entity_id=rc.control_id AND
  el.deleted_at IS NULL) AS evidence_count` (the same predicate the T1.3
  evidence factor uses). Render "Evidence (n)" as a link into the
  evidence module (existing deep-link pattern), where linking evidence to
  controls already works; note that evidence linked to grid/aria controls
  auto-mirrors onto the canonical control (evidence routes.py ~849), so
  counts include those. No new upload UI in this plan.
- ICE or CF change handler: PUT
  `/erm/api/risks/{rid}/controls/{control_id}` body
  `{ice_score: v===''?null:parseInt(v), cf_id: cfv?parseInt(cfv):null}`,
  then re-fetch `/erm/api/risks/{rid}` and re-render ONLY the summary strip
  and group headers (do not reload the page; the current code calls
  window.location.reload() after link/unlink, leave those as they are).
- "Suggest" button: GET
  `/erm/api/risks/{rid}/controls/{cid}/suggest-ice`, show a toast
  "Suggested ICE {n}% (auto score {auto})" and preselect the value in that
  row's select WITHOUT saving; the user confirms by leaving the select
  which fires the change handler. Wire the optional AI narrative: if the
  response contains `rationale`, append it to the toast.

### Step 4: control link modal (P2sT2 + CF + initial ICE)

In `ermOpenLinkControlModal` / `ermFilterLinkControls`:

- Add a chip row of P2sT2 categories (All, People, Process, System,
  Technology, Tool). Filter `_ermLinkCtrlData` on c.p2st2_category;
  controls with null category always show under All.
- Add a CF select (risk's CFs from `/erm/api/risks/{rid}/cfs`, plus
  Unassigned) and an initial ICE select defaulting "--".
- `ermDoLinkControl` sends `{control_id, weight, cf_id, ice_score}` (nulls
  omitted or null, backend tolerates both).

### Step 5: register + CSV

- Register table: add a Ref column (risk_ref) before Title and an RRR
  column after the existing residual/score column: value `r.rrr` with one
  decimal, red bold when >= 15, a plain hyphen "-" when null. Include
  risk_ref in the register's client-side text filter so typing RSK-0007
  finds the risk. Update the
  column count passed to spinner()/emptyRow() calls for that table.
- CSV export (routes.py ~958): add columns risk_ref, irr_score, loa_pct,
  rrr, emv_inherent, emv_residual to the header list and row tuples.

### Step 6: AI ICE narrative (small)

In the module imported as `ai` in routes.py add
`suggest_ice_rationale(control_title, control_description, ice_suggested,
factors)` returning one short sentence via the existing ai_client pattern
used by suggest_treatment (same guardrails, same fallback to empty string
on failure). Extend the suggest-ice endpoint: when query param `ai=1` and
the AI rate limit allows, include `rationale` in the response. Never let
an AI failure break the deterministic suggestion (wrap in try/except and
return the deterministic payload).

### Step 7: verify

- py_compile on routes + ai module; full pytest (no JS tests exist, suite
  must stay green).
- Live browser pass (mandatory): create a risk with 2 CFs, EMV-i 500000,
  pillar set; link 2 controls to CF001, score ICE 70 and 90; confirm the
  drawer strip shows LoA 80%, RRR 4.0, EMV-r $100,000; set one ICE to 0%
  and confirm LoA drops and the strip does NOT show "not yet scored";
  filter the control picker by a P2sT2 category; export CSV and check the
  new columns; delete the test risk afterwards.
- Update plans/README.md. One focused commit.

## Edge cases a weaker model would miss

- Strict null checks everywhere in JS: `c.ice_score === null` vs `0`.
  A select whose value is "0" must post integer 0, not null; a "--"
  selection must post null, not 0.
- The drawer refresh after an ICE change must re-read the RISK (loa/rrr
  live on the risk row), not just the controls list.
- ermSaveRisk currently rebuilds the whole data object; adding fields must
  not drop dimension_scores handling.
- The register table is also fed by the platform risk_register (merged
  register): rows from that source have no rrr; render "-" and never NaN.
- esc() every user string (CF descriptions, pillar names) in generated
  HTML; the file already has the esc() helper at line ~664.
- The modal is string-concatenated HTML: single quotes inside onclick
  attributes must be escaped exactly like neighbouring code does.
- Currency formatting: use toLocaleString with maximumFractionDigits 0 for
  EMV displays; never render floating point tails.
- Do not remove the existing weight input or dimension-score UI; they
  coexist with ICE.
- suggest-ice must stay usable when the control has no T1.3 score row
  (deterministic 0 suggestion, no crash).
- CSV: emv values may be NULL; write empty string, not "None".

## Acceptance criteria

- [ ] Full assessment loop works live in the browser exactly as in the
      Step 7 script, numbers matching the PLAN-23 worked example.
- [ ] ICE 0% behaves as a real score in every display.
- [ ] Old risks (no CFs, no ICE) still render drawer + register with no
      console errors and show RRR = IRR after PLAN-23 backfill.
- [ ] CSV contains the six new columns with correct values.
- [ ] pytest suite green; py_compile clean.
