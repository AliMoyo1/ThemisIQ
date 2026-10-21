# PLAN-34: ERM External Context — tailored sources + scheduled scan

## Status: IN PROGRESS (2026-08-31)

## Goal

Two improvements to the PLAN-28 emerging-risk inbox, both requested directly
by Ali after a review of the External Context page:

1. Replace the generic EU/US domain allowlist with one tailored to this
   deployment's actual sector (telecom) and jurisdiction (Zimbabwe/Africa,
   confirmed via `modules/grid/scheduler.py`'s `TZ = "Africa/Harare"`),
   plus AML/financial-services coverage given EcoCash.
2. Add a weekly scheduled scan (currently on-demand/button-only), reusing
   the existing per-module `scheduler.py` + `start_scheduler()`/
   `stop_scheduler()` convention already used by grid/sentinel/bcm/evidence/
   launcher/core/governance.

## Files to touch

1. `oneforall/config.py` — new `ERM_SCAN_ALLOWED_DOMAINS` default
2. `oneforall/modules/erm/data_service.py` — new `emerging_title_exists()` helper
3. `oneforall/modules/erm/ai_service.py` — dedupe check in both scan
   functions; new `run_emerging_scan()` shared orchestration function
4. `oneforall/modules/erm/routes.py` — simplify `/api/emerging/scan` to
   call the new shared function
5. `oneforall/modules/erm/scheduler.py` (NEW) — weekly job
6. `oneforall/main.py` — wire start/stop into app lifecycle

## Design notes

- `build_org_context()` and the AI scan functions are already global in
  scope (no org_id/business_unit_id filtering) — confirmed by reading
  `build_org_context` directly. `organizations` table exists but
  `business_units` has no `org_id` FK, so this deployment's multi-tenancy
  boundary is business-unit-within-one-org, not multi-org. A scheduled job
  calling the same functions the manual button already calls introduces no
  new scoping behavior.
- Adding a dedupe guard even though only 2 things were asked for: every
  other scheduler job in this codebase is explicitly idempotent (BCM's own
  docstring: "All jobs are safe to run repeatedly... checks existing tasks
  before creating"). Shipping a weekly recurring AI scan with zero
  duplicate protection would be inconsistent with that established bar,
  not a new feature — a scan that reruns weekly WILL resurface the same
  candidate repeatedly without it.
- Extracting `run_emerging_scan()` so route and scheduler share one code
  path rather than duplicating the grounded-then-fallback try/except.
- Timezone: Africa/Harare (CAT), matching GRID's scheduler and the org's
  actual operating timezone. Monday 06:00 CAT — ahead of BCM's Monday
  07:00/08:00 jobs, ready before the week's first review.
- Rate limiter (`check_ai_rate_limit`/`record_ai_call`) is a per-user
  human-abuse guard (60/hour); not applicable to a once-a-week system job,
  skipped for the scheduled path same as every other module's scheduler
  skips it.

## Changes log

- [x] Step 1: config.py domain list — 13 domains, replaced edpb.europa.eu +
      ico.org.uk (GDPR/UK-specific) with gsma.com, itu.int, rbz.co.zw,
      potraz.gov.zw, fatf-gafi.org
- [x] Step 2: data_service.py — emerging_title_exists() helper added before
      dismiss_emerging()
- [x] Step 3: ai_service.py — dedupe check added to both
      scan_emerging_risks_grounded and scan_emerging_risks loops;
      run_emerging_scan() added at end of file; import line extended for
      build_org_context + emerging_title_exists
- [x] Step 4: routes.py — /api/emerging/scan now calls ai.run_emerging_scan()
      instead of duplicating the grounded/fallback logic inline
- [x] Step 5: modules/erm/scheduler.py — new file, weekly Mon 06:00 CAT,
      modeled directly on modules/bcm/scheduler.py's structure
- [x] Step 6: main.py — start_scheduler wired after evidence scheduler in
      startup; stop_scheduler wired after evidence stop in shutdown
- [x] Step 7: verified
      - py_compile clean on all 6 touched files
      - runtime import smoke test: no circular imports, run_emerging_scan/
        emerging_title_exists/start_scheduler/stop_scheduler all resolve
      - test_erm_emerging.py: 1 failure on first run
        (test_scan_emerging_risks_grounded_citation_cross_check) --
        expected consequence of the new dedupe guard: scenario (b) reused
        the title "Cited Risk A" from scenario (a), which the guard
        correctly now treats as an existing item. Fixed the test to use a
        fresh title for (b) (the citation-trust behavior being tested
        doesn't depend on title). Re-ran: 8/8 passing.
      - full suite: all green, exit code 0, no regressions
      - scheduler runtime check: start_scheduler() in isolation registers
        erm_emerging_scan with next_run_time = next Monday 06:00 CAT;
        stop_scheduler() shuts down cleanly

## Status: COMPLETE (2026-08-31)
