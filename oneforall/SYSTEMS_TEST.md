# ThemisIQ Systems Test Log

Living record of QA passes against the running application: what was tested, what
was found, what was fixed, and what remains open. Updated as work happens, not
retroactively. Each pass is scoped and honest about what it covers versus what it
doesn't; "not covered" is tracked explicitly rather than implied as clean.

Test method throughout: real browser interaction against the local dev server
(`localhost:8080`), real accounts, real data entered through the UI (never assumed
working from reading code alone), direct DB inspection to confirm root cause before
calling anything a bug, cleanup of all test data after each pass.

---

## Pass 1 — Scenario 1 (Audit -> Finding -> Risk -> Corrective Action -> Evidence -> Close) + RBAC spot-check

**Status: COMPLETE.** Findings fixed same session.

**Covered:** super_admin login and full nav inventory, GRID audit -> finding creation
-> ERM risk escalation -> corrective action -> evidence -> close chain, one
low-privilege role permission spot-check.

**Findings (both fixed, verified live + full pytest pass):**

1. **CRITICAL — GRID finding creation was 100% broken.** `openNewNCModal` in
   `modules/grid/templates/index.html` never sent `audit_id`, which
   `grid_non_conformances.audit_id` requires `NOT NULL`. Every "New Finding"
   submission failed. Fixed: modal now fetches `/grid/api/audits`, injects a
   required Audit dropdown, `createNC` includes `audit_id` in the POST body.
2. **HIGH — false-positive breach cascade.** `core/event_handlers.py`'s
   `_BREACH_CATEGORIES` set included generic categories (`compliance_&_legal_risk`,
   `technology_risk`) that had no business auto-firing Sentinel's 72h breach
   clock. Any ERM risk logged under those categories fabricated a data breach
   record. Fixed: narrowed the set to `data_breach`, `privacy_breach`, `privacy`
   (plus the pre-existing title-keyword match, which still fires correctly on
   real breach language).
3. Data-quality item (DB, not code): a malformed legacy `grid_frameworks` row
   deactivated; the correct active ISO 45001:2018 framework row inserted.
4. Investigated and explicitly **declined** to change: Command Centre's
   daypart greeting logic. Correct, standard code; the "bug" was 3 of 4 seeded
   demo accounts having a role title as `full_name` instead of a real name.

---

## Pass 2 — GRID lifecycle completion, breach-cascade regression, Sentinel deep-dive, role spot-checks

**Status: COMPLETE. Findings and fixes both done, all verified live.**

**Covered:** full GRID CAP lifecycle (Open through Closed) on a fresh finding,
regression-check that the Pass 1 category fix didn't break the legitimate cascade,
Sentinel RoPA/DPIA/DSR create flows plus DPIA-gap detection and the 72h breach
countdown, `compliance_manager` and `dpo` persona spot-checks (nav narrowing +
route-level 403 enforcement).

**Not covered (explicitly, not implied clean):** BCM, ORM, ARIA deep-dives; Sentinel's
remaining ~10 sub-pages (Vendor Management, Consent, LIA, AIIA, Transfers, Retention,
Security Measures, Policies, Notices, Reports); any role beyond super_admin/
compliance_manager/dpo; load/performance testing; deliberate malformed-input/injection
fuzzing; import/export testing; notifications.

### Findings

| # | Severity | Area | Summary |
|---|----------|------|---------|
| 1 | Medium | GRID | "Invalid Date" on every finding's Created column |
| 2 | High | GRID | "Link Evidence" modal invisible/unclickable from the Finding drawer (z-index collision) |
| 3 | Low | ERM/core | Auto-escalated "Data Breach Risk" rows get a stale raw-slug category (`compliance` instead of `Compliance & Legal Risk`) until next app restart |
| 4 | Low | Sentinel | No RoPA-link field in the *New DPIA* creation modal (edit drawer already has one) |
| 5 | Medium | Sentinel | DPIA list "Risk" column always shows N/A (field-name mismatch) |
| 6 | Medium | Sentinel | DPIA list "DPO Consulted" shows a checkmark for unconsulted records (JS truthy-string bug) |
| 7 | Medium | Platform-wide | Floating "Themis" help widget (`z-index:9999`) sits above every modal (`z-index:1000`), intercepting clicks meant for a modal's primary action button when the button lands in the bottom-right corner |
| 8 | High | Sentinel | DSR response deadlines are never visible or editable; `update_dsr()` doesn't recompute `deadline_date` the way `create_dsr()` does, so editing in a `received_date` later never sets a deadline |

**Positive findings (confirmed working, no action needed):** full CAP lifecycle
stage advancement and status auto-sync; RoPA creation and its "high-risk, no DPIA"
gap detection banner; the 72h breach countdown on a freshly-cascaded breach;
`compliance_manager`/`dpo` nav narrowing and 403 enforcement at the route level
(not just hidden in nav); the breach cascade itself still firing correctly post
Pass-1 fix.

### Fix log (this session)

Each entry: file(s), what changed, why, live verification result.

- [x] **#1 Invalid Date** — root cause is a duplicated `fmtDate()` helper (10 copies
      across templates) that assumes any timestamp without a literal `T` is a bare
      `YYYY-MM-DD` date and blindly appends `T00:00:00`. SQLite's `datetime('now')`
      default produces space-separated `YYYY-MM-DD HH:MM:SS`, so the appended
      string is malformed and silently renders "Invalid Date" (`toLocaleDateString`
      doesn't throw on an Invalid Date, so the existing try/catch never engages).
      Two of the ten copies (`admin_logs.html`, `task_board.html`) already used a
      safe length-check + `isNaN` fallback pattern; fixed the other 7 to match:
      `grid/templates/index.html:622`, `evidence/templates/evidence_index.html:270`,
      `bcm/templates/index.html:825`, `orm/templates/index.html:577`,
      `sentinel/templates/index.html:1076`, `erm/templates/index.html:758`,
      `launcher/templates/calendar.html:332`.
      **Verified live:** created a fresh GRID finding, Created column and drawer
      footer both show "29 Jul 2026" instead of "Invalid Date".
- [x] **#2 Link Evidence z-index** — `.modal-overlay` and `.nc-detail-panel` (also
      shared by the Control detail drawer) both `z-index:1000` in
      `grid/templates/index.html`; bumped `.modal-overlay` to `1200`.
      **Verified live:** "+ Link Evidence" from within the Finding drawer now
      renders as a fully visible, centered, clickable modal; "Close" correctly
      dismisses it instead of hitting the Themis widget underneath.
