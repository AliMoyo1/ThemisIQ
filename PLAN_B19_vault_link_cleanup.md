# B19: Vault Evidence Links Not Cleaned on Evidence File Delete

**Bug:** `delete_evidence_file()` removes `grid_evidence_files` and `grid_approvals`
but leaves the corresponding `evidence_items` and `evidence_links` rows in the central
Evidence Vault. Deleted audit evidence stays visible in the vault.

**Fix:** Delete corresponding `evidence_links` rows (and orphaned `evidence_items` with
no remaining links) when a grid evidence file is deleted.

**Files to touch:**
- `oneforall/modules/grid/data_service.py`

## Change Log

- [done] `oneforall/modules/grid/data_service.py` (delete_evidence_file): added DELETE from evidence_items WHERE tags LIKE '%grid_evidence_id={eid}%' before deleting the grid_evidence_files row. evidence_links rows cascade-delete automatically via FK ON DELETE CASCADE on evidence_items.id.
- [done] Syntax check passed

## Status: COMPLETE
