# 07. Implementation ledger

**Purpose.** Documents 01 to 06 are proposals. This file records what was actually built from them, how it was checked, what was
left, and what the next person needs to know. Started 2026-10-14 on the local branch `claude/pg-layer-scope-and-findings`,
fast-forwarded to `origin/master` (`f770d33`). The earlier AI Governance history stays in
[../ai-governance/05-execution-ledger.md](../ai-governance/05-execution-ledger.md) and is not rewritten here.

**Status words** (from [05](05-delivery-and-acceptance.md) section 12, kept separate on purpose): *planned*, *built* (in the
working tree), *verified locally* (focused checks named below passed on SQLite, and on a disposable PostgreSQL where stated),
*pilot live*, *generally released*. Nothing in this file is *pilot live* or *generally released*. Plans 01 to 03 were merged
as pull request 10; plans 04 to 06 and follow-ups 11 to 13 are committed and pushed on the branch
`claude/plan-04-platform-truth`. Nothing here is merged to `master` or deployed: that is the owner's step.

## Working rules for whoever continues

- Test first; the focused checks of a slice run when it is built; a full suite runs only after a larger stage.
- Use the repo interpreter (`.venv\Scripts\python.exe`) from `oneforall/`, one pytest session at a time,
  `env -u TEST_DATABASE_URL` for SQLite, `-o addopts="--tb=short"`. The PostgreSQL lane needs the throwaway container
  `themisiq-pg-aigov` and the guard variables described in the memory file `reference_test_environment.md`.
- No em dashes, no pipe character in a command given to the user, one command per step.
- Regenerate `oneforall/docs/generated/capability_inventory.*` after a route or capability change
  (`python scripts/capability_inventory.py`; CI runs it with `--check`).
- Do not stage files that belong to other chats or are runtime artefacts (see the AI Governance ledger, handoff section 6).

## Baseline (Phase 0, read from the source, not from production)

What the code at `f770d33` already has, so a slice is not built twice. The deployed state of any tenant is not known from
here; the owner's VPS output reported the release healthy on 2026-10-14.

| Area | Present in the source | Gap named by the rework plans |
| --- | --- | --- |
| AI Governance | Intake (`ai_use_intake_requests`), profile and screening, inventory and workspace, guidance checklist, AIIA, decisions with conditions and expiry, evaluations, regulatory impact, Explain, review packs, human oversight, My Work, AI policy and rollout switch | Specialist home, Forms import, precedent review, outstanding-items workbench, external response, simpler navigation |
| AI literacy | `ai_literacy_courses`, `_versions`, `_completions`; learner and manager pages; My Work item; owner quality rule | Leaves the specialist navigation only after a consumer review (see 1A) |
| Evidence Vault | Paginated scoped list, metadata search, saved views, hash duplicate check, versions, links, coverage, AI link suggestions, campaigns | List-first screen, proof semantics, version impact, full text |
| Platform | Scoped My Work, global search, related items, reports, dashboards, predictive risk, canonical vendors | Source states, report snapshots, no synthetic fallback data |

## Slice status

| Slice | Plan | Status | Evidence |
| --- | --- | --- | --- |
| Shared source state (`core/metric_state.py`) | 04 section 2, 05 Phase 1 slice A | built, verified locally (SQLite) | `tests/test_metric_state.py` (12) |
| 1A Overview, portfolio monitoring and navigation | 01 sections 3, 5 | built, verified locally (SQLite, browser) | `tests/test_ai_governance_overview.py` (20), `_overview_routes.py` (21), the four browser files named below (51 passed) |
| 1B Forms import | 01 section 4 | built, verified locally (SQLite, browser); PostgreSQL case pending the stage lane | `tests/test_ai_governance_import_rules.py` (44), `_imports.py` (24), `_import_routes.py` (20), `tests/ui/test_ai_governance_import_ui.py` (5) |
| 1C Review desk, outstanding items, external response | 01 sections 5, 6 | built, verified locally (SQLite, browser, real PostgreSQL) | backend `test_ai_governance_questions.py` (10), `_external_responses.py` (19), `_precedents.py` (14), `_outstanding.py` (12), imports file (45 with the route file); browser `tests/ui/test_ai_governance_review_desk_ui.py` (6) and the seven other AI Governance browser files (66): all passed |
| 2A Vault library | 02 section 3 | built, verified locally (SQLite, browser, real PostgreSQL) | `tests/test_evidence_library.py` (12), `tests/ui/test_evidence_library_ui.py` (5) and the 22 existing Vault browser tests: 27 passed |
| 2B Vault proof semantics and version impact | 02 section 4 | built, verified locally (SQLite, browser, real PostgreSQL) | `tests/test_evidence_proof.py` (18), campaign decision tests (3 added to `test_evidence_campaigns.py`), the browser file above |
| 2C Assurance inspector and Find evidence | 02 sections 4, 6 | built, verified locally (SQLite, browser, real PostgreSQL) | `tests/test_evidence_inspector_find.py` (18), the PostgreSQL Vault test, `tests/ui/test_evidence_library_ui.py` (7) |
| 3A Change signals and publishers | 03 sections 1, 2 | built, verified locally (SQLite, real PostgreSQL) | `tests/test_change_signals.py` (41), the policy approval tests in `tests/test_aria_policy_approvals.py` (2), the replaced file assertion in `tests/test_evidence_proof.py`, the PostgreSQL case |
| 3B Connected view, changes page, My Work | 03 section 2, 05 phase 4 | built, verified locally (SQLite, browser, real PostgreSQL) | `tests/ui/test_governance_connected_ui.py` (3), the My Work service test |
| 3C Sentinel breach clock | 03 section 6 | built, verified locally (SQLite) | `tests/test_sentinel_breach_clock.py` (9) |
| 3D AI use signals and the other module kinds | 03 section 1 table | built, verified locally (SQLite) | inside `tests/test_change_signals.py`: one case per watched kind, and the decision, revocation and changed use handlers |
| 3E ERM acceptance, jurisdiction cards, GRID and BCM file convergence, module homes | 03 sections 3 to 9 | local build, focused verification; no release | ERM acceptance proposal/decision/history and My Work projection; one Vault artifact for each new GRID upload and BCM proof attachment; historical GRID file and version crosswalks; BCM legacy reference match; source-backed module overviews; Sentinel draft and DPO-approved rule cards with separate breach obligations. PostgreSQL verification, actual legal rule content, and a specialist pilot remain open |
| 4A Truthful dashboards and the metric registry | 04 section 2, 05 phase 1 slice A | built, verified locally (SQLite) | `tests/test_command_metrics.py` (7), `tests/test_dashboard_truth.py` (13) |
| 4B Reports: real paths, frozen runs, presets, notes | 04 sections 2, 5, 05 phase 1 slice B | built, verified locally (SQLite, browser) | `tests/test_report_runs.py` (22), `tests/ui/test_reports_and_search_ui.py` (6) |
| 4C My Work views, grouping, no duplicate actions | 04 section 3 | built, verified locally (SQLite, browser) | `tests/test_my_work_views.py` (6), `tests/ui/test_my_work_page.py` |
| 4D Search, related items and disputed connections | 04 section 4 | built, verified locally (SQLite, browser) | `tests/test_search_facts.py` (7), `tests/test_entity_scope.py`, `tests/ui/test_reports_and_search_ui.py` |
| 4E Platform functions, AI service declarations | 04 sections 6, 8 | built, verified locally (SQLite) | `tests/test_ai_declarations.py` (16), `tests/test_platform_functions.py` (3), `08-platform-functions-inventory.md` |
| 4F Command Centre first screen and the metrics page | 04 sections 1, 7 | built, verified locally (SQLite, browser) | `tests/test_first_screen.py` (5), `tests/test_metrics_page.py` (3), `tests/ui/test_command_centre_first_screen.py` (2) |
| 4G Acceptance scenarios | 04 section 9 | built, verified locally (SQLite); scenario 5 half covered | `tests/test_plan04_acceptance.py` (8) |
| 4H Predictive trace and the manager's team view | 04 sections 3, 9 (follow-up 11, steps 5 and 6) | built, verified locally (SQLite, browser, real PostgreSQL) | `tests/test_predictive_trace.py` (19), `tests/test_my_work_team.py` (12), `tests/ui/test_predictive_trace_ui.py` (3), `tests/ui/test_my_work_team_ui.py` (3), the PostgreSQL case |
| 4 Platform truth, navigation and reports | 04 | built, verified locally; see Not done (4) | the stage table below |
| 5 Delivery and acceptance records | 05 | built (documents only) | `10-completion-record.md` |
| 6 E0 Email inventory and decisions | 06 sections 2, 9 | built (from source; nothing read on a server) | `09-email-inventory.md` |
| 6 E1 Sender safety and truthful status | 06 sections 2, 7, 8 | built, verified locally (SQLite, browser) | `tests/test_email_transport.py` (12), `tests/test_email_producers.py` (reminders, administration), `tests/ui/test_admin_email_truthful_status.py` (2) |
| 6 E2 Outbox, templates and the pilot paths | 06 sections 3, 5, 6 | built, verified locally (SQLite, browser) | `tests/test_email_templates.py` (9), `tests/test_email_outbox.py` (18), `tests/test_email_producers.py` (36), `tests/ui/test_profile_email_preference.py` (3); the later cases are follow-up 11 |
| 6 E3 Urgent cases and management summaries | 06 sections 4, 9 | built for Sentinel breach and request deadlines, the GRID weekly summary, BCM incident and exercise mail, named AI Governance reviewers and deciders, and opt in My Work summaries with quiet hours. BCM acknowledgement and first alternate escalation were added in follow-up 12. Not built: jurisdiction wording and an alternate human contact for privacy deadlines | `tests/test_ai_governance_assignment.py` (13), `tests/test_bcm_escalation.py` (21), the browser files named below; see Not done (6) and follow-up 12 |
| 6 E3 BCM incident acknowledgement and escalation (follow-up 12) | 06 section 4; owner decision 3 | built, verified locally (SQLite, browser, real PostgreSQL); see the stage table | `tests/test_bcm_escalation.py` (21), `tests/ui/test_bcm_incident_escalation_ui.py` (4), the PostgreSQL case |
| 6 Hardening pack (follow-up 13): outbox purge, send budget, task hand over mail | 06 section 3, owner decision 5; Not done (6) | built, verified locally (SQLite, browser, real PostgreSQL); see the stage table | `tests/test_email_outbox.py` (23), `tests/test_task_assignment_mail.py` (7), the PostgreSQL case |
| 4 Badge text contrast (follow-up 13) | 04 section 7 (accessibility); follow-up 11 finding | built, verified locally (browser, both themes); see the stage table | `tests/ui/test_badge_contrast.py` (1) |
| 6 E4 Provider cutover | 06 section 7 | seams built in follow-up 11 (pause, comparison by provider, runbook [12](12-email-cutover-runbook.md)); the cutover is not possible, no managed sender identity exists | `tests/test_email_outbox.py`, `tests/ui/test_admin_email_truthful_status.py` |

## Change log

### 2026-10-16, My Work linked grouping continuation

- Added Vendor and Business process choices to My Work. AI use actions use the application's canonical provider. ORM events, ERM risks, GRID findings, BCM incidents and Sentinel request or breach actions use confirmed links to visible vendor or process records. Vendor links are merged under canonical identity where present. Grouping checks the viewer's source and linked-record scope. Actions linked to several vendors or processes appear in each relevant group without changing their underlying action count.
- Source actions without a qualifying link are labelled as such. Other actions appear under "Other work" until their source-owned vendor and process relationships are projected. This slice is local and unverified. Python and JavaScript syntax checks and `git diff --check` passed; no behavior tests, commit, push or deployment ran.
- My Work now ignores an earlier request after a newer filter request starts, so a slow response cannot append stale actions or group labels to the newly selected view.
- The ORM event drawer now mounts the shared Related Items panel so an authorized specialist can inspect and record cross-module relationships from the event they are reviewing. Browser and permission behavior remain unverified.

### 2026-10-16, report source traceability continuation

- Report runs now freeze each permitted source row ID alongside its source-recorded version and/or last change time where those fields exist. Sources without such fields say that revisions are not recorded. The report viewer shows the first 50 rows per source; its CSV exports the full bounded identifier list, revision detail and any truncation notice. This repairs the viewer's undefined identifier count and advances the report definition version.
- A source timestamp is explicitly described as incomplete change history because not every source workflow advances it. The report still lacks an enforced monotonic version for every table, per-figure row lineage, sharing, sign-off and retention. This slice is local and unverified; no behavior tests, commit, push or deployment have run.
- The shared Related Items picker now labels its search, holds focus inside the dialog, returns focus when closed, ignores stale search responses and keeps the picker open with a visible error when a link cannot be saved. Its browser and permission behavior remains unverified.
- Evidence Vault coverage now returns a null percentage for an empty denominator, explains that state in its definitions, and shows "Not measured" without a percentage bar in the Vault. Analytics narrative and its local Q&A no longer label an empty Vault healthy, imply that zero critical risks proves healthy posture, or show an unknown module score as 0%. Analytics now calls the module percentages indicators, labels their distinct numerators and denominators, and stops using one threshold to rate unlike measures. Source-by-source Analytics review remains open. This is local and unverified.

### 2026-10-15, local continuation after follow-up 13

