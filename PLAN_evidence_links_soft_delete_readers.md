# PLAN: evidence_links soft delete, readers outside the Vault

Status: complete, 2026-10-07. Working tree only, nothing committed or pushed (HEAD is still eec119f).

## Goal

Unlinking evidence is a soft delete (`evidence_links.deleted_at` is set, the row stays). The Evidence Vault read paths already count only live links (see `design/evidence-vault/PHASE-1A.md` in the main checkout, uncommitted there). These readers outside the Vault still count removed links and need `el.deleted_at IS NULL`.

## Files to touch

| Reader | Lines at HEAD eec119f | Effect of the bug |
| --- | --- | --- |
| `modules/governance/effectiveness.py` | 62 (evidence_uploaded), 77 (evidence_valid) | An unlinked item still earns the 20 point factor, and an unlinked expiring item can still zero the 15 point factor |
| `modules/erm/data_service.py` `list_risk_controls` | 999, docstring 992 | Risk control list shows an inflated evidence_count; docstring wrongly says there is no soft delete column |
| `modules/aria/routes.py` | 366 (frameworks list), 480 (framework detail) | Evidence counts include removed links |
| `modules/bcm/routes.py` | 440 (plan detail), 620 (incident detail) | Removed links still listed and counted |
| `modules/evidence/scheduler.py` | 149 (optional) | Over-selects controls for recompute |
| `tests/test_governance_controls.py` | 95 | Hand built `evidence_links` table lacks `deleted_at`; needed once `list_risk_controls` filters on it |

Out of bounds: the Vault module (`modules/evidence/`), and the Vault read fixes that live uncommitted in the main checkout (grid picker, bcm `search_vault_items`, topbar search).

## Approach

1. One new test file, `tests/test_removed_links_outside_vault.py`, SQLite via `test_db`, same helpers as `test_evidence_vault_reads.py` (insert item, one live link, one link with `deleted_at` set, assert only the live one counts). Each test also asserts the live link still counts, so a broken query cannot pass by returning zero.
2. Run the new tests against unfixed source first and read each failure (red).
3. Add the condition to each query, fix the docstring, rerun (green).
4. Run the neighbouring suites and the full backend suite with the project venv python.
5. Report what changed, including the lower effectiveness scores.

## Change log

- [done] `tests/test_removed_links_outside_vault.py` (new): 7 tests, one per query (effectiveness x2, ERM x1, ARIA x2, BCM x2).
- [done] Red run against unfixed source: 7 failed, each on an over-count (e.g. ARIA list 3 vs 1, BCM lists the removed item, effectiveness `evidence_uploaded` 1 vs 0). Positive controls (live link still counts) matched in every diff, so the queries do execute.
- [done] `modules/governance/effectiveness.py`: `AND el.deleted_at IS NULL` added to both queries (evidence_uploaded, evidence_valid).
- [done] `modules/erm/data_service.py` `list_risk_controls`: condition added to the evidence_count subquery; docstring corrected (the column exists, added in database.py).
- [done] `modules/aria/routes.py`: condition added to the frameworks list count and the framework detail per-control count.
- [done] `modules/bcm/routes.py`: condition added to the plan detail and incident detail evidence lists.
- [done] Green run: 7 new tests pass.
- [found] Existing `tests/test_governance_controls.py` hand builds `evidence_links` without `deleted_at`; after the ERM fix 4 of its tests crashed with "no such column: el.deleted_at".
- [done] `tests/test_governance_controls.py`: added `deleted_at TEXT` to that hand built table so it matches the real schema.
- [done] Mutation check on a scratch copy of the tree (real worktree untouched): removing each of the 7 added conditions one at a time fails exactly the one matching test, 7 of 7. Script is in the session scratchpad, not in the repo.
- [checked] `modules/bcm/data_service.py` `list_incident_vault_links` and `link_incident_vault_item` already filter `deleted_at IS NULL`; the incident detail route was the outlier.
- [checked] PostgreSQL: `evidence_links.deleted_at` comes from `_COLUMN_MIGRATIONS`, applied by both `_run_sqlite_alters` and `_run_pg_alters` (ADD COLUMN IF NOT EXISTS). The predicate is plain `IS NULL`. PostgreSQL itself was not run (none available locally).
- [checked] Merge overlap with the main checkout's uncommitted Vault work: only `bcm/routes.py` is touched in both. Main's single hunk is `api_vault_evidence_search` near line 804; mine are near 444 and 624. No textual overlap.
- [done] Browser tests from `oneforall/` as working directory: `tests/ui/test_action_surface_browser.py` (renders `/aria/frameworks` against the changed SQL) and `tests/ui/test_evidence_module_links.py`, 4 passed, none skipped. Gotcha: launched from the repo root the UI harness fails with `TemplateNotFound` because template folders are resolved against the working directory; that is environment, not code.
- [checked] `git apply --check` of my tracked-file patch against the main checkout's current working tree (read-only): applies cleanly, including `bcm/routes.py` next to the Vault hunk.
- [note] First full backend run was launched from the repo root while I ran other pytest sessions in parallel: 897 passed, 15 skipped (all real PostgreSQL tests), 2 failed. Both are explained and neither touches evidence links: `test_template_compilation` needs `oneforall/` as the working directory (passes there); `test_retention_sweep_skips_entirely_when_another_worker_holds_the_lock` raised `unable to open database file` once, and passes alone from either directory and with its whole file (42 passed). Clean rerun from `oneforall/` with nothing else running: 899 passed, 15 skipped, 0 failed (9 min 26 s). Neither failure recurred.
- [done] Browser tests from `oneforall/`, 11 passed in total and none skipped: action surface, evidence module links, BCM exercise workspace routes, BCM workflows, ARIA managed edit, module route survey.
- [done] Dash check on the 12 added lines of the tracked diff and on both new files: no em or en dashes.

