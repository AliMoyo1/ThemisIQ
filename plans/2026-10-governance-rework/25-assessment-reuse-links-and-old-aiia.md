# Plan 25: reusing earlier assessments (CISO 02), the rest of PLAN-37 Slice 1, and old AI impact assessments

**Status:** In progress on branch `claude/ciso-reuse`, stacked on `claude/ciso-assurance` (plan 24), started 2026-11-03.

**Owner's words (chat, 2026-11-03):** "finish CISO 02, Plan 37 and older AI impact assessments".

## 1. What was still open, checked against the code

| Item | Source | Found in the code |
|---|---|---|
| Reusing an earlier audit's reviewed answers and proof | [CISO 02](../ciso-assistant-features/02-cross-framework-assessment-reuse.md) | Not built. `grid_control_mappings` rows exist, with no reviewed state; IMS audits copy `ims_equivalent` links from ARIA without review |
| One relationship service | PLAN-37 Slice 1 | Built: `modules/governance/relationships.py` is the one place Related Items, the Vault and `core/links.py` rules meet. Nothing left to fold |
| Link write permissions | PLAN-37 Slice 1, `PLAN_close_open_findings.md` | Open: `_may_write` lets anyone who can see both records link them (only AI systems have a stricter rule), so a read-only role can link |
| Picker mismatch | PLAN-37 Slice 1 | Open: search names Vault files `platform/evidence`, the relationship service knows only `evidence/item`, so linking a file picked from search fails |
| Old AI impact assessments not linked to a system | AI Governance ledger (05), plan 06 section 6 | The "not linked" filter and a manual "Link to a system" action exist. The suggested match the ledger lists as not built is missing |

## 2. Research

- **CISO Assistant audit mapping** (AGPL-3.0, ideas only): a new audit can be prefilled from an existing one through a mapping between frameworks; the preview shows what would be set. Taken: preview before apply, one hop only. Not taken: setting the target's result automatically (CISO 02 forbids it).
- Name matching for the old assessments uses the standard library only (token overlap); no fuzzy matching package is added for a list a person confirms row by row.

## 3. Design

### CISO 02: Reuse an earlier audit

| Piece | Built as |
|---|---|
| Mapping review | `grid_control_mappings` gains `reviewed_by`, `reviewed_at`, `review_kind` (`equivalent` or `partial`). A row nobody reviewed is treated as partial, whatever its type says |
| Relation of a target control to the chosen source audit | full: the same requirement (same canonical control, or same framework and reference) or a reviewed equivalent mapping; partial: an unreviewed or partial mapping; none otherwise. One hop only |
| Preview | per target control: its current state, the source control, the relation and why, the source's accepted answer (from audit questions), its proof the viewer may open (approved GRID files, accepted Vault links) with what has expired, and what applying would do. Both audits must be in the viewer's scope; a source record they cannot open is left out |
| Apply | audit lead, selected rows, each with the fingerprint it was previewed with (a changed source or target refuses with "refresh"). Full: the source's current proof is linked to the target control as a suggestion waiting for review, and the source answer is added as a comment marked "Suggested, not yet assessed". Partial: proof only. Never changes the target's status. Idempotent |
| History and undo | `grid_reuse_decisions` and `grid_reuse_rows` keep who, when, both snapshots and what was created; undo removes what it created while none of it has been reviewed |
| Page | GRID: "Reuse an earlier audit" (`/grid/reuse/`) |

### PLAN-37

- A person may create or remove a link only if they may change at least one of its two records (each kind's write capability, the one its own module's edit routes require), as well as open both. AI systems keep their stricter rule.
- `platform/evidence` is an accepted spelling of `evidence/item`.

### Old AI impact assessments

- In the impact assessment list, an assessment not linked to a system shows a suggested system when its recorded system name or title matches one the person may open, with a one-click "Link" that uses the existing link action (same checks, same version). Nothing is linked without that click.

## 4. Decisions (chat confirmation, not sign-off)

(Filled in as slices finish.)

## 5. Build log

(Filled in as slices finish.)

## 6. Verification

(Filled in as slices finish.)
