# PLAN-28: ERM External Context - active tracking (2026-07-19)

## Status: COMPLETE

## Goal
See plans/PLAN-28-erm-external-context.md for full spec. Emerging risk
inbox with manual entries + AI horizon scan (grounded via Anthropic web
search tool, knowledge-only fallback otherwise), review workflow, and
add-to-register flow.

## Changes log

### Step 0: Create active plan file
- [x] plans/PLAN-28-active.md

### Step 1: database.py
- [x] erm_emerging_risks table (inserted after erm_objectives, auto-converted to PG)
- [x] verified against a fresh SQLite DB: table created correctly with all 14 columns

### Step 2: data_service.py
- [x] list_emerging (bu_scope-filtered, mirrors list_enterprise_risks) / create_emerging / dismiss_emerging / reopen_emerging
- [x] add_emerging_to_register (server-side idempotency guard)
- [x] build_org_context (pillars + active frameworks + top-5 categories, no PII)
- [x] delete_enterprise_risk: NULL added_risk_id cleanup
- [x] DEVIATION: create_enterprise_risk/update_enterprise_risk did not accept
      business_unit_id at all before this plan (schema column existed, RBAC
      already read it, nothing wrote it). Added it to both (writable field +
      INSERT column), matching the exact PLAN-27 precedent for objective_id/
      risk_context, since add_emerging_to_register's "copy it onto the created
      risk" instruction was otherwise a no-op. Small, symmetric, in-pattern.
- [x] py_compile clean

### Step 3: AI generator (two modes)
- [x] config.py: ERM_SCAN_MODEL (claude-sonnet-5), ERM_SCAN_MAX_SEARCHES (8), ERM_SCAN_ALLOWED_DOMAINS (10 seeded domains)
- [x] core/ai_client.py: create_message_web_search (mixed-block parsing, pause_turn
      continuation capped at 3, 400+"web search" -> distinct RuntimeError, anthropic-only guard)
- [x] erm/ai_service.py: scan_emerging_risks_grounded (citation cross-check, discards
      uncited source_url) + scan_emerging_risks (knowledge-only, forbids source_url)
- [x] py_compile clean + runtime import smoke test passed (no circular imports)

