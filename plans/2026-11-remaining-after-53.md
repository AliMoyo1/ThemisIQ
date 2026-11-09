# Remaining work after PR 53

Branch `claude/remaining-after-53`, stacked on PR 53. On 2026-11-09 the owner said in chat to merge PR 53 when green "and then finish all remaining work". This plan takes every item still open from the last two plans ([2026-11-relationship-service-fold.md](2026-11-relationship-service-fold.md), [2026-11-read-only-auditor.md](2026-11-read-only-auditor.md)) and the "what's next" list given in chat the same day. Decisions are chat confirmation, not sign-off.

## Items

| # | Item | Outcome |
| --- | --- | --- |
| R1 | Control effectiveness: the two evidence factors (35 of 100) could never be earned | Built (D1). |
| R2 | Other modules showed create buttons to an external auditor | Built for ARIA and GRID (D2). |
| R3 | Staff can mark their own file `auditor_signed` | No change (D3). |
| R4 | Close stale PR 12 | Not done: closing a pull request was refused by the session's automatic approval check. Owner step. |
| R5 | Rename the generated style tokens into readable class names | Not done (D4). |
| R6 | Owner, customer and specialist gates (customer AI evaluation, assisted AIIA drafts, Themis synthesis, ARIA to AIMS crosswalk, Sentinel legal review, sender domain, policy worker install and capacity, Sentinel unit audit script on the VPS, deployment) | Not code. Listed in [CURRENT-BUILD-STATUS-2026-11-05.md](CURRENT-BUILD-STATUS-2026-11-05.md). |

## Survey for R1

- `modules/governance/effectiveness.py` counted only Vault links with `entity_type = 'canonical_control'`. No route, event handler or import creates one: GRID uploads (`grid/data_service.py`), respondent assignments (`grid/assignments.py`) and reuse (`grid/reuse.py`) all link the file to the GRID control (`grid/control`). Only hand-made test rows had the canonical spelling.
- So every control lost 35 points, and the ERM residual risk worked out from the score treated every control as having no proof. The ERM risk-control view (`list_risk_controls`) also counted 0, and its docstring described a "mirror" onto canonical controls that does not exist.
- GRID controls carry `canonical_control_id`, the mapping the audit-passed factor already uses.

## Decisions

| Decision | Why | Cost | How to change |
| --- | --- | --- | --- |
| D1. Proof for a canonical control is a Vault file linked to it directly or to a GRID audit control mapped to it, under the same rules as before (current, unexpired, link not returned, rejected or out of scope). One shared fragment, `proof_for_control_sql`, feeds the score and the ERM risk-control count. Vault link, unlink and review rescore the mapped control at once; the nightly expiry check includes them. | It is how the product actually attaches proof. Without it the evidence factors were dead. | Scores rise by up to 35 where GRID proof exists, and ERM residual risk can fall for those risks after the next rescore (at once for Vault changes, 03:00 UTC for the rest). | `proof_for_control_sql` in `modules/governance/effectiveness.py`. |
| D2. The shell marks the page `data-read-only` for a read-only person, and any control with the class `write-action` is hidden. Tagged: ARIA Add Document, Import existing policies, Upload revision, Add Risk, Generate Report (two places), Add first framework; GRID New Audit (two places). The Vault already removes its controls on the server. | They could only meet the read-only refusal. | Controls built by scripts inside drawers (for example GRID status changes) still show and answer with the read-only message. | Add `write-action` to a control. |
| D3. `auditor_signed` stays as it is. | It describes the document (it carries an auditor's signature), like `digitally_signed`; the drawer already says the figure is metadata health and that only a reviewer's verdict on a link counts as proof, and the person who set it is recorded. | A person can still describe their own file that way. | Remove it from `_VALID_VERIFICATION_METHODS` in `modules/evidence/routes.py`. |
| D4. Style tokens keep their generated names. | Renaming 2,113 rules by hand changes nothing a user sees and each rename needs its own visual check; the guard tests already keep new code on classes. | Token names say nothing about intent. | Rename module by module when a page is next redesigned. |

## Evidence

| Check | Result |
| --- | --- |
| `tests/test_effectiveness_grid_proof.py` (mapped GRID proof earns both factors; unmapped, rejected or expired earns nothing; ERM view counts it; Vault link and unlink rescore at once) | 5 passed; the existing Vault rescore and removed-link tests 16 passed |
| 86 backend files (effectiveness, ERM, evidence, Vault, governance, GRID, shell, pages, onboarding, risk, controls, schedulers) | 1291 passed, 4 failed: `test_governance_controls.py` builds its own minimal schema without `grid_controls`. Added the table to that schema; 9 of 9 then passed. |
| CSP and style guards, the new proof tests, 23 ARIA, GRID, style policy, Command Centre, onboarding and read-only browser files | 133 passed |

## Change log

- 2026-11-09: survey, R1 to R6, D1 to D4; R1 and R2 built.
- 2026-11-10: PR 53 merged 00:23 CAT as 1185dfaa; this work moved onto `claude/effectiveness-and-read-only-ui` from that master; evidence above.
