# CISO Assistant-inspired improvements for ThemisIQ

**Status:** Proposals drafted 2026-10-07 against local `master` at `eec119f`, with a [review of the supplied feature list](ATTACHMENT-REVIEW-2026-10-08.md) on 2026-10-08. These files do not mark code complete. Start with the [portfolio roadmap](../ROADMAP-2026-10.md) and [feature assessment](../CISO-ASSISTANT-COMMUNITY-ASSESSMENT.md).

| Priority | Plan | Outcome | Prerequisite |
| --- | --- | --- | --- |
| 1 | [Assurance quality inspector](01-assurance-quality-inspector.md) | Explain contradictions and missing proof with one direct route to fix each | PLAN-37 scope fixes, Vault current-proof rules |
| 2 | [Cross-framework assessment reuse](02-cross-framework-assessment-reuse.md) | Preview and approve reuse of prior GRID/ARIA work | Permission-checked mappings, stable source/version contract |
| 3 | [Respondent assignments](03-respondent-assignments.md) | Let owners answer a small section and reviewers return only weak items | GRID audit scope, Vault requests, My Work |
| 4 | [Formal risk acceptance and exceptions](04-risk-acceptance-and-exceptions.md) | Show who accepted which exposure until when | ERM treatment, approval permissions and history |
| Early discovery; later rollout | [Versioned framework library import](05-framework-library-import.md) | Pilot one authorized customer framework with preview and version diff | Existing ID/mapping audit, source rights and PostgreSQL migration design |
| Conditional discovery | [Scoped external questionnaire invitations](06-external-questionnaire-invitations.md) | Let a named outside party submit a bounded questionnaire for review | Signed-in assignments, scoped Vault intake, invitation threat model |

**Adapt into existing plans instead of making more feature tracks:** CISO Assistant's focus mode fits [SBU-04](../PLAN-SBU-04-scope-legibility-and-filter.md) and the Command Centre. Its portals and trust-center ideas fit [VerifyWise auditor sharing](../verifywise-features/06-auditor-sharing-trust.md). The attached proposal's accountless write/upload questionnaire is distinct and has its own [conditional plan](06-external-questionnaire-invitations.md). Its BIA, TPRM, incidents, evidence, tasks, search and reports mostly overlap existing ThemisIQ modules. Specialist vulnerability/technical posture and DORA/EBIOS functions need customer discovery and a trusted source-system contract before planning implementation.

The reference [repository](https://github.com/intuitem/ciso-assistant-community/), [mapping documentation](https://github.com/intuitem/ciso-assistant-community/blob/main/documentation/audit-mapping.md), [assignments](https://github.com/intuitem/ciso-assistant-community/blob/main/product-docs/features/assignments.md), and [quality checks](https://github.com/intuitem/ciso-assistant-community/blob/main/product-docs/features/x-rays.md) are inspiration. The [edition comparison](https://intuitem.com/compare) distinguishes some Community and Pro features. Implement ThemisIQ behavior independently; the [source license](https://github.com/intuitem/ciso-assistant-community/blob/main/LICENSE.md) is not permission to copy assets or framework content without review.

Each plan has one owning module, phased scope and acceptance outcomes. Before a build, reconcile current code, PostgreSQL schema, production rollout, and the still-open [PLAN-36](../PLAN-36-themisiq-stabilization-and-product-improvements/task_plan.md) gates. Keep the existing dirty worktree intact.
