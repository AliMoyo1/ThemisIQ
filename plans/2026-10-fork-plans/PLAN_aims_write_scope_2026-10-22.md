# Operations Risk AI management (AIMS): close the cross unit hole in the write routes

Started 2026-10-22 (CAT). Origin: open item O5 of `PLAN_report_exports_2026-10-21.md` (branch `claude/sad-albattani-5255ea`, uncommitted when this was written).

## The hole

In `oneforall/modules/orm/routes.py` the AIMS routes that change data accepted any id with no business unit check:
`api_aims_update`, `api_aims_delete`, `api_aims_risk_create`, `api_aims_risk_update`, `api_aims_risk_delete`,
`api_aims_risk_control_create`, `api_aims_risk_control_update`, `api_aims_risk_control_delete`.
A risk owner in unit A (capability `orm.event.manage`) could edit or delete unit B's assessment, a risk in it, or a control link on that risk, by id.
The assessment list (`api_aims_list`) was already unit scoped. The five reads (`api_aims_get`, `api_aims_risks_list`, `api_aims_risk_get`,
`api_aims_aggregation`, `api_aims_aggregation_csv`) were fixed on the exports branch only, so on this branch they were open too.

## Decisions (from the brief where it was explicit, otherwise taken here; chat confirmation, not sign-off)

1. One rule for reads and writes: the assessment's unit, through `entity_scope_sql(("orm", "aims"), user, "a")` (the brief). A NULL unit is organization wide and open to
   every unit's managers, exactly as in the list. A risk and a control link have no unit column, so they follow their assessment.
   Why: one definition, the one the list and search already use. Cost: none. To change: the SQL in `_aims_in_scope_or_404`.
2. 404, never 403 (the brief), and a missing id answers exactly like another unit's id: same status and same body, on every route, reads included (taken here).
   Why: the answer must not confirm that another unit's row exists. How: a missing risk or link resolves to no assessment (`None`), so it takes the same
   path as a foreign one. This is stricter than the exports branch, whose `api_aims_risk_get` answers "Not Found" for a missing risk and
   "Assessment not found" for a foreign one. To change: make `_aims_risk_in_scope_or_404` load the risk first.
3. The guard runs before the body is read and before any data layer call, so a refused request changes nothing (the brief asks for no change on a 404).
4. The unit rule of `api_aims_create` is kept as it is (the brief): the unit comes from the body (`business_unit_id`), none when the body has none. The Operations Risk
   page sends none, so an assessment made in the page is organization wide. The create routes for a risk and a link add a row under an assessment the caller has just
   been shown to be able to open, so the new row sits in that assessment's unit. There is no other place to file them. (The brief expected `api_aims_create` to file in the
   caller's unit; it does not. Decision 6 is the check added on top of that rule, with the owner's go-ahead.)
5. `_aims_in_scope_or_404` is copied word for word from the exports branch so that the two branches meet cleanly when merged (the brief).
6. The unit a body names on `api_aims_create` and `api_aims_update` is checked (the owner's go-ahead, by button, after the first round: "add the business unit check ... Sentinel's
   rule, 400 for a unit outside the caller's"). Helper `_check_aims_unit`, ported from `_check_references` in `modules/sentinel/routes.py`: a unit the writer cannot open is a 400
   ("Choose a business unit you belong to"); the number may arrive as text and is stored as a number; only an administrator may take an assessment out of its unit (a 400 for
   anyone else who sends none or an empty value on an assessment that has a unit). A body that names no unit changes nothing, so the page keeps filing organization wide and
   the default rule of decision 4 is untouched. It runs after the existence rule, so a bad unit on another unit's assessment is the same 404 as any other write to it.
   Stricter than Sentinel in three places, on purpose: only positive whole numbers are units (Sentinel would store -1, the marker `bu_scope_ids` uses for "no unit", for a person with
   no unit; `true` and `1.5` would become unit 1); the administrator's value is also checked to be a number (on PostgreSQL "abc" was a 500); an empty value becomes none (on
   PostgreSQL "" was a 500). Cost: a client that sent a unit it cannot open now gets a 400 instead of planting a row. To change: `_check_aims_unit`.

## Files

- `oneforall/modules/orm/routes.py`: the guard helpers and a guard line on 13 routes; `_check_aims_unit` on create and edit of an assessment.
- `oneforall/modules/orm/data_service.py`: `get_aims_risk_assessment_id`, `get_aims_link_assessment_id` (read only lookups of the parent).
- `oneforall/tests/test_aims_write_scope.py`: new, 26 cases (19 for the guards, 7 for the unit a body names; the log has the counts that ran).

## Change log

