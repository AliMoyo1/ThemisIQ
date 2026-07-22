# PLAN-SBU-04: Scope legibility + single-SBU drill-down filter

## Leverage rank: 4 of 4 (DO LAST). UX polish that makes the (now-working)
## scoping understandable and lets a group monitor drill into ONE subsidiary.
## Lower leverage than 01-03 because the feature works without it — but it is
## what stops users from being confused about "why can't I see X" and lets the
## Econet-group user say "show me just EcoCash."

## Goal / feature

Two related UX additions:

**A. Scope indicator in the shell top bar.** Every page shows what the current
user's data scope is, so "missing" records are self-explanatory:
- Org-wide users (super-admin, or no BU): "All units" (subtle/neutral).
- Scoped users: "Unit: EcoCash (+2 sub-units)" or "Unit: Infraco".

**B. Single-SBU drill-down filter for multi-BU users.** A user whose scope
spans several SBUs (a group monitor, or a parent-BU head) gets a dropdown to
temporarily narrow the view to ONE descendant SBU. It works by adding
`?bu=<id>` to the current URL; the already-BU-scoped list endpoints
(post-SBU-02) honor it by intersecting the requested BU with the user's
allowed scope. This is what powers the SBU-03 rollup drill-down links too.

## Prerequisites
- SBU-01 (users assigned) and SBU-02 (endpoints scoped) should be done, or
  the `?bu=` filter has nothing to narrow. The scope *indicator* (part A)
  works after SBU-01 alone.

## Exact files to touch

