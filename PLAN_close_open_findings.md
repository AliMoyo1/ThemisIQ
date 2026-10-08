# Close the findings left open after the parallel-chat integration (2026-10-08)

Status: done and verified (2026-10-08); waiting for a decision on committing. Nothing here is committed or pushed. Follows `PLAN_integrate_parallel_chat_changes.md`, whose "Open, reported and not fixed here" list this plan works through. The user's instruction was "fix all that is pending"; it does not authorize committing.

## Items (in the order they will be done)

| # | Item | Why it matters | Source |
| --- | --- | --- | --- |
| A1 | Topbar search (`api_global_search`) shows titles from other business units, and checks no module capability | Live scope leak (PLAN-37 Appendix A, finding 2) | Reproduced again 2026-10-08 |
| A2 | Related Items (`api_links_get`, `api_links_create`, `api_links_delete`): returns other units' titles, answers for a record the caller cannot open, create-then-read reveals title and existence, create and remove not audited | Live scope leak (finding 1) | Reproduced again 2026-10-08 |
| A3 | `get_cross_module_profile` (`core/vendor_link.py`) ignores the viewer's scope | Finding 3 | Read |
| C | Ask ARIA page header count (`aria/routes.py`) counts the whole index | A number only, but it ignores the scope the search now applies | Read |
| D1 | Removing an evidence link, deleting, archiving or permanently deleting an item in the Vault does not recompute control effectiveness | Scores stay high until the 03:00 UTC job | PLAN_evidence_links_soft_delete_readers.md |
| D2 | GRID-first re-attach: an item attached from GRID keeps its `grid_evidence_files` row after the Vault unlinks it, so re-attaching from GRID returns early and no live link exists | Link and file disagree | same |
| B | About 39 more plain `LIKE %s` lines in 13 files are case sensitive on PostgreSQL (finding H3 in `PG_MIGRATION_AUDIT.md`) | Search boxes miss "iso 27001" when the data says "ISO 27001" | `PLAN_global_search_portable_like.md` item 5 |
| E | About 58 sites catch a database error and carry on (worst: `modules/launcher/routes_dashboard.py`, 14) | Failures look like empty data | `PLAN_pg_session_state_rollback.md` audit |
| F | RLS row filtering never exercised: the PG lane connects as a superuser | The user-named priority (RLS state) is only checked through session settings | integration report |

Correction to the earlier report: item B was described there as "unscoped" LIKE lines. They are a case-sensitivity (portability) problem, not a scope leak. The scope leaks are A1 to A3.

Not fixable from here: checking the production database role (NOSUPERUSER and NOBYPASSRLS) on the VPS, running `scripts/rebuild_ask_index.py` after deploy. Both stay with the user.

## Rules for this job

- Test first, and see it fail: every item gets a regression test that is red on today's code. PG-layer or PG-behaviour items also get a real-PG test (throwaway container, see the test-environment memory).
- Security first; shortest correct diff; reuse the existing scope rules (`bu_scope_ids`, `document_scope_sql`, `evidence_scope_sql`) instead of inventing new ones.
- Match what the owning module's own list and detail routes require; search and Related Items must never show more than the module does.
- No commit, no push, no deployment. No em dashes. Repo venv, from `oneforall/`, one pytest session at a time.

## Change log

2026-10-08, A1 + A2 (topbar search and Related Items).