- [x] **#3 Stale category slug** — `core/event_handlers.py:2085`,
      `category="compliance"` -> `category="Compliance & Legal Risk"`. Also fixed
      a pre-existing em dash in the same description string (standing house rule).
      Verified via `py_compile` + full pytest pass; not re-triggered live since
      reproducing it means recreating the full breach cascade for a one-line,
      unambiguous string fix already proven correct by inspection.
- [x] **#4 RoPA link at DPIA creation** — added a "Linked RoPA (optional)" field to
      the New DPIA modal (previously edit-only), wired `snSaveDpiaDrawer` to call
      the existing `POST /sentinel/api/dpias/{id}/link-ropa` endpoint right after
      creation if a RoPA was selected, without duplicating that endpoint's own
      drawer-refresh/toast logic (avoided a double-close bug during implementation).
      **Verified live:** field renders correctly in create mode with a
      "(optional)" hint; create-and-link logic confirmed correct by code
      inspection (existing `ropaCache` filter already excludes RoPAs linked to a
      different DPIA, so the field only ever offers valid targets).
- [x] **#5 DPIA Risk column N/A** — `sentinel/templates/index.html:1587`,
      `riskBadge(d.risk_level||d.risk)` -> added `d.overall_risk` (the actual API
      field, confirmed via `SELECT d.*` in `list_dpias()`), matching the fallback
      chain already used at line 1543.
      **Verified live:** a DPIA created with Overall Risk = High now shows a
      "High" badge in the list; pre-existing genuinely-unscored DPIAs correctly
      still show N/A (confirmed via direct DB check they have `overall_risk=NULL`).
- [x] **#6 DPO Consulted checkbox** — `sentinel/templates/index.html:1583`,
      wrapped `d.dpo_consulted` in `Number(...)` before the truthy check, since
      the DB's string `'0'` is JS-truthy and was rendering a checkmark for every
      unconsulted record.
      **Verified live:** a DPIA created with DPO Consulted checked shows ✓;
      existing records with `dpo_consulted=NULL` correctly show "—".
- [x] **#7 Themis widget z-index** — `templates/_platform_trainer.html`,
      `.trainer-bubble` z-index `9999` -> `900` (below every modal's `1000`+, one
      shared partial fixes every module at once).
      **Verified live:** confirmed as part of #2's live re-test (Link Evidence
      modal's "Close" button now receives the click instead of the widget).
- [x] **#8 DSR deadlines** — added a `deadline_date` field ("Response Deadline")
      to the DSR modal's field config (`sentinel/templates/index.html`, shared by
      create + edit), and mirrored `create_dsr()`'s auto-calculate-from-
      `received_date` logic inside `update_dsr()` (`sentinel/data_service.py`) so
      editing in a received date later still produces a deadline.
      **Verified live:** created a DSR with Date Received = 2026-07-29 and
      Response Deadline left blank; list shows a "30d" countdown badge, confirming
      the backend correctly auto-calculated deadline = received + Zimbabwe CDPA's
      30-day DSR window.

**Bonus fix found while verifying #1-8 (not in the original findings list, fixed
because it was a concrete, reproduced crash, not speculation):**

- [x] **#9 `NameError` crashing every Sentinel AI error path** —
      `modules/sentinel/routes.py` called `log.error(...)` in 12 identical
      exception handlers (RoPA scoring, DPIA research/generation, LIA, AIIA, DSR
      drafting, etc.) but never imported or defined `log` anywhere in the file.
      Discovered via a real traceback in the dev server's error log from earlier
      Sentinel testing (`NameError: name 'log' is not defined` at line 1515).
      Every one of those 12 call sites would crash with a raw `NameError` instead
      of returning a clean "AI processing failed" 500 whenever the underlying AI
      service had any error, and the actual failure reason was never logged
      anywhere. Fixed: added `import logging` + `log = logging.getLogger(
      "oneforall.sentinel")` at module level, fixing all 12 sites at once. Also
      fixed a pre-existing em dash in the file's top docstring (standing house
      rule, touched the file anyway).

### Verification checklist

- [x] `python -m py_compile` on every touched `.py` file (`core/event_handlers.py`,
      `modules/sentinel/data_service.py`, `modules/sentinel/routes.py`) — clean.
- [x] All 8 touched Jinja templates parse cleanly (checked via
      `Environment(loader=FileSystemLoader(...)).get_template(...)`) — clean.
- [x] Full `pytest tests/` suite — 199/199 passing, both before and after every
      fix in this session.
- [x] Live re-test of each fix using the original repro steps — see per-fix notes
      above.
- [x] Test data cleanup — all fix-verification records deleted (1 GRID finding,
      1 DPIA, 1 DSR, plus their auto-generated `cross_module_links` rows). Also
      caught and cleaned up one **missed item from Pass 2's own cleanup**: the
      GRID post-incident audit auto-cascaded from the Pass 2 regression-test
      breach (`grid_audits` id 22) was never deleted in Pass 2 — found and
      removed during this session's final DB sweep.

---

## Pass 3 — Sentinel's remaining 10 sub-pages

**Status: COMPLETE. Findings and fixes both done, all verified live. Item #10
(log_audit retrofit) deliberately deferred to its own follow-up, per explicit
instruction.**

**Covered:** Vendor Management, Consent Management, Legitimate Interest (LIA),
AI Impact Assessment (AIIA), Intl. Transfers, Retention, Security Measures,
Privacy Policies, Privacy Notices, Reports & Analytics, create flows on each.

