# DPIA form: what a person types is stored and shown again (22 Oct 2026, CAT)

Worktree `suspicious-swartz-8c47fe`, branch `claude/suspicious-swartz-8c47fe`. Nothing is committed or pushed (the brief said not to).
Started by the report exports session (ledger item O12 in `PLAN_report_exports_2026-10-21.md`, worktree `sad-albattani-5255ea`).
Decisions below are chat confirmations from the owner's brief and messages, not sign-off.

## 1. The defect

The Privacy DPIA drawer (`snSaveDpiaDrawer`) and the generic DPIA modal (`modalDefs.dpia`) in `modules/sentinel/templates/index.html`
send `description`, `mitigations`, `assessor` and `due_date`. `create_dpia` and `update_dpia` (`modules/sentinel/data_service.py`) store
only the keys in `_DPIA_FIELDS`, which held none of them, so all four were dropped on every save with no error. `description`,
`mitigations` and `owner` were columns already; `assessor` and `due_date` were not. The list page reads `due_date` for the overdue
banner and the Due column, so the banner could never fire.

## 2. Decisions

### D1. "Assessor / Owner" is stored in the existing `owner` column (no `assessor` column)
- Why: the field is labelled "Assessor / Owner"; `owner` is the word every Sentinel record uses (RoPA, retention, security, policy);
  `link_dpia_to_ropa` already copies the RoPA owner into `sentinel_dpias.owner`, so the column is the DPIA's "who answers for it" today
  and nothing in the UI showed it. No new column, no new migration for it.
- Cost: the assessor and the RoPA owner share one field (the label already merges them). A DPIA that was linked to a RoPA entry
  before this change shows that entry's owner in the field when it is opened. Both forms now send and read `owner` (they sent
  `assessor`, which never reached the database, so no stored data used that name).
- How to change: add `("sentinel_dpias", "assessor", "TEXT")` to `_COLUMN_MIGRATIONS` in `database.py`, add `assessor` to
  `_DPIA_FIELDS`, and point the two forms back at `assessor`.

### D2. `due_date` is a new nullable TEXT column, added through `_COLUMN_MIGRATIONS`, no data backfill
- Why: that list is what both `_run_sqlite_alters` and `_run_pg_alters` (public schema and every tenant schema) read. TEXT holding
  `YYYY-MM-DD` is how every other Sentinel date is stored (`deadline_date`, `review_date`, `discovery_date`). Nothing was ever stored
  for it, so there is nothing to backfill: a row from before the change reads NULL, which means "no due date" and is never overdue.
  The migration is `ADD COLUMN IF NOT EXISTS` (PG) or add-if-missing (SQLite): it touches no row and is safe to run again.
- A blank due date (the date input emptied) is stored as NULL, not as an empty string, so "no date" has one spelling.
- Anything else must be a real date written `YYYY-MM-DD`: `create_dpia` and `update_dpia` raise `ValueError` (nothing stored) and the
  two routes answer 400. Why: the drawer puts the stored text into an input and the banner compares it with today, and a free text
  value would otherwise be a stored-injection route (see D7) and a date nobody can read back. The form's date input cannot send
  anything else, so a person never sees the error.
- Cost: none beyond one nullable column. How to change: n/a.

### D3. `risk_level` is NOT stored by this change (decision left to the owner); the list shows the level that was chosen
- Both forms send `risk_level` (the drawer copies the Overall Risk Level into it) and `_DPIA_FIELDS` drops it too, so every DPIA keeps
  the column default `medium`. Consequences, all one root cause: the Sentinel dashboard risk buckets count `medium`, and the
  completion event (`api_dpia_update`) always carries `medium`, so the high-risk escalation in `dpia_completed_handler` (risk register
  entry, critical task) can never fire.
- Why it is left alone: storing it would wake that escalation in production for the first time, and the route emits the completion
  event on every save of a completed DPIA (the drawer always sends `status`), so each re-save would repeat the task and evidence
  entries. That needs its own decision and an idempotent event.
- What was done instead: the list's Risk column read `risk_level` first, so it showed `medium` for a DPIA whose Overall Risk Level was
  set to High (the level WAS stored, in `overall_risk`). It now reads `overall_risk` first and falls back to `risk_level`. Display only.
