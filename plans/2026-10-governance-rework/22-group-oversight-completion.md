# 22. Group oversight completion: the remaining build of plan 19

**Historical status (2026-11-03):** Eleven slices built on a feature branch. **Current code status:** merged through PR #42, with synthetic PostgreSQL pilot and speed checks; see [current build status](../CURRENT-BUILD-STATUS-2026-11-05.md). No real customer privacy sign-off is claimed.

## 1. What is already true

- **The DPO is the privacy reviewer, and code already enforces it.** `group.terms.privacy` is held only by the DPO. A relationship becomes active only after the DPO's privacy review (`privacy_review_by`) and the legal review. The terms, including `figure_measures` and `issue_types`, are written once when the relationship is proposed and never updated, and the publishers read terms only from active relationships. So the measure and issue lists cannot be shared without a DPO having reviewed them. Plan 21 section 6 said this was "a process gate, not enforced in code"; that was wrong and is corrected there.
- Plan 19's later status notes show stage 4 and 5 further along than its stage table: batch version filing, duplicate preview, control link suggestions, grant review with paging, request verdicts and history, parent cases, My Work feeds for requests, cases and grants.

## 2. What is left, and the slices

| Slice | Plan 19 stage | Build |
| --- | --- | --- |
| C1 | 2/6 | Pack integrity says "cannot be checked" (not "failed") when a pack's source is no longer readable. A test that the relationship cannot activate without a DPO privacy review. Plan 21 gap corrected. |
| C2 | 5 | Daily reminders and escalation (in-app notifications): grant reviews due in 14 days or overdue; proof requests past their needed-by date to the source reviewers, then after 7 more days to the requester's managers; parent policies with no adoption decision after 30 days. Nothing is released, renewed or granted automatically. |
| C3 | 5 | Absence cover. Changed while building (see section 4): no delegation outside a role. Group reviews are never assigned to one person, so any other holder of the role already covers an absence. When nobody else holds the role, the daily pass tells the organization's administrators to staff it. |
| C4 | 5 | Cases: amend the position (with a trail) and reopen a closed case (a different person, a reason). |
| C5 | 3/5 | Policy adoption: the parent sees each child's adoption state for its own published policy versions (state and dates only, never the child's reason text); a child may link the adopted policy to its own local controls. |
| C6 | 6 | More group measures: the registry's `bcm.*` and `sentinel.*` metrics are publishable, built by their own dashboard code for the whole organization. The `vault.*` metrics are registered but no code builds them, so they cannot be published; that is listed in section 7. |
| C7 | 6 | Framework register: per child, active frameworks and the share of controls implemented, published as a figure with a flat numeric detail map. |
| C8 | 6 | Packs carry issue register counts (by type and status, from the frozen run ids) as well as figures; retention date and legal hold on a pack; nothing is purged automatically. |
| C9 | 6 | Auditor room (see section 3). |
| C10 | 4 | Durable intake staging: a staged upload is stored server-side in quarantine and survives a reload; it is filed into the Vault only after review, through the existing upload checks; quarantine states for a file that fails a check. |
| C11 | 7 | Controlled intelligence: a cited answer over the documents a viewer can already open (own tenant and released group versions), with the provider off falling back to search results, and wrong-tenant and prompt-injection tests. |

Each slice has focused service tests, a PostgreSQL row level security test where it adds a table, and a browser test where it adds a screen.

## 3. Auditor room design (C9)

Research (2026-11-03): no open-source project fits this stack to reuse. CISO Assistant (AGPL-3.0, so its code cannot be copied into this product) lists RBAC and "respondent mode" but documents no expiring auditor access; grc-lake mentions a read-only "audit room" with no expiry detail. The common pattern is a named, read-only auditor identity limited to a room and a time window, which this design follows by reusing what ThemisIQ already has.