**Method:** for every entity, cross-referenced the frontend form's field config
against (a) its backend `_XXX_FIELDS` allowlist in `data_service.py` and (b) the
real DB table schema via `PRAGMA table_info`, so mismatches could be predicted
before triggering them. Live-confirmed a representative sample of each bug class
(Security Measures and Transfers both reproduced the predicted 500 crash exactly)
rather than redundantly re-clicking through an already-proven root cause on every
single entity; Retention and Policies were left as code-confirmed-only since the
identical `_generic_create` root cause applies to them without doubt.

**Root cause underlying 4 of the findings below:** `sentinel/data_service.py`'s
`_generic_create`/`_generic_update` build `INSERT`/`UPDATE` statements directly
from whatever field-name list they're given, with no validation that those names
are real columns in the target table. Combined with a form config that was
apparently never checked against the schema for several entities, this produces
either a silent dropped field (frontend name wrong but backend allowlist name is
real) or a hard 500 crash (backend allowlist name itself doesn't exist in the DB).

### Findings

| # | Severity | Area | Summary |
|---|----------|------|---------|
| 1 | High | Security Measures | Every creation attempt crashes 500 (`no column named responsible`) — `_SEC_FIELDS` uses `responsible`, real column is `owner` |
| 2 | High | Intl. Transfers | Every creation attempt crashes 500 (`no column named recipient`) — `_TRANSFER_FIELDS` uses `recipient`/`safeguards`, real columns are `recipient_name`/`safeguard` |
| 3 | High | Retention | Same crash predicted, not yet re-triggered live — `_RET_FIELDS` uses `deletion_method`/`responsible`, real columns are `disposal_method`/`owner` |
| 4 | High | Privacy Policies | Same crash predicted, not yet re-triggered live — `_POLICY_FIELDS` uses `type`, real column is `policy_type` |
| 5 | Medium | Vendor Management | Form field `service` silently lost (real column is `services`); form field `review_date` maps to no column at all |
| 6 | Medium | Consent Management | Form field `collection_method` silently lost (creation succeeds, column stays blank); form never exposes `subject_name`/`subject_id`/`consent_date` at all, so there's no way to record who consented or when |
| 7 | Medium | Privacy Notices | Form fields `type`/`url` map to nothing; `content_summary` should be `content` — confirmed live, `content` stays NULL despite entering text |
| 8 | Medium | Reports | `snLoadReports()` has a bare `return` inside the audit-trail empty-check that skips the compliance-score fetch entirely whenever the audit trail is empty — meaning "Compliance Score: —" never even attempts to populate itself while the trail is empty (which it always is, see item 10) |
| 9 | Low | Reports | The 3 differently-labeled report buttons (Audit Log Export, RoPA Report, Breach Report) and the Compliance Score card all call the identical `/api/audit-export` endpoint, which never reads its own `format`/`type` query params — all 4 actions download the byte-for-byte identical bundled ZIP regardless of label |
| 10 | Low | Platform-wide (surfaced via Sentinel Reports) | `audit_log` is never written by Sentinel, GRID, BCM, ERM, or ORM — only `"platform"`, `"aria"`, `"evidence"`, `"governance"` call `log_audit()`. Sentinel's "Audit Trail" table (and the export ZIP's `Audit_Trail_*.json`) will always be empty regardless of real activity; this is a missing write path across 5 modules, not a display bug, and is a bigger fix than Sentinel Reports alone — flagged separately rather than bundled into this pass's fixes |
| 11 | Low | Security Measures / Transfers / Notices | Modal shows "Edit"/"Update" even for a brand-new record (Vendor and Consent correctly show "Add"/"Create") |
| 12 | Low | LIA | 3 em dashes in modal copy: "Part 1 — Purpose Test", "Part 3 — Balancing Test", "Controller interests prevail — data subjects would not be surprised or object" |

**Positive findings (confirmed working, no action needed):** LIA works fully
end-to-end (3-part purpose/necessity/balancing test all passed correctly, zero
backend field-name mismatches, perfect match against the real DB schema via
`PRAGMA`); AIIA works fully end-to-end (created with correct autonomy level and
correct "Not Scored" default classification, also zero backend field-name
mismatches).

**Test data cleanup (testing phase):** all 6 records that actually persisted
(Vendor "VERIFY-SUB: CloudHost Data Processing Ltd" + its auto-created
`canonical_vendors` row, Consent "VERIFY-SUB: Marketing email consent", Notice
"VERIFY-SUB: Website Privacy Notice", LIA "VERIFY-SUB: Fraud monitoring via
transaction analytics", AIIA "VERIFY-SUB: Loan approval scoring model") deleted
and confirmed removed via direct DB query. Security Measures and Transfers test
attempts confirmed via direct DB query to have persisted zero rows (consistent
with both crashing before their INSERT could commit), so no cleanup was needed
for those two.

### Fix log

Each entry: file(s), what changed, why, live verification result.

- [x] **#1-2 Security Measures / Transfers 500 crashes** — `_SEC_FIELDS`'s
      `responsible` -> `owner`; `_TRANSFER_FIELDS`'s `recipient`/`safeguards` ->
      `recipient_name`/`safeguard` (`modules/sentinel/data_service.py`), with the
      matching frontend field names renamed in `modalDefs.security`/`.transfer`
      (`modules/sentinel/templates/index.html`) so the three-way match (form
      field name = backend allowlist name = real DB column) holds end to end.
      **Verified live:** created a Security Measure and a Transfer; both
      succeeded (`201 Created`, confirmed via direct DB query the `owner` /
      `recipient_name` / `safeguard` columns hold exactly what was typed).
- [x] **#3 Retention 500 crash** — same pattern: `_RET_FIELDS`'s
      `deletion_method`/`responsible` -> `disposal_method`/`owner`, plus the
      matching frontend rename.
      **Verified live:** created a Retention schedule; succeeded, `disposal_method`
      and `owner` confirmed correct via direct DB query.
- [x] **#4 Privacy Policies 500 crash** — `_POLICY_FIELDS`'s `type` -> `policy_type`
      (matching frontend rename). Also found and fixed a **second**, previously
      uncaught mismatch on the same entity while correcting this one:
      `_POLICY_FIELDS`'s `content` field pointed at a column that doesn't exist
      either; the real column is `description` (backend-only rename, the form
      never exposed a content field so there was nothing to rename there).
      **Verified live:** created a Privacy Policy with Type=Standard; succeeded,
      `policy_type='standard'` confirmed via direct DB query.
- [x] **#5 Vendor Management** — `service` -> `services` in `modalDefs.vendor`.
      `review_date` had no backing column anywhere (not a naming mismatch, a
      genuine gap); added `sentinel_vendors.review_date` via `_COLUMN_MIGRATIONS`
      in `database.py` (matches the existing `website`/`regulation` precedent for
      this exact table) and added it to `_VENDOR_FIELDS`.
      **Verified live:** created a Vendor with both fields filled; `services` and
      `review_date` both confirmed correct via direct DB query.
- [x] **#6 Consent Management** — `collection_method` had no backing column;
      added `sentinel_consent.collection_method` via `_COLUMN_MIGRATIONS` and to
      `_CONSENT_FIELDS`. Added the 4 real-but-unexposed columns
      (`subject_name`, `subject_id`, `subject_email`, `consent_date`) to
      `modalDefs.consent` so the form can actually record who consented and when.
      **Verified live:** created a Consent record with all 6 fields filled; every
      one confirmed correct via direct DB query.
- [x] **#7 Privacy Notices** — `content_summary` -> `content` (pure rename, no
      schema change, this was the field silently losing all typed text). `type`
      and `url` had no backing columns; added `sentinel_privacy_notices.notice_type`
      and `.published_url` via `_COLUMN_MIGRATIONS` (named `notice_type` rather
      than bare `type` to avoid ambiguity, matching the `policy_type`/`transfer_type`
      convention already used by sibling entities), wired into `_NOTICE_FIELDS`
      and the matching frontend field names.
      **Verified live:** created a Notice with Type/URL/Content all filled; all
      3 confirmed correct via direct DB query (`content` in particular, previously
      always NULL despite text being entered).
