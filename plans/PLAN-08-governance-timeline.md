# PLAN-08: Governance Timeline — cross-module causality view

## Goal

Roadmap item T2.4. Every module already emits persisted events into the
`events` table (`core/events.py` `emit()` INSERTs event_type,
source_module, source_entity_type, source_entity_id, payload, created_by,
created_at, status). Nobody can SEE this stream. This plan ships a
"Timeline" page: every cross-module event on one vertical, day-grouped,
color-coded timeline — policy published → control failed → risk
escalated → incident declared — with each entry deep-linking to its
source entity. This is the cheapest high-visibility feature in the
backlog because the data already exists.

**Dependency: PLAN-06** (deep links) for clickable entries. Ship after it.

## Exact files to touch

1. `oneforall/modules/launcher/routes_platform.py` (or a new
   `routes_timeline.py` registered in main.py — prefer extending
   routes_platform.py to avoid router wiring) — 1 API endpoint + 1 page route
2. `oneforall/modules/launcher/templates/timeline.html` — new page
3. `oneforall/templates/_icon_sidebar.html` — nav entry
4. `oneforall/core/events.py` — read-only reference (event constants for
   the label map; do not modify)
5. `oneforall/tests/test_timeline_api.py` — new test

## Step-by-step order

### Step 1 — API endpoint

`GET /api/timeline` in routes_platform.py, `@require_auth`. Query params:
`days` (int, default 30, clamp 1-365), `module` (optional, validate
against `{"aria","grid","bcm","sentinel","erm","orm"}`), `page` (default
1, 100 rows per page).

Query the `events` table:

```sql
SELECT id, event_type, source_module, source_entity_type,
       source_entity_id, payload, created_by, created_at
FROM events
WHERE created_at >= <days-ago>
[AND source_module = %s]
ORDER BY created_at DESC
LIMIT 100 OFFSET <(page-1)*100>
```

For the days-ago expression use the EXISTING cross-engine helper — grep
`sql_date_offset` / `sql_now_offset` in `database.py` and copy a call
site's usage exactly; do not hand-write `datetime('now', ...)` (breaks
PG) or `NOW() - INTERVAL` (breaks SQLite).

Enrich each row in Python:
- `user_name` via one batched query
  (`SELECT id, full_name FROM users WHERE id IN (...)`) over the distinct
  created_by ids — not per-row.
- `label`: humanize `event_type` with a static map for the ~30 known
  constants in `core/events.py` (e.g. `"sentinel.breach.confirmed"` →
  `"Breach confirmed"`); fallback = last segment, underscores→spaces,
  title-cased.
- `link`: `/{source_module}/?open={source_entity_type}:{source_entity_id}`
  when both are present, else null. Use the SAME entity-type strings the
  PLAN-06 boot handlers registered — READ one boot handler's OPENERS map
  and reconcile mismatches server-side with a small alias dict (e.g.
  events may say `enterprise_risk` where the SPA registered `risk`).

Also return `total` (COUNT with the same WHERE) for pagination.

### Step 2 — Page route + template

Add `GET /timeline` page route next to the other launcher page routes
(grep how `/workflows` or `/risk-register` are served in the launcher
routes files and copy that exact pattern, including `shell_ctx`).

`timeline.html` extends `base_shell.html` (copy the block structure from
`workflows.html`):

- Filter bar: module dropdown (All + 6 modules), day-range chips
  (7/30/90), Load-more button for pagination.
- Vertical timeline: entries grouped under day headers (group client-side
  by `created_at` date prefix). Each entry: colored dot per module (reuse
  the color map from workflows.html `catColor()` idea but key by module:
  aria `#1D9E75`, grid `#378ADD`, sentinel `#D85A30`, bcm `#993556`,
  erm `#E24B4A`, orm `#BA7517`), label, user_name, time, and — when
  `link` is non-null — a clickable "open" arrow using the deep link.
- Empty state: "No governance events in this window."
- All rendered strings through an `esc()` helper.

### Step 3 — Nav entry

In `_icon_sidebar.html`, add a Timeline icon between the module icons and
the governance icon, visible to all authenticated users (no capability
gate — the events shown are already tenant-scoped; see edge cases). Use a
simple clock/history SVG matching the existing 24x24 stroke style.

### Step 4 — Test

`test_timeline_api.py`: insert 3 events directly (two modules, one older
than 7 days), call the endpoint logic with `days=7` → only the recent 2;
filter `module=` → 1; verify `link` shape; clean up.

### Step 5 — Verify live, commit

Live: perform one real action that emits (e.g. create + close an ERM
risk), open /timeline, see the entries, click one, land in the module
with the drawer open. Commit:
`Add cross-module Governance Timeline page backed by the events table`.

## Edge cases a weaker model would miss

- **Tenant isolation comes from `get_db()` search_path on PG** — the
  `events` table has NO org_id column; isolation is schema-per-tenant.
  Therefore: use `get_db()` (never the bypass variant), and do NOT add
  an org_id filter that would break on the column not existing.
- **`audit_log` is NOT the source here.** It is tempting to merge
  audit_log rows in — do not: audit_log has the tenant-isolation bug
  (PLAN-01) and different semantics (every CRUD click). The events table
  is the curated cross-module stream. A merged view can be a follow-up
  after PLAN-01 lands.
- **payload is JSON TEXT and may be `"{}"` or invalid** — parse with
  try/except, never `json.loads` bare.
- **created_at formats differ across engines** (SQLite
  `YYYY-MM-DD HH:MM:SS` vs PG timestamps serialized by the wrapper).
  Group by `str(created_at)[:10]` client-side — do not date-parse
  server-side.
- **Entity-type mismatch between events and SPA openers is the #1
  breakage risk** — the alias dict in Step 1 exists precisely because
  handlers emit types like `"policy"` or `"non_conformance"` that must
  map onto whatever PLAN-06 registered. Build the alias dict by READING
  the actual `emit(...)` call sites (grep `emit(` across `modules/`) and
  the OPENERS maps, not by guessing.
- **Deleted entities:** deep link opens the module, the PLAN-06 retry
  loop expires silently. Acceptable; no server-side existence check
  needed (it would N+1 the whole timeline).
- **Do not paginate with OFFSET on `payload`-heavy selects beyond a few
  pages** — cap `page` at 20 server-side; the UI's Load-more stops when
  `page*100 >= total`.
- **The nav icon must also appear active** — pass
  `active_module="timeline"` from the page route and use the standard
  `{% if active_module == 'timeline' %} active{% endif %}` pattern so
  highlighting works.

## Acceptance criteria

1. `/api/timeline` returns paginated, filtered, enriched events; test
   passes; full suite green.
2. Live: a freshly emitted event appears on /timeline within one reload
   and its entry deep-links into the owning module.
3. Module filter and day chips change the result set.
4. Page renders with zero console errors and an empty-state when
   filtered to nothing.
5. Nav icon shows for a non-admin user (e.g. an `employee`-role login)
   and the page loads for them.