### Step 4: routes.py
- [x] GET/POST /api/emerging + dismiss/reopen/add-to-register (ERM_RISK_IDENTIFIED emit on add)
- [x] POST /api/emerging/scan (try-grounded-then-fallback via broad except, no provider pre-check needed
      since create_message_web_search's own guard raises RuntimeError for non-anthropic)
- [x] "external" added to _SPA_PAGES
- [x] py_compile clean

### Step 5: UI
- [x] New "external" SPA page (nav-visible to every ERM user, no capability gate
      unlike Objectives & Pillars), status chip filter (New/Dismissed/Added/All)
- [x] Manual add modal (title/summary/pillar/standard_ref/source_note/source_url)
- [x] Scan button (spinner while POSTing, toast labels live web scan vs model
      knowledge only) + per-card caveat banner for ai_scan + source link for ai_scan_web
- [x] DEVIATION: skipped the spec's "disabled note when AI is off" - grepped for
      how the chat page detects that and found no such client-side mechanism
      exists (chat just always renders and the backend stub degrades
      gracefully). Reused that same graceful-degradation approach: scan always
      clickable, 0-created case shows an honest "0 candidates added" toast.
- [x] "View risk" uses a plain <a href> (no data-spa) so a real page load fires
      the existing PLAN-06 deep-link boot handler; add-to-register's JS success
      path uses window.location.href for the same reason (SPA-internal
      navigate() would not re-trigger that load-time-only handler)
- [x] JS syntax verified via node --check

### Step 6: tests - oneforall/tests/test_erm_emerging.py
- [x] 8 test cases, all passing
- [x] Fixed during first run: 2 tests hit a real FOREIGN KEY constraint failure
      (erm_enterprise_risks.created_by REFERENCES users(id); the fresh test_db
      has zero seeded users, and my test passed a hardcoded user_id=1 that
      didn't exist there). Not an application bug -- every prior PLAN-2x test
      that called create_enterprise_risk simply never set created_by at all
      (NULL always satisfies a nullable FK). Added a _create_user(db) test
      helper and used its real id instead of a hardcoded 1.

### Step 7: verify
- [x] py_compile clean on database.py, config.py, core/ai_client.py,
      modules/erm/data_service.py, modules/erm/ai_service.py,
      modules/erm/routes.py, tests/test_erm_emerging.py
- [x] full pytest: 156/156 passing (148 pre-existing + 8 new), 0 regressions
- [x] live browser pass (temp super_admin `_plan28_verify`, id 13):
  - Manual add: created "PLAN28 Manual Test Item" (pillar Technology &
    Innovation, source_note "Internal analyst review") -- rendered with
    "Manual" origin badge.
  - Dismiss -> item left "New" filter, appeared under "Dismissed" with
    a Reopen button. Reopen -> reverse, back under "New" with
    Dismiss/Add-to-register buttons. Both transitions correct.
  - Add-to-register -> POST succeeded, client did a real
    `window.location.href` navigation to `/erm/register?open=risk:N`
    (not SPA-internal), which correctly fired the PLAN-06 deep-link
    boot handler on page load and auto-opened the risk drawer.
  - Created risk (id 275, RSK-0024) verified via direct API fetch of
    `/erm/api/risks/275`: `impacted_pillar: "Technology & Innovation"`,
    `risk_context: "external"`, description =
    "Manually entered emerging risk for verification purposes.\n\nSource:
    external context inbox. Internal analyst review" -- confirms the
    pillar copy-through, risk_context tagging, and description-suffix
    concatenation in add_emerging_to_register all work correctly
    end-to-end, not just at the unit-test level. Drawer additionally
    rendered the "Risk Context: External" badge (reusing the PLAN-27
    drawer badge) and correct inherent/residual scores (3x3=9,
    moderate).
  - AI-disabled scan: clicked "Scan for emerging risks" with no
    ANTHROPIC_API_KEY configured in this dev environment. Response:
    HTTP 200, `{"created":0,"grounded":false}` -- no 500, graceful
    degradation confirmed. Verified client-side toast wording via
    source read (`extRunScan`, index.html:3623): for `n=0` the message
    is "0 candidates added (model knowledge only)", using the normal
    (non-error) `showToast` path -- satisfies "the UI toast must handle
    '0 candidates added' without implying an error."
  - Real grounded scan: SKIPPED. No ANTHROPIC_API_KEY configured in this
    dev environment (confirmed via `config.settings.ANTHROPIC_API_KEY`
    empty) -- per the plan's own instruction to skip gracefully and note
    it here. Grounded-mode citation cross-check logic is covered instead
    by `test_scan_emerging_risks_grounded_citation_cross_check` and
    `test_create_message_web_search_pause_turn_continuation` at the unit
    level (mocked HTTP/API boundary).
  - Cleanup: deleted risk 275 via `DELETE /erm/api/risks/275` (confirmed
    `delete_enterprise_risk` correctly left `erm_emerging_risks.added_risk_id`
    NULL on the inbox row, matching test 5's exact scenario, before that
    row was itself deleted). Deleted the `erm_emerging_risks` inbox row
    directly (no API delete route exists for it by design -- it's an
    inbox, not an individually-manageable record). Deleted temp user
    `_plan28_verify` (id 13) and every row referencing it discovered via
    a schema scan for `REFERENCES users` (user_roles, sessions,
    audit_log, events, notifications -- 1 row each). Final state
    confirmed: 0 rows in erm_emerging_risks, 23 enterprise risks (back
    to the pre-session count), users back to the original 4
    (admin/compliance/dpo/bcm).
- [x] update plans/README.md

## Round 6 complete
PLAN-23 through PLAN-28 are all now DONE. This was the last plan in the
round; no further plan has been assigned.
