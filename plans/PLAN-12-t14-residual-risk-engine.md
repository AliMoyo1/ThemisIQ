# PLAN-12: Governance Graph T1.4 — Unified Residual Risk Engine

## PREREQUISITES — strict order

1. PLAN-05 (T1.2 — `risk_controls` bridge) implemented.
2. PLAN-11 (T1.3 — effectiveness engine + `residual_hook` seam) implemented.

If `grep -n "def residual_hook" oneforall/core/effectiveness.py` finds
nothing, STOP.

## Goal

Roadmap T1.4, the last block of the approved "Tier 1 in full". Today the
platform has two contradictory residual-risk models:

- ERM: `residual = residual_likelihood × residual_impact`, both typed by
  the user with no connection to controls
  (`modules/erm/data_service.py` `_compute_scores`).
- ORM RCSA: `residual = L × I × (1 − control_effectiveness/5)` with a
  manually typed 1-5 effectiveness
  (`modules/orm/data_service.py:529` and `:554`).

After this plan:

- ONE shared formula helper used by both modules:
  `residual_from(l, i, eff_5) = round(l * i * (1 - eff_5/5), 2)`.
- ERM risks that have linked controls get a **derived** residual, where
  `eff_5` comes from the live T1.3 scores (weighted mean of linked
  controls, mapped score/20 → 0-5).
- User-entered `residual_likelihood × residual_impact` becomes an
  explicit **manual override** with visible provenance
  (`residual_source` = 'manual' | 'derived' | NULL).
- Residuals recompute automatically when control effectiveness changes
  (via the `residual_hook` seam) and when controls are linked/unlinked.

## Exact files to touch

1. `oneforall/database.py` — 2 column migrations
2. `oneforall/core/effectiveness.py` — shared formula + fill the
   `residual_hook` seam
3. `oneforall/modules/erm/data_service.py` — `_compute_scores` precedence
   + `recompute_derived_residuals()` + link/unlink triggers
4. `oneforall/modules/orm/data_service.py` — replace the two inline
   formulas with the shared helper (lines ~529 and ~554)
5. `oneforall/modules/erm/templates/index.html` — provenance badge in
   drawer + CSV column
6. `oneforall/tests/test_residual_engine.py` — new tests

## Step-by-step order

### Step 1 — Columns

Append to `_COLUMN_MIGRATIONS` in database.py:

```python
        # ── Residual Risk Engine (T1.4) ────────────────────────────────────────
        ("erm_enterprise_risks", "residual_score",  "REAL"),
        ("erm_enterprise_risks", "residual_source", "TEXT"),
]
```

FIRST check whether `residual_score` already exists on
`erm_enterprise_risks` (read the CREATE TABLE at database.py ~2920 and
grep `residual_score` in erm/data_service.py — the current code may
compute it on the fly rather than store it). If it is computed-only
today, the new stored column becomes the single source the UI reads;
if a column already exists, add only `residual_source`.

### Step 2 — Shared formula in core/effectiveness.py

```python
def residual_from(likelihood, impact, eff_5) -> float:
    """Unified residual formula (T1.4): residual = L*I*(1 - eff/5).
    eff_5 is on the 0-5 scale (5 = fully effective => residual 0)."""
    l = int(likelihood or 3); i = int(impact or 3)
    e = max(0.0, min(5.0, float(eff_5 or 0)))
    return round(l * i * (1 - e / 5), 2)

def effectiveness_5_for_risk(db, risk_id) -> "float | None":
    """Weighted mean of linked controls' current scores, mapped to 0-5.
    None when the risk has no control links (caller falls back)."""
```

`effectiveness_5_for_risk`: read `risk_controls` rows (control_id,
weight) for the risk; fetch current scores via `get_current_scores`;
weighted mean of score×weight / sum(weight); divide by 20. Controls
with no score yet count as score 0 (unproven control = no risk
reduction — state this in the docstring). Zero links → None.

### Step 3 — ERM precedence logic

In `modules/erm/data_service.py`, READ `_compute_scores` fully, then
change its residual section to this exact precedence:

1. If `residual_likelihood` AND `residual_impact` are both non-null →
   `residual_score = rl × ri`, `residual_source = 'manual'`
   (existing behavior, now labeled).
2. Else call `effectiveness_5_for_risk(db, risk_id)`:
   non-None → `residual_score = residual_from(l, i, eff5)`,
   `residual_source = 'derived'`.
3. Else → `residual_score = NULL`, `residual_source = NULL`.

CAREFUL: `_compute_scores` today may be a pure function without db
access or risk_id — READ its signature and call sites first. If it is
pure, do NOT force db into it; instead apply step-2 logic in
`create_enterprise_risk` / `update_enterprise_risk` immediately after
the existing `_compute_scores` call, where `db` and the new row id are
in scope.

Add:

```python
def recompute_derived_residuals(db, control_id=None) -> int:
```

- control_id given → only risks linked to it via `risk_controls`;
  else all risks.
- Skip rows where both residual_likelihood and residual_impact are set
  (manual override wins — never overwrite it).
- For each: recompute via steps 2-3, UPDATE `residual_score`,
  `residual_source`, `updated_at`. No commit (caller commits). Return
  count changed.

