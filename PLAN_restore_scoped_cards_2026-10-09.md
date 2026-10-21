# Restore the zeroed cards and the platform risk register, with real ownership

Started 2026-10-09 on branch `claude/pg-layer-scope-and-findings` (base 15c0ba3). Nothing here is committed or pushed.

## Why

e3ddfad scoped the Command Centre, reports and unified risk register by business unit. Three tables had no
owner column, so for every role except the super administrator it returned zeros (SLA donut, active workflows,
appetite breaches, `sla_breaches`, `risks`, the report fields built on them) and hid the legacy platform risk
register (list, statistics, detail, topbar search). Its own follow-up says: "Add trustworthy business-unit
ownership to legacy platform risks and SLA/workflow records, then restore their restricted-user cards."

## What the code showed (facts, with where)

- `risk_register`, `sla_instances`, `workflow_instances` have no business unit column. `risk_register` has no
  org column either (the tenant schema isolates it). `sla_instances` and `workflow_instances` have `org_id`.
- Writers of `risk_register`: `core/event_handlers.py::_insert_risk` (ten automatic callers, each knows its
  source record), `POST /api/risks` (super administrator only since e3ddfad), bulk import in
  `routes_platform.py` (needs `platform.manage_users`), API v1 `POST /risks` (organization-wide key).
- Writers of the instance tables: `POST /api/workflows/instances`, `POST /api/sla/instances` (the form takes a
  module from a list, a FREE TEXT entity type and an optional id, none of it validated), and the event trigger
  `_auto_trigger_workflows`.
- `GET /api/workflows/instances`, `GET /api/sla/instances` and their actions are scoped by organization only,
  with no business unit and no capability. That is the tested contract (`tests/ui/test_workflow_*`).
- The ERM module's own dashboard, unified register, register stats and CSV export read `risk_register` (and the
  ERM risks) tenant wide. `erm/routes.py` documents the dashboard counters as "whole-tenant by design".
- `DELETE /erm/api/register-entry/{id}` deletes any platform risk row by id for any `erm.risk.manage` holder.
- `GET /api/bulk/export/{entity_type}` needs only a sign-in and dumps whole tables: `risk_register`,
  `aria_controls`, `evidence_items`, `sentinel_ropa`, `frameworks`. (Import needs `platform.manage_users`.)

## Decisions (defaults I chose; each is one line to change)

1. **Ownership is stored**, as a nullable `business_unit_id` on the three tables, not derived at read time.
   Deriving from the creator would move a record whenever its creator changes unit; SLA rows have no creator.
2. **Whose unit** (one function, `core/ownership.py::owner_unit`): the unit of the record the row is about when
   that record is a registered kind the actor can open (so a risk about a unit B breach belongs to unit B), else
   the unit of the person who created it, else none. "Found but organization wide" stays organization wide.
   A unit A user who names a unit B record they cannot open gets unit A, never B: nobody can plant a row in
   another unit's dashboard. The API never rejects a reference it cannot place (the form takes free text).
3. **NULL means organization wide**, the platform convention (`bcm_incidents`, `sentinel_dsr` precedent), so
   rows made by a super administrator or an organization-wide API key stay visible to everyone with the
   capability. Legacy rows that cannot be placed also stay NULL; the backfill logs how many.
4. **Backfill runs once per schema** (marker row in `settings`), at startup with the column migration, for the
   public schema and every tenant schema, before any request can read the new scope. It must not run again:
   re-running would hand rows to a user who has since changed unit.
5. **Who sees what**: platform risks need `erm.risk.view` plus the unit rule (same as ERM risks). SLA clocks and
   workflow instances need only a sign-in plus the unit rule and the organization (same as tasks today).
6. **Writes stay as e3ddfad left them**: create, update, close of platform risks are super administrator only.
   The "+ New Risk" button is hidden for everyone else (it posted into a 403 and failed silently).
7. **Restricted `risk_counts` = platform (scoped) + ERM (scoped)**, i.e. exactly the figures on `/risk-register`,
   so the widget and the page it opens cannot disagree. The super administrator's widget (platform only) is the
   legacy definition and is not changed here.
