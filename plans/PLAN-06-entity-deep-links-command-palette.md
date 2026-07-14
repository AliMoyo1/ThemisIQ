# PLAN-06: Universal entity deep links + Ctrl+K command palette

## Goal

Nothing in the platform can navigate to a specific record. Global search
(`/api/search`, routes_platform.py:93) finds entities across all modules
but every result links to the module ROOT (`"link": "/aria/"`). The
workflows page's `entityLink()` helper (workflows.html:445-454) does the
same. Notifications link to module roots too. Users find the thing, then
manually hunt for it again inside the module.

This plan introduces ONE deep-link convention platform-wide:

```
/{module}/?open={entity_type}:{id}      e.g.  /erm/?open=risk:42
```

Each module SPA reads the `open` param on boot and opens the matching
drawer/detail view. Then search results, the workflows helper, and a new
Ctrl+K command palette all emit these links. Every later plan (Related
Items, Timeline, Briefing) reuses this convention — build it once, here.

## Exact files to touch

1. `oneforall/modules/launcher/routes_platform.py` — `api_global_search()`
   (line ~93): emit deep links per result
2. `oneforall/modules/erm/templates/index.html` — boot handler
3. `oneforall/modules/orm/templates/index.html` — boot handler
4. `oneforall/modules/grid/templates/index.html` (or the GRID SPA entry
   template — verify name by listing `modules/grid/templates/`) — boot handler
5. `oneforall/modules/sentinel/templates/index.html` — boot handler
6. `oneforall/modules/bcm/templates/index.html` — boot handler
7. `oneforall/modules/aria/templates/index.html` — boot handler
8. `oneforall/modules/evidence/templates/evidence_index.html` — boot handler
9. `oneforall/modules/launcher/templates/workflows.html` — fix `entityLink()`
10. `oneforall/templates/base_shell.html` — Ctrl+K palette (extend the
    existing header search, do not add a second search UI)

## Step-by-step order

### Step 1 — Inventory the drawer-open functions (read-only, 30 min)

For each module SPA, grep its index.html for `Drawer(` and `function .*Open`
and record the function that opens a single entity by id, and whether it
fetches its own data or reads a pre-loaded cache. Expected (verify each):

- ERM: `ermOpenRiskDrawer(id)` — verify whether it reads `regCache` or
  fetches `/erm/api/risks/{id}`
- ORM: an event drawer function reading `evtCache` (orm index.html ~1077)
- GRID: audit detail opener
- Sentinel: breach / ropa / dsr / dpia openers
- BCM: plan / incident openers
- ARIA: document opener
- Evidence: item drawer opener

Write the inventory as a comment block at the top of each boot handler you
add in Step 3, mapping `entity_type` string → function name.

### Step 2 — Fix the search API to emit deep links

In `api_global_search()`, change each result's `"link"` value:

| Result type | New link |
|---|---|
| control | `/aria/?open=control:{id}` |
| document | `/aria/?open=document:{id}` |
| ropa | `/sentinel/?open=ropa:{id}` |
| audit | `/grid/?open=audit:{id}` |
| plan | `/bcm/?open=plan:{id}` |
| risk | `/erm/?open=risk:{id}` (READ the risk_register query first — if `source_module` is `orm`, emit `/orm/?open=event:{id}` accordingly) |
| evidence | `/evidence/?open=item:{id}` |
| breach | `/sentinel/?open=breach:{id}` |
| dpia | `/sentinel/?open=dpia:{id}` |
| dsr | `/sentinel/?open=dsr:{id}` |

READ the whole function to the end first — there are more result types
after line 182 than listed here; map every one.

### Step 3 — Add the boot handler to each SPA

Add one small script block per SPA, immediately after its existing init
code (find the `DOMContentLoaded` listener or the bottom-of-file init
calls). Template — adapt the mapping per module:

```js
(function(){
  var openParam = new URLSearchParams(window.location.search).get('open');
  if(!openParam) return;
  var sep = openParam.indexOf(':');
  if(sep < 1) return;
  var etype = openParam.slice(0, sep);
  var eid = parseInt(openParam.slice(sep + 1), 10);
  if(!eid) return;
  // Strip the param so refresh/back doesn't re-open the drawer
  window.history.replaceState({}, '', window.location.pathname);
  var OPENERS = {
    'risk': function(id){ ermOpenRiskDrawer(id); },
    // ...one entry per entity type this module owns
  };
  var fn = OPENERS[etype];
  if(!fn) return;
  // SPA data may still be loading — retry briefly until the opener succeeds
  var tries = 0;
  (function attempt(){
    tries++;
    try { fn(eid); } catch(e){ if(tries < 20) setTimeout(attempt, 250); }
  })();
})();
```

