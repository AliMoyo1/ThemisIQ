# PLAN-T1.2: Unified Controls Model — Completion

## Status: IN PROGRESS

## Context

T1.2 was designed to introduce a unified `canonical_controls` table linking every
module's controls together. Investigation found that most of the schema is already
built from earlier sessions:

- `canonical_controls` table: EXISTS (in `_PLATFORM_TABLES`, CRUD in governance data_service)
- `risk_controls` bridge: EXISTS (weight + direction, ERM data_service has link/unlink/list)
- ERM routes for risk-control linking: EXISTS (GET/POST/DELETE on /erm/api/risks/{id}/controls)
- ERM SPA "Linked Controls" panel in risk drawer: EXISTS
- `canonical_control_id` FK columns on orm_rcsa_controls, aria_controls, grid_controls: EXIST

What's actually missing (4 gaps found by code audit):

### Gap 1: Backslash bug in ERM SPA (ermUnlinkControl + ermOpenLinkControlModal)
- File: `modules/erm/templates/index.html` lines ~1399, 1418
- Bug: URLs use `\erm\api\risks\` (backslashes) instead of `/erm/api/risks/`
- In JS sloppy mode: `\e` = `e`, `\a` = `a`, `\r` = carriage return (CR!) — URL is malformed
- Effect: unlink and link API calls fail

### Gap 2: aria_controls INSERT column name mismatch
- File: `modules/launcher/routes_platform.py` line 562
- Bug: `INSERT INTO aria_controls (framework_id, control_id, title, description, status, evidence_notes)`
  — table has `ref`, `name`, `evidence_ref` not `control_id`, `title`, `evidence_notes`
- Effect: any code path importing `aria_controls` via this route crashes with column-not-found error

### Gap 3: ERM link-control modal uses browser prompt()
- File: `modules/erm/templates/index.html` lines ~1404-1422
- Current: shows list of controls as text in a `prompt()` dialog, requires typing an ID
- Fix: replace with a proper modal (search box + table of results, click to select)

### Gap 4: ORM RCSA effectiveness not rolled up
- File: `modules/orm/data_service.py`
- Bug: `update_rcsa_control` can update `design_effectiveness`/`operating_effectiveness` per control
  but `orm_rcsa_risks.control_effectiveness` (the INTEGER driving residual score) is never
  auto-updated from these individual assessments
- Fix: add `_recompute_risk_effectiveness(db, risk_id)` that maps the mean of individual
  control scores to the 1-5 integer, call from create/update/delete_rcsa_control

## Files to change

1. `modules/erm/templates/index.html` — fix backslash URLs + replace prompt() modal
2. `modules/launcher/routes_platform.py` — fix aria_controls INSERT column names
3. `modules/orm/data_service.py` — add _recompute_risk_effectiveness + wire into CRUD

## Effectiveness mapping for Gap 4

design_effectiveness TEXT: "adequate" = 1.0, "not_assessed" = 0.5, "inadequate" = 0.0
operating_effectiveness TEXT: "effective" = 1.0, "partially_effective" = 0.5, "ineffective" = 0.0, "not_tested" = 0.5

Combined score per control = mean(design_score, operating_score) * 4 + 1  → maps to [1, 5]
Average across all controls for the risk → round to nearest int, clamp 1-5
If no controls assessed: don't update (leave user-set value)

## Verification

1. py_compile all touched files
2. pytest full suite (77 tests)
3. Manual: open ERM risk drawer, link a canonical control, confirm it shows, unlink it, confirm it removes (no backslash errors)
4. Manual: check ORM RCSA — update a control's design/operating effectiveness, confirm risk control_effectiveness updates

---

## Change log

- [ ] Fix backslash URLs in ermUnlinkControl + ermOpenLinkControlModal
- [ ] Replace prompt() with proper modal in ermOpenLinkControlModal  
- [ ] Fix aria_controls INSERT in routes_platform.py
- [ ] Add _recompute_risk_effectiveness() to orm/data_service.py
- [ ] Wire recompute into create_rcsa_control, update_rcsa_control, delete_rcsa_control
- [ ] py_compile + pytest
- [ ] Commit