- [x] **#8 Reports compliance score never loading** — `snLoadReports()` had a
      bare `return` inside the audit-trail's empty-check that skipped the
      compliance-score fetch entirely whenever the trail was empty (which is
      always, per #10). Restructured the empty/non-empty branches into an
      if/else so the compliance-score fetch always runs afterward regardless.
      **Verified live:** Reports page now shows "Compliance Score: 52%" instead
      of a permanent "—".
- [x] **#9 Report buttons producing identical output** — `api_audit_export`
      (`modules/sentinel/routes.py`) never read its own `type` query param.
      Added branching: `type=ropa`/`breach`/`compliance` now each return a
      focused single-file export (`RoPA_Report_*.json`, `Breach_Report_*.json`,
      `Compliance_Score_*.json`); no `type` (the plain "Audit Log Export" button)
      keeps the original full multi-file evidence pack unchanged.
      **Verified:** direct script replicating each branch's ZIP-building logic
      confirms 4 distinctly different file listings (comprehensive 8-file pack
      vs. 3 single-file exports); all 4 endpoint calls return `200 OK` live.
- [x] **#11 Modal Add/Edit mislabeling** — root cause: `snOpenModal`'s
      `isEdit=!!existing` treated *any* object (including the `{}` five "+ Add"
      buttons on Security/Transfer/Retention/Policy/Notice passed by mistake,
      and a non-empty AI-draft prefill object on Policy) as "editing," since any
      object is JS-truthy. Fixed at the root: `isEdit=!!(existing&&existing.id)`,
      so only an object with a real persisted `id` counts as an edit. Also
      cleaned up the 5 button call sites to omit the stray argument entirely,
      and fixed two now-stale references surfaced by the #4/#2 renames above:
      the AI-draft policy prefill's `type:'policy'` -> `policy_type:'policy'`,
      and a "+ Transfer for X" quick-fill button's `recipient:` -> `recipient_name:`.
      **Verified live:** all 5 previously-mislabeled "+ Add" buttons now show
      "New X" / "Create"; editing an existing Security Measure still correctly
      shows "Edit Security Measure" with the record's real data pre-filled.
- [x] **#12 Em dashes in LIA modal copy** — `sentinel/templates/index.html`:
      "Part 1 — Purpose Test", "Part 3 — Balancing Test", and "Controller
      interests prevail — data subjects would not be surprised or object" all
      changed to colons (standing house rule). Also caught and fixed a 4th,
      identical-pattern instance in the same drawer not in the original
      findings list: "Part 2 — Necessity Test". Also fixed 2 more found while
      touching `api_audit_export`'s README text and the AI-draft policy
      toast message during the #9/#11 fixes above.

**Deliberately not fixed this pass:**

- [ ] **#10 `audit_log` never written by 5 modules** — per explicit instruction,
      this is scoped as its own follow-up rather than bundled here; it touches
      every mutation endpoint across Sentinel/GRID/BCM/ERM/ORM, a materially
      larger change than a field-name/UI fix.

### Verification checklist

- [x] `python -m py_compile` on all 3 touched Python files (`database.py`,
      `modules/sentinel/data_service.py`, `modules/sentinel/routes.py`) — clean.
- [x] `sentinel/templates/index.html` parses cleanly via Jinja `get_template()`.
- [x] Full `pytest tests/` suite — all passing, both before and after every fix.
- [x] Dev server restarted fresh; confirmed all 6 new `_COLUMN_MIGRATIONS`
      columns landed (`sentinel_vendors.review_date`,
      `sentinel_consent.collection_method`, `sentinel_transfers.legal_basis`
      and `.risk_level`, `sentinel_privacy_notices.notice_type` and
      `.published_url`) via direct `PRAGMA table_info` query.
- [x] Live re-test of each of the 7 entities' create flow (Vendor, Consent,
      Transfer, Retention, Security, Policy, Notice) — every one succeeded with
      `201 Created` and every field verified correct via direct DB query, not
      just assumed from a lack of errors.
- [x] Live re-test of Reports page — Compliance Score now populates (52%,
      previously permanently "—"); confirmed the 3 report-type branches produce
      genuinely different file listings.
