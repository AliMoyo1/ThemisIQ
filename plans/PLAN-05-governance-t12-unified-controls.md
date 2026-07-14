# PLAN-05: Governance Graph T1.2 — canonical controls, risk_controls bridge, BU scoping

## Goal

Tier 1.2 of the approved Governance Graph roadmap (see
`~/.claude/plans/graceful-shimmying-oasis.md`, section "T1.2"). Today
control effectiveness lives in four disconnected places (ARIA statuses,
GRID operating_effectiveness, ORM RCSA design/operating fields, ERM's
narrative-only `effectiveness_rating`), and no table links risks to the
controls that mitigate them. This slice creates:

1. A **`canonical_controls`** registry (same pattern as
   `canonical_vendors`) that ARIA/GRID/ORM control rows point at.
2. A **`risk_controls`** many-to-many bridge between enterprise risks and
   canonical controls (the graph edge every later tier needs — the
   effectiveness engine T1.3 and residual engine T1.4 both read it).
3. **BU scoping groundwork** deferred from T1.1: `users.business_unit_id`
   plus BU filters on the governance lists.
4. Minimal UI: a "Linked Controls" section in the ERM risk drawer with
   link/unlink.

Explicitly OUT of scope (later slices): the weighted effectiveness engine
(T1.3), automatic residual recalculation (T1.4), free-text department →
FK migrations.

## Exact files to touch

1. `oneforall/database.py` — 2 new tables, 4 column migrations, 1 backfill
2. `oneforall/modules/governance/data_service.py` — canonical controls CRUD
3. `oneforall/modules/governance/routes.py` — canonical controls endpoints
4. `oneforall/modules/erm/data_service.py` — risk↔control link functions
5. `oneforall/modules/erm/routes.py` — 3 link endpoints
6. `oneforall/modules/erm/templates/index.html` — drawer section
7. `oneforall/core/rbac.py` — no new capability needed (reuse
   `governance.entities.manage` for canonical control writes and
   `erm.risk.manage` for linking)
8. `oneforall/tests/test_governance_controls.py` — new tests

## Step-by-step order

### Phase 0 — Fix a latent table-ordering hazard FIRST (small, standalone)

T1.1 added `applications.vendor_id INTEGER REFERENCES canonical_vendors(id)`
inside `_SHARED_TABLES` and `_PLATFORM_TABLES`, but `canonical_vendors` is
created later, inside `_GRID_TABLES`. On an EXISTING database this is
harmless (`CREATE TABLE IF NOT EXISTS` no-ops), but on a FRESH PostgreSQL
database — i.e. provisioning a brand-new tenant org — PostgreSQL rejects a
REFERENCES clause pointing at a table that does not exist yet, and
provisioning fails.

Fix: in `oneforall/database.py`, find both occurrences of

```
    vendor_id           INTEGER REFERENCES canonical_vendors(id) ON DELETE SET NULL,
```

(one in `_SHARED_TABLES`, one in `_PLATFORM_TABLES`, both inside the
`applications` CREATE) and change both to:

```
    vendor_id           INTEGER,
```

Bare-integer cross-block references are the existing precedent
(`cross_module_links` uses no FKs). Commit this as its own commit before
the rest of the slice: `Fix tenant provisioning: applications.vendor_id FK
referenced a table created later`.

### Phase A — Schema

**A1.** In `database.py`, locate `CREATE TABLE IF NOT EXISTS canonical_vendors`
(inside `_GRID_TABLES`). Immediately after that table's index line, add:

```sql
-- ── Canonical Control Registry (shared identity across all modules) ───────
CREATE TABLE IF NOT EXISTS canonical_controls (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ref                 TEXT,
    title               TEXT NOT NULL,
    description         TEXT,
    owner_user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    automation          TEXT DEFAULT 'manual',
    test_frequency_days INTEGER,
    last_tested_at      TEXT,
    business_unit_id    INTEGER,
    is_active           INTEGER DEFAULT 1,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_canonical_controls_title ON canonical_controls(lower(trim(title)));
```

`business_unit_id` is a bare INTEGER on purpose (same ordering hazard as
Phase 0 — business_units is created in an earlier block, but keep the
convention consistent for cross-block references).

**A2.** At the END of `_ERM_ORM_TABLES` (just before its closing `"""`),
add:

```sql
-- ── Risk ↔ Control bridge (Governance Graph edge) ─────────────────────────
CREATE TABLE IF NOT EXISTS risk_controls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id     INTEGER NOT NULL REFERENCES erm_enterprise_risks(id) ON DELETE CASCADE,
    control_id  INTEGER NOT NULL,
    weight      REAL DEFAULT 1.0,
    direction   TEXT DEFAULT 'mitigates',
    created_by  INTEGER,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(risk_id, control_id)
);
CREATE INDEX IF NOT EXISTS idx_risk_controls_risk ON risk_controls(risk_id);
CREATE INDEX IF NOT EXISTS idx_risk_controls_control ON risk_controls(control_id);
```

**A3.** Append to `_COLUMN_MIGRATIONS` (keep the existing comment style):

```python
        # ── Governance Graph T1.2: canonical control linkage + user BU ────────
        ("aria_controls",     "canonical_control_id", "INTEGER"),
        ("grid_controls",     "canonical_control_id", "INTEGER"),
        ("orm_rcsa_controls", "canonical_control_id", "INTEGER"),
        ("users",             "business_unit_id",     "INTEGER"),
]
```

**A4.** Backfill: in `_seed_baseline_data()`, add a block (same
try/except/rollback style as the audit backfill) that creates canonical
rows from existing module controls and stamps them back. Mirror the
canonical-vendor auto-migration already in `database.py` (search for the
comment "canonical" near line ~3560 to find it and copy its shape):

```python
    # ── Backfill canonical_controls from ARIA + GRID controls (idempotent) ──
    try:
        for src_table, ref_col, title_col in (
            ("aria_controls", "control_ref", "title"),
            ("grid_controls", "ref", "title"),
        ):
            rows = conn.execute(
                f"SELECT id, {ref_col} AS ref, {title_col} AS title FROM {src_table} "
                f"WHERE canonical_control_id IS NULL AND {title_col} IS NOT NULL"
            ).fetchall()
            for r in rows:
                existing = conn.execute(
                    "SELECT id FROM canonical_controls WHERE lower(trim(title))=lower(trim(%s)) LIMIT 1",
                    (r["title"],)).fetchone()
                cid = existing[0] if existing else insert_returning_id(
                    conn,
                    "INSERT INTO canonical_controls (ref, title) VALUES (%s, %s)",
                    (r["ref"], r["title"]))
                conn.execute(
                    f"UPDATE {src_table} SET canonical_control_id=%s WHERE id=%s",
                    (cid, r["id"]))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
```

IMPORTANT: before writing this block, READ the actual column names of
`aria_controls` and `grid_controls` in their CREATE TABLE statements —
the ref/title column names above are guesses and MUST be corrected to the
real names found in the schema. Do not skip this check.

### Phase B — Governance module: canonical controls API

**B1.** `modules/governance/data_service.py`: add
`list_canonical_controls(bu_id=None, include_inactive=False)`,
`create_canonical_control(data)`, `update_canonical_control(cid, data)`,
`delete_canonical_control(cid)` — copy the exact shape of the existing
`list_applications` / `create_application` / etc. functions in the same
file (same `_dicts`, same commit/close pattern). Delete must refuse
(return False) when `risk_controls` rows reference the control.

**B2.** `modules/governance/routes.py`: add 4 endpoints under
`/governance/api/controls`, copying the applications endpoints exactly:
GET list (`governance.entities.view`), POST / PUT / DELETE
(`governance.entities.manage`), DELETE returning 409 when refused.

**B3.** `modules/governance/templates/index.html`: add a sixth tab
"Controls" following the exact pattern of the Applications tab (toolbar
with BU filter, table with Name/Ref/Owner/Automation/Last tested columns,
add/edit modal). Update `get_governance_summary()` in data_service to
include the `canonical_controls` count and add a sixth stat card.

### Phase C — ERM: risk↔control links

**C1.** `modules/erm/data_service.py`, new functions (place after
`delete_enterprise_risk`):

- `list_risk_controls(risk_id)` — JOIN risk_controls to
  canonical_controls, return control fields + weight.
- `link_risk_control(risk_id, control_id, user_id, weight=1.0)` — INSERT
  with `ON CONFLICT DO NOTHING` (the UNIQUE constraint makes re-links
  idempotent), commit, return True.
- `unlink_risk_control(risk_id, control_id)` — DELETE, commit.

**C2.** `modules/erm/routes.py`, three endpoints next to the existing
risk detail endpoint:

- `GET /api/risks/{risk_id}/controls` — capability `erm.risk.view`
- `POST /api/risks/{risk_id}/controls` — capability `erm.risk.manage`,
  body `{control_id, weight}`; 404 if the risk does not exist.
- `DELETE /api/risks/{risk_id}/controls/{control_id}` — `erm.risk.manage`

