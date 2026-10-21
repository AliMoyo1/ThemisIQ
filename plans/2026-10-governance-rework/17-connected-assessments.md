# 17. Connecting DPIAs, AIIAs and continuity plans to ARIA controls, without forcing it

Date: 2026-10-20. Status: assessment and plan for the owner, nothing built. Read on `master` (`790ce1c`).

## 1. Principle

A connection should save the person work at the moment they are already doing the task. So:

- **Derive, do not ask.** Work out likely controls from links that already exist (the processing activity, the system,
  the process, the evidence) instead of adding a new field to fill in.
- **Suggest, never record silently.** A guessed link is shown as a suggestion; it becomes a recorded link only when a
  person accepts it. Ignoring a suggestion costs nothing and never blocks saving.
- **Offer it where the work happens.** Inside the DPIA's mitigations step, the plan's page and the AIIA's mitigations
  step, not on a separate linking screen.
- **Give something back.** Each accepted control brings its status, effectiveness score and proof into the assessment,
  so the person writes less.
- **Respect scope.** Only controls the person may open are suggested; nothing hidden is named or counted.

The platform already supports this: `cross_module_links` has `provenance` and `status` (`candidate`, shown as
"suggested"; `confirmed`; `rejected`), and `modules/governance/relationships.py` creates a `system_candidate` as a
candidate and a manual link as confirmed.

## 2. Facts checked

- **The AIIA lives in Sentinel's tables** (`sentinel_aiia`, `sentinel_aiia_impacts`, `sentinel_aiia_dimensions`), and
  Sentinel's sidebar still has "AI Impact (AIIA)" under Assessments. The screens and service moved to AI Governance
  (`modules/ai_governance/assessments.py`); old Sentinel links redirect there.
- **No AI helps draft an AIIA, and none ever did.** There is no AIIA feature in `core/ai_policy.FEATURES`, and git history
  shows no AIIA function in Sentinel's `ai_service.py` before or after the move. What exists is a rule based prefill from
  the AI use's profile (`guidance.aiia_prefill`: title, purpose, deployment, autonomy, vendor, data categories, affected
  people), with its source shown. The DPIA, by contrast, has an AI full draft (`sentinel.ai_generate_full_dpia`), and BCM
  has AI plan drafting (`bcm.generate_plan`).
- **The live landing page lists AIIA as an AI drafted document** (Intelligence, Assisted authoring). That is not true
  today; fix the panel or build section 4.3 before launch.

## 3. Assessment of the three connections

| Connection | How it works today | Problem | Effect on the person |
| --- | --- | --- | --- |
| **DPIA to ARIA** | On `sentinel.dpia.completed`, `dpia_links_to_aria_controls` searches ARIA control names and descriptions for each of the first five data categories and links up to three matches each as "mitigates" (`core/event_handlers.py`) | Guessed links are created through `core/links.create_cross_module_link`, which sets no status, so they read as confirmed links a person made. Matching is by keyword ("personal" matches many controls), ignores business units, and happens after the DPIA is finished, so it does not help write it | Possible wrong links shown as fact; no help with the mitigations section |
| **BCP to ARIA** | On `bcm.plan.activated`, a task "CONTROL REVIEW: Verify controls for activated plan" goes to the compliance team | No link to any specific control; the task does not say which controls | Someone has to work out which controls matter, during an incident |
| **AIIA to ARIA** | Through the AI use: its checklist shows the AIIA, DPIA, RoPA, AIMS and the ARIA policy linked to the use. AI controls map to canonical controls, which show their proof (`modules/ai_governance/controls.py`) | The AIIA's own mitigations do not see those controls; no assisted draft | The assessor retypes mitigations that the control set already describes |

## 4. Plan

### 4.1 DPIA: suggested controls in the mitigations step

1. **Stop recording guesses as fact.** Change `dpia_links_to_aria_controls` to create its links through
   `relationships.create_link(..., provenance="system_candidate")` so they are candidates, shown as "suggested".
   Migrate the links it already made (`relationship='mitigates'`, created by that handler, status empty) to candidates;
   keep any a person has since confirmed. Respect the DPIA's business unit.
2. **Suggest from what is already linked, before keywords.** When the DPIA has a RoPA (`ropa_id`) or names systems, list
   the ARIA controls already confirmed against that RoPA, those systems and their data assets, and the controls that
   evidence on those records supports. Keyword matching stays only as a last resort, ranked lowest and labelled.
3. **Show them where the person writes mitigations.** A "Controls that may already cover this" box in the DPIA's
   mitigations step: each suggestion shows the control, its status, effectiveness score and whether proof is held.
   Accept (one click, becomes a confirmed "mitigates" link and inserts a short mitigation line the person can edit),
   or dismiss (recorded as rejected so it is not suggested again).
4. **Close the loop for free.** Control status changes already raise change signals; with confirmed links in place, the
   DPIA owner is asked to look again when a control it relies on stops working. No new mechanism.

Extra work for the person: none. Saved: retyping mitigations; finding the right controls.

### 4.2 Continuity plan: derived controls and a specific activation checklist

