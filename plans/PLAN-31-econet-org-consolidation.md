# PLAN-31: Consolidate Ecocash / Econet Wireless / Omni into one "Econet Group" org

## Status: PHASE 2 COMPLETE (committed on production 2026-07-23). Scope:
## "users + structure only" (no domain-data copy). Verified at the DB level:
## Econet Group (org 1) active with 12 users; Omni/Ecocash/Econet Wireless
## (orgs 4/5/6) inactive with 0 users, schemas + data preserved; BUs Omni
## (id=6), Ecocash (id=7), Econet Wireless (id=8) created under Econet (id=2).
## Superuser backup pre_consolidation_5434.dump held in /project/backups/.
## The deferred follow-ups below remain open (stale tenant schemas, optional
## Omni data copy, abandoned Docker container cleanup).

## CRITICAL ENVIRONMENT FINDING (2026-07-23) -- read before touching anything

The VPS runs MULTIPLE PostgreSQL instances, and the production one is NOT
the obvious default:

- **System PostgreSQL 18 on port 5434** (socket `/var/run/postgresql/.s.PGSQL.5434`,
  pidfile `18-main.pid`) is the **REAL production database.** Proven live:
  `pg_stat_activity` on this instance showed 4 idle `themisiq` connections
  from `::1` (the running app's uvicorn workers), and it holds the full 12
  users / 4 orgs that match the UI. `sudo -u postgres psql -d themisiq`
  reaches it (postgres superuser, bypasses RLS).
- **Docker `project-db-1` (postgres:16-alpine) on 127.0.0.1:5432** is a
  LEFTOVER from the original docker-compose deployment. The app is not using
  it. It doesn't even have a `postgres` superuser role. Do not touch it.
- **Docker `project-shadow-db-1` on 127.0.0.1:5433** -- shadow/staging copy,
  also not the live DB.
- Unrelated `odin-*` containers belong to a different project entirely.
- A `project-app-1` Docker container is crash-looping ("Restarting" every
  ~17s) -- a stale duplicate of the app; the real app runs via the
  `themisiq-app.service` systemd unit, not this container. Worth cleaning up
  separately, unrelated to this migration.

**Consequence for backups:** any `pg_dump -h localhost` (TCP, default port
5432) hits the abandoned Docker DB, NOT production. The FIRST backup taken
this session was exactly that mistake and is INVALID. Every backup and every
recon/migration query for this plan MUST target the system PG on 5434,
via `sudo -u postgres` (superuser, socket, port 5434). RLS on this database
silently returns 0 rows to the app's own `themisiq` role for org-scoped
tables when no `app.current_org_id` GUC is set, so only a superuser
connection sees the true, complete data.

**Tenant model correction:** despite the `tenant_public` naming assumed
below, the first recon pass showed only a single `public` schema and every
domain table carrying data there -- i.e. isolation on this database is by
`org_id` column + row-level security, NOT schema-per-tenant. This SIMPLIFIES
the migration substantially (no cross-schema row copying / PK-remapping):
consolidation is likely mostly `UPDATE ... SET org_id = <econet>,
business_unit_id = <sbu>` plus dropping the emptied org rows. The full
superuser recon (pending) confirms the exact shape before Phase 2 is
written. The "Why this isn't a simple UPDATE" section below was written
under the schema-per-tenant assumption and is superseded by this finding
for the column+RLS case -- kept for history, to be rewritten in the Phase 2
update.

## User-confirmed decisions (2026-07-23)

1. **Target org**: reuse the existing "Default" organization (`tenant_public`
   schema). Rename it to "Econet Group". Its existing users (admin, bcm,
   compliance, dpo) are untouched and keep working throughout.
2. **Source orgs**: Ecocash (`tenant_ecocash`), Econet Wireless
   (`tenant_econet_wireless`), Omni (`tenant_omni`). Each becomes a business
   unit inside Econet Group; all of their users and domain data (risks,
   evidence, controls, etc.) move into Econet Group's schema, tagged with
   the matching new business unit.
3. **After verification**: delete the three source organizations and their
   schemas. No "keep as deactivated fallback" — clean end state.
4. **Backup**: no existing recent backup confirmed. A full `pg_dump` is a
   mandatory first step, taken immediately before Phase 1's read-only recon
   (so the backup itself reflects the pre-migration state exactly) and again
   immediately before Phase 2 actually writes anything.

## Why this isn't a simple UPDATE

Two very different kinds of data are involved:

- **Shared tables** (`users`, `user_roles`, `organizations`) live in one
  place regardless of org — `users.org_id` is a plain FK. Moving a user
  between orgs is a one-column UPDATE.
- **Per-tenant-schema tables** — `business_units`, `departments`,
  `business_processes`, `applications`, `data_assets`, every ERM/ORM/ARIA/
  GRID/BCM/Sentinel domain table, `evidence_items`, `evidence_links`,
  `audit_log`, `cross_module_links`, `canonical_vendors`, `canonical_controls`,
  `task_board`, etc. — are **duplicated per org** (each org's schema has its
  own copy, created by `provision_tenant_schema()` in `database.py`). Ecocash's
  "risk #7" and Econet Wireless's "risk #7" are unrelated rows in different
  schemas that happen to share an auto-increment ID.

Consolidating means copying every per-tenant-schema row from the three
source schemas into Econet Group's (`tenant_public`) schema, which requires:
- **ID remapping**: every copied row gets a new primary key in the target
  schema (to avoid colliding with Econet Group's own existing rows, or with
  rows copied from the *other* two source schemas in the same migration).
- **Foreign key remapping**: every column that references a remapped ID
  (e.g. `risk_controls.control_id`, `evidence_links.entity_id`) has to be
  rewritten to point at the new ID, using a per-table old-id -> new-id map
  built during that table's own copy step. Tables must be copied in
  dependency order (parents before children).
- **Polymorphic reference handling**: some tables (`evidence_links`,
  `cross_module_links`, `audit_log`) reference other rows via an
  `entity_type` + `entity_id` pair rather than a real FK. Remapping these
  requires looking up the correct id-map based on `entity_type` per row, not
  a single blanket rule.
- **Business unit tagging**: after Ecocash/Econet Wireless/Omni exist as new
  business units inside Econet Group's schema, every row copied from that
  source org needs its `business_unit_id` set to the matching new BU (not
  whatever BU, if any, it pointed to inside its own now-decommissioned
  schema).

Getting any of this wrong silently corrupts real risk/evidence/audit data.
This is why the plan is phased.

## Why Phase 2 isn't written yet

A correct, safe migration script needs real facts this session doesn't have:
- Exact row counts per table per source org (a script handling "maybe a
  few dozen rows" looks very different from one handling thousands).
- Whether Ecocash/Econet Wireless/Omni already have their own internal
  `business_units` sub-structure (sub-departments etc.) below their root —
  if so, do we flatten everything under one new "Ecocash" BU, or preserve
  that structure as grandchildren? This is a real product decision that
  depends on what's actually there.
- Confirmation that production's actual per-tenant table set matches what
  `database.py` defines in code (a prior partial migration or manual hotfix
  could have left drift).

Phase 1 below answers all three, read-only. Phase 2 gets designed as a
follow-up plan update once those results are back.

## PHASE 1 RECON RESULTS (2026-07-23, superuser on 5434)

**Confirmed schema-per-tenant** (my earlier "single public schema / simple
UPDATE" note was WRONG -- it came from the stale Docker DB's RLS-filtered
view). Four schemas: `public` (Default/org 1), `tenant_omni` (org 4),
`tenant_ecocash` (org 5), `tenant_econet_wireless` (org 6).

**Users per org**: Default 4, Omni 4, Econet Wireless 3, Ecocash 1 (= 12).

**Business unit trees**:
- `public` (Default) already has TWO root BUs: id=1 "Company", id=2 "Econet"
  (the latter created by the user in the screenshot). No deeper nesting.
- `tenant_ecocash`, `tenant_econet_wireless`, `tenant_omni`: **no
  `business_units` table exists at all** -- these schemas predate the T1.1
  governance migration.

**MAJOR complication #1 -- the tenant schemas are STALE.** `public` has 173
tables; the tenant schemas have only 127-128. They are ~45 tables behind and
are missing the `business_units` table (and, needs confirming, likely the
`business_unit_id` columns and other newer columns too). Column/table
migrations (`_run_pg_alters`, new-table creation) were applied to `public`
but never retroactively to the existing tenant schemas -- a latent
platform bug independent of this consolidation. Implication for the copy:
source tables are a column-subset of their `public` targets, so an explicit
column-list INSERT (source columns only) works and target-only columns take
their defaults; but every copy must intersect columns dynamically, never
`SELECT *`.

**MAJOR complication #2 -- reference/seed data overlaps and must not be
duplicated.** Much of each tenant's row count is per-tenant COPIES of the
same seeded baseline that `public` already has its own copy of:
`frameworks` (15 everywhere), `aria_frameworks` (15), `orm_event_templates`
(35), `erm_risk_library` (25), `erm_risk_appetite` (8),
`bcm_scenario_library` (8), `sentinel_jurisdiction_config` (1), and largely
`controls` (296 in public/ecocash/omni; 23 in econet_wireless). Blindly
copying these into `public` would duplicate the seed catalogue. Worse, real
user-data rows reference these by FK (e.g. a `grid_control` -> a framework),
so when the seed row is skipped, the user-data row's FK must be REMAPPED to
public's equivalent seed row (matched by natural key: name/code), not the
source's id. Distinguishing "seeded" from "org-customized" rows within these
tables is itself non-trivial.

**Real user-data volumes (what actually needs migrating), by org**:
- **Ecocash** (1 user): essentially empty of real work -- 1 erm_enterprise_risk,
  1 aria_document, 1 evidence_item, 1 evidence_link. Everything else is seed
  data.
- **Econet Wireless** (3 users): also essentially empty -- 4 erm_chat_messages,
  12 analytics_snapshots, and seed data. No real risks/docs/evidence.
- **Omni** (4 users): the only org with substantial real data -- 73
  aria_documents, 87 evidence_items, 129 evidence_links, 74 grid_controls,
  41 grid_evidence_files, 99 task_board, 218 notifications, 194
  email_reminders, 22 ai_risk_predictions, 27 analytics_snapshots, 35
  aria_control_mappings, plus grid_audits/compliance/timeline.

**Also**: `public`/Default itself already holds a lot of data (311
ai_risk_predictions, 297 aria_control_mappings, 296 controls, etc.) --
whether that is genuine Econet-corporate data to keep at the root/Company
level or leftover test data to clear is a Phase-2 decision.

## SCOPE DECISION NEEDED before Phase 2 is written

Given Ecocash and Econet Wireless have negligible real data while Omni has
the bulk, and given the reference-data-overlap + stale-schema complications
make a full automated cross-schema row-copy genuinely risky, the user must
choose the migration scope:

- **Option A -- Full domain-data migration**: copy every real user-data row
  from all three tenant schemas into `public`, with PK/FK remap, seed-data
  dedup + natural-key FK remap, polymorphic-ref handling, and business_unit
  tagging. Highest fidelity, highest risk/effort.
- **Option B -- Users + structure only**: create the 3 SBU business units
  under "Econet" in `public`, move the 12 users (org_id + business_unit_id),
  and leave the old tenant schemas' domain data behind (kept intact in their
  schemas, or exported separately). Lowest risk. Accepts that existing
  Ecocash/EW/Omni risks/evidence/etc. do not carry over.
- **Option C -- Users + Omni's real data only**: Option B, plus migrate just
  Omni's substantial real data (skip the near-empty Ecocash/EW domain data).
  Middle ground.

Phase 2 will be written to the chosen scope. Whichever is chosen, the stale-
tenant-schema issue (complication #1) should be flagged to the user as a
separate platform bug worth its own fix, since it affects any future work
touching those existing tenants.

## Phase 0: Mandatory backup (CORRECTED to target the real DB on 5434)

The original Step 2 here used `pg_dump -h localhost` and backed up the WRONG
(abandoned Docker) database on 5432 -- see the CRITICAL ENVIRONMENT FINDING
above. The backup must run as the postgres superuser against the system PG
on 5434 (bypasses RLS, captures every org's rows). Because the postgres OS
user cannot write into the root-owned `/project/backups`, dump to `/tmp`
first, then move it as root.

Run on the VPS, one command at a time:

**Step 1** — create a backups directory if it doesn't exist:
```
mkdir -p /project/backups
```

**Step 2** — take a full custom-format superuser dump of the REAL database
(port 5434), writing to /tmp where the postgres user can write:
```
sudo -u postgres pg_dump -p 5434 -d themisiq -F c -f /tmp/pre_econet_migration_5434.dump
```

**Step 3** — confirm it was written and has a sane size (not 0 bytes):
```
ls -lh /tmp/pre_econet_migration_5434.dump
```

**Step 4** — move it into the project backups directory (as root):
```
mv /tmp/pre_econet_migration_5434.dump /project/backups/
```

The earlier, invalid 5432 backup at `/project/backups/pre_econet_migration.dump`
should be deleted to avoid confusion once Step 4 succeeds:
```
rm /project/backups/pre_econet_migration.dump
```

Do not proceed to Phase 1 until Step 3 shows a non-trivial file size.

## Phase 1: Read-only reconnaissance

`oneforall/scripts/econet_migration_recon.py` (added this commit) connects
using the app's own `DATABASE_URL` and only ever runs `SELECT`/`COUNT`
queries — it cannot modify anything. It reports:
- Every organization row (id, name, slug, status).
- Every tenant schema that exists in the database.
- User counts per organization.
- Row counts for every table in every tenant schema (skips empty tables to
  keep the report short).
- The full `business_units` tree (id, name, parent_id) in every schema, to
  reveal whether Ecocash/Econet Wireless/Omni have any internal
  sub-structure beyond their seeded root.

Run on the VPS, after pulling this commit:

**Step 4** — pull the recon script:
```
git pull
```

**Step 5** — run it:
```
python3 oneforall/scripts/econet_migration_recon.py
```

Paste the full output back. That determines exactly what Phase 2's
migration script needs to handle, and whether the business-unit structure
should be flat (3 BUs) or preserve existing sub-departments.

## Phase 2: DESIGNED -- scope "users + structure only" (user chose 2026-07-23)

After the Phase 1 recon showed Ecocash and Econet Wireless are near-empty of
real data (Omni is the only one with substance) and that the tenant schemas
are stale + reference-data overlaps make a full cross-schema copy risky for
little payoff, the user chose the **users + structure only** scope. No domain
data is copied; the source tenant schemas are left completely intact.

Implemented as `oneforall/scripts/econet_consolidation_migrate.py` (dry-run
by default, `--commit` to apply, one transaction, superuser on 5434). It:
1. Renames Default (org 1) -> "Econet Group". Slug stays `public` (it maps to
   the `public` schema; do not change it).
2. Creates business units Ecocash / Econet Wireless / Omni under the existing
   "Econet" root BU (id=2) in the `public` schema. Idempotent -- reuses them
   if already present. (Chosen default: SBUs hang off "Econet", not the
   original seeded "Company" root. "Company" is left untouched.)
3. Moves each source org's users into org 1 with the matching new
   `business_unit_id` (Omni users -> Omni BU, etc.). `users` is a single
   shared table, so this is a safe `UPDATE org_id, business_unit_id`; a
   collision guard aborts if any username/email would become non-unique.
4. Deactivates the 3 emptied source orgs (`status='inactive'`) rather than
   deleting them, so their tenant schemas + preserved domain data keep a
   valid parent org row. (The user's original "delete once verified" was for
   the full-migration scope; deactivate is the consistent choice here.)
5. Clears moved users' sessions so they re-login with fresh org context.

**Accepted tradeoffs of this scope** (the user understood these):
- Moved SBU users start fresh inside Econet Group scoped to their SBU BU;
  they do NOT see their old Omni/Ecocash/EW risks/evidence (that data stays
  in the old tenant schemas, reachable only by reactivating those orgs or a
  later targeted data-copy job).
- The old tenant schemas + their data remain on disk, untouched.

**Execution flow (nothing runs without user review):**
1. Fresh backup (Phase 0 Steps 1-4 again -- data may have changed).
2. Dry run:
   `sudo -u postgres python3 oneforall/scripts/econet_consolidation_migrate.py`
   -- prints the exact before/after and every user move, commits nothing.
3. User reviews the dry-run output.
4. Apply:
   `sudo -u postgres python3 oneforall/scripts/econet_consolidation_migrate.py --commit`
5. Verify in the app UI: Econet Group shows Ecocash/Econet Wireless/Omni as
   BUs under Econet, users land in the right units, the 3 old orgs show
   inactive.

## Deferred / separate follow-ups (not in this scope)

- **Stale tenant schemas** (complication #1): tenant_omni/ecocash/econet_wireless
  are ~45 tables behind `public` and never got the forward migrations. This
  is a latent platform bug affecting any future work on existing tenants and
  deserves its own fix (retroactively apply `_run_pg_alters` + missing
  CREATE TABLEs to every existing tenant schema, or a re-provision + data
  re-load). Out of scope for this consolidation.
- **Omni real-data migration**: if the user later wants Omni's 73 docs / 87
  evidence items / 99 tasks etc. carried into Econet Group, that is the
  Option C targeted copy job, written separately with seed-dedup + FK remap.
- **Cleanup of the abandoned Docker `project-db-1`/`project-shadow-db-1`
  containers and the crash-looping `project-app-1` container** -- unrelated
  infra hygiene, flagged during recon.

## Standing constraints for whoever executes this

- One command per step on the VPS, never chained with `&&`, never
  containing the pipe character (matches every other VPS interaction this
  session).
- No em dashes in any copy/comments.
- Nothing in Phase 2 runs without a fresh `pg_dump` immediately beforehand,
  even though Phase 0 already took one — data may have changed since.
- Do not commit or push Phase 2's migration script until the user has seen
  Phase 1's recon output and confirmed the design (flat vs. nested BUs,
  final table list) matches what they expect.
