# Plan 24: respondent assignments (CISO 03) and Needs attention (CISO 01)

**Historical status (2026-11-03):** In progress on feature branch. **Current code status:** base assignment and Needs attention work merged in PR #44, follow-up fixes in PR #45. New overlap and Command Centre assurance work is uncommitted in the current worktree; see [current build status](../CURRENT-BUILD-STATUS-2026-11-05.md).

**Owner's words (chat, 2026-11-03):** "go, build CISO 03 and CISO 01".

**Design sources:** [CISO 03](../ciso-assistant-features/03-respondent-assignments.md) and [CISO 01](../ciso-assistant-features/01-assurance-quality-inspector.md). This file records how they were built, the decisions taken on the way and the results. It does not mark anything deployed.

## 1. Research (before building)

- **CISO Assistant** (intuitem, AGPL-3.0, so ideas only, no code): its assignments use the states draft, in_progress, submitted, changes_requested and closed; scope is locked once an assignment leaves draft; each item is unreviewed, changes_requested, resubmitted or accepted; submission is refused while a requirement that needs evidence has none, and the refusal names them. Its X-rays run fixed checks on every page load (no stored issue table), grouped by area and rule with Error, Warning and Info severities, each row linking to the record to fix; it has no dismissal. Taken: the states, the locked scope, the evidence-required refusal, on-demand evaluation, severity grouping. Added beyond it: a reviewed false-positive record (CISO 01 slice 5).
- A web search for other open-source questionnaire or assignment tools found only commercial products (IBM OpenPages, ServiceNow GRC, MEGA HOPEX), whose flows (owner answers, reviewer sends back or accepts) match the plan. Nothing to reuse.

## 2. What exists and is reused

- GRID audits carry the business unit (`grid_audits.business_unit_id`); controls follow their audit (`entity_scope_sql(("grid","control"))`). GRID tables live in each tenant's own schema.
- A GRID control is `Not Started`, `In Progress` or `Complete`; GRID marks it Complete when its required evidence files are approved.
- Vault proof semantics (`modules/evidence/proof.py`): live, current, accepted; `review_link` records a reviewer's verdict on one link and refuses the person who attached it.
- The Vault's own inspector (`modules/evidence/inspector.py`) checks files; Needs attention checks the records that rely on them.
- ERM acceptance (CISO 04, built): `erm_risk_acceptances` with a source hash (`acceptance._snapshot`).
- My Work collects sources in `modules/launcher/my_work_service.py`; notifications go in the `notifications` table.

## 3. CISO 03 design: respondent assignments

| Piece | Built as |
|---|---|
| Tables (tenant schema, with GRID) | `grid_assignments` (audit, unit, assignee, reviewer, due date, instructions, state, lock `version`), `grid_assignment_items` (one GRID control, response, observation, review state and note), `grid_assignment_proof` (a Vault file chosen for an item, the version and hash at the time, the Vault link it created), `grid_assignment_events` (append only history) |
| Capabilities | `grid.assignment.manage` and `grid.assignment.review`: audit lead (and super administrator). `grid.assignment.respond`: every role except the external auditor; it opens nothing by itself, only the assignments naming the person |
| States | assignment: draft, in_progress, submitted, changes_requested, closed, cancelled. item: unreviewed, changes_requested, resubmitted, accepted |
| Create | audit lead picks controls of one audit in their scope, an assignee who works in the audit's unit, a reviewer (themselves by default, never the assignee), a due date and instructions. A control already in an open assignment is refused, named |
| Launch | draft scope is editable; launch freezes it and tells the assignee. A later change is a revision with a reason, logged |
| Respond | the assignee sees only their assignment: the audit name, each control's reference, name and description, and their own answers. Save is per item with the lock version (a stale save gets a conflict). Proof is chosen from Vault files the assignee may open; choosing creates a pending Vault link to that control |
| Submit | refused while an item has no response, or a control with required evidence items has no proof; the refusal names them |
| Review | per item, by the named reviewer: accept (accepts its proof links through `proof.review_link`, so the reviewer must be able to open each file and the file must still be current) or request changes with a reason. All accepted closes the assignment; nothing left to review sends it back to the assignee |
| GRID verdict | an accepted answer does not change the GRID control status; the audit lead still sets it in GRID. Accepted proof links count as accepted proof everywhere the Vault's proof rules are read |
| Work and notices | My Work source `grid_assignments` (assignee: in progress and changes requested; reviewer: submitted); one notification per state change |

## 4. CISO 01 design: Needs attention

