# PLAN-T1.4: Residual Risk Engine

## Status: COMPLETE

## Goal
ERM adopts the ORM formula: `residual = L × I × (1 - weighted_effectiveness/100)`
where `weighted_effectiveness` is the weighted mean (0-100) of all canonical controls
linked to the risk via `risk_controls`. The user-entered `residual_L` / `residual_I`
fields become override fields respected only when both are non-null.

## Formula

```
weighted_effectiveness = sum(score_i * weight_i) / sum(weight_i)   [0-100]
residual_score         = round(L * I * (1 - weighted_effectiveness / 100))
```

If no controls linked: formula yields NULL (same as current "no override" state).
If override set (both residual_L and residual_I non-null): use `residual_L * residual_I` (unchanged).

## New column
- `erm_enterprise_risks.control_effectiveness` INTEGER: stored weighted mean (0-100) when formula used; NULL when override active.

## Cascade chain
T1.3 recompute_control() -> recompute_residuals_for_control() -> recompute_residual_for_risk() per linked risk

## Files to change

1. `database.py` - add `control_effectiveness` column to `_COLUMN_MIGRATIONS`
2. `modules/erm/data_service.py`:
   - `_formula_residual(db, risk_id, L, I)` - new: compute weighted mean from control_effectiveness_scores
   - `recompute_residual_for_risk(db, risk_id)` - new: read risk, apply formula, UPDATE row in place
   - `recompute_residuals_for_control(db, control_id)` - new: batch helper for all risks linked to a control
   - `_compute_scores()` - extend: when no residual override, call `_formula_residual`
   - `update_enterprise_risk()` - call `recompute_residual_for_risk` when L/I/residual fields change
   - `link_risk_control()` - call `recompute_residual_for_risk` after linking
   - `unlink_risk_control()` - call `recompute_residual_for_risk` after unlinking
3. `modules/governance/effectiveness.py` - at end of `recompute_control()`: call `recompute_residuals_for_control`
4. `modules/erm/routes.py` - add POST `/api/risks/{rid}/recompute-residual` endpoint
5. `modules/erm/templates/index.html` - risk drawer: show Controls Linked + Avg Effectiveness + Residual Method badge

## Change log

- [x] Add control_effectiveness column to _COLUMN_MIGRATIONS in database.py
- [x] Add _formula_residual() to erm/data_service.py
- [x] Add recompute_residual_for_risk() to erm/data_service.py
- [x] Add recompute_residuals_for_control() to erm/data_service.py
- [x] Call recompute_residual_for_risk in update_enterprise_risk
- [x] Call recompute_residual_for_risk in link_risk_control and unlink_risk_control
- [x] Hook cascade in governance/effectiveness.py recompute_control()
- [x] Add POST /api/risks/{rid}/recompute-residual to erm/routes.py
- [x] Update risk drawer UI in erm/templates/index.html
- [x] Fix test fixture: add missing columns to erm_enterprise_risks in test_governance_controls.py
- [x] py_compile clean on all touched files (database.py, erm/data_service.py, governance/effectiveness.py, erm/routes.py)
- [x] 91/91 stable tests pass (pre-existing failures unchanged)
- [x] Commit
