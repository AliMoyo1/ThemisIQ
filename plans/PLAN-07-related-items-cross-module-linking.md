# PLAN-07: Related Items panel + manual cross-module linking

## Goal

`cross_module_links` (database.py, with a dedup UNIQUE index) is written
by event handlers today but has NO user-facing surface: users cannot see
that a breach is linked to an audit, or manually link a risk to a BCM
plan. This plan ships:

1. A generic links API (list both directions / create / delete).
2. A reusable "Related Items" panel rendered inside the entity drawers of
   ERM (risk), ORM (event), GRID (audit), Sentinel (breach), and BCM
   (incident), showing linked entities as deep links (PLAN-06 convention)
   with an unlink button.
3. A "+ Link" picker that reuses the global search endpoint to find the
   target entity.

This is the "modules are one brain" experience made tangible — the
highest-visibility cross-module communication win available without new
schema.

**Dependency: PLAN-06 must be done first** (deep links are what make the
panel's entries clickable).

## Exact files to touch

1. `oneforall/modules/launcher/routes_platform.py` — 3 new endpoints
2. `oneforall/static/js/related_items.js` — new reusable component
3. `oneforall/modules/erm/templates/index.html` — mount in risk drawer
4. `oneforall/modules/orm/templates/index.html` — mount in event drawer
5. `oneforall/modules/grid/templates/index.html` (verify actual template
   name) — mount in audit view
6. `oneforall/modules/sentinel/templates/index.html` — mount in breach drawer
7. `oneforall/modules/bcm/templates/index.html` — mount in incident view
8. `oneforall/tests/test_cross_module_links_api.py` — new tests

## Step-by-step order

### Step 1 — Entity whitelist + title lookup (server side)

At module level in `routes_platform.py`, add an explicit whitelist that
maps `(module, entity_type)` → `(table, title_column)`. NEVER interpolate
user input into SQL table names — only values from this dict:

```python
_LINKABLE = {
    ("erm", "risk"):        ("erm_enterprise_risks", "title"),
    ("orm", "event"):       ("orm_events", "title"),
    ("grid", "audit"):      ("grid_audits", "name"),
    ("grid", "nc"):         ("grid_non_conformances", "title"),
    ("sentinel", "breach"): ("sentinel_breaches", "title"),
    ("sentinel", "ropa"):   ("sentinel_ropa", "processing_name"),
    ("sentinel", "dpia"):   ("sentinel_dpias", "title"),
    ("bcm", "plan"):        ("bcm_plans", "title"),
    ("bcm", "incident"):    ("bcm_incidents", "title"),
    ("aria", "document"):   ("aria_documents", "title"),
    ("evidence", "item"):   ("evidence_items", "title"),
}
```

BEFORE writing this dict, verify every table/column pair against the
CREATE TABLE statements in `database.py` (e.g. confirm `grid_audits.name`
vs `title`, `bcm_incidents.title` — fix any that differ).

### Step 2 — Three endpoints

Add after the existing task endpoints in `routes_platform.py`, using the
same decorator/guard style (`@require_auth`, `_JSONResp`):

**GET `/api/links/{module}/{etype}/{eid}`** — return links in BOTH
directions. Two queries against `cross_module_links` (source-match and
target-match), then for each row resolve the "other side" title via
`_LINKABLE` (single `SELECT {title_col} FROM {table} WHERE id=%s` per
row — these lists are short, N+1 is acceptable here). Response items:
`{link_id, module, entity_type, entity_id, title, relationship, direction}`.
Unknown (module, type) pairs on the other side: include with
`title: null` rather than crashing.

**POST `/api/links`** — body
`{source_module, source_type, source_id, target_module, target_type, target_id, relationship}`.
Validate BOTH endpoints exist in `_LINKABLE` and both entity rows exist
(SELECT 1). Reject self-links (identical source and target triple).
Sanitize `relationship` with the existing `validate_choice` against
`{"related", "mitigates", "caused_by", "evidence_for", "triggered"}`,
defaulting to `"related"`. Insert copying the conflict-handling idiom
already used for this table — grep `INSERT` + `cross_module_links` in the
codebase and reuse that exact pattern (a dedup UNIQUE index exists;
duplicate links must be a silent no-op returning the existing state, not
a 500). Set `created_by` from the session user.

**DELETE `/api/links/{link_id}`** — allowed for the link's `created_by`
or anyone with `platform.manage_users`; 403 otherwise, 404 if missing.

### Step 3 — Reusable JS component

Create `oneforall/static/js/related_items.js`:

```js
/* Renders a Related Items panel into a container element.
   Usage: RelatedItems.mount(el, 'erm', 'risk', 42, {canEdit:true}) */
```

- `mount()` fetches `GET /api/links/{module}/{etype}/{eid}`, renders a
  list: icon per module, title (fallback `{module}/{type} #{id}` when
  title is null), relationship chip, deep link href
  (`/{module}/?open={type}:{id}` — same convention as PLAN-06), and an
  unlink × button when `canEdit`.
- "+ Link" button opens a minimal overlay: text input → debounced fetch
  to `/api/search?q=` → results list → click result → POST `/api/links`
  → re-render panel.
- No framework, plain JS, matches the drawer styling by reusing existing
  CSS classes (inspect the target drawer's section classes and reuse;
  e.g. ERM has `erm-drawer-section` / `erm-drawer-section-title`).
- All text content through a local `esc()` — titles come from the DB.

### Step 4 — Mount in five drawers

For each module, find the drawer/detail render function (the PLAN-06
inventory already lists them) and append a container div + mount call at
the end of the drawer body render. Example for ERM
(`ermOpenRiskDrawer`): after the drawer HTML is written, add

```js
var riWrap = document.createElement('div');
document.querySelector('.erm-drawer-body').appendChild(riWrap);
RelatedItems.mount(riWrap, 'erm', 'risk', r.id, {canEdit: true});
```

Load the script once per template via
`<script src="/static/js/related_items.js"></script>` near the other
script includes. Verify the static mount path prefix by checking how
existing files in `oneforall/static/` are referenced in templates.

### Step 5 — Tests

`oneforall/tests/test_cross_module_links_api.py` (copy bootstrap style
from an existing test):

1. POST a link risk→plan with both rows inserted directly; expect 200/201.
2. POST the same link again; expect success response and still exactly
   ONE row in cross_module_links.
3. POST with an invalid module (`"hack"`) → 400.
4. POST with nonexistent target id → 400/404.
5. GET from the risk side and from the plan side — both return the link
   with correct `direction`.
6. DELETE as a different non-admin user id → 403 (simulate by calling the
   underlying logic or via test client with a second session, matching
   how existing auth tests do it).
7. Clean up all rows.

### Step 6 — Verify live, commit

Live pass: open an ERM risk drawer → panel renders (empty state) →
"+ Link" → search a BCM plan → link it → entry appears → click it → BCM
opens with the plan via deep link → back to ERM → unlink → gone. One
commit: `Add Related Items cross-module linking panel and links API`.

## Edge cases a weaker model would miss

- **Table-name interpolation is the injection risk here.** Every f-string
  containing a table or column name must draw ONLY from `_LINKABLE`
  values, never from request input. Entity ids go through `%s` params.
- **Both directions matter.** A link stored as breach→audit must appear
  in the audit's panel too. Do not store two rows; query twice.
- **The dedup index treats `relationship` as part of the key** — linking
  the same pair with a different relationship creates a second row. That
  is intended behavior; do not "fix" it.
- **Deleted entities leave dangling links** (no FKs on this table by
  design). The GET endpoint must tolerate missing other-side rows
  (`title: null`), and the panel renders them with a muted
  "(deleted)" label instead of a broken deep link — no href in that case.
- **RLS/tenant scoping is already handled** by `get_db()` search_path on
  PG — but only if the endpoints use `get_db()` like the rest of
  routes_platform.py does. Do not use `get_db_bypass_rls()` here.
- **Drawer re-open leaks mounts** — the ERM drawer rebuilds its DOM on
  every open, which garbage-collects the old panel; but GRID's audit
  view may be a persistent page section. Check before mounting: if the
  container already has a `data-ri-mounted` attribute, clear it first.
- **The picker must exclude the current entity itself** from results
  (filter client-side on module+type+id equality) or users create
  self-links the server then rejects — confusing UX.
- **`related_items.js` is cached by nginx for 7 days**
  (`location /static/` sets `expires 7d`). During iteration add a
  `?v=1` query suffix to the script tag and bump it on change.

## Acceptance criteria

1. All 7 API tests pass; full suite green.
2. Live round-trip (link → deep-link navigate → unlink) works between
   ERM and BCM, and between Sentinel breach and GRID audit.
3. Duplicate link POST leaves exactly one row (verified in test 2).
4. A link whose target row was deleted renders "(deleted)" and the page
   does not error.
5. `grep -n "f\"" oneforall/modules/launcher/routes_platform.py` around
   the new endpoints shows table names sourced only from `_LINKABLE`.