Wire the triggers:
- In `link_risk_control` / `unlink_risk_control` (PLAN-05): after the
  insert/delete, recompute for that one risk, same transaction.
- In `core/effectiveness.py`, REPLACE the `residual_hook` no-op body:

```python
def residual_hook(db, control_id):
    from modules.erm.data_service import recompute_derived_residuals
    try:
        recompute_derived_residuals(db, control_id=control_id)
    except Exception:
        logging.getLogger("oneforall.effectiveness").exception(
            "residual recompute failed for control %s", control_id)
```

(Import inside the function — module-top import would cycle.)

### Step 4 — ORM convergence

In `modules/orm/data_service.py`, replace both inline formulas:

- Line ~529: `residual = round(il * ii * (1 - ce / 5), 2)` →
  `residual = residual_from(il, ii, ce)`
- Line ~554: same replacement inside `update_rcsa_risk`.

Import `from core.effectiveness import residual_from` at the top of
the file. Numerically identical output (same formula), but now ONE
definition exists platform-wide — the convergence T1.4 requires.

### Step 5 — UI provenance

In `modules/erm/templates/index.html`:

- Risk drawer residual card: append a small chip — "manual override"
  when `residual_source==='manual'`, "derived from controls" when
  `'derived'`, nothing otherwise. Find the residual render site by
  grepping `residual` in the template; READ the surrounding markup and
  match its classes.
- Edit modal: under the residual L/I inputs add one muted hint line:
  "Leave residual fields empty to derive residual risk from linked
  controls."
- CSV export: add a `Residual Source` column next to the existing
  residual column (grep the export function; carry the field through).

### Step 6 — Nightly + tests + verify

- Nightly: in the same scheduler block PLAN-11 added, after
  `recompute_all(db)` add
  `recompute_derived_residuals(db)` (import alongside), commit once.
- `tests/test_residual_engine.py`:
  1. `residual_from(4, 5, 0)` == 20.0; `(4, 5, 5)` == 0.0;
     `(4, 5, 2.5)` == 10.0; clamping: eff 7 → treated as 5.
  2. Manual override wins: risk with residual_L/I set keeps
     `rl*ri` and `residual_source='manual'` even with linked controls.
  3. Derived path: risk + one linked control with a known score (insert
     a `control_effectiveness_scores` row directly, e.g. score 60 →
     eff_5 3.0) → residual == `residual_from(l, i, 3.0)`, source
     'derived'.
  4. Unlink the control → residual becomes NULL, source NULL.
  Cleanup everything.
- `py_compile`, full pytest, live browser: create a risk with L4/I4 and
  empty residual fields → link a control (PLAN-05 UI) → drawer shows a
  derived residual + chip; type residual L/I into the edit modal →
  chip flips to manual and the number changes; ORM RCSA still computes
  identically to before (spot-check one RCSA risk).
- Commit:
  `Add unified Residual Risk Engine (T1.4): derived residuals with manual override provenance`.

## Edge cases a weaker model would miss

- **Never overwrite a manual override.** The recompute loop's WHERE
  must exclude rows with both residual_L and residual_I set. Deleting
  a user's judgment call silently is the worst failure mode this
  feature can have.
- **One residual_L set but residual_I NULL (half-filled override)** —
  treat as NOT overridden (both-or-nothing), matching how
  `_compute_scores` treats the pair today (verify by reading it; if
  today's code computes with one side NULL, keep whatever it does for
  backward compatibility and document).
- **Unscored controls count as zero effectiveness, not "skip".**
  Skipping them would make linking an untested control REDUCE
  residual risk — backwards. The docstring in Step 2 states this;
  keep the behavior.
- **`residual_hook` runs inside `compute_control_effectiveness`,
  which runs inside event handlers** — the whole chain must stay
  cheap (one control → few risks → few UPDATEs). Do not call
  `recompute_derived_residuals(db)` with no control_id from the hook.
- **The scheduler block commits once after BOTH recomputes** — two
  commits are fine too, but zero commits (forgetting because both
  functions are no-commit by design) silently discards the nightly
  work. Add the explicit `db.commit()` and a test-time reminder in
  the code comment.
- **`recompute_risk_bands` (Slice 2) rewrites `qualitative_score` —
  a DIFFERENT column** (inherent band). Do not touch it, and do not
  let the new residual logic write to it.
- **ORM's `ce` is already 1-5 with 5=effective** (the direction flip
  was deliberate in Slice 1 — see the plan document). `residual_from`
  keeps that direction. Do not "fix" the direction.
- **CSV escaping:** the new column value is one of three fixed strings
  — still route it through the export's existing escaping to keep the
  row shape uniform.

## Acceptance criteria

1. All 4 tests pass; full suite green.
2. Formula convergence proven:
   `grep -rn "1 - ce / 5\|1 - e / 5\|(1 - " oneforall/modules/orm/data_service.py`
   shows no inline formula remains — only `residual_from` calls.
3. Live: link/unlink flips a risk between derived and NULL; manual
   entry flips to manual and survives a control-effectiveness change.
4. Nightly path executes both recomputes and commits (run the job
   function manually in a shell; observe the log line and a changed
   `updated_at`).
5. An RCSA risk created before and after this change with identical
   inputs stores an identical residual_score.