- [x] Live re-test that fixing the Add/Edit mislabeling didn't break genuine
      edits — opened Edit on an existing Security Measure, confirmed it still
      correctly shows "Edit Security Measure" with real data pre-filled.
- [x] No console errors during the entire verification pass; server error log
      clean for every Sentinel-related request (the one error observed,
      `RuntimeError: No response returned` on `/api/notifications`, is the
      same pre-existing platform-wide middleware-stacking issue already
      identified and scoped out during the ERM Framework Editor slice,
      unrelated to any Pass 3 change).
- [x] Test data cleanup (fix-verification phase): all 7 `PASS3-FIX-VERIFY`
      records plus their 1 auto-generated `canonical_vendors` row deleted;
      confirmed zero rows remain across all 8 touched tables via a text-search
      sweep, not just the specific rows we remember creating.

---

## Pass 3 follow-up — audit_log retrofit (item #10)

**Status: COMPLETE for Sentinel/BCM/ERM/ORM. GRID needed a different, smaller
fix once investigation showed the original diagnosis was wrong for that one
module specifically.**

**What changed:** added `module_audit_middleware` (`core/middleware.py`),
registered as the innermost middleware in `main.py` (after
`tenant_context_middleware`, so `request.state.user` set by
`@require_auth`/`@require_capability` is already populated by the time it
runs). It matches the request path against
`^/(sentinel|bcm|erm|orm)/api/([a-zA-Z_-]+)(?:/(\d+))?`, and on any
successful (2xx) POST/PUT/PATCH/DELETE, calls the existing `log_audit()`
helper with the module/entity/id parsed from the URL. This closes the gap
for all ~250 mutation endpoints across the 4 modules at once, including
future ones, without hand-editing every route.

**Correction to the original Pass 3 diagnosis:** GRID was wrongly included
in "5 modules with zero audit logging." A live test surfaced entries like
`create_vendor`/`create_nc`/`advance_cap` already in `audit_log` for GRID
activity from earlier in this session, before this fix existed. Investigation
found `modules/grid/data_service.py`'s own `log_activity()` helper, called
from 45 of GRID's 64 mutation endpoints, with richer per-entity action names
than the generic middleware could produce, missed entirely by the original
grep (which only searched for `log_audit(` calls, not `log_activity(` or raw
`INSERT INTO audit_log`). GRID is now deliberately excluded from
`module_audit_middleware`'s scope, since including it would have
double-logged those 45 endpoints, not closed a real gap. Confirmed live:
creating a GRID vendor before the exclusion produced 2 audit_log rows for
one action (`POST vendors` from the new middleware + `create_vendor` from
GRID's own helper); after excluding GRID, the same action produces exactly 1.

**Verified:** BCM/ERM/ORM's `data_service.py` files have zero references to
`audit_log` or any `log_*` helper (confirmed via direct grep), so the
"genuinely audit-silent" diagnosis holds for those 3 plus Sentinel.
`py_compile` clean on `core/middleware.py`/`main.py`; full `pytest` suite
passing both before and after; live-verified a Sentinel vendor creation now
appears in Sentinel's own Reports > Audit Trail table (previously always
empty) with correct user/action/entity/timestamp.

**Remaining, smaller follow-up:** ~19 of GRID's 64 mutation endpoints have no
`log_activity()` call at all. Matching GRID's own existing convention there
is the right fix, not layering a second mechanism on top of the one it
already has. **Done, see below.**

---

## Pass 3 follow-up, part 2 — GRID log_activity gap-fill

**Status: COMPLETE.**

**Method:** grepped every `@router.post/put/delete` decorator in
`grid/routes.py` (64 total) and every existing `ds.log_activity(` call site
(45), then matched each route to its real function boundary (via every
`async def`/`def` line, not just decorator lines, since GET routes sit
between some POST/PUT/DELETE ones and would otherwise throw off a naive
line-range guess) to find which of the 64 had zero `log_activity()` call
anywhere in their body.

**Findings:** 20 routes had no call. 5 of those are AI-generation endpoints
(`/api/ai/parse-checklist`, `/api/ai/suggest-control`,
`/api/audits/{id}/ai-checklist`, `/api/ai/generate-report/{id}`,
`/api/ai/chat`) confirmed by reading each one's body to call only the `ai`
module and return JSON, no database write of any kind, so there is nothing
to log and these are correctly excluded, not a gap. The other **15 are real
gaps**, all genuine mutations with zero audit trail:

| Route | Action logged |
|---|---|
| `POST /api/evidence-items/{control_id}` | `create_evidence_item` |
| `DELETE /api/evidence-items/{item_id}` | `delete_evidence_item` |
| `POST /api/controls/{cid}/comments` | `add_comment` |
| `POST /api/reminders` | `create_reminder` |
| `POST /api/approvals/{evidence_id}` | `request_approval` |
| `POST /api/mappings` | `create_mapping` |
| `DELETE /api/mappings/{mid}` | `delete_mapping` |
| `PUT /api/timeline/{tid}` | `update_timeline` |
| `POST /api/scores/{audit_id}` | `record_score` |
| `POST /api/remote-sessions/{sid}/start` | `start_remote_session` |
| `POST /api/remote-sessions/{sid}/end` | `end_remote_session` |
| `POST /api/remote-sessions/{sid}/findings` | `create_remote_finding` |
| `PUT /api/remote-findings/{fid}` | `update_remote_finding` |
| `POST /api/remote-sessions/{sid}/notes` | `create_remote_note` |
| `POST /api/remote-sessions/{sid}/participants` | `add_remote_participant` |

### Fix log

- [x] Added one `ds.log_activity(_uid(request), action, entity_type,
      entity_id, ...)` call to each of the 15 routes above
      (`modules/grid/routes.py`), placed immediately after the mutation
      commits and before the response is returned, matching the exact
      call shape already used successfully at the other 45 existing sites
      in this file. Action names and entity types follow the same
      verb_noun / real-table-name convention already established (e.g.
      `create_vendor`, `advance_cap`).

### Verification checklist

- [x] `python -m py_compile modules/grid/routes.py` — clean.
- [x] Full `pytest tests/` suite — 200 passed, 0 failed.
- [x] Call-site count cross-check: 45 original + 15 added = 60, confirmed
      via `grep -c "log_activity("` on the file post-fix (was 45 before).
