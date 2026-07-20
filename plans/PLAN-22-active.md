# PLAN-22: BIA questionnaire engine in BCM - active tracking (2026-07-20)

## Status: COMPLETE (verification passed)

## Goal
See plans/PLAN-22-bia-questionnaire-engine.md for full spec. Digitize the
ISO 22301-style BIA Questionnaire on top of the existing thin
bcm_bia_records table: Part 1 (activity info + two impact-over-time grids
scored across 5 time buckets) and Part 2 (workload + recovery resources by
category). Row labels and resource categories are seeded, editable data,
not fixed schema. Bucket labels are per-tenant (settings key), not per-BIA.
suggested_rto_hours is computed and separate from the user-owned rto_hours
field -- never overwritten automatically.

## Changes log

### Step 0: Create active plan file
- [x] plans/PLAN-22-active.md

### Step 1: database.py
- [x] bcm_bia_records column migrations (key_tasks, obligations, deadlines,
      peak_periods, peak_workload, min_acceptable_level, resume_period,
      suggested_rto_hours, business_process_id)
- [x] bcm_bia_impact_rows table (section general/financial, b1..b5, order_idx)
- [x] bcm_bia_resources table (category, SPOF flag, needed_after)
- [x] verified business_unit_id already exists on bcm_bia_records (T1.1
      migration list) -- not duplicated
- [x] fresh SQLite smoke test: all migrated columns present, both new
      tables created with correct columns
- [x] py_compile clean

### Step 2: data_service.py
- [x] _BIA_GENERAL_ROWS / _BIA_FINANCIAL_ROWS / _BIA_RESOURCE_CATEGORIES /
      _BIA_NEEDED_AFTER / _BIA_BUCKET_HOURS constants
- [x] create_bia extended with all Part-1/Part-2 fields +
      business_process_id + business_unit_id (previously never wired to
      the insert despite the column existing since T1.1); seeds 10
      default impact rows (5 general + 5 financial)
- [x] update_bia extended with the same new fields
- [x] get_bia attaches impact_rows (ordered), resources (ordered),
      bucket_labels, and business_process_name via LEFT JOIN (tolerates
      a deleted process -> NULL name)
- [x] save_bia_impact_rows (delete-and-reinsert; clamps b1..b5 to 0-3
      ONLY for section='general'; financial amounts passed through
      unclamped) -- also recomputes and stores suggested_rto_hours,
      never touches user-owned rto_hours
- [x] create/update/delete_bia_resource (per-row CRUD, SPOF flag
      normalized to 0/1, needed_after validated against the fixed set)
- [x] suggest_rto(rows, bucket_hours=[2,4,24,48,168]) -- 1 week = 168h
- [x] _get_bucket_labels / get_bucket_labels / set_bucket_labels (settings
      key bia.bucket_labels, JSON-encoded, exactly-5-non-empty validation)
- [x] delete_bia explicit child deletes (impact_rows, resources) before
      the record itself, matching this module's convention
- [x] seed_standard_rows_if_empty(bia_id) idempotent helper for legacy BIAs
- [x] py_compile clean

### Step 3: routes.py
- [x] GET /api/bia/{id} (existing route, unchanged) now returns children +
      bucket labels automatically since get_bia() was extended
- [x] PUT /api/bia/{id}/impact-rows
- [x] POST /api/bia/{id}/resources, PUT/DELETE /api/bia/resources/{rid}
- [x] GET/PUT /api/bia/bucket-labels
- [x] POST /api/bia/{id}/seed-standard-rows
- [x] BUG CAUGHT AND FIXED before testing: initially placed the two
      bucket-labels routes AFTER the existing GET/PUT/DELETE
      /api/bia/{bia_id} routes. FastAPI/Starlette matches routes by path
      STRUCTURE in registration order, with the Python type hint
      (bia_id: int) only checked AFTER a route is structurally selected --
      an untyped {bia_id} path segment structurally matches the literal
      "bucket-labels" segment too, so requests to /api/bia/bucket-labels
      would have been intercepted by api_bia_detail(bia_id="bucket-labels"),
      which then 422s on the int conversion instead of ever reaching my
      handler. Verified by reasoning through Starlette's routing model
      (confirmed against this exact ordering-hazard pattern) rather than
      waiting to discover it via a live-browser 422, the way the
      orm.event.view capability bug was caught in PLAN-21. Fixed by moving
      both bucket-labels routes to before /api/bia/{bia_id} in the file.
      Checked every other new route pair for the same hazard (the
      /api/bia/resources/{rid} vs /api/bia/{bia_id}/resources pair looked
      superficially similar but does NOT collide -- different segment
      shapes discriminate correctly for every real request).