- The guard test lists `risk_level` as the one key a form sends that is deliberately not stored, so it cannot be dropped silently again.
- How to change: add `risk_level` to `_DPIA_FIELDS`, remove it from the guard test's exception set, and make the completion event fire
  once per completion.

### D4. Overdue means strictly before today
- The banner compared `new Date('YYYY-MM-DD')` (UTC midnight) with now, so a DPIA due today turned overdue at 02:00 CAT on its due
  day. It now compares dates the way the subject request countdown does (local midnight, strictly before today). Completed and
  approved DPIAs are never overdue (unchanged).

### D5. No silos: reports reach a DPIA's documents through the Evidence Vault
- Owner message of 22 Oct: "make sure the reports can link to other relevant documentation, no silos" and "they should link via the
  evidence repository". So the Vault is the one place a document is linked to a DPIA, and nothing new is added beside it.
- What already exists and is used, not rebuilt: `evidence_links` (the Vault links a file to a record; the Vault's link picker already
  offers Sentinel / DPIA), and `modules/governance/entity360.get_connected(db, user, "sentinel", "dpia", id)`, the connected view of a
  record. Its `proof` section is the list of Vault files linked to the record with each file's title, Vault link
  (`/evidence/?open=item:{id}`), version, state (accepted, waiting, expired, replaced) and expiry, read through the reader's own
  scope (organization, business unit, removed links and archived files left out). The Case report (`preset_case` in
  `modules/launcher/report_builders.py`) already freezes that view. A report on a DPIA should call `get_connected` and print
  `proof.items` as links; the DPIA record page for it is `/governance/connected/sentinel/dpia/{id}`.
- Built here: the DPIA drawer (edit mode, Review tab) now has "Documents in the Evidence Vault": the same `proof` list, each file a
  link to the Vault, plus how to add one (link it to the DPIA in the Vault) and a link to the connected view. Before this a DPIA
  showed nothing of the files linked to it.
- Tried and removed: a generic Related Items panel on the drawer and a `dpia_related_documents` helper. Both made a second way to
  link, beside the Vault. Related Items is for record to record links and is not mounted on the DPIA or RoPA drawers (follow-up).
- Not built here (other worktrees, uncommitted): printing `proof.items` as links in the DPIA document, the report kit and the evidence
  pack. The hand-over note in the shared notes folder says how.
- Known gap: the DPIA to RoPA link is a foreign key (`ropa_id`), not an edge, so the connected view does not list the RoPA entry.
  A report prints it from `get_dpia` (`ropa_ref`, `ropa_name`). By reading the code (not reproduced): that join has no scope check,
  so a DPIA that is organization wide and linked to a RoPA entry of another unit (only an administrator or an older row can be in
  that state) would show that entry's name to everyone who can open the DPIA. Not changed here.

### D6. Not committed
- The brief said not to commit or push unless asked. The commit message to use is at the end of this file.

### D7. A value that is stored now has to come back out of the form exactly (quotes), so the drawer escapes attribute values
- Found while checking that what is typed is shown again: the template's `esc()` is `textContent` then `innerHTML`, which escapes
  `&`, `<` and `>` but not quotes. The drawer put stored text inside `value="..."`, so a title such as `Customer "VIP" scoring`
  reopened as `Customer ` (and saving again would store the cut text), and a value such as `x" onfocus="..."` added an attribute
  of its own: a stored script injection by anyone who can save a DPIA, run in the browser of whoever opens it. The new `owner` field
  would have been one more such input.
- Fix, in this drawer only: a local `ea()` (esc plus quotes) for the six free text inputs (title, owner, due date, data subjects,
  subject count, retention). Textareas and element text were already safe (`esc` is enough there).
- Not fixed, found: the same `value="'+esc(...)+'"` pattern holds user typed text in a dozen or so other places of the Sentinel page
  (RoPA drawer, the generic record modal that serves breaches, requests, vendors and consent, LIA, jurisdictions, security measure
  evidence), and `title="'+esc(d.ropa_name)+'"` in the DPIA list. Other modules copy the same `esc()`; only the governance page's is quote safe. The one line fix is to escape
  quotes inside `esc()` itself. Left as its own decision (follow-up below), because it changes every form of the page.