For openers that read a cache (e.g. ORM's `evtCache`), the try/retry loop
handles the not-yet-loaded case only if the opener THROWS on a cache miss.
READ each opener: if it fails silently on missing cache, guard explicitly
(`if(!evtCache.length){ setTimeout(attempt,250); return; }`).

### Step 4 — Fix workflows.html entityLink()

Replace the body of `entityLink()` (line ~447) so the href includes the
entity: `href = (MODULE_HREF[module]||'/') + '?open=' + entityType + ':' + entityId;`
Keep the existing label/`target="_blank"` behavior. Add `erm`, `orm` to
`MODULE_HREF` (currently missing both).

### Step 5 — Ctrl+K command palette

FIRST read `oneforall/templates/base_shell.html` and find the existing
header search implementation (the header shows "Search across all
modules"). Extend it — do not build a parallel component:

1. Bind `Ctrl+K` (and `Cmd+K` via `e.metaKey`) on `document` to focus the
   existing search input (or open its dropdown). `e.preventDefault()` so
   the browser's own shortcut doesn't fire.
2. Ensure the dropdown renders results from `/api/search` with the NEW
   deep links (it probably already fetches this endpoint — verify), adds
   arrow-key navigation (`ArrowUp`/`ArrowDown` move an `.active` class,
   `Enter` navigates to the active result's link), and `Escape` closes.
3. Debounce input at 250ms if not already debounced.

### Step 6 — Verify

- `py_compile` on routes_platform.py.
- Full pytest.
- Live browser: search a known risk title → click result → ERM opens WITH
  the risk drawer showing. Repeat for one entity in each of: GRID audit,
  Sentinel breach, Evidence item, BCM plan, ARIA document, ORM event.
- Ctrl+K focuses search; arrows + Enter navigate.
- A deep link with a nonexistent id (`/erm/?open=risk:999999`) does NOT
  error in console after the retry window expires.

## Edge cases a weaker model would miss

- **The retry loop must terminate** (`tries < 20`) — a deleted entity id
  would otherwise retry forever, and each retry may re-throw, spamming
  the console.
- **`history.replaceState` must run BEFORE opening** — if the drawer
  open throws, you still want the param gone so a refresh doesn't loop.
  Also `window.location.pathname` drops the query but PRESERVES the
  path; do not use `'/'`.
- **Some SPAs route by sub-page** (`/erm/{page}` guarded by `_SPA_PAGES`
  in erm/routes.py:42). The boot handler must run on the DEFAULT page —
  a deep link to `/erm/?open=risk:42` lands on the register page, which
  is where the drawer lives. Do not append `?open=` to sub-page URLs.
- **Login redirect:** if the user is logged out, hitting a deep link
  bounces through `/login`. READ the login redirect code
  (`routes_auth.py`) — if it preserves a `next` param, deep links survive
  automatically; if it does not, note it in the final report but DO NOT
  change auth flow in this plan.
- **Sentinel/BCM SPAs may need a tab/page switch before the drawer
  exists** (e.g. breach drawer only mounts on the breaches tab). If the
  opener depends on the active tab, call the module's tab-switch function
  first, then the opener, inside the same attempt function.
- **`parseInt` guards:** `open=risk:abc` must be ignored, not NaN-crash.
- **Escape the param when building links in JS** — entity types are
  hardcoded strings server-side so injection is not possible via
  `/api/search`, but `entityLink()` in workflows takes DB-sourced values;
  keep the existing `esc()` wrapping on the href.
- **Do not touch the nginx config** — `?open=` is a query param on
  existing routes; no new locations needed.

## Acceptance criteria

1. Every `/api/search` result type carries a deep link containing
   `?open={type}:{id}` (grep the function: zero remaining bare
   `"link": "/aria/"`-style values except intentionally page-level ones).
2. Live browser: 7 modules × 1 entity each — search → click → correct
   drawer opens. No console errors.
3. Ctrl+K works from Command Centre AND from inside a module page.
4. Nonexistent-id deep link fails silently after ~5s.
5. Full pytest suite still green.
