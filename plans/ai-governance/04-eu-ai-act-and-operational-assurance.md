# 04. EU AI Act and operational assurance extension

**Status:** Proposed design, 2026-10-09. This is an optional, jurisdiction-aware extension to the [AI Governance programme](README.md), not a declaration that any customer is subject to the EU AI Act or that ThemisIQ satisfies it. Legal content and effective dates must be checked against the current official text before build and before each release.

## 1. Assessment and decision

The user-supplied landscape assessment identifies two thin areas in the programme: role-specific EU AI Act artifacts and formal oversight after deployment. Keep the existing conditional assessment engine, workflow, Vault, Sentinel, ORM, ERM, BCM, and Regulatory Inbox as writers. Add a versioned EU applicability pack and the records needed to use those writers together.

The assessment's claimed absence of all quantitative risk is inaccurate for this checkout: ERM already stores inherent and residual EMV and exposes those values in Scenario Studio. Its proposed conditional routing and operational human oversight are already in [feature journeys 3 and 6](02-feature-journeys.md). These need more specific records and acceptance, not replacement plans. A repository feature name alone does not establish production quality. VerifyWise's [licensing FAQ](https://github.com/verifywise-ai/verifywise/blob/develop/LICENSING-FAQ.md) confirms internal-only use under its current BSL terms; CISO Assistant's [repository](https://github.com/intuitem/ciso-assistant-community) identifies AGPL community code and separately licensed enterprise code. AGPL is not a blanket ban on commercial use, but using its code in ThemisIQ would require a legal and architectural licence review. No competitor code or wording is used by this plan.

| Priority | Addition | Decision |
| --- | --- | --- |
| First EU pilot after core G1-G5 gates | Reviewed role/applicability classification, applicable artifact checklist, FRIA route where required, oversight record | Build as a versioned content and workflow pack for customers with a confirmed EU use case |
| Same pilot's monitored phase | Provider post-market plan where applicable; deployer monitoring and serious-incident triage; re-review after material change | Extend existing monitoring, incident and task owners, with one visible system timeline |
| After source-version and proof gates | Annex IV binder, conformity/declaration/CE/registration evidence where applicable; obligation traceability export | Assemble exact approved versions; record external actions rather than claiming ThemisIQ performs them |
| Later, only with demand and proof of value | Decomposable readiness view, dataset lineage, independent model validation for regulated sectors | Reuse present metrics and versioned application components; do not create a generic second risk engine |
| Defer | General plugin system, automatic risk inheritance, public anonymous intake, self-issued seal, standalone tamper ledger | Separate security, product and customer-demand decisions are required |

## 2. Applicability and regulatory content contract

1. Record the **jurisdictions of placing on the market, putting into service and use**, the actor's relationship to each system (provider, deployer, importer, distributor or authorised representative), intended purpose, product or Annex III route, and source of every assertion. A customer may hold more than one role. An imported vendor model does not automatically make the customer its provider; a material change or rebranding can require role re-review.
2. The guided screen asks only facts relevant to the selected role and use. It proposes `out of scope`, `needs legal review`, `prohibited-practice review`, `high-risk candidate`, `transparency review`, or `other` with the exact rule and unanswered facts. General-purpose AI model obligations are a separate route and must not be inferred merely because a system uses a third-party model.
3. An authorized human adopts the classification with rationale, official source citation, jurisdiction, rule-pack version, effective date and review date. The system preserves prior classifications and never turns a model answer into a legal determination. Unknown facts block an automatic `not applicable` decision.
4. The Regulatory Inbox tracks changes to law, Commission guidance, templates and effective dates. Each reviewed update produces a diff of affected system classifications, required artifacts, owners and deadlines. No source text may change a customer's rule pack until approved; superseded versions remain attached to old decisions.
5. Candidate mappings link `legal provision -> applicability rule -> canonical control -> system -> owning assessment/decision -> accepted evidence version -> owner`. The relationship service resolves only records visible to the actor. A traceability export freezes this permitted graph and labels gaps, unknowns and stale proof. Do not claim the graph is a complete legal inventory without a reviewed content set.

## 3. Role-specific artifact journeys

| Trigger and owner | User action and source of truth | Completion evidence and guardrail |
| --- | --- | --- |
| **FRIA candidate, certain high-risk deployers** | The applicability route checks Article 27 conditions and exemptions. Sentinel owns a versioned fundamental-rights assessment form linked to the system, affected groups, intended use, harms, oversight and mitigations. Reuse permitted DPIA sections by reference while preserving distinct approvals. | Reviewer signs an applicability decision and the assessment. Show authority notification as a separate, externally performed action with receipt if required. FRIA is not universally required of all deployers or every high-risk system. |
| **Technical documentation, relevant providers** | Governance system/component versions and source-owned records populate an Annex IV-oriented binder manifest: intended purpose, architecture, data provenance, evaluation, risks, oversight, cybersecurity, changes and monitoring plan. Vault holds exact reviewed document versions. | Human reviews completeness and rights to disclose. A missing vendor detail is `unknown`; ThemisIQ does not fabricate training-data provenance or treat an uploaded model card as verified. |
| **Conformity, declaration, marking and registration, relevant providers** | Existing decision workflow coordinates the chosen Article 43 assessment route and links the signed declaration, marking record, notified-body or internal-control evidence, and external registration reference where Article 49 applies. | ThemisIQ records responsible person, date, scope, system version and evidence. It does not issue a CE mark, perform notified-body assessment, submit to an EU database, or assert legal conformity on the customer's behalf. |
| **Registration, certain deployers** | For Article 49 cases such as relevant public-authority deployers, show a separate task and external receipt tied to the provider's registered system. | Do not create the same task for every private deployer. Apply special non-public or national registry rules when relevant. |
| **Human oversight, provider and deployer roles** | Add one versioned oversight arrangement per system: named role/person, authority to monitor, interpret, override, reverse or stop, escalation route, training, availability, safe-state procedure and last exercise. Provider design measures and deployer operating measures are separately attributed. | An approval checks that required people, competence, authority and practical stop path are evidenced. A named person without an effective procedure does not satisfy the check. Changes reopen review. |

These artifacts extend [conditional routing](02-feature-journeys.md#3-conditional-assessment-and-obligation-routing), [template and proof work](02-feature-journeys.md#4-ai-controls-policies-evidence-and-assurance-quality) and [versioned decisions](02-feature-journeys.md#5-versioned-decisions-and-formal-risk-acceptance). They must never become a duplicate Vault, risk register or general assessment engine.

## 4. Post-deployment monitoring and incidents

**Provider plan where applicable.** Record a versioned post-market monitoring plan for each relevant high-risk system: objectives, signals, source permissions, performance and harm thresholds, review cadence, responsible people, incoming deployer feedback, interaction with other systems, corrective action path and retention. Link the plan into the Annex IV binder. A reviewer approves the plan; telemetry and evaluation jobs supply observations only if a named, authorized connector exists. Missing telemetry is `not measured`, never `passing`.

**Deployer operation.** Show instructions-for-use compliance, human oversight assignments, logging and operational checks in the system timeline. When a deployer finds a serious problem, create one triage case with a documented route to the provider and competent internal team. BCM owns continuity incidents, Sentinel owns personal-data breach obligations, and ORM/ERM own operational and enterprise risk actions. Link those records; do not silently merge their different regulatory clocks.

**Serious incident triage.** Capture awareness time, location, potentially affected persons, system/version, potential causal relationship, severity, immediate containment, evidence preservation, reviewer determination, reporting party and destination. Article 73 places the relevant reporting duty on the provider of a high-risk system; a deployer's discovery needs a prompt provider-notification path and role review. The applicable Article 73 clock is chosen from the current, reviewed rule pack by incident type and exemptions. Show clock source, timezone, start time, owner and escalation, allow a reviewed incomplete initial report, and record external filing receipt and follow-up. No AI model submits a regulator report. Preserve the initial timeline even if classification changes. A failed event consumer or missing awareness time produces an urgent review state rather than a false `on time` badge.

**Change and recurrence.** Evaluation failures, incidents, new deployment context, model/data/provider changes, stale oversight training, and amended legal rules open a diff and re-review task. One source event yields one canonical action in My Work. Closure requires a named reviewer and links corrective action to the next evaluation or control check.

## 5. Explainable readiness and management view

Start with separate, denominated measures: applicable obligations reviewed, required assessments approved, controls implemented, controls tested, current accepted evidence, operating oversight and monitoring coverage. Every number drills into the exact permission-checked records and shows the rule version, denominator, unknowns and last refresh. Evidence freshness is its own signal; presence is not effectiveness.

A single composite index remains a later product experiment. Before release, define and publish its weights, exclusions, treatment of `unknown` and `not applicable`, sensitivity to missing data, and whether users correctly understand it in pilot research. No score may be labelled `EU AI Act compliant`, `certified`, or `approved` merely because it is high. Prefer a status path and actionable gaps if a headline number hides uncertainty.

## 6. Data sources, security and acceptance

| Concern | Required connection or gate |
| --- | --- |
| Identity and permissions | Reuse Governance application identity, actor/org/BU authorization, source-module capabilities and PLAN-37's no-existence-signal rule across cards, counts, exports, links and citations. |
| Law and content | Pin official provision URL, consolidation/version, retrieval date, effective date, content owner, approved mapping and licensed-text rights. No copied competitor content. |
| Assessments and proof | Sentinel owns FRIA/DPIA/AIIA where configured; ARIA owns published policy; ORM/ERM own controls and risk; Vault owns immutable selected file versions; GRID owns audit findings. |
| Operational events | Approved evaluation and provider/deployer feeds with tenant mapping, retention and minimization. BCM/Sentinel incident records, workflow tasks, training status and provider feedback are linked, not duplicated. |
| Audit and integrity | Existing event/audit trail plus frozen manifests, version hashes where appropriate, access logs and source receipts. Evaluate a separately verifiable ledger only after threat model and customer requirement establish its value. |
| Human and AI guardrails | AI may explain applicability candidates or draft a section with citations. Only permitted humans classify, approve, waive a step where legally allowed, sign, publish or report. External legal text and uploaded files are untrusted data. |

The EU pilot requires an end-to-end scenario for a relevant provider and one for a relevant deployer, plus an out-of-scope system. Verify applicability against the then-current official text. Check a material change, FRIA/DPIA cross-reference, oversight reassignment, unmeasured monitoring, serious-incident clock selection, exact-version binder, denied cross-BU detail/count/export, and rollback. These are future release checks; none were run by writing this plan. The legal/content owner must approve the initial rule pack and its refresh policy before the feature flag is enabled.

## 7. Primary legal references

- [Classification: Article 6 and Annex III](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-6)
- [Human oversight: Article 14](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-14)
- [Provider obligations: Article 16](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-16) and [deployer obligations: Article 26](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-26)
- [FRIA: Article 27](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-27)
- [Conformity: Article 43](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-43), [declaration: Article 47](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-47), [CE marking: Article 48](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-48), [registration: Article 49](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-49)
- [Technical documentation: Annex IV](https://ai-act-service-desk.ec.europa.eu/en/ai-act/annex-4)
- [Post-market monitoring: Article 72](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-72) and [serious incidents: Article 73](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-73)