## Summary

Changed (uncommitted):

- `modules/governance/effectiveness.py`: `el.deleted_at IS NULL` on the evidence_uploaded and evidence_valid queries.
- `modules/erm/data_service.py`: same condition on the `list_risk_controls` evidence_count; docstring corrected.
- `modules/aria/routes.py`: same condition on the frameworks list count and the framework detail per control count.
- `modules/bcm/routes.py`: same condition on the plan detail and incident detail evidence lists.
- `modules/grid/data_service.py`: same condition on the "already linked" check in `attach_vault_item_to_grid_control` (Phase 2).
- `tests/test_removed_links_outside_vault.py` (new): 9 regression tests, one per query (7) plus the GRID attach pair (2).
- `tests/test_governance_controls.py`: its hand built `evidence_links` table gains `deleted_at TEXT`.

Verified: the 7 query tests fail on the unfixed code and pass on the fixed code, and removing any single one of those 7 conditions fails exactly its own test. The GRID attach test failed before its fix (`(0, 1)` instead of `(1, 2)`) and passes after. Final full backend suite on the finished tree: 901 passed, 15 skipped, 0 failed (8 min 24 s). 11 browser tests passed (run before the GRID change, which no browser test exercises).

Not verified: PostgreSQL. None is available locally, so the 15 real PostgreSQL tests skipped. The predicate is plain `IS NULL` on a column that both backends get from `_COLUMN_MIGRATIONS`.

Effect on scores: a control whose only evidence link was removed loses the evidence_uploaded factor (20) and the evidence_valid factor (15, only awarded when evidence is uploaded), so up to 35 points. A control whose removed link pointed at an item expiring within 7 days can gain the 15 point factor. Stored scores change at the next recompute (nightly 03:00 UTC job, audit completed, control status change, high or critical ORM event, or the manual recompute endpoint). Each recompute cascades into ERM residual risk, so residual risk rises on risks whose controls lose points.

Left for a decision (at the time of the first report): the scheduler query (see above), the GRID re-attach sibling bug (see above), and a recompute at unlink time (Vault module, out of bounds). Resolved in Phase 2 below.

## Phase 2: follow-ups taken (user said "go with your recommendations")

- [decision] `modules/evidence/scheduler.py` stays unchanged. Recommendation unchanged: harmless over-selection that incidentally refreshes stale scores.
- [found] Re-read `attach_vault_item_to_grid_control`: the unfiltered "already linked" check at the end of the function is only reached when no `grid_evidence_files` row exists yet for the control and item. The first report described the bug too broadly. Exact path: item linked to the GRID control from the Vault, unlinked there (soft delete), then attached from GRID. The function finds the removed row, skips the insert, and no live link exists.
- [done] Red run first: new test `test_grid_attach_creates_a_live_link_when_the_old_link_was_removed` failed with `(live, total) == (0, 1)`, expected `(1, 2)`. Positive control `test_grid_attach_does_not_duplicate_a_live_link` passed.
- [done] `modules/grid/data_service.py` `attach_vault_item_to_grid_control`: `AND deleted_at IS NULL` added to the "already linked" SELECT. A fresh live link is inserted and the removed row is kept as the audit trail. No unique constraint exists on `evidence_links`, so inserting beside a removed row is allowed.
- [done] Green: 24 passed across the new file (9 tests), `test_grid_backup_rls.py`, `test_grid_nc_bu_isolation.py`, `test_governance_controls.py`.
- [checked] No browser test exercises `POST /grid/api/controls/{cid}/attach-vault`; the backend tests are the coverage.
- [checked] Cumulative tracked-file patch applies cleanly to the main checkout working tree (`git apply --check`); the GRID hunk lands 4 lines offset because the Vault work sits earlier in the same file.
- [not done, on purpose] Same gap remains on the GRID-first path: an item first attached from GRID has a `grid_evidence_files` row, so re-attaching returns early before any link check. That is a design gap (unlinking in the Vault does not detach the GRID file), not a read of removed links, so it is left alone.
- [not done, on purpose] Recompute of control effectiveness at unlink time. The unlink route emits no event and nothing else hooks it, so the only place is inside the Vault module, which was ruled out. Hook points for whoever does the Vault work: `api_evidence_link_delete`, `api_evidence_delete` and `api_evidence_bulk_archive` (soft deletes), and `api_evidence_permanent_delete` (hard delete) in `modules/evidence/routes.py`. After each, collect the affected links with `entity_type='canonical_control'` and call `recompute_controls_by_ids(db, cids)` from `modules/governance/effectiveness.py`.
- [decision] `modules/evidence/scheduler.py` line ~149 left unchanged. It only picks which controls to recompute. Over-selecting is harmless, and with the corrected scoring it incidentally refreshes the stale score of a control whose only expiring item was unlinked. The real gap is that nothing recomputes at unlink time (Vault module, out of bounds).
- [found, not changed] `modules/grid/data_service.py` `attach_vault_item_to_grid_control` (~2890): the "ensure vault link exists" check does not filter `deleted_at`, so re-attaching an item to a GRID control after it was unlinked finds the removed row, inserts no new link, and leaves no live link. Not on the list, and `grid/data_service.py` is also modified in the main checkout, so left for a decision.
