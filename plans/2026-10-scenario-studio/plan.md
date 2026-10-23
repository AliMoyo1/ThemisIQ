# Scenario Studio rebuild (ERM)

Status: BUILT (all five phases), committed on the branch, not pushed. Branch `claude/scenario-studio` (worktree `.claude/worktrees/scenario-studio`, from origin/master fda87389).
Owner request (2026-10-23): fix the vanishing sidebar, make the studio complete and intuitive, add AI help inside it, and connect it to
the other modules and actions where that helps, without forcing connections that do not.

## 1. What exists today (read from code, 2026-10-23)

| Piece | Where | State |
|---|---|---|
| Page and API | `modules/erm/routes_scenarios.py` | List, create, update, delete, links, `/impact`, board packs. Works. |
| Engine | `modules/erm/scenarios.py` | `compute_scenario_impact` is pure and reproducible (never writes live tables). Board packs are hash chained, go stale when sources change, narrative by AI with citations restricted to allowed references. Good base, keep as is. |
| UI | `modules/erm/templates/scenario_studio.html` | One flat page: list, a form card, a link form, a "Compute Impact" button, board packs. |
| Sidebar | same file, `module_sidebar` block | Hard codes 4 items. The real ERM sidebar (about 12 items, counts, Ask ERM AI card) lives inside `index.html`. That is the bug the owner saw. |
| Link types | `scenarios.LINK_TYPES` | risk, control, kri, objective, external_context. Only risks have a picker; the rest need a typed numeric ID. Deltas are entered as a JSON box. |
| Capabilities | `core/rbac.py` | `erm.scenario.view`, `erm.scenario.manage`, `erm.boardpack.generate`, `erm.boardpack.publish`. |
| AI | `generate_board_pack_narrative` | Only AI use today. Feature id `erm.generate_board_pack_narrative`. |

Problems to fix:

1. Sidebar shrinks to 4 items on this page (two copies of the menu, they drifted).
2. Blank start with no explanation, no templates.
3. Linking: IDs by hand for four of five types, JSON for the changes.
4. Impact hidden behind a button, shown as plain tables, no headline.
5. No flow (what to do next), no description or owner or type on create, no comparison of two scenarios.
6. Studio is a silo: nothing outside ERM can see or reach a scenario.

## 2. Design principles

- The engine stays deterministic. AI only drafts inputs and explains outputs. Nothing AI proposes changes a number until a person accepts it item by item.
- Works fully with AI off.
- Connect only where a person would otherwise copy data by hand or lose the trail. Each connection below has a stated reason; the ones rejected are listed in section 6.
- Reuse the platform's existing mechanisms (Related Items edges, entity360, tasks, events, Evidence Vault links, report kit, platform guide). No new parallel link tables.
- Every new route is capability gated, business unit scoped, and tested for scope leaks (project rule: the code must have no security flaws).
- Icons from the sprite (`static/icons/sprite.svg`), no emoji, no em dashes in copy, no coloured top borders on cards.

## 3. Phases

Each phase ships on its own PR, tested, and leaves the app working.

### Phase 1: Shell and sidebar (small, independent)

- Extract the ERM sidebar into `modules/erm/templates/_erm_sidebar.html` (pattern already used by `ai_governance/_ai_sidebar.html`). `index.html` and `scenario_studio.html` both include it, with `active` set by a variable.
- Keep counts (`ermNavObl`, `ermNavAssess`, KRI breach badge) working on the studio page, or load them with the shared helper the dashboard already uses.
- Scenario Studio link gets `data-spa` only if the studio is moved into the ERM SPA (decision D1). Otherwise it stays a full page load but now shows the full menu.
- The "Ask ERM AI" card currently uses a warning triangle icon from the emoji pass. Replace with a sparkle or message icon while in here.
- Tests: sidebar item parity between the two pages (same set of links for the same role), capability gated items still hidden, UI test that the studio shows Obligations and Indicators.

### Phase 2: Studio rebuild without AI

Layout: list on the left, a guided workspace on the right with a stepper:
**1 Define, 2 Affected items, 3 Shocks, 4 Impact, 5 Brief.** Each step shows done / needs attention. The detail loads once and steps swap in place.

