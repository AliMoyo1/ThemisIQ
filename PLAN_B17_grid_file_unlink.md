# B17: Physical Evidence Files Not Deleted on Control Delete

**Bug:** `delete_control()` deletes `grid_evidence_files` rows but never calls `Path.unlink()`
on stored file paths. Physical files accumulate on disk silently.
The individual evidence delete route unlinks correctly — the cascade path does not.

**Fix:** Fetch file paths before deleting rows, then unlink each file.

**Files to touch:**
- `oneforall/modules/grid/data_service.py`

## Change Log

- [done] `oneforall/modules/grid/data_service.py` (imports): added `from pathlib import Path`
- [done] `oneforall/modules/grid/data_service.py:536` (delete_control): fetch `id` and `file_path` together before deleting rows; after DB commit, iterate file_paths and call `p.unlink()` on each real file (skips `aria://` virtual paths, swallows OSError if already gone)
- [done] Syntax check passed

## Status: COMPLETE
