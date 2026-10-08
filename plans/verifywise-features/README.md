# VerifyWise-inspired feature plans for ThemisIQ

**Status:** Planning only, 2026-10-07. These are proposals grounded in the current checkout and VerifyWise's public product guides, not shipped features or evidence of production state. Implement independently; do not copy VerifyWise code, copy, or branding.

**Cross-plan navigation:** [ThemisIQ portfolio and dependency map](../ROADMAP-2026-10.md) places these plans alongside [PLAN-37](../PLAN-37-connected-compliance-experience.md), the [Evidence Vault plan](../../design/evidence-vault/PLAN.md), and the [CISO Assistant-inspired assurance plans](../ciso-assistant-features/README.md). Review that map before starting a slice so relationship, task, approval and evidence work is built once.

## Decision and sequence

The strongest product opportunity is a **governed AI use journey**: register an AI use once, connect its data and vendor, complete the right assessments, obtain a recorded decision, monitor it, and assemble the supporting evidence. People should enter through a short task, see the next action, and remain able to navigate without AI. The connected-compliance vision is in [PLAN-37](../PLAN-37-connected-compliance-experience.md); the documents below are the requested **feature-specific build plans**.

| Order | Feature plan | User value | Proposed size | Starting point |
| --- | --- | --- | --- | --- |
| 0 | [Evidence Vault](../../design/evidence-vault/PLAN.md) and [PLAN-36](../PLAN-36-themisiq-stabilization-and-product-improvements/task_plan.md) gates | Safe, scalable evidence discovery and stable routes | Existing work | Vault Phase 1a built and verified locally, not committed, PostgreSQL lane not run; verify before building on it |
| 0b | Scope fixes and relationship service ([PLAN-37 Slice 1](../PLAN-37-connected-compliance-experience.md)) | Related Items and topbar search stop showing other business units' titles; one scoped relationship service | M | Evidence Vault resolver; live gaps verified 2026-10-07 |
| 0c | AI service foundation ([PLAN-37 Slice 1b](../PLAN-37-connected-compliance-experience.md)) | One model-call wrapper with per-organization policy and usage records | M | About 70 call sites in 15 files; no shared wrapper today |
| 1 | [AI intake, inventory and lineage](01-ai-intake-inventory.md) | One clear way to declare an AI use and find its owner, provider, model, data, and status | L | Canonical `applications`, Sentinel AIIA, Governance data assets |
| 2 | [Relationship and impact explorer](02-relationship-explorer.md) | Understand affected records and gaps from any entry point | M | `cross_module_links`, Related Items, deep links |
| 3 | [Decision and approval gates](03-approval-gates.md) | Know who approved what version, on which conditions | M–L | Workflow engine, My Work, ARIA approvals |
| 4 | [Evaluations and monitoring](04-evaluations-monitoring.md) | Test ARIA and governed AI uses before claims or release decisions | L | ARIA, ORM AIMS/AI controls, Evidence Vault |
| 5 | [Regulatory impact](05-regulatory-impact.md) | Turn relevant changes into reviewed, linked work | M | Regulatory Inbox, ERM External Context |
| 6 | [Auditor sharing and trust](06-auditor-sharing-trust.md) | Give a reviewer a bounded, reproducible evidence pack | M | Existing GRID signed-in share links; Vault |
| 7 | [AI literacy and training](07-ai-literacy-training.md) | Assign training by role and show real completion evidence | M | BCM training and Sentinel training records |
| 8 | [Contextual AI advisor](08-contextual-ai-advisor.md) | Find and prepare work in context with sources and human review | L | Ask ARIA, Vault search, module records |
| Later | [Shadow AI and gateway discovery](09-shadow-ai-gateway.md) | Decide whether detection and runtime controls are useful and feasible | Discovery first | No assumed access to customer network or model traffic |

Sizes are comparative planning estimates, not delivery commitments. Order 2–8 can overlap once shared tenant-safe relationship, search, workflow, and evidence contracts are stable. Each plan states its own narrower dependencies and acceptance gates.

## Shared implementation rules

1. A record has one canonical owner. `applications` remains the application identity; AIIA, DPIA, risk, control, policy, and audit records retain their own module lifecycle. Do not add a second generic task board, evidence store, regulatory inbox, or relationship database.
2. Every read, link, count, search result, snippet, export, notification, and AI citation is checked against the current organization, business-unit scope, role, and module capability. A link alone never grants access to its target.
3. Deterministic rules calculate status, due dates, thresholds, and scores. AI can suggest or draft, with citations and uncertainty; a permitted human confirms consequential changes.
4. Derive dashboards from authoritative source records. Capture source version and provenance when a decision or pack is frozen. Use idempotent event handling, built on `core/events.py`, for cross-module projections that must survive retries.
5. Every new journey needs loading, error, empty, stale-data, and unavailable-AI states, accessible keyboard navigation, reduced motion, narrow screens, and real deep links. Keep a non-AI route through the task.
6. Before each slice, reconcile the current branch, schema, and [PLAN-36](../PLAN-36-themisiq-stabilization-and-product-improvements/task_plan.md) with production. This folder is a plan, not a claim that all referenced capabilities are deployed.

## What is deliberately reused

- VerifyWise's [evidence collection](https://verifywise.ai/user-guide/ai-governance/evidence-collection) maps to the existing [Evidence Vault plan](../../design/evidence-vault/PLAN.md), not a new repository.
- VerifyWise's [share links](https://verifywise.ai/user-guide/ai-governance/share-links) inspire an extension of GRID's existing authenticated, audit-scoped share flow. Public anonymous audit access is not an initial requirement.
- VerifyWise's [model inventory](https://verifywise.ai/user-guide/ai-governance/model-inventory), [intake](https://verifywise.ai/user-guide/ai-governance/intake-forms), and [datasets](https://verifywise.ai/user-guide/ai-governance/datasets) inform one ThemisIQ AI application workspace with linked model components and existing data assets.

VerifyWise feature descriptions are public documentation, not a hands-on claim of how each feature behaves. Its [repository license](https://github.com/verifywise-ai/verifywise/blob/develop/LICENSE.md) is another reason to implement these ideas independently.
