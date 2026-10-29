# ThemisIQ specialist rework programme

**Status:** Design documents 01 to 06 were written 2026-10-14 and still describe behavior and acceptance gates: they do not mark a feature built or a release approved. What was built from them, how it was checked and what was left is in the implementation records below (07 to 14).

**Historical build status, 2026-10-15:** plans 01 to 03 were merged to `master` (pull request 10). Plans 04 to 06 and follow-ups 11 to 13 were then on `claude/plan-04-platform-truth`, awaiting a pull request. Pull request 11 has since merged that branch. Pull request 14 removed AI literacy application surfaces. Neither merge records a production deployment or a signed specialist pilot; see [10](10-completion-record.md) for the release gates.

**Policy intake extension, 2026-10-26:** [18 Existing-policy intake and document composition](18-policy-intake-and-document-composition.md) now has an isolated, uncommitted implementation slice for reviewed import, original preservation, control suggestions, composition, diagrams and scoped references. Its implementation ledger lists the release gates and remaining design work; it is not a deployment record.

## Product decision

ThemisIQ should answer four questions from any specialist record: **What is happening? Why does it matter? What is the next authorized action? What evidence supports the answer?** A person should be able to move between an AI use, process, vendor, privacy assessment, control, audit, risk, incident, and report without re-entering the same facts.

The owning module keeps the record and its lifecycle. Dashboards, My Work, related items, search, AI, and reports are scoped views over those records. AI suggests and drafts; deterministic rules compute deadlines, thresholds, and status; authorized people decide.

## Document map

| Document | Design authority in this programme | Builds on |
| --- | --- | --- |
| [01 AI Governance](01-ai-governance-specialist-workspace.md) | Specialist navigation, Forms import, precedent-assisted review, decision desk, external response, literacy separation | [AI Governance programme](../ai-governance/README.md), G7 oversight plan in the later release, [VerifyWise plans](../verifywise-features/README.md) |
| [02 Evidence Vault](02-evidence-vault-and-assurance.md) | Library UX, current proof, intake, reuse, versions, evidence search | [Vault plan](../../design/evidence-vault/PLAN.md), [CISO assurance plans](../ciso-assistant-features/README.md) |
| [03 Modules](03-specialist-module-journeys.md) | Domain journeys and cross-module contracts for the seven specialist modules and vendors | [PLAN-37](../PLAN-37-connected-compliance-experience.md), existing module plans |
| [04 Platform](04-platform-truth-navigation-and-reports.md) | Shared metrics, navigation, reports, AI, trust and unavailable states | [PLAN-37](../PLAN-37-connected-compliance-experience.md), [SBU plans](../PLAN-SBU-04-scope-legibility-and-filter.md) |
| [05 Delivery](05-delivery-and-acceptance.md) | Sequence, decisions, migration, acceptance, rollout | [Portfolio roadmap](../ROADMAP-2026-10.md), [PLAN-36](../PLAN-36-themisiq-stabilization-and-product-improvements/task_plan.md) |
| [06 Email](06-email-notifications-and-delivery.md) | Temporary Gmail sender, role-based touch points, shared templates, delivery outcomes, fallback, service-identity cutover | Existing `core/email.py`, module schedulers and platform notifications |
| [18 Policy intake and composition](18-policy-intake-and-document-composition.md) | Existing-policy import, metadata and clause review, framework links, rebranding, diagrams, and connected references | [PLAN-35](../PLAN-35-aria-policy-authoring-flow.md), [Vault assurance](02-evidence-vault-and-assurance.md), [PLAN-37](../PLAN-37-connected-compliance-experience.md) |
| [19 Evidence Vault and group oversight](19-evidence-vault-and-group-oversight.md) | One customer-neutral plan for company navigation, group onboarding/exit, policy adoption, requirement-led requests, reviewed metrics and restatements, filing, proof, auditor registers/rooms, distribution rights and privacy gates | [Vault assurance](02-evidence-vault-and-assurance.md), [18 Policy intake](18-policy-intake-and-document-composition.md), tenant and licence model |

## Implementation records

The documents above are the design. What was built from them, how it was checked, and what was left is kept apart so a
proposal is never read as a release.

| Record | What it holds |
| --- | --- |
| [07 Implementation ledger](07-implementation-ledger.md) | Slice status, a change log per slice with what was found on the way, the not done lists, stage verification and the handoff |
| [08 Platform functions inventory](08-platform-functions-inventory.md) | Per platform function: who reads and writes what, under which gate, what was found and fixed (plan 04 section 8) |
| [09 Email inventory](09-email-inventory.md) | Every path that sends mail, what it claimed, its state now, and the decisions only the owner can make (plan 06, E0) |
| [10 Completion record](10-completion-record.md) | The decision register, gates against evidence, migration inventory, security checks, verification results and the per slice record (plan 05 section 12) |
| [11 Follow-up plan](11-follow-up-plan.md) | The items the first build of plans 04 to 06 reported as not built: what could be built, the defaults chosen, and the running log |
| [14 Hardening pack](14-hardening-pack.md) | The outbox purge, the send budget, mail when a task is handed over, and badge contrast: the rules, the reasons and the log (follow-up 13) |
| [13 BCM incident escalation](13-bcm-incident-escalation.md) | Acknowledgement windows by severity, the first alternate, the rules and the log of the build (follow-up 12) |
| [12 Email cutover runbook](12-email-cutover-runbook.md) | Pause, switch, test and resume for the move to a managed sender identity (plan 06, E4). Nothing in it has been run |

