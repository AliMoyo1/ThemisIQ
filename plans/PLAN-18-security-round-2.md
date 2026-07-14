# PLAN-18: Security round 2 — org-enforced MFA, SBU data scoping, upload content verification

## Goal

The 8-phase hardening round closed the classic web vulns (ZAP clean,
CodeQL clean). The three highest-leverage gaps that REMAIN, each verified
against current code:

1. **MFA is opt-in per user** (`routes_auth.py:418` logs `mfa_enabled`;
   no enforcement path exists). A GRC platform selling to compliance
   officers must let an org admin REQUIRE MFA — at minimum for admin
   roles — or fail its own customers' audits.
2. **SBU access control is unenforced.** `business_units` and
   `users.business_unit_id` exist (T1.1 / PLAN-05 groundwork), but every
   module list endpoint returns ALL tenant rows regardless of the user's
   BU. For customers whose SBUs operate independently, one SBU's analysts
   can read another SBU's risks, breaches, and audits. This is the
   multi-tenant story's missing interior wall.
3. **Uploads trust the declared extension/MIME** (`evidence/routes.py:
   153-169` checks `Path(name).suffix` and `file.content_type` — both
   attacker-controlled). Add magic-byte verification so a renamed
   executable cannot enter the evidence vault.

## Exact files to touch

1. `oneforall/database.py` — 1 column migration (`users.mfa_secret`
   already exists — VERIFY by grepping; add none if present) + settings
   seeds are not needed (settings is key/value)
2. `oneforall/core/rbac.py` — 1 new capability + BU-scope helper
3. `oneforall/core/middleware.py` — BU-scope context helper
4. `oneforall/modules/launcher/routes_auth.py` — MFA enforcement gate
5. `oneforall/modules/launcher/routes_admin.py` — org security settings
   endpoints (require-MFA toggle, per-role)
6. Module list endpoints (ERM risks, GRID audits, Sentinel ropa/dpias/
   breaches, BCM plans/bia, ORM events) — BU filter injection
7. `oneforall/modules/evidence/routes.py` — magic-byte sniffing
8. `oneforall/tests/test_security_round2.py`

## Step-by-step order

### Part A — Org-enforced MFA

**A1.** Storage: use the existing `settings` table (key/value, per-tenant).
Keys: `security.require_mfa` = `'off' | 'admins' | 'all'` (default `'off'`).

**A2.** Admin endpoints in `routes_admin.py` (copy the guard style of the
neighboring settings endpoints; capability `platform.manage_settings`):
`GET/PUT /admin/api/security-settings` reading/writing that key with
`validate_choice`.

**A3.** Enforcement gate in the LOGIN flow (`routes_auth.py`): after
successful password verification, READ the whole login handler first.
Where it currently branches on the user having MFA enabled
(`mfa_pending` session path), add: if the org policy is `'all'` (or
`'admins'` and the user holds `super_admin` or any `*_manager`-tier
role — reuse `has_role`), and the user has NO MFA secret yet, do NOT
issue a full session: issue the existing `mfa_pending`-style session and
redirect to the EXISTING MFA setup page (grep `mfa/setup` route) with a
banner "Your organisation requires two-factor authentication". The setup
flow already exists — this plan only forces entry into it.

**A4.** Enforcement on session use is NOT needed (setup completes →
normal session). But block the "skip/cancel" path on the setup page when
policy demands MFA (READ the setup template; hide/disable the skip
control server-side via a context flag, never client-side only).

### Part B — SBU (business unit) data scoping

**B1.** Model: `users.business_unit_id` exists via PLAN-05's migration
list — VERIFY with `grep "business_unit_id" oneforall/database.py`
against the `users` entry; if absent (PLAN-05 not yet executed), add
`("users", "business_unit_id", "INTEGER")` to `_COLUMN_MIGRATIONS` here.

**B2.** Policy: a user WITH a `business_unit_id` sees only rows whose
`business_unit_id` is their BU or a DESCENDANT of it (SBU heads see
their subtree), plus rows with NULL BU (shared/tenant-wide records).
Users with NULL BU (group/central staff, CGRCO, super_admin) see
everything. This "NULL = shared" rule is what lets central group
management and independent SBUs coexist.

**B3.** Helper in `modules/governance/data_service.py`:

```python
def bu_scope_ids(user) -> "list[int] | None":
    """Return the BU-id subtree the user is confined to, or None for
    unrestricted (no BU assigned, or super admin)."""
```

Super admin / NULL BU → None. Else walk `business_units.parent_id`
children breadth-first (reuse the tree logic in
`get_business_unit_tree()`), return the id list (self + descendants).

