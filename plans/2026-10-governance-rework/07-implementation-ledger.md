# 07. Implementation ledger

**Purpose.** Documents 01 to 06 are proposals. This file records what was actually built from them, how it was checked, what was
left, and what the next person needs to know. Started 2026-10-14 on the local branch `claude/pg-layer-scope-and-findings`,
fast-forwarded to `origin/master` (`f770d33`). The earlier AI Governance history stays in
[../ai-governance/05-execution-ledger.md](../ai-governance/05-execution-ledger.md) and is not rewritten here.

**Status words** (from [05](05-delivery-and-acceptance.md) section 12, kept separate on purpose): *planned*, *built* (in the
working tree), *verified locally* (focused checks named below passed on SQLite, and on a disposable PostgreSQL where stated),
*pilot live*, *generally released*. Nothing in this file is *pilot live* or *generally released*. Nothing here is committed,
pushed or deployed: the owner is asked at the end.

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
| 3E ERM acceptance, jurisdiction cards, GRID and BCM file convergence, module homes | 03 sections 3 to 9 | not built | see Not done (3) |
| 4 Platform truth, navigation and reports | 04 | planned | |

## Change log

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

**Navigation.** The sidebar is grouped as Work (Overview, Requests, AI systems, Reviews and decisions, Monitoring, Review packs)
and Also (impact assessments, regulatory changes, register an AI use, AI literacy history or My training). Platform AI
features left the customer sidebar and are linked from the Super Admin page. The review queue gained a "Waiting for information"
tab, and the Decisions page lists approvals with open conditions.

**Literacy consumer inventory (done before touching its navigation).** What reads the course tables today: the learner and
manager pages (`/ai-governance/literacy`), My Work (one item per assigned course), the owner literacy quality rule, the shell
icon for people with no AI Governance access, and the notification handler for a published course. Nothing was removed or
hidden from those. Only the sidebar entry changed: managers and reporters see "AI literacy history", staff see "My training",
so a learner is not stranded and a specialist does not see a learner workflow in the main path. The routes, APIs, completions
and history are untouched. The move to a separate staff-facing project is not built; see 01 section 8.

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

**Built, in the working tree, not committed.** `modules/evidence/proof.py` (new), `modules/evidence/routes.py`,
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

### 2026-10-14, 3A to 3D: change signals, the connected view and Sentinel's breach clock

**Built, in the working tree, not committed.** New: `modules/governance/change_signals.py`, `modules/governance/entity360.py`,
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

- **Governed risk acceptance in ERM** (section 7): the delegated-authority matrix is an owner decision and the work belongs to
  `ciso-assistant-features/04`. A control or a finding that changes now reaches the owner of the risk it is connected to;
  nothing records an acceptance, its expiry or its return to action.
- **Jurisdiction cards with a source, rule version, timezone and approver** (section 6): they need legal approved content.
  One breach still has one regulation and one clock, and the clock says it is indicative. Several obligations on one breach
  is not built.
- **One file identity for GRID and BCM** (sections 4 and 5): both still keep their own file stores. A new Vault version tells
  the claims that used the old one; a GRID or BCM file is not yet one Vault family.
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
- **The Related Items panel** (`static/js/related_items.js`) is loaded by the shell but mounted by no screen in this tree, so
  the connected view is reached from the AI system header, the Governance tables, My Work and the changes page, not from it.

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

## Handoff (read this first)

1. Slices 1A, 1B, 1C (plan 01), 2A, 2B, 2C (plan 02) and 3A to 3D (plan 03) are built in the working tree and verified as
   above. Nothing is committed or pushed; the owner is asked at the end. The Docker container `themisiq-pg-aigov`
   (127.0.0.1:55433, database `themisiq_test_aigov`; recipe in the memory file `reference_test_environment.md`) is the
   PostgreSQL lane; remove it when the programme ends (`docker rm -f themisiq-pg-aigov`).
2. Existing browser tests were changed for the new layout and the queue fix: `test_evidence_keyboard_accessibility.py`,
   `test_evidence_pagination.py`, `test_ai_governance_pages.py` (tab order, and the wait for the chosen request),
   `test_ai_governance_review_desk_ui.py`.
3. **This is where the standing instruction stops: plan 04 (platform truth, navigation and reports) is next and is not
   started.** Its section 2 lists the truth repairs that were deliberately left for it (the ARIA Generate Report toast, the
   BCM report types, the BCM and Sentinel example data, frozen saved report runs, the metric registry).
4. Open decisions that block the rest of plan 03: the delegated-authority matrix for risk acceptance (ERM), legally approved
   jurisdiction content (Sentinel), and whether GRID and BCM files should become Vault families.
5. A specialist walkthrough on pilot data (Ali Moyo and Vivian Tsongorera) has not happened: nothing here has been seen by the
   people it is for.
