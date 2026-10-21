# Evidence Vault Phase 1a: correct data layer

Status: implemented and verified locally on 2026-10-07. The PostgreSQL lane has since been run on a real PostgreSQL 18.6 (2026-10-08, see PLAN_integrate_parallel_chat_changes.md). Parent plan: [PLAN.md](PLAN.md). Committed on the local branch `claude/pg-layer-scope-and-findings` on 2026-10-08; not pushed or deployed.

## Goal

Make the Vault's data layer correct before the Phase 1b redesign. One scope rule shared by every read path, a paginated list, search that works on PostgreSQL, removed links and superseded versions no longer counted as live, and the broken evidence bulk import fixed. No visual redesign: the only UI change is a "Showing X to Y of N" pager.

## Why this comes first

Verified on 2026-10-07 (HEAD eec119f), four of these by running a throwaway script on SQLite and the rest by reading the code:

1. Removed links still count as links in the list, the Unlinked view and stats.
2. The business unit boundary is applied in the list and in single item lookups only. Stats "recently added", topbar search, the GRID and BCM pickers, and the entity evidence panels ignore it.
3. "All evidence" mixes superseded versions with current ones.
4. Evidence bulk import inserts into a column that does not exist and never sets org_id.
5. Search is a plain `LIKE`, which is case sensitive on PostgreSQL (production).
6. Coverage percentages count expired and superseded evidence (decision deferred, see below).

## Decisions

| Decision | Reason |
| --- | --- |
| One predicate, `evidence_scope_sql(user, alias)` in `modules/evidence/scope.py`, shaped like `document_scope_sql` in `modules/aria/policy_access.py` | The org and BU rule was hand copied into about six places, which is why they drifted. `_scoped_evidence_item` is rebuilt on it so a single item and the list cannot disagree. |
| Fail closed: a user who is not a super admin and has no org sees nothing | Same as the existing `_scoped_evidence_item`. A NULL business unit means organization wide. |
| Search is `LOWER(col) LIKE LOWER(?) ESCAPE '!'` over title, file name, tags, description, with `%`, `_` and `!` escaped | Same behavior on SQLite and PostgreSQL, reuses the `LOWER()` form already used by search-entities, and is testable without PostgreSQL. Full text search stays in Phase 3. |
| One response shape for `GET /evidence/api/items`: `{items, total, page, page_size, pages}` | Every consumer is in this repo (Vault page, campaigns picker, three test files) and is updated together. Avoids keeping a 200 row legacy mode. Page sizes 25 and 50 only. Stable order `updated_at DESC, id DESC`. |
| Default list excludes `archived` and `superseded`; `view=superseded` and `view=archived` show them | PLAN.md section 7. Superseded rows stay reachable from the version panel. No new nav entry until 1b. |
| A link counts only when `deleted_at IS NULL`, in every Vault read path | Unlinking is a soft delete. |
| The coverage definition is not changed | Whether expired or superseded evidence counts as coverage is a product decision for Phase 0. Only the scope rule is unified. |
| No schema change, no new index | Nothing in 1a needs one. Measure on the VPS first. |
| Not committed or pushed | Standing rule: commit and push only on explicit instruction. |

## Tasks

- [x] T1 `modules/evidence/scope.py` with `evidence_scope_sql` and `evidence_search_sql`, plus unit tests
- [x] T2 Evidence routes: rebuild `_scoped_evidence_item`; list (scope, search, pagination, superseded, live links); stats; coverage; `/api/linked`; `/api/auto`
- [x] T3 Topbar global search: evidence block uses the shared predicates
- [x] T4 GRID `list_vault_evidence`, `search_vault_for_evidence` and BCM `search_vault_items` take the user and use the shared predicates
- [x] T5 Evidence bulk import: valid columns, org_id, uploader
- [x] T6 Vault page pager, campaigns picker, and the three existing tests that read the list response
- [x] T7 Static guard: evidence search outside the helper fails the suite
- [x] T8 PostgreSQL gated test (runs only with TEST_DATABASE_URL); written, not executed here
- [x] T9 Verification: py_compile, new tests, evidence and axe browser tests, full backend suite, full browser suite, live browser pass, security review of the diff (see the record below)