- Cost of the local fix: none visible; entity-encoded quotes render as the quote.

## 3. Change log

- `database.py`: `("sentinel_dpias", "due_date", "TEXT")` in `_COLUMN_MIGRATIONS` (SQLite path, PG public schema and every tenant schema).
- `modules/sentinel/data_service.py`: `_DPIA_FIELDS` gains `description`, `owner`, `due_date`, `mitigations`; `_date_or_none` turns a blank
  due date into NULL and refuses a due date that is not `YYYY-MM-DD` (ValueError) in `create_dpia` and `update_dpia`.
- `modules/sentinel/routes.py`: the DPIA create and update routes answer 400 for that ValueError.
- `modules/sentinel/templates/index.html`: the drawer and the generic DPIA modal send and read `owner` ("Assessor / Owner"), not `assessor`;
  the overdue count compares dates strictly before today; the Risk column reads `overall_risk` first; the Review tab lists the
  Vault documents linked to the DPIA (`snLoadDpiaDocuments`); the drawer's free text inputs use a quote safe `ea()` (D7).
- `tests/test_sentinel_dpia_form.py` (new, 23 tests): create and update round trip all four fields (data service and API), each field
  alone, blank dates, padding, refused due dates (7 shapes, data service and API), quotes and line breaks through the API, upgrade
  from a database without the column (run twice), the forms-against-allow-list guard, and the Vault documents of a DPIA through the
  connected view (links, scope, removed, archived, other unit, other organization, replaced, expired, empty).
- `tests/ui/test_sentinel_dpia_form.py` (new, 6 tests): type (with quotes, an ampersand and a line break), save and reopen every field
  in a real browser; a stored value cannot leave its input; clearing the date; the overdue banner and card for seven edge cases; the
  Vault documents in the drawer; the empty state.
- `tests/test_postgres_init.py`: `test_the_dpia_form_fields_and_the_due_date_column_run_on_real_postgres` (column type in public and a
  tenant schema, the four fields on PostgreSQL, a legacy row through the upgrade run twice).

## 4. Verification log

- New backend file on the final code: 23 passed. Against the old behaviour (scratch plugin that puts the allow list back, so no
  production code was edited): 18 of the 23 fail, the creates and updates reading `None` for all four fields as originally found;
  with the column migration removed as well: 19 fail. The 5 that still pass are the Vault document tests, which pin how a report
  reaches a DPIA's documents through code that already existed (a guard for the reports, not a test of the fix).
- New browser file on the final code: 6 passed. With the old allow list: the two storage tests fail (the due date does not come back,
  clearing it does nothing). With the old overdue check put back (template restored byte for byte, hash compared): the banner test fails
  (it counts the DPIA due today).
- Real PostgreSQL 18 (own container `themisiq-pg-test-dpiaform`, port 55441, removed afterwards): the new lane test passed. With
  the migration removed the public schema lacks the column; with the old allow list the fields read back None.
- `scripts/capability_inventory.py --check`: matches.
- Whole backend suite, whole `tests/ui`, whole real PostgreSQL lane file: section 6 (backend and lane green; the browser suite has 6
  failures that are on the base commit too).
- Later mutations (also by scratch plugin or a template swap restored byte for byte): without the quote safe `ea()` the title reopens
  as `Credit ` and the owner as `x`; without the due date check seven shapes of non-date are stored.

## 5. Follow-ups (not done here)

- `risk_level` (D3): dashboard buckets and the high-risk escalation still read a column nothing writes.
- `api_dpia_update` emits the completion event on every save of a completed DPIA; its payload also reads `recommendations` and
  `findings`, which are not columns, and carries no `data_categories`, so `dpia_links_to_aria_controls` never links anything.
  Now that mitigations are stored, `recommendations` could be fed from them.
