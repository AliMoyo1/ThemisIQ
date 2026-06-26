# B21: delete_enterprise_risk() Orphans Workflow History and KRIs

**Bug:** `erm/data_service.py:142` — Deleting a risk leaves behind:
- `erm_risk_workflow_history` rows
- `erm_kris` rows linked to the risk
- `erm_kri_history` rows for those KRIs

**Fix:** Add explicit cascade deletes for all three tables before removing the risk row.

**Files to touch:**
- `oneforall/modules/erm/data_service.py`

## Change Log

- [done] `oneforall/modules/erm/data_service.py:142` (delete_enterprise_risk):
  - Added `UPDATE erm_kris SET linked_risk_id=NULL WHERE linked_risk_id=%s` — matches ON DELETE SET NULL intent from DDL; KRIs survive but lose their risk link
  - Added `DELETE FROM erm_risk_workflow_history WHERE risk_id=%s` — cleans workflow history before the risk row is removed
  - Note: erm_kri_history is NOT deleted; it belongs to the KRI, not the risk
- [done] Syntax check passed

## Status: COMPLETE