## Acceptance gates (from PLAN.md section 9, narrowed to 1a)

- Every item is reachable beyond row 200 (browser test with 230 items).
- Stats total equals the default list total for a super admin and for a BU scoped user.
- No out of scope row in the list, stats recently added, topbar search, GRID picker, BCM picker, `/api/linked` or `/api/auto`.
- Search matches regardless of case; `%` and `_` in a query are literal.
- A removed link is not counted by the list, Unlinked view, stats, module filter or entity panels.
- py_compile clean; changed areas pass; full suite result reported with any known flakes named.

## Out of scope: found while verifying, not fixed here

Three of these were handed off as separate follow-up tasks (marked).

- Soft deleted links are also counted outside the Vault: `modules/governance/effectiveness.py` (two queries, feeds control effectiveness scores), `modules/erm/data_service.py` `list_risk_controls`, `modules/aria/routes.py` (two evidence count queries), `modules/bcm/routes.py` (two evidence list queries). Follow-up task spawned.
- Topbar search for every other module uses a plain `LIKE` (case sensitive on PostgreSQL). Follow-up task spawned.
- Ask ARIA passes control and risk chunks through without a scope check and has no org column on its index. Follow-up task spawned (verify first, then fix).
- uvicorn access logging is on by default, so GET search terms are logged.
- `tests/test_webhook_test_endpoint.py` has an intermittent Windows connection reset (mock handler never reads the request body).
- The upload route's duplicate check (`api_evidence_upload`) scopes by org only, so a hash match in another business unit answers 409 with that item's title and id. Low severity (the caller must already hold the identical file) but it is the same class as the business unit leaks fixed here; needs a product decision on what a user should see.
- Upload creates items with no business unit, so the business unit rule only ever filters rows created by other modules (BCM, ARIA, GRID, event handlers).

## Verification record

All runs used the repo `.venv` (Python 3.12.14, Playwright 1.63.0) on 2026-10-07.

| Check | Result |
| --- | --- |
| `py_compile` on every changed Python file | Clean |
| Backend suite, `pytest tests --ignore=tests/ui` | 928 passed, 16 skipped (the PostgreSQL lane), 0 failed |
| Browser suite, `pytest tests/ui` (real Chromium) | 411 passed, 2 skipped (a login action that is meant to be reachable logged out; a fixture with no document rows), 0 failed |
| New tests | 36 backend (12 scope, 22 read paths, 2 guard) and 2 browser (pager, campaigns picker) pass; the PostgreSQL test is skipped here |
| Red checks | 21 of 22 read-path tests fail on an export of HEAD; the guard flags exactly the five old copies there; the picker test fails with the old picker template |
| Live browser pass | Throwaway app and database, synthetic user, 230 items: stats total equals list total; other unit's item and superseded row absent from list, stats, recent strip and topbar search; superseded reachable by `view=superseded`; case-insensitive match; `%` literal; page clamped; paging by mouse; layout checked at desktop and 375 px |
| Security read of the diff | Every user value is a bound parameter; the only text spliced into SQL is fixed fragments from `scope.py`, and its alias argument must be a plain identifier; page size is limited to 25 or 50 and the search term to 200 characters; scope fails closed; no new routes; pager text is set with `textContent`; no new secrets or logging of search terms |
| PostgreSQL | **Not run.** `psql` is absent, `TEST_DATABASE_URL` is unset and the Docker daemon is off. The test `test_evidence_vault_search_and_scope_run_on_real_postgres` exists but has never executed; run it before release |

One flaky run to know about: a broader browser run taken while the backend suite was also running showed two axe color-contrast failures (`/tasks`, `/erm/register`). Both pass alone on this tree and on the untouched HEAD export, and the final full run on an idle machine passed everything, so they are load flakes of the kind already documented for this suite, not a regression.

## Change log

2026-10-07, T1 to T5 (backend). All working tree only.

