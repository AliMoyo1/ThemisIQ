# Fork and worktree cleanup, and the work to move into the main chat

Audit date: 23 October 2026. Master at the time: `fda87389` (PR 23).
Requested by the owner: audit and clean the forked sessions, record what is left in a plan, and move that work to this
main chat.

## 1. What was cleaned

Only things fully contained in master, with nothing uncommitted and nothing else that mattered, were removed.

| Removed | Why it was safe |
| --- | --- |
| Worktree `priceless-ardinghelli-064f9d` and branch `claude/funny-antonelli-7ac16e` | Sidebar overlap fix, merged as PR 20. |
| Worktree `status-after-pr11` and branch `claude/specialist-fixtures-grid-contrast` | PR 13, merged. Only SQLite temp files were untracked. |
| Worktree `suspicious-dijkstra-868efc` and branch `claude/suspicious-dijkstra-868efc` | Active Sessions fix, merged as PR 19. |
| Local branches `ecstatic-jemison-1ec81a`, `goofy-kowalevski-2c4f88`, `keen-poincare-67f4fb`, `lucid-liskov-c5e9b2`, `vibrant-keller-d6587a`, `landing-hero-connected` | Every commit is already in master. |
| Empty folders `suspicious-ishizaka-83672a`, `xenodochial-wilson-ce5658` | Not registered worktrees and empty. |

Kept on purpose:

- **Codex's worktrees** (`.worktrees/*`, the main checkout and `.codex/...`). They are not Claude's to remove.
- **Branch `claude/status-after-pr11`**, which has two commits for the open PR 12 (documentation only).
- **The six forks in section 2**, which hold uncommitted work that exists nowhere else yet.
- **The folder `hopeful-wilbur-d4d449`**. It is not a worktree but holds three files that exist nowhere else (section 3).

Not done, because deletion is not reversible and is the owner's call (section 5):

- Archiving or deleting the sessions in the sidebar.
- Deleting the GitHub copies of old branches.

## 2. Forks that still hold uncommitted work

None of these is committed or pushed. All start from master `bfde22d6`, now 20 commits behind. Codex's integration branch
(`codex/claude-integration-2026-10-22`, in `.worktrees/claude-integration-2026-10-22`) has copied the **production code**
of four of them. It has not committed, tested or pushed it, and it did **not** copy these forks' tests.

| Fork (worktree, branch) | Work | Codex has the code? | Not yet anywhere else |
| --- | --- | --- | --- |
| `great-jemison-18a029` | Operations Risk AIMS write routes lacked a unit check | Yes, extended | `tests/test_aims_write_scope.py`, plan file |
| `suspicious-swartz-8c47fe` | DPIA form dropped mitigations, assessor and due date | Yes, extended | `tests/test_sentinel_dpia_form.py`, `tests/ui/test_sentinel_dpia_form.py`, plan file |
| `sad-albattani-5255ea` | Report exports: shared report kit and every module report | Yes, reconciled by hand | `test_board_reports`, `test_export_safety`, `test_grid_audit_report`, `test_report_documents`, `test_report_kit`, `test_sentinel_reports`, `ui/test_report_buttons`, and the long plan (502 lines, open items O1 to O12) |
| `kind-cannon-4d360f` | Single record exports: DPIA, continuity plan and AI impact assessment | Yes, reconciled by hand | `test_record_documents`, `test_report_kit_links`, `ui/test_record_document_buttons`, plan file, plus the report tests above |
| `sweet-northcutt-aada82` | Fork of `sad-albattani`: regulator grade RoPA, DPIA and AIIA profiles by jurisdiction | Partly (codex lists "regulator record profiles") | `tests/test_record_profiles.py`, its plan. Its checklist steps S5 to S8 were still unticked. |
| `strange-nobel-62b25a` | Purge expired rows from the `sessions` table (session sweeper) | **No** | `core/session_sweeper.py`, `tests/test_session_sweeper.py`, edits to `core/auth.py`, `main.py`, `tests/test_postgres_init.py`, plan file |

How to read "differs": for the report and record forks, most files differ from codex's copy because codex reconciled them by
hand with newer master changes. Take codex's version of the production code. Bring the fork's tests across and make them
pass against codex's code, not the reverse.

## 3. Other things found

- **`hopeful-wilbur-d4d449`** (folder, not a worktree) holds three unique files from 21 October:
  - `PLAN_security_report_and_tracker_2026-10-21.md`
  - `ThemisIQ_Security_Report_2026-10-21.docx`
  - `ThemisIQ_PreLaunch_Tracker_updated.xlsx`

  Move them to a tracked place, or confirm they are superseded by `plans/security-assessment-2026-10-20.md`, then delete the
  folder.
- **A stray detached worktree** was registered by another session's scratch folder (`.../sad-albattani-5255ea/.../scratchpad/lk2`).
  Run `git worktree prune` after that session is closed.
- **PR 21 (onboarding guide, this chat) is half merged locally.** Master was merged into
  `claude/onboarding-agent-plan` in the landing-hero checkout with its one conflict resolved (the Themis panel template
  and script), but the merge is not committed or pushed. The capability inventory already matches. The remaining steps are to
  rerun the affected tests, commit the merge, push, wait for the checks and merge.
- **Privacy note from codex, to act on in PR 21.** The guide masks emails and long numbers, but that is not a reliable
  confidentiality boundary for free text. The AI feature is registered as data category "public". Before provider calls are
  enabled by default, classify a question as business data, so each organisation's AI policy can refuse it, and review the
  masking. Deterministic answers (no provider call) already work when AI is off.
- **Codex's "still to integrate"** also lists the Case and Audit report Vault-link patch.

