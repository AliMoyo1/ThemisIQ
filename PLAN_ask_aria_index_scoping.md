# PLAN: Ask ARIA search index tenant scoping

Status: DONE, READY FOR REVIEW (nothing committed, nothing pushed, nothing deployed)

## Goal

Find out whether the shared Ask ARIA search index (`aria_ask_index`) can carry
one organization's text into another organization's prompt, prove it with a
test, and close it by making the index itself carry tenancy (org and business
unit) and filtering in SQL before ranking and the top-k cut.

## Files to touch

- `oneforall/modules/aria/ask_service.py` (DDL, migration, indexers, search, ask)
- `oneforall/tests/test_aria_ask_scoping.py` (new regression tests, SQLite)
- this plan file

Nothing else. No commit, no push, no deploy.

## Recon (read-only, facts established from the code)

- Indexed content types, all via `rebuild_all()`:
  - `document` from `aria_documents` (has `org_id`, `business_unit_id`)
  - `control` from `controls` JOIN `frameworks` (neither has org or BU columns)
  - `risk` from `aria_risks` (no org or BU column)
  - ERM tables (`risk_register`, `erm_enterprise_risks`) are NOT indexed.
- The index DDL has no org or BU column on either engine.
- `search()` ranks the whole index and cuts to top k before
  `_filter_chunks_by_scope`, which only checks `document` chunks.
- PostgreSQL tenancy is schema per tenant (`SET search_path TO tenant_x, public`);
  RLS covers only a handful of public tables, not ARIA tables.
- `aria_ask_index` is created lazily by `init_index()` in whichever schema is
  first on the search_path, and once at startup in `public`.

## Approach

1. Capture baseline evidence against the UNMODIFIED code (scratch script).
2. Add `org_id` + `business_unit_id` to both index DDLs; migrate old indexes.
3. Stamp: documents copy org/BU from the source row; controls and risks have
   no source attribution, so they are stamped with the tenant bound at index time.
4. Filter in SQL (`WHERE ... AND scope`) inside `base_sql`, so both the framework
   filter and its unfiltered fallback carry it, before ORDER BY and LIMIT.
5. Keep `_filter_chunks_by_scope` as defense in depth (live row check).
6. Regression tests (SQLite) that also assert positive recall, so a swallowed
   SQL error cannot make an isolation assertion pass vacuously.

## Baseline evidence (unmodified code, SQLite, scratch script, stubbed model)

- Risks: one `aria_risks` row per org, both indexed. Org A's user asks about
  ransomware: retrieved 2 chunks, the prompt sent to the model contains org B's
  risk text, and a model that cites what it saw cites `RISK-B1`. `aria_risks`
  has no owner column, so the index has nothing to filter on.
- Documents: org B has 10 near-duplicate hits, org A has 1. Raw `search()` top 8
  are all org B. Org A's user gets 0 chunks and the model is never called
  (recall loss). No org B text reached the prompt (post-filter works).
- Index columns on the unmodified table: content_type, content_id, title,
  section, body, owner, framework, control_ref, url_path (no org, no BU).
- Baseline of existing suites before any edit:
  `tests/test_aria_policy_legacy.py` + `tests/test_aria_policy_publication.py`
  all pass (64 tests, 1m24s).

## Change log

- [done] ask_service.py: module docstring gains a Tenancy section.
- [done] ask_service.py: `_FTS_DDL_SQLITE` adds `org_id UNINDEXED`, `business_unit_id UNINDEXED`;
  `_FTS_DDL_PG` adds `org_id INTEGER`, `business_unit_id INTEGER`.
- [done] ask_service.py: `init_index()` now probes the catalog (`_index_columns`) and
  upgrades a pre-scoping index: SQLite drops and recreates (FTS5 cannot be altered;
  repopulated by Rebuild index), PostgreSQL `ADD COLUMN IF NOT EXISTS` x2 plus a
  one-statement backfill of document rows from `aria_documents`. Cheap enough to call
  before every question and write.
- [done] ask_service.py: `_clear_by()` calls `init_index()` first, so every write path
  (reindex_*, remove_from_index) targets the CURRENT tenant schema's table instead of
  falling through the PostgreSQL search_path to the shared public one.
- [done] ask_service.py: `reindex_document` stamps org_id and business_unit_id from the
  source row (NULL stays NULL, matching `document_read_ok` legacy visibility);
  `reindex_control` and `reindex_risk` stamp `get_current_org()`.
- [done] ask_service.py: new `_scope_sql(user)`; `search(..., user=)` returns [] for no
  user; `_search_sqlite` and `_search_pg` put the scope in `base_sql`, so the framework
  filter and its unfiltered fallback are both scoped, before ORDER BY and LIMIT.
