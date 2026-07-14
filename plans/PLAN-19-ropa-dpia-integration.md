# PLAN-19: RoPA ↔ DPIA integration — link, prefill, and drift indicator

## Goal

RoPA records and DPIAs describe the same processing activity but live as
disconnected forms: a user who filled a RoPA retypes everything into the
DPIA. The schema already anticipates the link — `sentinel_ropa.dpia_id`
and `dpia_required` exist (database.py:2604-2605) but nothing populates
them, and the DPIA list UI already renders a "Linked RoPA" column that is
always empty.

After this plan:
1. A "Create DPIA" action on any RoPA row opens the DPIA form PREFILLED
   from the RoPA (mapping below) and links both records on save.
2. An existing DPIA can be linked to a RoPA from the DPIA form (dropdown
   of unlinked RoPAs), which also backfills empty DPIA fields.
3. The link is visible and navigable in both directions, and a drift
   note appears on the DPIA when the source RoPA changed after the DPIA
   was last updated.

## Field mapping (RoPA → DPIA)

| sentinel_ropa | sentinel_dpias | Note |
|---|---|---|
| processing_name | title | prefix `DPIA — ` |
| department | department | |
| owner | owner | |
| purpose | description | seed text |
| legal_basis | legal_basis | column added by migration — verify present |
| data_categories | data_categories | |
| special_categories | special_categories | ALSO `special_cats` exists from a migration — READ which one the DPIA form actually uses and map to THAT |
| data_subjects | data_subjects | |
| retention_period | retention | migration column |
| international_transfers | intl_transfer | migration column |
| recipients | processors | migration column |
| regulation | regulation | |

Prefill NEVER overwrites a non-empty DPIA field (backfill semantics).

## Exact files to touch

1. `oneforall/database.py` — 1 migration: `("sentinel_dpias", "ropa_id",
   "INTEGER")` in `_COLUMN_MIGRATIONS`
2. `oneforall/modules/sentinel/data_service.py` — `create_dpia_from_ropa`,
   `link_dpia_to_ropa`, and include `ropa` join data in DPIA detail/list
3. `oneforall/modules/sentinel/routes.py` — 2 endpoints
4. `oneforall/modules/sentinel/templates/index.html` — RoPA row action,
   DPIA form dropdown, linked chips, drift note

## Step-by-step order

### Step 1 — Migration

Add the `ropa_id` column entry. (No FK — migration-added columns follow
the bare-INTEGER convention. `sentinel_ropa.dpia_id` already exists for
the reverse direction.)

### Step 2 — Data service

READ the existing `create_dpia` and `get_dpia` functions first and their
exact column list. Then add:

**`create_dpia_from_ropa(ropa_id, created_by)`** — fetch the RoPA row
(404-> None), build a dict via the mapping table, generate the ref_number
the same way `create_dpia` does (READ how; reuse the same helper),
`status='draft'`, `ropa_id=ropa_id`. Insert via the existing create path
if it accepts a dict, else mirror its INSERT. Then
`UPDATE sentinel_ropa SET dpia_id=%s, dpia_required=1 WHERE id=%s`.
One commit for both statements. Return the new id.

**`link_dpia_to_ropa(dpia_id, ropa_id)`** — validate both exist; refuse
(return False) if the RoPA already has a different `dpia_id` linked.
Backfill: for each mapping pair, if the DPIA's field is NULL/empty and
the RoPA's is not, UPDATE it. Set `sentinel_dpias.ropa_id` and
`sentinel_ropa.dpia_id`. One commit.

**DPIA list/detail enrichment** — add
`LEFT JOIN sentinel_ropa r ON r.id = d.ropa_id` exposing
`r.ref_number AS ropa_ref, r.processing_name AS ropa_name,
r.updated_at AS ropa_updated_at`. READ the current list SQL first (it
may alias the DPIA table differently).

### Step 3 — Endpoints

In `sentinel/routes.py`, next to the existing DPIA endpoints, matching
their exact decorator/capability (`sentinel.dpia.manage`):