- **Identity.** The auditor is an ordinary user in the parent tenant with the existing `external_auditor` role, so MFA, sessions and the login audit apply unchanged. No new identity system.
- **Room.** A Compliance Manager or Chief GRC Officer proposes a room: title, named auditor, start and end (at most 90 days), and its exact contents: issued packs and group-published document versions the proposer can currently open. A different person (DPO, Compliance Manager or Audit Lead) approves it. Nothing is in the room by default.
- **What the auditor sees.** Only rooms naming them, only while open, only the listed items, each rechecked at read time through the same pack and grant rules as the specialist who added it. Downloads are per item and off by default.
- **Questions.** The auditor asks a question on the room; a specialist answers, citing only room items. Questions and answers are kept with the room.
- **Ending.** Expiry ends access automatically; a specialist may close it early. Every open, download, question and answer is logged.

## 4. Decisions adopted (chat confirmation, not sign-off)

Each decision lists why it was taken, its cost, and how to change it.

| Decision | Why | Cost | How to change |
| --- | --- | --- | --- |
| No nested groups | Econet with EcoCash and OmniContact is one level; nesting multiplies the inference and grant paths | A grandchild is not visible to its grandparent | A new relationship model with path checks; separate plan |
| Figures stay whole organization, not per business unit | Group figures answer a group question; unit splits raise small-cell risk | A subsidiary cannot share one unit only | Add unit-scoped measures and terms; separate plan |
| No child participant inside parent cases | The proof request already carries the child's part, and a shared case would expose the parent's position and sibling requests | The child sees requests, not the case | A child-specific shared view with DPO review; separate slice |
| Reminders are in-app notifications and My Work, not email | Email templates need the email inventory and outbox review; in-app is already scoped and audited | No email nudge | Register templates in the email inventory and enqueue alongside |
| No delegation of a review to someone outside the role | Group reviews are not assigned to a named person: every other holder of the capability may act, so an absent reviewer is already covered. Lending a capability to someone outside the role would weaken the separation that the independence rules depend on | An organization with a single holder must assign the role to a second person; the daily pass tells its administrators when that blocks an item | A time-boxed capability loan with its own approval and audit; separate slice |
| A staged batch file is checked like an upload, and a file that fails is quarantined without its bytes | Keeping a file that failed a security check has no use and some risk; the reason and hash are enough for the person to see what happened | A quarantined file cannot be inspected later on the server | Keep quarantined bytes in a separate, never-served store with its own retention |
| The group question answer needs both organizations' AI policies | The asking organization's policy is the platform's normal check; the text belongs to the source, so its own policy decides whether it leaves | A subsidiary with no approved AI policy gives search results only | None needed: the subsidiary approves its own policy |
| Framework names cross only from the built-in catalogue | A framework a tenant created has a name a person typed; the group sees it only as Other frameworks | A custom framework is not named to the parent | Add it to the catalogue, or a reviewed per-relationship alias list |
| Pack retention records a date and legal hold, and nothing is ever deleted automatically | Deleting a board record is a reviewed decision, not a timer | Old packs stay until someone decides | A reviewed deletion step with second-person sign-off; separate slice |
| Auditor identity reuses tenant accounts with the `external_auditor` role | MFA, sessions and login audit already exist and are tested | The auditor needs an account in the parent tenant | Federated guest identities; separate plan |

## 5. Build log