| File | Change |
| --- | --- |
| `modules/evidence/scope.py` (new) | `evidence_scope_sql`, `current_library_sql`, `like_pattern`, `evidence_search_sql`. Alias arguments must be plain identifiers. |
| `modules/evidence/routes.py` | `_scoped_evidence_item` now runs the shared predicate. `GET /api/items` returns `{items, total, page, page_size, pages}`, sizes 25 or 50, order `updated_at DESC, id DESC`, `view=superseded` added, default hides archived and superseded, links counted only when live. Stats, coverage, `/api/linked` and `/api/auto` use the shared predicate and live links only. `/api/linked` answers 400 for a non-integer `entity_id` (was a 500). |
| `modules/launcher/routes_platform.py` | Topbar search evidence block uses the shared predicates (now also hides archived and superseded, ordered newest first). Evidence bulk import: `created_by` replaced by `uploaded_by`, `org_id` set, 403 for a non-super-admin with no org. Added the missing `log` (the error handler raised NameError, so any failed import was an unhandled 500). |
| `modules/grid/data_service.py`, `modules/grid/routes.py` | `list_vault_evidence(user, ...)` and `search_vault_for_evidence(user, names)`; blank names match nothing (was: everything). |
| `modules/bcm/data_service.py`, `modules/bcm/routes.py` | `search_vault_items(user, query)`; now searches filename and description instead of category text, same as every other Vault search. |
| `tests/test_evidence_scope.py` (new) | 12 tests for the predicates. |
| `tests/test_evidence_vault_reads.py` (new) | 22 tests across list, pagination, stats, entity panels, topbar search, pickers and bulk import. |

Behavior changes worth knowing: stats `total_links` now counts live links on current library items (a super admin used to get every link row); entity evidence panels and the auto evidence endpoint now apply business unit scope as well as org.

Evidence: 34 new tests pass. Red check: the same 22 read-path tests run against an export of HEAD with no source changes fail 21 of 22 (only the coverage smoke test passes there).

2026-10-07, T6 to T8 (page, tests).

| File | Change |
| --- | --- |
| `modules/evidence/templates/evidence_index.html` | "Showing X to Y of N" pager with Previous and Next (`aria-disabled` rather than `disabled`, so keyboard focus is not lost at either end), `evPage` state reset to 1 by view, module, category, search, saved view and upload; envelope parsing; a malformed response shows an error toast instead of an empty list. Page size is left to the server default (25). |
| `modules/evidence_campaigns/templates/index.html` | Submit-evidence picker reads `found.items`. |
| `tests/ui/test_evidence_load_race.py`, `test_evidence_upload_error_detail.py`, `test_org_isolation.py` | Updated for the envelope. |
| `tests/ui/test_evidence_pagination.py` (new) | Real Chromium: 230 items, pages 1 to 10 by mouse and keyboard, last page shows the oldest item, new search resets to page 1 and hides the buttons when everything fits. |
| `tests/ui/test_evidence_campaign_picker.py` (new) | Real Chromium: the picker lists a matching item from the envelope. Red check: with the old picker template and the new API it shows only the first prompt and never lists matches. |
| `tests/test_evidence_search_is_scoped.py` (new) | Static guard: a function that LIKE-searches `evidence_items` by title, description or filename must call `evidence_scope_sql`. Red check against the HEAD export flags exactly the five old copies. Internal `tags LIKE marker` sync lookups are deliberately not flagged. |
| `tests/test_postgres_init.py` | `test_evidence_vault_search_and_scope_run_on_real_postgres`: shows plain `LIKE` misses "access review" on PostgreSQL while the shared search finds it, and runs the scope and paged SQL there. Skipped without `TEST_DATABASE_URL`. |

Found in the live browser pass (demo app on a throwaway database, desktop and 375 px wide) and fixed: the floating Themis help button sat over the right-aligned Next button at the bottom of the page and swallowed clicks, so the buttons now sit beside the status text on the left with 84 px of room beneath; and after clicking Next at the bottom of a long page the view stayed at the bottom, so it now scrolls back to the top of the list.

Two things learned while testing: the global Python on this laptop has no Playwright, so browser tests silently SKIP there; the project `.venv` (Python 3.12, Playwright 1.63) is the interpreter to use. And the first pager test run failed on a race of my own (the search box's 300 ms debounce reset the page); the test now waits for the filtered response.
