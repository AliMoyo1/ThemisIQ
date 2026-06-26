# B15: N+1 Queries in GRID Evidence Completeness Check

**Bug:** `grid/data_service.py:1241` — For every control in an audit, 5-7 separate COUNT queries
run inside a Python loop. A 100-control audit fires ~700 database queries.

**Fix:** Replace with a single aggregate query using GROUP BY control_id.

**Files to touch:**
- `oneforall/modules/grid/data_service.py`

## Change Log

- [done] `oneforall/modules/grid/data_service.py:1220` — replaced `get_evidence_completeness()` loop (5-7 queries per control) with 3 aggregate queries total:
  - Query 1: controls list (unchanged)
  - Query 2: `grid_evidence_files` GROUP BY control_id with CASE/SUM for approved/pending/rejected counts
  - Query 3: `grid_evidence_items` LEFT JOIN `grid_evidence_files` GROUP BY control_id for item counts
  - Python loop now just merges pre-fetched dicts, no DB calls
  - For a 100-control audit: was ~700 queries, now 3
- [done] Syntax check passed

## Status: COMPLETE
