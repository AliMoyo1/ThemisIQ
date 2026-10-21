# 01 · AI intake, inventory and lineage

**Inspiration:** VerifyWise [intake forms](https://verifywise.ai/user-guide/ai-governance/intake-forms), [model inventory](https://verifywise.ai/user-guide/ai-governance/model-inventory), and [datasets](https://verifywise.ai/user-guide/ai-governance/datasets). **Priority:** first product slice. **Size:** L.

## Existing ThemisIQ anchor

`applications` in `oneforall/database.py` already carries name, owner, business unit, department, vendor, hosting, and criticality; Governance owns its CRUD. Sentinel AIIA has `application_id` and `ai_system_name`. Governance has data assets; ORM has an AI controls catalogue. Confirm current tenant and BU rules before changing these records.

Verified limits (code read on 2026-10-07; see [PLAN-37 Appendix A](../PLAN-37-connected-compliance-experience.md)): only five roles can create applications, while every role can list all applications and data assets with no business-unit filter. There is no duplicate check, and deletion is a hard delete. `sentinel_aiia` already stores autonomy, data categories, deployment environment, third-party details, and stakeholders, and its `application_id` has no foreign key and no screen sets it, so expect it empty.

## User journey

1. **Register an AI use** opens a short, authenticated form from Command Centre and the application inventory. Ask purpose, owner, department, provider, data categories, affected people, autonomy, jurisdiction, and target launch. Save a draft after the essentials. Search for likely existing applications before creation.
2. A review screen shows supplied facts, missing facts, source of any prefill, and a **provisional** risk tier with the rule behind it. A reviewer can correct the tier with a recorded reason. Approval of intake creates or links one `applications` row and an AI-specific profile; a rejected request remains traceable and editable for resubmission.
3. An **AI use workspace** presents Overview, Assessments, Data & Vendors, Risks & Controls, Evidence, Decisions, and Monitoring. It gives exact links to the owning Sentinel/ERM/ORM/ARIA/GRID records, their current status, and the next permitted action. Do not copy specialist fields into a second form.
4. When a use includes multiple models or provider versions, add versioned model-component records attached to the application. Reuse Governance `data_assets` and canonical vendors; add lineage edges for “uses data” and “provided by”. A model version change can trigger re-review without overwriting the previous version.

## Build slices

- **A (contract and migration):** define AI use versus application versus model component; add an AI profile keyed by application ID and a small intake submission table with org, actor, status, risk-rule version, review reason, and source snapshot. Include a uniqueness/duplicate policy and explicit legacy backfill review; no guessed matches. Start with a field-ownership table: for every intake question, say whether the profile or the AIIA owns it. The profile owns stable facts about the system; the AIIA references the application, snapshots the values it assessed, and prefills from the profile instead of asking again. Retire an application (`is_active = 0`) rather than deleting it once it has approvals or evidence. Backfill `sentinel_aiia.application_id` only from reviewed name matches.
- **B (usable intake):** draft/resume, conditional questions, progress, duplicate suggestions, review queue, accessible errors, and deep links. Start with authenticated staff; public anonymous intake and configurable form builder require separate demand/security discovery. Staff submit through the intake request only. `governance.entities.manage` (five roles) stays reviewer-only, so add a narrow submit capability rather than widening it, and decide whether the application inventory stays visible to every role across business units or becomes scoped (PLAN-37 Section 9, item 9). The rule-derived tier works without a model; AI classification suggestions wait for the AI service foundation (PLAN-37 Slice 1b).
- **C (connected workspace):** scoped summaries of AIIA/DPIA/RoPA, data assets, vendors, risks, AI controls, policies, and evidence. Use the relationship service (PLAN-37 Slice 1) and source-specific permissions; each tab is a source adapter that applies the viewer's own scope, and none reuses an unscoped aggregate. Add a model component table only after a pilot confirms actual multi-model/version needs.

## Acceptance gates

- Two users cannot create unintended duplicate canonical applications through resubmission or retry. A permitted reviewer can locate the owner, provider, data, current model version, AIIA, and approval path within one workspace.
- Wrong-org/BU and role-restricted records reveal no title, count, ID, or deep link; record creation and cross-module writes are atomic or safely recoverable.
- An inventory read applies the viewer's business-unit rule, or the org-wide rule is an explicit recorded decision; the AIIA no longer re-asks for facts the profile owns; staff can submit an AI use without any write access to `applications`.
- A rule-derived risk tier is labeled provisional, editable with rationale, and does not itself grant approval. Missing data says “unknown”.
- Observe representative staff completing registration and resuming an incomplete intake without guidance; measure time and abandonment before expanding the form.

**Out of scope for first slice:** anonymous public intake, automatic legal classification, a parallel generic `ai_systems` table, and direct deployment control.
