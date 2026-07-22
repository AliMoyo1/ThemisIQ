# PLAN-SBU-01: User → Business Unit assignment UI (activate the dead capability)

## Leverage rank: 1 of 4 (DO FIRST). Without this, the entire multi-SBU
## scoping mechanism is inert — no user is ever confined to an SBU because
## nothing can set `users.business_unit_id` from the UI.

## Goal / feature

Give admins a working UI to assign a user to a business unit (SBU). Today:
- `users.business_unit_id` exists (added via `_COLUMN_MIGRATIONS` in
  `oneforall/database.py`, ~line 4087) and `bu_scope_ids(user)` in
  `oneforall/modules/governance/data_service.py:30` correctly computes
  "this user's BU + all descendant BUs".
- BUT there is NO UI to set `business_unit_id` on a user. The only writer is
  `PATCH /api/admin/users/{uid}` (`routes_admin.py:340`), which does accept
  a `business_unit_id` field — but the Admin→Users edit drawer JS never sends
  it (`admin_users.html:846` sends only `{full_name, email}`), so it is
  unreachable. Result: every user has `business_unit_id = NULL` forever, and
  because `bu_scope_ids` treats NULL as "unrestricted", nobody is ever scoped.
- The `governance.bu.assign` capability (`core/rbac.py:131`, granted to
  `SUPER_ADMIN, GRC_OFFICER, COMPLIANCE_MGR`) is computed into a
  `can_assign_bu` template flag (`governance/routes.py:42`) but is read
  NOWHERE and gates NO endpoint. It is completely dead.

This plan builds a **"People" tab in the Governance module** (which
GRC_OFFICER and COMPLIANCE_MGR can already reach, and which already owns the
BU tree) where each user has an inline BU dropdown, backed by a new endpoint
gated by the real `governance.bu.assign` capability. It ALSO adds a
read-only Business Unit column + editable dropdown to the super-admin
Admin→Users edit drawer as a convenience.

**Why the Governance module and not just Admin→Users:** the Admin→Users page
is gated `platform.manage_users` = `{SUPER_ADMIN}` only (`rbac.py:119`), so a
GRC_OFFICER (the "Econet group monitor" persona) cannot even open it. BU
assignment must live somewhere the intended personas can reach. The
Governance SPA is gated `governance.entities.view` (all roles) with the
assignment control itself gated on `can_assign_bu`. This finally activates
the capability for the persona it was designed for.

## Exact files to touch

1. `oneforall/modules/governance/data_service.py` — add `list_assignable_users()`
   and `assign_user_business_unit(uid, bu_id)`.
2. `oneforall/modules/governance/routes.py` — add
   `GET /governance/api/users` (gated `governance.bu.assign`) and
   `PATCH /governance/api/users/{uid}/business-unit` (gated
   `governance.bu.assign`).
3. `oneforall/modules/governance/templates/index.html` — add a "People" tab
   (nav button + `tab-view` panel + JS loader/renderer/assign handler),
   rendered only when `can_assign_bu`.
4. `oneforall/modules/launcher/_route_helpers.py` — in `_render_admin_users`,
   fetch the active BU list and each user's `business_unit_id` +
   `business_unit_name`, pass `business_units` and `can_assign_bu` into ctx.
5. `oneforall/modules/launcher/templates/admin_users.html` — add a BU
   `<select>` to the Edit drawer, populate it on open, include
   `business_unit_id` in the PATCH body, and show the current BU in the row.
6. `oneforall/tests/test_bu_assignment.py` — NEW test file (see Step 7).

## Step-by-step order

### Step 1 — data_service helpers (`governance/data_service.py`)

Add at the end of the "BU SCOPE HELPER" / business-units section
(after `_is_descendant`, ~line 202):

```python
def list_assignable_users() -> list[dict]:
    """Active users in the current tenant schema with their current BU.
    Used by the Governance 'People' tab to assign users to SBUs."""
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT u.id, u.username, u.full_name, u.email, "
            "u.business_unit_id, bu.name AS business_unit_name "
            "FROM users u "
            "LEFT JOIN business_units bu ON bu.id = u.business_unit_id "
            "WHERE u.is_active = 1 "
            "ORDER BY u.full_name NULLS LAST, u.username"
        ).fetchall())
    finally:
        db.close()


def assign_user_business_unit(uid: int, bu_id: "int | None") -> bool:
    """Set (or clear, when bu_id is None) a user's business_unit_id.
    Validates the BU exists and is active when non-null. Returns False if
    the target BU id is invalid so the route can 400."""
    db = get_db()
    try:
        if bu_id is not None:
            ok = db.execute(
                "SELECT 1 FROM business_units WHERE id=%s AND is_active=1", (bu_id,)
            ).fetchone()
            if not ok:
                return False
        db.execute(
            "UPDATE users SET business_unit_id=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
            (bu_id, uid),
        )
        db.commit()
        return True
    finally:
        db.close()
```

