# 16. Specialist browser fixtures and the GRID card link contrast

Branch `claude/specialist-fixtures-grid-contrast`, from `master` `790ce1c`. Goal: make the browser lane on `master` green
again. The 46 failures are recorded in [07](07-implementation-ledger.md), "Stage verification (master after pull request
11)".

## Owner decision (chat confirmation, 2026-10-20, not a sign-off)

AI Governance is limited to specialist roles. General employees will not sign in to ThemisIQ at all. So the browser tests
that registered an AI use as the `employee` persona are wrong, not the product. They move to a specialist persona that holds
`ai_use.intake_create`. Tests that prove an employee is refused stay as they are, because the refusal is still the rule.

## Steps

1. List the exact failing browser tests on this branch (AI Governance files, AI policy page, module home).
2. Fix the GRID card links: the connected overview cards use `--accent` (`#059669`, 3.13 to 1). Use `--accent-ink`, the
   text-safe accent each module already defines for light and dark (`#047857` and `#6ee7b7` for GRID).
3. Move the AI Governance browser tests that act as the author of an AI use to a specialist persona.
4. Re-run the affected browser files, then the whole browser lane.
5. Record the result in 07 and here.

## Log

- Step 2 done: `static/js/module_home.js` card links now use `var(--accent-ink,var(--accent))`.
- Step 3: the author of an AI use in the browser tests is now `risk_owner` (`AUTHOR` in `test_ai_governance_pages.py`).
  A new `privacy_analyst` persona (sees AI Governance, cannot review or decide) replaces the employee in the checks that
  were about a viewer without review rights (decisions queue, regulatory page, review desk fallback). The oversight
  person is now the compliance manager, because an oversight person must be able to open the use. Checks that an
  employee is refused stay, and now also cover the inventory.
- First run after step 3: 5 failures left. Four were real findings:
  - **Product bug, fixed.** A decision asked for by someone who cannot open one checklist step (a DPO has no ORM
    access, so the AI management assessment step reads `no_access`) could never be approved by a decider who can
    open it: the digests differed, so the app said "The brief changed after the decision was requested". In practice
    a DPO's request on any use was undecidable by a super admin, GRC officer or compliance manager. Fix:
    `decisions._hash_as_asked` compares the current brief with the asker's, treating the steps the asker could not
    open as they were frozen. Every other moved fact still blocks. The decider still signs the full brief they see.
    The opposite direction (decider sees less than the asker) was already refused by `_proposal_access_gap`. Two
    backend tests added to `tests/test_ai_governance_decisions.py`; 37 of 37 decision tests pass.
  - The oversight picker no longer lists an employee: correct, see above.
  - **Open owner question.** `/ai-governance/requests` ("My requests") still opens for an employee, because it is
    gated by `ai_use.submit`, which every role except the external auditor holds. It shows only the person's own
    requests, so nothing leaks, but it does not match "AI Governance is for specialists". Narrowing `ai_use.submit`
    is an access change, so it is left for the owner. The browser test no longer asserts that page.
- The dialog wording "Required steps are not done" no longer exists (it reads "Review gaps remain"); one browser
  assertion was stale and is updated. It was never reached while registration failed.
- Step 4, lanes on this branch, 2026-10-20:
  - Backend, SQLite: 2670 passed (2668 plus the 2 new decision tests), 75 skipped, 0 failed.
  - Browser, all 89 files (the earlier lane ran 49): 552 passed, 2 skipped, 6 failed. Every AI Governance, module home
    and AI policy test passes. The 6 failures also fail on unmodified `master` `790ce1c` (checked in a throwaway
    worktree), so they are not from this branch: 2 in `test_aria_managed_edit.py` (the edit modal never opens) and 4
    in `test_workflow_sla_comm_scope.py` and `test_workflow_tenant_scope.py` (403 where the tests expect 404, 400 or
    201, consistent with the newer dedicated permission for authoring workflow and communication templates). Not fixed
    here.
  - PostgreSQL lane not run: the fix changes no SQL.

## Owner decision 2: nothing opens for employees (chat confirmation, 2026-10-20, not a sign-off)

Answer to the open question above: "Nothing opens for employees." Adopted for AI Governance as a whole.

- `ai_use.submit` and `ai_literacy.take` no longer include `employee` (`core/rbac.py`). These were the only two
  capabilities used by an AI Governance route that an employee still held, so My requests, the request pages, the
  business unit list for requests and AI literacy now answer 403 for an employee, and the shell no longer shows them the
  request history link. A backend test scans every `require_capability` in `modules/ai_governance` and asserts an
  employee holds none of them, so a new route cannot quietly reopen the module.
- AI literacy: a course can no longer target the `employee` role (422). A course saved earlier that names employees
  drops that role on its next edit instead of refusing the edit. A person whose only roles are employee or external
  auditor is never counted in a course's audience, including as the owner of an AI use. Cost: an AI use still owned by
  an employee keeps its "owner literacy" quality signal open until a specialist owner is named. How to change: put
  `EMPLOYEE` back in the two capability sets and in `literacy.AUDIENCE_ROLES`.
- Tests: the literacy backend tests use a privacy analyst learner; the literacy browser test assigns the course to a BCM
  manager (a specialist with no other AI Governance access); the browser refusal test now covers the home page, review,
  inventory, register, My requests and literacy. `docs/generated/capability_inventory.*` regenerated: the only change
  is `employee` leaving 11 AI Governance routes.

## Update after merging master (2026-10-21)

Pull request 14 retired AI literacy on `master` (capabilities, service, pages, scripts and tests). Merging `master` into this branch drops this plan's literacy changes (the `ai_literacy.take` employee exclusion, course audiences and the literacy tests) in favour of that retirement. Everything else stands: `ai_use.submit` still excludes employees, the guard test still checks every AI Governance route gate (now without the literacy capability), the decision fix, the fixtures and the contrast fix. Capability inventory regenerated on the merged code. Checks on the merge: AI Governance, capability and My Work backend tests 750 passed, 0 failed.
