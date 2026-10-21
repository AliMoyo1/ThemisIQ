# 03 · Decision and approval gates

**Inspiration:** VerifyWise [approval workflows](https://verifywise.ai/user-guide/ai-governance/approval-workflows). **Priority:** after AI intake. **Size:** M–L.

## Existing ThemisIQ anchor

The launcher workflow engine has templates, instances, actions, and decisions; My Work exposes assigned work. ARIA has its own managed-policy approvals. Extend these contracts for an AI-use decision rather than creating another workflow engine or treating a generic task completion as approval.

## User journey

An owner submits an AI use for review. A checklist displays required AIIA/DPIA, vendor/data assessment, policy/control, evaluation, and evidence states, including “not applicable” with reviewer and reason. Reviewers see a compact **decision brief**: what is being proposed, what changed, unresolved risks, exact evidence versions, and missing prerequisites. They approve, return for changes, reject, or approve with named conditions and an expiry/review date. A later material change opens a re-review while preserving the prior decision.

## Build slices

- **A (decision contract):** define lifecycle states and stage owners; configure stage requirements by org policy and risk tier. Decide which module owns each prerequisite. Store a decision snapshot referencing application/profile version, model components, assessment IDs/statuses, evidence versions, reviewer, rationale, conditions, and rule version. Use source adapters instead of copying assessments.
- **B (workflow integration):** add an AI-use workflow template and capability-checked decision endpoints. Idempotent submission and assignment; prohibit self-approval when policy requires separation. Route work to My Work and Command Centre with one canonical action ID. Surface stale prerequisites before final decision.
- **C (change and renewal):** define material changes (model/provider/data/purpose/autonomy/jurisdiction, serious incident, expired evidence), re-review triggers, due dates, and notification deduplication. Make conditions visible on the AI workspace and export.

## Acceptance gates

- An approval cannot complete with a mandatory unresolved prerequisite; a permitted override records who, why, and policy basis. Concurrent reviewers cannot silently overwrite one another.
- Reopening after a material change preserves the earlier approved snapshot and makes current state clearly “needs review”; no AI output can decide or sign on behalf of a reviewer.
- Assigned reviewers can reach the source record and return to their decision; inaccessible source detail remains hidden even in briefs and notifications.

**Out of scope for first slice:** replacing ARIA policy publication, automatic regulatory applicability decisions, or direct control of a customer's production AI deployment.
