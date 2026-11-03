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

| Decision | Why | Cost | How to change it |
|---|---|---|---|
| Reuse never sets a target control's status; it adds proof waiting for review and, for a full match, the earlier answer as a comment marked "Suggested, not yet assessed" | CISO 02: partial matches never silently become compliant, and the target keeps its own review | The auditor still reviews every reused control | Add an explicit "accept as assessed" step per row, after pilot users trust the matches |
| An unreviewed mapping counts as partial, whatever its type | Legacy `equivalent` and `ims_equivalent` rows were made automatically (IMS audits copy them from ARIA) and nobody reviewed them | Until someone marks a mapping equivalent, only proof is carried through it | Mark mappings equivalent on the Reuse page, or bulk-review them |
| One hop only: same requirement, or one direct mapping | CISO 02 pilot rule; multi-hop accuracy is unmeasured | A control two mappings away is not offered | Add a second hop after measuring direct-mapping accuracy |
| Only Vault proof is carried; GRID-only files are listed as held back | A GRID file belongs to its control; copying it would make a second file store | The auditor attaches still-valid GRID files again, or moves them to the Vault | Use the existing GRID-to-Vault migration first, then reuse carries them |
| Reuse is the audit lead's (`grid.audits.manage`); reviewing a mapping is `grid.cross_mapping.manage` | The same people who set up audits and maintain mappings in GRID today | None | Change the capabilities in `modules/grid/reuse.py` |
| Undo is allowed only while nothing it added has been reviewed | After a review, removing the link would erase a reviewer's decision | Reviewed suggestions are decided on in the Vault instead | None needed |
| GRID reports do not yet show reuse provenance | The provenance is stored (`grid_reuse_rows`) and visible on the Reuse page | A report reader does not see which answers came from an earlier audit | Add a provenance section to the GRID audit report |
| Linking needs the right to change at least one end | PLAN-37: a link is a change; seeing two records is not enough | A read-only role (an outside auditor, an employee reading Governance records) can no longer add Related Items links | Adjust `relationships.CHANGE` per kind |
| Vault files are changeable through links by every role except the outside auditor (new capability `evidence.item.change`) | The Vault lets everyone who files evidence link it; only the outside auditor is read-only | None for today's users | Narrow the capability |
| Old AI impact assessments get a suggestion, never an automatic link | Plan 06 section 6: "Nothing is matched by name automatically"; a suggestion the person clicks keeps that rule | Names that differ in wording are not suggested | Widen the word rule, or add an alias list per system |

## 5. Build log

- 2026-11-03: committed `810e2507`: `relationships.CHANGE` and `may_change` (link create and confirm need the right to change one end); `("platform","evidence")` aliased to `("evidence","item")`; capability `evidence.item.change`; 3 tests.
- 2026-11-03: committed `e902d42b`: `assessments._suggest_systems` and the list's "Suggested" line with one-click link; script version 2; test.
- 2026-11-03: committed `e95544d7`: `modules/grid/reuse.py`, tables `grid_reuse_decisions` and `grid_reuse_rows`, mapping review columns, 7 routes, the Reuse an earlier audit page and GRID sidebar link; 5 tests.
- 2026-11-03: CI's PostgreSQL schema job found that the new link rule refused an AI system's owner without an AI governance role, which `_may_write` has always allowed for edges of their own system. Ownership now counts as the right to change that end; SQLite test added.
- 2026-11-03: browser test for the Reuse page (preview, apply, undo, axe) and a real PostgreSQL test (tenant schema, ordinary role) added; capability inventory regenerated.

## 6. Verification

(Filled in as slices finish.)