- [x] Live HTTP verification (real authenticated session, not a script
      bypassing auth): fired all 15 fixed endpoints via `fetch()` from an
      authenticated GRID page (evidence item create+delete, comment add,
      reminder create, mapping create+delete, timeline update, score
      record, and a full remote-session lifecycle: create session, start,
      add a finding, update that finding, add a note, add a participant,
      end session). All 15 returned `200`/`201`. Confirmed via direct
      `audit_log` query that all 15 action names landed with the correct
      `module='grid'`, `entity_type`, and `entity_id`. The 16th route,
      `request_approval`, was not live-fired (no `grid_evidence_files` row
      existed in the dev DB to request approval on) — left as
      code-confirmed-only, since it is a byte-for-byte match of the
      already-proven `decide_approval` pattern one route below it.
- [x] Test data cleanup: all verification rows deleted (1 comment, 1
      reminder, 1 compliance score, 1 remote session cascade-deleted with
      its finding/note/participant, the paired evidence-item and mapping
      create+delete left nothing behind), plus the 15 `audit_log` rows the
      verification itself generated. One mistake caught during cleanup:
      the timeline-update test overwrote real seed data
      (`grid_timeline.id=31`, "Kick-off meeting") with a placeholder
      status instead of round-tripping the original value first; restored
      to `'Pending'` to match the other 9 seeded timeline rows, which are
      all `'Pending'` with no exceptions. Confirmed zero `GRID-VERIFY%`
      residue across every touched table afterward.

---

## Pass 4 — BCM's 14 sub-pages

**Status: COMPLETE. Findings and fixes both done, all verified live.**

**Covered:** Business Impact Analysis (BIA), Continuity Plans, Incidents,
Exercises & Testing, Risk Assessment, Dependencies, Training, Crisis Comms,
Emergency Contacts, Scenario Library, Documents, Compliance Controls,
Vendors, Reports, create flows on each.

**Method:** BCM has a different architecture from Sentinel's (hand-written
`create_X`/`update_X` functions per entity with explicit INSERT/UPDATE
statements, not a shared generic helper), so the bug class is different too:
mostly frontend fields with no backend/DB counterpart at all, rather than
allowlist/schema name mismatches. Extracted every `INSERT INTO bcm_X`
statement's column list and every `update_X`'s field tuple via Grep, cross-
referenced both against a single batched `PRAGMA table_info` sweep of all
~30 BCM tables, then cross-referenced the (now backend-confirmed) column
names against the frontend `modalDefs` config to find frontend-only dead
fields. This found all of the findings below via static analysis alone,
before any live testing; live testing was then used to confirm predictions,
not to discover new ones.

### Findings

| # | Severity | Area | Summary |
|---|----------|------|---------|
| 1 | Critical | Risk Assessment | Every creation attempt crashes 500 (`ValueError: invalid literal for int()`) — `create_risk`/`update_risk` call `int()` directly on `likelihood`/`impact`, but the form sends text labels ("Rare".."Almost Certain", "Negligible".."Catastrophic") |
| 2 | Medium | BIA | Form field `mtpd_hours` silently lost (real column, never wired into the INSERT/UPDATE); form field `status` maps to no column at all |
| 3 | Medium | Exercises & Testing | Form field `description` maps to no column at all; `lessons_learned` maps to no column either, despite a real `aar_summary` column existing unused and unexposed anywhere in the UI |
| 4 | Medium | Risk Assessment | Form field `risk_level` maps to no column at all, and duplicates the already-working auto-computed `bcmScoreToLevel(r.score)` severity badge shown in the risk list |
| 5 | Medium | Dependencies | Form fields `owner` and `recovery_priority` both map to no column at all |
| 6 | Low | Dependencies | `node_type` select isn't marked required despite being a `NOT NULL` DB column, so skipping it crashes with a raw `IntegrityError` instead of a friendly validation message |
| 7 | Low | Continuity Plans / Scenario Library | 4 em dashes in modal/help copy and 2 JS string literals |

**Ruled out (investigated, not a real bug):** while reading `bcmGenReport`/
`bcmBoardReport`'s `apiFetch()` calls via Grep, the output initially appeared
to show backslash-corrupted URLs (`\api\reports\definitions` instead of
`/api/reports/definitions`), which would have broken the Reports page's
generate buttons entirely. A follow-up Grep for the literal backslash
pattern returned no matches, and a direct `Read` of the same lines confirmed
the file correctly uses forward slashes throughout — the backslashes were an
artifact of how the first Grep call's output rendered, not real file
content. No fix needed.

**Positive findings (confirmed clean, no action needed):** Continuity
Plans, Incidents, Training, Crisis Comms, Emergency Contacts, Scenario
Library, Documents, Compliance Controls, Vendors, and Reports all passed
the three-way frontend/backend/DB check with zero mismatches.

**Test data cleanup (fix-verification phase):** all 4 `BCM-VERIFY` records
created to confirm the fixes (Risk "BCM-VERIFY: Test Risk Fixed", BIA
"BCM-VERIFY: BIA Fixed" plus its 10 auto-seeded `bcm_bia_impact_rows`,
Exercise "BCM-VERIFY: Exercise Fixed", Dependency Node "BCM-VERIFY: Node
Fixed") deleted and confirmed removed via direct DB query (zero
`BCM-VERIFY%` rows remain across all 4 tables).

### Fix log

Each entry: file(s), what changed, why, live verification result.

- [x] **#1 Risk Assessment 500 crash** — added `_risk_scale_value()` plus
      `_RISK_LIKELIHOOD_SCALE`/`_RISK_IMPACT_SCALE` lookup tables
      (`modules/bcm/data_service.py`) that convert the text labels to
      numbers for score arithmetic only, falling back to numeric-string
      parsing and then to `1` rather than raising. `likelihood`/`impact`
      are still stored as the original text for display (confirmed the
      list view reads `r.likelihood`/`r.impact` as raw text and derives
      its severity badge from `r.score`, not from these fields directly).
      **Verified live:** created a risk with Likelihood=Possible,
      Impact=Major; `201 Created`, DB confirms `likelihood='Possible',
      impact='Major', score=12` (3×4).