- Re-ran the earlier reproduction: a unit A user saw unit B breach titles in search and in Related Items, could link their risk to a second unit B breach and read its title back, and a nonexistent breach id answered 404 while an existing out-of-scope one answered 201 (an existence oracle). Note the earlier script used the role key `compliance_mgr`, which does not exist (`compliance_manager` does); the search ignored roles entirely, which is itself part of the bug.
- Found what each module's own routes require (list and detail agree): Sentinel breach, DPIA, DSR and vendor need their own `*.manage` capability (breach and vendor: super admin and DPO only), ropa needs `module.sentinel.access`; GRID nc needs `grid.nc.manage`; ERM risk needs `erm.risk.view`; the rest need the module capability. Business unit rule everywhere: NULL unit is organization wide, otherwise inside the caller's subtree.
- Tests first: `tests/test_entity_scope.py` (users by entity types matrix: 7 personas, 17 kinds, search per kind, Related Items per anchor, create/read/delete). RED on today's code: 19 failed (every non-super persona; the 30-result cap of search needed one query per kind, which I fixed in the test).
- New `modules/governance/entity_scope.py`: one registry of kinds (capability, licence module, business unit column or audit) with `may_view_kind` and `entity_scope_sql`; reuses `document_scope_sql` and `evidence_scope_sql` for the two kinds with org rules. It sits beside the Vault's own resolver, which is left untouched (to be folded together later, as PLAN-37 says).
- `routes_platform.py`: every search block now ANDs the scope in SQL (before LIMIT). Related Items: the entity must be visible or the answer is `[]`; only visible records are listed (no title, id or count for the rest; links to kinds the registry cannot check are not listed, they used to show as "(deleted)"); create answers one uniform 404 for missing and out-of-reach records on either end; create and remove are now audited (`link_create`, `link_delete`, ids only, no titles).
- GREEN: `tests/test_entity_scope.py` 24 passed; search, Vault search and ARIA scope tests still pass.
- Not changed: who may create or delete a link still follows creator-or-admin; a read-only role can still create links between records it can see (Slice 2c of PLAN-37 owns link permissions). The Related Items picker lists evidence as platform/evidence while the link API knows evidence/item, so evidence cannot be linked from the picker (pre-existing).

2026-10-08, A3 (vendor cross-module views).

- RED: with a BCM-only employee, `get_cross_module_profile` returned all three sections, including the Sentinel `ai_assessment` and the GRID findings; the platform vendor directory and `/api/vendors/{id}/profile` need only a sign-in.
- `core/vendor_link.py`: both functions now take the user (required, so no caller can forget). A section is read only when the user holds that module's vendor capability (`sentinel.vendor.manage`, `grid.vendor.manage`, `module.bcm.access`); flags that depend on a hidden section are dropped instead of guessed, because a hidden record would otherwise read as "no audit exists". The four callers pass `request.state.user`.
- GREEN: `tests/test_vendor_profile_scope.py` (profile, flags, directory, and the four routes) and `test_canonical_vendor.py`.
- Seen, not changed: `POST /api/vendors/directory` (create a canonical vendor) needs only a sign-in.

2026-10-08, C (Ask ARIA page header count).

- RED: a unit A user's Ask page showed 3 indexed chunks when 1 was theirs (the count read the whole table). New `ask_service.indexed_count(user)` counts under the same scope the search applies, after `init_index()` so a tenant with no table yet reads its own empty one instead of falling through to `public`'s. The page uses it. Test in `tests/test_aria_ask_scoping.py` drives `ask_page` itself.

2026-10-08, D1 (Vault changes rescore controls).

- Finding while reading: no code anywhere creates an `evidence_links` row with `entity_type = 'canonical_control'` (the Vault link API only accepts the resolver kinds; GRID, ARIA, BCM and the event handlers write module specific control types). The two evidence factors of the effectiveness score (20 + 15 of 100 points) read only that type, so through the product a control can never earn them. That is a scoring-design question, not fixed here (see "Open questions").
- Implemented anyway, as specified, for any such links that do exist (older data, scripts): unlink, archive, bulk archive, permanent delete and an edit of status or expiry now rescore the controls the change touched, after the change has committed, on a fresh connection; a failure is logged and never fails or undoes the user's action. `tests/test_vault_rescores_controls.py` (7 tests): RED 5 failed on today's code (stored score stayed 45), GREEN 7 passed.
- Not hooked: uploading a new version (it supersedes the old item but does not copy its links to the new one, so the control loses its evidence either way; part of the design question above).

2026-10-08, D2 (GRID re-attach).