- The AI draft (`ai_generate_full_dpia`) does not read the description, mitigations, owner or due date a person typed.
- Security (D7): `esc()` in the Sentinel template (and the copies of it in the BCM, ERM, ORM, GRID and other templates) does not escape
  quotes, so every `value="'+esc(x)+'"` and `title="'+esc(x)+'"` is an attribute injection point for stored text. Fix once, inside
  `esc()`, after a look at the few `onclick` strings that build JavaScript from it.
- The DPIA to RoPA foreign key is not an edge (D5, known gap), and Related Items is not mounted on the DPIA or RoPA drawers.
- Printing the Vault documents in the DPIA document, the report kit and the evidence pack (other worktrees).

## 6. Full runs

Repo `.venv` python, from `oneforall/`, one pytest session at a time (other sessions' runs were going on the same machine).

- Whole backend suite (`pytest tests --ignore=tests/ui`, final code state): **2692 passed, 76 skipped, 0 failed, 46 min 54 s** (started
  10:30, ended 11:17 CAT). The 76 skips are the real PostgreSQL lane, off in this run (it has its own run below). An earlier backend run
  was stopped on purpose when the hardening (D2 validation, D7 quote escaping) changed the code, so this one is the run that counts.
- Whole `tests/ui` (separate session, 14:42 to 15:19 CAT): **560 passed, 2 skipped, 6 failed, 37 min 22 s**. All six failures are outside
  Sentinel and are **not from this change**: the same six fail the same way on a clean checkout of the base commit bfde22d6 (a temporary
  worktree, removed afterwards). They are `test_aria_managed_edit.py` (2 tests, the edit modal never opens within 5 s) and four tests in
  `test_workflow_sla_comm_scope.py` / `test_workflow_tenant_scope.py` (the organization administrator's HTTP client gets 403 where the
  test expects 404, 400 or 201: the routes check `platform.workflow.author` first, and `core/rbac.py` gives that capability to the
  super administrator, compliance manager and GRC officer, not to the organization administrator, so the tests are stale against the
  roles; the cause of the two ARIA ones was not looked into). The 2 skips are old ones. The 6 new Sentinel DPIA browser tests are
  among the passes.
- Whole real PostgreSQL lane file (`tests/test_postgres_init.py`, PostgreSQL 18, own container `themisiq-pg-test-dpiaform` on port
  55441, removed afterwards): **76 passed, 0 failed, 9 min 43 s** (15:24 to 15:34 CAT), the new column test included.
- `scripts/capability_inventory.py --check` on the final tree: matches (no route was added, removed or re-gated).
- Nothing is staged or committed; `git status` shows 5 edited files and 3 new ones (the ledger and the two test files).

## 7. Commit message to use (when asked)

```
Store what the Privacy DPIA form sends: description, mitigations, owner and due date

The DPIA drawer and the generic DPIA modal sent description, mitigations, assessor and due_date, and
create_dpia/update_dpia kept only the keys in _DPIA_FIELDS, which held none of them, so all four were
dropped on every save without an error (ledger item O12 of the report exports work).

"Assessor / Owner" maps to the EXISTING owner column (no assessor column): the label already merges the two,
owner is the word every Sentinel record uses, and linking a RoPA entry already copies its owner there.
Both forms now send and read owner.

Due Date is a new nullable TEXT column, sentinel_dpias.due_date, added through _COLUMN_MIGRATIONS so the
SQLite path and the PostgreSQL path (public and every tenant schema) both add it. No backfill: nothing was
ever stored, a row from before reads NULL (no due date, never overdue), and the migration touches no row.
A blank due date is stored as NULL.

The overdue banner now counts a DPIA only when its due date is before today (it flagged a DPIA due today
from 02:00 CAT), the Risk column shows the Overall Risk Level that was chosen, and the Review tab lists the
Evidence Vault documents linked to the DPIA, the same list a report on the DPIA reads from the connected
view of the record. risk_level is deliberately still not stored (see PLAN_dpia_form_fields_2026-10-22.md, D3).

Tests: data service and API round trips of all four fields on create and update, blank dates, the upgrade
from a database without the column, a guard that every key the forms send is stored or named as not stored,
the Vault documents of a DPIA, 5 browser tests, and a real PostgreSQL lane test for the column.
```