1. **Empty state and templates.** Explain what a scenario is in two lines. Offer 6 to 8 starter templates (ransomware, key supplier failure, regulatory fine, data breach, FX shock, loss of key person, AI system failure, extended outage). A template pre fills title, description, assumptions, horizon and a suggested risk category. Templates are data in a small module file, not DB rows, so no migration. Also "Start blank".
2. **Define.** Title, description, type (from the template list), horizon (select plus custom), assumptions, owner (people picker), review date. Needs new nullable columns (`description` exists; add `scenario_type`, `owner_id`, `review_date`) through the repo's migration pattern, with a PG test.
3. **Affected items.** One searchable panel for risks, controls, KRIs, objectives, external context, grouped and filtered to the caller's business unit, with checkboxes. Replaces the numeric ID box. Uses existing list APIs; add one `GET /erm/api/scenarios/candidates?type=&q=` that applies the unit rule once, server side, instead of the browser calling five endpoints.
4. **Shocks.** Per risk: likelihood and impact sliders showing baseline, residual likelihood and impact, optional expected monetary value. Per control: works / degraded / fails mapped to the allowed ICE values. Per KRI: target override. A "worsen everything in this category by one level" shortcut. The JSON box moves behind an "Advanced" disclosure (kept for imports and tests). Validation stays in `_validate_delta`.
5. **Impact, live.** Recompute (debounced) after each shock, no button. Headline sentence first (risks moving band, appetite breaches, expected loss multiple), then before and after bars per risk, then the existing tables. Data quality issues shown as a "fix these" list linking to the record.
6. **Compare.** Pick two scenarios, or one against baseline, and show deltas side by side. Read only, built from two `/impact` calls.
7. **Brief.** Board pack preview, stale reason, narrative editor, publish checks in one place (existing endpoints).

Backwards compatible: no change to impact math, link storage, or board pack hashing. Existing scenarios open in the new UI unchanged.

### Phase 3: Connected, only where it earns its place

Detailed in section 4. Order inside the phase: (a) Related Items and entity360 registration, (b) tasks from results, (c) Evidence Vault, (d) events, notifications and My Work, (e) BCM exercise hand off, (f) read only context from ORM, vendors, AI governance, Sentinel.

### Phase 4: AI assistance inside the studio

Detailed in section 5. Order: draft from a sentence, suggest shocks, find what is missing, explain the result, stress test assumptions.

### Phase 5: Hardening, guide, docs

Platform guide entries and tour step (`core/platform_guide.py`, `core/onboarding.py`), capability inventory regeneration (`scripts/capability_inventory.py`, without DEBUG), README for the module, report kit export of a scenario (see 4g), full backend suite and the PG lane, browser pass with throwaway credentials.

## 4. Connections (what, why, how, and when not)

