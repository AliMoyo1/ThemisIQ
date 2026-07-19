# PLAN-27: ERM Objectives Registry + Pillars Admin (assessment contexts)

## Status: OPEN (requires PLAN-23; independent of PLAN-25/26 but the
dashboard objective filter lands here as a small follow-up to PLAN-26)

## Goal

Model the mind map's assessment contexts: a registry of objectives
(strategic, standard-based such as ISMS/BCMS/AIMS objectives, and
departmental), a hierarchy where standard and departmental objectives
support strategic ones, risk linkage to an objective, a risk_context tag
(strategic / operational / external), and an admin UI to manage objectives
and pillars. Rule from the mind map: a strategic assessment links the risk
to a Strategic Objective and the supporting standard objective; a
departmental assessment links departmental objectives to the strategic
objectives they support.

## Files to touch (exact)

1. `oneforall/database.py`
2. `oneforall/modules/erm/data_service.py`
3. `oneforall/modules/erm/routes.py`
4. `oneforall/modules/erm/templates/index.html`
5. `oneforall/tests/test_erm_objectives.py` (NEW)
6. `plans/README.md`

## Step-by-step order

### Step 0: create `plans/PLAN-27-active.md`; log every change as you go.

### Step 1: database.py

New table in `_ERM_ORM_TABLES` (after erm_pillars):

```sql
-- ── ERM v2: Objectives registry (strategic / standard / departmental) ──
CREATE TABLE IF NOT EXISTS erm_objectives (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    title             TEXT NOT NULL,
    obj_type          TEXT NOT NULL DEFAULT 'strategic',
    parent_id         INTEGER REFERENCES erm_objectives(id) ON DELETE SET NULL,
    standard_ref      TEXT,
    pillar            TEXT,
    department        TEXT,
    owner_id          INTEGER REFERENCES users(id),
    business_unit_id  INTEGER,
    status            TEXT DEFAULT 'active',
    description       TEXT,
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_erm_obj_type ON erm_objectives(obj_type);
CREATE INDEX IF NOT EXISTS idx_erm_obj_parent ON erm_objectives(parent_id);
```

obj_type values: strategic, standard, departmental (app-level validation).
standard_ref is free text like "ISO 27001" or "ISO 42001" for
obj_type = standard. Hierarchy rule enforced in the data service:
parent_id may only point at an objective of obj_type strategic, and
strategic objectives have parent_id NULL.

Column migrations appended to `_COLUMN_MIGRATIONS` after the PLAN-23
block:

```python
# ── ERM v2 (PLAN-27): objective linkage + assessment context ─────────
("erm_enterprise_risks", "objective_id", "INTEGER DEFAULT NULL"),
("erm_enterprise_risks", "risk_context", "TEXT DEFAULT NULL"),
```

risk_context values: strategic, operational, external (NULL for legacy
rows; the external value is consumed by PLAN-28).

### Step 2: data_service.py

- `list_objectives(obj_type=None, include_archived=False)`: joined with
  parent title (LEFT JOIN self) and owner name, ordered obj_type, title.
- `create_objective(data)` / `update_objective(oid, data)` /
  `archive_objective(oid)` (status flip, never DELETE while any
  erm_enterprise_risks.objective_id references it; check and raise
  ValueError "Objective is linked to N risks").
- Validation helper `_validate_objective(data, db)`: obj_type in the value
  list; title non-empty; parent rules above; standard_ref required when
  obj_type = standard.