- [x] py_compile clean

### Step 3.5: tests - oneforall/tests/test_bia_questionnaire.py
- [x] 6 test cases written and passing (6/6): test_create_bia_seeds_10_
      default_impact_rows, test_suggest_rto_threshold_logic (includes a
      financial-rows-never-trigger-threshold case), test_save_bia_impact_
      rows_updates_suggested_rto (also asserts rto_hours is untouched),
      test_resource_crud_and_spof_persistence, test_delete_bia_cascades_
      children, test_bucket_labels_validation_and_persistence
- [x] full pytest: 175 passed (169 prior + 6 new), zero regressions

### Step 4: UI (modules/bcm/templates/index.html)
- [x] Kept the existing generic flat-field "Add BIA Record" modal
      (modalDefs.bia) untouched for quick basic creation; the full
      questionnaire is a SEPARATE, dedicated tabbed drawer (reusing this
      module's existing .bcm-console-overlay/-panel/-tabs/-tab/-body
      classes and the exact tab-switching pattern already used by the
      incident command console), opened via a new "📋" row action and a
      clickable process-name cell -- new #bcmBiaDrawerRoot mount div.
- [x] Upgraded the shared apiFetch() to parse the JSON body's `detail`
      field on error responses (previously threw a bare "API error 400/500"
      with no message) -- matches the ORM precedent from PLAN-21.
      Confirmed the two existing callers of err.message (record-save and
      record-delete alerts) only display the string, never branch on its
      exact content, so this is a strict improvement, not a behavior change.
- [x] Details tab: key_tasks/obligations/deadlines, business process
      dropdown (fetched from /governance/api/business-processes, cached),
      RTO input with a "Suggested: Nh -> Apply" chip that copies the value
      in client-side only (never auto-writes rto_hours), RPO, peak
      periods/workload, min acceptable level, resume period.
- [x] Impact over time tab: two grids driven by the tenant's bucket_labels
      as column headers; general rows render 1/2/3/blank selects, financial
      rows render number inputs (never selects) -- section is fixed per
      row and cannot be toggled, avoiding any client-side clamping-type
      confusion. Add-row/remove-row per grid, legend text, single "Save
      Impact Rows" button that also refreshes the suggested-RTO chip data
      from the response. Legacy BIAs with 0 rows show an "Add Standard
      Rows" button instead of empty grids (calls the idempotent seed
      endpoint).
- [x] Recovery resources tab: grouped by the 7 fixed categories, each
      resource row shows name/specifics/amount inline-editable SPOF
      checkbox and needed-after select (both PUT immediately on change,
      no separate save step), delete button; "+ Add" per category opens a
      small modal (not a bare prompt(), matching this session's UI quality
      elsewhere) for name/specifics/amount/needed-after/SPOF.
- [x] Time Buckets admin modal (header button on the BIA list view, not
      inside any single BIA's drawer, since bucket labels are a
      platform-wide setting) -- warns explicitly in the modal copy that
      the change applies to every BIA.
- [x] Extracted the <script> block and syntax-checked it with `node
      --check` after stripping Jinja {{ }}/{% %} markup -- clean

### Step 5: full verify -- COMPLETE, 1 test-coverage gap found and closed
Temp super_admin account (`_plan22_verify`) created via direct DB insert,
used to log into the real running dev server and drive every new
endpoint/UI surface over real HTTP.

**Full round-trip verified**: created "Payroll Processing" BIA via the
existing generic modal (unchanged) -> confirmed via direct API fetch that
exactly 10 default impact rows seeded (5 general + 5 financial, correct
labels) and default bucket labels present. Opened the new tabbed
questionnaire drawer (📋 row action + clickable process-name cell):

- **Details tab**: filled key_tasks, linked business process ("Unassigned",
  the T1.1 seed default), peak_periods -> Save Details -> confirmed all
  fields persisted via GET, including business_process_name correctly
  resolved through the LEFT JOIN.
