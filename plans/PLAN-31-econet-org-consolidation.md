# PLAN-31: Consolidate Ecocash / Econet Wireless / Omni into one "Econet Group" org

## Status: PHASE 0-1 SPEC READY (backup + recon). Phase 2 (the actual data
## migration) is deliberately NOT designed yet -- see "Why Phase 2 isn't
## written yet" below. Do not run anything past Phase 1 without a follow-up
## plan update once recon results are in.

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

## Phase 0: Mandatory backup

Run on the VPS, one command at a time:

**Step 1** — create a backups directory if it doesn't exist:
```
mkdir -p /project/backups
```

**Step 2** — take a full custom-format dump (allows selective restore later,
unlike plain SQL text):
```
PGPASSWORD=$(cat /project/secrets/pg_password.txt) pg_dump -U themisiq -h localhost -d themisiq -F c -f /project/backups/pre_econet_migration.dump
```

**Step 3** — confirm it was written and has a sane size (not 0 bytes):
```
ls -lh /project/backups/pre_econet_migration.dump
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

## Phase 2: The actual migration (NOT YET DESIGNED)

To be written as a follow-up update to this plan once Phase 1's results are
in. Expected shape based on the design discussion above:
1. Rename Default -> "Econet Group" (`organizations.name`, and update
   `slug` if it's user-facing anywhere).
2. Create 3 business units in `tenant_public.business_units`: Ecocash,
   Econet Wireless, Omni (parent_id = the existing root, or a new "Econet"
   node if the user wants an extra level — the screenshot shows they'd
   already started creating one).
3. For each source schema, in dependency order per table: copy rows into
   `tenant_public`, building an id-remap dict, rewriting FK columns using
   the appropriate table's remap dict, handling polymorphic
   `entity_type`/`entity_id` pairs explicitly, and setting
   `business_unit_id` to the new matching BU.
4. Update `users.org_id` and `users.business_unit_id` for every migrated
   user.
5. Verification pass: row counts before/after per table (should match
   exactly, modulo any legitimate dedup), spot-check a handful of real
   rows' FK chains survived intact.
6. Only after the user confirms verification looks right: drop the three
   source schemas and delete their `organizations` rows.

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