### Step 2 — routes (`governance/routes.py`)

Add after the business-units endpoints block (after `api_bu_delete`, ~line 107).
NOTE: import `log_audit` and `_uid` pattern — check the top of the file; if
`log_audit` is not imported, add `from core.middleware import log_audit`.

```python
# ── People / BU assignment ───────────────────────────────────────────────────

@router.get("/api/users")
@require_capability("governance.bu.assign")
async def api_assignable_users(request: Request):
    return JSONResponse(ds.list_assignable_users())


@router.patch("/api/users/{uid}/business-unit")
@require_capability("governance.bu.assign")
async def api_assign_user_bu(request: Request, uid: int):
    body = await _json_body(request)
    raw = body.get("business_unit_id")
    bu_id = int(raw) if raw not in (None, "", "null") else None
    ok = ds.assign_user_business_unit(uid, bu_id)
    if not ok:
        raise HTTPException(400, "Invalid or inactive business unit")
    from core.middleware import log_audit
    log_audit(request.state.user, "governance",
              f"Assigned user #{uid} to business_unit {bu_id}", "user", uid)
    return JSONResponse({"ok": True, "business_unit_id": bu_id})
```

### Step 3 — Governance SPA "People" tab (`governance/templates/index.html`)

3a. Add the tab button in the `.gov-tabs` block (after the "Regulatory Inbox"
button at line ~108), gated on `can_assign_bu`:
```html
{% if can_assign_bu %}
<button class="gov-tab" data-tab="people" onclick="govSwitchTab('people')">People</button>
{% endif %}
```

3b. Add the tab-view panel after the last `tab-view` (`tab-reg`, ~line 206),
gated on `can_assign_bu`:
```html
{% if can_assign_bu %}
<div class="tab-view" id="tab-people">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    <div style="font-size:13px;color:var(--muted)">Assign each user to a business unit. Users see only their unit and its sub-units; leave blank for org-wide access.</div>
  </div>
  <table class="gov-table" id="peopleTable">
    <thead><tr><th>User</th><th>Email</th><th>Business Unit</th></tr></thead>
    <tbody id="peopleBody"><tr><td colspan="3" style="text-align:center;color:var(--muted);padding:24px">Loading…</td></tr></tbody>
  </table>
</div>
{% endif %}
```

3c. In the page script, find `govSwitchTab(tab)` (~line 241) and make it
lazy-load People on first switch. Add a loader + renderer + assign handler.
Mirror the existing fetch/escape helpers already in this file (there is an
`esc()`-style helper and a `govLoadBu()` pattern — reuse them; do NOT invent
new fetch wrappers). Concretely add:

```javascript
var _buOptionsCache = null;
async function govBuOptions(selectedId){
  if(!_buOptionsCache){
    var r = await fetch('/governance/api/business-units');
    _buOptionsCache = r.ok ? await r.json() : [];
  }
  var opts = '<option value="">— Org-wide (no unit) —</option>';
  _buOptionsCache.forEach(function(b){
    opts += '<option value="'+b.id+'"'+(b.id===selectedId?' selected':'')+'>'+esc(b.name)+'</option>';
  });
  return opts;
}
async function govLoadPeople(){
  var body = document.getElementById('peopleBody');
  try{
    var r = await fetch('/governance/api/users');
    var users = r.ok ? await r.json() : [];
    if(!users.length){ body.innerHTML='<tr><td colspan="3" style="text-align:center;color:var(--muted);padding:24px">No users</td></tr>'; return; }
    var rows = [];
    for(var i=0;i<users.length;i++){
      var u = users[i];
      var sel = await govBuOptions(u.business_unit_id);
      rows.push('<tr><td><strong>'+esc(u.full_name||u.username)+'</strong><div style="font-size:11px;color:var(--muted)">@'+esc(u.username)+'</div></td>'+
        '<td style="font-size:12px;color:var(--muted)">'+esc(u.email||'')+'</td>'+
        '<td><select class="form-input" style="max-width:240px" onchange="govAssignBu('+u.id+', this.value)">'+sel+'</select></td></tr>');
    }
    body.innerHTML = rows.join('');
  }catch(e){ body.innerHTML='<tr><td colspan="3" style="text-align:center;color:var(--red)">Failed to load</td></tr>'; }
}
async function govAssignBu(uid, val){
  try{
    var r = await fetch('/governance/api/users/'+uid+'/business-unit', {
      method:'PATCH', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({business_unit_id: val===''? null : parseInt(val)})
    });
    if(!r.ok){ var j={}; try{j=await r.json();}catch(_){} if(typeof showToast==='function') showToast(j.detail||'Assignment failed','error'); return; }
    if(typeof showToast==='function') showToast('Business unit updated');
  }catch(e){ if(typeof showToast==='function') showToast('Network error','error'); }
}
```
Then in `govSwitchTab`, after the existing tab-activation lines, add:
```javascript
if(tab==='people' && !window._peopleLoaded){ window._peopleLoaded=true; govLoadPeople(); }
```

