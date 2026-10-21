# 02. Reviewable cross-framework assessment reuse

**Status:** Implementation proposal, 2026-10-07. **Priority:** after scoped relationship/evidence semantics. **Owners:** GRID audit controls and ARIA framework mappings; Vault owns evidence versions. **Inspiration:** CISO Assistant's [audit mapping and preview](https://github.com/intuitem/ciso-assistant-community/blob/main/documentation/audit-mapping.md).

## User journey

An auditor starts an ISO audit, chooses a previously reviewed audit or ARIA framework mapping, and sees **current target vs proposed reuse** by requirement. The preview explains which source answer, control and proof support each suggestion, how strong the mapping is, and what is still missing. The auditor accepts selected rows. The target keeps its own review state and audit trail; partial matches never silently become compliant.

## Existing anchors and gap

`aria_control_mappings` links framework controls; `grid_control_mappings` links `grid_controls` across audits; `canonical_controls` provides a reusable identity. `grid_controls` currently carries audit-specific status, assignee, due date and notes. The [VerifyWise relationship explorer](../verifywise-features/02-relationship-explorer.md) explains linked entities. What is missing for this journey is an authorized **assessment projection and decision**, including provenance and a safe merge rule. Existing GRID mapping rows should not be treated as approved compliance results.

## Mapping semantics for the pilot

| Relationship | May suggest | Must remain for target review |
| --- | --- | --- |
| Reviewed equivalent/full coverage within the same permitted scope | Source response and current evidence as candidates | Applicability, target-specific wording and reviewer decision |
| Partial/intersection/uncertain | Relevant controls, observations and candidate proof | Target status, score and evidence sufficiency |
| No relation, stale mapping or source outside current scope | Nothing | Entire target assessment |

Start with **one-hop mappings only**. Normalize existing `mapping_type` values through an explicit vocabulary and migration review; do not assume every `equivalent` legacy row was actually reviewed. Multi-hop coverage and automated inference can wait until direct mapping accuracy is measured. The source and target may differ in framework version, audit scope, BU or effective date; show those differences in the preview.

## Design and build slices

1. **Audit mapping data.** Inventory real mapping types, direction, duplicates, cross-audit/same-audit cases, tenant and BU scope, source ownership and confidence. Add a reviewed/verified state and version or fingerprint to mappings where absent. Reject source/target combinations whose scope cannot be established. Define what happens when a framework/control is retired or renumbered.
2. **Choose a source snapshot.** For each proposed row capture the audit/control ID, relevant status/notes, reviewer, source date, mapping ID/version, canonical control link and exact Vault evidence versions. `grid_controls` does not currently expose an `updated_at` in the base schema, so add a version field or stable content fingerprint before promising reproducible projections.
3. **Read-only preview.** Return a paginated target list with current/proposed values, relation strength, conflicts, missing or expired proof, and count of rows that would actually change. Enforce read access to both sides, evidence items and mappings. An inaccessible source is omitted without leaking its title, count or existence. A missing mapping yields a clear non-destructive message.
4. **Confirm selected changes.** Require change permission on the target audit and a reviewer action. Recheck source and target versions inside one transaction; on a mismatch require a refreshed preview. Never overwrite a non-default target decision without an explicit per-row choice; never copy a source default over a more specific target value. A partial match links a candidate for review, not a verdict. Preserve target evidence/notes and append provenance idempotently.
5. **History and reversal.** Store a projection decision record with actor, source/target snapshots, mapping path, selected rows, before/after values and time. Rerun does not duplicate notes or links. Offer a safe undo only while target rows remain at the applied version; otherwise use a compensating review.
6. **UI integration.** Add “Reuse prior assessment” inside GRID audit setup/detail, show a prominent **Suggested, not yet assessed** state, and open mapping explanations from ARIA/GRID. Keep existing control-mapping screens as the source of mapping maintenance.

## Acceptance outcomes

- Reusing a fully mapped, reviewed answer saves re-entry, but the target can still be marked unknown or not applicable after review.
- Partial, stale, conflicting and out-of-scope mappings never set target compliance automatically; a reviewer sees why each was held back.
- A second apply produces no duplicate evidence links, notes or decisions, and a changed source forces preview refresh.
- Wrong-org/BU/module actors cannot inspect either audit or infer hidden evidence through preview, count, error or export.
- A report shows both the target verdict and the source/mapping provenance on which any accepted reuse depended.

**Not in the pilot:** bulk framework catalogue import, cross-tenant sharing, unrestricted multi-hop inference, and AI-written compliance scores. [Framework import](05-framework-library-import.md) is a later, separately gated slice.