1. `oneforall/core/shell_context.py` — compute a `scope_label` +
   `scope_bus` (the user's allowed BU list with names) and inject into the
   shell context returned by `shell_ctx()`.
2. `oneforall/modules/governance/data_service.py` — add a small helper
   `bu_scope_detail(user)` returning `{"mode": "all"|"scoped", "root_name":
   str|None, "descendant_count": int, "bus": [{id,name}]}` so the shell can
   render the label and the dropdown without re-deriving the tree.
3. `oneforall/templates/base_shell.html` — render the scope chip in the top
   bar (near the search box / theme toggle, ~lines 800-880) and, when
   `scope_bus | length > 1`, a `<select>` that sets `?bu=`.
4. **Each already-scoped module's list endpoint** (from SBU-02 + the ones
   already scoped: erm, orm, bcm, sentinel, grid) — accept an optional `bu`
   query param and, when present and valid, narrow the effective scope to
   `[bu]` (only if `bu` is within the user's allowed scope; otherwise ignore).
5. `oneforall/tests/test_bu_filter.py` — NEW.

## Step-by-step order

### Step 1 — scope detail helper (`governance/data_service.py`)
```python
def bu_scope_detail(user: dict) -> dict:
    """Human-facing description of the user's BU scope, for the shell chip
    and the drill-down dropdown."""
    scope = bu_scope_ids(user)  # None => all
    if scope is None:
        return {"mode": "all", "root_name": None, "descendant_count": 0, "bus": []}
    db = get_db()
    try:
        rows = _dicts(db.execute(
            "SELECT id, name FROM business_units WHERE id = ANY_PLACEHOLDER"
            .replace("ANY_PLACEHOLDER", "(" + ",".join(["%s"]*len(scope)) + ")"),
            tuple(scope),
        ).fetchall())
    finally:
        db.close()
    root_name = None
    root_id = user.get("business_unit_id")
    for r in rows:
        if r["id"] == root_id:
            root_name = r["name"]
    return {
        "mode": "scoped",
        "root_name": root_name,
        "descendant_count": max(0, len(rows) - 1),
        "bus": rows,
    }
```
(Placeholder note: the app uses `%s`; `IN (%s,%s,...)` is the portable form —
build the `IN (...)` clause with the exact count of `%s`. The `.replace`
above is just a readable way to build it; a plain f-string with the joined
placeholders is equally fine. Do NOT use `= ANY(%s)` — that is PG-only and
this app also runs SQLite in tests.)

### Step 2 — inject into shell context (`core/shell_context.py`)
In `shell_ctx()`'s returned dict, add:
```python
from modules.governance.data_service import bu_scope_detail
...
"bu_scope": bu_scope_detail(user),
```
Guard the import against circulars — if `shell_context` is imported very
early, do the import INSIDE the function (local import), matching how this
file already does lazy imports (it lazily imports `database`/`get_db` inside
`_license_status`). Wrap in try/except returning a safe default
`{"mode": "all", "bus": []}` so a governance-module failure never blanks the
whole shell.

### Step 3 — top-bar chip + dropdown (`base_shell.html`)
Find the top bar (search box + notification/theme buttons, ~line 800-880).
Add, before the theme toggle:
```html
{% if bu_scope and bu_scope.mode == 'scoped' %}
<div class="scope-chip" title="Your data is limited to this business unit and its sub-units">
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18M6 21V10M18 21V10M9 21V14h6v7M3 10l9-6 9 6"/></svg>
  <span>{{ bu_scope.root_name or 'Your unit' }}{% if bu_scope.descendant_count %} +{{ bu_scope.descendant_count }}{% endif %}</span>
</div>
{% endif %}
{% if bu_scope and bu_scope.bus | length > 1 %}
<select class="scope-filter" onchange="tiqSetBuFilter(this.value)" title="Focus on one sub-unit">
  <option value="">All my units</option>
  {% for b in bu_scope.bus %}<option value="{{ b.id }}">{{ b.name }}</option>{% endfor %}
</select>
{% endif %}
```
Add minimal CSS for `.scope-chip` (a subtle pill using existing tokens
`var(--surface2)`, `var(--muted)`; do NOT invent new colors) and `.scope-filter`
(reuse the existing select styling). Add the JS helper near the other shell
scripts:
```javascript
function tiqSetBuFilter(v){
  var u = new URL(window.location.href);
  if(v){ u.searchParams.set('bu', v); } else { u.searchParams.delete('bu'); }
  window.location.href = u.toString();
}
// Pre-select current ?bu= on load
(function(){
  var bu = new URLSearchParams(location.search).get('bu');
  if(bu){ var s=document.querySelector('.scope-filter'); if(s) s.value=bu; }
})();
```

### Step 4 — honor `?bu=` in the scoped list endpoints
For each already-scoped module list route (erm, orm, bcm, sentinel, grid, plus
SBU-02's task/evidence/rcsa/incidents), replace the direct
`scope = bu_scope_ids(user)` with a shared narrowing helper. Add to
`governance/data_service.py`:
```python
def effective_bu_scope(user: dict, requested_bu):
    """Intersect an optional ?bu= request with the user's allowed scope.
    - requested_bu None/blank -> the user's full scope (unchanged).
    - requested_bu in scope   -> narrow to [requested_bu].
    - requested_bu NOT in scope (or user unrestricted but bu given) ->
      narrow to [requested_bu] ONLY IF the bu is a real active BU; a scoped
      user requesting an out-of-scope bu is ignored (returns full scope) so
      they cannot escape their subtree."""
    allowed = bu_scope_ids(user)  # None => unrestricted
    try:
        rb = int(requested_bu) if requested_bu not in (None, "", "null") else None
    except (TypeError, ValueError):
        rb = None
    if rb is None:
        return allowed
    if allowed is None:
        return [rb]          # org-wide user drilling into one SBU
    if rb in allowed:
        return [rb]          # scoped user drilling into an allowed sub-unit
    return allowed           # out-of-scope request ignored (no escape)
```
Then in each route: `scope = effective_bu_scope(user, request.query_params.get("bu"))`
and pass `scope` where `bu_scope_ids(user)` currently goes. **Security-critical:
the `rb in allowed` check is the wall that stops a scoped user from typing
`?bu=<sibling>` to see another SBU.** Keep it.

### Step 5 — tests (`oneforall/tests/test_bu_filter.py`)
1. `test_effective_scope_narrows_for_org_wide` — `bu_scope_ids` None + `bu=5`
   → `[5]`.
2. `test_effective_scope_narrows_within_allowed` — allowed `[1,2,3]` + `bu=2`
   → `[2]`.
3. `test_effective_scope_ignores_out_of_scope` — allowed `[1,2]` + `bu=9`
   → `[1,2]` (NOT `[9]`; the escape attempt is refused).
4. `test_effective_scope_blank_returns_full` — allowed `[1,2]` + `bu=""`
   → `[1,2]`.
5. `test_scope_detail_labels` — a user assigned to a parent BU with 2 children
   → `bu_scope_detail` returns `mode='scoped'`, `descendant_count == 2`,
   `root_name` = the parent's name.

## Edge cases a weaker model would miss

- **`?bu=` must never let a scoped user escape their subtree.** The
  `rb in allowed` gate in `effective_bu_scope` is the whole security point. A
  naive implementation that trusts the query param (`return [rb]`
  unconditionally) turns the drill-down into an IDOR that defeats SBU-02. Test
  #3 exists specifically to catch this.
- **Org-wide users CAN use `?bu=` to focus** (that is the group-monitor
  drill-down) — that is allowed and correct (`allowed is None -> [rb]`),
  because they were entitled to everything anyway; focusing is not escalation.
- **The shell context runs on EVERY page.** `bu_scope_detail` does one small
  query; wrap the whole thing so a failure returns the safe "all" default and
  never blanks the shell. Do not let a governance import error take down every
  page.
- **Local import to avoid circulars.** `core/shell_context.py` is imported
  broadly; importing `modules.governance.data_service` at module top can
  create an import cycle. Import inside `shell_ctx()` (the file already uses
  this lazy pattern for `database`).
- **Do not add a scope chip for org-wide users.** Showing "All units" on every
  super-admin page is noise. Only render the chip when `mode == 'scoped'`. The
  dropdown only renders when the user actually has >1 BU to choose between.
- **Preserve other query params** when setting `?bu=` (the `URL`/
  `searchParams` approach does this; do NOT rebuild the URL by string
  concatenation, which would drop existing filters like `?status=open`).
- **Reuse existing color tokens.** No new palette — the chip uses
  `var(--surface2)`/`var(--muted)`, matching the no-new-colors constraint used
  across this repo's recent UI work.

## Acceptance criteria (verifiable)

1. Log in as a user assigned to SBU "EcoCash" (a leaf): the top bar shows a
   "EcoCash" scope chip; no drill-down dropdown appears (only one unit).
2. Log in as a user assigned to a parent SBU with children: the chip shows
   "Parent +N"; a dropdown lists the parent + each child; choosing a child
   reloads with `?bu=<child>` and the ERM/ORM/etc. lists now show only that
   child's (and NULL) records.
3. As that scoped user, manually edit the URL to `?bu=<a-sibling-not-in-scope>`:
   the lists do NOT change to the sibling's data (the request is ignored) —
   proving no escape.
4. As a super-admin: no scope chip (org-wide); but `/erm/?bu=<id>` DOES focus
   the register to that BU (group drill-down works for entitled users).
5. `python -m pytest tests/test_bu_filter.py` passes; full suite unaffected.
6. Choosing "All my units" clears `?bu=` and restores the full scoped view,
   preserving any other active filters in the URL.
```