**B4.** Apply to list endpoints. Pattern per endpoint (do NOT bulk-regex;
edit each by hand): compute `scope = bu_scope_ids(request.state.user)`;
when `scope is not None`, append
`AND (business_unit_id IN (…placeholders…) OR business_unit_id IS NULL)`
to the WHERE. Endpoints (verify each table has the column via the
PLAN-05/T1.1 migration list before touching):
- ERM `list_enterprise_risks` + dashboard stats
- GRID audits list
- Sentinel ropa, dpias, breaches lists
- BCM plans + bia lists
- ORM events list
Detail endpoints get the same guard (404 when out of scope) — a list
filter without a detail guard is IDOR, not security.

**B5.** Admin UI hook: the existing user-management page gets a BU
dropdown (populated from `/governance/api/business-units`) writing
`users.business_unit_id`. READ `routes_admin.py`'s user-update endpoint
and add the field with `validate_int`.

### Part C — Upload content verification

**C1.** In `evidence/routes.py`, next to the existing extension check
(line ~153), add a magic-byte table (no new dependency):

```python
_MAGIC = {
    ".pdf": [b"%PDF"], ".png": [b"\x89PNG"], ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"], ".gif": [b"GIF8"],
    ".zip": [b"PK\x03\x04"], ".docx": [b"PK\x03\x04"],
    ".xlsx": [b"PK\x03\x04"], ".pptx": [b"PK\x03\x04"],
}
```

After reading the first 8 bytes of the uploaded content: if the
extension is in `_MAGIC` and none of its signatures match → 400
"File content does not match its extension". Extensions not in the
table (txt, csv, md) skip the check. READ how the route buffers the
file first — if it streams to disk, sniff the first chunk before
writing, or reopen and check before committing the DB row.

**C2.** Confirm the existing allowlist rejects executables
(`.exe .js .html .svg` must NOT be uploadable — grep the allowed set;
if `.svg` or `.html` is allowed today, remove them: both are XSS vectors
when served inline). Confirm the download route serves with
`Content-Disposition: attachment` (grep it; add if missing).

### Part D — Tests + verify

`tests/test_security_round2.py`:
1. MFA policy: set `security.require_mfa='all'` in settings, simulate
   the login branch decision function (extract the policy check into a
   pure helper `mfa_required_for(user, policy)` so it is unit-testable);
   assert admins+users require, `'admins'` requires only admin roles,
   `'off'` requires none.
2. BU scope: build 3 BUs (root, child A, child B), a user in A;
   `bu_scope_ids` returns [A] (+descendants); a NULL-BU user returns
   None. Insert 2 risks (one in A, one in B) and assert the ERM list
   with the scope filter returns only A + NULL rows.
3. Upload sniff: bytes `MZ\x90` named `evil.pdf` rejected; real
   `%PDF-1.4` accepted.
Live pass: enforce-MFA on, log in as a non-MFA user → forced into
setup; assign a test user to a BU → their register hides other-BU
rows; upload a renamed .exe → clean 400. Clean up test rows/users.

## Edge cases a weaker model would miss

- **Do not lock out existing sessions when the MFA policy flips** —
  enforcement happens at LOGIN only. Killing live sessions mid-day
  bricks the org; note this in the settings UI copy ("applies at next
  sign-in").
- **The super admin must never be lockable-out by policy misconfig**:
  if policy is `'all'` and the super admin has no MFA, they are forced
  into setup like everyone — that is FINE (setup works), but the
  policy-read must fail-open to `'off'` on a broken settings value,
  never fail-closed into an unreachable login.
- **`mfa_pending` sessions have a 600s TTL** (core/auth.py:53) — the
  forced-setup flow rides that same short session; setup must complete
  within it, which it does today. Do not extend the TTL.
- **BU scope must include NULL rows** — filtering `business_unit_id IN
  (…)` alone hides every pre-existing record (all NULL) from every
  BU-assigned user, which reads as data loss. The `OR … IS NULL` is
  load-bearing.
- **Descendants matter**: an SBU head assigned to a parent BU must see
  child-BU rows. `bu_scope_ids` walks DOWN, never up.
- **The detail-endpoint guard returns 404, not 403** — 403 confirms the
  record exists (enumeration oracle).
- **docx/xlsx/zip share the PK signature** — the magic table maps
  many-to-one on purpose; do not try to distinguish OOXML flavors by
  content (that requires unzipping — out of scope).
- **Do not sniff files already in the vault** — this is
  create-time-only; a retroactive scan is a separate task.
- **RLS/tenant isolation is untouched** — BU scoping is an app-level
  layer INSIDE a tenant; never mix it into the RLS/org logic in
  database.py.

## Acceptance criteria

1. All unit tests pass; full suite green.
2. Live: `'admins'` policy forces MFA setup for a super admin login but
   not an `employee` login; `'off'` restores normal login.
3. A BU-assigned user's ERM/GRID/Sentinel lists exclude other-BU rows
   but include NULL-BU rows; direct GET of an other-BU detail id → 404.
4. Renamed executable rejected with 400; genuine PDF/DOCX still upload;
   downloads carry `Content-Disposition: attachment`.
5. `.svg`/`.html` are not accepted as evidence uploads.