**C3.** `modules/erm/templates/index.html`: in the risk drawer
(`ermOpenRiskDrawer`), add a "Linked Controls" drawer section listing
linked controls with an unlink button, plus a "+ Link control" button
that opens a small modal with a `<select>` populated from
`GET /governance/api/controls`. Follow the existing drawer-section
pattern (`erm-drawer-section` / `erm-drawer-section-title` CSS classes
already exist).

### Phase D — BU scoping groundwork

**D1.** `modules/governance/data_service.py`: every `list_*` function
already accepts `bu_id` — no change. Add BU column to the users admin?
NO — out of scope. Only add: `modules/erm/data_service.py`
`list_enterprise_risks(...)` gains an optional `bu_id=None` param that
appends `AND business_unit_id=%s` when set, and
`modules/erm/routes.py` `api_risks_list` passes
`bu_id=p.get("bu_id")` through (validate with `int()` inside a
try/except, ignore invalid).

**D2.** Do NOT implement per-user automatic BU restriction in this slice
(it changes every module's query surface). It ships with T1.3 when the
queries get touched anyway. The `users.business_unit_id` column from A3
is groundwork only.

### Phase E — Tests + verification

`oneforall/tests/test_governance_controls.py`:

1. Fresh-context test: create canonical control via data_service, list
   shows it, update changes title, delete succeeds when unlinked.
2. Link test: create a risk (direct SQL insert with minimal fields — copy
   an existing ERM test's insert if one exists), link the control, list
   returns 1 row with the weight, re-link is idempotent (still 1 row),
   delete of the canonical control now returns False (refused), unlink,
   delete now succeeds. Clean up all rows.

Then: `py_compile` all touched files; full pytest; live browser pass —
open Governance → Controls tab, create a control; open ERM → any risk
drawer → link it → see it listed → unlink. Delete test data.

## Edge cases a weaker model would miss

- **Phase 0 must land before any fresh-provisioning test** — if you
  provision a new PG tenant with the FK still in place, provisioning
  aborts mid-schema and leaves a half-created tenant schema behind.
- **Do not guess ARIA/GRID column names in the backfill** (A4). The real
  ref/title columns must be read from the CREATE TABLE text. If
  `grid_controls` has no ref column, backfill title-only and pass NULL
  for ref.
- **`risk_controls.control_id` has NO FK on purpose** in SQLite text but
  the table lives in `_ERM_ORM_TABLES` which is created after
  `_GRID_TABLES` (where canonical_controls lives) — an FK would actually
  be safe here. It is omitted anyway for consistency; app-level guards
  (delete refusal in B1) provide integrity.
- **`ON CONFLICT DO NOTHING` needs the UNIQUE constraint to exist on PG**
  — it is declared inline in the CREATE; but for EXISTING deployed
  databases the new table is only created fresh, so no migration issue.
  Never add `ON CONFLICT` clauses targeting constraints that older
  deployments might lack.
- **The framework editor (Slice 2) delete-reinserts framework content** —
  do NOT key anything in this slice to `erm_framework_*` row ids, and do
  not link canonical_controls to the rating-framework tables at all.
  "Rating Frameworks" (scoring) and compliance frameworks (controls) are
  unrelated concepts in this codebase.
- **`_to_pg_schema()` auto-converts the SQLite DDL** — write the new
  tables in SQLite dialect only (AUTOINCREMENT, datetime('now')); never
  hand-write a PG variant.
- **Drawer JS**: the ERM SPA caches heavily; after link/unlink re-fetch
  only the drawer section, not the whole register, and guard against the
  drawer being closed before the fetch returns (check the drawer element
  still exists before writing innerHTML).
- **Weight input**: clamp to 0.1–5.0 server-side (`max(0.1, min(5.0,
  float(weight or 1.0)))`) — the T1.3 engine will consume it and division
  by zero/negative weights must be impossible by construction.

## Acceptance criteria

1. Phase 0: fresh SQLite `init_db()` in a temp dir succeeds AND
   (code-inspection) neither `_SHARED_TABLES` nor `_PLATFORM_TABLES`
   contains `REFERENCES canonical_vendors`.
2. `canonical_controls` and `risk_controls` exist after init; summary
   endpoint returns a `canonical_controls` count.
3. Backfill: after startup with pre-existing ARIA/GRID controls, every
   row has non-NULL `canonical_control_id`, and duplicate titles across
   modules share ONE canonical id.
4. All 4 governance control endpoints + 3 ERM link endpoints respond
   correctly (201/200/409/404 paths).
5. Full pytest green including the 2 new test groups.
6. Live browser: create control → link to risk → visible in drawer →
   unlink → canonical delete succeeds. No console errors.