- `POST /api/ropa/{ropa_id}/create-dpia` → 404 if RoPA missing, 409 if
  it already has a linked DPIA, else `{id}` of the new draft.
- `POST /api/dpias/{dpia_id}/link-ropa` body `{ropa_id}` → 409 when the
  RoPA is already claimed, `{ok:true}` otherwise.

### Step 4 — UI

READ the Sentinel SPA's RoPA table renderer and DPIA form builder first
(grep `ropa` and `dpia` render functions in
`modules/sentinel/templates/index.html`).

- **RoPA row action**: a "Create DPIA" button per row. If
  `row.dpia_id` is set, render a link chip (`DPIA-…`) that opens the
  DPIA instead. On click → POST create-dpia → open the DPIA edit form
  for the returned id (the SPA already has an open-DPIA-editor function
  — find and call it).
- **DPIA form (Basics tab)**: a "Linked RoPA" select listing RoPAs with
  no dpia_id (fetch the existing RoPA list endpoint, filter client-side)
  plus the currently linked one; on change → POST link-ropa → toast +
  re-fetch the DPIA (backfilled fields appear).
- **DPIA list**: the existing "Linked RoPA" column now renders
  `ropa_ref` as a chip.
- **Drift note**: in the DPIA editor, when
  `ropa_updated_at > dpia.updated_at`, show a small banner: "The linked
  RoPA changed after this DPIA was last edited — review for drift." with
  a "Refill empty fields" button calling link-ropa again (idempotent
  backfill).

### Step 5 — Tests + verify

`tests/test_ropa_dpia_link.py`:
1. Create RoPA (direct insert with mapped fields populated) →
   `create_dpia_from_ropa` → DPIA fields equal mapping; RoPA.dpia_id
   set; DPIA.ropa_id set.
2. Second `create_dpia_from_ropa` on the same RoPA → refused.
3. `link_dpia_to_ropa` backfill: DPIA with empty department + non-empty
   title → after link, department filled, title UNCHANGED.
Cleanup rows. Then full pytest + live pass: RoPA row → Create DPIA →
form opens prefilled → save → both lists show the chip → edit the RoPA
→ reopen DPIA → drift banner appears.

## Edge cases a weaker model would miss

- **Two competing special-categories columns** exist on sentinel_dpias
  (`special_categories` from CREATE, `special_cats` from a later
  migration, database.py ~3489). The DPIA FORM decides which is live —
  read the form's save payload and map to that one; writing the dead
  column looks successful but shows nothing in the UI.
- **Backfill, never overwrite**: `link_dpia_to_ropa` on a hand-edited
  DPIA must not clobber the analyst's text. Empty means
  NULL or `''` after strip — check both.
- **Ref number generation must go through the existing helper** — DPIA
  refs look like `DPIA-20260709-T20FZ`; a hand-rolled format breaks
  any downstream parsing/uniqueness assumptions.
- **The 409 path needs a UI message**, not a silent failure — the RoPA
  "Create DPIA" button must flip to the chip state after success, and
  show the existing-link toast on 409 (row may be stale).
- **updated_at comparison is string-based** — both columns share the
  same format per engine, so lexicographic compare works; do NOT
  date-parse (PG timestamps vs SQLite strings differ).
- **Deleting a DPIA must clear `sentinel_ropa.dpia_id`** — READ the
  existing delete_dpia function and add the clearing UPDATE; otherwise
  the RoPA points at a ghost and blocks creating a fresh DPIA forever.
- **Tenant scoping is automatic** via get_db() — do not add org logic;
  but if PLAN-18's BU scoping has landed, the RoPA dropdown in the DPIA
  form must reuse the same scoped list endpoint (it does, by fetching
  the standard list API).

## Acceptance criteria

1. All 3 tests pass; full suite green.
2. Live: RoPA → Create DPIA opens a prefilled draft; both directions
   navigable via chips; second create attempt blocked with a clear
   message.
3. Backfill fills only empty fields (verified by pre-editing one field).
4. Drift banner appears after editing the linked RoPA, and "Refill empty
   fields" works.
5. Deleting the DPIA frees the RoPA to create a new one.