### Step 4 — Admin→Users context (`launcher/_route_helpers.py`)

In `_render_admin_users`, the per-user SELECT (lines 74-89) currently does not
fetch `business_unit_id`/name. Add them to BOTH branches' SELECT lists:
`u.business_unit_id, (SELECT name FROM business_units WHERE id=u.business_unit_id) AS business_unit_name`.

After building `rows`, fetch the active BU list once and add to ctx:
```python
try:
    bu_rows = db.execute(
        "SELECT id, name FROM business_units WHERE is_active=1 ORDER BY name"
    ).fetchall()
    business_units = [{"id": b["id"], "name": b["name"]} for b in bu_rows]
except Exception:
    business_units = []
```
(Wrap in try/except: the column/table may not exist on a very old DB before
migrations run. Do this INSIDE the existing `try:`/`finally:` that owns `db`,
BEFORE `db.close()`.)

Then in the `ctx.update({...})` block (line 137) add:
```python
"business_units": business_units,
"can_assign_bu": has_capability(user, "governance.bu.assign"),
```
`has_capability` — confirm it is imported in this helper file; if not,
`from core.rbac import has_capability`.

### Step 5 — Admin→Users edit drawer (`launcher/templates/admin_users.html`)

5a. Add a BU field to the Edit drawer, after the Email form-group (~line 635),
gated on `can_assign_bu`:
```html
{% if can_assign_bu %}
<div class="form-group" style="margin-top:14px;">
  <label class="form-label">Business Unit</label>
  <select id="drawerBusinessUnit" class="form-input" style="width:100%; box-sizing:border-box;">
    <option value="">— Org-wide (no unit) —</option>
    {% for b in business_units %}<option value="{{ b.id }}">{{ b.name }}</option>{% endfor %}
  </select>
</div>
{% endif %}
```

5b. On the Edit button (`au-edit-btn`, ~line 448), add a data attribute
carrying the current BU id:
```html
data-bu="{{ u.business_unit_id or '' }}"
```
And in `openEditDrawerBtn(btn)` (~line 772) pass `btn.dataset.bu`, extending
`openEditDrawer(...)` to accept a `buId` argument and do:
```javascript
var buSel = document.getElementById('drawerBusinessUnit');
if(buSel) buSel.value = buId || '';
```

5c. In `saveEditDrawer()` (~line 822), include BU in the PATCH body:
```javascript
var buSel = document.getElementById('drawerBusinessUnit');
var payload = { full_name: fullName, email: email };
if(buSel) payload.business_unit_id = buSel.value === '' ? null : parseInt(buSel.value);
```
and pass `payload` as the body instead of the current `{full_name, email}`.

5d. (Optional, nice-to-have) Add a "Unit" column to the users table showing
`u.business_unit_name or '—'`, and update it in-place after save using the
returned `business_unit_id`. Skip if it complicates the row layout.

### Step 6 — verify manually / py_compile
- `python -m py_compile` on the two touched .py files.
- Extract the `<script>` blocks from both touched templates and run
  `node --check` after stripping `{{ }}`/`{% %}` (replace with `1`/``), to
  catch JS syntax errors the Jinja hides.
- Jinja parse: load both templates via a `jinja2.Environment`.

### Step 7 — tests (`oneforall/tests/test_bu_assignment.py`)
Using the `test_db` fixture (fresh SQLite per test), write:
1. `test_assign_and_clear` — create two BUs (parent + child) and a user via
   raw SQL; call `assign_user_business_unit(uid, child_id)`; assert the user's
   `business_unit_id`; call with `None`; assert it clears.