- Decision: the Vault unlinking an item does NOT delete the GRID record that refers to it (that row can carry approvals and drives the control status); instead attaching again now repairs the link. Fix in `attach_vault_item_to_grid_control`: an existing attachment is reused but the live-link check now runs for it too, and the control status is only recalculated when a new record was created.
- Found and fixed in the same function: the "already attached" check matched `vault_evidence_id=1` as a prefix of `vault_evidence_id=12`, so attaching item 1 to a control that already carried item 12 silently did nothing. The marker now includes its trailing comma.
- `tests/test_grid_vault_attach.py`: RED 2 failed (no restored link; item 1 returned item 12's record), GREEN 3 passed together with allen's removed-link tests.

2026-10-08, B (case sensitive search boxes).

- Triage of the "39 plain LIKE lines": only places where a person types free text needed the fix (15 lines in 5 files). The rest stay as they are on purpose: LIKE on system generated markers (tags such as `aria_doc_id=...`, `vault_evidence_id=...` in notes, task titles), constant patterns (`'%grid%'`, `'%%auto%%'`), module keys, dropdown filters (mime type, framework) and the exact CSV membership test on control refs. Those never depend on what a user types.
- Converted to `ci_like` / `like_pattern` (case insensitive, `%`, `_` and `!` literal, capped at 200 characters): Sentinel RoPA, DPIA, AIIA, breaches, DSR, vendors, consent, policies, training (9); ARIA control search and document search (2); audit log action and user filters (2); ERM risk statement tags (1); BCM document chunk search (1).
- Tests first: `tests/test_list_searches_ignore_case.py` (14 tests, SQLite switched to `case_sensitive_like` so plain LIKE behaves like PostgreSQL): RED 14 failed, GREEN 14 passed.
- Found by the audit log test and fixed: the module dropdown query of `/admin/api/logs` reused the filter SQL without the `users` join, so filtering the log by user raised an error on both engines (it still would on PostgreSQL: missing FROM-clause entry for table "u").

2026-10-08, E (swallowed database errors).

- Re-ran the audit with an AST scan (the earlier count was 58 sites in modules and core). Excluding `database.py` (its migrations deliberately run "add this column" statements that fail when it already exists) and `main.py`'s one startup migration: 65 broad handlers swallowed a database error with no trace. 88 others already logged.
- New `core/best_effort.py`: `swallowed(where)` logs the current exception at WARNING with its traceback; `attempt(db, where)` runs one optional database step in a savepoint so its failure undoes only itself; `is_missing_relation(exc)` is true only for "table or column does not exist" (PostgreSQL 42P01 and 42703, SQLite "no such table/column").
- 58 handlers got a `swallowed(...)` line (behaviour unchanged, now visible): 16 dashboard widgets, ARIA stats, the settings lookups, MFA backup code check, event bookkeeping, schedulers (including the integrity-failure and missing-file alerts to admins, which used to vanish if the notification insert failed), and others. Two savepoint loops (readiness rules, bulk actions) log too.
- Behaviour fixes where silence was hiding damage:
  - `delete_business_unit` and `delete_department` skipped a reference check on ANY error, so a lock timeout let the delete go ahead and left orphans. They now skip only a table or column that is absent (`is_missing_relation`) and raise otherwise. `tests/test_governance_delete_guards.py`: RED 2 failed, GREEN 5 passed.
  - `delete_org_user` (super admin) ran about 30 optional clean-up statements, each wrapped in `except: pass`. On PostgreSQL the first one that failed rolled the whole transaction back, silently undoing the reassignments made before it, and the final DELETE then hit a foreign key. Each step now runs in a savepoint via `attempt`. Real PostgreSQL: RED `ForeignKeyViolation ... events_created_by_fkey` when one table is missing from the schema, GREEN with the fix.
- Guard: `tests/test_no_silent_database_swallows.py` fails when any broad handler around a database call neither logs, rolls back nor re-raises (RED: 63 offenders listed, GREEN: none). `tests/test_best_effort.py` covers the helper (7 tests).
- Not changed on purpose: where a tolerated failure sits inside a larger transaction on PostgreSQL and is NOT wrapped in a savepoint (most dashboard and settings reads, which write nothing), the wrapper still rolls back what was pending; those paths hold no earlier writes. The control effectiveness engine (`recompute_controls_by_ids`) is the one loop where that could matter; it now logs when a factor query fails, and its callers use fresh connections.

2026-10-08, F (row level security with an ordinary role).

- The lane's `postgres` user is a superuser, which bypasses RLS, so every earlier test could only check session settings. Three new real-PG tests `SET ROLE` to a NOSUPERUSER NOBYPASSRLS role: policies filter evidence rows by organization (org A sees A, org B sees B, the super admin flag and the bypass connection see both); a write for another organization is rejected; the organization scope survives a failed statement and does not reach the next borrower of the pooled connection.
- The survival test first passed against the ORIGINAL wrapper too, because `SET ROLE` plus a commit made the scope durable. Restructured so the scope is still uncommitted when the statement fails: GREEN on the fixed wrapper, RED on the original (`still scoped to the organization after the failure`: the ordinary role then sees nothing).
- Still true: nothing here proves the production role has those attributes; that is the one-line check on the VPS.

## Second round (2026-10-08, "continue with what you recommend")

- **Vendor directory write permission.** `POST /api/vendors/directory` (create a canonical vendor, or overwrite the contact details, services and risk level of an existing one) needed only a sign-in. It now needs `sentinel.vendor.manage`, `grid.vendor.manage` or `bcm.vendor.manage` (super admin, DPO, audit lead, BCM manager), and the Add Vendor button is only shown to those roles (`can_add_vendor`). RED: 5 other roles could write; GREEN: `tests/test_vendor_directory_permissions.py` (13 tests). Reading the directory is unchanged.
- **MFA backup codes spent once.** `core/mfa.py verify_code` read the stored list, checked the presented code and wrote the list back without it; two concurrent requests both passed. The write is now a compare and set (`WHERE id = ... AND backup_codes = <the list that was read>`) and succeeds only when exactly one row changed. RED: with a competing request squeezed between the check and the write both logins succeeded; GREEN on SQLite (`tests/test_mfa_backup_code_single_use.py`) and on real PostgreSQL.
- Left alone on purpose: link write permissions for Related Items, the evidence picker mismatch, links on new Vault versions, and the effectiveness evidence factors. Each needs a product decision rather than a code fix.

## Open questions and new findings (not fixed: each needs a decision or is outside the list)

1. **Control effectiveness evidence factors cannot be earned.** The score gives 20 + 15 points for live, current, unexpired evidence linked with `entity_type = 'canonical_control'`. Nothing in the product creates such a link (the Vault accepts only its resolver kinds; GRID links `grid/control` and `grid/audit`; ARIA, BCM and the event handlers link their own types). Counting evidence on the module controls that map to a canonical control (for example `grid_controls.canonical_control_id`) would fix it, but it moves every score up by as much as 35 points and lowers ERM residual risk across the board, so it is a product decision, not a bug fix.
2. ~~`POST /api/vendors/directory` for any signed-in user~~ Done in the second round (below).
3. ~~MFA backup codes could be spent twice by concurrent requests~~ Done in the second round (below).
4. Related Items: a read-only role can create links between records it can see (needs a write capability per kind); the picker lists evidence as `platform/evidence` while the link API knows `evidence/item`; a new Vault version does not inherit its predecessor's links; the three linkable-type registries (Vault, Related Items, `core/links.py`) are still separate (PLAN-37 Slice 1).
5. `grid.data_service.delete_evidence_file` deletes Vault items whose tags contain `grid_evidence_id=<id>`; worth reviewing before anyone relies on it.
6. Search stops at 30 results overall (not changed).

## Verification (2026-10-08, repo venv, from `oneforall/`)

Final run after the second round (vendor directory permission and MFA single use):

- Backend, SQLite plus the real-PG lane on PostgreSQL 18.6 (`pytest tests --ignore=tests/ui`): **1110 passed, 0 failed, 0 skipped** in 19m12s (1008 before the follow-up rounds).
- Browser suite (`pytest tests/ui`): **411 passed, 2 skipped, 0 failed** in 23m06s. The two skips are the same intentional ones as before.
- Throwaway containers removed.
- New test files this work added (collected counts): `test_entity_scope.py` 24, `test_vendor_profile_scope.py` 13, `test_vendor_directory_permissions.py` 13, `test_vault_rescores_controls.py` 7, `test_grid_vault_attach.py` 3, `test_list_searches_ignore_case.py` 14, `test_best_effort.py` 7, `test_governance_delete_guards.py` 5, `test_no_silent_database_swallows.py` 1, `test_super_admin_user_delete.py` 3, `test_mfa_backup_code_single_use.py` 2, one more in `test_aria_ask_scoping.py` (21 in the file), and ten in `test_postgres_init.py` (user deletion, scoped search and Related Items, Ask page count, list searches, Vault rescoring with GRID re-attach, backup codes, three ordinary-role RLS tests, `rebuild_index`).
- Not verified: the production VPS (role attributes, data). Not done by design: nothing pushed or deployed.
