# B18: NC and Control Status Accept Arbitrary Strings

**Bug:** `update_nc()` accepts any status/cap_status value. `advance_cap_status()` and
`revert_cap_status()` use `_CAP_STATUSES.index(current)` which raises ValueError on
unknown values. Setting an invalid cap_status via PUT permanently breaks the NC workflow.

**Fix:** Validate status and cap_status against allowed sets before writing.

**Files to touch:**
- `oneforall/modules/grid/data_service.py`

## Change Log

- [done] `oneforall/modules/grid/data_service.py` (after _CAP_STATUSES): added `_NC_STATUSES = {"open", "closed"}` and `_NC_SEVERITIES = {"minor", "major", "critical"}` constants
- [done] `update_nc()`: replaced `if col in data` block with validation — skips any status/cap_status/severity value not in the allowed set; no error raised (bad values silently dropped to avoid breaking partial updates from the UI)
- [done] Syntax check passed

## Status: COMPLETE