## 3b. Open decisions already recorded in the fork plans

These need the owner, not just work:

1. **AIMS O2:** are the AI controls catalogue routes a shared library, or are custom controls private to a unit?
2. **DPIA D3:** `risk_level` is deliberately not stored. The dashboard buckets and the high-risk escalation still read a
   column nothing writes. Codex shows unrated DPIAs as unrated; confirm that is the intended behaviour.
3. **Plans created in the app** have no business unit owner. Should a new plan take its author's unit?
4. **A generated record document is downloaded, not filed.** Should each export be kept in the Evidence Vault as a
   versioned artifact? This needs a retention and permission rule.
5. **Report plan O1 to O4, O6 to O8:** the two risk bandings, banker's rounding in about 25 other computations, what
   "done" means for a breach, and so on.

## 4. Order to move the work into this chat

1. **Finish PR 21** (small, in hand). Add the free-text classification fix first.
2. **Wait for codex to commit its integration branch.** Do not start another copy of the same code.
3. **Port the forks' tests onto codex's branch**, one fork at a time, in this order. Each step ends with its tests
   passing, the capability inventory regenerated, and one pytest session at a time:
   1. AIMS scope tests (`great-jemison`).
   2. DPIA form tests, backend and browser (`suspicious-swartz`).
   3. Report kit tests (`sad-albattani`).
   4. Record document tests (`kind-cannon`).
   5. Record profile tests (`sweet-northcutt`), then S5 to S8 of its plan.
4. **Build the session sweeper** (`strange-nobel`) on current master as its own small PR. It is independent of the rest.
   After deploy, `journalctl -u themisiq-app.service` should show "Session sweeper started" at boot and "Session purge:
   removed N expired session(s)" on the first run.
5. **Run the full suites once on the combined branch:** backend, browser, and the real PostgreSQL lane. The source forks'
   own results do not count for the integrated branch.
6. **Then clean up:** with everything committed and merged, remove the six fork worktrees and branches, move or delete
   `hopeful-wilbur-d4d449`, and archive the finished sessions.

## 5. Needs the owner

- Permission to archive, or delete, the sidebar sessions whose work is now merged: "Fix profile page active sessions list",
  "Fix module-sidebar overlap when icon rail is pinned", "Replace retired Claude model default", "Fix new-tenant
  provisioning FK ordering bug", "Fix My Dashboard role-detection bug", and the other July to September fixes. Archiving
  is reversible. Deleting is not, and the app asks first. I left the sidebar as it is, because the parent session of the
  forks ("Fix profile page ...") is what groups the others.
- Whether to delete the old GitHub branches (`claude/ecstatic-jemison-1ec81a`, `claude/landing-hero-connected` and the
  others already merged).
- The decisions in section 3b.

## Log

- 2026-10-23: audit done. Three merged worktrees, six merged local branches and two empty folders removed. Plan written.

## Status, 23 October 2026 evening (after codex finished; master 816e7db2)

Codex merged its integration (PR 25). Master now holds the production code of every fork except the session sweeper.
What was left in the forks was their tests, and a few places where the integrated code differed from what the fork
tests expected. This branch (`claude/port-fork-tests`) ports the tests and settles each difference:

| Fork | Result |
| --- | --- |
| `great-jemison` (AIMS write scope) | `test_aims_write_scope.py` ported. Integrated rule is stricter and is kept: a new assessment takes its author's unit, and only an administrator makes one organization wide, so two tests were rewritten to say that. |
| `suspicious-swartz` (DPIA form) | Backend and browser tests ported, plus the real PostgreSQL test. `risk_level` is now stored (derived from the chosen overall rating), so decision 3b.2 is settled that way and the test no longer lists it as not stored. **Two production gaps fixed:** the DPIA list failed to load whenever any DPIA had a due date (`today` was never defined in the list loader), and the drawer's "Documents in the Evidence Vault" panel had not been integrated. |
| `sad-albattani` (report kit) | Six backend files and the report button browser test ported. **One production gap fixed:** the RoPA report no longer limited the PDF to the document row limit, so 70 records made a 31 page document with no "the Excel download holds every row" note. The three RoPA tables have the limit again. The tests follow the new layout (controller register, processor register, readiness list). |
| `kind-cannon` (record documents) | Backend and browser tests ported; expectations follow the integrated wording (the downloads are links and are filed in the Vault, so the audit line carries `vault=...`; plan owner is "Process or unit owner"; the DPIA chart reads "Special category data"; `risk_level` has no default). |
| `sweet-northcutt` (record profiles) | Its production code is in master (`record_profiles` for RoPA, DPIA and AIIA); `test_record_profiles.py` passes there unchanged. Steps S1 to S7 of its plan are done by codex's integration; S8 is covered by the suites run on this branch. |
| `strange-nobel` (session sweeper) | Not in master. Built on current master as its own branch and PR. |

Decisions now settled by the integrated code (3b): 2 (`risk_level` is stored), 4 (record documents are filed in the Evidence
Vault as part of the download), and the unit rule for new AIMS assessments. Still open: AIMS O2 (is the controls catalogue
shared), plans created in the app having no unit owner, and report plan O1 to O4 and O6 to O8.

Verification on this branch: the ported backend files 294 passed, the three browser files and the DPIA form 25 passed, the
whole real PostgreSQL lane (78 tests) passed on PostgreSQL 18, capability inventory matches. The full backend and browser
suites run in CI.

Cleanup after merge: remove the six fork worktrees and branches (their work is either in master or in this PR), prune the
stray `lk2` worktree, and decide about `hopeful-wilbur-d4d449` and the sidebar sessions.