- The owner confirmed that a risk owner proposes acceptance and a different Compliance Manager or Chief GRC Officer decides it. A Super Admin may administer. Reason, expiry and review date are required. The owner also confirmed that GRID and BCM should share a canonical Vault artifact while keeping module-specific review.
- The uncommitted ERM acceptance slice adds a human decision record, immutable risk/appetite snapshot, decision events, independent authority, expiry and source-change checks, drawer actions, and a My Work projection. Historical `accepted` risk labels are still counted as exposure until reconciled. No behavior checks have run for this slice.
- The uncommitted BCM compliance proof slice replaces the route's client-provided path mirror with a scoped Vault attachment and link. It retains legacy rows as migration-needed metadata and soft-deletes new link rows; it does not migrate prior files. GRID now scopes Vault attachment and download and mirrors versioned GRID files into Vault, but its physical GRID copy still exists. Final canonical storage, a file crosswalk and the historical audit decision mapping remain open.
- While reviewing this path, BCM incident proof link list, attach and unlink were found to accept an incident ID or Vault link ID without a matching source and artifact scope check. The local patch adds those checks and records the linking user's ID rather than their name.
- The uncommitted import follow-up adds saved mappings scoped by organization. A specialist saves only a mapping that came from a valid preview, reuses it for a later export, and still reviews that export before creating requests. An archived mapping does not rewrite historical batch snapshots. Python and JavaScript syntax checks pass; behavior checks and both database migrations remain unverified.
- The Related Items component can now create a first link from an empty ERM risk, escapes returned text, uses bound handlers rather than interpolating search data into code, and links to permitted source records. It is mounted only on the ERM risk drawer. Browser and permission behavior are not yet verified.
- This continuation used syntax parsing and a whitespace check only. The changed ERM, GRID and BCM routes, schema migrations, database engines and browser flows require behavior verification before release. No commit, push or deployment was done here.

### 2026-10-14, start

- Reconciled the AI Governance ledger (see its 2026-10-14 entry) and fast-forwarded the branch to `origin/master`.
- Read plans 01 to 06. Sequence followed: the owner asked for documents 01, 02 and 03 to be implemented in order and for the
  work to arrive at 04; the shared source-state contract that 04 describes is introduced first inside 1A because the
  Overview cannot be truthful without it.

### 2026-10-14, 1A: the specialist Overview, portfolio monitoring and navigation

**What a person gets.** `/ai-governance/` is now the Overview, not the inventory. A reviewer or decider sees seven cards (new
requests, waiting for information, awaiting an independent decision, approved with open conditions, reviews due, material
change since the decision, evaluation and oversight gaps), a request ageing table, and a funnel of requests by stage. Every
card says what it counts, its window and denominator, and opens the list it counted. Staff see their own open requests and the
uses they own, not the specialist numbers. The inventory moved to `/ai-governance/systems` and keeps its filters; a new
Monitoring page (`/ai-governance/monitoring`) lists every active use in scope with what needs looking at.

**Truthfulness rules built in.**

- `core/metric_state.py` is the one shape of a dashboard number: measured (a measured zero stays zero), not measured,
  unavailable, partial, stale. A source that fails is `unavailable` with no value; the other cards still answer.
- A use with no evaluation that carries a pass or fail threshold, or no oversight arrangement, is listed as not measured and
  is never counted as passing. The card says how many there are.
- The funnel names the two stages nothing records yet (responded, closed) as not measured, and excludes a superseded request.
- Each card reads through the function that produces the list it opens (`service.review_count` beside `review_queue`, the
  decisions queue, `workspace.list_systems`, `monitoring.get_portfolio`), so a count and its list cannot disagree. Everything
  is inside the viewer's business unit scope; a parent unit sees its children, never the reverse.

**Navigation at the end of 1A.** The sidebar was grouped as Work (Overview, Requests, AI systems, Reviews and decisions, Monitoring, Review packs)
and Also (impact assessments, regulatory changes, register an AI use, AI literacy history or My training). Platform AI
features left the customer sidebar and are linked from the Super Admin page. The review queue gained a "Waiting for information"
tab, and the Decisions page lists approvals with open conditions. The later navigation correction removes AI literacy from
this sidebar and removes literacy-only access from the main module rail. Existing course routes and assigned links in My Work
remain until the staff learning destination is ready.

**Literacy consumer inventory (done before touching its navigation).** What reads the course tables today: the learner and
manager pages (`/ai-governance/literacy`), My Work (one item per assigned course), the owner literacy quality rule, the shell
icon for people with no AI Governance access, and the notification handler for a published course. Nothing was removed or
hidden from those. At the end of 1A, managers and reporters saw "AI literacy history" and staff saw "My training" in the
sidebar. The later navigation correction removes those entries while retaining the direct course route used by My Work.
The routes, APIs, completions and history are untouched. The move to a separate staff-facing project is not built; see 01
section 8.

**Found on the way.** The 14 browser tests that opened the inventory through `/ai-governance/?q=` failed after the landing page
moved; they now open `/ai-governance/systems?q=`. That was a test dependency on the landing page, not a product defect.

**Checks.** Backend: 53 passed (`test_metric_state`, `test_ai_governance_overview`, `test_ai_governance_overview_routes`).
Browser: `tests/ui/test_ai_governance_pages.py`, `_decisions_ui.py`, `_assessments_ui.py`, `_guidance_ui.py`: 51 passed, including
accessibility scans and phone width checks of the Overview, the systems list and Monitoring. The capability inventory was
regenerated (1046 routes). The guidance route file and the call guard also pass.

**Not done in 1A.** The charts the plan lists beyond ageing and the funnel (review to decision time by tier, approval status by
business unit, evaluations by outcome) are not built. Incidents are not a column of the portfolio because they are linked per
use and there is no portfolio read of links yet. The funnel is for requests; a use created without a request is not in it.

### 2026-10-14, 1B: importing the responses of an external form

**What a person gets.** A reviewer opens Import form responses from the Requests page, reads the published field guide, and
downloads a CSV template for the customer form administrator. They upload a CSV or Excel export, choose where it was made and
how dates are written, check which column answers which question, see every response with what will happen to it, and
confirm. Each response becomes a draft request in the existing intake lifecycle, authored by the importing specialist, with the
requester name, contact and organization kept as their own facts. The requester gets no account and no access.

**Rules built in.**

- A preview creates nothing. Unmapped columns are shown to the specialist and dropped when the import is confirmed.
- An answer that is not understood is left open and reported (an unknown choice, an unrecognized yes or no, a date not in the
  declared order); a cell over 4000 characters, an answer over its limit or a response with no name is an error and never
  becomes a request. Nothing is cut or guessed. A numeric date is read only in the order the specialist declares.
- A response is identified by its response id when the export has one, otherwise by the requester email and the use name,
  under the organization and the form name. The same response again is a duplicate and creates nothing, including when two
  imports race (a partial unique index on the source key and fingerprint backs the check).
- A corrected response is a new revision with a difference list. The earlier request is never edited: if nobody has decided it
  it is marked superseded; if it was accepted into the inventory it stays as it is and the revision is a new draft that says so.
- An owner is a person the specialist confirmed or an explicit gap. The import offers candidates (an exact email, else an exact
  name) and never assigns. A draft with the owner open cannot be submitted.
- The file is only read as text: size, row, column and cell limits, an unzipped size limit for workbooks, values only (no
  formula is evaluated), no link followed. A preview not confirmed in seven days is deleted on the next preview.

**Schema (additive).** New table `ai_import_batches`; seven nullable or defaulted columns on `ai_use_intake_requests`
(`source_kind`, `import_batch_id`, `source_key`, `source_fingerprint`, `requester`, `revision`, `supersedes_id`); one partial
unique index; the batch table is in the business unit reference guard. No existing row is changed.

**Checks.** `tests/test_ai_governance_import_rules.py` (44), `_imports.py` (24), `_import_routes.py` (20),
`tests/ui/test_ai_governance_import_ui.py` (5, with accessibility scans and a phone width check): all passed.

**Assumptions to verify with a real export.** The column header texts of Google Forms and Microsoft Forms exports, the
position of an id column, how an edited response appears, and the date format of the timestamp column were written from the
published behaviour of those tools, not from a customer file. Until a real export is inspected the mapping step is the
safety: a column the import does not recognize is left for the specialist to place. Direct Forms integration, a bounded
invitation form, email parsing and attachment handling are not built.

**Not done in 1B.** A saved, versioned mapping reused for the next export of the same form (the mapping is chosen per import
and recorded on the batch). A workbook with several sheets reads only its first sheet. The unified Requests queue with the
tabs of 01 section 3 (New, Needs clarification, In assessment, Awaiting decision, Responded, Closed) is not built; the review
queue and My requests remain separate screens, with an Imported label.

### 2026-10-14, 1C: the review desk (outstanding items, precedents, questions, the response to the requester)

**What a person gets.** A reviewer opens an AI system and finds a **Review desk** tab (staff do not see it, and a link to it
falls back to the Overview for them). It holds four panels, each loaded on its own so one failing source affects only itself:

1. *What is left before a decision.* One line per thing, each with one owning module, a state (done, not applicable, not done
   yet, waiting on someone, needs attention, could not be read, not open to you), the sentence that explains it, the owner, a
   due date where one exists, whether it holds the decision, and the place to resolve it. The lines come from the owning
   modules' own records (facts the profile must supply, a named owner, the required assessments, evaluation with a threshold,
   human oversight, proof for implemented AI controls, continuity impact, regulatory change, the independent decision, open
   conditions). A source that cannot be read is *could not be read*, never done. The summary says when a decision is not
   ready, and says in the same place that nothing here approves a use.
2. *Has the organization seen something like this?* Other uses the viewer may open, in three bands (confirmed as the same
   use, possible match, related precedent) with why each matched, what differs, its owner and unit, its last signed decision
   and latest evaluation, and a few linked records. A specialist can say a candidate is the same use, related, or not related,
   with a note, and can take that back. The verdict links nothing, merges nothing and approves nothing. The panel says that a
   decision about another use does not apply to this one. The same panel sits in the review queue for a request not yet in
   the inventory.
3. *Questions for the requester.* A reviewer writes up to twelve short questions on a request, takes the open ones out as plain
   text to send by whatever channel the customer uses, and records each answer with who entered it and where it came from. A
   request with an open question is waiting for information: it appears under Waiting for information in the review queue and
   in the Overview card, counted from the same function. The panel is in the review queue detail and in the review desk of the
   use that came from the request.
4. *Response to the requester.* A short document with the outcome, scope, conditions from the decision, what the requester
   still has to do, the review date, the source reference and the response date. It is drafted from the standing signed
   decision, edited by a reviewer, approved by a different person who may decide (the same separation as the decision itself),
   which freezes it under a SHA-256 hash, downloaded as PDF or JSON (each download is recorded as an export), and recorded as
   sent by a person with the date, the channel and a reference. A download is never shown as delivery. If the decision it
   rests on is revoked, expired or replaced, the response can no longer be approved or exported and the panel offers a new
   revision.

**Rules built in.**

- Deterministic and versioned: outstanding items rules `o1`, precedent rules `p1`. No model sets a line's state or a match.
- Every read goes through the viewer's business unit scope. A use or request the viewer cannot open is not a candidate, not a
  count and not a line; a hidden record answers 404 exactly as a missing one does.
- A precedent is a prompt to look: name alone is weak evidence, a shared provider or purpose adds reasons, and a prior approval
  is shown as that use's own decision.
- The external response carries no internal id, no reviewer name, no score and no evidence; the PDF holds no more than the
  JSON. The text a person types is escaped when the PDF is built and rendered as text in the page.
- All changes use compare-and-set on a version, so two people acting on the same draft get a clear conflict, not a silent
  overwrite.

**Schema (additive).** Three new tables: `ai_precedent_verdicts`, `ai_request_questions`, `ai_external_responses` (the last is in
the business unit reference guard). Nothing existing is changed. The system payload gained `source_request` (the request the use
was accepted from, for reviewers who may open it) and each response in a use's list carries `stands`.

**Found on the way.** `imports.confirm` relied on a check before the insert; on PostgreSQL two specialists confirming previews
of the same new response at the same moment would have raised a unique violation and returned a server error for the second.
The insert now uses `ON CONFLICT DO NOTHING` and the second is reported as a duplicate (SQLite test added; the PostgreSQL case
is in `test_ai_forms_import_review_desk_and_responses_run_inside_a_tenant_on_real_postgres`).

The first version of the PDF export escaped its own bold labels twice, so the PDF would have shown literal `<b>` tags and
`&amp;` for an ampersand; the earlier test only checked the `%PDF` header and did not read the text back. It is fixed, and a
test now extracts the PDF text and checks it says the same words as the JSON with nothing escaped twice.

**Not done in 1C.** The G4 decision brief does not yet carry evaluation outcomes or an intended scope of use (plan 01 section 6);
changing the signed manifest is a separate, careful change. Precedent sources are the AI uses and their linked records;
GRID audit outcomes, ARIA policy and control versions and Vault evidence versions are not searched as precedents, and a
candidate does not show a source version id. There is no sponsor line in the outstanding items (only the owner). The response
has no organization branding and no translation. ThemisIQ never emails the requester; the question export and the response
download are for the specialist to send.

### 2026-10-14, 2A and 2B: the Evidence Vault library and what a file proves

**Built, committed in `d20d202` and merged as pull request 10.** `modules/evidence/proof.py` (new), `modules/evidence/routes.py`,
`modules/evidence/templates/evidence_index.html`, `modules/evidence_campaigns/data_service.py` (one hook),
`modules/governance/effectiveness.py`, `core/rbac.py` (new capability `evidence.link.review`), `database.py` (nine additive
columns), `docs/generated/capability_inventory.*` (regenerated, 1067 routes).

- **Three measures, one definition each.** A live link, current proof (current version, not expired, not turned down) and
  accepted by a reviewer are counted separately per module and record kind, with `/evidence/api/coverage/definitions`
  publishing the wording. The old `with_evidence` and `pct` keys keep meaning "a live link". The control effectiveness score
  no longer counts a link a reviewer returned, rejected or ruled out.