| # | Connects to | Why a person wants it | How (reusing) | Phase |
|---|---|---|---|---|
| a | **Related Items / entity360** | From a risk, control, KRI, vendor, BCM plan or incident you should see "used in 2 scenarios"; from a scenario you should see everything tied to it. Today nothing outside ERM knows scenarios exist. | Register `("erm","scenario")` in `entity_scope` (capability `erm.scenario.view`, unit column, url `/erm/scenario-studio?open={id}`), label in `entity360`, valid module already `erm`. Link verbs reuse existing ones (`related`, `affects`, `impacts`). The scenario's own risk/control/KRI links stay in `erm_scenario_links` (they carry deltas); Related Items is for the looser links (vendor, application, process, BCM plan, incident). | 3 |
| b | **Tasks and workflows** | A result such as "three risks move to Critical" needs actions. Copying them into the task board by hand is the silo. | "Create action" on a per risk row and on the headline, via `task_service.create_task_with_assignment_notification`, with a back reference to the scenario (Related Items edge `platform/task` to `erm/scenario`). Optional workflow start for "board pack approval" only if a workflow template for it already exists (check; do not build one). | 3 |
| c | **Evidence Vault** | Assumptions need sources (loss data, incident report, vendor SLA). Board packs are audited; sources belong in the Vault with provenance. | Add `erm` / `scenario` as an evidence link target (existing `evidence_links`), show attached evidence in the Define step and as citations in the pack. Respect the Vault unit rules and soft delete readers. | 3 |
| d | **Events, notifications, My Work, calendar** | Owner should hear when a pack goes stale, a review date passes, or a linked risk changes enough to invalidate the scenario. | Emit `erm.scenario.created/updated/published` and use the existing stale sweeper (`sweep_stale_board_packs`) to notify; add owned and due scenarios to `my_work_service`; review date to calendar events. All through `core/events.py` and `core/notifications.py`. No new scheduler. | 3 |
| e | **BCM exercises and scenario library** | A severe scenario (outage, ransomware, supplier failure) is exactly what a tabletop exercise rehearses. BCM already has a scenario library and exercises. | "Rehearse in BCM" creates a draft `bcm_exercises` row pre filled from the scenario (title, description, objectives from assumptions) and an edge scenario to exercise. Reverse: a BCM incident or exercise offers "Model in Scenario Studio" pre filling a scenario. Unit rule of both ends applies (`_resolve_write_business_unit`). | 3 |
| f | **Read only context** (no new write paths): ORM loss events and KRIs, vendors, AI governance systems, Sentinel breaches and DPIAs, external context | Evidence for "how likely" and "what is exposed": last 12 months of ORM loss events in the category, vendor criticality, whether an AI system is in scope. | A "Context" side panel on the Shocks step reading existing services, unit scoped, with deep links. Informs AI suggestions in phase 4. Nothing is stored in the scenario. | 3 and 4 |
| g | **Reports and export** | The board pack is the output people share. | Use the shared report kit (`core/report_kit`) for the pack PDF and Excel, as the record document exports do, with Evidence and connected records sections via entity360. | 5 |
| h | **Search, Themis guide, onboarding** | Findable from the topbar search; the guide can explain it. | `search_service` entry for scenarios (scoped); `platform_guide.ENTRIES` plus a tour step. | 5 |

## 5. AI inside the studio

All calls go through the AI gateway (`core/ai_client.create_message`) with a declared feature id in `core/ai_declarations.py`, the existing rate limit (`check_ai_rate_limit` / `record_ai_call`), and masking. Output is JSON validated server side. Nothing is written by an AI call: each returns a proposal the person accepts item by item (same pattern as board pack narrative, and the AI generator in ARIA).