2. `test_assign_rejects_unknown_bu` — `assign_user_business_unit(uid, 99999)`
   returns `False` and does NOT change the row.
3. `test_assign_rejects_inactive_bu` — set a BU `is_active=0`; assigning to it
   returns `False`.
4. `test_bu_scope_after_assignment` — assign a user to the PARENT BU; call
   `bu_scope_ids({"business_unit_id": parent_id, "is_super_admin": 0})`; assert
   the returned list contains BOTH parent and child ids (rollup works
   end-to-end once assignment is wired). This is the acceptance-linking test.
5. `test_list_assignable_users_includes_bu_name` — after assigning, confirm
   `list_assignable_users()` returns the row with the correct
   `business_unit_name`.

Then run the FULL suite (`python -m pytest tests/`) — confirm no regressions
against the current passing count (176 at time of writing).

## Edge cases a weaker model would miss

- **NULL means unrestricted, and that is intentional.** Do NOT change
  `bu_scope_ids`. A user with no BU sees everything — that is the correct
  default for org-wide roles (e.g. the group CGRCO). Clearing a BU (setting
  NULL) is a valid, first-class action, hence the "— Org-wide (no unit) —"
  option, not a disabled/blank state.
- **`governance.bu.assign` gate, not `governance.entities.manage`.** Use the
  narrower, purpose-built capability so the control appears for exactly
  `{SUPER_ADMIN, GRC_OFFICER, COMPLIANCE_MGR}`. Do not reuse `entities.manage`
  (that set differs — it includes RISK_OWNER, who should not reassign people).
- **The Admin→Users page stays super-admin-only.** Do not loosen
  `platform.manage_users`. The GRC-officer path is the Governance People tab,
  NOT the admin page. Adding the BU control to the admin drawer is a
  convenience for super-admins only; it must be gated on `can_assign_bu`
  (which is true for super-admin anyway) so it does not render for a context
  where the ctx var is missing.
- **`business_units` lives in the tenant schema, not `public`.** All these
  queries run in the caller's current tenant search_path (set by
  `tenant_context_middleware`). Do NOT add an `org_id` filter to
  `business_units` — it has no such column; isolation is by schema. A
  super-admin operating in the public/default schema will see the default
  org's BUs; that is correct for this plan's scope. (Cross-org BU management
  by super-admins from a single screen is explicitly OUT of scope.)
- **The New User (create) flow is intentionally NOT changed here.** New users
  keep `business_unit_id = NULL` (org-wide) until assigned. Adding BU to the
  create-user Form POST is a separate, smaller follow-up — do not bundle it,
  because the create modal's org selector (super-admin only) interacts with
  per-tenant BU lists in a way that needs its own thought.
- **`onchange` fires on every dropdown change including mis-clicks.** That is
  acceptable (each change is an intentional, audited, reversible assignment).
  Do NOT add a separate "Save" button per row — inline-save is the pattern and
  keeps the tab simple. But DO show a toast on success/failure so the user
  gets feedback.
- **`esc()` / `showToast()` may or may not be globally defined** in the
  governance template. Confirm both exist (grep the file); if `esc` does not
  exist, add a 1-line `function esc(s){var d=document.createElement('div');d.textContent=String(s==null?'':s);return d.innerHTML;}`.
- **Audit logging** must record who reassigned whom (compliance requirement
  for a governance action). The route already calls `log_audit`; ensure the
  import resolves.

## Acceptance criteria (verifiable)

1. As a super-admin: open Governance → the "People" tab is visible; it lists
   active users each with a BU dropdown; changing a dropdown shows a success
   toast and persists (reload the tab → the new BU is still selected).
2. Create a temp user with role `grc_officer` (NOT super-admin); log in as
   them; open Governance → the "People" tab IS visible and functional; open
   `/admin/users` → still 403/redirect (page stays super-admin-only). This
   proves `governance.bu.assign` is now genuinely wired for the intended
   persona.
3. Assign a test user to a child SBU, then (via a direct DB read or the ERM
   register while logged in as that user) confirm they now see only that
   SBU's + descendants' risks — i.e. `bu_scope_ids` returns a non-None list
   for them where it returned None before. This proves the whole scoping
   mechanism is now reachable.
4. In the super-admin Admin→Users edit drawer, the Business Unit dropdown
   shows the user's current unit, and Save persists a change (verify via
   reopen).
5. `python -m pytest tests/test_bu_assignment.py` — all 5 new tests pass;
   full suite shows no regressions.
6. Assigning to a non-existent or inactive BU id via the API returns HTTP 400
   and leaves the row unchanged.
```
