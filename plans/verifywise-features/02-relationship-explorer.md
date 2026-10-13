# 02 · Relationship and impact explorer

**Inspiration:** VerifyWise [Entity Graph](https://verifywise.ai/user-guide/ai-governance/entity-graph). **Priority:** follows the intake identity contract. **Size:** M.

## Existing ThemisIQ anchor

`cross_module_links` already records source and target module/type/ID, relationship, actor, and date. The launcher Related Items API and deep links provide a starting point. Existing direct foreign keys, such as Sentinel AIIA → application, remain authoritative where present. See [PLAN-07](../PLAN-07-related-items-cross-module-linking.md).

The anchor is weaker than it looks (code read and one reproduction on 2026-10-07; see [PLAN-37 Appendix A](../PLAN-37-connected-compliance-experience.md)). `cross_module_links` has no org, scope, provenance, or status column, and its create helper validates module names only. The Related Items API (`_LINKABLE`, 11 kinds) checks that both records exist but not that the caller may see either, returns titles for 10 of the 11 kinds, answers for a record the caller cannot open, and does not audit create or remove. Creating a link and reading it back reveals a record's title and existence. Topbar search has the same business-unit gap. Two other registries of linkable types exist: Evidence Vault's `_ENTITY_RESOLVERS` (19 kinds, the only one with scope checks, visibility checks, and URL resolution) and `core/links.py`. None includes application, data asset, AIIA, AIMS assessment, or workflow instance. Slice A therefore fixes a live gap before it extends the feature.

## User journey

On an AI use, incident, vendor, risk, control, or evidence item, **Related to this** first shows a fast, grouped list: affected records, their status, owner, last update, and why the link exists. A **Show impact** action expands one or two hops and highlights open issues, missing evidence, or due work. The visual graph is a secondary, optional view with the same results and working list fallback. Every node opens its source module, preserving a return path.

## Build slices

- **A (trusted edge service):** define allowed source/target types and relationship verbs; validate target existence, org/BU scope, and read permission on both ends at create, query, search, graph render, and removal. Add provenance (`manual`, `system`, `imported`), verification state, and stale/dangling diagnostics. Reconcile duplicate/inverse edges and legacy rows before broad traversal. Do not infer a legal or control relationship just from matching names. Seed the service from Evidence Vault's resolver rather than writing a fourth registry, and fold Related Items and `core/links.py` into it. Keep the nine existing verbs, store each edge once in one direction, and render the inverse label from the incoming side. Add the missing stored edges before the impact walk: a process-to-application dependency, structured affected applications and vendors on BCM incidents (today free text), an application reference on AIMS assessments, and a mapping from ORM's AI control catalogue to `canonical_controls`. Say where an edge lives, because `cross_module_links`, `applications`, and `data_assets` have no `org_id` or row-level-security policy while `evidence_items` does.
- **B (list and impact panel):** page/group/paginate results; resolve names and statuses only through authorized source adapters; filter “requires attention”; explain each edge and show a usable empty state. Cap traversal depth, nodes, and time. Counts must use the same authorization as rows. Do not reuse aggregates that ignore the viewer's scope, such as the vendor cross-module profile, which returns GRID and Sentinel fields to any BCM user.
- **C (focused graph):** seed on a selected record, default to one hop, permit type and issue filters, search, zoom, keyboard navigation, reduced-motion animations, and an accessible tabular equivalent. Lazy-load additional nodes; never render the whole tenant by default.

## Acceptance gates

- A user in one business unit cannot read another unit's record title through Related Items, topbar search, or a create-then-read link sequence, and a nonexistent target and an unauthorized target answer identically. Creating and removing an edge is audited. A users-by-entity-types test matrix proves this in CI for every linkable type.
- A selected incident reveals all agreed directly linked affected records while unauthorized and dangling records reveal neither title nor existence. Clicking any visible result reaches its permitted source page.
- The list and graph return the same authorized set and issue states; at 500+ connected items, initial view stays bounded and usable.
- Every manually created/removed edge has a recorded actor, reason or source, and time; inferred edges are visibly unconfirmed.

**Out of scope for first slice:** full-tenant force graph, automatic business impact conclusions, and a replacement for module-specific registers.