1. **Derive, do not store.** A plan already links to BIA records (`bcm_bia_plan_links`), which point to business
   processes (`business_process_id`). Show on the plan page a read only "Controls this plan depends on": the ARIA
   controls confirmed against those processes and their systems, plus BCM compliance controls already linked to ARIA.
   Nothing is stored; it is computed when the page opens, through the viewer's scope.
2. **Make activation specific.** When a plan is activated, the existing task lists those controls with their current
   status, each with "still working" or "not working". "Not working" raises the existing change signal on the control.
   When no controls can be derived, the task stays as today.
3. **One-time IMS help for BCM's own controls.** BCM compliance controls (ISO 22301 clauses) can be offered as candidate
   equivalents of ARIA's ISO 22301 controls through the existing IMS matching and second-person review, once, not per
   plan.

Extra work: none for plan owners; activation becomes a short checklist instead of an open question.

### 4.3 AIIA: assisted draft and suggested controls

1. **Assisted draft for the narrative parts.** Register a new AI feature (for example `ai_governance.draft_aiia`) that,
   from the prefill already computed, the linked DPIA and RoPA and the AI controls mapped for the use, drafts the
   impact descriptions and proposed mitigations. Declared in `core/ai_declarations.py` as `beside_record` or `person`
   (shown for review, never saved without the assessor), governed by the organisation's AI policy, fallback
   "unavailable" so the form still works by hand.
2. **Suggest controls in the mitigations step.** Offer the AI controls already mapped for this use, their canonical ARIA
   controls, and ISO 42001 controls in ARIA, with status and proof. Accept creates a confirmed link from the AIIA to the
   ARIA control; dismiss records a rejection.
3. **Bring the ARIA policy into view.** The AI policy linked to the use (already in the checklist) is shown read only in
   the AIIA, so the assessor can cite it without leaving the page.

Extra work: none; the assessor reviews a draft instead of starting blank.

## 5. What stays deliberately out

- No mandatory link fields, no "link at least one control" rule, no new screens.
- No automatic confirmed links from any rule or from the AI.
- No suggestion of a control the person cannot open.

## 6. Steps and tests

| Step | Work | Tests |
| --- | --- | --- |
| 1 | DPIA handler creates candidates, unit aware; migration of its old links to candidates | Service tests: candidate status, unit scope, confirmed links untouched; real PostgreSQL migration test |
| 2 | Suggestion service: derive controls for a DPIA, a plan, an AIIA from existing links, scoped | Service tests per source, hidden records never named, ranking |
| 3 | DPIA mitigations box: accept, dismiss | Route and browser tests, accessibility check |
| 4 | Plan page derived controls; activation checklist | Route and browser tests; activation with and without derived controls |
| 5 | AIIA assisted draft (new feature, declaration, policy, fallback) and suggested controls | AI feature registered and declared; policy refusal; unavailable fallback; browser test |
| 6 | Landing page: remove AIIA from the assisted drafting panel until step 5 ships | Visual check |
| 7 | Update the features page brief: the connected governance study shows suggestions being accepted | Content review |

Estimate: steps 1 to 4 about four to five days; step 5 about three days; steps 6 and 7 under a day.

## 7. Owner decisions (chat confirmation, 2026-10-20, not a sign-off)

The owner said "go with your recommendations but explain them in the ledger" and "just do plans, don't build". These
are recorded as adopted for planning; nothing is built.

1. **Existing keyword links become suggestions, not deleted.** Why: some of them may be right, and a person can confirm
   those in one click, while a wrong one stops looking like fact. Deleting would throw the right ones away with the
   wrong. Cost: a one-off migration that only touches links made by the DPIA handler and still unconfirmed; owners see a
   few suggestions they may dismiss. How to change: delete instead, with the same selection.
2. **Build AI drafting for the AIIA** (after DPIA and plans). Why: the DPIA and the continuity plan already have AI
   drafting, the landing page already claims it for the AIIA, and the prefill gives it good inputs. Cost: about three
   days, a new registered and declared AI feature, governed by each organisation's AI policy and always reviewed by the
   assessor. Until it ships, AIIA is removed from the landing page's assisted drafting panel. How to change: drop step 5
   and keep only the landing page correction.
3. **Order: DPIA, then continuity plans, then AIIA.** Why: the DPIA links are the only ones that misrepresent data
   today, and DPIAs carry the most data protection weight; plans next because activation happens under pressure; AIIA
   last because it is the newest flow and needs the new AI feature. Cost: AIIA users wait longest for help. How to
   change: run step 5 first; it does not depend on steps 1 to 4 except for the shared suggestion service.

Status: planned only. No code, data or landing page change has been made.

## Log

- 2026-10-20: assessment and plan written. Verified: AIIA tables and sidebar in Sentinel, no AI drafting for AIIA ever,
  link statuses already supported, DPIA keyword links stored without a status.
- 2026-10-20: owner adopted the three recommendations for planning (chat confirmation); recorded in section 7 and in
  ledger 07. Not built, on the owner's instruction.