- [done] ask_service.py: `_search_pg` returns [] if the framework-filtered query raises,
  instead of running the fallback on a connection whose uncommitted tenant SETs were
  just rolled back.
- [done] ask_service.py: `_filter_chunks_by_scope` kept unchanged (docstring updated);
  `ask()` passes `user=user` to `search()`.
- [done] tests/test_aria_ask_scoping.py (new, 16 tests, SQLite, model stubbed):
  other org's risk/control text absent from prompt, answer and citations (both
  directions); other org's documents cannot crowd out the asker's own (with an
  explicit precondition that an unscoped top 8 really excludes them); framework
  fallback stays scoped; SQL scope equals `document_read_ok` for five personas
  incl. BU subtree, super admin, no BU, no org; live-row post-filter still drops a
  moved and a deleted document; no actor gets nothing and the model is not called;
  stamping by source row / bound tenant; `rebuild_all` under a tenant; legacy FTS5
  upgrade + `rebuild_index`; both DDLs declare the columns; PG query assembly via a
  recording stub (placeholders match params, scope before ORDER BY, no retry after
  a failure).
- [done] Mutation check: the new tests run against the ORIGINAL ask_service.py
  (from `git show HEAD:`): all 16 fail. Fixed file restored afterwards and re-run:
  16 pass.

## Verification

- `tests/test_aria_ask_scoping.py`: 16 passed (about 26 s).
- Before the change: `tests/test_aria_policy_legacy.py` + `tests/test_aria_policy_publication.py`
  64 passed.
- Full non-UI suite after the change (`pytest tests --ignore=tests/ui`, repo .venv python):
  908 passed, 15 skipped, 0 failed, 0 errors (923 total, includes the 16 new tests). All 15
  skips are `tests/test_postgres_init.py` (no `TEST_DATABASE_URL`).
- Real app boot (startup calls `init_index()`): `tests/ui/test_harness_smoke.py` 1 passed;
  `tests/ui/test_chip_filters_are_buttons.py` (renders the Ask ARIA page) 6 passed, 1 skipped
  (its own fixture has no document rows; unrelated to this change).
- NOT verified: anything PostgreSQL (no server, no Docker daemon, no pg binaries on
  this machine). PG DDL, the PG upgrade statements (ALTER ... IF NOT EXISTS plus the
  backfill UPDATE) and tenant-schema behaviour were reviewed by reading only. CI's
  `postgres-schema.yml` lane runs only `test_postgres_init.py`, which does not touch
  `aria_ask_index`.
- Rebuild cost: SQLite `rebuild_all()` about 10 percent slower (one catalog read per
  indexed item from `_clear_by -> init_index`), rare admin action.

## Findings

1. Indexed content: `document` (aria_documents), `control` (controls JOIN frameworks),
   `risk` (aria_risks). Nothing from `risk_register` or `erm_enterprise_risks`.
   `rebuild_all()` reads every row visible to its connection, with no filter.