| Rule (version `a1`) | Fires when | Severity |
|---|---|---|
| `proof_missing` | a GRID control marked Complete, or an ARIA control marked Implemented, has no current accepted proof (an approved, unexpired GRID file, or an accepted current Vault link) | warning |
| `proof_stale` | the same claim has proof, but all of it expired, was replaced or was turned down | error |
| `risk_basis_unexplained` | an open ERM risk whose planned residual score is lower than its current score, with no treatment plan and no treatment | warning |
| `risk_residual_above_current` | an open ERM risk whose planned residual score is higher than its current score | error |
| `owner_or_review_missing` | an overdue GRID audit with no lead, BCM exercise with no owner, BCM plan review with no owner, or ERM risk review with no owner | warning |
| `risk_acceptance_expired` | the latest approved acceptance of an open risk has expired | error |
| `risk_acceptance_basis_changed` | the risk changed after its acceptance was approved | warning |

- Computed on request, through each module's own scope (`entity_scope_sql`): a record the viewer cannot open is never counted or named. A rule whose source cannot be read is reported as could not be checked, never as no issues.
- Each issue has a stable key (rule, rule version, record kind and id) and a fingerprint of the facts that raised it.
- A reviewer may record a false positive or an accepted exception against that fingerprint, with a reason and an optional expiry. The issue stays listed, marked reviewed with the reason; a changed fingerprint or a passed expiry opens it again. The source record never changes.
- Page: Needs attention (`/governance/attention/`), grouped by severity and rule, filters, pagination, each row opening the owning record.

## 5. Decisions (chat confirmation, not sign-off)

| Decision | Why | Cost | How to change it |
|---|---|---|---|
| Only the audit lead sends and reviews; the GRID auditor role does neither | Accepting an answer accepts its proof, which needs `evidence.link.review`; the auditor role does not have it | An auditor cannot run a round on their own | Give the auditor `evidence.link.review` and the two assignment capabilities |
| Anyone except an external auditor can be sent questions | The person who runs a control is often an employee or control owner without GRID access | None: the capability opens only assignments naming the person | Narrow `grid.assignment.respond` in `core/rbac.py` |
| An accepted answer does not change the GRID control status | GRID's own rules set Complete from approved evidence; an answer is a proposal (CISO 03: "a proposal until the auditor accepts it", and the verdict stays GRID's) | The audit lead still marks the control in GRID | Add an explicit "apply to the control" step to acceptance |
| Accepting an answer accepts its proof links under the Vault's rule | One meaning of accepted proof everywhere (Needs attention, coverage, group figures) | A reviewer who cannot open the file, or who uploaded it, cannot accept that answer; they are told why | Separate answer acceptance from proof review |
| A respondent's link is made to the assigned control only, without GRID's IMS inheritance | The assignment authorizes that control, not the controls it maps to | Mapped controls get the proof when someone links it in GRID or the Vault | Run the inheritance for respondent links too, checking each mapped control's scope |
| Upload goes through the Vault, not the assignment page | One upload path with all its checks (type, size, duplicates, filing scope) | The respondent uploads in the Vault, then chooses the file | Add an upload button that posts to the Vault's own route |
| Needs attention is computed on request with no issue table | The X-rays pattern; nothing to keep in step with the sources; a failed source is said to be unchecked | Each page load runs the checks (bounded at 2,000 records per source) | Materialize issues when a tenant outgrows it (measure first, as plan 23 did for search) |
| A reviewed issue stays listed as reviewed; nothing hides it | CISO 01: never hide an issue from an authorized view without a visible reason | The list keeps reviewed items (filtered out of Open by default) | None needed |
| No Command Centre count and no report gate yet | Rule quality and false positives should be seen with pilot users first (CISO 01 slice 6) | The page is reached from the sidebar, not from a count | Add a count card and a pre-report acknowledgement after the pilot |

## 6. Build log

- 2026-11-03: research recorded (section 1).
- 2026-11-03: committed `800ab8e7`: tables `grid_assignments`, `grid_assignment_items`, `grid_assignment_proof`, `grid_assignment_events` (GRID tables, so in every tenant schema), `assurance_issue_reviews` (shared, with row level security); capabilities `grid.assignment.manage`, `.review`, `.respond`, `assurance.attention.view`, `.review`; `modules/grid/assignments.py` and 15 routes under `/grid/api/assignments`; the Audit questions page; My Work source `grid_assignments`; `modules/governance/attention.py`, its page and two routes; sidebar links.
- 2026-11-03: found and fixed while testing in the browser: both pages announced success before redrawing, so text typed right after the message went into a form that was about to be replaced (the second answer of a reviewer was lost). They now redraw first. The Needs attention link was only in one of the three Command Centre sidebars; it is in all three.
- 2026-11-03: security review of the new code: a person answering from a parent unit can choose a file in a sibling unit that the reviewer cannot open. The reviewer was shown its title, and the refusal to accept named it. Both now say only that a file was chosen that they cannot open; test added.
- Known limit: the rule "one control, one open assignment" is checked in code, not by a database constraint, so two audit leads creating assignments for the same control at the same instant could both succeed. The second round is visible in the list and can be cancelled.

## 7. Verification

(Filled in as slices finish.)