Where an older plan and this user-directed rework disagree, these documents state the changed product decision. An implementation still has to reconcile code, schema, live data, permissions, and historical plan links before changing behavior. Do not silently rewrite or delete the earlier plan.

## Baseline observed in the code snapshot

| Area | Already present in the reviewed source | Proposed gap or correction |
| --- | --- | --- |
| AI Governance | AI intake, application-linked profiles, screening, AIIA, decisions and conditions, evaluations, regulatory review, review packs, oversight, My Work, and AI policy | Specialist home, external response import, precedent review, outstanding-items workbench, external response export, simpler navigation |
| AI literacy | Course, version, completion, learner page, quality signal | Remove learner and course work from the specialist journey only after a history and consumer migration; use another staff-facing project for future assignments |
| Evidence Vault | Paginated list, metadata search, saved views, exact-hash duplicate check, versions, links, coverage, AI link suggestions, request campaigns | List-first workflow, proof semantics, guided filing, version impact, full-text search, accountable reuse across modules |
| GRID and BCM | Their own evidence or document surfaces plus Vault links | Clarify canonical artifact versus module-specific acceptance, avoid copies, keep prior audit history |
| Platform | Scoped My Work, global search, related-item service, reports, dashboards, predictive risk, canonical vendors | Historical report snapshots, action-oriented views, source and scope explanation, no synthetic fallback data |
| Email delivery | Central SMTP provider selection, Admin Email Settings, direct scheduler sends, in-app notifications and reminder table | Safe secret storage, honest delivery states, role-scoped intents, one template catalogue, retries, provider switch and deliverability monitoring |

Specific findings to repair before premium reporting: the Vault coverage query accepts expired or superseded linked items; its confidence score rewards hashes and number of links rather than sufficiency; BCM and Sentinel can render sample dashboard data after source failure; ARIA reports success without generating a report; BCM report actions use unsupported report types; a non-super-admin's saved report run is recomputed when read. These are source observations, not claims that a live user encountered them.

## Source-of-truth map

| Record or decision | Owner | Consumers |
| --- | --- | --- |
| Application and AI-use identity | Governance `applications`; AI Governance owns use profile, intake, decision, oversight and evaluation | ERM, ORM, Sentinel, GRID, Command Centre |
| Business process, data asset and canonical vendor | Governance and canonical vendor service | AI Governance, BCM, Sentinel, GRID, ERM |
| Framework requirement, policy and canonical control | ARIA and Governance | GRID, AI Governance, Vault, reports |
| Audit-specific review, finding and sign-off | GRID | ERM, Vault, Command Centre, reports |
| Continuity assessment, plan, exercise and incident | BCM | ERM, AI Governance, Sentinel, Command Centre |
| Privacy record and jurisdiction applicability | Sentinel | AI Governance, BCM, ERM, reports |
| Enterprise exposure, appetite and acceptance | ERM | All specialist workspaces and board reporting |
| Operational event, KRI and RCSA | ORM | ERM, BCM, AI Governance, reports |
| Artifact, file version, integrity, owner and renewal | Evidence Vault | Source modules, assurance inspector, report packs |
| Assigned request or workflow action | Its source module and shared workflow service | My Work, notifications, calendar |

Links and projections do not transfer record ownership or grant access. A report preserves the source IDs, versions, scope, and as-of time it used.

## Scope boundaries and deferred work

- Do not create another risk register, evidence file store, generic task board, regulatory inbox, or questionnaire engine.
- Keep existing AI Governance data and historical review packs. The rework is a navigation and workflow evolution, not a reset of G1 to G7.
- Do not present AI screening as a legal classification, an evidence link as sufficiency, a policy as implemented, or a dashboard percentage as certification.
- External invitation forms, source-system connectors, model component catalogues, semantic search, public trust publication, and shadow-AI detection remain gated options, not first-release commitments.
- This repository contains ThemisIQ plans only. The proposed staff-facing learning project has an interface contract here, with no code or project assets copied into this repository.

## Cross-cutting quality contract

All list rows, counts, search hits, snippets, related items, alerts, exports, report sources, and AI citations must obey the same organization, business-unit, role, and record authorization. Unavailable and partial data must never appear as zero, complete, or sample data. Every actionable insight names its trigger, owner, age, source, and next step. Every write is auditable and safe to retry. Each workflow has a manual path if AI is disabled.

Email is an optional delivery channel over that same authorized action. A message must not reveal a case to a person who cannot open it, and a mail provider accepting a message must not be mistaken for human receipt or completion. The [email plan](06-email-notifications-and-delivery.md) defines the temporary Gmail gate and the later managed sender cutover.
