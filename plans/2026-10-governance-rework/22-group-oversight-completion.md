# 22. Group oversight completion: the remaining build of plan 19

**Status:** In progress on branch `claude/group-completion`, from master `807e65f1` (after PR 41), started 2026-11-03. Owner direction (chat, 2026-11-03): "The privacy reviewer is the DPO. Do and complete all remaining building." That is a chat confirmation, not a formal sign-off. Nothing here is merged, deployed or enabled for a real customer group.

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
| C6 | 6 | More group measures: the registry's `bcm.*`, `sentinel.*` and `vault.*` metrics become publishable once each builder is shown to run organization-wide without a viewer. A measure that cannot is left out and listed. |
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
| Auditor identity reuses tenant accounts with the `external_auditor` role | MFA, sessions and login audit already exist and are tested | The auditor needs an account in the parent tenant | Federated guest identities; separate plan |

## 5. Build log

- 2026-11-03: plan written; branch created from `807e65f1`.
- 2026-11-03: C1 committed (`07f9532a`): pack integrity is `passed`, `failed` or `partly_checked` with the unreadable organizations named; the page and exports use the same sentence. DPO privacy review test added. 40 tests pass.
- 2026-11-03: C2 committed (`539c92c4`): `modules/evidence/group_reminders.py`, table `group_reminders_sent` (organization-scoped row level security), daily job at 09:30 UTC in the evidence scheduler. Each organization's pass runs in its own tenant context, so it reads only rows it is a party to (the adoption table has no bypass policy, so a platform-wide read would have seen no decisions and nagged everyone).
- 2026-11-03: C3: the administrator alert when nobody can act, 5 reminder tests pass.

## 6. Verification

(Filled in as slices finish.)