2. Only `aria_documents` has `org_id` and `business_unit_id`. `aria_risks`, `controls`,
   `frameworks` have neither; `risk_register` and `erm_enterprise_risks` have no `org_id`
   either (the platform's own comment says "per-tenant-schema isolation"). The ARIA risk
   register page (`routes.py` risks_page) lists every `aria_risks` row with no org filter.
3. Verified on SQLite: with two orgs in one database, org A's user received org B's risk
   text in the retrieved chunks, in the prompt sent to the model, and in the citations of a
   model that cites what it was shown. Cause: nothing in the index or source row says who
   owns a risk or control chunk, and `_filter_chunks_by_scope` only looks at documents.
4. Verified on SQLite: org B's 10 relevant documents filled the top 8, so org A's user got
   0 chunks and the model was never called (recall loss). No org B document text leaked
   (the post-filter works for documents).
5. PostgreSQL, from reading the code (not reproduced, no server here): tenants are schemas,
   and `aria_ask_index` is not in the tenant DDL. It is created by `init_index()` in the
   first schema on the search_path, plus once at startup in `public`. A tenant with no
   table of its own resolves the unqualified name to `public.aria_ask_index`.
   - Write path: the publication scheduler runs `reindex_document` inside
     `tenant_context(...)` without `init_index()`, so a tenant's first published policy
     could be written into (and its `_clear_by` delete from) the shared public table.
     Document ids are per-schema sequences (`DOC-0001`...), so a colliding id in
     `public.aria_documents` would make the document post-filter pass the foreign chunk
     for a default-org user.
   - `_search_pg` ran its unfiltered fallback after the filtered query failed, on a
     connection whose uncommitted SET search_path / SET app.current_org_id the wrapper's
     rollback had just undone (reads `public`).
   - Ask page header count (`routes.py`, `SELECT COUNT(*) FROM aria_ask_index`) is not
     scoped, so a tenant without its own table sees the public chunk count (a number only).
6. Search errors are swallowed into an empty result. `_search_sqlite`: three
   `except OperationalError: rows = []`, no log. `_search_pg`: three `except Exception`
   with a WARNING log. `ask()` then answers "I couldn't find anything...", `covered=False`,
   `success=True`, logs it to `aria_ask_log` as an uncovered question. An outage, lock
   timeout, or a bug in a new predicate looks like "no policy covers this" and skews the
   coverage percentage. Reported only; behaviour unchanged except the PG retry above.

## Residual limits and decisions

- Controls and risks have no source owner. They are stamped with the tenant bound when
  indexed, which is exactly right on PostgreSQL (schema = tenant). In ONE shared SQLite
  database hosting several orgs, whoever runs Rebuild index owns every control and risk
  chunk (the other org gets none until it rebuilds). Proper fix: add `org_id` (and BU) to
  `aria_risks` and `controls`, scope the risk and framework pages, backfill.
- Control and risk chunks only enter the index through the admin Rebuild index button
  (nothing calls `reindex_risk` / `reindex_control` on create or update).
- SQLite upgrade drops the old FTS5 index (cannot be altered); it is empty until Rebuild
  index, same as a fresh install. PostgreSQL keeps its rows.

## Deploy notes (when approved)

- After deploy, run Rebuild index once per tenant schema and once for the default org:
  stamps control and risk chunks, and clears any chunk that an earlier publication wrote
  into the shared public table. The upgrade backfill stamps document rows from
  `aria_documents` by `doc_id`, which could mis-stamp such a stray row until that rebuild.
- Before release, exercise `init_index()` against a real PostgreSQL 18 (Docker): a tenant
  schema holding a pre-scoping `aria_ask_index`, and a tenant schema holding none while
  `public` has one. The new tests are SQLite only and CI's PG lane
  (`test_postgres_init.py`) does not touch this table.
  (Superseded by the follow-up round below: this was then run on real PostgreSQL 18.)

## Follow-up round ("go with your recommendations")

Done and verified
- Real PostgreSQL 18 (own throwaway container on port 55433, removed afterwards): 4 tests
  appended to `tests/test_postgres_init.py` (tenant write stays in its own schema; in-place
  upgrade of a pre-scoping table; scoped search before top-k incl. framework fallback; rebuild
  stamps). Whole PG lane: 19 passed (15 existing + 4 new). Against the ORIGINAL ask_service.py
  all 4 fail, and the first REPRODUCES the cross-tenant leak: the default org's prompt held the
  tenant's text and the default org's own chunk had been wiped by the tenant's reindex
  (search_path fall-through to public.aria_ask_index, colliding DOC-0001).
- Swallowed search errors fixed: `_search_sqlite` and `_search_pg` no longer catch, `search()`
  raises, `ask()` returns success False with "Search is temporarily unavailable..." and writes
  no `aria_ask_log` row. Unused `OperationalError` import removed. 2 new SQLite tests, PG
  assembly test updated. 87 passed across the new file plus legacy, publication, reliability.
- `scripts/rebuild_ask_index.py` (new): loops active orgs, `tenant_context`, `rebuild_all()`.
  Smoke run against the throwaway PostgreSQL: "askrebuild: 2 chunks", exit 0.

NOT done or not verified
- No unit tests for the rebuild script; no bullet yet in docs/aria-policy-authoring.md section 7.
- Full non-UI suite and UI smoke NOT re-run since the error-handling change (last full run was
  908 passed, 15 skipped, before it).
- Left out on purpose: org_id on aria_risks/controls (redundant on PostgreSQL schema-per-tenant,
  wide blast radius), incremental indexing of risks/controls, scoping the Ask page count.

New finding, NOT fixed (database.py, belongs with the running chip session)
- `provision_tenant_schema` and `_migrate_all_tenant_schemas` return their pooled connection with
  `pool.putconn(pg_conn)` after committing `SET search_path TO tenant_x` and the RLS bypass
  GUCs, without the reset `_PgConnWrapper.close()` does. Probe on real PG: the first no-context
  `get_db()` after `init_db()` or after provisioning had search_path `tenant_<last>, public` and
  `app.bypass_rls = 'true'`; the next call was clean. So startup's `init_index()` can land in the
  last tenant's schema. Likely fix: `wrapper.close()` instead of `putconn`. Probe script was
  `pg_dirty_pool_probe.py` in the session scratchpad.