- [x] **#2 BIA dead fields** — wired the existing `mtpd_hours` column into
      `create_bia`/`update_bia`; added `bcm_bia_records.status` (default
      `'active'`) via `_COLUMN_MIGRATIONS` and wired it in too.
      **Verified live:** created a BIA with MTPD=72, Status=draft; DB
      confirms `mtpd_hours=72, status='draft'`.
- [x] **#3 Exercise dead fields** — added `bcm_exercises.description` via
      `_COLUMN_MIGRATIONS`, wired into `create_exercise`/`update_exercise`.
      Renamed the frontend's `lessons_learned` field key to `aar_summary`
      (a real, previously-unexposed column) rather than adding a new one,
      after confirming via grep that none of the 4 `aar_*` columns had any
      other frontend reference anywhere in `index.html` — safe rename, no
      conflict. Visible label stays "Lessons Learned".
      **Verified live:** created an exercise with both fields filled; DB
      confirms `description` and `aar_summary` both hold the typed text.
- [x] **#4 Risk `risk_level` dead field** — removed from the frontend modal
      entirely instead of adding a backing column, since it would have
      duplicated the already-working auto-computed severity badge and
      created two disagreeing sources of truth for the same concept (a
      manually-picked level vs. the score-derived one).
- [x] **#5 Dependency Node dead fields** — added
      `bcm_dependency_nodes.owner` (TEXT) and `.recovery_priority`
      (INTEGER) via `_COLUMN_MIGRATIONS`, wired into
      `create_dependency_node`/`update_dependency_node`.
      **Verified live:** created a node with both fields filled; DB
      confirms `owner='Owner Should Save Now', recovery_priority=1`.
- [x] **#6 Dependency Node missing required flag** — added `required:true`
      to the frontend's `node_type` field config so the browser blocks
      submission before it ever reaches the server, instead of a raw
      `IntegrityError: NOT NULL constraint failed` 500.
- [x] **#7 Em dashes** — 4 fixed: 2 in modal/help copy (Continuity Plans,
      Scenario Library), 2 in JS string literals (`bcmOpenDocViewer`'s
      board-report title, a toast error message) found while investigating
      the ruled-out backslash item above.

### Verification checklist

- [x] `python -m py_compile` on both touched Python files (`database.py`,
      `modules/bcm/data_service.py`) — clean.
- [x] `bcm/templates/index.html` parses cleanly via Jinja `get_template()`.
- [x] Full `pytest tests/` suite — 200 passed, 0 failed, both before and
      after every fix.
- [x] Live re-test of all 4 affected create flows (Risk, BIA, Exercise,
      Dependency Node) — every one succeeded and every field verified
      correct via direct DB query, not just assumed from a lack of errors.
- [x] Live re-test of the Dependency Node validation fix — submitting with
      no Type selected is now blocked client-side instead of crashing.
- [x] Test data cleanup: all 4 `BCM-VERIFY` records plus the BIA's 10
      auto-seeded impact rows deleted; confirmed zero rows remain via a
      text-search sweep across all 4 touched tables.

---

## Pass 5 — ORM deep dive

**Status: COMPLETE. Findings and fixes both done, all verified live.**

**Covered:** Events, KRI Indicators, Event Templates, RCSA (Assessments, Risks,
Controls, Actions), AI Controls, AI Risk (AIMS Assessments/Risks/Risk-Controls),
create flows on each.

**Method:** ORM uses hand-written CRUD like BCM (no shared generic helper),
so the same "dead field" bug class applied. Extracted every `INSERT INTO`
column list and every `update_X`'s allowed-fields tuple from `data_service.py`,
cross-referenced against a batched `PRAGMA table_info` sweep of all ORM/AIMS
tables, then cross-referenced the backend-confirmed columns against every
frontend field-collection site in `templates/index.html` (found via every
`apiFetch('/orm/api/...', {method:'POST'|'PUT', body:...})` call site, not
just a `modalDefs`-style search, since ORM builds its `data` object inline
per save function rather than through a shared config table).

### Findings

| # | Severity | Area | Summary |
|---|----------|------|---------|
| 1 | Critical | KRI Indicators | `auto_update_event_type`/`auto_update_notes` collected by a real, prominently-featured form control (with a pre-built 11-item KRI library showcasing it) but never read by `create_kri`/`update_kri` — every KRI's auto-increment-from-events configuration was silently discarded, permanently starving `orm_event_logged_handler`'s `WHERE auto_update_event_type=%s` query. This meant the platform's advertised "KRIs auto-update when their configured event type fires" feature (per the module's own README) never worked for any KRI created through the UI |
| 2 | High | RCSA | `orm_rcsa_controls` and `orm_rcsa_actions` had full backend CRUD (create/update/delete) plus an effectiveness roll-up calculation (`_recompute_risk_effectiveness`), but zero frontend UI — no "+Add Control"/"+Add Action" anywhere, only a read-only Actions list. Risks could only be scored via a single manual slider, so the roll-up logic was permanently unreachable |
| 3 | Medium | Event Templates | `basel_category` is a real, backend-wired column and appears on the live Event form, but the Template modal never exposed it, so templates could never carry a Basel category into pre-filled events |
| 4 | Medium | AI Risk (AIMS) | `aims_risks.implemented`/`.scope_justification` are real columns already in the backend's `_AIMS_RISK_FIELDS` allowlist but had no UI control anywhere |
| 5 | Medium | AI Risk (AIMS) | `aims_risk_controls.action_steps`/`.responsible`/`.interdependency` are real columns already in `_AIMS_RC_FIELDS` but had no UI control in the Link Control modal |
| 6 | Low | Events | `orm_events.parent_event_id` is read by the frontend for parent/child event grouping display, but nothing anywhere (no escalate/split-event flow) ever writes it, so that display code can never actually show anything. Left deferred, not fixed: fixing it means designing a "link to parent event" picker UX, a genuinely different kind of work than wiring an existing input |

