# 03. Small, reviewable respondent assignments

**Status:** Implementation proposal, 2026-10-07. **Priority:** after GRID/Vault scope and My Work reliability. **Owner:** GRID for audit answers; Evidence Vault campaigns for proof requests. **Inspiration:** CISO Assistant's [assignments and respondent mode](https://github.com/intuitem/ciso-assistant-community/blob/main/product-docs/features/assignments.md).

This plan is for an **authenticated, narrowly authorized internal respondent**. CISO Assistant's respondent role also signs in. An accountless external write/upload flow is a separate, conditional [invitation plan](06-external-questionnaire-invitations.md), not an automatic extension of this role or a public trust page.

## User journey

An auditor selects five controls in one audit, assigns them to the service owner, adds a due date and instructions, and sends the assignment. The owner lands on a focused page with those five questions, prior accepted facts and an **Attach existing proof** picker. They save a draft, submit, and see two items returned with exact reviewer comments while three remain accepted. The auditor sees review progress and unresolved requests in GRID; the owner sees only their own work in My Work.

## Current-state anchor

`grid_controls` has `assignee_id`, `due_date`, `status` and notes. Vault's local `evidence_campaigns`, `evidence_requests`, `evidence_request_events` and data service support named assignees/reviewers and requested → submitted → in_review → accepted/returned transitions, but the current Phase 1a work is uncommitted. [PLAN-36](../PLAN-36-themisiq-stabilization-and-product-improvements/task_plan.md) and the [Vault plan](../../design/evidence-vault/PLAN.md) own their acceptance. This feature groups audit questions and their review states; it does not create a second evidence request lifecycle or generic task engine.

## Scope and data contract

- One assignment belongs to one organization, audit and authorized BU scope. It has assignee (or resolved team membership), reviewer, due date, instructions, state, lock version, created/submitted/reviewed times, and an immutable history of transitions.
- Assignment items reference existing `grid_controls`; each item has its own response, observation, review state (`unreviewed`, `changes_requested`, `resubmitted`, `accepted`) and a set of selected versioned evidence links. Decide whether GRID's existing control status remains the final audit verdict; the assignment response is a proposal until the auditor accepts it.
- One control should have one active assignment for a review round unless the auditor explicitly opens a second contributor role. Define reassignment and reviewer conflict rules before adding team assignment.
- The assignee's access is the intersection of organization, BU, module capability and exact assigned items. A respondent-only capability grants no audit-wide read or mapping/export privileges. Direct-ID APIs, counts, filenames, search results and download URLs obey the same rule.

## Design and build slices

1. **Inventory roles and requests.** Determine which GRID actions currently require auditor privilege, how My Work resolves GRID tasks, and which Vault campaign/request paths are actually accepted on PostgreSQL. Specify a narrow respondent capability and reviewer capability; avoid broadening an existing role to all audit records.
2. **Create and launch.** Auditor selects permitted control IDs in the same audit, sees duplicates/active assignments, confirms owner and due date. Draft scope is editable; launched scope is frozen. A later scope change makes an explicit revision with actor and reason instead of silently altering accepted work.
3. **Focused response page.** Show control wording, linked context, current accepted answer if permitted, required inputs, evidence version/status and guidance. Allow save draft, resume, submit and accessible inline validation. Evidence selection uses Vault's scoped picker and link operation; upload is an optional route into the same canonical item.
4. **Item-level review.** Auditor accepts or requests changes per item with a specific reason. Assignment state is `draft`, `in_progress`, `submitted`, `changes_requested`, `closed` (or a compatible explicit mapping to existing states). Resubmission preserves accepted item decisions unless source data changed. Optimistic locking prevents stale reviewers from overwriting each other.
5. **Work and notifications.** Project a single assignment action into My Work and Command Centre with a deep link and due date. Reuse existing notification/event infrastructure after PLAN-37's delivery fixes, dedupe by assignment ID and state version. A separate Vault evidence request is created only for a real missing-proof need, with its ID linked to the assignment item.
6. **Reporting.** GRID shows completion and review progress separately. Exports label draft answers and returned proof clearly; only accepted responses may influence an approved audit verdict, subject to GRID's own signoff rules.

## Acceptance outcomes

- A respondent can complete their assigned items without seeing the rest of the audit or another BU's titles, counts, files or status.
- An auditor can return one item, leave three accepted, and see who changed each item and when; resubmission does not erase prior review evidence.
- Assignments and evidence requests do not produce duplicate My Work tasks or file copies. A Vault version change or permission loss is visible to the reviewer before acceptance.
- A stale edit receives a conflict and refresh path. A departed/reassigned user cannot continue using an old direct URL or download link.
- The focused journey is usable with keyboard, mobile, 200% zoom and no AI provider. Track median completion time and returned-item rate in a pilot.

**Later:** conditional questionnaires and team assignment after a simple single-assignee round is reliable. Do not auto-expand a live assignment because a framework question changes without an explicit, reviewable rule.