- **A reviewer's verdict on each link** (`POST /evidence/api/links/{id}/review`): accepted, returned, rejected, does not apply,
  or back to waiting. Needs `evidence.link.review` and the right to open the record; the person who attached the file or made
  the link cannot review it; only the current, unexpired version can be accepted; compare-and-set on the status the reviewer
  saw; a reason is required to turn a link down; audited. A hash, a link count or the metadata health score never accepts
  anything. The old "Confidence" label is now "Metadata health" and says it proves nothing.
- **A new version never inherits a verdict.** Replacing a file proposes its links on the new version (only to records the
  uploader may open), each waiting for its own review; the old links stay as history. `/api/items/{id}/impact` and the Versions
  tab say what the new version did to the claims of the old one, naming only records the viewer may open. "Add a new version"
  is now an action in the detail panel (the upload form never sent `replace_id`).
- **Collection requests and links agree.** Accepting or returning a request records the same verdict on the link for the file
  and record it was about, creating the link when the submission had none.
- **Library.** Search first, then work views whose counts are the stats and the lists (All, Needs filing, Waiting for review
  for reviewers, Review due, Requests, Recently updated), filter chips, the list as the default, columns Name and source,
  Linked claims, Owner, Review due, State, Updated, and the totals, recently added and coverage behind a collapsed Insights
  panel. Owner, review date and the period a file covers are new fields (review date is not expiry).
- **Duplicates.** An upload whose hash matches a file in a unit the caller cannot open is refused without naming it.
- **Checked on the way in:** dates, status values and the owner (an active person of the caller's organization).

**Found on the way.** The review queue cleared its own "Accepted" announcement whenever other requests were still waiting,
because selecting the next request reset the status line; and a slower answer for an earlier choice could replace the request
now shown. Both are fixed in `ai_governance_lists.js` and covered by the review desk browser tests.

**Not done (2A and 2B).** No artifact family row (versions are still the `parent_id` chain). The guided upload that links in
the same step is not built (link after upload). The period a file covers is shown and checked for order but not yet used in a
freshness rule. GRID and BCM still keep their own file stores; no convergence or crosswalk. "For my review" is shown as
"Waiting for review" because target visibility is not evaluated in SQL, so the count is of files, not of claims the person
may open. On a phone the list scrolls inside its own box rather than stacking. The API field is still `confidence_score`.
Self acceptance is refused with no switch for a tenant with one specialist: a product decision for the pilot.

### 2026-10-14, 2C: the assurance inspector and Find evidence

**What a person gets.**

- **Quality checks.** Under Insights, and on each file under Checks, deterministic checks (rules `i1`) name concrete defects,
  each with the rule, why it matters, the claims affected (only those the viewer may open) and where to put it right: a file
  with no owner; an expired file that still supports claims (they no longer count as current proof); a new version that
  leaves behind claims the old one supported; a link a reviewer turned down; a link that has waited more than 30 days for a
  reviewer; a file describing a period that ended over a year ago; a file with claims and neither a review date nor an expiry;
  and two current files with the same title (a suggestion only). A file with no finding has no known defect, and the page
  says that is not a statement that it is sufficient. Nothing is changed by the inspector and no model plays a part in it.
- **Find evidence.** A question in the person's own words becomes editable filters (words that must all match, a state, a
  module, "only mine") over the same scoped list, and up to five files come back with why each matched, its version and
  state, its owner and dates, and the claims it supports that the person may open. It can answer "No accessible match". The
  filters can be changed and the whole result opened in the library. It is read-only.
- **How the question is read.** By rules always. By a model only when the organization's AI policy allows (feature
  `evidence.find_evidence`, category business): the model receives the question and the vocabulary and nothing from any file,
  and its answer is cut to the vocabulary before use. If the model is off, not configured, refused by policy, fails or answers
  nonsense, the rules read it and the note says so. The manual path never depends on the model.
- **State filters that match the state column.** `needs filing`, `awaiting review`, `accepted`, `returned` and `expired`
  partition the current files exactly as the state a row shows; an expired file is "Expired", not "Needs filing", in the
  list, the tab and the count.
- **Owners of existing files.** Files that existed before the Vault named owners get their uploader as owner, once per
  schema, so the inspector does not open with a finding for every old file.
- **The AI use's Evidence tab** now says what each file proves for that use (replaced, expired, archived, or the reviewer's
  verdict, which is "waiting" until a reviewer says).

**Found on the way.** The real PostgreSQL lane caught `updated_at >= text` on a timestamp column in the "Recently updated"
view and count (SQLite compares text and hid it); it now uses the helper that gives the column's own type. Existing "expired"
and "N days left" badges failed colour contrast and were corrected, and coverage module names are no longer coloured text.

**Not done (2C).** No document text extraction, so search is metadata only and "not indexed" is not yet a state; no retrieval
of file content by a model (a later gate by the plan). The inspector has no period-against-claim rule because claims carry no
period yet. Reuse suggestions are title-based only. The inspector scans the first 2000 current files and says when that
limit was hit.

### 2026-10-18, Evidence Vault guided filing and version access extension

**Built locally, not released.** The upload dialog can select an accessible module record through the scoped entity search.
The upload route checks the record, owner and replacement before storing a file, gives the file the selected record's business
unit where present, and commits the file row and a pending review link together. A failed write rolls back rows and removes
the newly written file. A replacement must name a visible current version, and a selected link already carried from the
old version is not duplicated. Version history returns only a contiguous visible chain, without hidden parent IDs or file
metadata, and the UI can open each visible version. AI Governance records are included in the target search allowlist.

**Focused evidence.** The new guided-upload backend cases, existing Vault library and proof cases, a browser upload to an
ERM claim, and 500-item browser pagination were run locally. The 500-item check proves reachability, not production search
latency or a 5,000-item capacity target. Document text extraction, OCR, artifact families and the real PostgreSQL gate remain
open under plan 02. See `PLAN_EVIDENCE_VAULT_GUIDED_UPLOAD_2026-10-18.md` for the slice and its limits.

### 2026-10-14, 3A to 3D: change signals, the connected view and Sentinel's breach clock

**Built, committed in `d20d202` and merged as pull request 10.** New: `modules/governance/change_signals.py`, `modules/governance/entity360.py`,
`core/change_watch.py`, `modules/governance/templates/connected.html`, `static/js/governance_connected.js`. Changed:
`database.py` (two tables), `core/rbac.py` (capability `governance.change.review`), `modules/governance/routes.py`,
`entity_scope.py` (one accessor), `data_service.py` and `templates/index.html`; the update functions of Sentinel, GRID, BCM,
ERM and ORM (one decorator each); `modules/aria/routes.py` and `policy_workflow_service.py`; `modules/evidence/routes.py`,
`proof.py` and `templates/evidence_index.html`; `modules/ai_governance/handlers.py`, `templates/workspace.html` and the review
queue script; `modules/launcher/my_work_service.py` and `templates/my_work.html`; `modules/sentinel/jurisdictions.py`,
`data_service.py` and `templates/index.html`; `docs/generated/capability_inventory.*` (regenerated, 1075 routes).

**What a person gets.**

- **Changes to look at** (`/governance/changes`, a tab in Governance, and My Work under "Needs my action"). When a record that
  other records depend on changes in a way that matters, the owner of each connected record gets one item that says what
  changed (the field, what it was, what it is, by whom, when). They answer **It needs a second look** (a task is opened for
  them, naming both records) or **No action needed** (a reason is required). Nothing in the connected record is edited,
  closed, re-opened or re-scored, so an earlier decision, approval or assessment keeps the basis it was made on.
- **What counts as a change.** An application (criticality, hosting, provider, type, unit, owner, in use), a business
  process (criticality, recovery time and point objectives, unit, owner, in use), a data asset (classification, the kinds of
  data it holds, system, unit, owner), a vendor in Sentinel, GRID or BCM (risk level and the like, and the same company in the
  other two modules, found by canonical id), a processing record, a DPIA, a breach, a data subject request, an audit, an audit
  control, a finding, a continuity plan, a BIA, an incident, an exercise, a continuity risk, an enterprise risk, an operational
  event, a key risk indicator, an ARIA control (status, owner, version), an approved policy version, a file replaced by a new
  version, and an AI use that was decided, revoked or changed in a way its approval covered. Saving a record with nothing
  that matters changed, or the same change twice in a day, is not a new signal.
- **Connected view** (`/governance/connected/{module}/{type}/{id}`, linked from an AI system's header and from the
  Governance tables). One record, its owner and unit, the records connected to it grouped by the module that owns each, the
  proof held for it and the state of each file, and the changes that name it. A connection nobody confirmed is marked
  "Proposed, not confirmed". A section that could not be read says so and is never shown as empty.
