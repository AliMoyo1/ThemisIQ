# 05. Execution ledger

**Purpose.** The design plans stay proposals. This file records what was actually built, how it was verified, what was
skipped, and what stays switched off. A slice is marked built only with evidence listed here. Started 2026-10-11 on branch
`claude/pg-layer-scope-and-findings`, baseline commit `8039af4` (pushed). Nothing in this ledger is a production release
decision; every flag below defaults to the safe state.

## Handoff: where this stands and how to continue (reconciled 2026-10-14)

Read this section first; everything after it is the evidence trail. The owner's standing request is to finish the AI
Governance programme slice by slice, run full suites only after a major stage, and state what cannot be checked on a laptop.
G5 and G6 apply steps below are retained as a record and must not be repeated. G6 was committed and pushed at `4384c79`;
its milestone lanes passed as recorded below. The production tenant-copy inspection found no old copies. G7's content-neutral
oversight foundation was merged to `master` on 2026-10-13 (PR #6, `dfaa357`) together with G1 to G6, after a startup repair
(PR #8, `fe1b12f`) and a navigation fix (PR #9, `f855c9d`); `origin/master` is `f770d33`, which the owner's VPS output
reported healthy on 2026-10-14. EU rule content still requires recorded legal approval.

**What comes next is the specialist rework programme** in [`plans/2026-10-governance-rework/`](../2026-10-governance-rework/README.md)
(planning documents 01 to 06, written 2026-10-14). Its implementation record is
[07-implementation-ledger.md](../2026-10-governance-rework/07-implementation-ledger.md). This ledger keeps the history of G1 to G7
and is not rewritten for that work; the rework links back here.

### 1. State of each slice

| Slice | Code | In the working tree and wired | Verified |
| --- | --- | --- | --- |
| G1a, G1b, G1c, G2 | done | yes | milestone lanes below |
| G3, G3b, rollout switch, G4 | done | yes | milestone lanes below |
| G5 monitoring, evaluation records, regulatory impact, Explain | done | yes | focused checks and the full G6 milestone lanes below pass |
| G6a review packs | done | yes | focused checks and the full G6 milestone lanes below pass |
| G6b AI literacy | committed at `4384c79` | service, pages, API, My Work and quality wiring | focused checks and the full G6 milestone lanes below pass |
| G6c platform AI features | committed at `4384c79` | public-only operator notes, registry list, tenant usage metadata and page | focused checks and the full G6 milestone lanes below pass; production old-copy check found none |
| G7 content-neutral oversight foundation | merged to `master` (PR #6, `dfaa357`, 2026-10-13); in the release reported healthy at `f770d33` | versioned design and operation records, scoped person picker, workspace, Monitoring, Decisions and My Work | focused service, HTTP, browser and real PostgreSQL checks passed; a full disposable PostgreSQL lane passed; the local full backend run had two ARIA policy failures outside G7 that passed on focused rerun; no EU rule content enabled; see section 8 and the 2026-10-13 change log entries |

### G6b build record, 2026-10-12

- `modules/ai_governance/literacy.py` owns course drafts, compare-and-set saves, immutable published editions, derived
  role, owner and unit assignment, grading, renewal and unit-scoped coverage. A first publication or a later publication
  requiring a retake enqueues the existing `AI_LITERACY_PUBLISHED` event after the course change, in the same transaction.
  The existing notification handler uses the current audience and event ID for once-per-person delivery.
- The learner, manager and reporting APIs and the two pages are wired in `modules/ai_governance/routes.py`,
  `templates/literacy*.html` and `static/js/ai_governance_literacy.js`. Learners receive prompts and options but never the
  correct options. The manager sees the working copy. Reports show one person at most once per course, with individual
  rows limited to 200 names within the viewer's unit scope. These responses use `private, no-store`.
- My Work derives one item for each assigned course needing completion. AI use quality adds a dismissible owner literacy
  warning when an active owner-targeted course lacks a current completion. Neither changes a tier or decision.
- Audience and timing are course metadata rather than published-version fields in the existing G6b schema. Saving the
  audience or due time on an active course changes derived assignments and due dates immediately. Renewal changes apply
  to future completions; stored expiry dates stay historical. The manager page says this. A save alone does not send an
  assignment notification. Publishing with a retake sends one notification to the resulting audience.
- Added a completion lookup index in both SQLite and PostgreSQL tenant schema definitions. The existing idempotent
  tenant-schema replay applies it to existing PostgreSQL tenants on startup.
- Static checks completed: `python -m py_compile` for the changed Python service and wiring, `node --check` for the
  new JavaScript, Jinja parsing for the new pages and sidebar, and `git diff --check` for tracked edits. No focused,
  HTTP, browser, real PostgreSQL or full-suite tests were run in this slice. The owner asked
  to defer full suites until a larger stage; focused verification remains outstanding too. The change is not committed,
  pushed or deployed.

### G6c build record, 2026-10-12

- `modules/ai_governance/platform_features.py` lists the registered first party AI call sites from
  `core/ai_policy.FEATURES` in registry order. It combines declared data categories with public operator notes and grouped
  `ai_usage_log` metadata from public history and every tenant schema. It counts successful, refused and error calls
  separately and shows the last successful use. It does not read or store prompts, answers or evidence.
- The operator may save owner, provider and model note, known limitations, incident path, deployment decision and next
  review date. A compare-and-set version prevents lost updates. Changing notes clears the previous review; a completed
  review requires these fields and a future next-review date. A missed due date reads overdue. Deployment here is an
  oversight record and does not switch a model call on or off.
- `/ai-governance/platform-features` and its three API routes are available only with the super administrator capability
  `ai_governance.platform.manage`. The service checks the capability again. The route binds the public schema, the service
  refuses a non-public PostgreSQL connection, and the API returns `private, no-store`. The page labels itself as an internal
  operator record, not a customer inventory or certification. Audit entries record saves and completed reviews.
- The dormant `platform_ai_features` definition had been inside `_PLATFORM_TABLES`, which provisions tenant copies.
  It is now in `_SHARED_TABLES` so new deployments create it only in public. Existing tenant copies, if already created,
  are unused and are not dropped automatically. Before a PostgreSQL release, inspect whether any such copies have rows;
  no automatic data deletion or migration is implied by this build.
- Static checks passed: Python syntax for the service, routes and schema; JavaScript syntax; Jinja parsing for the new
  page, sidebar and styles; `git diff --check` for tracked edits; and whitespace inspection of the three new files. No
  focused, HTTP, browser, real PostgreSQL or full-suite tests were added or run in this build slice. The later focused
  verification below supersedes that test status. Nothing was committed, pushed or deployed.

### G6b and G6c focused verification, 2026-10-12

- `tests/test_ai_governance_g6bc.py`: 8 passed. These cover answer-key removal, grading and failed-attempt non-persistence,
  duplicate completion, retake and stale edition, role and unit assignment, scoped coverage, explicit acknowledgement,
  expiry and the My Work item, the owner quality signal before and after completion, one notification on publication,
  registry-bound notes, validation, optimistic version checks, review state, usage status counts, signed-out and denied
  HTTP paths, indistinguishable missing/wrong-unit course responses and private no-store.
- `tests/ui/test_ai_governance_g6bc_ui.py`: 2 passed together in a disposable SQLite app. A DPO created and
  published a course; an employee completed it. A super administrator searched registered features, saved oversight
  notes and marked one reviewed; a DPO could not open that page. Both journeys passed the critical/serious axe scan.
- `tests/test_postgres_init.py::test_ai_literacy_and_platform_feature_notes_use_their_postgres_schemas`: 1 passed against
  the guarded, disposable `themisiq_test_aigov` PostgreSQL database. It confirmed a tenant literacy completion, a
  public-only note row, no new tenant note table and one tenant usage call counted on the public operator screen.
- Before the destructive test fixture reset that disposable database, a read-only catalog query found one old tenant
  copy, `tenant_aipack.platform_ai_features`, with **0 rows**. This was the local test database only. The owner then
  ran the validated read-only count against the app database on the production VPS from `/project`. The command exited
  successfully with no rows, meaning **no tenant copies** of `platform_ai_features` exist there at the time checked.
  No migration or deletion is needed for those copies on that database. Recheck if another environment is released.
- Cross-tenant aggregation with multiple provisioned organizations was not directly tested in this focused slice.
  The broad suites ran in the G6 milestone below. No commit, push or deployment occurred during the focused verification.

### G6 milestone verification, 2026-10-12

- Full backend lane, with `tests/ui` excluded and no PostgreSQL URL: **2079 passed, 66 skipped**, exit 0.
- Guarded `tests/test_postgres_init.py` against the disposable local `themisiq_test_aigov` database: **66 passed**, exit 0.
- Full browser lane against the disposable SQLite app, after two repairs: **481 passed, 2 skipped**, exit 0. The
  earlier workspace keyboard journey still expected the retired "Nothing is measured" placeholder. It now checks the
  G5 source-based monitoring empty state. The task board used a generic low-contrast label for AI Governance tasks;
  a synthetic task reproduced 3.88:1 contrast. It now has a named module color, label and destination. The new
  populated-task accessibility regression and the existing `/tasks` route check pass.
- These are local verification results, not production readiness or a release approval. The G7 EU content pack still
  requires a recorded legal/content owner approval before it can be enabled.

### 2. What the previous full verification covered

Milestone run of 2026-10-11 (backend with `tests/ui` excluded, then the real PostgreSQL lane, then the browser lane), on the
tree that held G1 to G4, the switch, the separation setting, the decision export, the Sentinel write scope patch and the
canonical vendor index:

- **Backend** (SQLite): 1928 passed, 63 skipped, 2 failed. Both failures were expectations that my own changes had made
  stale, not bugs: the Decisions tab is now live (was "not started"), and My Work gained the `ai_governance` source. Both tests
  were corrected on 2026-10-12 and the two pass again (run together with the 33 pack rule tests: 35 passed). The whole
  backend lane was **not** re-run after the correction.
- **Real PostgreSQL** (`tests/test_postgres_init.py`): 63 passed.
- **Browser** (`tests/ui`): 467 passed, 2 skipped.

The G5 and G6a test files were created after those lanes had started collecting, so none of them was in those numbers.
Before that milestone: G3 + G3b + switch backend 1787 passed, 60 skipped; PG 62 passed plus one nondeterministic test of mine
that was fixed.

### 3. Files prepared for G5 and G6a

G5 and G6a are wired and their focused lanes passed. The broad suites were deferred at this point and later ran at the
G6 milestone recorded above.

| Kind | Files |
| --- | --- |
| G5 modules | `modules/ai_governance/evaluations.py`, `monitoring.py`, `regulation.py`, `explain.py` |
| G5 page and script | `modules/ai_governance/templates/regulatory.html`, `static/js/ai_governance_monitoring.js` |
| G5 tests (backend) | `tests/test_ai_governance_evaluations_rules.py` (11), `_regulation_rules.py` (18), `_evaluations.py` (11), `_regulation.py` (7), `_monitoring.py` (5), `_explain.py` (7), `_g5_routes.py` (13); all 72 pass |
| G6a module and tests | `modules/ai_governance/review_packs.py`; `tests/test_ai_governance_pack_rules.py`, `tests/test_ai_governance_packs.py` (57 together), `tests/test_ai_governance_pack_routes.py` (3), `tests/ui/test_ai_governance_packs_ui.py` (1), a focused real PostgreSQL case |
| G5 integration cases | `tests/ui/test_ai_governance_monitoring_ui.py` (9 pass), the G5 case in `tests/test_postgres_init.py` (1 pass) |
| Scripts that apply the wiring | `handoff/patch_g5_core.py`, `handoff/patch_g5_wire.py`, `handoff/patch_g6_core.py`; `handoff/run_milestone.sh` runs the three lanes |

### 4. G5 apply record (completed; do not repeat)

Every command runs from `oneforall/` (the scripts use paths relative to it). Each script asserts that every anchor occurs
exactly once and stops with an assertion if one does not. A script writes file by file, so if one stops half way, look at
which files it printed as patched, do not re-run it (the already patched anchors are gone), and apply the remaining edits by
hand from the script's text. The files are CRLF in places; the scripts preserve it, and so must any hand edit.

1. G5 core: schema in both DDL blocks, the unit reference guard, the event constant, the `governance.explain_ai_use` feature,
   decision reopening on a failed evaluation or a confirmed regulatory change, two quality rules, two notification handlers.

```bash
../.venv/Scripts/python.exe ../plans/ai-governance/handoff/patch_g5_core.py
```

2. G5 wiring: routes and the regulatory page, the sidebar entry, the Monitoring tab, the "Explain this status" button, the My
   Work item and the reopening reasons in My Work.

```bash
../.venv/Scripts/python.exe ../plans/ai-governance/handoff/patch_g5_wire.py
```

3. Put the two held tests back: the browser test into `tests/ui/`, the PostgreSQL test appended to `tests/test_postgres_init.py`
   (it uses that file's helpers `_ai_governance_world`, `_AI_GOOD` and `_raw_rows`).

```bash
cp ../plans/ai-governance/handoff/held_tests/test_ai_governance_monitoring_ui.py tests/ui/test_ai_governance_monitoring_ui.py
```

```bash
cat ../plans/ai-governance/handoff/held_tests/pg_g5_test.py >> tests/test_postgres_init.py
```

4. One expectation changes with the wiring: `tests/test_ai_governance_service.py::test_the_decisions_and_monitoring_tabs_say_plainly_that_nothing_is_recorded_or_measured`
   still asserts that the monitoring tab is `not_measured`. After step 2 the tab is `ok` with one section per source, and each
   source that has nothing recorded says `not_measured`. Change that last assertion to the sections' states.
5. The G5 tests were run after the wiring. Their first failures exposed fixture assumptions and the PostgreSQL DDL order;
   the focused backend, browser and PostgreSQL lanes now pass.

```bash
env -u TEST_DATABASE_URL ../.venv/Scripts/python.exe -m pytest -p no:warnings -o addopts="--tb=short" -q tests/test_ai_governance_evaluations_rules.py tests/test_ai_governance_regulation_rules.py tests/test_ai_governance_evaluations.py tests/test_ai_governance_regulation.py tests/test_ai_governance_monitoring.py tests/test_ai_governance_explain.py tests/test_ai_governance_g5_routes.py
```

6. Regenerate the capability inventory (CI runs the same script with `--check`) and run the model call guard, which reads the
   source and needs the new call site to name a registered feature as a string literal.

```bash
../.venv/Scripts/python.exe scripts/capability_inventory.py
```

```bash
env -u TEST_DATABASE_URL ../.venv/Scripts/python.exe -m pytest -p no:warnings -o addopts="--tb=short" -q tests/test_ai_call_guard.py
```

7. G6a was applied once and wired. Do not run `handoff/patch_g6_core.py` again. G6b and G6c are built in the working tree; their focused and full milestone lanes passed on 2026-10-12.
8. After a major step run the three lanes with `handoff/run_milestone.sh` (set `AIGOV_TEST_DATABASE_URL` first) and record the
   numbers in the change log below.

### 5. Conventions that the code and the tests rely on

- **Service layer.** A function takes `(db, user, ...)`, checks the capability and the unit scope itself, never commits, and
  returns `{"audit": [(action, entity_type, entity_id, detail)], "events": [event ids]}` which the route handles after the
  commit through `service.audit` and `service.deliver`. A hidden record answers exactly like a missing one (404). A change
  carries the `version` it was based on; a stale one is a 409. Errors are `ServiceError(status, message, **extra)`; field
  errors are a 422 with `errors={field: sentence}`.
- **Routes** use `_transact` (commit, audit, deliver; rolls back on `ServiceError`), `_read`, `_body` (400 unless a JSON
  object), `_error`, `_page`. The one exception is opening a review pack, which must commit its own access record even when
  it refuses (see [09](09-g6-build-plan.md) section 5.1).
- **Scope.** `modules/governance/entity_scope.py` is the only registry (`entity_scope_sql`, `describe_record(s)`,
  `may_view_kind`, `record_unit`). A NULL unit is organization wide. A new table with a unit goes into `_BU_REFERENCES` in
  `modules/governance/data_service.py`, not in `database.py`.
- **Schema.** Governance tables are written twice in `database.py`: once in `_SHARED_TABLES` (tenant) and once in
  `_PLATFORM_TABLES`; edit both. A column added to an existing table goes into `_COLUMN_MIGRATIONS` (one list for SQLite and
  PostgreSQL). An index on a pre-existing table goes into both `_POST_MIGRATION_INDEXES` (SQLite) and the `_run_pg_alters`
  tuple (PostgreSQL).
- **Model calls** go through `core/ai_client.py::create_message(..., feature=, sources=)`. The feature key matches
  `[a-z]+\.[a-z0-9_]+`, is registered in `core/ai_policy.FEATURES` with the categories of data it sends, and is passed as a
  string literal (`tests/test_ai_call_guard.py` reads the source).
- **Events.** `events.enqueue(db, ...)` writes the event on the caller's connection with a dedup key; handlers live in
  `modules/ai_governance/handlers.py` and use `_notify(db, event_id, user_id, title, message, link)`, which is unique per
  event and person, and `_holders(db, capability, unit_id, org_id, exclude)`.
- **Frozen decisions hold ids and facts only;** names are looked up again for each viewer (`present_manifest`), so a decision
  never discloses a title to someone who may not open it.
- **Front end.** No inline script, no `innerHTML`, text through `textContent`; dialogs are `.aig-dialog`; the shared helpers
  are on `AIGov` in `static/js/ai_governance_common.js`. The CSP forbids `unsafe-eval`, so browser tests wait on selectors.
- **Tests.** Use the `world` fixture of `tests/test_platform_ownership.py` (personas `super`, `dpo_a`, `dpo_a1`, `dpo_b`,
  `dpo_no_unit`, `owner_a`, `owner_b`, `employee_a`) and the helpers of `tests/test_ai_governance_service.py` (`FULL`,
  `submitted`, `approve_new`, `commit`, `count`, `fail`, `user`, `roles`). Browser tests use `tests/ui/conftest.py`
  (`login_as`, `run_axe`) and `_accepted_system` from `tests/ui/test_ai_governance_pages.py`. Real-PG tests use the `pg`
  fixture and `_ai_governance_world` in `tests/test_postgres_init.py`. Write assertions that can fail: no `or True`, no
  alternatives that match anything.

### 6. Rules to keep following

- Use the repo's interpreter, `C:\Projects\One For All\One For All\.venv\Scripts\python.exe`; the global Python silently skips
  the browser tests. Run pytest from `oneforall/`, **one pytest session at a time**, with `env -u TEST_DATABASE_URL` for SQLite
  runs and `-o addopts="--tb=short"` (the ini sets `-q --tb=short`).
- Do not edit application code while a pytest run is in progress (a lazily imported module can be read half edited). New test
  files and brand-new modules nothing imports yet are safe, but a new test file placed where a later lane collects it will
  show up in that lane.
- Never commit or push without an explicit instruction. Commit messages end with `Co-Authored-By: Claude Sonnet 5.5
  <noreply@anthropic.com>`; pull request descriptions end with the "Generated with Claude Code" line the harness gives you.
- Do not stage files that belong to another chat or are runtime artefacts: `PLAN_ai_governance_planning_2026-10-09.md`,
  `PLAN_sentinel_write_scope_2026-10-11.md`, `plans/ai-governance.zip`, `plans/verifywise-features.zip`, `data/oneforall.db-shm`,
  `data/oneforall.db-wal`, and the modified `plans/PLAN-37-connected-compliance-experience.md`, `plans/ROADMAP-2026-10.md`,
  `plans/verifywise-features/README.md`. Do not touch `.claude/worktrees/*`.
- This repository is ThemisIQ only (AGENTS.md): no EcoAegis or ODIN content. The target is a Hetzner Ubuntu VPS with
  PostgreSQL behind `themisiq-app.service`; the code must have no security flaws.
- Style set by the owner: no em dashes anywhere; never put a pipe character in a command given to the user; one command per
  step in its own fenced block; keep a plan file and log what changed; shortest correct diff, but never drop validation,
  security or tests.
- Do not use sub-agents unless the owner asks. A foreground `sleep` is blocked here: wait with a background loop that polls
  for the `exit:` line. A Bash heredoc containing apostrophes or backslashes breaks the tool; write files with the Write or
  Edit tools.
- Report outcomes faithfully: state failures with their output and say what was not verified.

### 7. Environment still running

- A throwaway PostgreSQL container, `themisiq-pg-aigov`, is up on `127.0.0.1:55433` with database `themisiq_test_aigov`. The
  guard needs a database name starting `themisiq_test_`, `THEMISIQ_ALLOW_DESTRUCTIVE_PG_TESTS=1` and `TEST_DATABASE_URL`. The
  connection recipe is in the memory file `reference_test_environment.md`; do not print credentials in replies or files.
  **Remove it when the programme is finished**: `docker rm -f themisiq-pg-aigov`.
- G7 was built in a separate Codex worktree and is merged; that worktree (`C:\Users\isadmin\.codex\worktrees\g7-oversight`) and
  `.worktrees/ai-governance-nav` are no longer part of this work. Stage files by name so other worktrees remain untouched.
- The local checkout was fast-forwarded to `origin/master` (`f770d33`) on 2026-10-14. It carries no uncommitted application
  change of its own; three plan files modified by another chat (`plans/PLAN-37-connected-compliance-experience.md`,
  `plans/ROADMAP-2026-10.md`, `plans/verifywise-features/README.md`) and several untracked planning, test-output and database
  files remain and must not be staged.

### 8. What is not built, and what is waiting on the owner

**Not built by design (each is a plan gate, not an omission).**

- *Shadow AI discovery and any gateway.* The plan requires a named, authorized feed with documented fields, retention,
  residency and an owner. None exists. No scraper, agent, prompt capture or manual import was added.
- *Model component lineage.* "If needed"; nothing asks for it.
- *Public trust page, anonymous links, certified or readiness wording.* Out of scope by decision 7.
- *Running evaluations.* ThemisIQ records a run a person or an organization's own system produced; it executes nothing. The
  Ask ARIA baseline is its existing test suite, not a scheduled run. Runs against a platform feature are not built.
- *Regulatory sources.* The inbox is manual; nothing fetches regulation text.
- *Reminders by email* for training and decisions: My Work and one notification per event only.

**G7 (conditional EU content).** Blocked on decision 8: the rule content needs a recorded legal approval of the current rule
version and effective dates, which cannot be given from here. Do not write obligation text, roles or deadlines from memory.
The owner asked to start G7. The content-neutral human oversight foundation is built and verified with focused checks in a
separate worktree (see `PLAN_G7_OVERSIGHT.md`). It records internal arrangements and review history, and connects live status
to Monitoring, Decisions and My Work. It does not alter signed decision manifests. No EU applicability, obligation,
deadline or compliance claim is enabled. The conditional EU content pilot remains blocked.

**CISO assurance briefs.** Read of each, not built:

- *01 quality inspector.* The AI use already has one (`quality.py`, G3), which is the model for a platform wide read. A wider
  one needs the "claim contract" inventoried across ARIA, GRID and ERM and rule semantics agreed with each module's owner
  (the brief says so); the brief's own list of four rules is the place to start.
- *04 risk acceptance.* ERM owned. `ai_use_decisions` is the pattern (frozen manifest, derived state, conditions, expiry). The
  brief lists four policy decisions that come before any schema (who approves by band, whole risk or per factor, which
  figure is authoritative, maximum duration).
- *02, 03, 05, 06* need discovery or prerequisites that are not local: permission checked mappings, GRID audit scope,
  customer framework content with source rights, and an invitation threat model for accountless uploads.

**Decisions that are the owner's, adopted by default and not yet confirmed.**

| Id | Question | Default adopted |
| --- | --- | --- |
| D2 | Who may write AI impact assessments | the union of the privacy team and the AI reviewers (compliance manager, GRC officer, risk owner and org admin gain write access they did not have in Sentinel) |
| D3 | Sentinel licence needed to open AI impact assessments | no |
| D4 | Approved assessments can be deleted | no (refused with a message) |
| | Sentinel navigation keeps its privacy link | yes |
| | Platform default for the AI policy | compatibility (an organization with no policy keeps today's behavior); "deny until a policy exists" is a release decision |
| | Separation of duties on decisions | on; an org admin may turn it off and each decision then says so |
| | Review packs, literacy, platform features | decision rows 13 and 14 above |
| | Sentinel write scope, round 4 | stamp the creator's unit on RoPA, DPIA and breach create, and the links that already cross units: see `PLAN_sentinel_write_scope_2026-10-11.md` |

**What cannot be done from a laptop and is not claimed.** Staff, DPO and auditor journey observation, baseline task times,
two or three named pilot uses, a read of the production schema and row counts, a rights review of framework text, the legal
approval of EU content, and any live feed. The pilot outcome metrics in `03-delivery-and-acceptance.md` section 5 are not
claimed. The migrations in this ledger have run on SQLite and on a throwaway PostgreSQL 18 only.

## G0. Baseline and decisions

**Baseline reconciled (read only).** Branch is level with `origin`; the working tree held only unrelated planning files from
another chat (these plans) when this started. PLAN-36's release gate is not part of this ledger. Evidence Vault Phase 1a is
committed (`fe74628`) and its PostgreSQL lane ran on 2026-10-08. Platform risks, SLA clocks and workflow instances carry a
business unit since `8039af4`. Unit scope for cross-module reads is one registry (`modules/governance/entity_scope.py`).

**What could not be done here, and what stands in for it.** The plans ask for staff, DPO and auditor journey observation,
baseline task times, 2-3 named pilot uses, a read of the production schema and row counts, a rights review of framework text,
and legal approval of EU content. None of that can be observed from a laptop. Stand-ins: the recommended defaults below are
adopted as the working policy; three synthetic pilot uses (an embedded vendor assistant, an in-house screening model, and
the first-party Ask ARIA feature) seed demonstrations and tests; baseline measurements stay empty and the pilot outcome
metrics in `03-delivery-and-acceptance.md` section 5 are not claimed. Production schema and counts are the owner's check
before rollout.

### Decisions adopted (the recommended defaults of `03-delivery-and-acceptance.md` section 6)

| # | Decision | Adopted |
| --- | --- | --- |
| 1 | One AI use versus component | One business deployment is one `applications` row with one AI profile. Components stay out until a pilot needs several models in one use. |
| 2 | Visibility across business units | Business-unit scope on every read (same rule as every scoped table: NULL is organization wide, a parent unit sees its children). No org-wide exception beyond NULL. |
| 3 | Who submits, reviews, decides | Submit: every staff role except the external auditor. Review and promote into `applications`: the five `governance.entities.manage` roles plus the DPO. Decide: GRC officer, compliance manager, DPO, risk owner, super administrator, with separation of duties on by default. |
| 4 | When an assessment is required | Versioned rule set (`rules v1`); anything unanswered is `needs review`, never low risk. The reviewer may mark a step not applicable with a reason. |
| 5 | What reopens a decision | Purpose, data categories, model or provider, autonomy, deployment, jurisdiction, a serious incident, a failed critical control, expired required proof (fingerprint of the facts the decision covered). |
| 6 | What may go to an AI provider | Enforced per organization at one wrapper. Release default is compatibility mode (an organization with no policy row keeps today's behavior); an organization with a policy row is held to it. Flipping the platform default to deny is a release decision recorded here, not a code change. |
| 7 | Auditor and public views | Named, authenticated packs only. No public trust page, no anonymous links, no certified or seal wording. |
| 8 | Framework content licensing | Only content the customer is authorized to use; no licensed text is shipped. EU AI Act applicability stays a conditional pack that needs a recorded legal approval before it can be switched on. |
| 9 | Where the AI impact assessment lives | Moves from Sentinel into AI Governance on the owner's instruction of 2026-10-11 (plan [06](06-aiia-in-ai-governance.md), slice G3b). Tables and link identity are unchanged; three new capabilities (`ai_assessment.view`, `.manage`, `.configure`); DPIA and RoPA stay in Sentinel. Adopted by default and still to confirm: the wider write set (D2), no Sentinel licence needed (D3), approved assessments cannot be deleted (D4). |
| 10 | AI Governance entry points | A per-organization switch (`core/ai_rollout.py`), off unless `AI_GOVERNANCE_DEFAULT_ENABLED` says otherwise, set by a platform administrator on the AI Policy page. It hides the navigation link, the "Uses AI?" questions and the Vault target. It is a visibility control, not a security control: capability and unit scope decide what a person may do whether it is on or off. The AI impact assessments are not behind it, because they are functionality that already existed. |
| 11 | Separation of duties on decisions | On by default: the decider is neither the person who asked nor the system's owner. An organization administrator may turn it off (one person may be the whole function); the choice is audited and each decision made while it is off carries that fact. |
| 12 | What reopens an approval (G5 amendment of decision 5, applied) | Besides a changed profile fact, a tier change, an expired approval and expired signed proof: an evaluation recorded as failed or interrupted after the decision was signed, and a regulatory change confirmed for the use after it was signed. What was recorded before the signing stands behind it. |
| 13 | Review packs (G6a, built and verified) | One named, signed-in person of the same organization per pack, 1 to 90 days (default 30), preview hash must match at issue, names and free text out unless chosen, download off unless chosen, never a certification wording. Issuing needs `ai_pack.manage` (the deciders' set); receiving also covers auditor, audit lead and external auditor. Adopted by default; to confirm. |
| 14 | AI literacy and the platform's own AI features (G6b and G6c, built and verified; the rework programme proposes moving learner work to a separate staff project, see the 2026-10-14 entry) | Literacy is its own small domain inside AI Governance; BCM attestations and Sentinel training stay where they are and are never counted as AI course completions. The platform feature inventory is operator only and stores notes, never customer content. Adopted by default; to confirm. |

### Field ownership (profile, application, AIIA, RoPA, DPIA)

| Fact | Owner | Others |
| --- | --- | --- |
| Name, owner, business unit, department, vendor, hosting, criticality, active or retired | `applications` | Profile and AIIA read it |
| Purpose, AI capability type, intended users, affected people, autonomy, deployment context, intended jurisdictions, model or service reference, review cadence, provisional tier and its rule version | `ai_use_profiles` (one row per application) | AIIA snapshots what it assessed and prefills from here |
| Impact dimensions, mitigation, classification, residual classification, reviewers, status | `sentinel_aiia` (screen and service owned by AI Governance from G3b; until then Sentinel) | Workspace shows status and links |
| Processing purpose, categories, lawful basis, recipients, retention, transfers | RoPA | Linked, never copied |
| Privacy assessment | DPIA | Linked |
| Risk, treatment, acceptance | ERM, ORM AIMS | Linked; acceptance is a separate signed decision |
| Policy version and approval | ARIA | Linked |
| Evidence item, version, verification | Evidence Vault | Linked by version in decisions and packs |

### Capability matrix (new, mapped explicitly in `core/rbac.py`)

| Capability | Roles | Meaning |
| --- | --- | --- |
| `ai_use.submit` | all except external auditor | Create, resume and submit own intake drafts |
| `ai_use.view` | all except external auditor | List and open AI systems inside the viewer's unit scope |
| `ai_use.review` | super administrator, GRC officer, compliance manager, risk owner, org admin, DPO | Return, reject, promote or link an intake; edit profile |
| `ai_use.link` | same as review, plus the system's owner (object check) | Create and remove relationships from the workspace |
| `ai_use.decide` | super administrator, GRC officer, compliance manager, risk owner, DPO | Sign a decision on a frozen manifest |
| `ai_governance.policy.manage` | super administrator, org admin | Provider and data-category policy, usage view |
| `ai_assessment.view` | super administrator, DPO, privacy analyst, compliance manager, GRC officer, risk owner, org admin | List and open AI impact assessments inside the viewer's unit scope. Was `module.sentinel.access` |
| `ai_assessment.manage` | same as view | Create, edit, link and delete AI impact assessments. Was `sentinel.dpia.manage`, which excluded compliance manager, GRC officer, risk owner and org admin |
| `ai_assessment.configure` | super administrator, DPO, privacy analyst, org admin | Manage the impact dimensions list (changes how every assessment is scored) |
| `ai_pack.manage` (G6a, applied) | super administrator, GRC officer, compliance manager, risk owner, DPO | Preview, issue, list and revoke review packs for uses the caller may open |
| `ai_pack.receive` (G6a, applied) | the five above plus audit lead, auditor, external auditor | Open a pack addressed to the caller. Needs no other AI governance access |
| `ai_literacy.take` (G6b) | all except external auditor | Assigned courses |
| `ai_literacy.manage` (G6b) | super administrator, org admin, DPO, GRC officer, compliance manager | Define, publish and retire courses |
| `ai_literacy.report` (G6b) | the five above plus risk owner | Scoped coverage reports |
| `ai_governance.platform.manage` (G6c) | super administrator | First party AI feature notes and review |

### Migration inventory (additive, nullable, no guessed data)

What the code now creates, in the shared schema and, through the existing runners, in every tenant schema:

| Slice | New tables | New columns and indexes |
| --- | --- | --- |
| G1a | none | `cross_module_links.provenance`, `status`, `confirmed_by`, `confirmed_at`, `note`; PostgreSQL only: the unique index `idx_xlinks_dedup_uq` (see the first finding below) |
| G1b | `event_deliveries` (shared schema) | `events.attempts`, `last_error`, `next_attempt_at`, `dead_lettered_at`, `org_id` |
| G1c | `ai_usage_log` | none; the policy is one JSON value in `settings` (`ai.policy.org<id>`), so it needs no table |
| G2 | `ai_use_profiles`, `ai_use_intake_requests` | `applications.retired_reason`, `retired_at`, `retired_by`; `aims_assessments.application_id`; `notifications.source_event_id` with a partial unique index; `canonical_vendors` and `business_processes` get `uses_ai`, `uses_ai_note`, `uses_ai_source`, `uses_ai_set_by`, `uses_ai_set_at` |
| G3 | `ai_use_step_overrides`, `ai_use_finding_dismissals`; `ai_control_mappings` (with the ERM and ORM tables) | `ai_use_profiles.material_changed_at`; index `idx_ai_control_mappings_canonical` |
| G3b | none | `sentinel_aiia.version` (default 1); index `idx_aiia_application`. No row moves: the AI impact assessment keeps its three tables, reference numbers and link identity |
| G4 | `ai_use_decisions` (one open request per application, by a partial unique index), `ai_use_decision_conditions` | none on existing tables; `ai_use_decisions` is in the business unit reference guard |
| Switch | none | two rows per organization in `settings`: `ai_governance.enabled.org<id>` and `ai_governance.separation.org<id>`, written only by the two admin calls |
| Canonical vendors (spawned session, integrated) | none | PostgreSQL unique index on `canonical_vendors` names, created after a merge of duplicates that repoints every holder including `applications.vendor_id` (no foreign key). Data migration: read the log of the first start |
| G5 (applied in working tree) | `ai_evaluation_runs`, `ai_regulatory_impacts` | in both DDL blocks; both in the business unit reference guard. PostgreSQL requires `regulatory_updates` before `ai_regulatory_impacts` because of its foreign key |
| G6 (schema applied) | `ai_review_packs`, `ai_review_pack_events`, `ai_literacy_courses`, `ai_literacy_versions`, `ai_literacy_completions` (tenant), `platform_ai_features` (public schema only in current DDL) | Applied once with `handoff/patch_g6_core.py`; G6a, G6b and G6c passed focused verification. The three tables with a unit are in the business unit reference guard |
| G7 | `ai_oversight_heads` (one row per use and track: `design` or `operation`), `ai_oversight_versions` (append only content versions bound to a profile version, with `draft` or `reviewed` status and separate author and reviewer) | none on existing tables; no new capability (the routes use `ai_use.view`, `ai_use.review` and `ai_use.decide`); the capability inventory gained four routes |

A migration that touches data: on the first PostgreSQL start `_ensure_pg_link_dedup_index` deletes exact duplicate rows of
`cross_module_links` (same source, target and verb), keeping the oldest, then creates the unique index. It logs how many it
removed. The owner should read that count from the first start's log before the next release.

Not manufactured by any migration: approvals, training completion, risk acceptance, evidence versions, a match between an AIIA
and an application. `sentinel_aiia.application_id` is set only by a person, from the AIIA screen or by a reviewer promoting a
request, and the route refuses an application the writer cannot open.

## Slice status

| Slice | Status | Evidence |
| --- | --- | --- |
| G1a Relationship registry (one registry, three folded) | built, verified (SQLite, real PostgreSQL) | `tests/test_relationships.py` (64), real-PG tests for typed edges, scope and duplicate collapse in `tests/test_postgres_init.py`, the Related Items and Vault suites |
| G1b Events: atomic enqueue, retry, dead letters | built, verified (SQLite, real PostgreSQL) | `tests/test_event_delivery.py` (18), two real-PG tests (retry and dead letter inside the right tenant, enqueue with a claim), the existing event suites |
| G1c AI service foundation (wrapper, policy, usage, guard) | built, verified (SQLite, real PostgreSQL, browser) | `tests/test_ai_policy.py` (32), `tests/test_ai_call_guard.py` (62), `tests/test_ai_policy_admin.py` (22), `tests/ui/test_ai_policy_page.py` (7), one real-PG test |
| G2 Intake, profile, inventory, workspace | built, verified (SQLite, real PostgreSQL, browser); pilot observation not possible here | `tests/test_ai_governance_rules.py` (46), `_service.py` (75), `_routes.py` (66), `_integration.py` (13), `tests/test_aiia_application_link.py` (5), `tests/ui/test_ai_governance_pages.py` (18), two real-PG tests |
| G3 Guided assessment and evidence | built, verified (SQLite, real PostgreSQL, browser) | `tests/test_ai_governance_checklist_rules.py` (16), `_guidance.py` (22), `_guidance_routes.py` (14), `tests/ui/test_ai_governance_guidance_ui.py` (6), one real-PG test |
| G3b The AIIA moves into AI Governance | built, verified (SQLite, real PostgreSQL, browser); plan [06](06-aiia-in-ai-governance.md) | `tests/test_ai_governance_assessments.py` (38), `_assessments_routes.py` (19), `tests/ui/test_ai_governance_assessments_ui.py` (14), one real-PG test; the seven classification and dimension tests of the old `tests/test_aiia.py` moved with the same assertions |
| Rollout switch and separation setting | built, verified (SQLite, browser through the suites) | `tests/test_ai_rollout.py` (5), `tests/test_ai_policy_admin.py` (30, the switch and separation cases among them) |
| G4 Decisions and action lifecycle | built, verified (SQLite, real PostgreSQL, browser); plan [07](07-g4-decision-lifecycle-build.md) | `tests/test_ai_governance_decisions_rules.py` (12), `_decisions.py` (24), `_decisions_routes.py` (16), `_decisions_integration.py` (10), `tests/ui/test_ai_governance_decisions_ui.py` (8), one real-PG test (two askers, two deciders) |
| G5 Monitoring, evaluation records, regulatory impact, Explain | built and verified (focused SQLite, real PostgreSQL, browser); plan [08](08-g5-build-plan.md) | 72 focused backend checks, 9 browser checks, 1 real PostgreSQL case, 63 AI call guard checks; capability inventory regenerated |
| G6a Review packs | built and verified in focused SQLite, HTTP, browser and PostgreSQL lanes; plan [09](09-g6-build-plan.md) | 57 rules and service checks, 3 HTTP checks, 1 browser journey with accessibility scans, 1 real PostgreSQL case; capability inventory regenerated |
| G6b AI literacy | built and milestone verification passed (plan 09 section 5.2) | 8 shared G6b/G6c service and HTTP cases, 2 browser journeys and 1 real PostgreSQL case; full milestone lanes above |
| G6c Platform AI features | built and milestone verification passed (plan 09 section 5.3) | Same focused set and full milestone lanes; the production read-only query found no old tenant copies |
| G6 shadow AI discovery, component lineage, public trust | **not built, by design**: no authorized feed, no evidence of need, separate approval (plan 09 section 1) | |
| G7 Conditional EU content | content-neutral human oversight foundation built, verified in focused and PostgreSQL lanes and merged to `master` (PR #6); EU rule pack still blocked on recorded legal approval (see Handoff) | `tests/test_ai_governance_oversight.py`, `_oversight_routes.py`, `tests/ui/test_ai_governance_oversight_ui.py`, one real PostgreSQL case for tenant unit scope; no rule text or deadline enabled. The pilot runbook in `PLAN_G7_OVERSIGHT.md` has not been run |
| CISO assurance briefs 01 to 06 | not started (see Handoff for a feasibility read of each) | |

## Change log

### 2026-10-14, ledger reconciliation and the specialist rework programme

- Fast-forwarded the local branch from `4384c79` to `origin/master` (`f770d33`); nothing was committed, pushed or deployed
  by this step. Corrected the labels that had gone stale: decision rows 13 and 14 (built, not "written" or "designed only"),
  the G7 slice row, the G7 worktree note, and the migration inventory (G7 tables). The change log below had no entry for G7 or
  for the release; those follow.
- Another session wrote the specialist rework programme on 2026-10-14 (`plans/2026-10-governance-rework/`, documents 01 to
  06, planning only). It does not reset G1 to G7. Where it changes an earlier product decision it says so; the two that touch
  this ledger are the move of learner AI literacy out of the specialist navigation (history and APIs kept until a consumer
  review) and the Google or Microsoft Forms export as the first external request path. Its implementation record is
  `plans/2026-10-governance-rework/07-implementation-ledger.md`.
- Not verified here: production row counts for the G7 tables, any live use of the oversight arrangements, and the G7 pilot
  runbook. The last browser lane result of the G7 branch was not recorded when its pull request opened.

### 2026-10-13, release: startup repair and navigation

- The production restart at `dfaa357` failed while seeding users. Startup counted `public.users` before any request had an
  RLS scope, saw zero rows, and tried to insert the bootstrap users, which PostgreSQL rejected under the users policy. The
  previous commit was healthy after rollback. By the branch history this was the first start from `master` of code that includes
  the connection layer of `9ead959` (it reached `master` with PR #6); whether the previous code had the same blind spot was not
  established.
- PR #8 (`fe1b12f`): startup's global user count and default organization bootstrap, and `seeds/seed.py`, use
  `get_db_bypass_rls()`; request connections stay scoped. The diff touches those three call sites only.
- PR #9 (`f855c9d`): a super administrator sees AI Governance in the module navigation while an organization's rollout switch
  is off (`can_ai_admin_nav`). Capability and unit scope are unchanged.
- The owner's VPS output reported `f770d33` healthy on 2026-10-14. A health response is not evidence that tenant data or
  authorization are right; no tenant journey was recorded.

### 2026-10-13, G7 human oversight foundation

- `modules/ai_governance/oversight.py` and four routes under `/ai-governance/api/systems/{id}/oversight`. Two content-neutral
  tracks per use, `design` and `operation`. Each names a responsible person and records how people observe, intervene, stop
  and escalate. A save appends an immutable content version bound to the profile version it was written against; a second
  person may mark that version reviewed, never its author; a stale browser revision is refused. A later profile edit makes
  both tracks read as changed and asks for a new reviewed version; earlier versions stay visible to scoped viewers.
- The person picker offers only people who can open that use. A hidden use answers like a missing one. Status appears in the
  workspace, Monitoring, a live link in Decisions that does not alter a signed brief or its digest, and My Work.
- The workspace says that recording an arrangement is not a legal conformity decision. EU rule text, effective dates,
  classifications and obligations stay disabled until a legal or content owner records an approved rule version.
- Verified: focused service, HTTP, browser and disposable PostgreSQL cases, a PostgreSQL case for a provisioned tenant's
  business unit scope, and the full disposable PostgreSQL lane. The local full backend run had two ARIA policy failures outside
  G7 that passed on focused rerun. The CI Linux backend coverage job reached 80 percent and then its 20 minute limit, so the
  limit was raised to 40 minutes.

### 2026-10-12, G5 monitoring and evaluation records

Applied the G5 schema, events, service wiring, routes, monitoring and regulatory screens, evaluation form, Explain panel,
decision reopening, quality signals and My Work links. Recorded evaluations are supplied by a person; the app does not run
them. Regulatory changes still enter through the manual inbox. Explain falls back to cited rule facts when AI is disabled or
its answer cannot be used. The workspace hides review controls until the permission response arrives.

The focused G5 backend set passed 72 checks. The browser G5 file passed 9 checks, the AI call guard passed 63, and six
adjacent workspace and My Work checks passed. The new
G5 case passed on the guarded `themisiq_test_aigov` PostgreSQL container. The capability inventory now lists 1000 routes.
The first PostgreSQL run found that the new `ai_regulatory_impacts` foreign key preceded `regulatory_updates`; the DDL order
was corrected in both shared and tenant blocks, then the PostgreSQL case passed. The broad suites were deferred until the
larger programme stage as requested. This work is uncommitted and has not been deployed.

### 2026-10-12, G6a AI review packs

Applied the G6 core patch once. It added the pack tables, events, capabilities and notification handler; it also added dormant
schema and capabilities for G6b and G6c. Wired the pack routes, recipient and manager pages, sidebar, workspace link, and a
client script that builds server content as text nodes. The manager chooses a named recipient, expiry, whether to include names
or notes, and whether JSON download is allowed. Issuing requires a fresh preview token bound to both the manifest and every
sharing choice. The recipient sees a frozen account and can no longer open it after expiry, revocation or loss of the issuer's
sharing right. Every open, download and refusal is logged. Manager history and change summaries remain scoped to the AI use.

The focused rules and service files passed 57 checks, HTTP passed 3, and the browser journey passed 1 with accessibility scans
on the manager and recipient screens. The guarded PostgreSQL test passed issue, open, revoke and loss of issuer authority in a
tenant schema. The first HTTP run found a template collision with the dictionary method `items`; that was fixed before the
passing run. The first PostgreSQL run exposed an unrealistic test persona whose session held a tenant-only unit not persisted
on the shared user row. The test now uses an organization-wide use and verifies the reloaded issuer has scope. The capability
inventory matches the registered routes at 1012. The broad suites remain deferred; no production deployment is claimed.
The recipient list now checks each issuer and AI use pair, so a scope change on one use cannot expose its pack through another.
It also omits a pack whose frozen manifest no longer matches its hash. The preview screen shows each manifest item and line in
collapsible sections before the person can issue the pack. The browser journey includes a phone-width overflow check.

### 2026-10-11, G1a to G2

**Defects found by the new tests and fixed here (each was live before this work).**

1. *Related Items and the Vault disagreed about who may see a record.* A compliance manager could resolve a data subject
   request's name through an Evidence Vault link that the Privacy module itself would not show them. The Vault now uses the
   single registry rule. A UI test that depended on the looser rule was corrected.
2. *PostgreSQL had no unique index on `cross_module_links`.* The index that makes `ON CONFLICT DO NOTHING` and "link again" safe
   was created only by the SQLite runner, so production stored an edge as many times as it was linked. Found by the first real
   PostgreSQL test of the relationship service. Fixed by `_ensure_pg_link_dedup_index` (see the migration note above).
3. *The `audit_log` row level security policy did not restrict reads.* Its write policy was `FOR ALL USING (true)`, and permissive
   policies combine with OR, so any role subject to the policy could read every organization's audit entries. Reads are now
   scoped by organization and only INSERT is open (so system events with no organization still log). Test: a role that is
   not a superuser, both halves.
4. *Sentinel AIIA update and delete ignored the business unit.* An officer in one unit could change or delete another unit's
   assessment by id, and `application_id` could be set to any number. Both routes now answer 404 outside the caller's scope and
   validate the application and the unit.
5. *Governance applications, data assets and business processes were listed in full for every role and changed or deleted by id
   from any unit.* Reads are scoped, writes answer 404 outside scope, a record cannot be filed in a unit the caller does not
   belong to, and an edit that does not mention the active flag no longer reactivates a retired application.
6. *An application referenced by an AI profile, an assessment, a request or a link could be hard deleted.* It is now refused with
   "retire it instead".

**Found and not fixed here (spawned as separate tasks, running in their own sessions).**

- `canonical_vendors` has no unique name index on PostgreSQL, the same class as defect 2, and its duplicates cannot simply be
  deleted because three vendor tables reference it.
- The other Sentinel write routes (breaches, RoPA, DPIAs, vendors and the sub-resources that act on a record by id) check the
  business unit on read but not on write.

**Slice evidence and what stands in for what could not be done.**

- G1a. `modules/governance/entity_scope.py` is the one registry (36 kinds: table, title column, deep link, capability, unit
  rule). `modules/governance/relationships.py` is the one service: an edge is stored once with an active verb, both ends must be
  records the viewer may open, an unknown and a hidden record answer alike, typed verbs join only the pairs `PAIR_RULES`
  allows, an application edge needs `ai_use.link` or ownership, a candidate stays out of every list until confirmed, and the
  service never commits. Related Items, the Vault and `core/links.py` read from it.
- G1b. `emit` still delivers inline; `enqueue(db, ...)` writes the event on the caller's connection so it commits with the
  change; each handler's outcome is its own delivery row, so a retry runs only the handlers that have not succeeded; failures
  back off 1, 5, 15, 60 and 360 minutes and are then dead (`/super-admin/api/events/dead` and `/retry`); a one minute sweeper
  leases an event before delivering it, runs it inside its own tenant, and never touches rows written before this design (they
  have no scheduled attempt). A concurrency test runs two reviewers against one request on real PostgreSQL.
- G1c. Every provider call passes `core/ai_client.py` `_guarded`: policy is read for the current organization, a refusal
  happens before the provider is contacted and is recorded, a policy that cannot be read refuses (fail closed), the usage row
  holds metadata only, and `tests/test_ai_call_guard.py` reads the source so a new call site needs a registered feature and a
  second path to a provider cannot appear. 56 call sites were migrated onto 52 registered features. The admin page is
  `/admin/ai-policy`.
- G2. Staff describe a use in a request that writes nothing in `applications`; a reviewer links it to one application or
  creates one; promoting twice, or two reviewers at once, makes one application; a stale answer is refused; the author and
  in-scope reviewers see a request and nobody else does. The inventory is the applications that have a profile, scoped, filtered
  and paged on the server; the workspace loads each tab on its own and says "no access", "unavailable" or "empty" separately.

**Decisions made while building (the plans left them open).**

- The provisional tier is called Needs review, Lower, Moderate or Elevated, never "high risk", and the screen says it is an
  internal aid that approves nothing. A use is "Lower" only when every screening answer is given.
- A reviewer may accept their own request (the inventory entry is not the approval); the audit says so. Separation of duties
  belongs to the decision in G4.
- The AI policy default is compatibility mode (no policy row means today's behavior); moving the platform default to "deny until
  a policy exists" is a release decision.
- Categories an AI feature sends are declared per feature in `core/ai_policy.FEATURES`, not inferred from prompt text.

**Open limitations (stated so no one assumes otherwise).**

- No prompt redaction or minimization is done; only what a feature declares is checked. Cost is not computed, only tokens.
- The platform help assistant keeps a response cache shared by every organization (it sends no organization data, but it is a
  shared cache).
- An AI button is not hidden when the policy forbids it; the person sees the refusal sentence, and the capability state API
  reports `disabled_by_policy`.
- Other code still reads `applications` directly without the viewer's scope (ERM, BCM and reporting queries): listed for the
  scope matrix work, not changed here.
- The reviewer queue for linking old AIIA rows to applications by a suggested name match is not built; linking is manual from
  the AIIA screen.
- Staff, DPO and auditor observation, baseline task times, a read of the production schema and row counts, and the pilot
  outcome metrics cannot be done from a laptop and are not claimed.

### 2026-10-12, linked-record read access follow-up

- Assessment details and lists no longer expose raw application, RoPA or DPIA IDs when the viewer cannot open the
  linked record. The editor omits restricted references on save so an unrelated edit preserves those links.
- A decision manifest now reduces each restricted checklist record, assessment, AI control and proof item to a
  restricted marker. Visible controls omit frozen canonical mapping IDs and proof counts that belonged to the
  original decider's scope. Change summaries are computed from the current viewer's redacted manifests.
- The decision screen renders restricted entries without references, status, classification or proof details.
- No tests were added or run in this follow-up, per the staged verification instruction.

### 2026-10-12, focused access verification

- Focused backend cases passed for redacted assessment IDs, preserving hidden links on an unrelated edit, and
  decision manifest redaction. The related Sentinel creator-unit, import and ERM event checks also passed. The full
  suite remains deferred.
- A browser case found that the assessment's restricted Choose and Clear buttons remained visible because the shared
  button display style overrode `hidden`. The AI Governance action style now honors `hidden`; the restricted-link
  browser edit and the decision review flow both passed after the change.
- The local SQLite file has an old, empty schema. Production historical rows and cross-unit RoPA/DPIA links remain
  unverified. The count-only PostgreSQL audit script is prepared in `scripts/audit_sentinel_unit_access.py` for an
  operator to run after release; its pure link-classification case passed. No historical data was changed.

### 2026-10-11, G2 milestone run and the AIIA move

- **G2 milestone, full backend suite** (SQLite, `tests/ui` excluded): 1678 passed, 58 skipped, exit 0. The skips are the tests
  that need a real PostgreSQL URL or a browser; those lanes run separately and are recorded under each slice.
- **Owner instruction:** "lets move AIIA to the AI governance module too. Add that to the plan". Planned as slice G3b in
  [06](06-aiia-in-ai-governance.md) and folded into the README, domain contract, journey 3 and delivery slices as an
  amendment. Two items the earlier plan carried are replaced by it: the Sentinel deep link for "start an assessment from this
  system" and the separate reviewer queue for unlinked assessments (now a list filter with an inline link action).
- Nothing in G3b is built yet. The decisions it adopts by default are listed in the table above (number 9) and in 06 section 4.
