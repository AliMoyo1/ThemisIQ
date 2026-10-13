# AI Governance implementation programme

**Status:** Implementation plans only, 2026-10-09. No feature, migration, release, or production configuration is authorized or marked complete by these documents. **Scope:** ThemisIQ only. **Planning baseline:** local `claude/pg-layer-scope-and-findings` checkout on 2026-10-09. The checkout had an ahead commit and unrelated modified and untracked files; they were not changed for this planning work. Older plan status and production status require fresh verification.

## Decision

Create one **AI Governance** entry point and AI-use workspace. Build it over the existing canonical `applications` identity and the owning modules. The entry point is a product surface, not a second risk register, assessment engine, evidence vault, task board, or regulatory inbox. An organization can govern its own AI use cases; ThemisIQ's first-party AI features should be governed in a separate, platform-controlled inventory and must never expose customer-tenant data in a shared record.

The first customer journey is **declare an AI use -> connect its data and provider -> complete the required specialist reviews -> record a versioned decision -> monitor changes -> produce a reproducible evidence pack**. Start with a short form and clear next action. AI assistance remains optional.

## Document map and authority

| Document | Owns | Relationship to earlier plans |
| --- | --- | --- |
| [01. Domain and integrations](01-domain-and-integrations.md) | Identity, field ownership, source adapters, relationship and event contracts, authorization, data sources | Implements the shared contracts proposed by [PLAN-37](../PLAN-37-connected-compliance-experience.md); does not supersede its platform-wide security fixes |
| [02. Feature journeys](02-feature-journeys.md) | User-visible behavior, source and target records, automation, guardrails, acceptance per feature | Extends the nine [VerifyWise-inspired briefs](../verifywise-features/README.md), [Evidence Vault](../../design/evidence-vault/PLAN.md), and [CISO-inspired assurance briefs](../ciso-assistant-features/README.md) without duplicating their specialist implementation detail |
| [03. Delivery and acceptance](03-delivery-and-acceptance.md) | Ordered slices, dependencies, migration, rollout, checks, outcomes, decisions | Fits the [plan portfolio](../ROADMAP-2026-10.md) and [PLAN-36](../PLAN-36-themisiq-stabilization-and-product-improvements/task_plan.md) release gates |
| [04. EU AI Act and operational assurance](04-eu-ai-act-and-operational-assurance.md) | Conditional role/applicability pack, formal artifacts, post-deployment oversight, incident triage, explainable readiness | Extends the shared journeys for confirmed EU use cases; distinguishes provider and deployer duties |
| [07. G4 build plan: decisions on an AI use](07-g4-decision-lifecycle-build.md) | The build plan for slice G4 (request, brief, decide, derive the standing state, conditions, expiry, re-review), written before the code | Implements [journey 5](02-feature-journeys.md) and the [approval gates brief](../verifywise-features/03-approval-gates.md) |
| [06. The AI impact assessment moves into AI Governance](06-aiia-in-ai-governance.md) | Amends ownership of the AIIA: screens, API, service, capabilities and navigation move from Sentinel to AI Governance; tables and link identity stay | Owner instruction of 2026-10-11. Where it differs from 01 to 04 on the AIIA, this document governs |

**Conflict rule:** The owning module plan governs that module's workflow and data. These documents govern how AI Governance composes the modules. If an old plan and current code disagree, inspect current code and amend the contract before implementation. Do not silently choose one. The October 7 portfolio is a historical snapshot, not proof of what is deployed today.

## Feature ownership and existing plan mapping