- [done] `routes.py`: `_aims_in_scope_or_404` added (same text and same place as on the exports branch, above the aggregation routes).
- [done] `routes.py`: guard on `api_aims_get`, `api_aims_risks_list`, `api_aims_aggregation`, `api_aims_aggregation_csv` (the same single line as the exports branch).
- [done] `routes.py`: `api_aims_risk_get` guards before loading (differs from the exports branch on purpose, decision 2).
- [done] `routes.py`: `_aims_risk_in_scope_or_404` and `_aims_link_in_scope_or_404`, and a guard as the first statement of the eight write routes.
- [done] `data_service.py`: the two parent lookups.
- [done] `tests/test_aims_write_scope.py`: written first, then run against the saved pre-fix `routes.py` (see the log).
- [done] `scripts/capability_inventory.py --check`: passes (no route added, removed or re-gated).
- [done] Round 2 (owner's go-ahead, decision 6) `routes.py`: `_check_aims_unit` added above `api_aims_create`; called in `api_aims_create` before `created_by` is set and in
  `api_aims_update` after the existence rule and the body read, before the data layer call.
- [done] Round 2 `tests/test_aims_write_scope.py`: 7 cases added (filing under a unit the writer cannot open, the page's way unchanged, moving inside the writer's units, only an
  administrator widens, a person with no unit, the administrator's value, the unit rule after the existence rule); docstring says so.

## Verification log

All times CAT, 2026-10-22. Every pytest session ran from `oneforall/` with the repo venv python, one at a time, the backend files and `tests/ui` as separate sessions.

- About 10:08 `python scripts/capability_inventory.py --check`: "Capability inventory matches registered routes and reviewed annotations." (exit 0; no route added, removed or re-gated).
- About 10:10 Real PostgreSQL 18.6 (own container `themisiq-pg-aims-scope`, 127.0.0.1:55437, database `themisiq_test_aims`, removed afterwards). One script, not the repository's
  PostgreSQL lane (`tests/test_postgres_init.py` is not run: no schema, row level security or migration code changed). It seeds units A, A1 (under A) and B, one assessment
  with a risk and a link in each of A, A1, B and organization wide, six risk owners and a DPO, and drives the real router with the same matrix as the new test file:
  351 checks, 0 failed. The scope SQL it printed is the same as on SQLite (`(a.business_unit_id IS NULL OR a.business_unit_id IN (%s,%s))` for a unit A owner,
  `(1 = 1)` for the administrator, `(1 = 0)` for an organization without the Operations Risk licence). Ids that cannot exist (99999999999999999999999, 2147483648, 0, -1)
  answer 404 on every route, not an error. Negative control, the same script against the saved pre-fix `routes.py`: 186 of 351 checks fail (a unit A owner edits, files under
  and deletes unit B's assessment, risks and links, and the tables change).
- 10:21 Tests fail on the old behaviour. `tests/test_aims_write_scope.py` run from `oneforall/` with the repo venv python against the genuine pre-fix `modules/orm/routes.py`
  (saved from git HEAD bfde22d6 and loaded in place of `modules.orm.routes` by a throwaway pytest plugin, so nothing in the repository was touched): 10 failed, 9 passed.
  The 10 are the 4 "no write route reaches another unit" cases, the 4 read cases for the confined personas, "a missing id answers like another unit's" and
  "no Operations Risk licence"; the 9 that pass are the positive twins (own places for 5 personas, the administrator's reads), the two refused-role cases and the
  re-parenting guard, which hold before and after.
- 10:22 Same file against the fix: 19 passed in 30 s.
- 10:30 The neighbouring backend files (`test_aims_engine`, `test_entity_scope`, `test_relationships`, `test_platform_ownership`, `test_platform_ownership_surfaces`,
  `test_no_duplicate_routes`, `test_vendor_profile_scope`, `test_change_signals`, `test_ai_declarations`, `test_template_compilation`): 337 passed in 7 min 38 s.
- 10:30 to 11:17 Full backend suite (`pytest tests --ignore=tests/ui`, repo venv python, from `oneforall/`, one session): 2688 passed, 75 skipped, 0 failed, 47 min 2 s.
  The 75 skips are the real PostgreSQL lane tests (no `TEST_DATABASE_URL`; none of them touches this change, which has no schema, row level security or migration code).
- 11:17 to 11:52 Browser suite (`pytest tests/ui`, a separate session): 554 passed, 2 skipped, 6 failed, 35 min 37 s. The six failures are
  `tests/ui/test_aria_managed_edit.py` (2 tests: `test_managed_document_edit_sends_metadata_only_and_preserves_lifecycle`, `test_legacy_document_edit_still_sends_lifecycle_fields`),
  `tests/ui/test_workflow_sla_comm_scope.py::test_communication_template_stays_with_creator_organization` and `tests/ui/test_workflow_tenant_scope.py` (3 tests: other organization,
  invalid steps, next step rollback; they get 403 where 404, 400 and 201 are expected). They are the same six that the report exports ledger records on an unmodified checkout of
  this base commit (bfde22d6), and they call workflow and ARIA routes, not Operations Risk. I did NOT rerun them myself on a clean copy of the base: I exported one
  (`git archive HEAD oneforall`) and queued the three files, but other sessions kept two or three pytest runs going from 14:42 and the machine never went idle, so I stopped
  waiting. The match is by test name and failure signature (403 where 404, 400 and 201 are expected), not by my own run.
- Checked after the runs: `modules/orm/routes.py`, `modules/orm/data_service.py` and the new test file were last written at 10:04, 10:04 and 10:12, before every run above.
  Round 1 ends here. Round 2 (decision 6) changed `routes.py` and the test file again, so the runs above do not cover it; its own runs follow.
- Round 2, about 15:10 Real PostgreSQL 18.6 again (own container, 127.0.0.1:55437, removed afterwards), the same script with a section added for the unit a body names:
  383 checks, 0 failed. The same script against the routes as they were after round 1, without `_check_aims_unit`: 23 of 383 fail. Three of those are real PostgreSQL
  failures the old code produced as HTTP 500: a unit of "abc", of `true` and of a list, and an empty string, which PostgreSQL refuses for an integer column. The rest are the
  planting cases (a unit A owner creating under unit B, a person with no unit creating under -1, 0 or 1.5, moving an assessment to B, widening one to organization wide).
- Round 2, 15:20 Tests fail on the old behaviour. `tests/test_aims_write_scope.py` against the routes as they were after round 1 (saved copy loaded in place of
  `modules.orm.routes` by the same throwaway plugin; it refuses to run if the file has `_check_aims_unit`): 6 failed, 20 passed. The 6 are the unit-rule cases (filing under a
  unit the writer cannot open; the page's way, which fails there because an empty `business_unit_id` was stored as an empty string instead of none; moving; widening; a person
  with no unit; the administrator's value). The 20 that pass are the 19 round 1 cases and the existence-before-unit case, which hold before and after.
- Round 2, 15:21 Same file against the final routes: 26 passed in 42 s.
- Round 2, 15:21 to 15:32 The neighbouring files again, plus `tests/test_sentinel_write_scope.py` (the rule that was ported): 410 passed in 11 min 6 s.
- Round 2, 15:33 to 16:16 Full backend suite again (`pytest tests --ignore=tests/ui`, one session): 2695 passed, 75 skipped, 0 failed, 43 min 45 s (2688 of round 1 plus the 7 new cases).
- Round 2 browser suite: NOT rerun. Round 2 changes only `api_aims_create` and `api_aims_update` and no template or script, and no browser test creates or edits an assessment
  (the only browser tests that name AIMS render the page's list). The page's own requests (title, mode, status and evaluation date, never a unit) are reproduced in the
  backend tests; I did not click through the page.
- Checked after the round 2 runs: `routes.py` and the test file were last written at 15:11 and 15:12, `data_service.py` at 10:04, before every round 2 run.
- Cleanup: both throwaway PostgreSQL containers were removed after their runs.

## Open items, not done here

- O1 CLOSED in round 2 (decision 6). `api_aims_create` and `api_aims_update` took `business_unit_id` from the body without checking it against the caller's units, so a
  manager could file or move an assessment into a unit they cannot see. The page never sends the field. Kept out of round 1 because the brief said to keep the create rule;
  done on the owner's go-ahead.
- O2 The AI controls catalogue routes (`api_ai_control_create`, `_update`, `_delete`, `_get`, `_list`) have no unit check, although the entity registry gives the kind a unit
  column. Either the catalogue is a shared library (then the registry entry is misleading) or custom controls are meant to be private to a unit.
- O3 The report exports branch has its own copy of the five read guards. A simulated three-way merge (`git merge-file`, base = HEAD, the two working copies of
  `modules/orm/routes.py` normalized to LF) gives exactly one conflict: the import lines of the CSV route (take the exports branch's lines; the guard line below them is
  identical on both sides and merges once; re-run after round 2, same result, and `_check_aims_unit` is a single definition too). `_aims_in_scope_or_404` merges as a
  single definition. `api_aims_risk_get` merges without a conflict but with two guards
  (this branch's before the load, the exports branch's after it): delete the exports branch's line `_aims_in_scope_or_404(request, r["assessment_id"])`.
- O4 The user asked (twice, in this session) that reports link to other relevant documentation, through the Evidence Vault. That belongs to the report exports program:
  it was sent to that session as a message (queued; whether it was delivered across the app restart is not confirmed) and is repeated in this session's final report, and the
  groundwork is in the shared notes folder (`reports-link-related-documentation.md`). Nothing built here.

## Status: COMPLETE for the eight write routes, the five reads and the unit a body names (O1 closed); O2 to O4 are open and need the owner.

Nothing is committed or pushed (the brief said not to). Changed: `oneforall/modules/orm/routes.py`, `oneforall/modules/orm/data_service.py`; new: `oneforall/tests/test_aims_write_scope.py`
and this file.
