# PLAN-36 progress ledger

## 2026-09-30 T08 sessions 7-9 — F16: bcm_incidents, sentinel_dsr, grid_non_conformances had no BU scoping

Outcome: three more confirmed, F14-class tenant-isolation gaps found and
fixed, discovered while checking (before starting P01 implementation)
whether the existing `/api/my-dashboard/data` and `/api/command-centre/stats`
widget queries were safe to build a new feature on top of. They were not --
several of the tables those widgets touch turned out to have no scoping at
all. Investigated each module's own primary routes directly (not assumed)
before concluding anything; found the picture was mixed, not a uniform
app-wide failure: `erm_enterprise_risks` and `orm_events` were already
correctly scoped via `bu_scope_ids()` on checking, and most of Sentinel's
other record types (DPIAs, breaches, AI impact assessments) were too.
Three tables were not. See `findings.md` F16 for the full writeup; this
entry is the implementation/verification evidence for each.

**Session 7 -- `bcm_incidents`**: no `business_unit_id` (or any scoping
column) existed at all; `list_incidents`/`get_incident`/`update_incident`/
`delete_incident`/the CSV export/the AI-suggest endpoint all queried by
plain id or no filter. `module.bcm.access` (gating list/get) is held by
`EMPLOYEE`. Fixed: `business_unit_id` added via the existing
`_COLUMN_MIGRATIONS` mechanism; every touchpoint now takes an optional
`bu_scope` parameter and applies the same `(business_unit_id IN (scope) OR
business_unit_id IS NULL)` convention `bcm_plans`/`bcm_bia_records` already
use; `get_incident` returns `None`/`update_incident` and `delete_incident`
return `False` outside scope (routes turn `False` into 404). No backfill:
`commander`/`assigned_to` are free-text names, not user FKs -- no reliable
column exists to derive an existing row's business unit from, and a fuzzy
name-match was rejected as riskier than leaving pre-existing rows NULL for
a human to assign later.

New file `tests/test_bcm_incident_bu_isolation.py` (6 tests: get denies/
allows/unscoped-super-admin, list excludes, update refuses, delete
refuses). Red/green proof: temporarily short-circuited `get_incident` to
`return row` unconditionally (this alone also defeats `update_incident`/
`delete_incident`, which call `get_incident` internally for their own
check) -- 3 of 6 tests FAILED for the expected reasons. Separately
short-circuited `list_incidents`' own WHERE-clause condition
(`if False and bu_scope is not None`) -- its own test FAILED too (all 4
independent mechanisms proved red). Restored both; `git diff --stat`
showed only the intended cumulative diff; all 6 green again.

**Session 8 -- `sentinel_dsr`**: GDPR data-subject-request records (real
requester names/emails/request details), gated by `sentinel.dsr.manage`
(DPO, PRIVACY_ANALYST). Same shape as `bcm_incidents` -- no scoping column,
no user-id column to backfill from either. Also found and fixed in the same
pass: the AI-draft endpoint (`POST /api/ai/dsr-draft/{dsr_id}`, gated by the
separate, broader `sentinel.ai.assess`) had its own unscoped `get_dsr` call,
and the audit evidence-pack ZIP export (`GET /api/audit-export`, gated by
the broad `module.sentinel.access`) was found to *also* unscope
`list_ropa()`/`list_dpias()`/`list_breaches()` inside the same function --
fixed all three alongside the DSR log, even though RoPA/DPIA/breach listing
elsewhere in the module already scope correctly; this one export function
had simply never had `bu_scope` threaded through despite the underlying
`list_*` functions already supporting it. `_DSR_FIELDS` (the generic
create/update field whitelist) extended with `business_unit_id`; `get_dsr`/
`update_dsr`/`delete_dsr` wrap the generic `_generic_get`/`_generic_update`/
`_generic_delete` helpers with the same fail-closed check as `bcm_incidents`
-- the generic helpers themselves were deliberately left untouched, since
other sentinel record types share them and don't all have a
`business_unit_id` column.

New file `tests/test_sentinel_dsr_bu_isolation.py` (5 tests, same shape as
the BCM file). Red/green proof: same two-part short-circuit pattern
(`get_dsr` forced to `return row`, `list_dsrs`' own filter condition forced
false) -- 3 then 1 more test failed for the expected reasons across the two
rounds. Restored both; diff clean; all 5 green again.

**Session 9 -- `grid_non_conformances`**: gated by `grid.nc.manage`,
unscoped whenever `GET /grid/api/ncs` was called without a specific
`audit_id` (an optional query parameter -- omitting it returns every NC
platform-wide). Fixed differently from the other two, after checking the
schema rather than assuming the same shape applied: `audit_id` is a
required, `NOT NULL` foreign key to `grid_audits`, which already has its
own `business_unit_id` column (from earlier T-work) and its own correctly
`bu_scope_ids()`-scoped listing -- so this table needed no new column and
no backfill at all. Scoped by joining through the audit relationship the
query already had (it already joined `grid_audits a` for `audit_name`
display) and filtering on `a.business_unit_id`. `list_ncs`/`get_nc`/
`update_nc`/`delete_nc` all updated; `update_nc`/`delete_nc` previously had
no return value at all (implicit `None`) and now return `True`/`False` so
the route can 404 correctly.

New file `tests/test_grid_nc_bu_isolation.py` (5 tests, same shape). Red/
green proof: same two-part short-circuit pattern. Restored both; diff
clean; all 5 green again.

**Named, not-yet-fixed gap found while fixing this**: `create_nc` does not
verify the caller's `bu_scope` actually includes the `audit_id` supplied in
the request body -- a user could still create a non-conformance record
under another business unit's audit. This is a write-side gap distinct from
the read/update/delete-by-id gap this session fixed, and was not fixed
alongside it (see `findings.md` F16 for why it's named rather than silently
left out).

Verification commands (all from `oneforall/`):

1. `..\.venv\Scripts\python.exe -m pytest tests/test_bcm_incident_bu_isolation.py tests/test_sentinel_dsr_bu_isolation.py tests/test_grid_nc_bu_isolation.py -v` -- 16 passed, exit 0 (after all three red/green proofs were completed and reverted).
2. Full backend suite (`pytest tests --ignore=tests/ui -q`) run twice: once after `bcm_incidents` alone (clean), once again after all three fixes combined -- both `PYTEST_EXIT:0`, zero `FAILED` lines.
3. Full browser suite (`pytest tests/ui -q`) run once after all three fixes combined, to catch any BCM/Sentinel/GRID UI test relying on the old unscoped behavior -- `PYTEST_EXIT:0`, zero `FAILED` lines.

Explicitly unverified/skipped in this session:

- The broader, not-yet-resolved "does `(business_unit_id IN (scope) OR business_unit_id IS NULL)` leak a NULL-BU row across organizations, not just business units" question named in `findings.md` F16 -- affects every table using this established convention, not just the three fixed here, and needs its own dedicated investigation.
- `create_nc`'s write-side `audit_id` ownership gap (named above).
- PostgreSQL acceptance for these three migrations -- SQLite-verified only, no local Postgres instance available this session (same standing gap as F14/T03/T04).
- No commit or push has been made for this work yet -- the user's earlier "commit and push" authorization covered the T08-T10 work already pushed as `5bc237d`; this is new work discovered and fixed afterward, in the same session, and awaits its own commit.
- No production host or data was touched. No commit, push, migration, service restart, or deployment was performed.

## 2026-09-30 — T08-T10 work committed and pushed (user-authorized)

Commit `5bc237d` on `master`, pushed to `origin/master`
(`1ccb005..5bc237d`). Covers every T08/T09/T10 session recorded below in
this same date's entries: the F14 evidence tenant-isolation fix, the F15
ORM capability/query fix, the new registry-driven/CSRF/org-isolation/
download/concurrency test files, `.github/workflows/test.yml`, the
`postgres-schema.yml` extension, and `scripts/capability_inventory.py`.
`git diff --check` passed with zero whitespace errors before staging.
Explicitly user-authorized this turn, not assumed.

## 2026-09-30 T10 session 1 — capability inventory generator (+ F15, a real bug it found)

Outcome: T10's two boundED, low-risk deliverables are done (baseline
measurement, capability inventory generator); its large, open-ended
deliverables (extracting the 5 oversized templates, moving business logic
into services, rewriting 3 planning documents, a CI drift check) are
explicitly **not started** this session -- each is its own substantial,
multi-step project that T10's own instructions say must not be rushed
("incremental... a big-bang rewrite is prohibited"), and attempting them
now, at the end of an already long session, would trade away the care this
whole plan has otherwise been built with.

**Baseline measurement** (`wc -l` across every module's routes/service/
template file): confirms findings.md F11's claim still holds today. Five
module `index.html` templates exceed 3,000 lines (sentinel 4322, erm 4040,
grid 3879, bcm 3566, orm 3074); four route/service files exceed 1,500
(aria/routes.py 3055, grid/routes.py 2293, launcher/routes_platform.py
2134, sentinel/routes.py 1730). Inline-handler count and cyclomatic
complexity were not separately measured -- no such tool already exists in
this repo's dev dependencies, and adding one is its own decision this
session left to whoever picks up the actual extraction work.

**New `oneforall/scripts/capability_inventory.py`**: a read-only generator
(never touches app state; forces `DATABASE_URL=""` the same way the test
harness does) that introspects the REAL running route table rather than
source text. How: `require_auth`/`require_capability`/`require_module` all
decorate with `@functools.wraps(func)`, which preserves the wrapper's own
`__closure__`; a route gated by `require_capability("x","y")` has a wrapper
whose closure contains a `capabilities` cell holding exactly `("x","y")`,
readable directly and exactly -- immune to decorator aliasing (e.g.
`modules/launcher/routes_admin.py` imports the same decorator as
`_require_cap`, which a source-text/regex scan would have to special-case
but runtime introspection does not need to know about at all). Recursing
through FastAPI's internal `_IncludedRouter.original_router.routes`
wrapper (not a standard/documented type -- found by printing `type(r
).__name__` for every top-level route object, since the naive top-level
`app.routes` list only shows 12 entries directly) was needed to reach the
real 857 routes; a first attempt without that recursion undercounted at 12,
caught immediately by sanity-checking the count against how many modules
this app actually has rather than assuming 12 was plausible. Output:
`docs/generated/capability_inventory.{json,md}`, grouped by module, cross-
referencing `core/rbac.py`'s `CAPABILITIES` table for role membership and
flagging license-gated (`module.*.access`) capabilities. The generator
deliberately does not attempt implemented/gated/configuration-required/
pilot-only/deprecated/planned classification -- its own docstring and the
Markdown output's own header explain why (a product judgment a static scan
cannot make honestly), leaving a blank column for a human to fill in once
next to the facts the generator gets right for free.

**F15 (findings.md addendum)**: the generator's first real run flagged
exactly one capability string granted to no role anywhere:
`orm.event.view`. `core/rbac.py`'s `has_capability()` returns `False`
immediately for an unrecognized string (`if allowed is None: return
False`), before ever checking the caller's roles, with no super-admin
carve-out at that layer -- so `GET /orm/api/export/csv`
(`modules/orm/routes.py:576`) has been unreachable by literally every
account on the platform, including a super admin, since it shipped. Fixed
the capability string to `module.orm.access` (matching every other
read-only GET route in the same file, checked directly rather than
guessed). That fix immediately surfaced a **second**, previously-masked
bug in the same handler: its query selected `reporter_name`, a column that
does not exist on `orm_events` at all (the table has `reported_by`, a
user-id foreign key) -- a 500 the capability bug had made completely
unreachable and therefore untested until the auth layer was fixed. Fixed
by joining `users` and aliasing `u.full_name AS reporter_name`, the same
pattern this codebase's other CSV exports already use.

Red/green proof: added `orm_events_csv` to `tests/ui/test_download_contracts.py`'s
existing `_DOWNLOADS` table (reusing that file's already-established
unauthenticated-redirect / authenticated-200-with-correct-headers /
persona-without-capability-403 pattern from T08 session 4). Before either
fix: `test_download_contract[orm_events_csv]` FAILED with 403 (red --
confirmed even the intended persona, `risk_owner`, was denied). After the
capability fix alone: still FAILED, now with 500 "A database error
occurred" (the sanitized F08-style message; the real column-name error was
found by reading the schema directly, not by relaxing the sanitization).
After both fixes: full file green, 9 passed (3 downloads x 3 checks each).

Re-ran the capability inventory generator after both fixes: 857 routes,
zero unknown-capability warnings.

Verification commands (all from `oneforall/`):

1. `..\.venv\Scripts\python.exe scripts\capability_inventory.py` -- before the fix: 857 routes, 1 unknown-capability warning (`orm.event.view`). After: 857 routes, zero warnings.
2. `..\.venv\Scripts\python.exe -m pytest tests/ui/test_download_contracts.py -v` -- red (403) after adding the case with no fix, red again (500) after the capability-only fix, green (9 passed) after both fixes.
3. Full backend suite (`pytest tests --ignore=tests/ui -q`) and full browser suite (`pytest tests/ui -q`) both re-launched after the fix -- both `PYTEST_EXIT:0`, zero `FAILED` lines, confirming no regression anywhere else touching `modules/orm/routes.py` or the capability table.

Explicitly unverified/skipped in this session:

- The remaining T10 steps named in the outcome line above -- not started.
- Whether any OTHER already-shipped route has a similarly masked bug that only a capability fix would surface was not exhaustively checked beyond what the generator's own unknown-capability scan already caught (which, by construction, only catches a capability string that's wrong in a way that makes it match nothing at all -- a capability string that's merely wrong-but-happens-to-collide with a real, different, less-restrictive one would not be flagged this way).
- No commit or push has been made for any file across any session of this entire plan yet (T00 through T10). No production host or data was touched. No commit, push, migration, service restart, or deployment was performed.

## 2026-09-30 T09 session 1 — CI enforcement wired up

Outcome: T09's file/code-level work is done; its own completion gate
("a deliberately failing ... test ... blocks CI in a temporary branch") is
explicitly **not yet demonstrated**, since that requires pushing to a real
branch and watching actual hosted GitHub Actions runs, which this session
was not authorized to do. Everything below was instead verified as far as
possible without that: YAML parse-validated, every shell fragment run
locally exactly as written, and the two new test files red/green-proved
(template compilation) or reasoned through against re-read exact method
signatures (Postgres, since no local Postgres instance existed all session).

**New `.github/workflows/test.yml`**, six jobs:

1. `compile-and-static-checks` -- `python -m compileall`, `git diff --check`
   (with a base-ref fallback chain: PR base SHA -> push's `before` SHA ->
   `HEAD~1`, since a bare `git diff --check` with no ref would just compare
   the already-committed tree against itself and always pass trivially --
   tested all three branches of this logic locally), `pip check`, and
   `pip-audit` against all three requirements files (confirmed zero known
   vulnerabilities as of today).
2. `secret-scan` -- `gitleaks/gitleaks-action`. Checked the repo's own
   remote (`AliMoyo1/ThemisIQ`) before assuming no license secret is needed:
   confirmed personal-account repo, so `GITLEAKS_LICENSE` (org-only) is not
   required.
3. `backend-tests` -- full `tests --ignore=tests/ui` suite with
   `--cov-fail-under`. Measured today's real coverage first rather than
   guessing a floor: `python -m coverage report --precision=2` gives
   43.65% (the terminal's own rounded 44% would have set an
   immediately-failing floor). Floor set to 43, overridable via the
   `COVERAGE_FLOOR` repo variable so it can ratchet up without a workflow
   edit, matching the coverage policy's "never lower it to merge a change."
4. `js-checks` -- `node --check` over every `static/js/*.js` file (all 10
   pass locally) plus `node --test` over `tests/js/*.test.js` using
   Node's own built-in test runner (no npm/package.json exists in this
   repo and none was added -- `aria_policy_workflow.test.js` already used
   `node:test`/`node:assert` directly; its 4 tests pass).
5. `browser-smoke` (pull_request only) -- 5 representative UI files
   (harness smoke, modal contract, action-registry contracts, CSRF, org
   isolation), Playwright Chromium cached by a key hashing
   `requirements-browser-dev.txt`.
6. `browser-full` (master push only) -- the complete `tests/ui` suite.

Every `uses:` is pinned to a commit SHA, looked up live via `gh api
repos/<owner>/<repo>/tags` (not guessed), matching the convention
`aria-preview-image.yml` already established:
`actions/checkout@3d3c42e...` (v7.0.1), `actions/setup-python@5fda3b9...`
(v7.0.0), `actions/cache@55cc834...` (v6.1.0), `actions/upload-artifact@043fb46...`
(v7.0.1), `gitleaks/gitleaks-action@e0c47f4...` (v3.0.0).

**One fabricated-SHA mistake caught before it could ship**: a first draft
pinned `actions/cache` to `0057852bfaa89a56745cba8c7296529d2fc39830 # v4.3.0`
-- a SHA that does not exist anywhere in that repo's real tag list (current
was already v6.1.0). Caught immediately by actually running `gh api
repos/actions/cache/tags` instead of trusting a plausible-looking string,
and fixed before this was ever presented as done. Recorded here as a
concrete example of why every SHA in this file was looked up live, not
recalled from training data.

**`postgres-schema.yml`** (existing file): the job and its
`TEST_DATABASE_URL`/destructive-test-target guard are untouched (per T09's
own "retain" instruction); its two previously-floating `@v4`/`@v5` action
tags are now pinned the same way as above. Extended with T03/T04/F14 cases
by adding 3 new tests directly to `tests/test_postgres_init.py` (the one
file this job already runs, using its existing `pg` fixture):
   - `test_erm_risk_library_gets_org_id_column_on_real_postgres` (T03).
   - `test_evidence_items_gets_org_id_column_and_rls_policy_on_real_postgres`
     (F14) -- checks the column, the `pg_policy`/`pg_class.relforcerowsecurity`
     catalog rows, and then a **functional** proof: two real connections with
     `set_rls_context()` called for two different orgs, confirming org B's
     connection cannot read org A's row and org A's own connection can (the
     same positive-control discipline as every other isolation test this
     plan has built, now proven at the database layer Postgres RLS actually
     runs on, not just the app layer SQLite is limited to).
   - `test_warm_replay_queries_execute_on_real_postgres` (T04) -- the same
     every-query-executes proof `tests/test_warm_replay.py` already does
     against SQLite, run against a real Postgres schema instead.

   These 3 tests could only be verified by careful reading (exact
   `set_rls_context(org_id, is_super=False)` signature re-confirmed against
   `database.py:303`; `get_db()`'s own automatic RLS-context-from-contextvar
   behavior at `database.py:465-474` was initially a concern -- it only
   fires `set_rls_context` automatically when a contextvar was already set,
   which my tests never do -- resolved by calling `set_rls_context`
   directly on the wrapper myself instead of relying on that automatic
   path) and by local collection (`pytest tests/test_postgres_init.py
   --collect-only -q` -- 13 items, up from 10, confirms every import
   resolves) -- **not run against a real instance**, since none was
   available this session. This is the same class of gap this ledger has
   named every session: "PostgreSQL gate remains unverified... no
   PostgreSQL instance available."

**New `tests/test_template_compilation.py`** (T09's "Jinja compilation
with real filters" step, runs as part of the ordinary backend suite, not a
separate CI step): imports `main` (which registers every module's custom
Jinja filters as an import side effect) and walks every
`starlette.templating.Jinja2Templates` instance left in `sys.modules`,
compiling every reachable `.html` file against the **union** of every
instance's search path and every instance's registered filters.

A per-instance-only version was tried first and produced a false positive:
`modules/launcher/templates/profile.html` uses the `format_dt` filter
(registered on `modules/launcher/_route_helpers.py`'s `shell_templates`,
which `routes_auth.py` imports and actually renders `profile.html`
through), but is also syntactically reachable through a *different*,
separately-constructed `Jinja2Templates(directory=["templates", ...])`
instance some other module owns (the same per-module-instance pattern
`modules/evidence/routes.py` uses), which never got `format_dt` registered
on it specifically. Compiling strictly instance-by-instance flagged this as
a failure even though the template is never actually rendered through that
other instance. Switched to the union approach, which still catches the
real defect class this exists for (a filter referenced that no instance
anywhere has registered) without asserting a specific module/template
pairing this file has no way to verify is the real one.

Red/green proof: created a temporary throwaway file
`templates/_plan36_t09_red_proof_temp.html` with a deliberately unclosed
`{% if %}` block -- FAILED as expected. Deleted it (never a real repo file,
confirmed via `git status --short` showing nothing). Reran -- 1 passed.
Also fixed the test's own initial `assert len(files) >= 60` (copying the
original audit's stale count) after it failed on a real run: 47 templates
were found today, and 60 vs. 47 reflects legitimate template churn since
the 2026-09-24 audit plus a different discovery method (walking registered
`Jinja2Templates` instances vs. a live crawl), not a real problem --
loosened to a `>= 30` sanity floor that only catches discovery finding
nothing at all, with the reasoning spelled out in the test's own docstring
so a future reader doesn't wonder why it isn't 60.

Verification commands (all from `oneforall/`):

1. `..\.venv\Scripts\python.exe -m pytest tests/test_template_compilation.py -v` -- 1 passed (both before and after the red/green proof).
2. `..\.venv\Scripts\python.exe -m pytest tests/test_postgres_init.py --collect-only -q` -- 13 items collected (10 pre-existing + 3 new), confirming imports resolve; all skip without `TEST_DATABASE_URL`.
3. `python -m yaml.safe_load` (via a one-off `pip install pyyaml`) on all three workflow files -- valid YAML, both before and after every edit.
4. Every shell fragment in `test.yml` (`git diff --check` fallback logic, the `node --check` loop, the `node --test` glob-or-skip logic) run locally exactly as written -- all behave as intended.
5. `python -m pip_audit` against `requirements.txt`, `requirements-dev.txt` (now including the added `pip-audit==2.10.1`), and `requirements-browser-dev.txt` -- zero known vulnerabilities in all three.
6. Full backend coverage run, `pytest tests --ignore=tests/ui -q --cov=. --cov-report=term-missing` -- 43.65% (used to calibrate the CI floor above).

Explicitly unverified/skipped in this session:

- T09's own completion gate (a deliberately failing test/browser test/PG test/template compile actually blocking a real GitHub Actions run) -- requires a real push, not done.
- The 3 new Postgres tests have not executed against a real Postgres instance.
- Branch protection requiring these jobs -- explicitly deferred until stable hosted results exist to observe (this step's own wording), which in turn needs a push.
- No secret-scan exception process (owner/expiry for an accepted finding) was built -- nothing to except yet; this is a process definition for the user's own repo settings, not code this session can create unilaterally.
- No commit or push has been made for any file across any session of this entire plan yet (T00 through T09). Everything above, including this CI wiring, is sitting locally uncommitted pending the user's explicit go-ahead.
- No production host or data was touched. No commit, push, migration, service restart, or deployment was performed.

## 2026-09-30 T08 session 6 — multi-tab/concurrency coverage

Outcome: T08's "Test multi-tab or concurrent behavior for approval,
task/update, and idempotent actions where race conditions matter" step is
now checked off. Two of the three named categories turned out to already
have real coverage from earlier sessions/plans, found by searching rather
than assumed absent:

- **Approval**: `tests/test_aria_policy_approvals.py::test_two_concurrent_deciders_exactly_one_wins` already exists -- a genuine two-thread race (real file-based DB, real separate `database.get_db()` connections per thread, not the shared test fixture) against `modules/aria/policy_workflow_service.py`'s `decide_approval`, which locks in this order: document, version, approval (`SELECT ... FOR UPDATE` on Postgres) plus an optimistic `lock_version` check in the final `UPDATE ... WHERE status='pending' AND lock_version=%s`, checking `rowcount` and raising `AlreadyDecidedError` (409) for the loser. Confirmed exactly one winner, one `AlreadyDecidedError`.
- **Idempotent actions**: `tests/test_aria_policy_approvals.py::test_resubmitting_same_request_id_is_idempotent` already covers ARIA's submit-for-approval `request_id` idempotency.
- **Task/update**: no existing coverage of a genuine concurrent race (only `tests/test_concurrency_guards.py::test_task_update_non_owner_hits_predicate`/`test_task_update_owner_succeeds`, which test the ownership predicate via direct SQL, not a race). Grepped `lock_version` across `modules/` first to check whether any module besides ARIA already had optimistic-locking infrastructure worth reusing -- none did.

New file `tests/ui/test_task_update_concurrency.py`: two real threads, two real `httpx` clients, two genuinely concurrent `PUT /api/tasks/{tid}` requests against the live app (not a simulated single-threaded race) setting different `status` values on the same task. Finding: `api_task_update` (`modules/launcher/routes_platform.py`) has **no** optimistic guard at all -- its `UPDATE`'s `WHERE` clause only re-checks existence and ownership (`WHERE id=%s AND (created_by=%s OR assigned_to=%s)`), never a prior field value, so `cur.rowcount` can only be 0 if the row vanished or ownership changed, never because a concurrent write already changed the row first. Both concurrent requests get 200; the later commit silently wins with no conflict signal to either caller. The test asserts this as the current, factual behavior (with an explicit docstring instruction not to just loosen the assertion if this ever changes) rather than asserting it is wrong -- whether task-board drag/drop needs approval-grade conflict detection is a product decision this testing task should surface, not silently make.

Verification: `..\.venv\Scripts\python.exe -m pytest tests/ui/test_task_update_concurrency.py -v` -- 1 passed, `PYTEST_EXIT:0`. No red/green proof recorded: this test characterizes existing behavior rather than proving a fix, so there is no "fix" to prove catches a regression -- the equivalent assurance is the test's own explicit instruction to update its assertions (not loosen them) if `api_task_update` ever gains a guard.

Explicitly unverified/skipped in this session:

- Whether task_board (or any other un-audited module) *should* gain optimistic locking is a product decision, not made here.
- No commit or push has been made for any file across any T08 session yet.
- No production host or data was touched. No commit, push, migration, service restart, or deployment was performed.

## 2026-09-30 T08 session 5 — F14: evidence repository had no tenant scoping at all

Outcome: a new critical, previously-uncatalogued finding was discovered
while building T08 session 4's download-contract tests, investigated fully,
fixed, and tested the same session. Recorded as `findings.md` F14 (its own
addendum section, since the original register is a dated 2026-09-24 audit
snapshot and this was found 2026-09-30). This took priority over continuing
straight down the T08 checklist because it is a live cross-tenant data
exposure, not a coverage gap -- closing exactly this class of issue is
PLAN-36's own stated objective.

**What was found**: `evidence_items` (`database.py`) had no `org_id`,
`business_unit_id`, or creator-scope column at all -- confirmed by reading
its `CREATE TABLE`, not assumed. None of `modules/evidence/routes.py`'s
list, get, download, download-pdf, update, delete/archive, restore, or
permanent-delete routes filtered by organization; every one reached the row
by plain `id`. `evidence.delete` is `COMPLIANCE_MGR`-gated (org-scoped), and
list/get/download needed only `@require_auth` (any authenticated user, any
org, no extra capability). PostgreSQL's RLS layer (`core/rls.py`) covers
exactly 4 tables (`users`, `audit_log`, `licenses`, `webhooks`) --
`evidence_items` was never one of them. Net effect: any logged-in user in
any tenant could list, read, download, rename, archive, restore, or
permanently delete any other tenant's evidence by knowing or guessing an id,
on both SQLite (always) and PostgreSQL (for any org not on a dedicated
tenant schema). Two smaller, adjacent leaks in the same upload function were
found and fixed alongside it: cross-org duplicate-detection-by-hash (a hash
match in another org confirmed that org's document title/id existed) and the
`replace_id` version-chain lookup (an arbitrary id from another org could be
marked superseded).

**The fix**:

- `database.py`: `("evidence_items", "org_id", "INTEGER REFERENCES organizations(id)")` added to the existing `_COLUMN_MIGRATIONS` list (the same schema-evolution mechanism `erm_risk_library.org_id` and `webhooks.org_id` already use -- covers SQLite and PostgreSQL from one list).
- `database.py`: new `_backfill_evidence_org_id(conn)`, called from `init_db()` right after `_backfill_legacy_seeded_admin`. Backfills `org_id` from the row's own `uploaded_by -> users.org_id`, idempotent (`WHERE org_id IS NULL`). This matters because, unlike `erm_risk_library`'s NULL-means-global-catalogue semantics, evidence has no shared/global concept -- leaving deployed evidence at NULL post-upgrade would silently hide every organization's own existing evidence from itself. An orphaned uploader (no org, or deleted) leaves the row NULL, which is treated as super-admin-only -- failing closed, not guessing.
- `modules/evidence/routes.py`: new `_scoped_evidence_item(db, eid, user)` helper (same fail-closed shape as `modules/launcher/routes_admin.py`'s `_get_webhook_for_admin`: super admin sees any row, everyone else only `org_id == their org_id`, NULL org_id belongs to nobody but super admin). Applied to get, update, delete/archive, restore, permanent-delete, download, and download-pdf. `list` got an inline `WHERE e.org_id = %s` addition (matches its existing dynamic-WHERE-building style). Upload now: rejects a non-super-admin with no org outright (same fail-closed guard `create_library_item` already established this plan); sets `org_id` on the INSERT; scopes the duplicate-hash check and the `replace_id` lookup through the same helper.
- `core/rls.py`: added `evidence_items` to the 4-table RLS policy list, for Postgres defense-in-depth alongside the app-level check (matching webhooks' own belt-and-braces treatment).

**Tests** (new): `tests/test_evidence_org_isolation.py` (7 backend/migration-level tests: backfill sets org_id from uploader, backfill never overwrites an already-set org_id, backfill leaves an orphaned upload NULL, `_scoped_evidence_item` denies another org/allows the owning org/allows super admin across any org/denies a NULL-org row to an ordinary user) and three new tests appended to `tests/ui/test_org_isolation.py` (HTTP-level, real upload by org A's risk_owner, real denied list/get/download/update attempt by org B's risk_owner, each with a same-org positive control). Evidence's `delete`/`restore` need `COMPLIANCE_MGR`, not `RISK_OWNER` -- cross-org HTTP proof for those two specifically was not added (a third persona/fixture pair just for that was judged not worth it given `_scoped_evidence_item` already gates them identically and is proven directly); noted here rather than silently skipped.

One test-authoring bug caught by the tests themselves, not a product bug:
`_upload_evidence`'s test helper originally sent identical file bytes for
every call, so the second and third calls in the same test file legitimately
409'd against the first as duplicates -- inside the SAME org, which is
correct behavior, just not what the test intended. Fixed by including the
title in the uploaded content so each probe gets a distinct hash.

Red/green proof, two rounds: (1) commented out the `_backfill_evidence_org_id(conn)` call in `init_db()` and short-circuited `_scoped_evidence_item` to `return row` unconditionally -- 3 of the 7 backend tests FAILED for the expected reasons (backfill test saw `org_id is None`; both denial tests got a real row back instead of `None`). Restored; `git diff --stat` showed only the intended cumulative diff; green again. (2) Repeated at the HTTP level: re-applied the same `_scoped_evidence_item` short-circuit plus disabled the `list` route's org filter (`if False and not user.get(...)`) -- all 3 new `test_org_isolation.py` evidence tests FAILED. Restored; diff clean; green again.

Verification commands (all from `oneforall/`):

1. `..\.venv\Scripts\python.exe -m pytest tests/test_evidence_org_isolation.py -v` -- 7 passed, exit 0 (and 3 of 7 FAILED during the round-1 red proof, restored to 7 passed).
2. `..\.venv\Scripts\python.exe -m pytest tests/ui/test_org_isolation.py -q` -- 5 passed, exit 0 (and 3 of 5 FAILED during the round-2 red proof, restored to 5 passed).
3. Full backend suite, `pytest tests --ignore=tests/ui -q` from `oneforall/` -- exit 0, clean (only the pre-existing, unrelated openpyxl `utcnow()` deprecation warnings from `test_user_import.py`), run after every evidence.py edit in this session including the follow-up round below. Full browser suite (`pytest tests/ui -q`) launched in parallel; result confirmed in the next session entry.

**Follow-up in the same session**: while documenting the "not yet fixed" list below, seven more `evidence_items`-by-id touchpoints were found to have the identical unscoped-lookup shape and were fixed the same way (routed through `_scoped_evidence_item`, or in `api_evidence_link_delete`'s case, through the evidence row the link points at) rather than left for later, since they were cheap, in the same file, and of the same class: `GET /api/items/{eid}/versions` (also closes the entry point to its whole parent/child walk, not just the top-level row), `GET /api/items/{eid}/verify` (was re-hashing and confirming file-on-disk existence for any id), `POST`/`DELETE /api/items/{eid}/confidence-verify`, `POST /api/items/{eid}/links` (the evidence side only -- the target entity's own org is not cross-checked, a separate and more module-spanning gap), `DELETE /api/links/{lid}` (previously had **zero** ownership check of any kind, not even the plain `@require_auth`-only pattern -- looked up the link's `evidence_id` and soft-deleted it unconditionally), and `POST /api/items/{eid}/suggest-links` (was leaking another org's evidence title/description/tags into an AI prompt and would have billed the caller's org for a suggestion against a resource it doesn't own). Re-ran `tests/test_evidence_org_isolation.py` + `tests/ui/test_org_isolation.py` after this follow-up round -- still 12 passed, 0 failed -- and then the full backend suite again (item 3 above already reflects this final state, not the pre-follow-up one).

**Second follow-up, same session**: `GET /api/linked` and `GET /api/auto/{module}/{entity_type}/{entity_id}` were re-examined and found to be the same severity class as `list`/`get` (both `SELECT e.*`/full-column reads of `evidence_items`, joined through `evidence_links` to an entity, with zero org filter) -- not the lower-severity aggregate class initially assumed. Fixed both with the same inline `WHERE ... AND e.org_id = %s` (non-super-admin only) pattern `list` already uses. Re-ran `tests/test_evidence_org_isolation.py` + `tests/ui/test_org_isolation.py` -- still 12 passed, 0 failed.

`GET /api/resolve-links`, `GET /api/coverage`, and `GET /api/search-entities` were each read directly and confirmed genuinely out of F14's scope, not just deprioritized: none queries `evidence_items` for content. `resolve-links` batch-resolves OTHER modules' entity ids (aria_documents, grid_controls, bcm_bia_records, sentinel_* tables, etc.) to a display name/url via a hardcoded `_ENTITY_RESOLVERS` map. `coverage` counts entities in those same other-module tables and whether each has any evidence link at all. `search-entities` searches those other-module tables by name for entities to link evidence to. Whether those target tables are themselves org-scoped is each of those modules' own tenant-isolation question, not evidence's.

**Third follow-up, same session**: re-reading `GET /api/stats` before writing it off as "aggregate-only, lower priority" (the initial characterization above) found that its `recently_added` field returns real `title`/`category`/`file_name` for the platform's 5 most-recently-uploaded non-archived items -- not a count. That is exactly the same content-disclosure class as `list`, not a product-policy question, and the initial characterization was wrong. Fixed: every one of the endpoint's 8 queries (`total`, `by_category`, `expiring_soon`, `total_links`, `unlinked`, `by_module`, `expiring_7`, `recently_added`, `archived_count`) now takes an `org_filter`/`org_params` pair built once at the top of the function (empty for a super admin). New test `test_evidence_stats_does_not_leak_another_orgs_recent_titles` in `tests/ui/test_org_isolation.py` (org A uploads, asserts its title is absent from org B's `recently_added` and present in its own, both through the real endpoint).

One test-authoring mistake caught while adding that test, fixed immediately: the Edit that inserted the new test function was built from a truncated re-read of the file and didn't include the five lines that already followed the insertion point (`test_evidence_from_another_org_cannot_be_updated`'s own positive-control check, `same_org_resp = org_a_client.put(...)`) -- those lines got mechanically pushed to the end of the newly-inserted function instead of staying in the original one, producing a `NameError: name 'eid' is not defined` (the new function never defined `eid`). Caught immediately by running the file (not by inspection), fixed by moving the five lines back to their original function.

A second, separate real regression was caught the same way, in a file this session had not touched directly: the full browser suite (`pytest tests/ui -q`) launched after the first evidence follow-up round came back with exactly one failure, `test_modal_contract.py::test_link_evidence_modal_from_an_existing_item` (`Page.evaluate: SyntaxError: Unexpected token '<'... is not valid JSON`). Root cause: that test seeds its own `evidence_items` row directly via `INSERT INTO evidence_items (title, category, uploaded_by) VALUES (...)` with no `org_id`, logs in as a non-super-admin (`compliance_manager`), and opens that item's detail view -- which now correctly 404s under the new fail-closed default (NULL `org_id` is super-admin-only), and the frontend's `openDetail()` doesn't handle a 404 gracefully in this path. This is the test fixture being stale against the new, correct security model, not a flaw in the fix: a real `compliance_manager` would only ever encounter evidence rows that already carry their own org's `org_id`, since upload now always sets one. Fixed by adding `org_id` (from `synthetic_tenant["org_id"]`) to the test's INSERT, matching what every real upload does post-fix.

Verification commands (all from `oneforall/`):

4. `..\.venv\Scripts\python.exe -m pytest tests/ui/test_org_isolation.py -q` -- 6 passed, exit 0 (after both the stats fix and both test-bug fixes above).
5. `..\.venv\Scripts\python.exe -m pytest tests/ui/test_modal_contract.py::test_link_evidence_modal_from_an_existing_item -v` -- 1 passed, exit 0 (was the sole failure in the full browser suite before this fixture fix).
6. Full backend suite and full browser suite both re-launched from a clean state after every fix above landed. The backend rerun's *first* pass (before this final one) surfaced a **fourth**, separate real regression this same fix caused: `tests/test_evidence_suggest_links.py`'s 6 tests all failed with `HTTPException 404: Evidence not found` inside `api_evidence_suggest_links` -- that file's `_actor`/`_evidence_item` fixtures had no `org_id` concept at all (only `business_unit_id`, since it predates the org_id column entirely), so every seeded evidence row and every actor had `org_id=NULL`, which never matches under the new check. Same root cause and same category as the `test_modal_contract.py` fixture staleness above, just in a backend test that calls the route function directly rather than through the browser. Fixed by adding a shared `_org()` helper and threading one real `org_id` through both `_actor` and `_evidence_item` in every one of the file's 6 tests (this file is entirely about BU-vs-BU isolation within one org, never org-vs-org, so one shared org per test is correct, not a simplification that loses coverage). Verified: `pytest tests/test_evidence_suggest_links.py -v` -- 6 passed. Final reruns after this fourth fix: backend suite -- `PYTEST_EXIT:0` (explicitly appended as the log's last line specifically to avoid an exit-code ambiguity below), zero `FAILED` lines. Browser suite -- 100% completion, zero `FAILED`/`ERROR` lines (all dots/skips).

**Tooling note for future sessions**: this session's own verification commands twice produced a misleading exit-code signal by chaining `; echo "EXIT:$?"; grep -c "FAILED" logfile` -- the outer shell/task-notification reports the *last* command's exit code, which is `grep -c`'s, not pytest's. `grep -c` itself exits 1 when it finds zero matches (a clean run) and 0 whenever it finds at least one match (a run with real failures) -- backwards from what a glance at "exit code" suggests. Concretely: task `bobgzljph` reported "exit code 0" while the log it produced actually had 6 real `FAILED` lines (grep found matches -> exit 0), and task `bzjfzoqct` reported "failed, exit code 1" while its log was 100% clean (grep found zero matches -> exit 1). Both were caught by reading the log's actual content rather than trusting the summary. Going forward: read the log directly, or append the real exit code as the log's own last line (as done for `full_backend_truly_final.log` above) rather than trusting a trailing `grep`'s exit code.

Explicitly unverified/skipped in this session:

- PostgreSQL acceptance for this specific migration (the RLS policy addition and the `ADD COLUMN`/backfill) has not been run against a real PostgreSQL instance this session -- SQLite-verified only so far.
- Cross-org HTTP proof for evidence delete/restore specifically (named above).
- No commit or push has been made for any file across any T08 session yet -- this fix, despite its severity, is sitting uncommitted locally pending the user's explicit go-ahead, consistent with this plan's own working rule 9 and this session's established pattern.
- No production host or data was touched. No commit, push, migration, service restart, or deployment was performed.

## 2026-09-30 T08 session 4 — download contract checks

Outcome: T08's "Add download checks for expected content type, disposition,
non-empty file, and authorization" step now has coverage for two
representative CSV export routes: ERM risk register
(`/erm/api/export/csv`, `erm.risk.view`) and BCM incidents
(`/bcm/api/export/csv`, `module.bcm.access`). Both were chosen specifically
because they stream straight from a DB query with no filesystem/upload
dependency, unlike evidence's file-backed download
(`modules/evidence/routes.py`'s `api_evidence_download`), which needs a real
uploaded-file fixture this suite doesn't have yet and is left as a named gap.

New file `tests/ui/test_download_contracts.py`, three checks per download:
unauthenticated request redirects to `/login` (these are GET/`read_only`
actions, so they were never covered by `test_action_registry_http_contracts.py`,
which only drives `classification == "mutation"` entries); an authenticated
holder of the right capability gets 200 with the exact expected
`Content-Type` prefix, an `attachment` `Content-Disposition` carrying the
right filename, and a non-empty body; and a persona lacking the capability
gets 403.

One wrong assumption caught by the test itself, not a false pass: the denied
persona started as `"employee"` for both downloads, copying the pattern from
`test_action_registry_http_contracts.py`. `bcm_incidents_csv`'s denial check
failed with a real 200 instead of 403 -- reading `core/rbac.py`'s
`CAPABILITIES` table showed `EMPLOYEE` is deliberately included in
`module.bcm.access` (business-continuity duties reach every staff member),
so it was never a valid "denied" persona for that specific download. Switched
to `"viewer"` (`EXTERNAL_AUDITOR`), which core/rbac.py confirms holds neither
`module.bcm.access` nor `erm.risk.view`.

No separate red/green proof was recorded for this file: the capability-denial
mechanism it exercises (`core/middleware.py`'s `require_capability`) is the
exact same decorator already red/green-proven in T08 session 1's webhook
example, and the content-type/disposition assertions are direct reads of
each route's own explicit `media_type`/`Content-Disposition` header
construction (`modules/erm/routes.py:1405-1408`,
`modules/bcm/routes.py:1346-1349`), not new logic.

Verification: `..\.venv\Scripts\python.exe -m pytest tests/ui/test_download_contracts.py -q` -- 6 passed, exit 0.

Explicitly unverified/skipped in this session:

- Evidence's file-backed download (`api_evidence_download`) and any other
  non-CSV download (GRID zip export, ARIA document export, etc.) are not
  covered.
- Whether `api_evidence_download`'s `@require_auth`-only gate (no capability
  or ownership/org check beyond being logged in -- read directly, not
  assumed) is intentional-by-design or a real gap was NOT determined this
  session. Flagging it here rather than silently asserting either way: any
  authenticated user can currently download any evidence item by id if that
  reading is correct. Needs a deliberate look before more download tests are
  built on top of it.
- No commit or push has been made for any file across any T08 session yet.
- No production host or data was touched. No commit, push, migration, service
  restart, or deployment was performed.

## 2026-09-30 T08 session 3 — HTTP-level cross-org isolation proof

Outcome: the "organization/SBU isolation ... on critical routes" slice of
T08's first step now has one concrete HTTP-level proof (previously this
invariant was only tested at the service/data layer, e.g.
`tests/test_erm_library_tenancy.py`, `tests/test_audit_org_isolation.py` --
valuable but none of them go through the real ASGI app with two real
sessions).

Chose ERM's risk library as the target after checking, not assuming, that it
was a real example: `erm.library.manage` (`core/rbac.py`'s `CAPABILITIES`
table) is held by `RISK_OWNER`, an org-scoped role, not a platform-wide one
-- unlike `platform.manage_users` (webhooks' own capability, super-admin-only,
first considered and rejected as the example for this reason: the org-scoped
branch in webhooks' `_get_webhook_for_admin` is currently unreachable by any
role that actually holds that capability). `modules/erm/data_service.py`'s
`_library_can_manage` is explicit that a non-super-admin actor may only
manage a row belonging to their own `org_id`.

`synthetic_tenant` (`tests/ui/conftest.py`) only builds one organization, so
new file `tests/ui/test_org_isolation.py` adds its own second, disposable org
+ risk_owner user directly via `database.get_db()` (same pattern
`test_link_evidence_modal_from_an_existing_item` already uses), then two
tests: org B's risk_owner cannot PUT or DELETE an item org A's risk_owner
created (expect 404, and for delete, a DB-level check that `is_active` stayed
1), each with a positive control in the same test proving org A's own
risk_owner CAN act on its own item (so the 404 is proven to mean isolation,
not just "writes are broken").

One real bug caught while building this before it could become a false
"regression": both test bodies originally POSTed to `/api/library`, which
doesn't exist -- `modules/erm/routes.py`'s router is mounted at prefix
`/erm`, so the real path is `/erm/api/library`. Found immediately (both
tests failed with a 404 body of `{"detail":"Not found."}` instead of the
expected 201) rather than a false pass, but recorded here since it's exactly
the kind of assumed-path mistake this session's own methodology (verify,
don't assume) exists to catch.

Red/green proof: temporarily changed `_library_can_manage` to
`if actor.get("is_super_admin"): return True` followed by an unconditional
`return True` (short-circuiting the real org-ownership line). Both new tests
FAILED (red). Restored; `git diff --stat` showed zero diff; reran green.

Verification: `..\.venv\Scripts\python.exe -m pytest tests/ui/test_org_isolation.py -q` -- 2 passed, exit 0 (before and after the red/green proof).

Explicitly unverified/skipped in this session:

- Only one module (ERM library) got an HTTP-level cross-org proof. Other
  org-scoped critical routes (evidence, ARIA documents, GRID, BCM, sentinel)
  still rely on service-layer isolation tests only, not an HTTP-level one.
- SBU (business-unit-level, as opposed to org-level) isolation at the HTTP
  layer is not covered by this file.
- No commit or push has been made for any file across any T08 session yet.
- No production host or data was touched. No commit, push, migration, service
  restart, or deployment was performed.

## 2026-09-30 T08 session 2 — default-fail page-error gate, desktop viewports, CSRF coverage

Outcome: three more T08 steps advanced.

**1. Console/page-error capture becomes default-fail, not opt-in** (step:
"Capture uncaught page errors, console errors, failed same-origin requests,
... and server 5xx; fail the test unless explicitly allowlisted with
rationale"). Before this, `tests/ui/conftest.py`'s `page` fixture collected
errors onto `page.console_errors` but only 12 of 24 UI test files actually
asserted on it -- the other 12 silently passed even if a real console/page
error fired, unless a test's own explicit UI assertion happened to catch the
downstream symptom.

`tests/ui/conftest.py`'s `page` fixture now asserts `not
gated_errors` at teardown for every UI test, unless marked
`@pytest.mark.expected_page_errors("reason")` (registered in `pytest.ini`).
"Failed to load resource" is excluded from the gate specifically, not from
the raw list: two existing tests
(`test_webhook_admin_ui.py`/`test_email_settings_error_detail.py`) already
documented that Chromium logs that exact line for *any* non-2xx fetch/XHR
response or network-level failure regardless of whether the page's own JS
handled it correctly -- confirmed empirically, not assumed, by running the
full existing UI suite against the new gate before deciding whether any
existing deliberate-failure test (test_api_client.py's 400/401/403/409/429/500/
abort/timeout cases, test_admin_connectors_ui.py's 429/400/500 cases,
test_email_settings_error_detail.py's 502/500 cases,
test_task_board_and_my_dashboard_migration.py's 400/409/500 cases) would need
the new marker. Result: **zero existing tests needed it** -- full suite ran
green with no changes to any of those files. `requestfailed`/`response`
listeners were considered and deliberately not added as a separate channel:
the existing console listener already surfaces the same signal (with the
status/reason in the message text), so a second listener would just be
duplicate machinery for the same underlying browser events.

Verification: `..\.venv\Scripts\python.exe -m pytest tests/ui -q` from
`oneforall/`, full suite, exit 0, run after the fixture change and before any
other change in this session.

**2. Desktop viewport coverage** (step 5: "Test at least desktop 1366x768 and
1920x1080 ... plus mobile regression 390x844"). 390x844 (modal overflow,
2 representative modals) and 640x800/200%-zoom-equivalent (shell overflow,
21 T07 acceptance routes) already existed; the two named desktop sizes did
not. New file `tests/ui/test_desktop_viewports.py`: the same 21-route list
at both 1366x768 and 1920x1080 for shell overflow, plus the same two
representative modals (newTaskModal, uploadModal) at both sizes for modal
overflow -- 46 parametrized cases total.

Verification: `..\.venv\Scripts\python.exe -m pytest tests/ui/test_desktop_viewports.py -q` -- 46 passed, exit 0.

**3. CSRF/origin coverage** (step: "... CSRF/origin behavior ... on critical
routes"). Grepped every `validate_csrf` call site first rather than assuming
blanket CSRF middleware exists -- it doesn't. `core/middleware.py`'s
`validate_csrf()` is called explicitly, as the first statement, inside 9
`/admin/users/*` form routes (`modules/launcher/routes_admin.py`) sharing one
identical rejection pattern, plus `/login`, `/mfa/verify`, and
`/mfa/setup/confirm` (`modules/launcher/routes_auth.py`). The much larger set
of JSON `/api/*` mutation routes already covered by
`test_action_registry_http_contracts.py` do not call `validate_csrf` at all
-- session cookie plus JSON content-type/body shape is the actual mitigation
there (not forgeable by a plain cross-site HTML form), which is a real
architecture split, not a gap invented here.

New file `tests/ui/test_csrf_protection.py`: all 9 `/admin/users/*` actions
checked for both a missing csrf_token (the `if not form_token` branch) and a
present-but-wrong one (the `secrets.compare_digest` branch) -- 18 cases,
proxied by the exact known rejection message (source-verified to `return`
before any `db = get_db()` call in every one of the 9, so the message is a
sound proxy, not a guess) -- plus one direct DB postcondition check (the
`create` action, bad CSRF -> no user row inserted) for concrete proof beyond
message-matching, plus `/login` checked the same way (missing and wrong
token), proven by checking the session cookie is never set even with
correct credentials.

`/mfa/verify` and `/mfa/setup/confirm` are NOT covered -- would need a
mfa_pending session fixture this suite doesn't build yet. Also not done:
the 9 `/admin/users/*` actions are not yet in `action_registry.json` (T00's
own registry is honestly partial and each T-task is supposed to extend it
for the module it touches -- this is debt this session found but did not
pay down, to stay focused; noted here rather than silently dropped).

Red/green proof: temporarily changed `if not validate_csrf(...)` to `if
False and not validate_csrf(...)` in `admin_deactivate_user`
(routes_admin.py) and in `login_submit` (routes_auth.py). Both
`test_admin_users_action_rejects_missing_csrf_token[deactivate]` and
`test_login_rejects_missing_csrf_token_and_does_not_authenticate` FAILED
(red). Restored both lines; `git diff --stat` on both files showed zero
diff; full file reran green.

Verification: `..\.venv\Scripts\python.exe -m pytest tests/ui/test_csrf_protection.py -q` -- 21 passed, exit 0 (both before and after the red/green proof).

Explicitly unverified/skipped in this session:

- `/mfa/verify` and `/mfa/setup/confirm` CSRF coverage (named above).
- Adding the 9 `/admin/users/*` actions to `action_registry.json` (named above).
- Organization/SBU isolation, success/validation/conflict/server-failure
  coverage, realistic data seeding, multi-tab/concurrency, and download
  validation -- none of T08's remaining steps -- not started this session.
- No commit or push has been made for any file in this or the prior T08
  session yet.
- No production host or data was touched. No commit, push, migration, service
  restart, or deployment was performed.

## 2026-09-30 T08 session 1 — registry-driven HTTP contract tests (auth + capability denial)

Outcome: two of T08's steps ("Add HTTP integration coverage for authentication
... capability denial ... on critical routes" and part of "Drive every
action-registry entry that is safe in an isolated database") now have generic,
registry-driven coverage. Not a completion-gate claim for T08 as a whole --
CSRF/origin behavior, org/SBU isolation, success/validation/conflict/server-failure
coverage, multi-viewport (1366x768/1920x1080), multi-tab/concurrency, download
validation, and console/5xx/redirect capture are still open (see task_plan.md T08
steps, all still unchecked).

Before touching code this session, first confirmed the state left by the prior
session's work (the `_backfill_legacy_seeded_admin` migration, the
`api_client.js` redirect-ordering fix, and the `warm_replay.py` schema
corrections/`_classify` refactor) by reading the diffs and this ledger's most
recent entries above, then ran the full suite twice as a fresh baseline:

1. `..\.venv\Scripts\python.exe -m pytest tests --ignore=tests/ui -q` (backend) -- exit 0.
2. `..\.venv\Scripts\python.exe -m pytest tests/ui -q` (browser) -- exit 0.

Both ran from `oneforall/` as background jobs and both finished clean, confirming
the other session's changes did not regress anything before new work started.

New file: `oneforall/tests/ui/test_action_registry_http_contracts.py`. Plain
`httpx` against the real ASGI app (`live_app`), not Playwright -- these checks
are about the HTTP contract (status/redirect), not rendered DOM, matching the
precedent already documented in `test_request_id_middleware.py`. Two generic
tests parametrized over `action_registry.json`:

- `test_unauthenticated_mutation_is_redirected_not_executed` -- every
  `classification == "mutation"` action (12 total; 11 exercised, 1 --
  `auth.login.submit` -- intentionally skipped since it's reachable while
  logged out by design) is called with no session and a placeholder path
  parameter (`999999999`, safe because `require_auth`/`require_capability`
  both run before any resource lookup -- confirmed by reading
  `core/middleware.py` directly, not assumed). Asserts a redirect to `/login`
  or a 401, never a 2xx.
- `test_persona_without_capability_is_forbidden` -- the subset of mutation
  actions gated by one simple capability string (not ARIA's `"X OR (Y AND
  is_own)"` ownership expressions, which need a real owned/not-owned document
  fixture and are left to `test_aria_managed_edit.py`) is called by a real
  logged-in persona confirmed to lack that capability. Asserts 403.

A `persona_client` fixture logs in through the real `/login` form (GET for the
CSRF cookie, POST credentials + token back, exactly what a browser does) and
caches one `httpx.Client` per persona per module.

One fixture-shape bug found and fixed while building this: sending `json={}`
to `evidence.upload_evidence.submit` (`multipart/form-data`-only) got a 422
from FastAPI's own request-shape validation before `@require_auth` ever ran,
which would have falsely read as "no auth check". Added a
`_MULTIPART_ACTIONS` override so that one action gets a real file upload body
instead.

Red/green proof (the review-list item this directly answers -- proving the
new capability-denial test actually catches a real regression, not just a
passing tautology): temporarily commented out
`@_require_cap("platform.manage_users")` on `api_webhook_create`
(`modules/launcher/routes_admin.py:1150`, backing
`launcher.admin_webhooks.create_webhook.submit`). Reran just that
parametrization --
`test_persona_without_capability_is_forbidden[launcher.admin_webhooks.create_webhook.submit]`
-- FAILED (red, for the expected reason: a denied persona got 201 instead of
403). Restored the decorator; reran the full file -- 15 passed, 1 skipped
(green).

Verification commands (all from `oneforall/`):

1. `..\.venv\Scripts\python.exe -m pytest tests/ui/test_action_registry_http_contracts.py -q` -- 15 passed, 1 skipped.
2. Red/green proof above.
3. Full backend + browser baselines (both green, see above) re-confirmed unaffected after restoring the decorator.

Explicitly unverified/skipped in this session:

- The remaining T08 steps listed in the outcome line above -- not started yet.
- No commit or push has been made for this file yet.
- No production host or data was touched. No commit, push, migration, service restart, or deployment was performed.

## 2026-09-29 — webhook test fixture socket-race correction

A follow-up review identified the concrete cause of the intermittent failures in
`tests/test_webhook_test_endpoint.py` that earlier entries below had attributed
to generic localhost timing. The local `BaseHTTPRequestHandler` returned its
response without reading the POST request body. Its default HTTP/1.0 behavior
then closed the socket with unread inbound data, which can produce a Windows
connection reset and surface through httpx as `ConnectionAbortedError:
[WinError 10053]`. This is a defect in the test fixture, not in the production
webhook delivery path.

The handler now drains exactly the declared `Content-Length` before sending
either its 200 or 500 response. The earlier T06/T07 ledger entries that recorded
the symptoms are corrected below to point to this diagnosis instead of treating
the failures as an unexplained transport hiccup.

Verification: five pre-fix repetitions happened to pass locally, which did not
disprove the reported intermittent race; the review evidence reproduced the
failure in two of three isolated runs and captured the exact Windows exception.
After the fix, the complete five-test endpoint file passed ten consecutive
process-isolated runs (50 test executions). The full backend suite then passed
with its ten expected PostgreSQL skips and only the existing openpyxl
deprecation warnings.

## 2026-09-28 — follow-up fixes after review of 8086c46

A second review of commit 8086c46 found three implementation gaps and one
stale ledger statement. All confirmed gaps are fixed:

1. The shared API client now detects a followed login redirect before every
   success response mode. Expired sessions therefore raise the same typed
   authentication error for JSON, blob, text, and no-content callers; GRID
   report downloads can no longer save the login page as a PDF/DOCX and show
   a false success toast. The browser regression test covers all three
   response modes that previously returned before redirect detection.
2. Database initialization now performs an idempotent data migration for the
   exact legacy default seed account (admin / admin@oneforall.local) when that
   account still holds the super_admin role. This reaches existing databases,
   while a negative regression test proves that unrelated organization-scoped
   users holding the same role are not promoted to platform access.
3. The remaining invalid warm-replay queries now use the real schema:
   ARIA risks are grouped by likelihood and impact, and ORM events by
   event_type. A new schema-execution regression test runs all 28 replay
   queries against a freshly initialized SQLite database, preventing future
   table or column drift from escaping the unit suite.
4. The prior section's stale statement that commit 8086c46 had not been
   committed or pushed is corrected below.

Verification: the focused regression tests were first observed failing for
the expected reasons, then passed after the fixes. The full backend suite
passes with its existing skips. The full browser suite passes with one
expected skip. PostgreSQL warm replay was not run because no shadow
PostgreSQL instance is available in this workspace; its queries remain
standard SQL and the production migration uses the shared SQLite/PostgreSQL
initialization path.

## 2026-09-28 — post-push code-review fixes (7 findings, all confirmed and fixed)

After T00-T07 was committed and pushed (commit `0011473`), an external code
review of that commit returned 7 findings. Each was independently verified
against the actual current code (not taken on trust) before fixing -- one
finding's exact mechanism (the middleware-ordering bug) required working
through Starlette's actual `add_middleware`/`build_middleware_stack`
semantics by hand rather than assuming the report's framing was correct,
since "outermost first" is the kind of claim that's easy to get backwards.
All 7 were confirmed real. Every fix has a red/green-proved test.

1. **[P1] GRID audits sent to the AI unscoped, and joined the wrong
   frameworks table** (`modules/evidence/routes.py`, `api_evidence_suggest_links`).
   The audits query had no business-unit filter at all (the adjacent risks
   query, two lines below, already had one) and joined the shared `frameworks`
   table instead of `grid_frameworks` (GRID's own, confirmed as a distinct
   real table in `database.py`). Fixed: scoped by `bu_scope_ids()` exactly
   like the risks query; joins `grid_frameworks`. New tests:
   `test_suggest_links_excludes_another_business_units_audit`,
   `test_suggest_links_org_wide_audit_is_visible_to_every_bu`,
   `test_suggest_links_uses_grid_frameworks_not_shared_frameworks_table` in
   `tests/test_evidence_suggest_links.py`. Red/green-proved by reverting to
   the original unscoped/wrong-table query -- both the cross-BU leak and the
   wrong-table join failed exactly as expected.
2. **[P1] Expired sessions produced false mutation-success toasts**
   (`static/js/api_client.js`). `fetch()`'s default `redirect:'follow'`
   means an expired-session mutation that gets redirected to `/login` comes
   back as a 200 HTML page; `ApiClient.request()` treated any 200 response
   as success and returned the raw (non-JSON) body when `expect` was
   `'json'` (the default) -- so a caller's success path ("Saved",
   "Delivered") fired even though the mutation never ran. Fixed: a 200
   response that isn't JSON when JSON was expected now throws instead of
   silently degrading to truncated raw text, with a specific "session
   expired" message when the response was actually redirected to `/login`
   (`response.redirected` + `new URL(response.url).pathname`). New tests:
   `test_login_redirect_throws_session_expired_not_fake_success` (simulates
   real expiry by clearing cookies after `login_as`, not just redirecting
   the mocked endpoint -- an *authenticated* browser hitting `/login`
   bounces onward to `/`, which would miss the exact case this fix targets)
   and `test_non_json_200_without_redirect_throws_parse_error` in
   `tests/ui/test_api_client.py`. Both red/green-proved.
3. **[P1] The SSRF policy let IPv4 Shared Address Space (CGNAT,
   100.64.0.0/10, RFC 6598) through** (`core/outbound_http.py::_is_blocked`).
   The function OR'd together `is_private`/`is_loopback`/`is_link_local`/
   `is_reserved`/`is_multicast`/`is_unspecified` -- confirmed directly in a
   throwaway interpreter session that `ipaddress.ip_address('100.64.0.1')`
   has every one of those as `False` while `is_global` is also `False`: this
   specific range isn't private, loopback, link-local, reserved, multicast,
   or unspecified by Python's own classification, but is still not globally
   routable. Fixed: `_is_blocked` is now simply `not ip.is_global`, which is
   what the function's own docstring already claimed to implement. New
   parametrized cases (`100.64.0.1`, `100.100.100.1`) added to the existing
   `test_rejects_non_global_dns_answer` in `tests/test_outbound_http.py`.
   Red/green-proved by reverting to the old OR-chain.
4. **[P2] A non-super-admin actor with no org_id could create an ERM
   library row neither they nor anyone but a real super admin could ever
   manage again** (`modules/erm/data_service.py::create_library_item` +
   `seeds/seed.py`). `create_library_item`'s own org_id-selection logic
   (`None if is_super_admin else actor.get('org_id')`) produces `org_id=NULL`
   -- indistinguishable from a real global row -- for ANY actor whose
   `org_id` happens to be `None`, not just a true super admin; `_library_
   can_manage` then permanently refuses that same actor, since it only
   trusts `org_id IS NULL` when `is_super_admin` is genuinely true. Confirmed
   this was reachable by the actual default seeded admin: `seed.py` granted
   the `SUPER_ADMIN` role via `user_roles` but never set the raw
   `users.is_super_admin` column, which several code paths (this one
   included) check directly rather than going through the role-based
   capability system -- so the fresh-install admin had `is_super_admin=0`
   (the column's own default) and `org_id=NULL`, exactly the broken
   combination. Fixed both ends: `seed.py` now sets `is_super_admin=1`
   explicitly (the root cause), and `create_library_item` now fails closed
   (returns `None`, route raises 403) for any non-super-admin actor with no
   org_id, as defense in depth against the same actor shape arising some
   other way in the future. New tests:
   `test_create_library_item_refuses_a_non_super_admin_with_no_org` in
   `tests/test_erm_library_tenancy.py`; new file
   `tests/test_seed_admin_is_super_admin.py`. Both red/green-proved -- the
   first caught a real orphan row (id 26) being created before the fix.
5. **[P2] warm_replay.py's recovery-parity script could exit 0 despite
   real checks never running** (`scripts/warm_replay.py`). Two independent
   bugs: (a) four queries referenced columns/tables that don't exist at all
   (`users.role` -- role lives in a separate `user_roles` table;
   `grid_ncs` -- real name is `grid_non_conformances`; `grid_evidence` --
   real name is `grid_evidence_files`; `erm_obligations` -- real name is
   `erm_regulatory_obligations`; all confirmed directly against
   `database.py`'s actual schema), so these had never once executed
   successfully on either database; (b) a query erroring on one or both
   sides was classified SKIP, which never contributed to `fail_count`/
   `failures` and therefore never affected the exit code -- so those four
   permanently-broken queries silently reported SKIP forever while the
   script still exited 0. Fixed both: corrected all 4 queries to the real
   schema, and removed the SKIP classification entirely (any error on
   either side is now FAIL, matching the module's own stated invariant that
   every query must always be valid on both databases). The classification
   logic was factored out into a pure `_classify()` function specifically so
   this could be unit tested without real database connections. New file
   `tests/test_warm_replay.py`, 5 tests, red/green-proved by temporarily
   reintroducing the old SKIP-returning branches.
6. **[P2] Request ID and security headers did not wrap early middleware
   rejections** (`main.py`). The registration order matched the comment's
   stated *intent* ("outermost first: request ID, then security headers,
   ... then CSRF") but not Starlette's actual semantics: both
   `app.middleware("http")(fn)` and `app.add_middleware()` insert at the
   *front* of Starlette's internal middleware list, and
   `build_middleware_stack()` wraps that list in reverse -- so the *last*
   middleware registered ends up *outermost*, exactly backwards from a
   naive top-to-bottom reading. Worked through this by hand (simulating the
   insert-at-0-then-reverse construction step by step for the actual
   registration order in this file) rather than trusting the finding's
   framing alone, since this is exactly the kind of claim worth confirming
   independently. Confirmed the practical consequence directly: with the
   old order, `request_id_middleware`/`security_headers_middleware` ended up
   *inside* `cors_block_middleware`, so a cross-origin-rejected request
   (which `cors_block_middleware` answers directly, without calling
   `call_next()`) never reached them at all -- a real 403 came back with
   neither header. Fixed by reversing the registration order (a pure
   reordering, no logic changes) so the actual runtime order now matches
   the comment's original intent. New test
   `test_request_id_and_security_headers_survive_a_cors_rejection` in
   `tests/ui/test_request_id_middleware.py` -- deliberately not just another
   404 case (a 404 passes through every middleware's own `call_next()`
   fully before the router fails to match, so it can't distinguish
   "outermost" from "innermost" the way an early-return rejection can).
   Red/green-proved by reverting to the old order.
7. **[P3] task_plan.md's own top-of-file status line was stale**, still
   saying "T01-T10 and P01-P09 NOT STARTED" after this same commit reported
   T00-T07 complete. Fixed directly; no test applicable to a status line.

Verification: `pytest tests/test_evidence_suggest_links.py
tests/test_outbound_http.py tests/test_erm_library_tenancy.py
tests/test_seed_admin_is_super_admin.py tests/test_warm_replay.py
tests/ui/test_api_client.py tests/ui/test_request_id_middleware.py -q` --
all pass. Full backend suite (`pytest tests --ignore=tests/ui -q`) --
**clean, 0 failures** -- run as a final check given finding 6 touches
middleware order for every request in the app. Full browser suite
(`pytest tests/ui -q`) -- **clean, 0 failures, 1 expected skip** -- run as a
final check given finding 2 touches the shared `api_client.js` every
migrated mutation path in the app calls through. `python -m compileall`
clean. These fixes were committed and pushed as 8086c46.

Status: T00-T06 substantially complete (see each section). **T07 is now complete against its own stated completion gate** (see task_plan.md's T07 section for the exact gate language and what "complete" does and doesn't claim), reached across three sessions: session 1 found/fixed a sitewide template bug plus skip link/landmark/several accessible-name gaps; session 2 closed every `select-name`/`label` axe finding across all 21 acceptance routes, converted Evidence's and ERM's keyboard-inaccessible clickable divs/spans to real buttons, fixed several SPA anchors missing `href`, gave the toast system a live region, and fixed every color-contrast finding with the user's explicit sign-off; session 3 (2026-09-28) completed the interactive-chip/badge sweep across every module, fixed the last visible-focus and reduced-motion gaps found repo-wide, gave every high-traffic custom drawer/panel the same Tab-trap/focus-restore behavior ModalManager provides real modals, added tab-order/200%-zoom automated checks, and wrote a manual keyboard test script for what automation can't prove. **The axe acceptance-route suite passes all 21 routes with zero xfail; the full browser and backend suites are clean** (each with one already-documented, independently-reproduced pre-existing flaky test, neither in a file any T07 session touched). Known, explicitly documented remainder (not blocking the gate, tracked as the plan's own "remaining moderate findings"): ~44 smaller ad-hoc modal instances across ERM/ORM/BCM/admin_users/my_dashboard without Tab-trap/focus-restore, Evidence's detail panel with Escape-only, and dark-mode contrast for 3 modules. (T00's full-inventory registry step is intentionally partial; "real Edge" was tested as Chromium, not the msedge channel -- see T00; no PostgreSQL/Docker instance available this session -- affects T01, T03, T04's two operational-script checkboxes, and T05's PostgreSQL-specific save-path parity.) T08-T10 and P01-P09 not started.

## 2026-09-28 T07 session 3 — interactive-chip sweep, remaining visible-focus fixes, reduced-motion sweep

Outcome: resolves the two largest items session 2 left explicitly open. (1) The "chip/badge" census session 2 flagged as untriaged (aria 9, bcm 6, grid 8, admin_users/launcher/projects 3, task_board 5, timeline 4, orm 3, sentinel 31) is now fully triaged: every one individually checked for a real click handler versus being a pure display badge, with interactive ones converted to `<button>` and decorative ones deliberately left alone. Along the way this also caught 2 sets entirely missed by the original per-module census because they live in files outside the `modules/` tree (`templates/command_centre.html`, the first page after login) or under a differently-named class the module list didn't separately call out (ERM's `.chat-prompt-chip`, distinct from the `.erm-chip` family already fixed in session 2). (2) The remaining "visible focus"/"reduced motion" T07 steps: a repo-wide scan for `outline:none` with no visible replacement found the last 2 real instances (both fixed); a repo-wide scan for looping (`infinite`) CSS animations found ~25, of which every purely decorative/ambient one now respects `prefers-reduced-motion` (loading spinners deliberately excluded as legitimate functional feedback).

Files changed:

- `oneforall/templates/base_shell.html`: `.filter-chip` (the platform-wide shared filter-chip class used by BCM/GRID/Sentinel/Command Centre) gained `font-family:inherit` -- it already set `border`/`background` explicitly, so this was the only UA button-chrome property left to neutralize for the conversions below.
- `oneforall/modules/sentinel/templates/index.html`: 29 `.filter-chip`/`.chip-pick` spans (DSR/ROPA/DPIA/AIIA/DataFlow/Training status and risk filters, all wired via individual inline `onclick` attributes) plus 1 multi-line `.aria-ctrl-chip` (a control-linking chip built across several `+`-concatenated JS lines, which needed a hand edit since the general regex only matches single-line `<span>...</span>` content) converted to `<button type="button">`. One `.filter-chip` span at line ~3601 (a read-only tag display on a record, no `onclick`) deliberately left as a span -- same shared CSS class, but genuinely not interactive.
- `oneforall/modules/aria/templates/ask.html`: 7 `.sug-chip` suggestion prompts and the `.history-item` recent-question list item converted to `<button>` (both wired via the file's own single delegated `document.querySelectorAll('.sug-chip, .history-item').forEach(el => el.addEventListener('click', ...))`, so no JS changed). `.sug-chip`/`.history-item` CSS gained `font-family:inherit`; `.history-item` also gained `width:100%;text-align:left;background:none` since (unlike `.sug-chip`) it didn't already set its own background, and is a full-width list row, not an inline pill.
- `oneforall/modules/bcm/templates/index.html`, `grid/templates/index.html`, `launcher/templates/task_board.html`, `launcher/templates/timeline.html`, `templates/command_centre.html`, `erm/templates/index.html`: BCM (5), GRID (8), Task Board (5), Command Centre (7) filter-chip spans (inline `onclick`) converted the same way; Timeline's 3 period chips (delegated listener, like ERM's original chips) and ERM's 4 `.chat-prompt-chip` quick-prompts (also delegated) converted directly. `.tb-pri-chip`/`.tl-chip`/`.chat-prompt-chip` CSS each gained `font-family:inherit`.
- `oneforall/modules/aria/templates/ai_generator.html`: `.aria-draft-editor` (the main policy-draft textarea -- previously no border, no outline, no focus indicator of any kind) gained `.aria-draft-editor:focus{box-shadow:inset 0 0 0 3px var(--accent-pale)}`.
- `oneforall/modules/launcher/templates/timeline.html`: `.tl-module-sel` (a filter `<select>` that removed the native outline and replaced it with nothing) gained a `:focus` border-color/box-shadow ring matching the platform's established `.form-input:focus` convention.
- `oneforall/modules/launcher/templates/login.html`: added one `@media (prefers-reduced-motion:reduce)` block disabling all 12 purely-ambient looping animations (`scene-top-pulse`, `scene-bottom-glow`, `scene-spot`, `card-glow`, all 4 beams, all 4 corners). The 3D card-tilt and background-spot parallax are JS mousemove handlers, not CSS animations, so they needed a separate guard: both listeners are now registered only when `window.matchMedia('(prefers-reduced-motion: reduce)').matches` is false.
- `oneforall/templates/_platform_trainer.html`, `modules/aria/templates/base.html`, `modules/sentinel/templates/dashboard.html`, `modules/sentinel/templates/index.html`, `modules/bcm/templates/index.html`: one `@media (prefers-reduced-motion:reduce)` rule each, disabling the trainer bubble's pulse ring, tooltip-mode glow, AI "typing" dots, the ARIA-ask floating-button pulse, Sentinel's dashboard status dot, its overdue/critical badge pulse, and BCM's live-badge dot.

New files:

- `oneforall/tests/ui/test_chip_filters_are_buttons.py` -- 7 tests (1 skips gracefully when a fixture doesn't seed the rows a decorative-chip check needs): BCM/GRID filter chips are buttons; Task Board's 5 priority chips are buttons; Timeline's period chips are buttons and keyboard-operable (red/green-proved by reverting to `<span>`); Command Centre's and ERM's newly-found chips are buttons; and a guard the opposite direction -- ARIA's `.row-chip` (a genuinely non-interactive display badge) is confirmed to remain a plain `<span>`, not over-converted.
- `oneforall/tests/ui/test_visible_focus_indicators.py` -- 2 tests, both red/green-proved: the draft editor's focus ring (tested by injecting a throwaway element with the same class into the already-loaded page, since `#draftEditor` itself is only visible after opening/starting a draft -- a bigger flow than this fix needed to drive) and Timeline's module filter.
- `oneforall/tests/ui/test_reduced_motion.py` -- 4 tests using Playwright's real `page.emulate_media(reduced_motion=...)`, not a simulated preference: login's ambient animations stop under the preference (red/green-proved) and a control case confirms they still run without it; the card-tilt JS doesn't respond to mouse movement under the preference (red/green-proved); the trainer pulse and typing dots stop too.

Verification commands and results:

1. `pytest tests/ui/test_reduced_motion.py -q` -- 4 passed.
2. **Red/green proof #1** (login CSS reduced-motion block): temporarily renamed the media query to `prefers-reduced-motion:reduceDISABLED` -- the ambient-animation test failed. Restored; passed.
3. **Red/green proof #2** (login JS tilt/parallax guard): temporarily hardcoded `prefersReducedMotion = false` -- the tilt-response test failed (the card responded to mouse movement regardless of the emulated preference). Restored; passed.
4. `pytest tests/ui/test_chip_filters_are_buttons.py -q` -- 6 passed, 1 skipped (no `.row-chip` rows seeded for the decorative-chip guard in this fixture state -- structurally confirmed correct by direct source reading instead, see Files above).
5. **Red/green proof #3** (Timeline chip conversion): temporarily reverted the 3 period chips back to `<span>` -- the keyboard-operability test failed. Restored; passed.
6. `pytest tests/ui/test_visible_focus_indicators.py -q` -- 2 passed (both already red/green-proved in session 2; unchanged this session, re-run only to confirm no regression from the reduced-motion/chip edits touching nearby CSS in the same files).
7. A final repo-wide sweep (every `<span>`/`<div>` with a "chip" class, cross-checked against every `querySelectorAll`/`addEventListener` site targeting a "chip" class anywhere in the codebase) confirms zero remaining interactive chip-class span/div anywhere -- not just the files this session touched.
8. Full browser suite, `pytest tests/ui -q`, run three times across this session (after the reduced-motion fixes; after the chip conversions; and once more as a final pass) -- all three clean, 0 failures.
9. `python -m compileall -q oneforall` -- exit 0 (this session touched no Python).
10. `git fetch origin --prune` + `git rev-parse HEAD origin/master` -- both match the session-2 baseline exactly; no reconciliation needed.

## 2026-09-28 T07 session 3 continued — dialog semantics, tab order, 200% zoom, manual keyboard script

Outcome: closes out every remaining T07 step the user asked to finish. (1) A new shared `DialogFocus` utility gives every high-traffic custom drawer/panel that predates ModalManager the same Tab-trap and focus-restore-on-close behavior, without the visual risk of migrating each one onto the `.modal-overlay`/`.modal` markup contract. (2) Tab order and keyboard-trap automated checks added (both clean). (3) A new 200%-zoom reflow suite across all 21 acceptance routes (clean). (4) A human-run manual keyboard test script for what automation genuinely can't prove (focus-indicator perceptibility, screen-reader announcement, full no-mouse task completion).

Files changed:

- `oneforall/static/js/dialog_focus.js` (new) -- `DialogFocus.trap(container)` / `.release()`. Reuses modal_manager.js's own Tab-wrap algorithm exactly (first/last focusable, Shift+Tab and Tab wrap-around). Release is automatic via a `MutationObserver` watching for the trapped container leaving the DOM -- deliberate, not a simplification: several of the panels this got wired into close from 4+ different call sites (a Cancel button, a backdrop click, a post-save success handler, a separate Escape listener elsewhere in the file), and requiring every one of those to remember an explicit `release()` call is exactly the kind of thing that gets missed once a fifth call site is added later. Panels that close via a CSS class toggle instead of DOM removal (nothing to observe) still need an explicit `release()` call -- found to be a real, not just theoretical, gap by a genuine end-to-end test failure on People Directory's drawer (see Verification below), not assumed correct from the utility's own unit tests alone.
- `oneforall/templates/base_shell.html`: `dialog_focus.js` loaded right after `api_client.js` (before end-of-body), for the identical reason T06 already documented for `api_client.js` itself -- several call sites invoke `DialogFocus.trap()` from a bare top-level function, not one wrapped in `DOMContentLoaded`.
- `oneforall/modules/erm/templates/index.html`: risk drawer and results drawer both gained a `trap()` call right after their real content is rendered (not the "Loading…" placeholder state) and a `release()` call in their close functions.
- `oneforall/modules/orm/templates/index.html`: all 4 drawer-rendering functions (event detail, RCSA results, AIMS assessment, AIMS risk detail) gained a `trap()` call using the function's own already-scoped `drawer` variable; `ormCloseDrawer()` (shared by all 4) gained `release()`.
- `oneforall/modules/sentinel/templates/index.html`: all 8 of its ad-hoc dialogs (RoPA/DPIA/AIIA record drawers, LIA, generate-notice, draft-policy, both jurisdiction configs) gained a `trap()` call. These close from many scattered `.remove()` call sites (6+ found just for DPIA alone) rather than one shared function, which is exactly the case the MutationObserver auto-release was built for -- no explicit `release()` calls were added here, relying entirely on DOM-removal detection, and the generic test in `test_dialog_focus.py` proves that mechanism works.
- `oneforall/modules/aria/templates/base.html`: the Ask ARIA drawer's `openDrawer()`/`closeDrawer()` gained `trap()`/`release()`. The existing 180ms-delayed focus onto the question input specifically (not just "the first focusable element," which would have been the header close button given DOM order) was deliberately preserved by leaving that call in place after `trap()`, rather than replaced.
- `oneforall/modules/launcher/templates/people_directory.html`, `vendor_directory.html`: `openDrawer()`/`vdOpenDrawer()` gained `trap()`; `closeDrawer()`/`vdCloseDrawer()` gained an explicit `release()` -- required here specifically because these close via `classList.remove('open')`, not DOM removal, so the MutationObserver would never fire. This exact gap was caught by a real failing test, not reasoned through in advance: the first version of `test_people_directory_drawer_...` failed with focus landing nowhere (`activeElement.id === ''`) after Escape, which is what led to adding the explicit call here and auditing Vendor Directory for the identical pattern proactively.

**Explicitly not done, found but out of scope for this session**: a repo-wide scan for the same `document.body.insertAdjacentHTML('beforeend', html)` pattern found ~44 *more* ad-hoc modal instances beyond what's listed above -- ERM has 15 more (its own `.erm-modal-overlay` convention, no per-dialog ID, closed via a bare `document.querySelector('.erm-modal-overlay')`), ORM has ~13 more (`.orm-modal-overlay`, *with* per-dialog IDs like `ormBulkStatusModal`), BCM has ~21 (a plain unprefixed `class="modal-overlay"` -- the same class name ModalManager's own real dialogs use, which is what stopped this session from applying the same blind "grab the last-inserted element with this class" fix used for ERM/Sentinel: on a page that might also have a real, currently-open ModalManager dialog, that query could select the wrong element). admin_users and my_dashboard have 1 each. These are real gaps, not invented ones, but chasing another ~44 individually-verified call sites was judged a worse use of remaining session time than getting the ones already wired fully correct and tested -- and BCM's specific ambiguity is a genuine "stop and think" signal, not just more of the same mechanical work. A dedicated follow-up (or folding this into T10's modularization pass, since several of these files are already flagged by F11 as oversized) is the right next step, not a rushed mass-edit here.

New files:

- `oneforall/tests/ui/test_dialog_focus.py` -- 3 tests. Two are unit-level proofs of the utility itself, independent of any specific drawer: Tab-trap wrap-around in both directions on a synthetic 3-button panel, and the MutationObserver auto-release proof (red/green-proved: temporarily broke the observer's release-on-removal logic, confirmed Tab would otherwise stay captured against a detached node and the trigger would never regain focus). The third is a real end-to-end proof through People Directory's actual drawer -- this is the one that found the class-toggle-close gap described above; its first version failed for a genuine reason, not a test bug, and the fix (adding `release()` to `closeDrawer()`) is what made it pass.
- `oneforall/tests/ui/test_200_percent_zoom.py` -- all 21 acceptance routes at 640x800 (the standard reflow-equivalent breakpoint for 200% zoom on a 1280px design -- the same halving relationship WCAG 1.4.10's own 400%-zoom/320px-width guidance uses), checking `document.body.scrollWidth > window.innerWidth`, the identical technique `test_modal_contract.py` already established for its own 390x844 mobile-overflow check. All 21 pass. Two showed a `login_as` networkidle timeout on the first full-suite run; both passed cleanly when re-run in isolation (2/2), matching this plan's own already-documented flake class (browser-test timeouts under many sequential full-suite runs in one session, not a real defect) rather than a genuine reflow problem.
- `oneforall/docs/manual-keyboard-test-script.md` -- a human-run script, not an automated test, for exactly the things automation can't prove: whether a focus indicator is genuinely perceptible (not just present in computed style), whether a screen reader actually announces what the markup claims, and whether a full multi-step task (create a risk, upload evidence, test a webhook) is completable with no mouse at all. Explicitly documents that Task Board's native HTML5 drag-and-drop kanban board has no keyboard equivalent by design, but confirms (by reading the task detail drawer's `#ddStatus` select) that a full non-dragging alternative already exists and is the thing a manual tester should verify is genuinely discoverable, per WCAG 2.5.7's actual requirement (an alternative must exist, not that the drag gesture itself become keyboard-operable).

Verification commands and results:

1. Repo-wide scan for a positive `tabindex` value (breaks natural DOM tab order): zero found anywhere.
2. Repo-wide scan for CSS `order:` (flex/grid visual reorder without a matching tab-order change): zero found. First attempt's regex false-matched every `border:` declaration in the codebase (the string "order:" is a substring of "border:"); corrected with a word-boundary anchor (`\border:`) and re-verified clean.
3. `pytest tests/ui/test_dialog_focus.py -q` -- 3 passed, after the People Directory fix described above (1 genuine failure found and fixed, not a clean first pass -- recorded honestly, not glossed over).
4. **Red/green proof** (MutationObserver auto-release): temporarily made the observer's callback a no-op -- `test_dialog_focus_restores_focus_and_stops_trapping_after_dom_removal` failed (focus never returned to the trigger after the panel was removed). Restored; passed.
5. `pytest tests/ui/test_200_percent_zoom.py -q` -- 21 passed on first full run except 2 `login_as` timeouts; both isolated re-runs passed (2/2) -- treated as the documented flake class, not a defect, consistent with this plan's own established evidence standard for that specific failure signature.
6. Full browser suite, `pytest tests/ui -q`, run twice after all of this session's dialog-semantics/zoom work. First run: 3 failures (`test_aria_managed_edit.py` x2, `test_axe_acceptance_routes.py`'s `/` case) -- none in a file this session touched. Re-ran all 3 in isolation: 23/23 passed (the 21 axe routes plus the 2 aria-managed-edit tests), confirming the same full-suite-load flakiness class already documented repeatedly in this file, not a regression. Second full run (final, clean checkpoint before stopping): **clean, 0 failures, 1 expected skip.**
7. Full backend suite, `pytest tests --ignore=tests/ui -q`, run once as a final check (unnecessary strictly speaking, since this session touched no Python, but run anyway rather than assumed clean). One failure: `test_aria_policy_publication.py::test_purge_expired_trash_leaves_recent_entries` -- this is the same already-documented flake class named in T04/T05/T06's own entries in this file (a filesystem-mtime-vs-`time.time()` boundary race in ARIA trash-purge logic, a different sibling test each time it recurs, same root cause, same file, unrelated to anything any of those sessions or this one touched). Re-ran in isolation 3 times: 3/3 passed, confirming non-deterministic rather than a regression.
8. `python -m compileall -q oneforall` and `git diff --check` (filtering the benign Windows LF/CRLF normalization warnings every session this plan has produced) -- both clean.
9. `git fetch origin --prune` + `git rev-parse HEAD origin/master` -- both still match the session-2 baseline; no reconciliation needed.

**Both full suites are clean as of the final checkpoint.** T07's own completion gate (see task_plan.md's updated note) is now met for everything this programme's audit and this session's own repo-wide scans found; the ~44 remaining ad-hoc modal instances are documented as the plan's own "remaining moderate findings," not silently dropped.

Explicitly unverified/skipped:

- ~44 additional ad-hoc modal instances across ERM/ORM/BCM/admin_users/my_dashboard -- found, counted, and deliberately not fixed this session (see "Explicitly not done" above for exactly why, including the specific BCM ambiguity risk that triggered stopping rather than pushing through).
- Evidence's `#evDetailPanel` still has Escape-only, no Tab-trap -- not revisited this session.
- No commit, push, migration, service restart, or deployment was performed. No production host or data was touched.

## 2026-09-25 T07 session 2 — select-name/label sweep, keyboard-accessible buttons, SPA anchor hrefs, toast live region

Outcome: closes every `select-name` and `label` axe finding session 1 left open across all 21 acceptance routes, converts every clickable div/span/dropdown-item found to be keyboard-inaccessible in Evidence and ERM into real `<button>` elements (native Tab/Enter/Space support, no JS rewrite needed since the existing click wiring in both files is tag-agnostic), fixes 6 SPA sidebar/card anchors that were missing `href` (mouse-only via a delegated `data-spa` click handler; every other `data-spa` element in the same codebase already correctly pairs it with a real `href`, so this brought 6 stragglers in line with the codebase's own established, working convention rather than inventing a new one), and gives the toast system a proper ARIA live region. Also found, via direct contrast-ratio measurement rather than guessing, that one of session 1's own fixes (`.module-name` switched to `--accent-mid`) does not actually clear WCAG AA for every module -- ARIA's own `--accent-mid` fails 3.80:1 on `.module-name`, and (surprisingly) Sentinel's real finding turns out to be the *same* `.module-name` issue (4.37:1) rather than the button-background issue GRID has, which the prior session's own note had assumed by inheritance without separately measuring it. Presented all 5 findings to the user as one consolidated decision (darken the specific text usages, review each individually, or leave for later); the user chose "darken the specific text usages," so this session went on to implement that -- every color computed programmatically from the WCAG relative-luminance formula (same hue/saturation, only lightness reduced), not eyeballed, and re-verified against axe's own measured colors after two rounds of a value landing just short of 4.5:1 (see "Color contrast: implemented" below for exactly what that means and two additional same-pattern bugs it surfaced).

Files changed:

- `oneforall/templates/base_shell.html`: `#toastContainer` gained `role="status" aria-live="polite" aria-atomic="false"`; `showToast()`'s decorative checkmark SVG gained `aria-hidden="true"` so screen readers announce only the message text, not an unlabeled icon, on every toast the whole app shows.
- `oneforall/modules/launcher/templates/calendar.html`, `risk_register.html`, `people_directory.html`, `admin_users.html`, `erm/templates/index.html` (dashboard/register/library views), `aria/templates/documents.html`: every toolbar filter `<select>`/`<input>` visible on a route's default page load that had no accessible name now has one -- a `.sr-only` `<label for="...">` (the exact pattern session 1 already established on Task Board's `#filterModule`) for filters with no visible label text, or a real `for`/`id` pairing (aria/documents' Search/Framework/Status/Type already had visible `<label>` text, just not associated) where one already existed. `admin_users.html`'s edit-drawer labels (Full Name/Email/Username/Account Created) and ERM register's `#regSelectAll` checkbox got the same for/id or aria-label treatment for a second, separately-diagnosed `label`-class axe finding (not `select-name`) on `/admin/users` and `/erm/register`.
- `oneforall/modules/evidence/templates/evidence_index.html`: the stats-bar filter tiles (Total/Expiring/Unlinked/per-module counts), the "recently added" strip cards, the grid-view evidence cards, and the "link an entity" search-result rows were all `<div>`/mouse-only-`onclick` -- converted to `<button type="button">` with an inline reset (`width:100%;display:block;text-align:left;font:inherit` where the element sits in a CSS grid and needs to keep filling its cell; `text-align:left;font:inherit` alone where it doesn't). The Details/Versions/Activity detail-panel tabs gained real `role="tablist"`/`role="tab"`/`aria-selected`/`role="tabpanel"` semantics (`.ev-tab`'s CSS gained `background:none;border:none;font-family:inherit` so the button reset doesn't fight its own existing `border-bottom` active-state indicator -- the same longhand-vs-shorthand trap almost bit this fix: `border:none` alone would have killed the *intentional* `border-bottom` too, so the class rule keeps `border-bottom` as its own explicit longhand after the reset). `evShowTab()` now toggles `aria-selected` alongside its existing `.active` class toggle. The detail panel (`#evDetailPanel`, a hand-rolled slide-in panel that predates T02 and doesn't go through `ModalManager`) had no Escape-to-close at all -- added a scoped `keydown` listener.
- `oneforall/modules/erm/templates/index.html`: all 24 `.erm-chip` status/industry filter spans (register status, library industry, external-context status, obligations status, assessments status) converted to `<button type="button">` via a targeted regex substitution (verified against the exact 24 expected matches before writing, not a blind find/replace) -- the shared `initChips(barId, onchange)` wiring function only does `querySelectorAll('.erm-chip')` + `addEventListener('click', ...)`, so it needed zero changes to keep working with buttons instead of spans. `.erm-chip`'s CSS gained `font-family:inherit` (it already set its own `border`/`background`/`font-size`/`font-weight` explicitly, so no other UA button-chrome reset was needed).
- `oneforall/modules/bcm/templates/index.html`, `orm/templates/index.html` (×3), `sentinel/templates/index.html`, `grid/templates/index.html`: fixed the 6 SPA elements missing `href` -- 5 "View All"/"View Events"/"View KRIs" anchors that had `data-spa` but no `href`, and 4 sidebar "Ask <Module> AI..." chat-launcher cards that were plain `<div data-spa="...">` (GRID's used a bespoke `onclick="gridRouter.navigate(...)"` instead of `data-spa`, now brought in line with the other three modules' convention). Confirmed safe before editing: every module's document-level `click` listener does `e.target.closest('[data-spa]')` + `e.preventDefault()`, so adding `href` changes nothing about mouse-click behavior and only adds native keyboard focus/activation plus a working fallback destination.

New files:

- `oneforall/tests/ui/test_evidence_keyboard_accessibility.py` -- 7 tests: stats-bar tiles are real buttons (and the one non-clickable "Links" tile stays a plain div, proving the fix didn't over-convert); a stats-bar tile is keyboard-focusable and Enter-activates `switchView` (red/green-proved by reverting one tile to a bare div); recent/grid cards render as buttons; the link-entity dropdown's search-result rows are buttons (exercised through the real `openLinkToModal`/`searchEntities` flow, not a synthetic DOM -- an earlier version of this test hand-built duplicate `#linkModule`/`#linkEntityType` elements to avoid opening the real modal, which silently failed because `document.getElementById` found the *real*, empty modal elements first, not the injected ones; fixed by driving the actual modal instead of trying to shortcut around it); the detail-panel tabs carry tab semantics and toggle `aria-selected` on click; Escape closes the detail panel (red/green-proved by disabling the new keydown listener); the toast container is a live region.
- `oneforall/tests/ui/test_erm_chip_filters_keyboard.py` -- 1 test: register status chips are all real buttons, and Tab+Enter on the "Open" chip toggles `.active` correctly (red/green-proved by reverting the register chips back to spans). This test's first draft failed for an unrelated reason worth recording: `initChips('regFilterBar', ...)` is only wired up *after* `ermLoadRegister()`'s own `await apiFetch('/erm/api/register')` resolves, but the filter-bar buttons already exist in static markup from page load -- so a test that clicks immediately after the buttons appear in the DOM (rather than waiting for `networkidle`) races the click against the listener not being attached yet. This would have raced identically for a mouse click before this session's change; it is a pre-existing timing characteristic of the page, not something the span-to-button conversion introduced. Fixed by waiting for `networkidle` before interacting, matching this suite's existing convention elsewhere.

Verification commands and results:

1. `pytest tests/ui/test_evidence_upload_error_detail.py tests/ui/test_modal_contract.py tests/ui/test_task_board_and_my_dashboard_migration.py tests/ui/test_erm_library_and_email_reset.py tests/ui/test_apifetch_migration_smoke.py -q` (existing suites covering every file touched this session, run before adding new tests) -- 32 passed.
2. `pytest tests/ui/test_evidence_keyboard_accessibility.py tests/ui/test_erm_chip_filters_keyboard.py -q` -- 8 passed, after two genuine debugging detours (both documented above under "New files", not glossed over).
3. **Red/green proof #1** (Evidence stats-bar keyboard operability): temporarily reverted the "Expiring 30d" tile from `<button>` back to `<div onclick=...>` -- `test_stats_bar_card_is_keyboard_operable` failed (Enter no longer reached `switchView`). Restored; passed.
4. **Red/green proof #2** (Evidence detail-panel Escape close): temporarily changed the new listener's key check from `'Escape'` to `'EscapeDISABLED'` -- `test_escape_closes_the_detail_panel` failed (panel stayed open). Restored; passed.
5. **Red/green proof #3** (ERM chip keyboard operability): temporarily reverted all 6 register-view chips from `<button>` back to `<span>` -- `test_register_status_chips_are_buttons_and_keyboard_operable` failed. Restored; passed.
6. `pytest tests/ui/test_axe_acceptance_routes.py -q` after the structural/keyboard fixes but before any color change -- **0 failures, 5 xfail** (down from the session-1 baseline of 11 routes with at least one finding), confirming `select-name`/`label` were fully resolved independent of the (larger, separately-decided) color-contrast question.
7. `pytest tests/ui/test_axe_acceptance_routes.py -q` again after every color fix below -- **0 failures, 0 xfail.** All 21 acceptance routes now pass clean.
8. Full browser suite, `pytest tests/ui -q`, run three times across this session (after the structural/keyboard fixes; again after the color fixes) -- all three clean, 0 failures.
9. Full backend suite, `pytest tests --ignore=tests/ui -q`, run twice (same checkpoints). First run clean. Second run (after the color fixes) had one failure in `test_webhook_test_endpoint.py::test_test_endpoint_reports_real_failure_never_fake_success` (`response_code==0` instead of `500`). Five immediate isolated reruns passed, so this entry originally classified it as a generic localhost timing failure. The 2026-09-29 follow-up above established the concrete test-fixture cause: the local HTTP handler did not consume the POST body before closing its HTTP/1.0 connection, allowing an intermittent Windows reset. The fixture now drains the request body before responding.
10. `python -m compileall -q oneforall` -- exit 0 (this session touched no Python).
11. `git fetch origin --prune` + `git rev-parse origin/master` -- matches local HEAD (`2b98cc4...`) exactly; no reconciliation needed at session start.

Color contrast: implemented, with the user's explicit sign-off on the approach (asked via a direct choice between "darken the specific text usages," "review each one with me first," and "leave for now"; the user chose the first). Every finding was diagnosed by direct contrast-ratio measurement against the actual rendered colors (a throwaway diagnostic axe scan reading `nodes[].any[].data.fgColor/bgColor/contrastRatio` directly, never guessed or assumed to generalize from one module to another), then fixed by computing a minimally-darkened, same-hue-and-saturation replacement via the WCAG relative-luminance formula (binary search on HSL lightness), reusing an existing darker "-mid"/"-dark" variant where the numbers showed one already cleared 4.5:1, or a newly-computed hex where none did.

What was actually wrong, per route (some of this corrected an earlier assumption in this very session, not just session 1's):

- **`/grid/`**: `.btn-primary`/`.nav-item.active` -- white text on GRID's own `--accent` (#059669) is 3.76:1. Every *other* module's own `--accent` already clears 4.5:1 (verified all 7, not assumed) using the plain `--accent`/`--accent-mid`/`--accent-dark` values already defined in `base_shell.html`'s `[data-module="X"]` blocks, so the fix is a GRID-only override (`[data-module="grid"] .btn-primary,[data-module="grid"] .nav-item.active{background:var(--accent-mid)}`, hover pushed to `--accent-dark` so it still visibly darkens further on hover), not a change to the shared rule every module uses.
- **`/aria/documents`** and **`/sentinel/`**: both are actually the *same* underlying bug, `.module-name` (the sidebar's "Governance"/"Privacy" header) using `--accent-mid` -- ARIA 3.80:1, Sentinel 4.37:1. This session's own first assumption (copied from GRID's diagnosis: "same brand-accent-vs-white-text finding as GRID") was wrong for Sentinel specifically -- Sentinel's plain `--accent` actually already passes at 5.67:1; a fresh diagnostic scan of `/sentinel/` directly (rather than trusting the inherited assumption) found the real selector. Fixed by switching the shared `.module-name` rule to `--accent-dark` -- verified safe for all 7 modules (ARIA 8.64:1, Sentinel 8.20:1, and every other module's already-passing accent-mid only gets a bigger margin from an even-darker value, since darkening a color that is compared against a light background can only raise contrast, never lower it).
- **`/my-dashboard`**: the shared `--good` semantic color (#16a34a, used for "healthy/positive" stat text like "0/324 controls") is 3.13:1 on `--surface2`. Darkened `--good` itself (to #11803a) rather than inventing a parallel `--good-text` variable, since every other consumer of `--good` (backgrounds, borders, icons) can only gain contrast from a darker shade, never lose correctness. `--green-status`, a separate variable with the same original hex, was deliberately left alone -- it was never verified as failing anywhere, unlike `--good`.
- **`/erm/library`**: two distinct bugs bundled in what looked like one 18-node finding, only one of which this session initially caught. (1) The `catColors` "soft chip" category badges (`background:col+'22';color:col`) -- worst of all findings, 2.24:1. (2) `.lib-tag`'s `color:var(--muted)` on `--surface3` (4.28:1, also shared verbatim by `base_shell.html`'s `.badge-draft`) -- this is the *same* pairing this session had manually calculated earlier as "probably moderate, not gate-blocking" and deliberately left alone; that assumption was wrong (axe's own `run_axe()` fixture only returns critical/serious by default, and this was one of the 18 nodes from the start), caught only because the fix for (1) alone didn't clear the route and a second diagnostic pass was run rather than assuming the first pass had found everything. `.lib-tag` and `.badge-draft` both switched to `--text-mid` (9.14:1), the same safe reuse session 1 already established for `.sidebar-label`.
- **A genuine calculation bug caught by axe itself, not self-detected**: the first `catColors` fix computed each darkened color against a tint of the *original* brighter color, but the template uses the same variable for both the tint and the text (`background:col+'22';color:col`) -- so darkening the text also darkens the tint it's measured against, partially undoing the fix. Axe's re-measurement came back at 4.23-4.48 (short of 4.5) instead of the 4.75 computed. Re-solved self-consistently (foreground vs. a tint of *itself*, not of the original color) and re-verified clean.
- **A second near-miss from rounding**: a first attempt targeted exactly 4.50 for `--good` and the `catColors` set; axe's own color math (browser compositing rounding) measured some of those a hair under 4.5 (4.48, 4.23) despite Python computing >=4.50 for the same nominal values. Every final color was retargeted to ~4.75:1 for margin, and re-verified against axe's actual measurement, not just the Python calculation, before being accepted as fixed.

Explicitly out of scope, found but not fixed:

- **Dark mode's `.module-name` contrast is a separate, pre-existing defect**, unrelated to anything asked or fixed this session, discovered only because the light-mode fix had to be checked for a dark-mode regression first. `[data-theme="dark"]` does not override `--accent`/`--accent-mid`/`--accent-dark` (only `--accent-pale`/`--accent-bg`), so `.module-name`'s color and the sidebar's own dark glass-panel background are already set independently of each other today -- measuring the *current, unmodified* `--accent-mid` against dark mode's own sidebar background shows only ARIA (4.65:1) currently passes; GRID/sentinel/platform/bcm/erm/orm are all already failing in dark mode right now (2.2-3.9:1), before this session touched anything. Applying this session's own light-mode fix (`--accent-dark`) with no dark-mode override would have made every one of those regress further (near-black text on a near-black background, 1.3-2.2:1) -- caught before shipping, not after. Mitigated, not fixed: added `[data-theme="dark"] .module-name{color:var(--accent-light)}`, which fixes ARIA/GRID/Sentinel/platform in dark mode (6.7-9.2:1) and measurably improves BCM/ERM/ORM (2.6-2.9 -> 2.8-4.25) without fully clearing 4.5:1 for those three -- full dark-mode compliance for those three would need genuinely new colors invented for dark mode specifically, which is a real design task of its own, not a "reuse an existing variant" fix, and was judged out of proportion to add unilaterally to a light-mode-focused, already-large session. Flagged here as a named follow-up, not silently left for someone to rediscover.

Visible focus (T07 step 8, partial): a repo-wide scan (regex over every `.html` under `modules/`+`templates/`) for a selector setting `outline:none`/`outline:0` with no `:focus`/`:focus-visible` rule anywhere in the same file providing a visible replacement found exactly 2 real instances out of 25 files using `outline:none` at all -- `.aria-draft-editor` (`modules/aria/templates/ai_generator.html`, the main policy-draft textarea, previously had no visible focus indicator at all: no outline, no border, nothing) and `.tl-module-sel` (`modules/launcher/templates/timeline.html`, a filter `<select>` that removed the native outline and put nothing in its place). Both fixed with a box-shadow ring matching `base_shell.html`'s own established `.form-input:focus` convention (`.aria-draft-editor` uses `inset` since it's a full-width borderless surface; `.tl-module-sel` uses the same outward ring as `.form-input`). Both red/green-proved (temporarily removing each new `:focus` rule) with new tests in `tests/ui/test_visible_focus_indicators.py`. The draft-editor test needed a specific workaround worth recording: `#draftEditor` is only visible after opening/starting a draft (a multi-step, possibly-AI-dependent flow well beyond this fix's scope, gated behind an ancestor's own show/hide state this test doesn't reverse-engineer) -- rather than drive that whole flow, the test injects a throwaway `<textarea class="aria-draft-editor">` into the already-loaded page and checks its own focus state, which exercises the real shipped CSS rule as the real browser parses it, not a reimplementation of the check. The other 23 files' `outline:none` usages were confirmed (by the same scan) to already have some visible-replacement `:focus` rule in the file; not individually verified as the *matching* one for every single selector, so this is a heuristic pass, not an exhaustive per-selector audit. Tab order, 200% zoom, and reduced-motion were not checked this session.

Explicitly unverified/skipped:

- A broader "interactive chip/badge" sweep beyond ERM: a repo-wide check found `class="...chip..."` spans in `aria` (9 across 5 files), `bcm` (6), `grid` (8), `admin_users`/`launcher`/`projects` (3), `task_board` (5), `timeline` (4), `orm` (3), and `sentinel` (31) -- ERM's 24 were fixed because they were unambiguously interactive (wired through the shared, generically-tag-agnostic `initChips()`) and already flagged by axe. The others were not individually triaged this session; many are likely decorative/non-interactive status badges that should *not* become buttons (adding button semantics to a non-interactive element is its own accessibility anti-pattern), so this needs per-instance judgment, not a blind bulk conversion, and is left as a named follow-up rather than guessed at.
- `#regSelectAll`-style "select all" checkboxes in GRID's and ORM's own tables (found via the same grep pattern) were not checked for the same missing-label gap ERM's had -- neither route currently fails axe's `label` rule for it, so it wasn't chased without evidence it's actually broken there, but it's worth a direct look before assuming it's fine.
- T07's remaining named steps not addressed this session: full div/span-to-button conversion beyond Evidence/ERM (see above), tab order/200%-zoom/reduced-motion/keyboard-trap verification, dialog-semantics review against the T02 `ModalManager` contract, and manual keyboard scripts for flows automation can't prove.
- No commit, push, migration, service restart, or deployment was performed. No production host or data was touched.

## 2026-09-25 T07 session 1 — skip link/landmark/accessible names, plus a sitewide template bug found along the way

Outcome: T07's first few steps (skip link + main landmark, several named accessible-name gaps, one div-as-button conversion) landed cleanly, but building the axe-core acceptance-route suite (T07's own step 9) surfaced a genuine, previously completely invisible bug affecting 22 templates across nearly every module: a nested `<style>` tag that silently truncated `base_shell.html`'s own stylesheet and, on one ARIA template, its shared script includes. This was found and fixed. The axe-core suite itself is built and running against the plan's named acceptance routes; a handful of real, not-yet-fixed findings remain, tracked explicitly rather than glossed over -- one of them (a brand accent-color contrast ratio used site-wide for primary buttons and active nav) is deliberately paused for explicit sign-off before touching it, since it's a visual-branding change, not a structural-markup one.

Files changed:

- `oneforall/templates/base_shell.html`: added a skip link (`<a href="#mainContent" class="skip-link">`, visually hidden until keyboard-focused, real underline so it isn't distinguished by color alone -- axe caught this specifically) as the first focusable element after `<body>`; converted the `<div class="main-content" id="mainContent">` wrapper to a real `<main>` landmark with `tabindex="-1"` (so the skip link's fragment jump actually moves keyboard focus there, not just scrolls to it -- a `<main>` isn't natively focusable). Added `.sr-only` (a standard visually-hidden-but-in-the-accessibility-tree utility, the clip-rect pattern, not `.skip-link`'s off-screen-position pattern, which only reveals itself on focus and would never reveal a non-focusable `<label>`). The notification bell button had no accessible name at all (an SVG icon, nothing else) -- added `aria-label`, `aria-haspopup`, `aria-expanded` (now wired live in `toggleNotif()`), `aria-controls`. The sidebar-toggle button had only a `title` (not reliably announced by screen readers) -- added `aria-label` alongside it. `.sidebar-label` (section headers in every module's sidebar) used `--dim`, which fails WCAG AA contrast for real text at that size -- switched to `--muted`, a darker gray this same file already uses for real text elsewhere (`.nav-item`), rather than inventing a new color. `.module-name` (each module's sidebar header) used `--accent` for text color, also failing contrast in at least GRID's green theme -- switched to `--accent-mid`, a darker variant this codebase's own per-module color palette already defines for exactly this need, confirmed defined for all 7 modules plus the `:root` fallback before changing a rule every module's sidebar shares.
- `oneforall/templates/_platform_trainer.html`: the floating "Themis" chat bubble (`.trainer-icon`) was a `<div onclick=...>` with zero keyboard support -- converted to a real `<button>` (its CSS already set `background`/`cursor` explicitly; added `border:none;padding:0;font:inherit` to neutralize the browser's default button chrome, the standard reset for this exact conversion) with `aria-label`, `aria-haspopup`, `aria-expanded` (wired in `toggleTrainer()`). The close button (`&times;`, already a real `<button>`) and the send button (an SVG-only `<button>`) both had zero accessible name -- both real `<button>` elements already, just missing `aria-label`. The tooltip-mode toggle had a `title` only -- added `aria-label` and `aria-pressed` (wired in `toggleTooltipMode()`, matching the existing `.active` class toggle it already did). The chat input (`#trainerInput`) had no associated label at all -- added a `.sr-only` `<label for="trainerInput">` (visible placeholder text doesn't substitute for a real accessible name per WCAG).
- `oneforall/modules/launcher/templates/task_board.html`: the "My Tasks" toggle (`.tb-mine-btn`) was the same div-as-button pattern as the trainer bubble -- converted to `<button>` with `aria-pressed` (wired in `toggleMine()`); its CSS already had `border`/`padding` explicit, only needed `font-family:inherit` added. The module filter `<select>` had no label at all (axe: critical, not just serious) -- added a `.sr-only` label.
- **The sitewide bug** (`oneforall/templates/command_centre.html` plus 21 more files across `aria`, `bcm`, `grid`, `sentinel`, and `launcher`): `base_shell.html` has one `{% block extra_styles %}{% endblock %}` marker sitting inside its own already-open `<style>` tag, specifically so child templates can add page-specific CSS without repeating `<style>` boilerplate. 22 templates ignored that contract and wrapped their own `<style>...</style>` around their content anyway. Since HTML's `<style>` element is a raw-text element (its content is read literally up to the *first* `</style>`, with no concept of "nesting"), the child's own `</style>` closes `base_shell.html`'s outer tag early -- meaning any CSS `base_shell.html` itself defines *after* that block marker becomes ordinary (non-rendering) HTML text, not real CSS, on every page using an affected template. This was 100% invisible until this session, because nothing had ever been placed after that marker before. Fixed all 22 by removing the redundant `<style>`/`</style>` wrapper from each. One template (`modules/aria/templates/base.html`) additionally had a `<script src=".../chart.js">` tag inside the same broken region -- meaning Chart.js was never actually loading as a script on any ARIA page extending it either (same raw-text-mode mechanism: a `<script>` tag positioned inside an open `<style>` region is inert text, not a real script element). Moved it into that same template's existing `{% block extra_scripts %}` (which already correctly includes two other shared ARIA scripts, confirmed positioned *outside* any `<style>` tag before moving anything there). While tracing this, found `modules/aria/templates/dashboard.html` overrides that same `extra_scripts` block without calling `{{ super() }}` (unlike `ai_generator.html`, which does it correctly) -- meaning `dashboard.html` was separately, independently missing the base template's shared scripts (`ai-guidance-dialog.js`, `thinking-trace.js`, and now chart.js) regardless of the style-tag bug. Added the missing `{{ super() }}` call.

New files:

- `oneforall/tests/ui/vendor/axe.min.js` -- axe-core 4.10.2, downloaded once and vendored locally (not fetched from a CDN at test time) specifically so the accessibility test suite has no live-network dependency and behaves identically in an offline CI runner.
- `oneforall/tests/ui/conftest.py`: new `run_axe` fixture -- injects the vendored axe-core into the current page and runs a real `axe.run()` scan, returning only `critical`/`serious` impact violations by default (matching T07's own completion-gate wording exactly), with an `impacts=` override available for a test that wants the fuller picture.
- `oneforall/tests/ui/test_axe_acceptance_routes.py` -- parametrized across the 21 routes task_plan.md's own "Acceptance routes" line names, one persona (`super_admin`, since the gate is about the page's own markup, not per-role authorization, which is already covered elsewhere) per route. A route with a real, found, not-yet-fixed violation is marked `xfail` with the specific violation id and a real reason in a `KNOWN_FAILURES` dict -- removed in the same change that fixes it -- rather than either silently excluded or left failing the whole suite.

Verification commands and results:

1. **The bug-discovery sequence itself, kept here because it is the evidence this was found by investigation, not assumed:** added the skip link and `.sr-only` CSS to `base_shell.html`; `run_axe()` on `/` still reported the skip link's own `link-in-text-block` finding after the CSS was added. Directly inspected `getComputedStyle()` on `.skip-link` in the real browser: none of `color`/`background`/`text-decoration` were applying despite being clearly present in the source. Queried `document.styleSheets` for any rule matching `skip-link`: zero found, while a rule immediately *before* the insertion point (`.sidebar-label`) and rules from an entirely separate `<style>` tag much later in the DOM (`_platform_trainer.html`'s own) both were found -- isolating the break to content positioned between those two points in `base_shell.html`'s own stylesheet, not a global parse failure. Found `command_centre.html`'s `extra_styles` block wraps its own `<style>` tag at exactly that position; confirmed 21 more templates share the identical pattern via a repo-wide grep for a `<style>` tag immediately following a `{% block extra_styles %}`/`{% block head %}` open.
2. Fixed all 22 templates (21 via a small one-off script removing the specific `<style>`/`</style>` line pair per file, spot-checked against 3 files' exact structure before running it; 1 -- `aria/templates/base.html`, whose block has an extra `<script>` line the script's narrower line-window didn't match -- fixed by hand, same edit).
3. **Immediately introduced and then caught a second bug while writing the explanatory comment for fix #2**: used an HTML `<!-- -->` comment containing the literal text `{% block extra_styles %}` as an illustrative example. Jinja does not respect HTML comment boundaries -- it scans the raw template text for `{% %}` delimiters unconditionally, so that literal example text was parsed as a second, real `{% block extra_styles %}` open tag, unbalancing the file's block count. This crashed every request to `/` with `jinja2.exceptions.TemplateSyntaxError: Unexpected end of template` (caught via the full browser UI suite, not missed). Fixed by rewording the comment to describe the tags in prose instead of pasting literal Jinja syntax; confirmed the codebase's one pre-existing comment that does this correctly uses Jinja's own `{# ... #}` comment syntax instead of an HTML comment, which Jinja *does* parse specially and skip.
4. `pytest tests/ui -q` (full browser suite, run after fixes #2 and #3 above) -- clean, 0 failures, exit 0. Re-ran `run_axe()` fresh against `/`: 0 critical/serious violations (down from the 2 found at the start of this session: `color-contrast` on `.sidebar-label`, `link-in-text-block` on the new skip link).
5. Spot-checked 9 more acceptance routes directly (`/bcm/`, `/grid/`, `/admin/connectors`, `/tasks`, `/sentinel/`, `/orm/`, `/erm/`, `/aria/documents`) for console errors (none -- confirms the template fix holds beyond just `/`) and fresh axe results: `/bcm/`, `/admin/connectors`, `/orm/` clean; `/tasks` had one real `select-name` finding (fixed, see Files above, then reconfirmed clean); `/grid/`, `/sentinel/`, `/erm/`, `/aria/documents` have real remaining findings, listed explicitly in `KNOWN_FAILURES` above rather than silently left out of the new test file.
6. Full backend suite and full browser suite re-run one more time after all fixes in this entry: pending, see next entry once background runs complete.

Explicitly unverified/skipped:

- The GRID/Sentinel brand-accent-color contrast findings (`.btn-primary`/`.nav-item.active`: white text on the module's own accent background falls short of 4.5:1 in at least GRID's green and Sentinel's theme). Deliberately not fixed this session: `--accent` is each module's own brand color, used extremely broadly (primary buttons, active nav, likely much more); a compliant fix means either darkening the affected modules' `--accent` itself or repointing specific shared rules like `.btn-primary` to `--accent-mid`, either of which changes site-wide visual branding for however many modules are affected, not just structural markup -- exactly the kind of change this session's actual established pattern (many strict Task Board/GRID/other fixes today) treats as needing explicit user awareness first, unlike the sidebar-label/module-name text-contrast fixes already made (smaller, more clearly-scoped, still reused an existing "-mid" variant rather than inventing a new color).
- `/erm/`'s and `/aria/documents`'s specific `select-name`/`color-contrast` findings: identified as real (not yet investigated to the same per-element detail as GRID/Task Board's were) and tracked in `KNOWN_FAILURES`, not fixed.
- The remaining 21 acceptance routes not yet individually spot-checked (`/my-dashboard`, `/reports`, `/calendar`, `/risk-register`, `/people`, `/admin/users`, `/admin/api-keys`, `/erm/register`, `/erm/library`, `/erm/external`, `/evidence`, `/governance`): covered by the new parametrized test file, but results not yet reviewed at the time of writing this entry.
- T07's remaining steps (div/span-to-button conversion beyond the two found so far, SPA anchor `href` audit, T02 modal semantics reuse confirmation, toast live-region behavior, visible-focus/tab-order/200%-zoom/reduced-motion/keyboard-trap verification, manual keyboard scripts) are not started.
- No commit, push, migration, service restart, or deployment was performed. No production host or data was touched.

## 2026-09-25 T06 session 1c — GRID, Task Board, My Dashboard, Command Centre (F08 complete for its named modules)

Outcome: closes out every module F08 names by name. GRID had its own shared wrapper too (named `api()`, not `apiFetch` -- missed by session 1b's name-based grep, found by actually reading the file) with a worse bug than any seen so far: it discarded every error and returned `null`, indistinguishable from "no data." Task Board, My Dashboard, and Command Centre (the last one not touched at all until this pass, despite being named explicitly in F08) had no shared wrapper and needed per-call-site migration. `api_client.js` gained blob-download support (`expect: 'blob'`) for GRID's PDF/DOCX report downloads, the one response shape not yet covered.

Files changed:

- `oneforall/modules/grid/templates/index.html`: the `api(url,methodOrOpts,body)` wrapper (~90 call sites through it) migrated with a **deliberately different contract decision than every other module this session**: kept "return null on any failure" exactly as before, rather than switching to throw. Reasoning: unlike ERM/BCM/Sentinel/ORM (each with 10-30ish call sites, spot-checked before migrating), GRID's 90 call sites include many that already do `if(res&&res.id){success}else{showToast('Failed to X')}` -- switching to throw without auditing every one of the 90 risked turning an already-handled failure into an uncaught exception, and risked double-toasting wherever a caller's own generic message would stack with a new one added inside `api()`. What GRID's `api()` still gets for free: real timeout/abort protection (the old code could hang forever) and a classified error in its console.warn log instead of a raw exception. Five additional individual mutations not behind `api()`: `deleteAudit` (already reasonable error handling, migrated for consistency), evidence upload/replace (already reasonable, simplified), AI parse-checklist (fixed the "unconditional response.json()" pattern -- a non-JSON error response would previously have thrown inside the try block with a generic caught message; now gets the real detail), AI generate-checklist (same fix, plus a **found-and-fixed pre-existing XSS gap**: the failure branch inserted the server's error message into `innerHTML` without the `esc()` helper this same file uses everywhere else for exactly this purpose), and the report-download function (migrated onto the new `expect: 'blob'` mode). Two reads left deliberately quiet: a Sentinel active-breach banner check and an IMS-framework dropdown supplement inside the New Audit modal -- both non-critical enhancements to an otherwise-working view, matching the plan's own background-panel carve-out.
- `oneforall/modules/launcher/templates/task_board.html`: 9 of 10 fetch call sites. `loadUsers`/`loadTasks` were fully silent on failure despite being the page's actual primary content (not a background panel) -- now show a toast. `bulkSetField`, `aiPrioritize`, `applyAiPriorities`, `saveDrawer`, `confirmDeleteTask`, `submitNewTask` already had reasonable-shaped handling; migrated for the real detail message and timeout protection. The drag-and-drop status move (`onDrop`) had the same "raw fetch doesn't reject on non-2xx" bug as several other fixes this session: a server-rejected move (invalid transition, permission denied) previously left the optimistic local UI update in place with nothing to catch and revert it. `updateStats()` (a small supplementary stat-row refresh, not primary content) left quiet deliberately.
- `oneforall/modules/launcher/templates/my_dashboard.html`: all 3 (`loadPrefs` stays quiet -- a preference load with a sane in-code default is a legitimate background case; `savePref` was completely silent despite being a real mutation the user might act on, e.g. hiding a widget, with no way to know it didn't persist; `loadDashboard` -- the page's entire primary content -- did `if (!resp.ok) return;`, leaving a blank page with zero explanation on any failure).
- `oneforall/templates/command_centre.html`: served at `/`, the first page after login, and F08 names it explicitly, yet nothing had touched it before this pass. `ackAdvisory` and `acknowledgePrediction` previously reset their button on failure with no message at all. `exportReport`/`generateBoardReport` (two-step: create a report definition, then run it) already showed a generic toast; now show the real detail, and simplified from manual `resp.ok`/`throw new Error(...)` chains into two `ApiClient.request` calls each. Also fixed two stray em dashes in the two success-toast strings this pass rewrote anyway (`'Export ready — opening Reports'` etc.) -- consistent with this session's own no-em-dash convention, not applied retroactively to lines this pass didn't otherwise touch. `loadDashboard`/`loadBriefing` (the page's main data load) were deliberately left on their existing pattern: unlike most other "silent" loads fixed this session, these already fall back to a real static `fallback` object on any failure rather than showing nothing, which is a legitimate, more sophisticated version of the same graceful-degradation the plan's carve-out describes -- migrating the transport without touching that fallback behavior wasn't judged worth the risk for a page this central, given time already spent; `loadPredictiveRisk`, a self-contained panel with its own manual refresh control, migrated onto `ApiClient.request` for the timeout benefit while keeping its existing console-only failure UX.
- `oneforall/static/js/api_client.js`: `request()` gained `expect: 'blob'`, returning `{blob, filename}` (filename parsed from `Content-Disposition` when present) instead of parsed JSON -- the one response shape not yet needed by any earlier migration this session.

New files:

- `oneforall/tests/ui/test_grid_migration_smoke.py` -- 2 tests: the dashboard loads and makes a real `/grid/api/` request (the test that actually matters for the "keep returning null" decision above -- if the migrated `api()` were broken, this is what would catch it, since nearly the whole page depends on it), and `deleteAudit` surfaces a real route-intercepted 409 detail.
- `oneforall/tests/ui/test_task_board_and_my_dashboard_migration.py` -- 4 tests: Task Board loads and a new-task validation failure shows the real detail; the drag-and-drop move's fix specifically (exercised directly against a route-intercepted rejection, not via simulated DOM drag events -- a real `DataTransfer`-bearing drag event is fragile to fake reliably and the part actually under test, the request/catch/toast, is already proven generically in `test_api_client.py`); My Dashboard loads via a real `/api/my-dashboard/` request; a data-load failure shows a toast instead of leaving the page blank.
- `oneforall/tests/ui/test_command_centre_migration.py` -- 2 tests: the root page loads clean, and a failed advisory-ack re-enables its button and shows the real permission-denied detail (previously: silent reset, no message).
- `oneforall/tests/ui/test_api_client.py`: +1 test for the new `expect: 'blob'` mode (fulfills a fake PDF response with a `Content-Disposition` header, asserts the returned filename and blob content).

Verification commands and results:

1. `pytest tests/ui/test_grid_migration_smoke.py tests/ui/test_task_board_and_my_dashboard_migration.py tests/ui/test_command_centre_migration.py -v` -- 8 passed.
2. `pytest tests/ui/test_api_client.py -v` -- 16 passed (15 from earlier sessions + the new blob test).
3. Full backend suite, `pytest tests --ignore=tests/ui -q` -- one failure in `tests/test_webhook_test_endpoint.py::test_test_endpoint_is_rate_limited_per_actor_and_webhook`, a 502 where 200 was expected. Six of seven isolated reruns passed, so this entry originally left it as unexplained local-server timing. The 2026-09-29 follow-up above found and fixed the fixture bug: its HTTP/1.0 handler closed the connection without first consuming the POST body, intermittently causing a Windows connection reset. Production webhook code was not implicated.
4. Full browser suite, `pytest tests/ui -q` -- clean, 0 failures, exit 0.
5. Repo-wide raw-`fetch(` census after this pass: 34 files still contain at least one `fetch(` call. Spot-checked the list: files already migrated this session appear only for their deliberate quiet-background-read carve-outs (documented per-file above); ARIA's other 8 templates (`ai_generator`, `ask`, `base`, `dashboard`, `framework`, `mapping`, `risks`, `templates` -- `documents.html` is migrated) and a handful of lower-traffic admin/reporting pages (`admin_api_keys`, `admin_frameworks`, `admin_logs`, `admin_security`, `admin_users`, `analytics`, `calendar`, `people_directory`, `reports`, `risk_register`, `timeline`, `vendor_directory`, `governance/index.html`, `_platform_trainer.html`) were never in F08's named list and are not covered by this pass.
6. Em-dash sweep on every file this pass touched, checked around each `PLAN-36 T06` marker -- zero matches, except the two Command Centre strings named above that this pass rewrote anyway and fixed as part of that same edit.

Explicitly unverified/skipped:

- ARIA's 8 other template files and the ~13 lower-traffic admin/reporting pages listed above (item 5): none is in F08's named list, none was touched. A genuinely exhaustive "every fetch in the app" sweep would need to cover these; T06's own completion gate ("no action in the critical-action registry uses naked fetch unless documented") is judged met for the registry's actual current entries (all migrated or explicitly out of scope), not for every fetch call that exists in the codebase, which is a broader claim than either F08 or the task's own step list makes.
- A dedicated test for GRID's `api()` beyond the one page-load + one `deleteAudit` test: with ~90 call sites behind one function whose contract deliberately didn't change, the highest-value thing to prove was "the migrated wrapper still works for real requests," which the page-load test with real network-traffic assertion does; testing all 90 individually was never proportionate even before this session's time budget, and remains a good T08 (regression-suite completion) candidate if deeper coverage is wanted later.
- PostgreSQL-specific behavior: none of this pass's changes touch SQL. Not applicable rather than unverified.
- No commit, push, migration, service restart, or deployment was performed. No production host or data was touched.

## 2026-09-24 T06 session 1b — connectors, ARIA edit/delete, Evidence, and six apiFetch wrappers (F08)

Outcome: continuing directly from session 1's foundation (same day), this pass covers `admin_connectors.html` individually, ARIA document edit/delete, all 8 of Evidence's mutation functions, and -- the highest-leverage piece -- six pre-existing hand-rolled `apiFetch(url,opts)` wrappers (ERM, BCM, Sentinel, ORM, super_admin, workflows) that were each already the single chokepoint their whole module's SPA called through. Migrating each wrapper once upgrades every call site behind it, rather than requiring one migration per site across several thousand lines of template JS. Also fixed a real script-load-order bug this work surfaced, which would otherwise have been a landmine for every subsequent migration in this session.

Files changed:

- `oneforall/templates/base_shell.html`: **bug fix, not a stylistic move.** `api_client.js` was loaded at the end of `<body>` (session 1's placement, matching `modal_manager.js` immediately above it). `admin_connectors.html` calls `loadStatus()` as a bare top-level statement (not wrapped in `DOMContentLoaded`, unlike the two pages migrated in session 1) -- so it ran before the end-of-body script had loaded, throwing `ReferenceError: ApiClient is not defined` on every page load. Root cause, not the one symptom: moved `api_client.js` to load immediately after `<body>` opens, before any child template's inline script can run, so no future migration can hit this same race regardless of whether that page's own init call happens to be `DOMContentLoaded`-wrapped or not. `modal_manager.js` was left in its original end-of-body position -- no evidence it has the same problem anywhere, and moving it wasn't needed to fix this bug.
- `oneforall/modules/launcher/templates/admin_connectors.html`: `_post()` (shared by save/test-slack/test-teams/test-whatsapp) now catches `ApiClient.request` and normalizes both a body-level `{ok:false}` and an HTTP-level `ApiError` into the one shape its callers already handled, so none of those four callers needed changes. `removeSlack/Teams/Whatsapp()` previously `await fetch(...)` and discarded the result unconditionally -- the most severe F08 instance found this session, worse than "shows a generic message": a failed remove looked identical to a successful one, with literally nothing checked. All three now report a real failure. Also dropped the `X-CSRF-Token` header this file (and 4 others, untouched) sent on every request: confirmed by a repo-wide grep that zero Python files read that header anywhere -- it was already dead weight before this change, not something this migration made dead.
- `oneforall/modules/aria/templates/documents.html`: `submitEdit()` (T01's own managed-edit fix, same file) and `deleteDoc()` migrated. Verified against the actual backend routes' response shape first (`{"ok": true}` success, real 403/404/409/500 status + `{"error": ...}` on every failure, never a 200-with-failure-in-body case) rather than assumed, since the frontend's old `res.ok && data && data.ok` double-check suggested it might have been guarding against a shape that, on inspection, this route never actually produces.
- `oneforall/modules/evidence/templates/evidence_index.html`: 8 functions. `evSaveField`, `unlinkEvidence`, `createLink` were completely silent (no error path existed at all -- assumed success unconditionally). `applyAiLink` was worse: its `try/catch` never checked `res.ok`, so a real 403/500 would resolve normally and show "Linked" as if it had worked. `archiveEvidence`/`restoreEvidence`/`permanentDeleteEvidence` already checked `r.ok` reasonably; simplified onto `ApiClient.request` for consistency, no behavior change intended or observed. `handleUpload` had a real 409-duplicate-file branch that reads `existing_id`/`existing_title` out of the error body to build a "View Existing / Link Existing" recovery UI -- `ApiClient.ApiError` only carried a `.detail` string, not enough for this, so `api_client.js` gained a new `.body` field (the parsed JSON error body, `null` when there isn't one) rather than leaving this one call site unmigrated; also fixed `handleUpload`'s other silent gap (any failure that wasn't 409 and wasn't `r.ok` fell through every branch and did nothing).
- `oneforall/modules/erm/templates/index.html`, `bcm/templates/index.html`, `sentinel/templates/index.html`, `orm/templates/index.html`, `launcher/templates/super_admin.html`, `launcher/templates/workflows.html`: each had its own `apiFetch(url,opts)` (or, in super_admin's case, a differently-shaped equivalent) as the one function its whole SPA's data layer calls through. All six now delegate to `ApiClient.request` internally, keeping each function's own external contract (what it returns, what callers already do with the result) intact so no caller needed to change. Two were worse than "just discards the message": **Sentinel's** `apiFetch` (F08 names this module explicitly) always threw a constant `'API error '+status`, never looking at the response body at all. **super_admin's** `apiFetch` never checked `res.status` at all -- an error response's JSON body would be parsed and hand to the caller exactly like real data, since `fetch()` itself doesn't reject on a non-2xx status. `super_admin`'s migration preserves its old "204 -> `{}`" contract exactly (`ApiClient.request` returns `null` for 204; translated back to `{}` at the boundary) rather than changing what callers receive.
- `oneforall/static/js/api_client.js`: `ApiError` gained a `.body` field (see Evidence above). No other behavior change.
- `oneforall/tests/ui/action_registry.json`: no changes this pass (the two entries touched in session 1 already cover webhooks; connectors/ARIA/Evidence/ERM/BCM/Sentinel/ORM/super_admin/workflows are outside the registry's intentionally-partial ~25-entry coverage from T00, so there was nothing stale to correct here).

New files:

- `oneforall/tests/ui/test_admin_connectors_ui.py` -- 5 tests. `admin_connectors.html` had zero browser coverage before this. Covers a real success, an HTTP-level failure (429) surfacing where only a body-level failure could before, a 400 validation detail on save, and -- the important one -- that a failed Remove now shows something instead of nothing.
- `oneforall/tests/ui/test_evidence_upload_error_detail.py` -- 3 tests focused on `handleUpload`, the most structurally complex of Evidence's 8 migrated functions (the only one needing `.body`): the 409 duplicate-file recovery UI still renders correctly with working View/Link-Existing buttons, a non-409 failure now shows a toast instead of nothing, and the success path still closes the modal and refreshes the list. The other 7 Evidence functions are migrated but not each individually browser-tested -- same proportionality call as T05's connector-test coverage (one deep test of the novel/risky path; the simpler, structurally-identical ones lean on the pattern already proven six-plus times this session).
- `oneforall/tests/ui/test_apifetch_migration_smoke.py` -- 8 tests across BCM/Sentinel/ORM/super_admin/workflows (ERM already had `test_erm_library_and_email_reset.py` from T03 to lean on; these five had nothing). Deliberately not just "the page loads": for BCM/Sentinel/ORM, watches the actual network traffic during page load and asserts a real request under that module's `/api/` prefix was made, and for super_admin, waits for `#statOrgs` to actually populate with real org-count text -- proving `apiFetch`'s migration didn't silently break the data layer, not just that the page renders without a JS exception.

Verification commands and results:

1. `pytest tests/ui/test_admin_connectors_ui.py tests/ui/test_evidence_upload_error_detail.py tests/ui/test_apifetch_migration_smoke.py -v` -- 16 passed.
2. `pytest tests/ui/test_aria_managed_edit.py -q` (T01's existing file, unchanged) -- 2 passed, confirming the `documents.html` edit migration.
3. `pytest tests/ui/test_erm_library_and_email_reset.py -q` (T03's existing file, unchanged) -- 4 passed, confirming the ERM `apiFetch` migration didn't disturb the one ERM page with prior coverage.
4. **Root-cause bug found via empirical debugging, not guessed**: `admin_connectors.html`'s Remove-button tests failed with a Playwright "element not visible" timeout, not the expected assertion. Wrote a throwaway diagnostic test dumping `page.console_errors` and confirmed `ReferenceError: ApiClient is not defined`; a second diagnostic confirmed `ModalManager`/`ApiClient` both loaded fine on a bare page load, isolating the bug to *load order* (script tag position) rather than *whether* the script loaded at all, which is what pointed at the actual fix (move the script tag, not add a guard/retry). Diagnostic files deleted after use, not left in the tree.
5. **Red/green proof (implicit, via the fix itself)**: `test_remove_surfaces_a_failure_instead_of_silently_discarding_it` and `test_remove_succeeds_and_refreshes_status` both failed with the exact ReferenceError-caused timeout before the `base_shell.html` fix, and both pass after it -- the fix's necessity is proven by the tests that motivated finding it, not asserted separately.
6. Full backend suite, `pytest tests --ignore=tests/ui -q` -- **clean except one already-documented-category pre-existing flake**: `test_aria_policy_publication.py::test_purge_expired_trash_deletes_only_old_enough_entries` (note: a *different*, sibling test to the one named in T04/T05's entries -- same file, same mtime-vs-`time.time()` boundary-race category, same "purge expired trash" function under test, just checking the opposite side of the assertion). Re-ran in isolation 3 times: 3/3 clean, confirming non-deterministic rather than a regression, consistent with every prior occurrence of this flake class this session. T06 touches nothing related to ARIA trash/purge logic.
7. Full browser suite, `pytest tests/ui -q` -- clean, 0 failures, exit 0.
8. `python -m compileall -q .` -- exit 0 (unaffected; this pass touched no Python).
9. Repo-wide em-dash sweep on every file this pass touched or created, checked specifically around each `PLAN-36 T06` marker comment -- zero matches; the em dashes present elsewhere in these files (UI placeholder glyphs like `'—'` for an empty field, pre-existing section headers) predate this session's edits and were left alone, not "fixed," since they're outside this task's scope and not something this session authored.

Explicitly unverified/skipped:

- GRID (`modules/grid/templates/index.html`, 9 raw `fetch` calls), Task Board (`task_board.html`, 10), and My Dashboard (`my_dashboard.html`, 3) -- F08's remaining named modules. None has a shared wrapper to leverage the way ERM/BCM/Sentinel/ORM/super_admin/workflows did, so each would need per-call-site migration at roughly the pace of the Evidence/ARIA work above, not the one-change-many-sites leverage this pass got from the `apiFetch` files.
- "Modal create forms" as a general category: covered only incidentally, where a create form happened to live inside an already-migrated page (webhook creation, connector save, evidence upload). Modal-hosted forms in GRID/Task Board/My Dashboard or elsewhere are not swept.
- A dedicated test per Evidence function beyond `handleUpload`: judged disproportionate given 6 of the other 7 are now structurally identical one-line-different repetitions of a pattern already proven (in this exact file and five others) rather than open questions.
- PostgreSQL-specific behavior: none of this pass's changes touch SQL. Not applicable rather than unverified.
- No commit, push, migration, service restart, or deployment was performed. No production host or data was touched.

## 2026-09-24 T06 session 1 — shared request/error client + X-Request-ID middleware, first migration wave (F08)

Outcome: the foundational piece (`static/js/api_client.js` + `core/middleware.py::request_id_middleware`) is built and gate-tested on its own terms -- every response shape task_plan.md names is proven via real-browser route interception, not assumed. Two call-site groups are migrated onto it (webhook Test, Email Settings Reset/Save/Test), each proved behavior-preserving or strictly-improved against existing or new browser tests. The remaining migration (ARIA edit/delete, modal create forms, connector tests, Evidence, ERM, and the rest of F08's named modules) is explicitly **not done** -- this is a deliberately scoped first wave, not the full task; see "Explicitly unverified/skipped" below for why.

Files changed:

- `oneforall/static/js/api_client.js` (new) -- single shared `fetch` wrapper: `request(url, options)` classifies every response into either the parsed success value or a typed `ApiError` (`status`, `detail` -- always safe to render, never a raw body/stack/SQL error, `retryable`, `requestId` from the `X-Request-ID` response header, `kind` in `network|timeout|abort|auth|forbidden|validation|conflict|rate_limit|server|parse|unknown`, `retryAfterSeconds` parsed from a 429's `Retry-After` header). Never auto-retries anything (the plan's own constraint: only with a caller-supplied idempotency key on a route that explicitly supports one -- no route does yet, so the client simply never retries; `idempotencyKey` is still accepted and sent as a header so the wire format is ready whenever one does). `withButtonState(button, {pendingLabel, fn})` -- lifts T05's hand-rolled disable/restore-in-`finally` pattern out of `admin_webhooks.html` into a shared helper for the common case. Telemetry reuses the PostHog integration `base_shell.html` already loads (`posthog.capture('api_request', {action_id, status_class, duration_ms, request_id})` on every call, success or failure) rather than standing up a new metrics sink -- no such sink existed anywhere in this codebase to extend, and PostHog's `capture` API already receives exactly this class of event elsewhere via its own `autocapture`.
- `oneforall/core/middleware.py`: new `request_id_middleware` -- accepts an incoming `X-Request-ID` only if it matches `^[A-Za-z0-9_-]{8,64}$` (strict bounded format per the plan), otherwise generates one (`uuid.uuid4().hex`); sets `request.state.request_id` *before* calling `call_next` (so route handlers/error logging during the request can use it, not just the final response header) and echoes it on every response including error responses.
- `oneforall/main.py`: registers `request_id_middleware` as the **outermost** middleware (before `security_headers_middleware`, which the file's own existing comment already documented as "outermost first") -- specifically so the header is never missing even when a later middleware rejects the request early (proved directly, see verification #5 below).
- `oneforall/templates/base_shell.html`: `<script src="/static/js/api_client.js?v=1">`, same cache-busting convention as T02's `modal_manager.js?v=1` immediately above it.
- `oneforall/modules/launcher/templates/admin_webhooks.html`: `testWebhook()`'s hand-rolled `fetch`/`resp.json().catch()`/`data.detail || data.error` extraction (T05, this session) replaced by `await ApiClient.request(...)`, which already does exactly that extraction internally. The richer 3-state choreography (Sending/Delivered/Failed with color + a settle delay before reverting to "Test") stays bespoke rather than using `withButtonState`, since that helper only manages a single pending/restored pair, not three visible states with a delay -- proved behavior-identical by re-running T05's own `test_webhook_admin_ui.py` completely unchanged.
- `oneforall/modules/launcher/templates/admin_email.html`: `loadConfig`, `saveConfig`, and `runTest` (the plan's own named "Email Reset/Save/Test") migrated onto `ApiClient.request`. This is a genuine behavior improvement, not just a lateral rewrite: `saveConfig` previously showed a constant `"Save failed"` string on any error, discarding whatever the server actually said (the exact F08 anti-pattern -- "converts server... failures into missing UI feedback"); it now shows the real `err.detail`. `runTest` previously called `await r.json()` unconditionally regardless of `r.ok` (F08's other named anti-pattern, "unconditional `response.json()`") -- a non-JSON error response (e.g. a proxy page) would have been caught only by the generic catch-all with a fixed message; it now gets `ApiClient`'s proper per-`kind` classification. `runTest`'s button also keeps its own disable/restore (not `withButtonState`) because its resting state is an icon plus text (`btn.innerHTML = '<svg>...</svg> Send Test Email'`), which the generic helper's text-only restore would have destroyed on first use -- confirmed this matters with a dedicated test, not just reasoned through (see below).
- `oneforall/tests/ui/action_registry.json`: the `launcher.admin_email.reset.click` entry's note, still describing the pre-T03-fix `ReferenceError` state even though T03 (an earlier task this same session) had already fixed it, updated to describe the current, correct, now-doubly-tested state.

New files:

- `oneforall/tests/ui/test_api_client.py` -- 14 tests, one per response shape task_plan.md names, all via `page.route()` interception on a real authenticated page (so `base_shell.html` loads the real script under test; the intercepted URL is always a fake `/api/test-endpoint`, never a real route). Includes a hanging-route trick for timeout (`page.route(..., lambda r: None)` -- the request just never resolves until the client's own timer fires) and a genuine `route.abort('failed')` for the network-failure case, so nothing here depends on real network flakiness or a real slow endpoint.
- `oneforall/tests/ui/test_request_id_middleware.py` -- 9 tests. Deliberately **not** a browser test: it needs the real ASGI middleware stack (which only `live_app` provides -- calling a route function directly, this codebase's usual test pattern, bypasses `app.middleware("http")` entirely) but no DOM/JS, so it uses plain `httpx` against the already-running `live_app` server and never imports Playwright.
- `oneforall/tests/ui/test_email_settings_error_detail.py` -- 3 tests proving the F08 fix concretely: Save shows the server's real 400 detail (not "Save failed"); Test shows the server's real 502 detail; the Test button's icon survives a failed attempt (the specific risk the `withButtonState`-avoidance decision above was about -- written to confirm the judgment call, not just to pad coverage).

Verification commands and results:

1. `pytest tests/ui/test_api_client.py tests/ui/test_request_id_middleware.py -q` -- 23 passed.
2. `pytest tests/ui/test_webhook_admin_ui.py -q` (T05's existing file, unchanged) -- 2 passed, confirming the `admin_webhooks.html` migration preserved T05's proven behavior exactly rather than just looking equivalent by inspection.
3. `pytest tests/ui/test_erm_library_and_email_reset.py -q` (T03's existing file, unchanged) -- 4 passed, same confirmation for the `admin_email.html` migration's Reset path.
4. `pytest tests/ui/test_email_settings_error_detail.py -q` -- 3 passed (1 initial failure, same category as T05's: a deliberate 502 test response logs its own "Failed to load resource" browser console message independent of whether the page handled it gracefully; filtered the same way `test_webhook_admin_ui.py` already does, not by loosening what counts as a real error).
5. **Red/green proof #1** (X-Request-ID middleware, the header-setting line itself): temporarily removed `response.headers["X-Request-ID"] = request_id` -- all 9 middleware tests failed. Restored; 9/9 passed.
6. **Red/green proof #2** (`api_client.js`, the 500-HTML-body-leak guard -- chosen because it is the one security-relevant assertion in the new file): temporarily made the non-JSON-response branch fall back to the raw response text instead of the safe generic message -- `test_500_html_never_leaks_the_raw_body` failed immediately. Restored; passed.
7. **Red/green proof #3** (`api_client.js`, the timeout-vs-caller-abort distinction -- chosen because it is the least obvious piece of logic in the file): temporarily collapsed the abort-reason branch so every non-timeout abort was still classified `'timeout'` -- `test_caller_abort_is_classified_as_abort_not_timeout_or_network` failed immediately. Restored; passed.
8. Full backend suite, `pytest tests --ignore=tests/ui -q` -- clean, 0 failures, exit 0.
9. Full browser suite, `pytest tests/ui -q` -- clean, 0 failures, exit 0 (no recurrence of the pre-existing login/base_shell flake this run; still expected to be non-deterministic per T04/T05's own findings, not treated as newly fixed).
10. `python -m compileall -q .` -- exit 0.

Explicitly unverified/skipped:

- **The bulk of T06's own migration list.** ARIA edit/delete, modal create forms broadly (beyond the two forms incidentally covered by the webhook/email pages already migrated), Slack/Teams/WhatsApp connector tests (T05 built `_rate_limited_connector_test` as a shared backend helper already, but the *frontend* buttons for those three still use hand-rolled `fetch`), Evidence upload/link/delete, ERM scan and library actions, and GRID/Sentinel/Task Board/My Dashboard/Command Centre (F08's other named modules) are all still on hand-rolled `fetch`. This was a deliberate scoping decision, not an oversight: F08 alone names 9 modules, and task_plan.md's own step list names 6 more specific path groups on top of that -- attempting all of it in one pass risked exactly the shallow, unproven-per-site coverage this session has otherwise avoided throughout T00-T05. The foundation is built and gate-tested against every response shape the plan names, and the migration *pattern* is proved twice (once as a like-for-like consolidation of this session's own T05 code, once as a genuine bug-fixing migration of T03-era code) with real before/after regression tests, not just written once and assumed to generalize -- the remaining sites are mechanical repetitions of that same proved pattern, not open design questions.
- A dedicated telemetry test: `reportTelemetry`'s PostHog integration is exercised implicitly by every `test_api_client.py` test (it runs on every call and is wrapped in try/catch, so a real page without PostHog blocked/absent would silently no-op rather than fail) but there is no test asserting the specific `posthog.capture` call shape, since intercepting `window.posthog` itself would require either stubbing it before `base_shell.html`'s own PostHog-init script runs (a real ordering dependency) or accepting PostHog's real (blocked-by-CSP-allowlist-in-this-environment anyway) network calls -- judged disproportionate for a fire-and-forget analytics call that already fails safe.
- PostgreSQL-specific behavior: none of this task's changes touch SQL at all (pure Python middleware + static JS + template JS), so this is judged not applicable rather than unverified.
- No commit, push, migration, service restart, or deployment was performed. No production host or data was touched.

## 2026-09-24 T05 session 1 — make webhook testing truthful and harden all outbound destinations (F06 + F07)

Outcome: T05's completion gate is met on SQLite with fresh evidence. Every admin-supplied outbound destination (generic webhooks, Slack, Teams, WhatsApp -- save, test, and real event delivery) now routes through one shared policy/transport module; the admin Test button makes a real delivery and never fabricates success; double-click suppression and Sending/Delivered/Failed states are proven in a real browser.

Files changed:

- `oneforall/core/outbound_http.py` (new) -- single chokepoint: `validate_outbound_url()` requires HTTPS, a real hostname, no embedded credentials, and resolves every A/AAAA record via `socket.getaddrinfo`, rejecting the destination if *any* answer is loopback/private/link-local/reserved/multicast/unspecified (checked explicitly via the `ipaddress` module, not string-prefix matching -- the exact F07 defect: the old code missed most of `172.16.0.0/12` and never checked IPv6 at all). `send_outbound()` revalidates immediately before connecting, applies strict per-phase timeouts (`httpx.Timeout`), never follows redirects, and caps the response body it reads back.
- `oneforall/core/webhooks.py`: `_deliver_once` now calls `send_outbound` instead of a raw `httpx.post` (real event delivery gets the same policy as the admin Test button, not a parallel unhardened path). New `send_test_ping(webhook_id, url, secret)`: one real signed attempt, no retries (an interactive click needs a fast truthful answer, not ~7s of retry backoff), always logs the real attempt via the existing `_log_attempt`, returns a short sanitized `{success, status_code, detail}` -- `detail` never contains the raw response body, headers, or resolver internals.
- `oneforall/core/notifications.py`: `send_slack`/`send_teams`/`send_whatsapp` refactored onto one shared `_send(label, url, payload)` helper that also goes through `send_outbound`, so the three connectors cannot silently diverge from the webhook policy over time.
- `oneforall/modules/launcher/routes_admin.py`: `_validate_webhook_url` now delegates to `validate_outbound_url` (used by both generic-webhook save and `api_connectors_save` for all three connectors -- confirmed by reading `api_connectors_save` directly, not assumed). `api_webhook_test` rewritten: per-actor-and-webhook rate limit (`check_rate_limit`/`record_failed_login`, the existing generic primitives, keyed `webhook_test:{uid}:{wid}`) before a real `send_test_ping` call; the old code path that inserted a synthetic `response_code=200/success=1` row without ever calling `core.webhooks` is gone entirely. New shared `_rate_limited_connector_test(request, connector, send_fn, message)` used by all three `/api/admin/connectors/test-*` routes, keyed `connector_test:{connector}:{uid}`.
- `oneforall/modules/launcher/templates/admin_webhooks.html`: Test button gained `id="test-btn-{id}"` and now disables itself synchronously on click (a disabled DOM button dispatches no further click events -- the double-click suppression mechanism itself, not just a visual affordance), shows Sending.../Delivered/Failed, and surfaces the route's sanitized `detail`/`error` message as the button's `title` on failure. Previously: `alert('Test ping sent and logged.')` only on `resp.ok`, nothing shown at all on failure or on a 429 -- silently doing nothing on a real failure is itself a truthfulness gap the plan's UI requirement (F06) covers, not just the backend.
- `oneforall/tests/test_security.py`: pre-existing `TestSSRFValidation.test_valid_https_url_passes` asserted `https://hooks.example.com/webhook` passes validation -- true under the old string-matching validator, which never resolved DNS, but `hooks.example.com` does not actually exist (NXDOMAIN), so it now correctly fails under real DNS resolution (an unresolvable host cannot be verified safe, so F07 rejects it, matching `send_outbound`'s own behavior on the same host). Fixed by mocking `socket.getaddrinfo` for this one test, the same pattern `test_outbound_http.py` already uses, keeping it a fast network-independent unit test rather than switching it to a live-resolving hostname.
- `oneforall/tests/test_webhooks.py`: 3 existing tests monkeypatched `wh.httpx.post`, which no longer exists after the `_deliver_once` refactor; fixed to monkeypatch `wh.send_outbound` and import `OutboundResult` from `core.outbound_http`. Added `test_deliver_blocked_by_outbound_policy_does_not_retry_as_network_error`.
- `oneforall/tests/live_webhook_test.py`: a manual, non-pytest-collected integration script (`python tests/live_webhook_test.py`; no `test_*` functions, so it contributes 0 collected tests and was unaffected by any run this session) whose own loopback HTTP receiver would now be rejected by the new HTTPS-only/public-DNS policy. Patched with the same local-fixture bypass the automated tests use, so it stays actually runnable for whoever reaches for it next.
- `oneforall/tests/ui/action_registry.json`: the `launcher.admin_webhooks.test_webhook.click` entry (written during T02, explicitly marked "currently red, must not be automated ... until T05 lands") and the `create_webhook.submit` entry's note updated to describe the now-fixed, now-tested behavior instead of the pre-fix state.

New files:

- `oneforall/tests/test_outbound_http.py` -- 24 tests: HTTPS/credentials/malformed-host/unresolvable-host rejection; 11 parametrized non-global DNS-answer rejections (loopback, RFC1918 x2, link-local, the literal metadata address, unspecified, IPv6 loopback/link-local/ULA, both 172.16/12 bounds) plus 4 parametrized public-answer allowances (including public 172.15.x/172.32.x, proving the over-broad old 172.x check is gone); a hostname resolving to one public and one private answer is rejected outright; redirect-not-followed, response-cap-exact, read-timeout, and truthful-success against a real local HTTP server. DNS cases are mocked (`socket.getaddrinfo`), never real network.
- `oneforall/tests/test_webhook_test_endpoint.py` -- 5 tests against `/api/admin/webhooks/{id}/test` at the route level (real local HTTP fixture): real delivery logged truthfully, real failure never reported as success, organization isolation, per-actor-and-webhook rate limiting, and a DNS-rebind scenario (mocked `socket.getaddrinfo` returning a private address at send time) never reported as success.
- `oneforall/tests/test_notifications.py` -- 11 tests: `_send()` (the shared chokepoint behind send_slack/send_teams/send_whatsapp) parametrized across all three connectors for not-configured/policy-blocked/success/failure, plus one HTTP-level test of `/api/admin/connectors/test-slack` against a real local fixture proving the rate limit applies there too.
- `oneforall/tests/ui/test_webhook_admin_ui.py` -- 2 real-browser tests: Sending/Delivered state transitions plus double-click suppression (two DOM-level click events fired back to back; asserts the fixture server received exactly one request, not just that the UI looked right), and a real-failure-shows-Failed test.
- `oneforall/docs/outbound-webhook-egress.md` -- operator-facing: what the application layer now enforces, the residual DNS-rebinding risk this module cannot close on its own (two separate DNS resolutions between validate and connect), and a concrete nftables egress rule recommendation for the Hetzner VPS to close that gap at the network layer. Not applied anywhere by this session's code; deploying it is a separate manual operational step.

Verification commands and results:

1. `pytest tests/test_outbound_http.py tests/test_webhooks.py tests/test_webhook_test_endpoint.py tests/test_notifications.py -v` -- 47 passed.
2. `pytest tests/test_security.py -v` -- 58 passed (includes the fixed `TestSSRFValidation` class, 12 tests, all passing in 1.18s -- confirms no live-network dependency remains).
3. `pytest tests/ui/test_webhook_admin_ui.py -v` -- 2 passed, repeated 3 times in a row for stability (all 3 clean).
4. **Red/green proof #1** (response-size cap, found while writing its own test, before shipping): `send_outbound`'s chunk loop appended a full chunk before checking the length cap, so a response could exceed `MAX_RESPONSE_BYTES` by up to one chunk size (observed 130816 bytes vs. a 65536 cap). Fixed by truncating each chunk to the remaining budget before extending and breaking as soon as a chunk alone reaches the cap; test tightened from an approximate bound to an exact one (`== MAX_RESPONSE_BYTES`).
5. **Red/green proof #2** (double-click suppression, the plan's own named test requirement): temporarily removed the `if (!btn || btn.disabled) return; btn.disabled = true;` guard from `testWebhook()` -- `tests/ui/test_webhook_admin_ui.py`'s suppression test failed immediately (the button never reached the `[disabled]` state the test waits for first). Restored; passed, 2/2, re-run 3 times clean.
6. **Root-cause test-infrastructure bugs found and fixed while building the above** (none are product bugs; noted because two are non-obvious for whoever touches this test file next): (a) `_admin()` test-actor helper set `is_super_admin` but no `roles` list -- `core/rbac.py::has_capability` grants `platform.manage_users` purely by role-set intersection (`_role_set(user) & CAPABILITIES[cap]`, reading only `user.get("roles")`), an entirely separate mechanism from the `is_super_admin` column that `_get_webhook_for_admin` independently checks for its own org-bypass; fixed by giving test actors `roles: ["super_admin"]` while deliberately keeping `is_super_admin: 0`, which turned out to make the organization-isolation test exercise the real org-scoped branch naturally, with no special-casing needed. (b) The same helper never set `username`, and `core/middleware.py::log_audit` does `user["username"]` unconditionally -- `KeyError` on the very first successful call. (c) `core/middleware.py::_login_attempts` is a process-global in-memory dict (used whenever `_use_db_rate_limit()` is false, i.e. SQLite -- PostgreSQL production uses the DB-backed path instead, so this was a test-only concern, not a production one); since `test_db` gives each test function a fresh SQLite file whose autoincrement ids restart, two unrelated tests reusing the same admin uid could collide on the same rate-limit key and inherit each other's attempt counts. Fixed with an autouse fixture that clears the dict before each test.
7. Full backend suite, `pytest tests --ignore=tests/ui -q` (715 collected): first run (before the `test_security.py` fix above) showed exactly one failure, `TestSSRFValidation::test_valid_https_url_passes`, already diagnosed and fixed by the time this run's output was read -- a stale-relative-to-the-fix run, not counted as evidence per this ledger's own rule. Re-run after the fix: **clean, 0 failures, exit 0** (10 skipped -- `tests/test_postgres_init.py`, `TEST_DATABASE_URL` not set this session, same constraint as every prior T00-T04 entry).
8. Full browser suite, `pytest tests/ui -q`: first run showed one failure, `test_aria_managed_edit.py::test_managed_document_edit_sends_metadata_only_and_preserves_lifecycle`, with the exact `"Cannot read properties of null (reading 'style')"` / `HTMLImageElement.onload` at `login:430` signature already documented against T01-T04 -- a pre-existing, non-deterministic shared-shell-code race, not caused by any T05 change (T05 never touches login.html/base_shell.html/image-onload code), and not either of this session's own new UI tests. Immediate re-run: **clean, 0 failures, exit 0**, same non-deterministic pattern T04 already established (fails under load, passes on isolated/immediate re-run).
9. `python -m compileall -q .` -- exit 0. `python -m pip check` -- exit 0. `git diff --check` on every T05-touched file -- exit 0 (one CRLF-substitution notice on `test_security.py`, not an error, same category T04 saw on its own touched scripts).
10. Repo-wide security-review sweep for the completion gate ("no unvalidated alternate outbound path remains"): grepped for `httpx.*`/`requests.*`/`urlopen(` outside `core/outbound_http.py`. Found `core/ai_client.py` (OpenRouter/Anthropic/Gemini -- fixed, server-configured LLM provider endpoints, never an admin- or tenant-supplied destination), `core/email.py` (fixed Microsoft Graph/SendGrid provider endpoints, same reasoning), `scripts/deploy.py` (a deploy-time localhost health probe) and `scripts/fetch_fonts.py` (build-time hardcoded font CDN URLs). None accept a destination URL an admin or tenant ever supplies, so none are "outbound webhook destinations" per this task's own scope; every path that *does* accept an admin-supplied destination was confirmed by direct source reading (not assumed from memory) to route through `core/outbound_http.py`.

Explicitly unverified/skipped:

- PostgreSQL-specific behavior: `_connectors_save`/webhook creation against a real PostgreSQL schema-per-tenant instance -- no instance available this session, same constraint as T01/T03/T04. The application-layer policy itself (`validate_outbound_url`/`send_outbound`) has no PostgreSQL dependency at all (pure Python/socket/httpx), so this risk is judged low, but it is unverified, not passed.
- Correlation ID for individual delivery attempts: the plan asks for one; no correlation-ID mechanism exists anywhere else in this codebase to extend (confirmed by a repo-wide grep, not assumed), and inventing one net-new solely for this task was judged out of proportion. `elapsed_ms` is captured on every attempt; `webhook_logs` rows are timestamped and queryable per webhook, which covers the practical debugging need this step is aimed at.
- A dedicated HTTP-level test for each of the Teams and WhatsApp connector-test routes individually: covered at the unit level (`_send`, parametrized across all three) and at the HTTP level for Slack only, since all three connector routes share the exact same `_rate_limited_connector_test` helper and the exact same `_send` chokepoint -- judged redundant to triplicate the same real-local-server HTTP-level test three times for what is, by construction, identical shared code.
- No commit, push, migration, service restart, or deployment was performed. No production host or data was touched. `docs/outbound-webhook-egress.md`'s recommended nftables rule was written but not applied anywhere.

## 2026-09-24 T04 session 1 — remove stale erm_risks references, restore recovery-signal integrity (F05)

Outcome: T04's completion gate is met for everything reachable by reading and by SQLite execution. The two checkboxes that require actually running the backup/restore/drill scripts against PostgreSQL/Docker are explicitly left unverified -- see task_plan.md.

Files changed:

- `oneforall/database.py`: deleted the two stale `_POST_MIGRATION_INDEXES` entries (`idx_erm_risks_status`/`idx_erm_risks_module`) that targeted a table named `erm_risks`, which has never existed -- these produced the `WARNING oneforall.migrations: Skipped index ...` seen on every single test run and real startup this whole session (T00 through T03's progress entries all show it). The *correct* indexes for this concept already existed elsewhere in the same file, under the real table name (`erm_enterprise_risks`), untouched.
- `oneforall/modules/evidence/routes.py` (`api_evidence_suggest_links`): the risk-suggestion query now targets `erm_enterprise_risks` (`title AS name`, preserving the existing prompt-dict shape) with business-unit scope applied via the existing `bu_scope_ids()` helper (`modules/governance/data_service.py`) -- the same helper every other ERM/BCM/GRID/Sentinel/ORM listing route in this codebase already uses, not a new mechanism. Organization-level isolation needed no application code at all: `erm_enterprise_risks` has no `org_id` column, because (like T03's `erm_risk_library` finding) it lives in `_ERM_ORM_TABLES`, which PostgreSQL provisions once per tenant *schema* -- cross-organization rows are structurally unreachable from a given connection already. **Incidental fix, same function, not named in F05**: the `audits` query two lines above the risks query selected a `framework_name` column that `grid_audits` has never had (only `framework_id`) -- this made `api_evidence_suggest_links` throw before ever reaching the line F05 is actually about, so no test of the named fix was possible without also correcting this. Fixed with a `LEFT JOIN frameworks` (not `INNER JOIN`, so an audit with no framework isn't silently dropped), mirroring the `controls` query's existing join shape three lines above it.
- `oneforall/scripts/restore_backup.py` (`validate_row_counts`): table name fixed; now returns `bool` instead of always implicitly succeeding, and `main()` exits 1 when it's `False`. Also fixed a transaction-poisoning bug that would have undermined the fix on its own: PostgreSQL aborts the rest of a transaction after one failed statement, so without a `conn.rollback()` after catching the per-table exception, a single genuinely-missing table would have cascaded into every table checked after it *also* reporting a false failure.
- `oneforall/scripts/weekly_restore_drill.py`: table name fixed in `_CORE_TABLES` (`aria_risks` alongside it is a real, distinct table -- confirmed before leaving it alone). Same transaction-poisoning fix as `restore_backup.py` (`prod.rollback()` / `drill.rollback()` on a per-table exception) -- this script already exited non-zero correctly, it just risked misreporting *which* table failed.
- `oneforall/scripts/warm_replay.py`: table name fixed in the `erm:risks_by_treatment` query. Before, this comparison failed identically on both the SQLite and shadow-PostgreSQL sides (the table existed on neither), which `main()`'s own logic classifies as SKIP, not FAIL -- so this specific parity check had silently done nothing, every run, since it was written.

New files:

- `oneforall/tests/test_no_stale_erm_risks_table.py` -- static repo-wide guard: scans every `.py` file under `oneforall/` (skipping venvs/caches and its own file) for `\berm_risks\b`, excluding lines that are themselves comments (so explanatory `# ...erm_risks...` history notes elsewhere in this session's diff don't self-trigger). Not a behavioral test; a regression fence.
- `oneforall/tests/test_evidence_suggest_links.py` -- 3 tests against `modules.evidence.routes.api_evidence_suggest_links` directly (same `_mock_auth`/`_request_as` pattern as `test_aria_policy_legacy.py`, since it's an async `@require_auth` route): reaches the AI layer without a SQL error and the captured prompt contains an in-scope risk title; another business unit's risk title is absent from the same prompt; a `business_unit_id IS NULL` (org-wide) risk is visible regardless of the actor's own BU, proving the scope fix didn't overcorrect into hiding legitimately-shared risks.

Verification commands and results:

1. `pytest tests/test_no_stale_erm_risks_table.py tests/test_evidence_suggest_links.py tests/test_erm_library_tenancy.py -q` -- 17 passed.
2. **Red/green proof #1** (guard test): temporarily reintroduced `FROM erm_risks` in `warm_replay.py` -- guard test failed, naming that exact file and line. Restored; passed.
3. **Red/green proof #2** (the actual F05 fix): temporarily reverted the evidence-suggestion query back to `SELECT id, name, category FROM erm_risks {risk_where} LIMIT 50` -- failed with `sqlite3.OperationalError: no such table: erm_risks`, the literal SQL error F05 says never surfaced anywhere before. Restored; passed.
4. Confirmed the stale-index startup warning is gone: `pytest tests/test_evidence_suggest_links.py -v --log-cli-level=WARNING`, zero matches for "Skipped index" or "erm_risks" (compare every prior session entry's captured log, which always showed two such warnings).
5. Full suite (`pytest tests -q`) four times in a row while finalizing T04, because the same two failures recurred identically on runs 1-2 and made a third data point worth checking before writing this off as ambient flakiness:
   - Run 1: `test_aria_policy_publication.py::test_purge_expired_trash_leaves_recent_entries` (7th occurrence of the already-documented pre-existing mtime-timing flake) + `tests/ui/test_aria_managed_edit.py::test_managed_document_edit_sends_metadata_only_and_preserves_lifecycle` (`Cannot read properties of null (reading 'style')`, the same base_shell.html-level race noted against T01/T02/T03 -- this time it fired before the toast even appeared, outside the exact window T01's snapshot-scoping fix targets, confirming it's a general low-frequency race in shared shell code, not specific to any one reload sequence).
   - Run 2: identical 2 failures again.
   - Isolated rerun of `tests/ui/test_aria_managed_edit.py` alone: 2 passed -- confirms this is a full-suite-context-only condition (higher probability under load), same shape as T00's Playwright-collection-time finding, not a fundamentally broken test.
   - Enhanced `tests/ui/conftest.py`'s `pageerror` handler to capture `.stack` (previously only `str(exc)`), so a future occurrence is diagnosable instead of just a bare message -- a permanent, small improvement, kept regardless of outcome.
   - Run 3 (with the stack-capture change in place): full suite clean, **zero failures**, exit 0.

   Conclusion: genuinely non-deterministic under load (confirmed by the clean 3rd run after 2 identical failures), not a regression this session's changes made reliably reproducible. Worth a real fix eventually -- likely a periodic poll in `base_shell.html` racing a page/DOM teardown -- but that file is untouched by and unrelated to any T00-T04 finding; flagging it as a good candidate for T07 (accessibility/keyboard foundation, which already touches shared shell JS) or T08 (which explicitly anticipates exactly this case: "fail the test unless explicitly allowlisted with rationale") rather than chasing it further under T04.
6. `python -m compileall -q .` -- exit 0. `python -m pip check` -- exit 0. `git diff --check` -- exit 0 (CRLF-substitution warnings on the 3 newly-touched scripts, not errors). `git status --short` -- exactly the files listed above plus this plan folder.

Explicitly unverified/skipped:

- PostgreSQL fresh-init/upgrade parity for the removed stale indexes -- no instance available this session.
- Actually running `restore_backup.py`, `weekly_restore_drill.py` (needs Docker), and `warm_replay.py` end-to-end against a disposable restored database -- no PostgreSQL/Docker/real backup archive available this session. All three were corrected by reading their logic carefully (including the transaction-poisoning issue, which only a careful read would catch -- it wouldn't reproduce with a single missing table in a quick manual test either), not by execution.
- No commit, push, migration, service restart, or deployment was performed. No production host or data was touched.

## 2026-09-24 T03 session 1 — Email Reset (F04) + tenant-safe ERM library (F03 + F13)

Outcome: T03's completion gate is met on SQLite. PostgreSQL schema parity is explicitly unverified (no instance available); the reasoning for why the chosen design should still reach production tenants is recorded below for whoever runs that verification next.

**Architecture finding worth flagging explicitly**: `erm_risk_library` lives in `_ERM_ORM_TABLES`, which `_apply_tenant_schema_ddl` creates once per PostgreSQL tenant *schema* (`tenant_<slug>.erm_risk_library` -- confirmed by reading `provision_tenant_schema`/`_migrate_all_tenant_schemas`, `database.py`). That means in production, cross-organization row visibility is already structurally impossible (different orgs are physically different tables), which is a *stronger* guarantee than the row-level `org_id` filtering findings.md's F13 describes -- the audit's "same global catalogue used by every organization" framing was almost certainly observed against the SQLite dev/test path (a single flat table, no schema separation), where it's exactly right. Two designs were available:

1. Relocate `erm_risk_library` into `_SHARED_TABLES` (public schema, created once) so a literal single shared table exists.
2. Leave it exactly where it is; add `org_id` as an authorization marker (global-seeded vs. this-org's-own-row) enforced by the *application*, not the schema boundary.

Chose (2): (1) would require dropping/migrating every already-provisioned tenant's existing `tenant_X.erm_risk_library` copy -- a real hazard for what my own memory records as a likely-already-live production deployment, and unverifiable without a PostgreSQL instance this session -- while (2) uses the exact `_COLUMN_MIGRATIONS` mechanism the plan's own text calls for, requires no data relocation, and still satisfies every behavioral requirement in section 2.4 (global rows super-admin-only, org rows own-org-only, and cross-org rows literally unreachable -- even more strongly than row filtering alone would provide). `_apply_tenant_schema_ddl` already runs `_run_pg_alters` (where the new columns/indexes live) against each tenant's own schema, and `_migrate_all_tenant_schemas` is the existing, already-invoked-at-startup mechanism that brings every previously-provisioned tenant current -- so this migration has a real path to production without new deploy-time machinery. Not run against a real PostgreSQL instance this session; flagging this reasoning so it's checked, not re-derived, when one is available.

Files changed:

- `oneforall/database.py`:
  - `_COLUMN_MIGRATIONS`: added `erm_risk_library.org_id` (`INTEGER REFERENCES organizations(id)`, NULL = global), `.created_by` (`INTEGER REFERENCES users(id)`), `.updated_at`. Existing rows backfill to `org_id IS NULL` automatically (no-default ADD COLUMN behavior on both dialects) -- exactly the "seeded rows are global" requirement, no separate backfill script needed.
  - Removed the old blanket `CREATE UNIQUE INDEX idx_erm_library_title ON erm_risk_library(title)` (both its original-DDL copy and its `_POST_MIGRATION_INDEXES` copy). Replaced with two partial unique indexes -- `uq_erm_library_title_global ON erm_risk_library(title) WHERE org_id IS NULL` and `uq_erm_library_title_org ON erm_risk_library(org_id, title) WHERE org_id IS NOT NULL` -- in both `_run_sqlite_alters`'s `_POST_MIGRATION_INDEXES` and `_run_pg_alters`'s duplicated list (a `DROP INDEX IF EXISTS idx_erm_library_title` precedes both, for upgrade safety). Confirmed the existing seed function's `INSERT ... ON CONFLICT DO NOTHING` (bare, no target column) is compatible with either constraint shape -- it doesn't name `title` specifically.
- `oneforall/modules/erm/data_service.py`: `list_library`, `get_library_item` (now takes `actor`), `update_library_item`/`delete_library_item` (now return `bool`, `False` for out-of-scope), `create_library_item` (now takes `actor`; caller-supplied `org_id` is never trusted -- always derived from the actor). New `_library_in_read_scope`/`_library_can_manage`/`can_manage_library_item` helpers encode section 2.4's rule once, reused by every entry point.
- `oneforall/modules/erm/routes.py`: all five `/api/library*` routes pass `request.state.user` through; update/delete now 404 on a `False` return instead of silently no-op-ing on an out-of-scope id; create/update/delete now call `log_audit`; `erm_spa` passes `can_manage_library = has_capability(user, "erm.library.manage")` to the template (distinct from the pre-existing `can_manage_frameworks`, which findings.md flagged the template as wrongly not using anyway -- it wasn't using either).
- `oneforall/modules/erm/templates/index.html`: `#libAdminBtn` is now inside `{% if can_manage_library %}` (absent from the DOM otherwise, not just hidden); built the create/edit modal from scratch (it didn't exist) on T02's canonical `.modal-overlay`/`.modal`/`ModalManager` contract -- the first consumer of that shared infrastructure outside T02's own migration list; added a 🌐 Global / 🏢 Organization badge per card and gated the per-card Edit/Retire buttons through a new `ermCanManageLibraryItem()` client helper (UI-only signal -- the server re-checks independently on every write, per `_library_can_manage`).
- `oneforall/modules/launcher/templates/admin_email.html`: `Reset` now calls a new `window.resetConfig()` instead of the undefined global `loadConfig()`. `resetConfig()` snapshots tracked field values after every successful load, confirms before discarding a dirty form, and surfaces `loadConfig(throwOnError=true)`'s distinguished 403/5xx/non-JSON/network errors via toast (or `alert` if the toast helper isn't present) instead of the previous silent `console.error`-only failure. The internal `loadConfig()` used by save/test-success callers is unchanged in behavior for those callers (still best-effort, still IIFE-scoped) -- only the Reset button's own path changed.

New files:

- `oneforall/tests/test_erm_library_tenancy.py` -- 13 tests directly against `modules.erm.data_service` (no route/middleware mocking needed, since the functions now take a plain actor dict -- mirrors `test_erm_objectives.py`'s existing pattern for this same module). Covers every item in T03's own test list except a dedicated `use`-route test (see task_plan.md's checkbox notes) and PostgreSQL parity.
- `oneforall/tests/ui/test_erm_library_and_email_reset.py` -- 4 real-browser tests: button absent (not hidden) without `erm.library.manage`; button present, modal opens on the T02 contract, created row is correctly org-scoped; a global (seeded) template shows no manage controls to an ordinary org user; Email Reset reloads with zero console errors.

Verification commands and results:

1. `pytest tests/test_erm_library_tenancy.py -v` -- 13 passed on first full run after fixing a test-authoring bug of my own (below).
2. **Red/green proof #1 (ERM authorization)**: temporarily made `_library_can_manage` always `return True` (the literal F13 bug) -- reran: exactly the 2 tests that assert unauthorized writes are blocked failed (`test_org_risk_owner_cannot_update_global_row`, `test_org_risk_owner_cannot_update_another_orgs_row`); the other 11 stayed green (they assert *allowed* paths, which remain true regardless). Restored; reran -- 13 passed.
3. `pytest tests/ui/test_erm_library_and_email_reset.py -q` -- 4 passed (after fixing a persona-choice bug of my own, below).
4. **Red/green proof #2 (Email Reset)**: temporarily reverted the Reset button's `onclick` back to the literal original `loadConfig()` -- reran: failed with `AssertionError: unexpected console/page errors: ['loadConfig is not defined']`, the exact ReferenceError findings.md describes. Restored; reran -- 4 passed (though see the flake note below -- one rerun of the full 4-test file hit the same base_shell.html-level race noted in T01/T02, unrelated to this fix, gone on the next immediate rerun).
5. Full suite (`pytest tests -q`) twice: first run hit the same pre-existing `tests/test_aria_policy_publication.py` timing flake already logged against T00/T01/T02 (6th observed occurrence this session, still always that one file, never anything T00-T03 touched); second run fully clean, zero failures, exit 0.
6. `python -m compileall -q .` -- exit 0. `python -m pip check` -- exit 0. `git diff --check` -- exit 0. `git status --short` -- exactly the files listed above plus this plan folder.

Bugs found in my own test code (both caught by actually running the tests, not assumed away):

- `erm_risk_library.org_id`/`.created_by` are real foreign keys (`REFERENCES organizations(id)`/`REFERENCES users(id)`). My first test draft used bare integers (`org_id=1`, actor `id=10`) with no matching `organizations`/`users` rows, and every write failed with `sqlite3.IntegrityError: FOREIGN KEY constraint failed` -- correctly, since that's exactly the same constraint that will protect real data. Fixed by making the test's `_actor()` helper create a real backing `users` row (and `organizations` row, if `org_id` is set) the first time each actor is used.
- My first list-scope test asserted an *exact* set of visible titles, not accounting for the ~24-row baseline catalogue `test_db` auto-seeds the first time `erm_risk_library` is empty (the same seed function that runs in production on first boot). Fixed to assert the specific rows-of-interest are present/absent rather than an exact-set match.
- The first browser test used the `employee` persona to prove "no `erm.library.manage` -> no button," but `employee` doesn't hold `module.erm.access` either (`core/rbac.py`), so the library page never rendered any cards and the test timed out for the wrong reason. Fixed by switching to `compliance_manager`, which has module access but not library-manage.

Explicitly unverified/skipped:

- PostgreSQL schema/query parity -- no instance available this session; see the architecture-finding note above for what should be checked first when one is.
- A dedicated test of `/api/library/{id}/use` denying another organization's template id (covered only indirectly, through the shared `get_library_item` scope check that route also calls).
- 403/500/non-JSON/network branches of Email Reset's error handling are implemented and unit-reasoned but not independently browser-tested (only the success/reachability path was).
- No commit, push, migration, service restart, or deployment was performed. No production host or data was touched.

## 2026-09-24 T02 session 1 — modal contract consolidation (F02)

Outcome: T02's completion gate is met. All 9 broken dialogs (F02's 5 runtime-confirmed + 3 same-pattern-affected + `admin_frameworks.html`'s separate local workaround) now use the canonical contract and are covered end-to-end in a real browser.

Files added:

- `oneforall/static/js/modal_manager.js` -- the shared dialog manager the plan's section 2.1 calls for. Stack-based (`openStack`) so focus-trap/Escape only ever act on the topmost modal; tracks the pre-open `document.activeElement` per id for focus restoration; ref-counted body scroll lock (`scrollLockCount`) so a future nested-modal case can't unlock the body while an outer one is still open; exposes `open(id)`, `close(id, {force})`, `isOpen(id)`, and `registerCloseGuard(id, fn)` (an opt-in hook for "don't close a dirty form without confirming" -- infrastructure only, since no migrated modal currently has that behavior to preserve).
- `oneforall/tests/ui/test_modal_contract.py` -- 13 real-browser tests: a parameterized open/close/focus/Escape/dialog-semantics test across 8 modals, a Tab/Shift+Tab focus-trap-cycling + return-to-trigger test, a 2-modal mobile-viewport (390x844) overflow check, the API-key generate->reveal two-modal transition, and Link Evidence's seeded-item trigger path.

Files changed (all application source):

- `oneforall/templates/base_shell.html` -- `.modal-overlay.open` added as the canonical visible-state rule alongside the retained `.modal-overlay.show` compatibility alias (per section 2.1, `.show` is not removed here); `modal_manager.js` loaded as a new shared script (`?v=1`).
- 8 templates migrated from outer `.modal` / inner `.modal-content` / raw `.modal-backdrop` div / `this.closest('.modal').classList.remove('open')` to outer `.modal-overlay` (`role="dialog" aria-modal="true" aria-labelledby="..."`) / inner `.modal` / `ModalManager.open(id)` / `ModalManager.close(id)`, with the backdrop div deleted outright (the overlay itself is now the click-to-close backdrop, exactly matching ARIA's own already-correct pattern):
  - `modules/launcher/templates/task_board.html` (`newTaskModal`)
  - `modules/launcher/templates/reports.html` (`newReportModal`)
  - `modules/launcher/templates/risk_register.html` (`newRiskModal`)
  - `modules/launcher/templates/calendar.html` (`eventModal` only -- `evOverlay`/`evDrawer` is a separate side-drawer mechanism, untouched, correctly out of scope)
  - `modules/launcher/templates/admin_api_keys.html` (`newKeyModal` and `revealModal`)
  - `modules/launcher/templates/admin_webhooks.html` (`newWhModal`)
  - `modules/evidence/templates/evidence_index.html` (`uploadModal` and `linkToModal`, including two dupe-warning buttons built as escaped-quote HTML strings inside `handleUpload()` -- `evDetailOverlay`/`evDetailPanel` is a separate drawer, untouched)
  - `modules/launcher/templates/admin_frameworks.html` (`newFwModal`) -- this one needed real restructuring, not just a class rename: it had inline `position:fixed;inset:0;...;display:none` hardcoded on the outer element, a raw unstyled backdrop div, no `.modal-header`/`.modal-close` structure at all, and a page-local `<style>.modal.open{display:flex !important}</style>` override (the "local workaround" the plan names explicitly). Rebuilt to the same canonical structure as the other 7; the local override was deleted, not superseded.
- `oneforall/tests/ui/action_registry.json` -- corrected 6 trigger-selector guesses from T00 that turned out wrong once the real markup was read closely (e.g. reports' trigger is "+ New Report", not "Create Report" -- that's the modal's own title/submit-button text; webhooks' is "+ New Webhook", not "+ Add Webhook"; the API-key submit button's own label is "Generate", not "Generate API Key"), corrected 3 `required_capability` guesses from a bare `"super_admin"` role-name guess to the actual decorator (`platform.manage_users`, confirmed by reading `routes_admin.py`), marked all 8 F02 entries FIXED with test pointers, and added 2 new entries for `admin_frameworks.html`'s custom-framework action. 25 entries total (was 21).

Verification commands and results:

1. `pytest tests/ui/test_modal_contract.py -q` -- 13 passed (first full run after the focus-trap test was tightened; see below).
2. **Red/green proof #1 (the core F02 defect)**: temporarily reverted `task_board.html`'s `newTaskModal` markup to the exact original outer-`.modal`/inner-`.modal-content`/backdrop-div/`this.closest('.modal')` pattern -- reran the parameterized suite: `1 failed, 7 passed` (only `[newTaskModal]` failed, the other 7 already-correct modals stayed green, proving good test isolation). Failure was `AssertionError: newTaskModal must start closed` -- the reverted element was visible even before any click, an even more direct reproduction of F02 ("stays in normal document flow") than "open has no effect." Restored the exact original template text (`git diff --stat` showed the file back to its final T02 diff, zero residual); reran -- green.
3. **Red/green proof #2 (focus-trap cycling)**: temporarily added an early `return` in `modal_manager.js`'s Tab-handling branch. First attempt at asserting the wrap used a fragile `element.id || element.textContent` string comparison, which **did not catch the break** (false negative -- Tab moving focus outside the modal happened to produce a value that satisfied the loose comparison). Rewrote the assertion to compare Playwright element handles directly (`document.activeElement === el`); reran against the still-disabled trap -- correctly red (`1 failed`). Restored the removed `return`; reran -- green. This is recorded because it is exactly the kind of test-quality gap the plan's evidence rules exist to catch -- a passing red/green cycle with a weak assertion is not real proof.
4. Repo-wide grep for `modal-backdrop`, `class="modal-content`, and `this.closest('.modal')` under `modules/` -- zero matches, confirming complete removal, not just the 8 migrated files.
5. Full suite (`pytest tests -q`) run three times across this session's T02 work: T02's own new/changed tests were clean in all three; the same pre-existing `tests/test_aria_policy_publication.py` flake from T00/T01 (see those entries) recurred in 1 of 3 -- now observed 5 times total this session, always that one file, never anything T00/T01/T02 touched. Not investigated further here; still out of scope.
6. `python -m compileall -q .` -- exit 0. `python -m pip check` -- exit 0. `git diff --check` -- exit 0. `git status --short` -- exactly the files listed above plus this plan folder; nothing unrelated staged or changed.

Scope notes (things noticed but deliberately not touched, to stay inside T02's named files):

- `modules/launcher/templates/people_directory.html` (`pdAddModal`, `pdImportModal`) uses its own `pd-modal-overlay` class -- a third, distinct convention from both the shared `.modal`/`.modal-overlay` pattern and ARIA's local one. Not named in `findings.md` F02 or in T02's migration list; not investigated for correctness, just noted here so it isn't mistaken for something T02 already covered.
- ARIA's own modals (`modules/aria/templates/{documents,framework,risks,templates}.html`, via `modules/aria/templates/base.html`'s own `.modal-overlay.open{display:flex}`) were confirmed already correct and were not touched -- not in T02's scope, and findings.md is explicit that ARIA "uses another overlay convention" as a separate, working thing.
- Drawers (`evOverlay`/`evDrawer`, `evDetailOverlay`/`evDetailPanel`, `tdOverlay`/`taskDrawer`, `editDrawer`, `pdDrawer`, `orgPanel`, `vdDrawerOverlay`) are a different UI mechanism from modals and were left alone throughout.

Explicitly unverified/skipped:

- PostgreSQL gate -- not applicable to this task (no schema/query changes) but still generally unverified this session.
- Literal Microsoft Edge (`msedge` channel) -- tested via Playwright's bundled Chromium instead; same engine, not byte-identical to a real Edge install.
- Axe-core/automated accessibility scanning of the migrated modals -- deferred to T07 per the plan's own dependency order; this task's tests check the specific contract items T02 itself lists (role/aria-modal/name/focus/Escape/close/mobile-overflow), not a full WCAG pass.
- No commit, push, migration, service restart, or deployment was performed. No production host or data was touched.

## 2026-09-24 T01 session 1 — ARIA managed-edit repair (F01)

Outcome: T01's completion gate is met on SQLite. PostgreSQL coverage is explicitly unverified (same environment constraint as T00 -- no PostgreSQL instance in this session).

**What was actually broken vs. already fixed:** reading `tests/test_aria_policy_legacy.py` before touching anything showed the *backend* contract for `update_document` was already fully correct and already covered by five passing tests (permitted-fields-succeed, lifecycle-fields-409, pending-approval-lock, legacy-unaffected, org-scope-404) -- all pre-existing, none written this session. F01 was a pure client bug: `documents.html`'s `submitEdit()` sent `status`/`version`/`owner`/`approver` unconditionally regardless of `doc.policy_workflow_managed`, so the server's correct guard 409'd on every managed edit. T01's real scope was therefore entirely `documents.html`, not `routes.py` -- confirming the plan's own conditional file list ("routes.py only if response/error clarity requires a non-security behavior change": it didn't).

Files changed:

- `oneforall/modules/aria/templates/documents.html` (application source; 90 insertions / 38 deletions):
  - Added `#edit-is-managed` hidden input, set explicitly from `doc.policy_workflow_managed` in `openEditModal()` -- the managed/unmanaged state is now carried on the form, not re-derived from field disabled-state.
  - Wrapped the four lifecycle inputs (`edit-status`/`edit-version`/`edit-owner`/`edit-approver`) in `#edit-legacy-lifecycle-fields` (`display:contents` so they don't disturb the existing CSS grid), toggled fully hidden (not just `disabled`) for managed documents.
  - Added a "Policy Workflow — Current Lifecycle State" read-only block inside `#edit-managed-panel` showing status/version/owner/approver as plain text for managed documents.
  - Gave the Save button a stable id (`#edit-save-btn`) and set its label dynamically: "Save metadata" (managed) / "Save changes" (legacy).
  - Rewrote `submitEdit()`: appends title/effective_date/review_date/location/comments/control_ref always; appends status/version/owner/approver only `if (!isManaged)`; added try/catch/finally with a disabled "Saving..." state, non-JSON-body tolerance, and status-specific messages for 403/409/5xx/network failure, restoring the button in every failure path.
  - `routes.py` was **not** touched -- its guard, error messages, and the pending-approval lock were already correct.
- `oneforall/tests/ui/test_aria_managed_edit.py` (new) -- two real-browser tests: managed-path (metadata persists, lifecycle fields don't, read-only display and "Save metadata" label verified, zero console errors) and legacy-path (lifecycle fields still persist, "Save changes" label, zero console errors).
- `oneforall/tests/ui/conftest.py` -- `page` fixture's console-error listener now includes the script URL/line (`msg.location`) so a captured error is actually actionable, not just a bare message string.
- `oneforall/tests/ui/action_registry.json` -- `aria.documents.save_changes` narrowed to the legacy-only path (selector corrected to `#edit-save-btn`, marked FIXED); added sibling `aria.documents.save_metadata` for the managed path, marked FIXED, with the red/green evidence pointer in its `notes`.

Verification commands and results:

1. `pytest tests/ui/test_aria_managed_edit.py -v` -- 2 passed (first clean run, 15.25s).
2. **Red/green proof**: temporarily changed `if (!isManaged) {` to `if (true) {` in `submitEdit()` (i.e. restored exactly the F01 bug: send lifecycle fields even when managed) -- reran, got `AssertionError: the permitted metadata field must persist / assert 'Original Title' == 'Renamed Via Metadata Save'` (red, for the right reason: the 409 blocked the save, so nothing persisted -- reproducing F01's exact user-visible symptom). Restored the exact original conditional; reran -- 1 passed (green).
3. `pytest tests/test_aria_policy_legacy.py tests/ui/ tests/test_ui_action_registry.py -q` -- exit 0, no failures (this is T01's complete relevant test surface: the five pre-existing backend tests, the two new browser tests, T00's harness smoke test, and the registry schema gate).
4. `python -m compileall -q .` -- exit 0. `python -m pip check` -- exit 0. `git diff --check` -- exit 0 (one CRLF-will-be-substituted warning from Windows git config, not an error).
5. Full suite (`pytest tests -q`) run four times across this session's T00+T01 work: T01's own new/changed tests were clean in all four; a **pre-existing, unrelated flake** in `tests/test_aria_policy_publication.py` (`test_purge_expired_trash_leaves_recent_entries` and/or `test_purge_expired_trash_deletes_only_old_enough_entries`, both comparing a directory's filesystem `mtime` against `time.time()` with a tight/zero grace window) appeared in 3 of those 4 runs, never in isolation, never touching anything T00/T01 changed. See "Full-suite flake" note below.

Debugging notes worth keeping (both are about my own new test code, not the application):

- **Row-selector collision**: `tests/ui/test_aria_managed_edit.py` originally clicked the page's only `.edit-btn`; once a second test in the same session-scoped `synthetic_tenant`/`live_app` seeded a second `aria_documents` row, that selector became ambiguous and the wrong row could be clicked. Fixed by scoping to `#row-{doc_id} .edit-btn` (the table row already carries a stable `id="row-{{ doc.doc_id }}"`, `documents.html`, reused rather than inventing a new one).
- **Reload-race in the post-save wait**: the initial test waited via `page.wait_for_url(...)` (a no-op -- the URL never changes for this modal-based page) then `wait_for_load_state("networkidle")`, which can resolve right after the save POST, well before `submitEdit()`'s hardcoded `setTimeout(location.reload, 900)` actually fires. This intermittently read the DB before -- or asserted console-errors across -- the reload's teardown window, where an unrelated `base_shell.html` background poll can race `location.reload()` and throw `Cannot read properties of null (reading 'style')`. Not an F01 bug: the same error was never observed on the simpler T00 smoke test, which never reloads. Fixed two ways: (1) `_wait_for_save_and_reload()` now waits for the actual `.toast-success` element, then explicitly past the 900ms mark, then for the reload's own `load` event; (2) the console-error assertion uses a snapshot taken right after the toast, before the reload teardown window, since what F01's fix is responsible for is "opening the modal and saving cleanly," not "surviving a page teardown race in shared shell code this task never touched."

**Full-suite flake, explicitly not fixed (out of scope for T01):** `tests/test_aria_policy_publication.py`'s `test_purge_expired_trash_deletes_only_old_enough_entries` / `test_purge_expired_trash_leaves_recent_entries` compare a just-created directory's `mtime` against `time.time()` with `grace_hours=0`, i.e. a zero-width timing window. Observed failing in 3 of 4 full-suite runs this session, always a different one of the two, never when run in isolation or as part of a smaller subset (confirmed by explicitly bisecting with `git stash` back to the untouched baseline plus `--ignore` on every file this session added, which still passed cleanly at that point -- see the T00 entry above for that same investigation applied to a different symptom). The same file already carries a first-party comment acknowledging Windows/antivirus filesystem-timing flakiness in this exact staging/trash mechanism. Neither `modules/aria/policy_storage.py` nor `modules/aria/policy_publication.py` nor their tests were touched by T00 or T01, and this is not named in `findings.md`. Recorded here so it is never mistaken for a T01 regression; a real fix belongs to whichever task next touches ARIA storage/publication (widen the grace window in the test, or accept a small tolerance in the comparison).

Explicitly unverified/skipped:

- PostgreSQL gate -- no instance available this session (same as T00).
- Accessibility/keyboard checks on the new read-only lifecycle block and the restructured form -- deferred to T07 per the plan's own dependency order.
- No commit, push, migration, service restart, or deployment was performed. No production host or data was touched.

## 2026-09-24 T00 session 1 — baseline reconciliation

- `git fetch --all --prune`: no new remote commits. HEAD = `2b98cc4549e5e74decab32e7bafa79985008b17b` on `master`, identical to `origin/master`. Working tree clean except this plan's own untracked folder.
- Environment: `.venv` Python 3.12.14 (project interpreter; system `python` is 3.14.3 and is not used for this repo). Node v24.14.0, npm 11.9.0.
- DB mode for tests: SQLite per-test tmp DB via `tests/conftest.py` (`database._DB_PATH` monkeypatch, `DATABASE_URL` forced empty). No PostgreSQL instance configured in this session yet; PostgreSQL gate remains unverified until T03/T04.
- Baseline full suite: `..\.venv\Scripts\python.exe -m pytest tests -q` from `oneforall/` — exit code 0, 508 passed, 10 skipped, 0 failed/errored. Matches findings.md's audited baseline ("full Python suite passed ... with 10 expected skips"). Note: this pytest version (9.0.3) does not print its usual final one-line `N passed in Ys` summary under `-q` in this environment (dot/`s` progress and warnings summary print normally, counted manually); not investigated further as it doesn't affect pass/fail signal.
- `python -m compileall -q oneforall` (run from `oneforall/` as `.` ): exit 0, no syntax errors.
- `python -m pip check`: exit 0, "No broken requirements found."
- `git diff --check` (repo root): exit 0, no whitespace errors.
- `git status --short` (repo root): only the untracked PLAN-36 folder.
- No application source, test, schema, configuration, secret, deployment, or production changes were made in this baseline step. No commit, push, migration, service restart, or deployment was performed.

## 2026-09-24 T00 session 1 — critical-action registry, browser harness, completion gate

Outcome: T00's completion gate is met. The "inventory every rendered button" step is intentionally **partial** -- see coverage note below -- everything else in T00 is done with fresh evidence.

Files added:

- `oneforall/requirements-browser-dev.txt` -- Playwright pinned to `1.63.0` (confirmed current on PyPI via `pip index versions playwright` at pin time), dev/CI-only, documented separately from `requirements.txt`/`requirements-dev.txt`.
- `oneforall/tests/ui/action_registry.json` -- machine-readable action registry (schema documented inline in a `$schema_notes` key). 21 entries.
- `oneforall/tests/test_ui_action_registry.py` -- static schema/quality gate (no app, no browser). Rejects duplicate IDs, missing selectors, missing backend method/path, invalid classification/destructive-policy enum values, mutation actions with no `expected_failure_ui`, and entries with no personas.
- `oneforall/tests/ui/conftest.py` -- the harness: boots the real `main:app` via `uvicorn` in a background thread against an isolated per-session SQLite file (never `DATABASE_URL`, never the developer's `oneforall.db`/`themisiq.db`); `synthetic_tenant` fixture creates one disposable organization, one business unit, and one user per persona (all 11 roles in `core/rbac.py` that the plan names, plus `is_super_admin` handled correctly as its own column, not just a role row); `browser`/`page` fixtures wrap Playwright Chromium; `login_as(persona)` drives the real `/login` HTML form. Playwright is imported lazily inside the `browser` fixture (not at module top level) -- see "bugs found" below for why that matters.
- `oneforall/tests/ui/test_harness_smoke.py` -- T00's own completion-gate proof: real login (`auth.login.submit`), navigation check (`nav.launcher.my_dashboard`), modal open/close on `#addModal` (`aria.documents.add_document.open` -- deliberately the ARIA "Add Document" modal, which already uses the canonical `.modal-overlay`/`.modal` contract, so this proves the harness mechanism rather than prejudging the F02 fix), and one authenticated read-only API call (`GET /aria/api/templates`). Also asserts zero console/page errors.

Registry coverage (honest scope, not the full audit-counted ~993 buttons/398 links/1341 onclick handlers): 21 entries covering every action named in `findings.md` F01-F08 (ARIA managed-edit save, all 8 F02 broken-modal triggers plus their real mutation endpoints where distinct, ERM library add-template, email-settings Reset, webhook test-send) plus login and one nav item. Each entry's `route`/`selector`/`backend` was read directly from the current template/route source (not guessed) -- see the `notes` field on each entry for the exact file:line it came from. Full-app inventory beyond this slice is deferred, not silently dropped: each of T01-T06 is expected to add/update the registry entries for the module it touches (already true for aria.documents.save_changes, which documents exactly what T01 must change). This checkbox in `task_plan.md` is left unchecked for that reason.

Verification commands and results (all from `oneforall/`, `.venv` Python 3.12.14):

1. `..\.venv\Scripts\python.exe -m pytest tests/test_ui_action_registry.py -v` -- 117 passed in 0.14s.
2. `..\.venv\Scripts\python.exe -m pip install -r requirements-browser-dev.txt` then `python -m playwright install chromium` -- both succeeded; Chrome Headless Shell 153.0.8010.12 downloaded.
3. `..\.venv\Scripts\python.exe -m pytest tests/ui/test_harness_smoke.py -v -s` -- 1 passed in 9.59s (after fixing a test-side assertion bug of my own: `wait_for_selector(":not(.open)")` doesn't mean what it sounds like in Playwright -- fixed to `state="hidden"`).
4. **Red/green harness proof**: temporarily deleted the one line `document.getElementById('addModal').classList.add('open');` from `modules/aria/templates/documents.html`'s `openAddModal()` (a real application regression, not a fake test-side selector typo) -- reran step 3, got `playwright._impl._errors.TimeoutError: Page.wait_for_selector: Timeout 5000ms exceeded` (red, for the expected reason). Restored the exact original line; `git diff --check -- oneforall/modules/aria/templates/documents.html` showed zero diff; reran step 3 -- 1 passed in 9.90s (green again).
5. Full suite, `..\.venv\Scripts\python.exe -m pytest tests -q` -- **two bugs found and fixed** along the way (below), then two consecutive clean runs: exit 0, 631 passed, 10 skipped, 0 failed both times.
6. `python -m compileall -q .` -- exit 0. `python -m pip check` -- exit 0, "No broken requirements found." `git diff --check` (repo root) -- exit 0.
7. `git status --short` (repo root) -- only the files listed above plus this plan folder; nothing unrelated staged or changed.

Bugs found and fixed (both are test-infrastructure correctness bugs the new harness surfaced, not application/security logic; both are in-scope for T00 since they block the harness running reliably in the full suite):

- **`tests/test_security_hardening.py` restore bug**: all three `test_audit_isolation_*`/`test_audit_unscoped_returns_all` tests monkeypatch `modules.sentinel.data_service.get_db` directly (`ds.get_db = lambda: con`) and "restore" it with `ds.get_db = getattr(ds, "_orig_get_db", ds.get_db)` -- but `_orig_get_db` is never set anywhere in the file, so that expression always evaluates to the *current* (stub) value, i.e. the restore was a no-op. `ds.get_db` stayed bound to a `:memory:` SQLite connection created on the main pytest thread for the rest of the process. This was invisible before because nothing else in the suite called into `sentinel.data_service.get_setting()` from a different thread; the new UI harness's `login_submit` → MFA-policy check is the first thing that does, and it failed with `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread`. Fixed by capturing `orig_get_db = ds.get_db` before patching and restoring that captured value in `finally`, in all three tests.
- **`tests/conftest.py` missing pre-import**: added `import modules.sentinel.data_service` next to the existing (and exactly-applicable) `modules.erm.data_service`/`modules.governance.data_service` pre-imports, for the same documented reason already in that file's comment (a module that does `from database import get_db` at top level freezes that name the first time it's imported; importing it at collection time, before any fixture can be mid-patch, guarantees it freezes onto the real function).
- **Collection-time Playwright import side effect** (design fix, not a pre-existing bug): `tests/ui/conftest.py` originally did `pytest.importorskip("playwright.sync_api")` at module level, which -- because pytest imports every `conftest.py` during collection, before any test runs -- loaded Playwright's driver/threading machinery into the process before `test_aria_policy_publication.py::test_purge_expired_trash_leaves_recent_entries` (an unrelated, pre-existing, timing-sensitive `mtime`-vs-`time.time()` filesystem test) ran. Confirmed by bisection: full suite fails deterministically on that one test with `tests/ui` collected, passes cleanly with `--ignore=tests/ui --ignore=tests/test_ui_action_registry.py` on an otherwise-identical tree (checked against both the original stashed baseline and the fixed tree). Fixed by moving the Playwright import into the `browser` fixture body (`pytest.importorskip` called at fixture-setup time, not collection time), which confines the side effect to only when a browser test actually runs. `modules/aria/templates/documents.html` and `modules/aria/policy_storage.py` were never touched -- the fix stayed entirely inside the new `tests/ui/conftest.py`.

Explicitly unverified/skipped in this session:

- PostgreSQL gate (`test_postgres_init.py` against a disposable `themisiq_test_*` DB) -- no PostgreSQL instance available in this session; unverified, not passed. Required before any T03/T04 schema claim.
- CI wiring (T09) -- not started; the browser dependency is installed locally only.
- Dependency vulnerability scan / secret scan for `playwright`/`pyee` -- not run this session.
- No commit, push, migration, service restart, or deployment was performed. No production host or data was touched at any point (harness asserts `DATABASE_URL == ""` and that its SQLite file lives under pytest's own tmp dir; server binds `127.0.0.1` on an OS-assigned ephemeral port only).

## 2026-09-24 planning session

- Confirmed repository baseline: `2b98cc4549e5e74decab32e7bafa79985008b17b` on `master`, matching `origin/master` when audited.
- Confirmed the working tree was clean before plan creation.
- Converted the application audit into an ordered remediation and product-improvement programme.
- No application source, test, schema, configuration, secret, deployment, or production changes were made.
- No commit, push, migration, service restart, or deployment was performed.

## How future implementers must update this ledger

After every task, append:

1. task identifier and outcome;
2. exact files changed;
3. exact verification commands and summarized results;
4. unverified or skipped checks, stated explicitly;
5. commit SHA only if the user separately authorizes a commit;
6. production release evidence only if the user separately authorizes deployment.

Never replace this file with a generic completion statement. Preserve earlier entries.
