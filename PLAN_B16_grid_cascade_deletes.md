# B16: Orphaned NC Evidence + Missing Audit Signoffs on Delete

**Bug:**
- `delete_nc()` at line 993 does not delete `grid_nc_evidence` rows
- `delete_audit()` at line 367 does not cascade to `grid_nc_evidence` or `grid_audit_signoffs`

**Fix:** Add explicit deletes for orphaned rows in both handlers.

**Files to touch:**
- `oneforall/modules/grid/data_service.py`

## Change Log

- [done] `oneforall/modules/grid/data_service.py:993` (delete_nc): added `DELETE FROM grid_nc_evidence WHERE nc_id=%s` before deleting the NC row
- [done] `oneforall/modules/grid/data_service.py:367` (delete_audit): added `DELETE FROM grid_nc_evidence WHERE nc_id IN (SELECT id FROM grid_non_conformances WHERE audit_id=%s)` before deleting NCs; added `DELETE FROM grid_audit_signoffs WHERE audit_id=%s` before deleting the audit row
- [done] Syntax check passed

## Status: COMPLETE