| Feature id | What it does | Input (only the caller's unit data) | Output validation |
|---|---|---|---|
| `erm.scenario_draft` | From a sentence ("payment processor down 5 days") propose title, assumptions, horizon, type, and which existing risks, controls, KRIs to link. | The sentence plus a bounded candidate list of the caller's risks, controls, KRIs (ids and titles). | Every proposed id must be in the candidate list; reject otherwise. |
| `erm.scenario_shocks` | Propose likelihood, impact and control state per linked item with a one line reason. | Linked items, baselines, ORM loss events and KRI trend as context. | Values pass `_validate_delta`; reasons length capped. |
| `erm.scenario_gaps` | Suggest related items not yet linked. | Linked set and candidate list. | Ids in candidate list only. |
| `erm.scenario_explain` | Plain language reading of the impact result: biggest movers, drivers, controls that matter. | The `/impact` JSON only. | Must cite item references from the result (reuse citation check from board packs). |
| `erm.scenario_challenge` | Flag weak assumptions (horizon vs KRI frequency, missing owner, stale baseline). | Scenario fields and data quality issues. | Free text capped, labelled as a prompt to think, not a finding. |

Guardrails: free text from the user is classified and masked before any provider call (the open follow-up from the onboarding guide is the same code path, build it once and reuse); AI badge on every accepted item (`source: ai | ai_edited | human` exists for narratives, extend to link deltas as a note field if the owner wants provenance per shock, see D4); studio fully usable when AI is not configured (buttons hidden, not broken); no AI call on page load, only on click; output never rendered as HTML (esc only).

## 6. Considered and not doing (so it stays out of scope)

- **GRID control gaps and ARIA frameworks:** controls already link directly (`control` link type); no extra coupling needed.
- **Predictive risk engine:** separate concept (forecast from signals), different data lifecycle; revisit only if the owner wants "forecast vs scenario" views.
- **Auto creating scenarios from every Sentinel breach or BCM incident:** noisy and would fill the list; offered only as an explicit "Model this" button (4e).
- **New link tables or a graph store:** Related Items already is the graph.
- **Monte Carlo or full quantification:** engine is score and EMV based; out of scope.
- **Scenario sharing outside the business unit:** unit rule stays as is.

## 7. Security and quality checklist (applies to every phase)

- New endpoints: `require_capability`, unit scope through the existing `bu_scope_ids` and `_check_write_scope`, never trust ids from the browser (candidates API filters server side).
- All new JS builds DOM with `esc()` and never puts markup inside `textContent`; `esc` here does not escape quotes, so no values inside attributes without `esc` plus numeric casting of ids (existing code does `Number(row.id)`).
- AI outputs validated and bounded before display; prompts never include data from other units.
- RLS lane: tests on real PG for any new column or query (`TEST_DATABASE_URL`, repo `.venv` python, one pytest session at a time).
- Capability inventory regenerated without DEBUG; new capabilities named in `rbac.py` with role sets decided in D3.
- No icons as emoji; icons from the sprite.

## 8. Test plan

- Unit: template catalogue integrity, candidates API scoping, delta validation for slider values, AI validators (reject foreign ids, bad deltas), event emission, entity registration, scope tests for every new edge.
- UI (Playwright, repo venv): sidebar parity, stepper flow end to end, live impact updates, compare mode, accept and reject AI proposals with a stubbed provider, create task from a result, exercise hand off.
- PG lane for migrations and scope.
- Browser pass with throwaway credentials, discarded before committing.

## 9. Decisions needed from the owner

Proposed defaults are marked. Say "go with your recommendations" and I will adopt them and record them in the log with the reason.

- **D1 Where does the studio live?** Recommended: move it into the ERM SPA like the other ERM pages, so the sidebar never reloads. Alternative: keep a separate page with the shared sidebar (smaller change, Phase 1 only).
- **D2 Starter templates.** Recommended list in 3.2 (8 templates). Edit the list or give industry specific ones.
- **D3 Who can use what.** Recommended: unchanged roles for view and manage; AI features need `erm.scenario.manage`; "Create action" needs the task capability the user already has; "Rehearse in BCM" needs `module.bcm.access` plus BCM exercise create.
- **D4 AI provenance per shock.** Recommended: yes, store `source` and `reason` on each delta (small JSON addition, no new table) so a board reader can see what was machine suggested.
- **D5 BCM hand off.** Recommended: include (4e). Cost: a second module write path to test.
- **D6 Compare mode and PDF export.** Recommended: compare in Phase 2, PDF in Phase 5.
- **D7 Order.** Recommended: Phase 1 first and ship alone, then 2, 3, 4.

## 10. Log

- 2026-10-23: plan written from a read of the code. Nothing built.
- 2026-10-23: owner confirmed in chat: "go with your recommendations" for D1 to D7 (chat confirmation, not a formal sign-off). Adopted:
  D1 studio moves into the ERM SPA (done in Phase 2; Phase 1 ships the shared sidebar first so the menu is right straight away). Why: one menu, no reload.
  D2 eight starter templates. D3 roles unchanged, AI needs erm.scenario.manage. D4 store source and reason per shock (small JSON addition, no table).
  D5 BCM hand off included. D6 compare in Phase 2, PDF in Phase 5. D7 Phase 1 alone first.
  To change any of these: edit this list and the matching section, nothing is built on D2 to D6 yet.
- 2026-10-23 Phase 1 built: modules/erm/templates/_erm_sidebar.html (shared), index.html and scenario_studio.html include it, studio route passes can_manage_frameworks and can_view_scenarios, studio fills the nav counts from /erm/api/dashboard. Test: tests/ui/test_erm_scenario_studio_browser.py parity test (studio and dashboard show the same links for the same role, studio link active). Existing scenario tests still pass.
  Merge note: the svg-icons branch edits the same sidebar block (Ask ERM AI card icon); when both land, apply that change inside _erm_sidebar.html.

## 11. Build log, 2026-10-23 (all phases)

What was built, by phase:

- **Phase 1** shared sidebar `_erm_sidebar.html` (ERM page and studio include it, same links per role, studio link active, nav counts filled on the studio).
- **Phase 2** studio rebuilt: stepper (Define, Affected items, Shocks, Impact, Brief) plus Compare; 8 starter templates; type, owner, review date (migration `erm_scenarios.scenario_type`, `review_date`; owner already existed); one searchable picker with checkboxes (`/api/scenarios/candidates`, unit rule applied on the server); likelihood and impact sliders, control effectiveness select, indicator target, "worsen a category by one level", JSON kept under Advanced; live headline strip and impact view with before/after bars, appetite, totals, data quality fixes; compare two scenarios.
- **Phase 3** connections: Related Items and entity registration (`("erm","scenario")`, label, Evidence Vault target, global search, My Work owner review), Evidence card plus `/evidence/?attach=erm:scenario:ID` upload deep link (new `entity_id` filter on `/evidence/api/search-entities`), tasks from results (`POST /api/scenarios/{id}/actions`, related edge `derived_from`), BCM "Rehearse" draft tabletop (`POST /api/scenarios/{id}/rehearse`, needs `bcm.exercise.manage`), "Model a worse case in Scenario Studio" from a BCM incident (`?model=bcm:incident:ID`, also ORM events and Sentinel breaches via the seed route), read only ORM loss event context, events `erm.scenario.created/updated/published`, notification to the pack's creator when a pack goes stale.
- **Phase 4** AI: `erm.scenario_draft`, `_shocks`, `_gaps`, `_explain`, `_challenge` (gateway features, declarations, policy entries; `erm.scenario.manage` plus `erm.ai.use`; typed sentence refuses email addresses and long numbers; every answer validated before it leaves; per shock provenance `source` and `reason` stored in the delta, D4).
- **Phase 5** hardening: capability inventory regenerated, module README and ARCHITECTURE events updated, real PostgreSQL test added to the PG lane.

Deviations from the plan, and why:

1. **D1 (studio inside the ERM SPA) not done.** The studio stays its own page with the shared sidebar. Result for the user is the same menu; moving it would have grown a 4000 line `index.html` for faster navigation only. To change: add a `spa-view` and route in `index.html` and mount the studio script there.
2. **Review date on the calendar not done.** My Work already lists the owner's review on its date and the stale pack notification covers the rest; a calendar write path needed its own tenant handling for little gain.
3. **Board pack PDF and Excel export (4g) not built.** The shared report kit is not on master yet (it lives on the reports branch). Build it after that lands; the existing pack view and narrative stay as they were.
4. **Platform guide entries and the onboarding tour step (4h) partly done.** PR #21 (the guide) is not merged, so `core/platform_guide.py` does not exist on master. A Scenario Studio entry was added to the existing trainer keyword list; add the guide entry and tour step after #21 merges.
5. **Context panel reads ORM loss events only.** Vendors, AI systems and Sentinel records already show through Related Items; no extra read path was added.

An engine finding, fixed because it misled the board numbers: a risk with no stored residual score had its baseline residual taken as the inherent score while the scenario residual came from the tiered calculation, so a scenario that changed nothing showed a large improvement (totals and appetite). The baseline now runs through the same tier ladder with no changes when no residual is stored (`rrr_calculated` flag on the baseline). Rows with a stored residual behave exactly as before.

Verification: backend regression set 449 passed (before the one expected-set update in `test_my_work_service`), browser tests for the studio, Vault, BCM incident and My Work 45 plus 7 passed, `test_scenario_studio_runs_on_real_postgres` passed on PostgreSQL 18, capability inventory matches, screenshots of every step in light and dark reviewed. Not run: the full backend and browser suites (about an hour each), and the AI paths against a real provider (stubbed in tests; no provider key here).

Merge note: the svg-icons branch converts emoji in `index.html`; the "Ask ERM AI" card now lives in `_erm_sidebar.html`, so apply that icon change there. The studio template itself uses no emoji and no icons.