- Pillar CRUD to complete PLAN-23's read-only endpoint:
  `create_pillar(data)`, `update_pillar(pid, data)`,
  `deactivate_pillar(pid)` (is_active = 0; block when referenced by any
  risk's impacted_pillar with a ValueError, matching the objective rule).
- `create_enterprise_risk` / `update_enterprise_risk`: add objective_id
  and risk_context to the writable fields (update path); create INSERT
  gains both columns. Validate risk_context value when present; validate
  objective_id exists when present (raise ValueError).
- `get_enterprise_risk`: LEFT JOIN objective title as objective_title and
  parent strategic objective title as strategic_objective_title so the
  drawer can show "Objective X supporting Strategic Objective Y".

### Step 3: routes.py

Under the framework-admin endpoints (same file section, same style):

- `GET  /api/objectives` (erm.risk.view) with optional obj_type param.
- `POST /api/objectives`, `PUT /api/objectives/{oid}`,
  `POST /api/objectives/{oid}/archive` (erm.framework.manage).
- `POST /api/pillars`, `PUT /api/pillars/{pid}`,
  `POST /api/pillars/{pid}/deactivate` (erm.framework.manage).
- ValueError anywhere maps to HTTP 400 with the message.

### Step 4: UI

a) New SPA page "objectives" ("Objectives & Pillars"): add to _SPA_PAGES
in routes.py (line ~41 region) and the router/crumbs/switch in index.html,
following exactly the pattern the rating-guide and framework-admin pages
used. Nav link gated on can_manage_frameworks (context flag already
exists). Two panels:
- Objectives: table grouped by obj_type (Strategic first), columns title,
  type badge, standard_ref, supports (parent title), pillar, owner,
  status; add/edit modal with the validation rules mirrored client-side
  (parent select only lists strategic objectives and only shows for
  non-strategic types; standard_ref input only for standard type).
- Pillars: simple list with add/edit/deactivate.

b) Risk modal (ermOpenRiskModal): add a Risk Context select
(-- None -- / Strategic / Operational / External) and an Objective select
populated from `/erm/api/objectives` filtered client-side: when context is
strategic show strategic + standard objectives grouped with optgroup;
when operational show departmental + standard; when external or none show
all. Preselect existing values. ermSaveRisk sends objective_id
(int or null) and risk_context (string or null).

c) Drawer details grid: show risk_context badge and
"{objective_title} supporting {strategic_objective_title}" line when
present.

d) Dashboard filter (only if PLAN-26 is already merged): add an Objective
select to the filter bar and `objective_id` to _posture_where and the
dashboard endpoint params. If PLAN-26 is not merged yet, skip d) and note
the skip in the active plan file.

### Step 5: tests - `oneforall/tests/test_erm_objectives.py`

1. create strategic objective; standard objective with the strategic
   parent: ok; standard objective with a standard parent: ValueError;
   strategic with any parent: ValueError.
2. standard type without standard_ref: ValueError.
3. archive blocked while a risk links the objective; allowed after
   unlinking.
4. risk create with objective_id + risk_context strategic persists; bogus
   objective_id raises; bogus risk_context raises.
5. get_enterprise_risk returns objective_title and
   strategic_objective_title.
6. pillar deactivate blocked while referenced by a risk's impacted_pillar.

### Step 6: verify

- py_compile + full pytest.
- Live browser: create a strategic objective "Grow ARR", a standard
  objective "ISMS: protect customer data" supporting it (ISO 27001);
  create a risk with context Strategic linked to the ISMS objective;
  drawer shows the support chain; the register still renders; clean up.
- Update plans/README.md. One focused commit.

## Edge cases a weaker model would miss

- The legacy `strategic_objective` TEXT column on risks stays untouched
  and keeps rendering wherever it already renders; the new registry is
  additive. Do not migrate or delete the old text values.
- parent_id ON DELETE SET NULL means archiving is the safe path; the
  archive guard must count LINKED RISKS, not child objectives (children
  survive with parent_id NULL only on hard delete, which this plan never
  performs).
- Client-side filtering of the objective select must not hide an already
  linked objective on edit (an operational risk linked to a strategic
  objective before a context change must still display its current link).
  Always include the currently selected objective in the options.
- optgroup labels are not selectable values; test the select posts the
  option value (id int), not the label.
- risk_context and objective_id are independent: either may be set alone.
  No cross-validation between them (the mind map allows departmental
  assessments linking through standards).
- Deactivated pillars must still render on risks that already carry them
  (impacted_pillar is a TEXT snapshot, not an FK): the modal select shows
  active pillars plus the risk's current value when inactive.

## Acceptance criteria

- [ ] All 6 test cases pass; suite green; py_compile clean.
- [ ] Hierarchy rules enforced exactly (only strategic parents; strategic
      roots only).
- [ ] Objectives admin page fully usable by an erm.framework.manage user
      and invisible to others.
- [ ] Risk modal round-trips objective_id + risk_context.
- [ ] Legacy strategic_objective text still displays unchanged.
