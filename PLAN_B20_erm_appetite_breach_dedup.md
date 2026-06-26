# B20: ERM Appetite Breach Events Fire on Every Dashboard Refresh

**Bug:** `api_appetite_status` is a GET endpoint that emits `ERM_APPETITE_BREACHED` events
(and potentially notification emails) on every call. No deduplication. Every dashboard
load or polling interval fires the event repeatedly.

**Fix:** Add `last_breach_notified_at` column to `erm_risk_appetite`. Only emit the event
if the category has been in breach for the first time, or has not been notified within
24 hours.

**Files to touch:**
- `oneforall/database.py` — add ALTER to add `last_breach_notified_at` column
- `oneforall/modules/erm/routes.py` or `erm/data_service.py` — patch the breach event logic

## Change Log

- [done] `oneforall/database.py:3270` (_COLUMN_MIGRATIONS): added `("erm_risk_appetite", "last_breach_notified_at", "TEXT")` — auto-migrates on app startup for both SQLite and PostgreSQL
- [done] `oneforall/modules/erm/data_service.py` (after get_appetite_status): added `mark_appetite_notified(appetite_id, is_breached)` — sets or clears last_breach_notified_at
- [done] `oneforall/modules/erm/routes.py` (api_appetite_status): added `utcnow`/`to_dt` imports; replaced unconditional emit with dedup check — only emits if never notified or last notification was over 24 hours ago; clears timestamp when breach resolves so next breach fires again
- [done] Syntax check passed on all 3 files

## Status: COMPLETE
