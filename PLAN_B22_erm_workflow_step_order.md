# B22: ERM Workflow Allows Skipping Steps

**Bug:** `transition_workflow()` validates that the target step exists but does not
enforce sequential progression. A user can jump from "draft" directly to "closed",
bypassing assessment and treatment steps entirely.

**Fix:** Enforce that forward transitions only advance one step at a time. Backward
transitions (returns) can go to any earlier step.

**Files to touch:**
- `oneforall/modules/erm/data_service.py`

## Change Log

- [done] `oneforall/modules/erm/data_service.py` (transition_workflow): after validating to_step is in _WORKFLOW_STEPS, compute from_idx and to_idx; raise ValueError if to_idx > from_idx + 1, naming the step that must come first. Backward transitions (to_idx < from_idx) are unrestricted — allows returns/revisions.
- [done] Syntax check passed

## Status: COMPLETE