8. **Appetite breaches** need no new data: thresholds are organization configuration, the breach count is over
   the ERM risks the viewer can see.

## Out of scope on purpose (reported, not changed)

- Business-unit scoping of the Workflows module's own list/detail/action APIs. Approvals are assigned by role
  across the whole organization, so scoping them changes who can act; that is a product decision.
- The ERM module's tenant-wide dashboard, unified register and CSV export (`/erm/api/export/csv` exports every
  ERM risk, ignoring the unit rule the list route applies).
- API v1 (organization-wide keys): rows it creates are organization wide, which is its access model.
- Analytics trends and predictive risk (still super administrator only until scoped history exists).

## Work items

- [ ] Registry: `table` on `_Kind`; kinds `("platform","sla")`, `("platform","workflow")`; `("platform","risk")`
      gets its unit column; drop the `(1 = 0)` rule.
- [ ] `core/ownership.py`: `record_unit`, `owner_unit`, `backfill`.
- [ ] Columns in `_COLUMN_MIGRATIONS`; backfill hooked into both alter runners (covers tenant schemas).
- [ ] Capture the unit on every writer (events, both start APIs, auto trigger, risk create, bulk import).
- [ ] `scoped_metrics.table_scope`: three tables, organization predicate for the two instance tables.
- [ ] Dashboard: SLA, workflow, appetite, overdue SLA rows, risk counts, `sla_breaches`, `risks`.
- [ ] Reports: `risk_report` merges platform rows for restricted users; SLA and brief fields follow the scope.
- [ ] Register: detail, hide "+ New Risk", search (free once the kind changes).
- [ ] Guards: ERM platform-risk delete respects the unit; bulk export needs `platform.manage_users`.
- [ ] Tests: SQLite, through-the-app, real PostgreSQL (migration in tenant schemas, backfill, cards); update the
      e3ddfad expectations that asserted the hidden state.
- [ ] Full backend suite, PG lane, browser suite, capability inventory check, duplicate-route guard.
- [ ] Memory and this log.

## Verification (final tree, 2026-10-09)

- Backend suite with the real PostgreSQL 18 lane on: 1311 passed, 0 skipped, 0 failed (16 min 24 s). Includes three new
  lane tests: columns and placement in public plus two tenant schemas (unit ids differ per schema so a wrong-schema
  lookup would be caught), a failing placement that must not stop startup and is retried, and the scope/cards/
  reports/detail queries on PostgreSQL.
- Browser suite: 414 passed, 2 intentional skips (the public login route, a chip-filter fixture with no document rows).
- `scripts/capability_inventory.py --check` matches; the duplicate-route guard is part of the backend suite;
  `git diff --check` is clean.