- 2026-11-03: plan written; branch created from `807e65f1`.
- 2026-11-03: C1 committed (`07f9532a`): pack integrity is `passed`, `failed` or `partly_checked` with the unreadable organizations named; the page and exports use the same sentence. DPO privacy review test added. 40 tests pass.
- 2026-11-03: C2 committed (`539c92c4`): `modules/evidence/group_reminders.py`, table `group_reminders_sent` (organization-scoped row level security), daily job at 09:30 UTC in the evidence scheduler. Each organization's pass runs in its own tenant context, so it reads only rows it is a party to (the adoption table has no bypass policy, so a platform-wide read would have seen no decisions and nagged everyone).
- 2026-11-03: C3 committed (`764aa2d9`): the administrator alert when nobody can act, 5 reminder tests pass.
- 2026-11-03: C4 committed (`d5df1f8e`): `amend_position` and `reopen_case` in `group_cases.py`, two routes, forms on the cases page; the earlier position and the closing conclusion stay in the case trail.
- 2026-11-03: C5 committed (`6ab46105`): `group_adoption.rollup` reads each subsidiary's decision state in its own tenant context (state and dates only); `group_adoption_controls` (subsidiary-only row level security) links an adopted policy to the subsidiary's own ARIA, GRID, BCM or AI controls; panels on the adoption page.
- 2026-11-03: C6 committed (`ae005a45`): `bcm.*` and `sentinel.*` figures are publishable; the DPO's family filter now shows the privacy figures.
- 2026-11-03: C7 committed (`9ab23824`): `modules/aria/framework_register.py`, registry key `aria.framework_implemented`, the framework catalogue hoisted to `database.EXPECTED_FRAMEWORKS`; figure labels show the fixed module or framework name. Found and fixed while testing: the correction form on the figures page was bound only after two requests finished, so an early click submitted the form natively and lost the entry.
- 2026-11-03: C8 committed (`a2d0c9d8`): packs freeze issue register counts (never rows) with their run hash; `group_pack_runs` keeps those runs from the daily pruning; `group_pack_retention` (append only) records the retention date and legal hold; PDF and Excel include both.
- 2026-11-03: C9 committed (`122909e8`): `modules/governance/group_rooms.py`, four tables with parent-only row level security, capabilities `group.room.manage`, `group.room.approve` and `group.room.enter`, ten routes and the Audit rooms page.
- 2026-11-03: C10 committed (`24f37854`): `modules/evidence/staging.py`, table `evidence_staging`, three routes; the upload route files a staged file by id; the batch page keeps each file on the server once it has a scope and restores the queue after a reload; staged files expire after seven days in the daily job. The upload's blocked extension and MIME lists moved into `staging.py` so both paths share one copy.
- 2026-11-03: C11 committed (`ec832768`): `modules/evidence/group_ask.py`, AI feature `evidence.group_ask` declared, route and the Vault panel. Found and fixed while testing: the Vault page never loaded the "Shared by related companies" section on start, only after an upload; the group catalogue responses now also send `Cache-Control: private, no-store`.
- 2026-11-03: review hardening: a group question reads at most 200,000 characters of one document; quarantined files count toward the 50 staged files a person may hold.

## 6. Verification

- Focused SQLite tests per slice, all passing: reminders 5, case amend 2, adoption rollup 3, figures and band and packs 63, pack issues and retention 4, rooms 6, staging 5 (with the upload library and proof tests, 36), group ask 6 (with the AI declaration tests, 22).
- Browser: group figures page 12, cases page 2, requests and adoption page 3, audit rooms page 3, batch page 10, group ask 1 with the company review page 2.
- PostgreSQL with the restricted (non-bypass) role: a new test covers every table this plan added; with the existing group tests, 8 passed.
- Full PostgreSQL lane (PostgreSQL 18, Docker): 93 passed.
- Full backend suite: 3352 passed, 93 skipped, 2 failed on the first run. Both failures were the AI call guard: the group question passed its feature name through a constant instead of the literal string the guard reads. Fixed; the guard, group ask and AI declaration tests then passed (92).
- Capability inventory regenerated; `--check` passes.
- Three browser tests in `tests/ui/test_evidence_upload_error_detail.py` fail on this branch and on the merged G1 code alike (the upload dialog's toasts and duplicate notice): not caused by this work, not fixed here.

## 7. Still open after this plan

Update 2026-11-03: plan 23 built the Vault claim figures, ran the synthetic pilot (21 of 21 steps on PostgreSQL) and measured search speed (every p95 under 0.25 seconds at 5,000 files). Each customer names its own DPO at onboarding, so that is no longer an owner step.

- **Owner and operations:** a live inventory and sign-off of real tenants, the pilot with one real customer group, deployment.
- **Measured acceptance:** mobile usability, timed specialist tasks with people.
- **Not built, by decision (section 4):** nested groups, unit-level group figures, child participants in parent cases, review delegation outside a role, email reminders, federated auditor identities, automatic deletion of packs.