**Ruled out (not a bug, no action needed):** `orm_events.business_unit_id`,
`orm_rcsa_assessments.business_unit_id`, and `orm_rcsa_controls.canonical_control_id`
all have zero frontend references anywhere, consistent with the already-known,
already-documented Governance T1.2 deferral (BU-scoping and canonical-controls
unification are explicitly future work, not a fresh gap). `orm_events.root_cause`
has no manual-entry UI (only a Root Cause *Category* dropdown), but this looks
intentional — it's most likely meant to be filled by the existing
`/api/ai/analyze/{id}` AI root-cause-analysis endpoint rather than typed by hand;
not conclusively a bug, left alone.

**Dev-tooling note (not an application bug):** while verifying the KRI fix,
the running `uvicorn --reload` dev server logged `WatchFiles detected changes
in 'modules\orm\data_service.py'. Reloading...` but kept serving the old
bytecode (confirmed: the identical fix worked instantly when invoked directly
via a Python script, and worked over HTTP only after a manual server
stop/restart). Recorded here for transparency since it cost real debugging
time and could resurface on a future session; not a code defect.

**Test data cleanup:** all `ORM-VERIFY`-prefixed rows created during
verification (KRI, Event Template, AIMS Assessment/Risk/Risk-Control, RCSA
Assessment/Risk/Control/Action) deleted and confirmed removed via direct DB
query. One mistake caught during the RCSA UI test: the timeline-update-style
slip did *not* recur here, but a wrong hardcoded action id was used on a
first edit attempt (my own test-script error, not an app bug) — self-caught
via a DB check showing the status hadn't changed, corrected with the right
id on retry.

### Fix log

- [x] **#1 KRI auto-update fields** — added `auto_update_event_type`/
      `auto_update_notes` to `create_kri`'s INSERT and `update_kri`'s
      allowed-fields tuple (`modules/orm/data_service.py`); added an
      "Auto-update notes" input to the KRI modal and included both fields
      in `ormSaveKri`'s request body (`modules/orm/templates/index.html`).
      **Verified live:** created and updated a KRI with
      `auto_update_event_type='fraud'`/`'system_failure'`; DB confirms both
      persist correctly on create and update.
- [x] **#2 RCSA Controls + Actions UI** — built from scratch, since the
      backend routes already existed in full
      (`GET/POST/PUT/DELETE /api/rcsa/risks/{id}/controls` and
      `/api/rcsa/controls/{id}/actions`) and needed no changes. Added a
      nested "Controls" section under each Risk row in the RCSA drawer
      (add/edit/delete, design/operating effectiveness, test date, tested
      by, evidence notes, gap description), a nested Actions list per
      Control with its own add/edit/delete, and edit/delete icons on the
      existing flat "Remediation Actions" summary. All three share the
      existing `_DESIGN_EFF`/`_OPER_EFF` value vocab so the roll-up
      calculation reads what the UI writes.
      **Verified live, full lifecycle, in the actual browser:** created an
      assessment, added a risk (control effectiveness 60%, residual 3.6),
      added a control with Design=adequate/Operating=effective — the
      previously-dead roll-up fired immediately and correctly: effectiveness
      jumped to 100%, residual dropped to 0.0, health score to 100%. Added
      an action under that control, confirmed it rendered both nested and
      in the flat summary. Edited the action's status (in_progress →
      completed, confirmed via DB). Deleted the action and the control,
      confirmed both removed via DB.
- [x] **#3 Event Template basel_category** — added the same Basel III
      Category dropdown already used on the live Event modal to the
      Template modal, and added `basel_category` to `ormSaveTemplate`'s body.
      **Verified live:** created a template with Basel=Internal Fraud; DB
      confirms `basel_category='internal_fraud'`.
- [x] **#4 AIMS Risk implemented/scope_justification** — added an
      "Implemented" Yes/No select next to "In Scope", and a conditionally-
      shown "Scope Justification" field (only relevant when out of scope),
      to `ormOpenAimsRiskModal`/`ormSaveAimsRisk`.
      **Verified live:** created a risk with In Scope=No,
      Implemented=Yes, Scope Justification filled; DB confirms
      `in_scope=0, implemented=1`, and the justification text, all correct.
- [x] **#5 AIMS Risk-Control action_steps/responsible/interdependency** —
      added all three to the Link Control modal
      (`ormOpenAimsRiskControlModal`/`ormSaveAimsRiskControl`).
      **Verified live:** created a control link with all three filled; DB
      confirms all three persist correctly.

**Deliberately not fixed this pass:**

- [ ] **#6 `parent_event_id` has no write path** — needs a "link to parent
      event" picker UX decision (which events are eligible? one level or a
      full chain?) rather than a straightforward field-wiring fix; flagged
      for a future pass rather than designed under this one.

### Verification checklist

- [x] `python -m py_compile` on `modules/orm/data_service.py` — clean.
- [x] `orm/templates/index.html` parses cleanly via Jinja `get_template()`.
- [x] Full `pytest tests/` suite — 200 passed, 0 failed, both before and
      after every fix.
- [x] Live re-test of all 5 fixed create/update flows (KRI, Event Template,
      AIMS Risk, AIMS Risk-Control, and the full RCSA Control/Action
      lifecycle) — every field verified correct via direct DB query, not
      just assumed from a lack of errors.
- [x] Live re-test specifically confirming the RCSA effectiveness roll-up
      (`_recompute_risk_effectiveness`) now actually executes and produces
      correct numbers, since that was the entire point of building the
      Controls UI.
- [x] No server errors in the dev log across the whole verification pass
      (aside from the unrelated reload anomaly noted above, which affected
      test timing, not application behavior).
- [x] Test data cleanup: all `ORM-VERIFY` rows across all 8 touched tables
      deleted; confirmed zero rows remain via a text-search sweep.

---

## Open items carried forward (not yet scheduled)

- ARIA deep-dive
- Remaining personas from the original QA brief (audit_lead, risk_owner,
  bcm_manager, grc_officer, org_admin, employee)
- Load/performance testing
- Deliberate malformed-input / injection fuzzing
- Import/export round-trip testing
- Notifications