- **My Work** also carries the evidence waiting for a reviewer other than the person who attached it ("Review evidence: file
  for claim") and the changes to look at.
- **Sentinel breach clock.** A breach with no recorded discovery date has no clock ("Clock not started"), and a regulation the
  platform has no rule for has none either (the stored deadline is empty too, so the scheduler and the dashboards do not
  count down from a guess). A fixed rule says "Indicative: N hours after the recorded discovery date under the regulation"
  and a privacy specialist confirms the legal trigger. A regulation that says "as soon as practicable" says that any
  countdown is an internal target. The deadline now follows an edited discovery date or regulation (it was set once, at
  creation), and an explicit deadline in an update is kept as given.
- **The Vault's owner editor** finds a person by typing a name. It listed the first thirty names alphabetically, so in an
  organization of more than thirty people most owners could not be chosen.

**Rules that hold.**

- **One signal per change.** The key is the change itself (whole values) and the day, enforced by a unique index; a retry
  never doubles the work. A signal reaches only records connected through a confirmed link, so a proposed link, or a similar
  name, reaches nobody.
- **Both ends must be openable**, as with a link. A person sees a signal only when they may open the record to look at and the
  record that changed; otherwise it answers like one that does not exist, so nothing says that a hidden record changed. No
  title is stored with a signal (a data subject's name would otherwise be copied out of its own record), and a long value is
  stored in its first 120 characters, so free text is not copied into another table.
- **Who may decide.** The owner of the connected application or process, or a holder of `governance.change.review`
  (administrators, compliance, GRC, audit, DPO, BCM and risk owners). Compare-and-set on "open", so two people deciding
  cannot both succeed; a decided signal is final. Another organization's signals do not exist for the person.
- **A failure never costs the edit.** Publishing runs inside a savepoint (inside the update's own transaction for an
  application or process, and in its own connection after the update for the others) and is logged, not raised.
- **Event driven where an event existed.** An AI decision, a revocation and a material change of an AI use are published from
  the existing event handlers, so they inherit the event bus's retry and its dedup key. A changed use is only told while an
  approval stands, because only then did an approval cover what changed.

**Found on the way.**

- **A real race in the review queue.** The queue selects its first request on its own, and the form of the request shown a
  moment ago stayed on screen, with a working Accept button, while the request a reviewer had just clicked was still loading.
  Pressing Accept in that window decided the wrong request. The form is now replaced by a loading line the moment another
  request is chosen. It surfaced as two browser failures at the end of a 116 test run (the 5th and 6th review desk tests,
  alternating from run to run): a request left waiting by an earlier test was first in the queue. The tests that click a
  queue item now also wait for that request's own heading.
- **My first design said that a hidden record had changed.** A connected record that the reader could not open was shown with
  a note that "a record this one is connected to changed". That note is itself the existence of a hidden record. Both ends
  must now be openable, as for links, and the task a person opens names only a record they may open.
- **The data subject's name.** The first design stored the changed record's title with the signal, which would have copied a
  requester's name out of a data subject request. No title is stored.

**Not done (3).**

- **Governed risk acceptance in ERM** (section 7): the owner approved the authority rule on 2026-10-15. A local, unverified
  proposal and decision record now exists with expiry and review dates, separate approval and a My Work projection. The
  schema, route behavior, legacy accepted labels and report treatment still need review before release.
- **Jurisdiction cards with a source, rule version, timezone and approver** (section 6): they need legal approved content.
  One breach still has one regulation and one clock, and the clock says it is indicative. Several obligations on one breach
  is not built.
- **One file identity for GRID and BCM** (sections 4 and 5): the owner approved a canonical Vault artifact on 2026-10-15.
  BCM's new compliance proof attachment uses one Vault artifact and GRID can attach one too. GRID's upload mirror still
  keeps a separate physical copy, and historical GRID and BCM files need an organization-scoped inventory and crosswalk
  before a final cutover.
- **Module homes with Act now, Portfolio, Trends and Coverage** (section 9): they depend on the metric registry of plan 04.
- **Truth repairs that open plan 04**: the ARIA "Generate Report" timer toast, the BCM report types that the shared engine
  does not register, the BCM and Sentinel example data after a failed read, and frozen saved report runs. They are the first
  items of plan 04 section 2 and were left for it.
- **No inference.** A change reaches only records connected through a confirmed link. A vendor that nobody linked to a record
  informs nobody. There is no matching by name, and no automatic link.
- **Quiet changes.** A change made directly in the database, by an import that does not go through the update functions, or
  in a screen that writes the table itself (the ARIA risk and document forms) publishes nothing. The control update and the
  approval of a policy version are wired; the others are listed here.
- **A burst.** A bulk edit that goes through the update functions publishes one signal per changed record, each with up to
  200 targets. There is no batching or rate limit.
- **The Related Items panel** (`static/js/related_items.js`) is now mounted locally on the ERM risk drawer, with its empty
  state, scoped link picker, safe text rendering and target link repaired. Other module detail screens still need a mount and
  browser review. The connected view also remains reachable from the AI system header, Governance tables, My Work and the
  changes page.

### 2026-10-14, plan 04: what was found before building

Read from the source on the branch `claude/plan-04-platform-truth` (cut from `master` at `a568b75`), not from production:

- **Three screens still invent numbers when a read fails.** `templates/command_centre.html` carries a `fallback` object (78%
  compliance, "ISO 27001 . ISO 9001 . PCI DSS", seven named overdue actions) that is shown when `/api/command-centre/stats`
  fails. `modules/bcm/templates/index.html` shows a made up plan list, risk spread, activity feed and two incidents when
  `/bcm/api/dashboard` fails or omits a field, and again on its Reports view. `modules/sentinel/templates/index.html` shows
  24 processing records, 72 per cent coverage, five named data subject requests and an activity feed, and when the read
  succeeds it still computes coverage against a constant (`Math.max(count, 33)`).
- **Zero stands in for "could not read".** The Command Centre API sets `sentinel_open_breaches`, `orm_open_events`,
  `bcm_active_incidents` and the appetite count to `0` inside `except` blocks, shows module health as 100 per cent when a
  module has nothing recorded, and has two near copies of the statistics (one for super administrators, one scoped).
- **The BCM dashboard is not scoped.** `/bcm/api/dashboard` counts every unit's plans, incidents, exercises and analyses.
- **Reports.** ARIA "Generate Report" shows "Report generated successfully" after two seconds without calling anything. The
  five BCM report buttons post definitions of types the shared engine does not register (`bcm_coverage`, `bcm_plans`,
  `bcm_incidents`, `bcm_exercises`, `bcm_summary`), so each ends in "Report generation failed". A saved run stores its
  output only for a super administrator; for anyone else opening the run recomputes today's numbers and shows them under the
  run's name.
- **Search** covers fourteen kinds with their own scope but returns no status, date or business unit, and does not search AI
  uses or the Governance structure.

Slices, in the order built: 4A (the registry, then the Command Centre, BCM and Sentinel dashboards), 4B, 4C, 4D, 4E, 4F.

### 2026-10-14 and 15, 4A to 4G: platform truth, navigation and reports

**Built, committed as `cbf9372` and pushed on the branch `claude/plan-04-platform-truth`.** New: `core/metric_registry.py`,
`modules/launcher/command_metrics.py`, `modules/bcm/dashboard_metrics.py`, `modules/sentinel/dashboard_metrics.py`,
`modules/launcher/report_snapshot.py`, `modules/launcher/report_builders.py`, `modules/launcher/search_service.py`,
`modules/launcher/first_screen.py`, `core/ai_declarations.py`, `modules/launcher/templates/metrics.html`. Rewritten:
`modules/launcher/routes_reports.py` and `templates/reports.html`. Changed: `routes_dashboard.py`, `routes_platform.py`,
`routes_my_work.py`, `my_work_service.py`, `scoped_metrics.py`, `templates/command_centre.html`, `analytics.html`,
`my_work.html`, `base_shell.html`, `static/js/my_work.js`, `governance_connected.js`, `modules/bcm/{routes,ai_service}.py` and
`templates/index.html`, `modules/sentinel/{routes.py,templates/index.html}`, `modules/erm/{routes,ai_service}.py` and
`templates/index.html`, `modules/orm/{routes,ai_service}.py`, `modules/aria/{routes.py,templates/dashboard.html}`,
`modules/evidence/routes.py` (`coverage_for`), `modules/governance/{relationships,entity360}.py`, `core/ai_client.py`,
`core/predictive_risk.py`, `core/framework_service.py`, `main.py` (two exception handlers), `scripts/capability_inventory.py`.

**What a person gets**, by slice.

- **4A, a number says what it is.** Every Command Centre card carries a state. A figure that could not be read is
  *unavailable*, never a zero; one with nothing to measure is *not measured*, never a good looking 100 per cent; a sum that lost
  a source is *partial* and names it; a module the viewer may not open sends no metric at all. Each figure has a stable key, a
  plain definition, a denominator and a drilldown (or the reason it has none) in `core/metric_registry.py`, and a control
  counts as implemented only by the status the registry names, never because a document exists. The Command Centre no longer
  has a fallback object (78 per cent compliance and seven named overdue actions when a read failed), and the legacy keys
  `compliance_pct`, `sla.pct` and `module_health[].pct` are `null` when nothing is recorded. The BCM dashboard reads through the
  viewer's units and its sample plans, risks, activity and incidents are gone, also from its Reports view. The Sentinel page
  computes coverage against the real number of processing records, or says it is not measured, instead of against a constant.
  Board narratives are given figures and never a record title.
- **4B, a saved report is the document that was made.** A run keeps a canonical envelope (who, when, for which scope, which
  sources were read and which could not be) and a SHA-256 of its exact text. Only the person it was generated for opens it; if
  they lose access the output is hidden and the refusal is written to the audit log; a run changed in the database is refused;
  a run saved before reports were frozen is labelled *legacy* and is never recomputed; running again makes a new run linked to
  the one before it with a change summary. A source that could not be read is blank in the run, and the run says it is
  incomplete. Reviewer notes and disputes sit in `report_run_notes`, beside the run, which is never edited. Seventeen report
  types: the module reports, four presets (specialist, management, board, case) built over the same definitions, and the five
  BCM types the buttons asked for (they were not registered, so each ended in "Report generation failed"). The ARIA Generate
  Report button now makes a real run instead of announcing success after two seconds. The executive figures are a frozen run
  even when the assistant is off; a narrative is a draft kept with its run and given only figures. CSV export is the frozen run
  and text that looks like a formula is written as text.
- **4C, My Work is one list of obligations.** An unread notification is a *change*, not an action (a new "Recently changed"
  section); an item and the notification about it are one line that says it was also notified. Every item says what kind of
  action it is, who acts and why it is ranked where it is. Grouping (none, by source, by unit, by parent such as the audit a
  finding belongs to) is presentation only and names each group.
- **4D, search says what a result is.** A result carries its status, date, unit and a short permitted snippet (the narrative
  of a privacy record is never one), through the same unit scope as the result itself. AI uses and the Governance structure
  are searchable. Search inside a case returns only connected records the viewer may open. A connection is shown as
  recorded, suggested or disputed, and a disputed one is marked in the connected view.
- **4E, AI use cases declare themselves, and a feature that needs the assistant does not make an answer up.**
  `core/ai_declarations.py` declares 54 places that call a model (the task, what it reads and leaves out, who starts it, what
  becomes of the answer, whether a person reviews it, and what happens when the assistant is not available); the AI
  Governance platform features page shows it. A policy refusal reaches the person with its own sentence (403) and "the
  assistant is not available" is a 503 with the reason. The defects found while declaring are listed below.
- **4F, the Command Centre first screen** answers four questions (what needs me, what changed, what do I have to prove, what
  can I report) from sources that exist, each read through the person's scope, one failing source blanking only its own
  panel. `/metrics` lists the definitions of the figures of the modules the person may open.
- **4G, acceptance.** `tests/test_plan04_acceptance.py` has one test per scenario of plan 04 section 9, written against what
  a specialist sees.

**Rules that hold.**

- A source that failed is never a sample value and never a zero. A module the viewer may not open is not announced.
- A report figure is read once, through the viewer's own scope, then frozen. Opening a run later never recomputes it.
- Counts, lists, exports and the narrative for one person agree because they read through one scope helper.
- AI writes nothing a person did not review, except the three places named under Not done (4), which are declared as such.
- A prediction never creates a risk: a critical predictive alert goes to the ERM emerging-risk inbox for a person to review.

**Schema (additive).** One table, `report_run_notes`; three columns: `report_runs.snapshot_hash`,
`report_runs.previous_run_id`, `ai_risk_predictions.emerging_id`. Nothing existing is rewritten. Old runs keep their rows and
are labelled legacy.

**Found on the way.**

- **A plan review that nobody made.** `POST /bcm/api/plans/{id}/reviews` returned a fixed score of 72 with canned strengths
  when the assistant was off, and then failed to save it (a list was bound to a text column), so the button was broken in both
  modes. It now saves a real review with its provider, checks the plan's unit, and does not run when the assistant is off.
- **A risk score written over the owner's.** `POST /erm/api/ai/score-risk/{id}` wrote likelihood and impact for anyone holding
  `erm.ai.use`, without a unit check, and wrote a canned 3 by 3 when the assistant was off. It now suggests a score and the
  page asks the person to confirm it through the ordinary update, with its own capability and scope.
- **Fabricated content.** `identify_risks_from_responses` returned "Risk identified from assessment" at 3 by 3, and the
  operational event analysis wrote a canned root cause into the event, both with the assistant off. Now unavailable, and the
  event analysis fills only empty fields, only in the person's unit.
- **A prediction that made a risk** (above). **Policy refusals were swallowed** by services that caught every exception.
- **The topbar search lost the colon** of `?open=control:12`. It now keeps any path on this site and refuses all else.
- **Imported risks had no business unit**, so every imported risk was organization wide. They take the importer's unit.
- **The capability inventory** listed seven mutation routes as sign-in only because `require_auth` wraps the capability
  check. They are capability gated; the generator now sees through the wrapper.
- **Em dash characters** introduced by this slice into templates and code were replaced (a rule of this repository).

**Checks.** Backend: `test_command_metrics.py` (7), `test_dashboard_truth.py` (13), `test_report_runs.py` (22),
`test_my_work_views.py` (6), `test_search_facts.py` (7), `test_ai_declarations.py` (16), `test_first_screen.py` (5),
`test_metrics_page.py` (3), `test_platform_functions.py` (3), `test_plan04_acceptance.py` (8), plus the changed
`test_entity_scope.py` and `test_platform_ownership_surfaces.py`. Browser: `tests/ui/test_reports_and_search_ui.py` (6),
`test_command_centre_first_screen.py` (2), `test_my_work_page.py`. Full backend result: see the stage table.

**Not done (4).**

- **Vendor and process grouping** in My Work has a local, unverified first slice. AI-use provider IDs and confirmed links
  from ORM events, ERM risks, GRID findings, BCM incidents, and Sentinel requests and breaches group work by a visible vendor
  or process. Vendor identity is canonical where present. Both endpoints are scoped, and actions with no such link are labelled
  as unlinked. Other source actions and unverified UI behavior remain open.
  The manager's team view was built afterwards (follow-up 11, step 6).
- **A predictive number's trace** (acceptance scenario 5, second half) was built afterwards (follow-up 11, step 5). A
  prediction made before it carries no trace and says so.
- **Report sharing, a review workflow with sign-off, and retention** of saved runs: a run is for one person and is kept.
- **Incomplete per-record version stamps** in the envelope: the 2026-10-16 local patch freezes version and last-change fields where a source records them, and labels missing fields. These are not yet enforced on every write, and the identifier list is scoped source rows rather than exact per-figure lineage. Browser and database behavior remain unverified.
- **ERM and ORM dashboard scope:** a 2026-10-15 local patch scopes dashboard figures and their AI board inputs to the
  viewer's business unit. It is not behavior-verified yet. Unowned records, organization-wide KRIs and cross-module event
  payloads still need an explicit source-ownership contract.
- **Workflow authoring** is open to every signed-in user of the organization (08 inventory); which role authors workflows is a
  product decision.
- **Three places still write without a review step**: auto-mapping of controls, the regulatory drift check and checklist
  import risk scoring (declared in `WRITES_WITHOUT_REVIEW`). The three chats and the three board narratives still return a
  labelled placeholder when the assistant is off, not analysis.
- **Analytics empty-data states** still need a source-by-source review. The Vault coverage `pct` now returns null for an empty denominator in a local unverified patch.
- **The Related Items panel** is locally mounted on the ERM risk and ORM event drawers; other module homes still need an entry point
  and browser review (see Not done (3)).

### 2026-10-15, plan 06: email notifications and delivery (E0, E1, E2, and part of E3)

**Built, committed as `cbf9372` and pushed on the branch `claude/plan-04-platform-truth`.** New: `core/email_templates.py` (the catalogue and its renderer),
`core/email_outbox.py` (the outbox, its worker and `for_each_tenant`), `plans/2026-10-governance-rework/09-email-inventory.md`.
Rewritten: `core/email.py` (the transport), `core/reminder_scheduler.py`, `modules/sentinel/scheduler.py`,
`modules/evidence/scheduler.py`, `modules/grid/email_service.py`. Changed: `modules/grid/scheduler.py` (the mail jobs),
`modules/grid/routes.py` (finding assignment and the share result), `modules/launcher/routes_admin.py` and
`templates/admin_email.html`, `routes_auth.py` and `templates/profile.html`, `task_service.py`, `main.py` (demo request),
`database.py` (one table, three columns), `docs/generated/capability_inventory.*` (regenerated, 1090 routes).

**What a person gets.**

- **An administrator sees the truth about the sender** (Admin, Email Settings). The badge says *Configured* only when a host,
  user and password exist, and says *Console only* or *Incomplete* otherwise. A password is a deployment secret
  (`SMTP_PASS`, `MS_CLIENT_SECRET` in the service environment): the page explains that, disables the field, and refuses to
  store a new one in the database unless the operator set `EMAIL_ALLOW_DB_SECRETS`. A copy stored by an earlier version is
  still read so a running installation does not stop, is reported as obscured and not encrypted, and can be cleared with an
  explicit, confirmed action once the secret has moved. The test message reports what happened in words that cannot be taken
  for delivery (*the provider accepted it*, *nothing was sent*, or *the provider did not accept it*) and asks the
  administrator to say whether it arrived. A delivery queue lists counts by state and what needs attention, with a button to
  send a message again, and shows no recipient and no text.
- **A message says one thing and links to it.** Eleven templates form the catalogue and ten have a producer: a task
  assigned to someone else (`action.assigned`); a finding assigned (`audit.finding`), its response deadline
  (`audit.deadline`) and its escalation (`audit.escalation`); a control reminder a person subscribed to
  (`control.reminder`); evidence that is about to expire (`evidence.renew`, to the file's owner or, when it has none, its
  uploader; asked for by the Evidence job, the GRID vault job and GRID evidence files); a privacy deadline and a request
  deadline for the named privacy officers (`privacy.deadline`, `privacy.dsr`); a weekly audit summary (`summary.weekly`);
  and `delivery.failure`, which tells the administrators of an organization, once a day, how many messages ended as a
  permanent failure in the last seven days. `decision.ready` has no producer (see Not done (6)). Each message is a fixed
  subject, a reference, a date, one link to the record, a plain text part and an HTML part that say the same thing, and why
  the person received it. A message never carries a title, a name, a narrative or a token.
- **A person can turn off mail about assigned actions** on their profile. The page says what is always sent.

**Rules that hold.**

- **Nothing is called sent that was not accepted.** Statuses are `provider_accepted`, `logged_only`, `suppressed` and `failed`;
  `ok` is true for the first only. A console fallback, a missing credential and an address that is not an address are never
  "sent". A reminder is marked sent only on acceptance, and one that was only logged stays due and says so.
- **One message per action, person and threshold.** The outbox key is organization, source record, recipient, channel,
  purpose and threshold, so a retried event, a second run of a job or two jobs that overlap ask for the same message and get
  the one that exists. A corrected due date is a new threshold and is told again. A job that failed halfway is safe to run again.
- **The recipient and the work are checked when the message is sent, not when it was asked for.** A person who left, has no
  valid address, belongs to another organization, may not open the record, has turned action mail off, or no longer owns the
  work is suppressed with the reason. A critical message (breach and request deadlines) is not turned off by a preference
  and may pass the daily cap; its first failure tells the organization's administrators in the app at once, not after the
  retries.
- **A worker that dies does not lose a message.** A row a worker leased and never finished is sent again when its lease has
  run out, and no database transaction is held open while the provider is called.
- **A request never waits on mail.** The in-app notice and the source action are committed first; asking for the email is
  best effort after that and can never undo them.
- **Safe headers, verified TLS, no template from a caller.** Line breaks are removed from the recipient and subject, an
  address must be one plain address, an error is stored as its class and code only (never the recipient or the server's
  words), STARTTLS verifies the server, the From is the authenticated mailbox for Gmail, and the link is built from
  `APP_URL` only when it is an HTTPS origin and a route the template allows. Without an origin the message has no link and
  says where to look.
- **Every scheduled mail job visits each organization in turn** (`for_each_tenant`, as not a super administrator), and a
  platform operator is not part of an organization's staff for the people a job addresses.

**Schema (additive).** One table, `email_outbox` (unique `dedupe_key`; it holds fields and a reference to the source, never
the text of a message); three columns on `email_reminders`: `delivery_status`, `delivery_error`, `attempts`. No existing row is
changed.

**Found on the way.**

- **No GRID mail was ever sent.** Every template raised `NameError` while rendering (`os` was never imported in
  `email_service.py`), so the reminders, expiry alerts, escalations, digest and finding mails failed before any send; the jobs
  catch and log. A second defect sat behind it: the escalation query joined every administrator of the database to every
  control, so a "manager" was any administrator of any organization.
- **The first user was the DPO.** `_get_dpo_email` fell back to the first active row of `users`. The breach "notified" flags
  were set after a helper that returns nothing, so a failed or console-only send was recorded as delivered, and the link in
  the message was `#`. The DSR mail named the data subject.
- **A reminder was marked sent when it was only logged**, and when it had no address. Its HTML was built from unescaped title
  and message, and a recurring one was rescheduled with a SQLite-only `datetime()` call.
- **The demo request mail never left**: `send_email(body_text=...)` was called on a function that did not take it.
- **Evidence expiry mail** interpolated the title and the owner's name unescaped and linked to the relative path `/evidence/`;
  the GRID vault job was written to mail the same people every day for thirty days.
- **STARTTLS did not verify the server**, a recipient with a line break could add a header, and the sender was the placeholder
  `noreply@example.com` whatever mailbox authenticated.
- **The scheduled jobs did not bind a tenant.** By the contract written in `database.list_active_tenants`, a connection with
  no tenant bound stays on the public schema, so on PostgreSQL the GRID, Sentinel, Evidence and reminder jobs would have seen
  none of an organization's rows. They now run once per organization. This is read from the code; it was not observed on the
  deployed installation.
- **The organization administrator role key is `org_admin`**; older role lists in the jobs used `admin` and `super_admin`
  only, so an organization administrator was never told. The new paths use `ADMIN_ROLES`.

**Checks.** Backend: `test_email_transport.py` (12, a fake SMTP server), `test_email_templates.py` (9),
`test_email_outbox.py` (13), `test_email_producers.py` (26: the GRID jobs, vault expiry through both jobs, the finding and
task assignment, the Sentinel jobs, the reminders, the administration routes, the people a job addresses, the failure
report, the preference, the demo request). Browser:
`tests/ui/test_admin_email_truthful_status.py` (2), `test_profile_email_preference.py` (2), and the existing Email Settings
files (error detail, reset, accessibility, zoom, viewports) and the audit share journey, all passed. No mailbox, credential,
DNS record or server schedule was touched, and no real message was sent.

**Not done (6).**

- **E3, urgent cases.** Sentinel breach and request deadlines now use the common contract, but the jurisdiction wording and
  the alternate human contact are not approved (owner decisions 3 and 7 in `09-email-inventory.md`): the message states the
  deadline the application recorded, and an administrator is told in the app when nobody is named. BCM incident mail was
  built afterwards for a named commander (follow-up 11, step 3); a BCM escalation clock and an alternate contact were not.
- **Management summaries across modules** were built afterwards as an opt in My Work summary (follow-up 11, step 2).
- **AI Governance review and decision mail** was built afterwards for a named reviewer or decider (follow-up 11, step 4).
  With nobody named it stays in the app only, as the plan requires.
- **Preferences beyond action mail** were built afterwards: a daily or weekly summary and quiet hours (follow-up 11, step 2).
  A tenant cannot override them (owner decision 4).
- **Bounces and replies.** The Reply-To comes from `SMTP_REPLY_TO`; no bounce or reply intake exists. SPF, DKIM and DMARC are
  a property of the real sending domain and were not checked.
- **Rate limits per minute and per account**, and retention (a purge) of old outbox rows: both were built afterwards
  (follow-up 13).
- **Task updates and bulk assignment** did not notify at all (no in-app notice existed there either), so they sent no mail:
  an edit that hands a task to someone, and a bulk assignment, now tell the new assignee (follow-up 13).
- **The audit share link** keeps its direct send (a recipient bound, signed in link). Its token expiry and revocation review
  is open; the creator now sees `email_status`.
- **E4, provider cutover**: no managed sender identity exists. Its seams (pause, comparison by provider, the runbook
  [12](12-email-cutover-runbook.md)) were built afterwards (follow-up 11, step 1). **A pilot** with named recipients on a real
  mailbox, a second mailbox provider and an inbox placement check has not happened.

### 2026-10-15, follow-up 11: the items the first build of plans 04 to 06 left

**Built, committed as `cbf9372` and pushed on the branch `claude/plan-04-platform-truth`.** After the first build the owner asked to deal with the five items it had
reported as not built. The plan and its running log are [11](11-follow-up-plan.md); the cutover runbook is
[12](12-email-cutover-runbook.md). New: `modules/launcher/summary_mail.py`, `modules/launcher/predictive_trace.py`,
`modules/ai_governance/assignment.py`. Changed: `core/email_outbox.py` (pause, comparison by provider, preferences, quiet
hours, the open checks for four more kinds), `core/email_templates.py` (`bcm.incident`, `bcm.exercise`, `summary.mywork`),
`core/auth.py` (`licensed_modules_for`), `core/events.py`, `core/predictive_risk.py`, `database.py` (three nullable columns,
one table), the BCM routes, data service, scheduler and page, the AI Governance service, decisions, handlers, routes and two
scripts, `my_work_service.py` with its route, template and script, the profile and Email Settings pages, `routes_dashboard.py`
with the Command Centre template, and `docs/generated/capability_inventory.*` (regenerated, 1099 routes).

**What a person gets.**

- **An administrator can pause the queue and compare providers** (Email Settings). Pause sending holds every message but a
  critical one; held messages stay queued and a hold is not an attempt; the page shows a notice while paused and the
  deliveries by provider for the last 30 days. The cutover runbook is [12](12-email-cutover-runbook.md). The cutover itself
  needs a managed sender identity that does not exist: nothing was switched.
- **A person can choose how much mail they get** (Profile). Action mail on or off; one by one or in a daily summary; a weekly
  summary; quiet hours with a UTC offset in 15 minute steps. Mail that is not critical waits for the end of quiet hours
  without using an attempt; critical mail ignores every choice. The My Work summary (`summary.mywork`) is opt in, is sent
  after 07:00 local time at most once a day or week and never for zero, and its counts are the ones the person sees on My Work.
- **A BCM incident can name its commander as a person**, from the organization's people who can open Business Continuity.
  The commander is told by a critical message when named or changed, and only while the incident is open and they are still
  its commander. The owner of a planned exercise is told once, 14 days out. The free text commander, plan owner and training
  owner stay labels and are not mailed.
- **A review request or a decision request can name who handles it.** Nobody named is as before: everyone in scope sees it in
  the app and nobody is mailed. A reviewer can name the reviewer of a request, and a reviewer or decider can name the decider
  of a decision request, from people who hold the capability, can open the use and are not its requester (nor, when
  separation is required, its owner). The person named is told in the app and by mail and sees it as theirs on My Work;
  everyone else sees it as waiting on that person. Naming someone else stops the earlier message.
- **A platform administrator can ask why the predictive number is what it is** (Command Centre, "Why this number?"). Each
  of the six signals shows its rule, its period, its weight, the figure it produced and the term it added, the records
  behind it that the viewer may open, with links, and a place to dispute the signal. A record the viewer may not open, or
  that no longer exists, is counted and not named. A dispute is a note beside the number: it edits nothing and does not change
  the prediction. A signal that lowers the score (a recent exercise) says so instead of showing a share of the score.
- **A person who heads a unit can see their team's work** (My Work, "My team's"): for each person, how many items are
  overdue, due soon, to act on and waiting on others, and the five oldest overdue items with links.

**Rules that hold.**

- **Only assigned work is charged to a person.** Evidence expiring, open incidents, statutory deadlines, evidence waiting for
  any reviewer and notifications are queues many people see; counting them against each person on a team would charge one
  item to everyone. An AI decision or request counts for a person only when it is named to them.
- **The team view never shows more than its viewer could see.** A team is the units the viewer heads that lie inside the
  viewer's own scope (heading a unit does not widen scope), and every item is read through the viewer's own scope after the
  person's. A title from a module the viewer may not open is counted and not named; a source the function does not know is
  not named.
- **The trace is frozen with the prediction**: record ids and weights, at most 25 per signal, and the count of all. It is
  not a live recount, so it says what the number was made from when it was made. A prediction made before this change
  carries no trace and says so.
- **Naming a person adds no rights.** The person named must already hold the capability and be able to open the use; the
  service checks it when naming and the sender checks it again when sending.
- **Nothing is called sent that was not accepted**, as before: every new template goes through the same outbox, preferences,
  suppression and status rules.

**Schema (additive).** `bcm_incidents.commander_user_id`, `ai_use_intake_requests.assigned_reviewer_id`,
`ai_use_decisions.assigned_decider_id` (nullable) and the table `ai_risk_prediction_notes`. Preferences are rows of
`user_preferences`. No existing row is changed; the telemetry of a new prediction gains a `trace` key.

**Found on the way.**

- **`body` is a rich text key.** The request layer keeps HTML tags in any field named `body`, so a dispute passed through
  with its markup; the note now strips tags where it is stored, and every viewer shows it as plain text.
- **The predictive share of a negative term is an absolute value**, so a recent exercise showed as a percentage of the score
  while lowering it. The trace labels it as lowering the score. The model also clips the sum at zero; the formula shown says so.
- **The module header says breaches are counted over 30 days; the query has no window.** The trace states the rule the code has.
- **My Work ran the title, source and basis of an item together on one line**, and its Load more button was never hidden (a
  `hidden` attribute loses to a `display` rule). Both fixed in the template.
- **The notification list could not be scrolled by keyboard once it held about seven rows** (it scrolls at 320 pixels; axe:
  `scrollable-region-focusable`). It appeared only in a long browser session, where an administrator had collected enough
  notices, and passed on an empty database. The list is now a focusable region with a name, and
  `tests/ui/test_notification_list_keyboard.py` fails without that. The rows are still not individually focusable: that is a
  larger change and is not done.
- **Amber badges are below the contrast minimum** (`.badge-high` and `.badge-progress`: `#d97706` on `#fffbeb`, 10 pixel
  bold, 3.07 to 1 against 4.5 to 1). The axe check of `/erm/register` failed after earlier tests had put such a badge on
  the register and passes on an empty one, so it depends on the order and the data. **Not fixed**: the colours come from the
  shell palette and changing them is a design decision for every page; recorded here instead.

**Checks.** Backend: `test_email_outbox.py` (18), `test_email_producers.py` (36), `test_email_templates.py` (9),
`test_email_transport.py` (12), `test_ai_governance_assignment.py` (13), `test_predictive_trace.py` (19),
`test_my_work_team.py` (12), and the My Work service and views files. Browser: `test_profile_email_preference.py` (3),
`test_bcm_incident_commander_ui.py` (1), `test_ai_governance_assignment_ui.py` (2), `test_admin_email_truthful_status.py` (2),
`test_predictive_trace_ui.py` (3), `test_my_work_team_ui.py` (3), `test_notification_list_keyboard.py` (1). PostgreSQL: the outbox and jobs case, and one for the trace
and the team view. Full lanes: see the stage table below. No mailbox, credential, DNS record or schedule was touched and no
real message was sent.

**Not done (follow-up 11).**

- **E4, the cutover itself**: it needs a managed sender identity (a domain with SPF, DKIM and DMARC, and an account). Nothing in
  the repository can create one. A pilot with a real mailbox and an inbox placement check has not happened.
- **A BCM escalation clock and an alternate human contact** were built afterwards (follow-up 12). Jurisdiction wording for
  Sentinel and its alternate contact are still open (owner decisions 3 and 7). Plan owner and training owner are free text
  and stay unmailed.
- **A tenant cannot override** the preferences, quiet hours or sender identity (owner decision 4); there is no bounce or
  reply intake. (The purge of old outbox rows and a per minute limit were built afterwards: follow-up 13.)
- **A named reviewer or decider is not asked to accept and is not chased.** Nothing nudges a person who has been named and
  does nothing; the item follows its own due dates and shows as overdue on their My Work and in the team view.
- **The team view** reads 25 people a request (a unit can be chosen for a larger team), is based on the unit head (the schema
  has no manager of a person), has no grouping by vendor or process and no trend.
- **The trace** keeps 25 records a signal. A dispute is a note: it cannot be answered, closed or resolved and it notifies
  nobody. Predictions made before the change are not back-filled.

**Decisions taken (owner, 2026-10-15) and why.** The owner was shown the defaults this follow-up used and the two things
code cannot do, and answered: "Go with your recommendations but explain them in the ledger". Each decision below is
therefore adopted, not a default still waiting for an answer. The reasons are written down so that a later owner can change
one on purpose. It is a confirmation of product defaults in chat; it is not a sign-off of a phase (see
[10](10-completion-record.md)).

1. **A team is the active people of the units a person heads, and of the units below them.**
   - *Why.* The schema records one fact about who leads whom: `business_units.head_user_id`. A person has no "reports to".
     Using the unit head needs no new schema, no data entry and no screen, and it follows the same unit tree that already
     decides what every person may see, so the team and the scope cannot drift apart.
   - *Cost.* A matrix organization is not described: someone who reports to a person outside their own unit is not on that
     person's team. A unit with no head gives nobody a team view.
   - *Change it by.* Adding a "reports to" field and reading it in `team_units` (one function). Nothing else depends on how a
     team is found.
2. **Heading a unit does not widen what the head may see**: a team is the units a person heads that already lie inside their
   own scope.
   - *Why.* Naming a head is an edit of the unit (`governance.entities.manage`: platform administrator, GRC officer,
     compliance manager, risk owner, organization administrator), and nothing checks that the named person belongs to the
     unit. If heading granted reach, anyone who may edit a unit could appoint themselves head of another and read what its
     people are late on. The head stays a label; scope stays what the unit tree and the role say.
   - *Cost.* A head who is not placed in the unit, or in a unit above it, sees no team until they are, and the page does not
     say why: it simply does not offer the view.
   - *Change it by.* Not without deciding who may name heads: the alternative is a higher capability for naming a head and
     only then letting it widen scope.
3. **Only work assigned to a person is counted against them.**
   - *Why.* Much of My Work is a shared queue that everyone with a capability sees: evidence expiring, open incidents,
     statutory privacy deadlines, evidence waiting for any reviewer, and any AI request or decision nobody is named for.
     Counted per person, five people who may decide three pending decisions would show fifteen items, and one statutory
     deadline would read as five people's lateness. A manager asks who is late on what they own; assigned work answers that.
   - *What counts.* Tasks assigned to or created by the person, workflow decisions assigned to them, policy approvals, GRID
     findings they are assigned or lead, ERM reviews they own or review, ORM events they own, change reviews, and AI items
     that are theirs by name (a named reviewer or decider, a literacy course, a condition, a returned request).
   - *Cost.* A shared item that is overdue with nobody named is on nobody's line in the team view. That is the reason naming
     was built (decision 7): name someone for anything that matters. An "unassigned queue" row is the natural addition and
     is not built.
   - *Change it by.* Moving a source in or out of `_ASSIGNED_SOURCES` and `_ASSIGNED_AI` in `my_work_service.py`.
4. **Summaries are opt in, per person.**
   - *Why.* Whether a person wants a digest, and how often, is theirs to say; nothing arrives that they did not ask for,
     which is the plan's rule for role scoped mail. It is opt in rather than on because the sender is still a temporary
     account with a daily cap and no managed domain: switching on a new stream for everyone on the day of deployment would
     spend that cap, and the sender's reputation, before the pilot has measured anything.
   - *Cost.* Adoption depends on people finding the switch on their profile; nobody is reminded.
   - *Change it by.* Defaulting `email.weekly` or `email.mode` on for a tenant is a small change once the sender is managed.
5. **Quiet hours use a fixed UTC offset in 15 minute steps, not a named time zone.**
   - *Why.* A named zone needs a time zone database and daylight saving rules in every worker and every test, and the region
     the pilot runs in (UTC+2 all year in Zimbabwe) has no daylight saving, so a fixed offset is exact there. Critical mail
     (breach and request deadlines, an incident commander) ignores quiet hours and every preference, so a late hour never
     holds back a statutory message.
   - *Cost.* A person in a zone with daylight saving must change their offset twice a year.
   - *Change it by.* Replacing `local_now` and `quiet_until` in `core/email_outbox.py`; a named zone is the only thing that
     would change in what is stored.
6. **Preferences and quiet hours are platform wide; a tenant cannot override them** (owner decision 4 in
   [09](09-email-inventory.md)).
   - *Why.* An override needs an administrator screen, a rule for which wins between the tenant and the person, and per
     tenant storage. There is one pilot tenant and the sender identity is the platform's anyway; building precedence rules
     before a second tenant asks for them would be guessing.
   - *Cost.* A tenant administrator cannot force a digest on, or switch one off, for their people.
   - *Change it by.* Deciding the precedence first (the person over the tenant is the usual), then adding a tenant row
     beside the person's in the `user_preferences` lookup.
7. **Naming a reviewer or a decider is optional; nobody named is the earlier behaviour.**
   - *Why.* The plan forbids mailing every person who might decide, and the data model had no named person. Optional naming
     puts a specific person on the hook, and mails only them, without changing how any existing request is triaged. The
     person named must already hold the capability, be able to open the use and not be its requester (nor its owner when
     separation is required), so naming adds no right.
   - *Cost.* An unnamed request still reaches nobody by mail, and a named person who does nothing is not chased.
   - *Change it by.* Making naming required would need a default assignee rule per unit. Not recommended before the pilot has
     shown how requests are really triaged.
8. **An incident commander is a named user; the free text commander stays as a label.**
   - *Why.* Mail needs an identity, and free text cannot safely be resolved to a person. Keeping the label loses nothing that
     was typed. A commander is mailed as critical because an incident is time bound.
   - *Cost.* Older incidents have only the label and are never mailed.
9. **A prediction's trace is frozen with it, and a dispute is a note.**
   - *Why.* A reviewer must be able to reproduce why the number was what it was when it was made; a live recount could
     differ from the number it is meant to explain. A dispute records disagreement without letting anyone edit a model
     output or a source record from the panel.
   - *Cost.* Up to 25 record ids a signal are stored with each prediction; earlier predictions have no trace.

**Recommendations for what code cannot do (owner action; nothing built).**

- **The provider cutover (E4).** Recommended order: create a sending subdomain you control; publish SPF and DKIM and start
  DMARC at `p=none`, moving to `quarantine` after a few weeks of clean reports; send as a service identity (a shared mailbox
  or an API key), never as a person's mailbox; use Microsoft Graph if the organization already runs Microsoft 365, otherwise
  SendGrid or an SMTP relay; run a pilot with named recipients and an inbox placement check; then follow
  [12](12-email-cutover-runbook.md), keeping the temporary account as a fallback for a week or two. The application side is
  ready: pause, test message, comparison by provider and the runbook.
- **A BCM escalation clock and an alternate contact.** The application needs two facts only the owner has: how long a
  commander has to acknowledge an incident, by severity, and who is next. Recommended starting point: acknowledgement
  windows of 15, 30 and 60 minutes for critical, high and medium incidents, and the BCM manager as the first alternate. The
  build is then: record the acknowledgement on the incident, escalate once by mail and in the app when the window ends, and
  show the state on the incident. **Adopted by the owner ("go for it") and built as follow-up 12.** The privacy deadline
  clock stays a separate legal decision (owner decisions 3 and 7).

### 2026-10-15, follow-up 12: BCM incident acknowledgement and escalation

**Built, committed as `7425111` and pushed on the branch `claude/plan-04-platform-truth`.** The owner answered "go for it" to the recommendation in "Decisions taken"
(15, 30 and 60 minute windows, the BCM manager as the first alternate). The plan and its log are
[13](13-bcm-incident-escalation.md). New: `modules/bcm/escalation.py`. Changed: `core/email_templates.py`
(`bcm.escalation`; `bcm.incident` is version 2 and says how long the commander has), `core/email_outbox.py` (a send-time
check), `core/event_handlers.py` (the incident a confirmed breach opens now starts a clock), `database.py` (four nullable
columns on `bcm_incidents`), `modules/bcm/data_service.py`, `routes.py`, `scheduler.py` and the BCM page, and
`docs/generated/capability_inventory.*` (regenerated, 1100 routes).

**What a person gets.**

- **A commander has a window.** 15 minutes for a critical incident, 30 for high, 60 for medium; low has none. The
  commander's message says how long they have.
- **The incident shows where the clock stands** (list and console): awaiting, overdue, escalated or acknowledged, and who
  acknowledged and when. The named commander or a BCM manager acknowledges with a button. A person who declares an incident
  and names themselves commander has acknowledged by doing so.
- **When the window ends with no acknowledgement**, the BCM managers who can open the incident are told once: in the app and by
  a critical email (a reference and a link, never a title). When none can open it, the organization's super administrators
  who can are told. When nobody can, the administrators are told in the app, without the reference, that nobody who can
  open the incident could be told, so the gap is a configuration to fix and not a silent one. The timeline of the incident
  records the escalation and the acknowledgement.

**Rules that hold** (the reasons are in [13](13-bcm-incident-escalation.md)).

- **The clock restarts** when the commander changes or the incident is reopened, and **shortens** when the severity is
  raised; lowering the severity never lengthens it. It stops at acknowledgement, resolution or closure.
- **Once.** One escalation per clock, claimed by one conditional update, with the notices and the email requests written in the
  same transaction: two workers, or a worker that dies, cannot send it twice or lose it.
- **Nobody is told about an incident they cannot open**: the module's own unit rule decides, checked when the alternates are
  chosen and again when the email is sent.
- **Incidents declared before this change have no clock** and are never escalated.

**Schema (additive).** `bcm_incidents.ack_due_at`, `acknowledged_at`, `acknowledged_by`, `escalated_at`, all nullable.

**Found on the way.**

- **The incident a confirmed Sentinel breach opens had no commander, no owner and no one asked to take it**, and carried the
  tier names `major` and `significant`, which the BCM page does not offer. It now starts the same clock (the windows read
  those two as high and medium), so a breach that becomes an incident cannot sit unacknowledged without the BCM managers
  being told. The tier names themselves are not changed.
- **A race in the profile quiet hours editor** (written in follow-up 11, found by this lane). Saving anything else, the time
  zone for one, answered with the saved state and drew it over quiet hours the person had ticked and typed but not saved: the
  box came unticked, the times reset and Save was disabled, depending on which answer came first. The page now keeps a
  draft until it is saved or switched off; `test_changing_the_time_zone_does_not_undo_quiet_hours_that_are_not_saved_yet`
  fails without the change (checked).
- **The profile page's active sessions list can never load.** It selects `sessions.last_active`, which the table does not
  have; the error is swallowed, so the list is always empty. Not caused by this work and not fixed here: a separate task was
  raised for it.

**Checks.** Backend: `test_bcm_escalation.py` (21: the windows, the clock on declare, restart, raise and reopen, the job and
its single claim, who is told and who is not, the fallbacks, the send-time check, the commander's message, the route and its
scope, the breach incident), and the changed `test_email_producers.py` and `test_email_templates.py`. Browser:
`test_bcm_incident_escalation_ui.py` (4, including an axe check of the new markup). PostgreSQL: one case (the columns in a tenant
schema, the claim and the notices from that schema). The full lanes are in the stage table below.

**Not done (follow-up 12).**

- **One level only.** If the BCM manager does not act, nothing nudges them or tells anyone else: no second alternate, no
  repeat.
- **The windows are constants** (`WINDOWS` in `modules/bcm/escalation.py`), not set per organization or per incident type.
- **An alternate with no unit sees only organization wide incidents** (the module's own rule), so a BCM manager who is not
  placed in the incident's unit, or above it, is not told. The administrators are told that nobody could be; placing the
  manager is the fix, and it is not made for them.
- **Acknowledgement is a click.** A status change, a timeline post or an action does not count as one, and My Work does not
  show the commander a due time for it.
- **The privacy deadline clock and its alternate contact** are separate legal decisions (owner decisions 3 and 7) and are not
  part of this.

### 2026-10-15, follow-up 13: the hardening pack

**Built, committed and pushed on the branch `claude/plan-04-platform-truth` (`ecccbad`, with its verification record in the commit after it).** The owner answered "do this" to the recommendation made after follow-up 12:
the three open items of plan 06 that code can close, and the badge contrast finding. Plan and log:
[14](14-hardening-pack.md). Changed: `core/email_outbox.py`, `core/email_templates.py` (`tasks.assigned`),
`modules/launcher/task_service.py`, `routes_platform.py`, `templates/base_shell.html`, and the tests.

**What a person gets.**

- **Old delivery records are removed.** A delivery that ended (accepted, suppressed, failed for good or logged only) more than
  180 days ago is deleted, once a day per organization. A delivery that is waiting, retrying or leased is never touched.
- **Ordinary mail is paced.** At most 20 messages other than critical go to the provider in a minute, across every
  organization, since they leave through one account. Critical mail is not counted and is never held; a suppression, which
  is a local decision, is not counted either. What is left over waits for the next minute.
- **A task handed to someone tells them.** Editing a task so that it belongs to someone else, or assigning a group of tasks,
  tells the new assignee in the app and by email. One task is told as a task is when it is created; a group is one message,
  "N tasks are assigned to you". The person who made the change is not told, and a task given away and given again is told
  again.
- **Badge text is readable.** The 10 pixel bold badges (high, in progress, low, complete, critical, overdue) used the fill
  tints as text colours and measured about 3:1. They use a darker text token in the light theme and the same colours as before
  in the dark theme.

**Decisions taken (owner, 2026-10-15: "do this") and why.**

1. **Retention of 180 days.** The rows are a recipient, a reference and a status, not a message, so they are small, and after a
   few weeks they answer only "was this sent". The cost is that the deduplication key goes with the row: an action still open
   after 180 days and asked for again is told once more, which is a reminder and not a defect. A shorter window repeats
   reminders sooner; a longer one keeps delivery history for no use. The number is `RETENTION_DAYS`. Owner question 5 in
   [09](09-email-inventory.md) (retention and processor terms) is still the owner's to confirm.
2. **20 a minute.** The temporary account has a daily cap of 200; 20 a minute drains it in ten minutes and keeps a burst
   (a bulk assignment, a deadline run) below what a consumer mailbox provider treats as a flood. The number is `PER_MINUTE`.
   The initial implementation served organizations in id order, allowing the first organization's backlog to consume the
   whole allowance every minute. The later fairness correction gives each organization a first share, redistributes unused
   capacity, and rotates the starting organization when there are more tenants than available sends. This unverified
   working-tree correction is tracked in `PLAN_email_queue_fairness_and_ai_literacy_navigation_2026-10-15.md`.
3. **One message for a group of tasks.** The daily cap and the person's inbox are both shared; forty messages for forty tasks
   would spend the first and bury the second.
4. **Green and red were fixed with amber.** The probe that found the amber measured the green tints at 3.14 to 1 and the red
   at 4.41 to 1; leaving them would have left the same finding on the next page that shows a row. Fills, icons and borders
   are unchanged.

**Rules that hold.**

- **Nothing that is waiting is purged**, however old, and a purge never touches the in-app notice or the work.
- **A hand over is told only when it happened**: the assignee changed, to someone other than the person doing it, and the task
  is still theirs to be told about at sending (the outbox checks that again).
- **The email carries no title**, as every message: a kind, a reference and a link, or a count and a link.

**Found on the way.**

- **`deliver_all_tenants` had no limit across organizations**, only 50 examined per organization per pass, so many
  organizations could each send 50 a minute through the same account. They now share one budget.

**Checks.** Backend: `test_email_outbox.py` (5 added: the budget, a suppression not spending it, one budget for the passes of
a minute, the purge, the once a day run), `test_task_assignment_mail.py` (7), `test_email_templates.py` (the new template).
Browser: `tests/ui/test_badge_contrast.py` (seeds one row of each badge in the BCM incident list and the ERM register and asks
axe about both themes; it fails on the earlier colours and passes now). PostgreSQL: one case (the purge, the budget and the
hand over from a tenant schema). The full lanes are in the stage table below.

**Not done (follow-up 13).**

- **The retention and the send limit are constants**, not settings an administrator can change.
- **Only an assignment notifies.** A status change, a drag between columns and a delete tell nobody; a bulk change of status
  or priority tells nobody.
- **Other badge definitions are not touched.** The Governance page defines its own `.badge-high` (orange on a tint) and
  `.badge-med`, and inline colours elsewhere; only the shell's six classes were fixed.
- **The notification rows are still not individually focusable** (the list itself takes focus).

## Stage verification (end of plan 02, 2026-10-14)

| Lane | Result |
| --- | --- |
| Full backend, SQLite (`pytest --ignore=tests/ui`) | 2319 passed, 69 skipped (the real-PostgreSQL tests, which skip without the throwaway database), 37 minutes |
| Real PostgreSQL 18 (`tests/test_postgres_init.py`, container `themisiq-pg-aigov`) | 69 of 69 passed after the fix above; includes the Forms import, review desk, response, Vault proof, library, inspector and Find evidence |
| Focused browser files (AI Governance 72, Vault 27 plus 2C) | passed |
| Full browser suite (`tests/ui`) | not completed as one run: it takes about 3.8 hours and was stopped. The 14 files before the review desk ran in lane order twice, with one real defect found and fixed (see 3, Found on the way); the browser run after plan 03 is in the table below |
| Capability inventory | regenerated, 1070 routes |

## Stage verification (end of plan 03, 2026-10-14)

| Lane | Result |
| --- | --- |
| Full backend, SQLite (`pytest --ignore=tests/ui`) | 2386 passed, 70 skipped (the real-PostgreSQL tests, which skip without the throwaway database), 35 minutes. Run before the last follow-ups below |
| Backend after the follow-ups (the 12 files they touch: signals, clock, approvals, My Work, proof, AI decisions, service, packs, event handlers, templates, duplicate routes) | 221 passed; then 95 passed again after the last change (a change nothing is connected to is not recorded): signals, approvals, proof, AI decisions, My Work |
| Real PostgreSQL 18 (`tests/test_postgres_init.py`) | 70 of 70 passed, 7 minutes |
| Browser files touched by plan 03 and the queue fix (connected view, Vault library, My Work, Governance, the Vault files, zoom, action surface, connectors and all 11 AI Governance files) | 148 passed and 2 skipped, 9 failed and 1 teardown error in a 2 hour 40 minute run during which the machine was suspended (every failure is a network suspended or access denied error or a timeout in the same few minutes: connectors, one action surface page, three AI Governance tests); the same 9 tests passed when run again straight away, so none is a defect. The review desk file, which carried the queue race, passed in lane order |
| Capability inventory | regenerated, 1075 routes (`--check` passes) |

Not run: the full browser suite in one session, and a specialist walkthrough with pilot data (plan 05 section 10).

## Stage verification (end of plan 04, 2026-10-15)

| Lane | Result |
| --- | --- |
| Full backend, SQLite (`pytest --ignore=tests/ui`), after slices 4A to 4G and before plan 06 | 2481 passed, 70 skipped (the real-PostgreSQL tests, which skip without the throwaway database), 30 minutes |
| Focused browser files of plan 04 (reports and search, Command Centre first screen, My Work) | passed, in the browser lane of the next table |
| Capability inventory | regenerated after 4G, 1084 routes (`--check` passes) |

## Stage verification (end of plan 06, 2026-10-15)

| Lane | Result |
| --- | --- |
| New and neighbouring backend files (transport 12, templates 9, outbox 13, producers 26; the guard files for silent swallows and security, diagnostics, Sentinel clock and write scope, GRID isolation) | 60 passed in the email files; 244 passed in the guard and neighbouring files |
| Full backend, SQLite, after plan 06 | 2542 passed, 71 skipped (the real-PostgreSQL tests, which skip without the throwaway database), 48 minutes. An earlier attempt on the same code stood still at 46 per cent for an hour and a half while the machine was asleep; it was killed, and the rerun with a hang dump armed finished with nothing stuck |
| Real PostgreSQL 18 (`tests/test_postgres_init.py`, container `themisiq-pg-aigov`) | 71 of 71 passed, 7 minutes; includes the new case that asks for a finding deadline message inside a tenant, sends it from that schema and checks it was asked for once and delivered once |
| Browser files touched by plan 06 (Email Settings error detail, reset, accessibility at zoom and viewports, the truthful status page, the audit share journey, the profile preference) | 11 passed |
| Browser files touched by plans 04 and 06 together (42 files: Command Centre, first screen, reports and search, My Work, analytics, BCM, Sentinel and ERM pages, the topbar, Email Settings and the profile, GRID findings and the audit share, the connected view, org isolation, CSRF, and the accessibility, 200 per cent zoom and desktop viewport files with the three new routes added: `/metrics`, `/my-work`, `/profile`) | 370 passed, 1 skipped, 18 minutes |
| Capability inventory | regenerated, 1090 routes (`--check` passes) |

Not run: the full browser suite in one session (about 3.8 hours), a specialist walkthrough with pilot data, and any send
through a real mailbox.

## Stage verification (follow-up 11, 2026-10-15)

| Lane | Result |
| --- | --- |
| Focused backend files (outbox 18, producers 36, templates 9, transport 12, assignment 13, trace 19, team 12, My Work service and views) | passed |
| Full backend, SQLite (`pytest --ignore=tests/ui`), after follow-up 11 | 2599 passed, 1 failed, 72 skipped (the real-PostgreSQL tests, which skip without the throwaway database), 51 minutes. The one failure was the hand written list in `test_email_templates.py`, which did not yet name the two new BCM templates; it was corrected and that file passes (9 of 9). The whole suite was **not** run again |
| Real PostgreSQL 18 (`tests/test_postgres_init.py`, container `themisiq-pg-aigov`) | 72 of 72 passed, 7 minutes; includes the new case for the trace and the team view inside a tenant schema. The container was removed afterwards |
| Browser, 36 files touched by follow-up 11 (the 11 AI Governance files, BCM, Command Centre, My Work, profile and Email Settings, the accessibility, zoom and viewport files, CSRF, organization isolation, modal and dialog, reports and search, the connected view, the shell) | 253 passed, 14 failed, 1 teardown error, 2 hours 7 minutes. The machine was suspended for about an hour and a half in the middle: 12 of the failures and the teardown error are `ERR_NETWORK_IO_SUSPENDED`, `ERR_NETWORK_ACCESS_DENIED` or a 30 second navigation timeout. The other two were real axe findings that depend on data and order (see Found on the way) |
| The 14 failures run again, with the new accessibility checks (whole guidance file, all 23 acceptance routes for axe, the team view and trace files) | 42 passed, 5 minutes |
| After the notification list change: the new keyboard test, the shell and theme files | 66 passed, 6 minutes; the keyboard test fails without the change (checked) |
| After the same change, the shell wide files (axe on 23 routes, 200 per cent zoom, desktop viewports, dialog focus, modal contract, My Work, first screen) | 116 passed, 8 minutes |
| Capability inventory | regenerated, 1099 routes (`--check` passes) |

Not run: the whole browser suite in one session (about 3.8 hours); the 36 file subset again in one piece after the last
template change (the change is one set of attributes on the notification list in the shell, every page that extends the shell
carries it, and a representative set of pages, the accessibility, zoom and viewport files, was run again, not every file); the
full backend suite after the one test correction; a specialist walkthrough on pilot data; and any send through a real mailbox.

## Stage verification (follow-up 12, 2026-10-15)

| Lane | Result |
| --- | --- |
| Focused backend (`test_bcm_escalation.py` 21, the email producer, template and outbox files) | passed |
| Full backend, SQLite (`pytest --ignore=tests/ui`) | 2621 passed, 73 skipped (the real-PostgreSQL tests, which skip without the throwaway database), 0 failed, 1 hour 7 minutes |
| Real PostgreSQL 18 (`tests/test_postgres_init.py`, container `themisiq-pg-aigov`) | 72 of 73 passed in the lane, 6 minutes. The new BCM case failed on its own last line: it expected a timeline note that only the acknowledge route writes, and the test called the data function. The assertion was corrected and the case passes (5 seconds); the product code was right. The container was removed afterwards |
| Browser, 15 files (the four BCM files, axe on 23 routes, 200 per cent zoom, desktop viewports, modal and dialog, the notification list, Email Settings and the profile preference, CSRF, organization isolation, action contracts) | 167 passed, 1 skipped, 2 failed, 8 minutes. One failure is the known amber badge contrast on `/erm/register`, which appears once earlier tests have put such a badge on the register (see follow-up 11); the other was a real race in the profile quiet hours editor, fixed (see Found on the way) |
| The profile file after that fix | 4 passed; the new regression test fails on the earlier page (checked) |
| Capability inventory | regenerated, 1100 routes (`--check` passes) |

Not run: the 15 browser files again in one piece after the profile fix (the profile file was run again, and the change is
inside that page's script), the PostgreSQL lane again after the one corrected assertion (that case was run on its own), the
whole browser suite in one session, a walkthrough on pilot data, and any send through a real mailbox.

## Stage verification (follow-up 13, 2026-10-15)

| Lane | Result |
| --- | --- |
| Focused backend (`test_email_outbox.py` 23, `test_task_assignment_mail.py` 7, templates, producers) | 75 passed |
| Full backend, SQLite (`pytest --ignore=tests/ui`) | 2633 passed, 74 skipped (the real-PostgreSQL tests, which skip without the throwaway database), 0 failed, 32 minutes |
| Real PostgreSQL 18 (`tests/test_postgres_init.py`, container `themisiq-pg-aigov`) | 73 of 74 passed in the lane, 6 minutes. The new case failed on its own setup: it queued messages for a task that was still assigned to someone else, which the outbox correctly suppressed when sending. The data was corrected and the case passes (5 seconds); the product code was right. The container was removed afterwards |
| Browser, 43 files (the shell and its accessibility, zoom, viewport, dialog and modal files, the premium theme, BCM, ERM, task board, My Work, the Command Centre, profile and Email Settings, reports and search, CSRF, isolation, action contracts, the 11 AI Governance files, and the new badge and notification list tests) | 350 passed, 1 skipped, 0 failed, 22 minutes. The amber badge finding on `/erm/register` did not recur |
| Capability inventory | unchanged: no route was added (1100) |

Not run: the whole browser suite in one session (about 3.8 hours), the PostgreSQL lane again after the one corrected case
(that case was run on its own), a walkthrough on pilot data, and any send through a real mailbox.

## Handoff (read this first)

1. Slices 1A, 1B, 1C (plan 01), 2A, 2B, 2C (plan 02) and 3A to 3D (plan 03) are built and verified as above. They were
   committed (`d20d202`, `e0e2c13`) and merged to `master` as pull request 10 (`a568b75`, 2026-10-14, merged by the owner on
   GitHub; this session's auto mode refuses to merge an unreviewed pull request, even with an allow rule). Deploying to the
   VPS is the owner's step. The Docker container `themisiq-pg-aigov` (127.0.0.1:55433, database `themisiq_test_aigov`; recipe
   in the memory file `reference_test_environment.md`) was the PostgreSQL lane. It was removed on 2026-10-15 after the last
   run (72 of 72, after follow-up 11); recreate it from that recipe for the next lane.
2. Plans 04, 05 and 06 and follow-up 11 are built on the branch `claude/plan-04-platform-truth` (cut from `master` at
   `a568b75`) and were committed (`cbf9372`, `083e661`, follow-up 12 as `7425111`, the profile fix `1a88208`) and pushed to
   `origin/claude/plan-04-platform-truth` on 2026-10-15 at the owner's request. Follow-up 13, the hardening pack
   ([14](14-hardening-pack.md)), is committed as `ecccbad`, its verification record as the commit after it, and both were pushed on 2026-10-15 at the owner's request. Plan 04 is slices 4A to 4G; plan 05 is documents only
   (`10-completion-record.md`); plan 06 is E0 to E2 and part of E3 (see Not done (4) and Not done (6)). Follow-up 11
   ([11](11-follow-up-plan.md)) added the E4 seams, BCM mail, a named AI reviewer and decider, summaries and quiet hours, the
   predictive trace and the manager's team view; its entry and stage table are above. Nothing in them is pilot live or
   generally released.
3. **Before this reaches a server**, the owner has three things to do that code cannot: set the mail secret in the service
   environment (`SMTP_PASS`, `APP_URL` as an HTTPS origin, and `SMTP_REPLY_TO` if replies are monitored) and then use
   Clear stored secrets on the Email Settings page, decide the seven questions in `09-email-inventory.md`, and run the
   PostgreSQL lane (`tests/test_postgres_init.py`) against the build that will be deployed. The new tables `email_outbox`
   and `report_run_notes` are declared with the platform tables, so `_migrate_all_tenant_schemas` creates them in every
   existing tenant schema on the first start (idempotent, additive).
4. Existing tests were changed for the new behaviour: `test_entity_scope.py`, `test_platform_ownership_surfaces.py`,
   `tests/ui/test_my_work_page.py`. The new files are listed in the
   slice table.
5. The owner resolved the ERM delegated-authority and canonical Vault artifact decisions on 2026-10-15; their unverified
   local slices are logged above. Legally approved jurisdiction content (Sentinel) remains open. Open decisions for plan 04:
   which role authors workflows, and whether the three chats and three board narratives are kept as labelled placeholders
   or refuse when the assistant is off. Open decisions for plan 06 are listed in `09-email-inventory.md`. The defaults of
   follow-up 11 were confirmed by the owner on 2026-10-15 (see "Decisions taken"). Still open for the owner: a managed sender
   identity, and the BCM acknowledgement windows and alternate contact (a starting point is written there, not built).
6. A specialist walkthrough on pilot data (Ali Moyo and Vivian Tsongorera) has not happened: nothing here has been seen by the
   people it is for. A mail pilot with a real mailbox has not happened either.
7. Nothing was deployed by this work. The branch was pushed on 2026-10-15 at the owner's request. What is left for the owner:
   open and merge the pull request on GitHub (this session's auto mode refuses to merge) and deploy to the VPS.
8. The browser lane depends on order and data. Two findings only appear after earlier tests have created records (the
   notification list and the badge text contrast, both fixed), and a machine that sleeps during a
   run produces a block of network errors that pass when run again. Run the files that failed on their own before reading
   a failure as a defect, and give a long run keep-awake.

## Connected module stage, 2026-10-16

This section updates the older 3E status and handoff. The working tree contains this stage and other local user edits. It has not been committed, pushed or deployed by this stage.

| Area | Local build | Focused evidence and remaining gate |
| --- | --- | --- |
| ERM risk acceptance | Owner proposal, independent Compliance Manager or Chief GRC Officer decision, dates and reason, history and My Work action | Three dedicated backend checks passed. Specialist pilot remains open |
| GRID and BCM files | New GRID uploads and replacements use one Vault byte store; BCM attaches one Vault artifact. Historical GRID current files and versions have idempotent crosswalks. BCM has a human-confirmed reference match. GRID file APIs hide internal storage paths | Canonical upload, migration, Vault scope, BCM service and one BCM review browser check passed. Existing files are not bulk-migrated. PostgreSQL check remains open |
| Module homes and connected navigation | Four source-backed overview cards on each specialist home, plus Related Items at GRID control, BCM incident and Sentinel breach record views | Three backend/HTTP checks and five Chromium module home checks passed. Wider specialist pilot remains open |
| Sentinel jurisdiction obligations | Versioned draft and DPO-approved cards, sourced trigger facts, separate obligations and change history. Existing simple clocks are indicative | Three new and nine existing focused clock checks plus one DPO draft browser check passed. Real legal rules have not been authored or approved |
| Earlier local slices | AI import mappings, My Work grouping, report traceability and scoped modules remain in this working tree | Focused backend checks passed. One stale My Work source-list assertion was corrected after the ERM acceptance source was added |

The final focused backend group passed 18 checks and seven focused Chromium checks passed. The real PostgreSQL lane is pending because the local Docker daemon is unavailable. Do not treat SQLite or browser checks as production migration proof. No full suite was run in this stage.

### Follow-up, 2026-10-18

- Added a guarded real-PostgreSQL upgrade regression for the GRID historical crosswalk and Sentinel obligation tables in an existing tenant. It is pending because the local Docker daemon is unavailable. Do not run it against production or any database outside the disposable test naming guard.
- Fixed canonical GRID upload atomicity: control status is projected before the Vault and GRID rows commit. A status failure rolls back both records and removes the newly written file. Failed replacement preserves the prior approved version.
- Replacing an approved GRID file now reopens a completed control for review. The focused canonical upload file passed five checks; the connected module backend group passed 22 checks. The live specialist pilot and PostgreSQL lane remain open. This follow-up is local and uncommitted.
- ARIA risk and document form edits now publish only material, structured field changes to confirmed linked records. Owner names, mitigation prose and document comments are not copied into signals. The two new regressions failed before the change and passed afterward; the focused change-signal file plus ARIA form tests passed 44 checks. Direct database edits, ARIA imports and bulk signal batching remain open.
- Evidence Vault local text-indexing build: a bounded parser process and per-version table index PDF, DOCX, XLSX, TXT, CSV and JSON; scoped library and Find evidence results show short source passages. The index is hash-bound and the scheduler uses a cross-worker lease and tenant rotation. See `PLAN_EVIDENCE_VAULT_TEXT_INDEX_2026-10-18.md`. Syntax and whitespace checks passed; automated tests and PostgreSQL migration verification were not run for this slice. Untrusted-file OS isolation remains a release gate.
- Follow-up: the AI Governance overview gained evaluation outcome and attention by tier views from its scoped Monitoring portfolio, with not-measured drilldowns and explicit partial coverage above 500 uses. Evidence Vault file path containment now uses exact resolved directory ancestry for downloads, preview, verification and permanent deletion. Automatic text extraction is disabled by default pending an operating-system sandbox for untrusted files. No automated or production checks were run for these local changes.
- Follow-up: the specialist Requests page gained a paginated lifecycle worklist with scoped counts for New, Needs clarification, In assessment, Awaiting decision, Ready to respond, Response sent and Closed. It derives the first six from existing intake, question, decision and response records. Closing is a separate, version-checked human action after a response was sent, or after a triage rejection was communicated externally with a recorded reference. The overview funnel now measures accepted requests whose response was sent and whose record was closed. Reviewers can open a permitted request; only an author can edit a manual draft. This local slice has syntax checks only; the new columns still need the real PostgreSQL migration lane.
- A governance reviewer may edit and submit an imported draft in their own organization and business-unit scope, even when another specialist imported it. Manually created staff drafts remain author-only. The actual specialist who submits is recorded as the event actor. This change has syntax review only.
- The overview now reads worklist counts without loading a page of request details. The request funnel's accepted, assessed, decided, responded and closed counts include a linked AI system only if that system is openable in the reviewer's scope. This local scope correction has syntax review only; PostgreSQL and role-based behavior remain unverified.
- External response reads and drafts now bind requester snapshots to an intake the specialist may review. The response panel asks which request it answers and keeps the selected request while switching AI system tabs; a shared AI system alone no longer authorizes reading another unit's requester snapshot. Each request gets its own response revision chain. Legacy unlinked responses with a requester snapshot are withheld until provenance is repaired. The bounded decision history now retrieves an older standing decision separately so a series of returned proposals cannot make it disappear. These are local changes with syntax review only; their migration and browser behavior remain unverified.
- Editing a draft preserves its stored business unit unless the specialist explicitly changes that field through the scoped choice. This prevents an imported request whose payload omitted the unit from silently becoming organization-wide on save. This is local and behavior-unverified.
- The Vault text indexer now requires Linux Bubblewrap as well as an explicit enable flag. Its child receives one frozen document and read-only interpreter and package mounts, no application data directory and no network namespace. The target VPS must have Bubblewrap and allow its namespaces; neither the sandbox nor document extraction has been exercised under the production service identity. Leave extraction disabled until that proof, the PostgreSQL migration check and scope verification are complete.

### AI decision brief slice, 2026-10-19

- Local build: an AI use profile can name an active sponsor in its organization; the outstanding-items view shows whether one is named. Existing profiles with no sponsor retain their original fingerprint until a covered fact changes. The sponsor column is additive in both schema declarations and the column migration.
- A proposed decision now stores a frozen brief of intended scope, owner and sponsor, checklist source references and versions, AI impact assessments, evaluation outcomes, Vault proof versions, review gaps and quality findings. The requester can include proposed conditions, expiry and review date. Approval refuses a proposal whose current source brief has changed. The signed record retains the proposed terms alongside the decider's actual conditions, rationale, expiry and review date.
- Specialist screens show the brief before a request, the proposed terms before a decision, and source versions in the review desk. Counts over the bounded assessment, evaluation and control reads produce explicit partial-history gaps instead of implying full coverage.
- This slice is local and uncommitted. Automated, PostgreSQL and browser verification and the specialist pilot have not been run for it. Other local changes in the working tree predate this slice and are not part of its release claim.
- Approval stays fail closed when the decider lacks access to sources captured by the requester. The reviewer screen distinguishes that access gap from changed facts. A DPO without ORM source access cannot approve a proposal that includes ORM proof; use a decider with that access or design a separately authorized review-pack grant before the pilot.

### Remaining connected and platform work, local build, 2026-10-19

This entry records local changes in a pre-existing dirty working tree. It does not claim that production rows were migrated, that a lawyer approved a jurisdiction rule, or that mail was sent. No automated tests were run for this slice.

| Area | Local implementation | Release or external gate |
| --- | --- | --- |
| Historical GRID and BCM files | Tenant-admin inventory and guarded per-record migration for GRID current files and historical versions. The source bytes remain on disk. An idempotent crosswalk records Vault artifact, source hash and legacy path. BCM reconciliation requires a human to select an existing accessible Vault artifact and retains BCM's review status. | Run an inventory in each live tenant, inspect every manual-review entry, back up files and database, migrate bounded groups, verify counts and hashes, then reconcile BCM references individually. No live rows were changed here. |
| Change signals | ARIA control status edits and a bounded bulk edit publish material control changes. Framework bulk creation, force-seeding and lazy seeding count actual inserts and publish a framework control-count signal for confirmed linked records. ARIA form edits and record change signals from the earlier slice remain. | Direct SQL changes are outside the event seam. Verify linked framework behavior and source scope in PostgreSQL before release. |
| Connected entry points | ARIA risk and document lists now open the scoped Connected Records page. Existing module drawers for GRID, BCM, Sentinel, ERM and ORM remain. | Specialist click-through and role review are pending. |
| Dashboard figure ownership | Metric definitions disclose whether the owner is an organization, an eligible business unit or mixed sources. The definitions remain the authority for scope and drilldown. | Confirm labels with data owners; validate all mixed-source figures in a specialist pilot. |
| Saved reports | Named, expiring, revocable shares recheck current modules, capabilities, row scope and frozen source IDs. A reviewer may have additional grants but must retain every source grant and the same scope. An independent capable reviewer signs or rejects an intact run with a reason. A tenant administrator may set a documented retention date or hold; the scheduler purges due content and keeps a hash tombstone. | Review the retention schedule and sign-off authority with the tenant, then verify PostgreSQL upgrade and role behavior before release. Existing saved runs without complete frozen scope cannot be shared. |
| Workflow and AI write decisions | Workflow and communication template authorship now needs a dedicated platform capability. AI control mappings await a different human reviewer; GRID AI scores are presented as suggestions for per-row selection; regulatory AI summaries need an explicit human decision before non-managers see them. | Verify role paths and source readers in the browser and PostgreSQL lane. Earlier AI-generated mappings remain historical accepted rows and need a separate provenance review. |
| Privacy escalation and legal content | Admin can nominate an active same-organization privacy specialist as alternate contact. Sentinel includes the person in deadline mail routing and scoped in-app alerts, which remain useful before mail is configured. Recipient lookups require the current organization; duplicate case alerts to a named recipient are suppressed. Case alerts require current case access and omit breach titles. Source review corrected two legacy figures and marks broad DSR and breach clocks as internal review targets. See [source review](15-jurisdiction-source-review.md). | No card is legally approved by this research. A privacy/legal reviewer must confirm each rule, trigger and effective date, and a different DPO must approve it in Sentinel. No live sender account is configured. |

The mail outbox and templates are ready for a controlled pilot only after the sender address, Reply-To owner, credentials, domain authentication and the runbook's delivery checks exist. Do not claim provider acceptance or deliverability from a queued row.