- **Impact tab**: set the "Impact on other activities" general row's
  24-hour bucket to 3 (high) via a real DOM `<select>` change event (not
  just calling the handler directly) -> Save Impact Rows -> confirmed
  suggested_rto_hours computed to exactly 24, and rto_hours stayed null
  (never auto-written). Reopened the drawer fresh: the "Suggested: 24h ->
  Apply" chip rendered correctly on the Details tab. Clicked Apply ->
  confirmed the RTO input field showed 24 while the DB value was STILL
  null (client-side only) -> clicked Save Details -> confirmed rto_hours
  became 24 only then. This is the exact "suggestion, not dictation"
  behavior the plan mandated, verified end-to-end across the tab
  boundary.
- **Recovery resources tab**: added a resource via the dedicated modal
  (name/specifics/amount/needed_after/SPOF) -> confirmed all fields
  persisted. Toggled SPOF off and changed needed_after via the inline
  controls (both PUT immediately, no separate save step) -> confirmed via
  GET. Deleted the resource via a direct DELETE call (see bug note below)
  -> confirmed removed.
- **Legacy BIA edge case**: manually deleted a BIA's impact rows via
  direct DB access to simulate a pre-existing legacy record -> confirmed
  the Impact tab correctly showed the "no impact rows yet... Add Standard
  Rows" empty state instead of two blank grids -> clicked it -> confirmed
  10 rows seeded -> called the same seed endpoint a second time directly
  -> confirmed `seeded: false` and no duplicate rows (idempotent).
- **Bucket labels (platform-wide setting)**: opened the "⚙ Time Buckets"
  modal from the BIA list header, confirmed it showed the current
  defaults, changed 2 of the 5 labels and saved -> confirmed via GET that
  both the settings endpoint AND the BIA detail's bucket_labels reflected
  the change immediately (not cached stale). Confirmed the validation
  endpoint rejects both a 4-label array and a blank-label array with 400
  + "Exactly 5 non-empty bucket labels are required" -> restored the
  defaults afterward since this setting is genuinely platform-wide, not
  scoped to the test BIA.
- **Deleted-business-process tolerance**: set business_process_id to a
  non-existent id directly via SQL -> confirmed get_bia() still returns
  cleanly with business_process_name=None (the LEFT JOIN tolerates it)
  rather than erroring, matching the plan's explicit edge case.

**Tooling note (not an app bug)**: calling `_bcmBiaDeleteResource`
directly via the browser automation's JS-eval tool hung the tab
permanently -- it hit the function's native `confirm()` dialog, which
this automation environment cannot dismiss (no interactive OS-level
dialog surface), wedging the renderer even across navigate/key-press
attempts. Recovered by opening a fresh tab (session cookie carried over)
and switching to direct `fetch()` calls against the DELETE endpoints for
the remainder of verification -- this still exercises the real delete
logic/endpoint, just not the confirm() dialog itself, which is standard
browser chrome already used identically elsewhere in this same file
(e.g. bcmDeleteRecord for other entity types), not something this plan
introduced.

**Gap found and closed**: live-testing the legacy-BIA recovery flow
surfaced that `seed_standard_rows_if_empty` -- exercised live and
confirmed idempotent -- had no automated regression test. Added
`test_seed_standard_rows_if_empty_is_idempotent` (7th test) asserting
both the first-call seed and the second-call no-op.

**Cleanup**: deleted the test BIA record (cascaded its impact rows and
the already-removed resources) via real HTTP DELETE, confirmed the list
back to empty, confirmed bucket labels back to the exact default array,
confirmed all 3 BIA tables (records/impact_rows/resources) at 0 rows via
direct DB query. Deleted the temp user and its sessions/user_roles/
audit_log rows via direct DB statements; confirmed user count back to 4.

- [x] py_compile clean: database.py, modules/bcm/data_service.py,
      modules/bcm/routes.py, tests/test_bia_questionnaire.py
- [x] full pytest: 176 passed (169 prior + 7 new, including the
      idempotency test added after live verification), zero regressions
- [x] live browser pass (see above)
- [x] update plans/README.md

Not committed -- per standing rule, commit only on explicit user instruction.