| AI Governance surface | Source of truth | Existing build plan |
| --- | --- | --- |
| AI-use intake and inventory | Governance `applications` plus proposed AI profile and intake requests | [VerifyWise 01](../verifywise-features/01-ai-intake-inventory.md), PLAN-37 Slices 2a-2c |
| Related records and impact | Permission-checked relationship service over source records | [VerifyWise 02](../verifywise-features/02-relationship-explorer.md), PLAN-37 Slice 1 |
| Assessment routing and decision | AI Governance AIIA (moved from Sentinel, [06](06-aiia-in-ai-governance.md)), Sentinel DPIA/RoPA, ORM AIMS, ERM, existing workflow engine | [VerifyWise 03](../verifywise-features/03-approval-gates.md), [PLAN-20](../PLAN-20-aiia-ai-impact-assessment.md), [PLAN-21](../PLAN-21-ai-controls-catalogue-aims-engine.md) |
| AI controls, policies, audit and proof | ORM AI controls, canonical controls, ARIA, GRID, Evidence Vault | [CISO 01](../ciso-assistant-features/01-assurance-quality-inspector.md), [ARIA policy flow](../PLAN-35-aria-policy-authoring-flow.md), Vault plan |
| Evaluation and monitoring | Versioned evaluation results, owning incident/risk/control records | [VerifyWise 04](../verifywise-features/04-evaluations-monitoring.md), PLAN-37 Slice 5 |
| Regulatory review | Existing Regulatory Inbox and ERM External Context | [VerifyWise 05](../verifywise-features/05-regulatory-impact.md), [PLAN-13](../PLAN-13-drift-detection-regulatory-inbox.md) |
| EU AI Act applicability and artifacts | Reviewed rule pack over AI system profile; source assessments and Vault versions retain ownership | [EU AI Act extension](04-eu-ai-act-and-operational-assurance.md), after core trust and decision gates |
| Auditor pack and public trust | GRID sharing and Vault versions; explicit publishing workflow later | [VerifyWise 06](../verifywise-features/06-auditor-sharing-trust.md) |
| Literacy | Reconciled BCM and Sentinel training records | [VerifyWise 07](../verifywise-features/07-ai-literacy-training.md) |
| In-context assistance | Scoped search/citations and one AI-call policy layer | [VerifyWise 08](../verifywise-features/08-contextual-ai-advisor.md), PLAN-37 Slice 1b |
| Shadow AI and runtime enforcement | Named, opt-in external signal source only | [VerifyWise 09](../verifywise-features/09-shadow-ai-gateway.md), discovery later |
| Formal acceptance and assurance quality | ERM approved acceptance, shared quality read model | [CISO 04](../ciso-assistant-features/04-risk-acceptance-and-exceptions.md), [CISO 01](../ciso-assistant-features/01-assurance-quality-inspector.md) |

## Incremental product boundary

The early product contains **Overview, AI Systems, Reviews, Controls & Evidence, Monitoring**. Each system page offers a scoped summary and deep links into owning modules. Use accessible lists and filters before a graph. A system can be registered and reviewed without calling an AI model.

Later options include a provider/model-component inventory, richer evaluations, role-based AI literacy, bounded auditor packs, a public trust page, and opt-in shadow-AI discovery. Do not present a readiness score as certification or attach TrustArc's TRUSTe seal. Actual third-party certification requires its own independent process.

## What the TrustArc review adds to the earlier plans

| Refinement | Where it is specified here |
| --- | --- |
| Make AI use discoverable during ordinary vendor and business-process registration, including an honest `unknown` option | [Feature journey 1](02-feature-journeys.md#1-declare-an-ai-use-and-discover-embedded-ai) |
| Turn an inventory entry into a conditional, risk-based assessment route instead of another static questionnaire | [Feature journey 3](02-feature-journeys.md#3-conditional-assessment-and-obligation-routing) and [decision contract](01-domain-and-integrations.md#1-concepts-and-source-of-truth) |
| Offer an original, reviewable AI governance template set within the existing ARIA authoring flow | [Feature journey 4](02-feature-journeys.md#4-ai-controls-policies-evidence-and-assurance-quality) |
| Present ongoing review, data/model changes, current proof, and denominated management metrics in one system workspace | [Feature journeys 2, 6 and 10](02-feature-journeys.md) |
| Make ThemisIQ's own AI features subject to platform-side inventory, evaluation and provider policy | [Feature journey 12](02-feature-journeys.md#12-govern-themisiqs-own-ai-features) |

These are refinements to the planned AI-use journey. They are not an additional source database or a claim that TrustArc's commercial services have been reproduced.

## Sources and reuse

- TrustArc public [AI governance](https://trustarc.com/solutions/ai-governance/), [assessment workflow](https://trustarc.com/resource/elevating-privacy-impact-assessments-pias-to-ai-governance/), [PrivacyCentral](https://trustarc.com/products/privacy-data-governance/privacycentral/), and [maturity model](https://trustarc.com/resource/ai-governance-maturity-model/) describe product patterns, not validated behavior in a customer account. Implement original ThemisIQ workflows, language, UI, and content.
- [ISO/IEC 42001](https://www.iso.org/standard/42001) and the [NIST AI RMF](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/) can inform optional, versioned framework mappings. Legal applicability and control satisfaction are reviewed decisions, never a model conclusion.
- Licensed framework text, templates, seals, and competitor assets require a rights review before import. Do not copy source code or protected content from competitor products.