- Red first: every new behavior test failed for the stated reason before its code existed. The ERM delete guard was
  proved by switching it off (a unit A risk owner then deleted unit B's risk). The bulk export hole was reproduced at
  handler level (a DPO got 200 for all five tables). The business unit delete error was reproduced
  (`FOREIGN KEY constraint failed`).
- Screenshots from the real app on a throwaway database with two units: the Finance risk owner sees 9 met, 4 at risk,
  2 breached clocks and 5 open risks and none of Operations' 9 breached clocks or 6 critical risks.
- Not verified: an upgrade of a real production dump (only synthetic legacy rows, in SQLite and PostgreSQL); the
  production role is NOSUPERUSER and NOBYPASSRLS (the user's check, unchanged by this work).

## Reported, not changed

- Workflows module list, detail and action APIs: organization scope only (tested contract). A unit user can still list
  every SLA clock and workflow instance there. Scoping them touches who can act on approvals (actions are assigned by
  role across the organization), so it needs a product decision.
- ERM module: dashboard counters, unified register and register stats are tenant wide. The CSV export ignored the unit
  rule its own list route applies; FIXED in item 13 below. Still open, found by that session: `GET /erm/api/register`
  (`get_unified_register`) returns titles, descriptions, treatment and owners of both tables tenant wide to every
  `erm.risk.view` holder, the same leak as the export, so it is the one to fix next. Also tenant wide: the dashboard
  title blocks (`top_critical_risks`, `actions_required`, `posture.high_rrr`, `appetite_status[].top_risk`,
  `risk_feed`), the AI board report and chat inputs, and the dashboard's `business_unit_id` filter is not clamped to
  the caller's subtree. The "whole-tenant by design" comments are about the PLAN-26 posture filters, not business units,
  but one says "Do not fix this", so scoping the row content (not the counters) is the user's call.
- `delete_business_unit` did not check about 15 other tables that reference a unit (a 500 instead of a refusal);
  FIXED in item 13 below. Still unchecked: `users.business_unit_id` and 7 other columns with no declared foreign key.
- The super administrator's Risk Register widget and Risk Report count platform risks only, while the page they open
  (and now every restricted user's widget and report) count platform plus enterprise risks.
- `docs/generated/capability_inventory.md` lists the bulk export and import as "authenticated" because the generator
  does not read inline `has_capability` checks; both now need `platform.manage_users` in the handler.

## Deploy notes

- Nothing to run by hand. Startup (the FastAPI startup event, before any request is served) adds the three
  columns, then places existing rows once per schema (public and every tenant). Each schema logs one line:
  "Placed N platform risks, SLA clocks and workflow instances in a business unit; M left organization wide."
  Read M: those rows had no placeable record and no creator with a unit, so they are visible to everyone who may
  see platform risks (the platform convention for a NULL unit). A super administrator can place any of them with
  `PUT /api/risks/{id}` and a `business_unit_id` (platform risks only; there is no screen for it yet).
- Rollback is safe: the columns are nullable and unused by older code, which then falls back to the
  zeros e3ddfad shipped.
- `bu_scope_ids` runs one small query per scoped figure, as before; the restricted dashboard does about ten more
  of them now (SLA, workflows, platform risks, appetite). Not a concern at this size, worth a request-level cache
  if the dashboard ever shows up in a slow-query log.

## Change log

Each item below was written test first (the new test failed for the stated reason before the code existed).

1. **Registry** (`modules/governance/entity_scope.py`): `_Kind` gained `table`; every kind that has or follows a
   unit names it. `("platform","risk")` now has `business_unit_id` and the `(1 = 0)` rule for non-super is gone;
   new kinds `("platform","sla")` and `("platform","workflow")` (sign-in only, unit rule). `record_unit` and
   `owner_unit` are the one place that decides who owns a new row (aliases: non_conformance, enterprise_risk,
   policy; ids outside 1..2^31-1 are "unknown" so PostgreSQL never sees an out-of-range integer).
2. **Columns** (`database.py` `_COLUMN_MIGRATIONS`): `business_unit_id` on `risk_register`, `sla_instances`,
   `workflow_instances`. They ride the existing runners, so public and every tenant schema get them.
3. **Writers record the owner**: `_insert_risk` (ten automatic callers, no signature change),
   `_auto_trigger_workflows`, `POST /api/workflows/instances`, `POST /api/sla/instances`, `POST /api/risks`
   (an explicit `business_unit_id` must be an active unit, else 400; `PUT /api/risks/{id}` accepts it too, which is
   how a super administrator places a risk whose owner was never known). Bulk import and API v1 stay NULL: only
   a super administrator can import, and an organization-wide key creates organization-wide rows.
4. **Backfill** (`database._backfill_owner_units`, called from `_run_sqlite_alters` and `_run_pg_alters`): same rule
   as a new row, once per schema (marker `ownership.backfill.v1` in that schema's `settings`), inside a savepoint so
   a failure leaves no marker, never blocks startup, and is retried on the next start. Logs placed / left counts.
5. **Scope** (`scoped_metrics.table_scope`): the three tables go through the registry. `_ORG_OF` generalises
   the task board's organization predicate to the two instance tables (`org_id`, or the starter's organization
   when the row has none). Appetite and obligations stay closed in `table_scope`; the appetite card has its own query.
6. **Dashboard** (`routes_dashboard.py`): `_scoped_command_stats` now returns the SLA block (same formulas as the
   super administrator's), `workflow_active`, `erm_appetite_breaches` (shared `_appetite_breaches`, which the super
   administrator's card now uses too), overdue SLA rows in the overdue list and count, and `risk_counts` including
   the platform risks in scope (equal to the register page's `by_level`). `api_my_dashboard_data`: `sla_breaches`, `risks`.
7. **Reports** (`routes_reports.py`): `sla_performance` and `executive_brief` follow the scope with no code change;
   `risk_report` for restricted users merges the platform risks in scope with the enterprise ones (the super
   administrator's report is unchanged). Card, report and page now agree (test).
8. **Register** (`routes_risks.py`, `risk_register.html`): detail opens by the unit rule (404, never 403);
   "+ New Risk" is hidden unless the viewer is a super administrator (it posted into a 403 and failed silently).
9. **Guards found on the way**: `DELETE /erm/api/register-entry/{id}` deleted any platform risk for any
   `erm.risk.manage` holder, now 404 outside the caller's unit (proved by turning the guard off: a unit A owner
   deleted unit B's risk). `GET /api/bulk/export/{type}` needed only a sign-in and dumped `risk_register`,
   `aria_controls`, `evidence_items`, `sentinel_ropa`, `frameworks`; it now needs `platform.manage_users`, like the import.
10. **Business unit deletion** (`governance/data_service.delete_business_unit`): the three tables join the list it checks
    (without that, deleting a unit that owns a risk, clock or workflow raised a foreign key error, shown red first).
    A scan found about 15 other tables with a foreign key to `business_units` that the list does not cover; that is
    older, harmless to data (the key blocks the delete) and reported below, not changed.
11. **Browser suite**: `test_modal_contract.py` opens "+ New Risk" as the super administrator now (the only role offered
    the button); `tests/ui/action_registry.json` lists the open and submit actions for the super administrator only;
    new `tests/ui/test_restored_cards_browser.py` (risk owner, employee, super administrator) compares the page's own
    API before and after seeding rows, so leftovers from other tests cannot change the answer.
12. **Tests**: `tests/test_platform_ownership.py` (resolver, writers, backfill, registry guards),
    `tests/test_platform_ownership_surfaces.py` (scope per persona, cards, my dashboard, reports, register, search,
    guards, and the same through the real routers), page tests, three real-PostgreSQL tests. e3ddfad's
    `test_entity_scope.py` expectations that asserted the hidden state were rewritten for the new truth.
13. **Two follow-up patches from spawned sessions, applied to the working tree 2026-10-09** (not committed; the full suite
    was deliberately not rerun after applying, because the same patched code had been run in a scratch copy of this
    tree first). Both sessions' own plans sit beside their patches in `.claude/worktrees/sad-volhard-f2f618/` and
    `.claude/worktrees/recursing-wescoff-fc6702/`.
    - **ERM CSV export** (`erm_export_unit_scope.patch`): `api_export_csv` applies `entity_scope_sql(("erm","risk"), user, "e")`
      and `entity_scope_sql(("platform","risk"), user, "r")`; new `tests/test_erm_export_unit_scope.py` (8 tests through the
      real ERM router, imports the `world` fixture from `tests/test_platform_ownership.py`, so commit them together). On
      the unpatched source 6 of the 8 fail (the super administrator and the 403 pass either way). Side effect: a tenant
      without the ERM licence now gets a header-only CSV; before, `erm.risk.view` alone exported everything.
    - **Business unit delete** (`delete_business_unit_complete_guard.patch`): the list in `delete_business_unit` is now
      `_BU_REFERENCES`, 38 (table, column) pairs covering every foreign key to `business_units` (it checked 21); schema-scan
      tests in `tests/test_governance_delete_guards.py` (SQLite) and `tests/test_postgres_init.py` (PostgreSQL, public and a
      tenant schema) fail when a table is missing; the 409 text now says to deactivate. Decision: any assignment or
      transfer history row blocks the delete (the foreign keys forbid it anyway). A unit named only by an ended assignment
      returned 500 before and 409 after, through the real router.
    - Checks before applying: `git apply --check` of both together, clean; in a scratch copy of this tree 179 focused tests,
      274 wider governance, ERM, export and download tests and the whole PG18 lane (50 passed) pass; their new tests fail on
      the unpatched source (10 failed). After applying here: the two patches' own test files, 21 passed, and the capability
      inventory check matches.
