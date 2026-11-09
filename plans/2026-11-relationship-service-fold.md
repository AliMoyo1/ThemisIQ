# One registry for linkable records (PLAN-37 Slice 1 leftovers)

Branch `claude/relationship-service`, from master 78ddafb4 (PR 51 merged). On 2026-11-09 the owner said in chat "build 1 and 2":

1. Fold the three linkable-type registries (Evidence Vault, Related Items, `core/links.py`) into one relationship service.
2. Fix the picker mismatch (platform/evidence vs evidence/item).

Decisions below are chat confirmation, not sign-off.

## Survey (2026-11-09)

- **Item 2 is already built.** `entity_scope._KEY_ALIASES` maps `platform/evidence` to `evidence/item` (plan 25, PR 44), and `tests/test_relationships.py:350` links a Vault file picked from search. Nothing to build.
- **Related Items** already goes through `modules/governance/relationships.py` and the registry in `modules/governance/entity_scope.py` (`_KINDS`). Write rule "may change at least one end" is in place there (PR 44).
- **Still separate:**
  - `core/links.py` checks only the module name (`_VALID_MODULES`), so the event handlers store kinds the registry does not know.
  - The Vault keeps its own target list (`_VAULT_TARGETS`), a hand-written alias for `grid/non_conformance`, and two more hard-coded module lists (`api_search_entities`, `api_auto_evidence`).
- **Drift found (F1):** the event handlers store system links as `platform/risk_register` and `erm/enterprise_risk`. The registry knows those records as `platform/risk` and `erm/risk`, and Related Items, the connected-records page, change signals and the record graph drop any end they cannot place. So every automatic link to a platform risk or an ERM risk (breach, DPIA, DSR, BCM incident, ORM event escalations) has never been shown. Other code reads the stored spelling (`event_handlers` XM-CLOSE queries, the ERM delete cleanup), so the stored spelling must not change.
- **F2:** the two `grid.finding.created` handlers write `grid/finding` whatever the event says. GRID raises that event for a non-conformance (id in `grid_non_conformances`, event type `non_conformance`) and for a remote-audit finding (id in `grid_remote_findings`, event type `finding`). The same spelling names two tables, so a link cannot be placed.
- **F3:** the audit-completed handler links `platform/framework` with `grid_audits.framework_id`, which is a `grid_frameworks` id. Aliasing it to `aria/framework` would show a different framework's title. `sentinel/grid_finding` is a task pseudo-type pointing at the finding's own id. Neither names a registered record.
- **F4 (security):** the Vault's own link routes (`POST /evidence/api/items/{eid}/links`, `DELETE /evidence/api/links/{lid}`, and the claim link made during upload) check only that the caller can see both ends. Related Items requires the right to change at least one end, so a read-only External Auditor is refused there but can link or unlink evidence through the Vault.
- **F5 (reported, not changed):** other Vault writes (upload, edit, confidence verification) have no capability check, so an External Auditor, described as read-only, can file and edit evidence; anyone can mark their own file `auditor_signed` (+40 confidence). Product decision needed on what an outside auditor may file.
- **F6:** deleting an ERM risk removes its links stored as `erm/enterprise_risk` only; links made by people through Related Items are stored as `erm/risk` and were left behind.

## Decisions

| Decision | Why | Cost | How to change |
| --- | --- | --- | --- |
| D1. Register `platform/risk_register` and `erm/enterprise_risk` as other spellings of `platform/risk` and `erm/risk`. Stored rows are not rewritten. | Makes every automatic risk link visible through the same scope rule as any other link, without touching readers that query the stored spelling. | People now see more connections (and change signals reach those risks). Each end still has to pass the owning module's scope. | `_KEY_ALIASES` in `modules/governance/entity_scope.py`. |
| D2. `core/links.py` refuses a kind the registry does not know (any spelling), instead of checking the module name only. | One registry decides what can be linked. Unknown kinds were stored but never shown. | System links to `platform/framework` (a GRID framework), `sentinel/grid_finding` and a remote-audit `grid/finding` are no longer stored; they were invisible. A warning is logged. | Register the kind in `_KINDS` (table, title, scope) and it is stored and shown. |
| D3. The GRID finding handlers link the kind the event names (`non_conformance` or `finding`). | A non-conformance's links then reach its audit and the ERM risk it raised. | None. | `core/event_handlers.py` `grid_finding_created_handler`, `finding_triggers_sentinel_check`, `finding_elevates_to_erm`. |
| D4. The Vault's link targets live in the registry (`EVIDENCE_TARGETS`); the Vault's resolver, search and alias table are built from it. | One list; a new kind is added once. | None. | `EVIDENCE_TARGETS` in `entity_scope.py`. |
| D5. Linking or unlinking a Vault file (including the claim chosen at upload) needs the right to change the file or the record, the same rule as Related Items. | F4. | An External Auditor can no longer link Vault files. | `relationships.may_change` and `CHANGE`. |
| D6. Deleting an ERM risk also removes links stored under `erm/risk`. | F6. | None. | `modules/erm/data_service.py`. |

## What was built

- `modules/governance/entity_scope.py`: the two aliases (D1), `EVIDENCE_TARGETS` (D4), `is_registered` and `spellings`; the docstring now names it the one registry. `relationships.py` uses the shared `spellings`.
- `core/links.py`: `_VALID_MODULES` removed; both ends must pass `is_registered` (D2).
- `core/event_handlers.py`: the three `grid.finding.created` links use the event's `entity_type` (D3).
- `modules/evidence/routes.py`: `_VAULT_TARGETS`, the hand-written alias and the two module lists are gone; `_ENTITY_RESOLVERS` is built from `EVIDENCE_TARGETS` under every spelling. `_may_link` (the Related Items rule) guards link create, link delete and the claim chosen at upload (D5). The item payload carries `can_link`, and `static/js/evidence_vault.js` hides "Link to..." and the unlink button when it is false.
- `modules/erm/data_service.py`: the delete removes both spellings (D6).
- Tests: `tests/test_relationship_registry_fold.py` (11 cases). 9 of them fail on the old code (checked by reversing the patch); the other two (an unknown module, the picker under both spellings) held before and are kept as guards.

## Evidence

| Check | Result |
| --- | --- |
| New tests on the old code | 9 failed, 2 passed (expected) |
| New tests on the change | 11 passed |
| 55 related backend files (relationships, entity scope, Vault, evidence, events, ERM, change signals, AI Governance integration, DPIA links, search, Themis, reports) | 831 passed |
| New tests with the drawer check, CSP and style guards, 14 Vault, Related Items and style policy browser files | 102 passed |

## Change log

- 2026-11-09: survey, findings F1 to F6, decisions D1 to D6.
- 2026-11-09: built D1 to D6, `can_link` in the Vault drawer; tests and evidence above.
