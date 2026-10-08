# ThemisIQ plan portfolio and dependency map

**Snapshot:** 2026-10-07, local `master` at `eec119f`; CISO attachment reviewed 2026-10-08 in the [decision record](ciso-assistant-features/ATTACHMENT-REVIEW-2026-10-08.md). **Type:** navigation and proposed sequencing, not a release decision. The checkout contains modified BCM, GRID, Evidence Vault, launcher and test files, plus untracked Vault work and recent plans. Those changes were left in place. Reconcile the branch, worktree, and production state before executing a slice.

## How to use this portfolio

1. Start here for ownership and order. Open the linked plan for detailed scope and acceptance conditions.
2. Read [PLAN-36's current task and progress records](PLAN-36-themisiq-stabilization-and-product-improvements/task_plan.md) before building on its surfaces. Its release gate was still open in the reviewed document.
3. Treat a plan's `DONE`, `OPEN`, or `NOT STARTED` label as a historical statement until current code and acceptance evidence confirm it. Older specification files and later `-active.md` tracking files sometimes disagree.
4. Keep one source of truth per record: specialist modules own status and writes; Command Centre, My Work, search, AI, and reports are scoped views over them.

## Current planning tracks

| Track | Canonical plan or record | Role in the product | Current planning interpretation |
| --- | --- | --- | --- |
| Stabilization and release | [PLAN-36](PLAN-36-themisiq-stabilization-and-product-improvements/task_plan.md), [progress](PLAN-36-themisiq-stabilization-and-product-improvements/progress.md) | Browser, accessibility, scope, route, and release acceptance | Some slices complete; programme release gate open in the reviewed plan. Verify again before implementation. |
| Evidence discovery and collection | [Evidence Vault plan](../design/evidence-vault/PLAN.md), [Phase 1a](../design/evidence-vault/PHASE-1A.md) | One evidence library, scoped search, versions, requests, campaigns and guided intake | Local Vault files are currently uncommitted; no claim that the proposed next phases are deployed. |
| Connected platform | [PLAN-37](PLAN-37-connected-compliance-experience.md) | Shared identity, relationship/permission service, event contract, AI service foundation, cross-module journeys | Proposal. Its trust and access fixes are prerequisites for broad cross-module features. |
| AI governance expansion | [VerifyWise feature plans](verifywise-features/README.md) | AI intake, relationship explorer, approvals, evaluations, regulatory impact, sharing, literacy and contextual AI | Proposal. Its numbered files are feature plans, not delivered status. |
| Assurance and assessment reuse | [CISO Assistant feature plans](ciso-assistant-features/README.md), [attachment review](ciso-assistant-features/ATTACHMENT-REVIEW-2026-10-08.md) | Quality inspector, reviewed cross-framework reuse, internal respondent assignments, formal risk acceptance, framework-edition pilot and possible external invitations | Proposal. Reuses PLAN-37, Vault, GRID and ERM ownership; external invitations require their own security design. |
| Business-unit scope | [SBU-01](PLAN-SBU-01-user-bu-assignment.md), [SBU-02](PLAN-SBU-02-complete-bu-scoping.md), [SBU-03](PLAN-SBU-03-group-rollup-dashboard.md), [SBU-04](PLAN-SBU-04-scope-legibility-and-filter.md) | Assignment, authorization closure, group rollup and visible focus filter | Historic SBU status text is not a current access audit. PLAN-37 found live scope gaps in related/search paths. Reconcile before broad retrieval. |
| Earlier implementation history | [Execution rounds 1-6](README.md), corresponding `-active.md` files | Trace why existing modules and contracts look as they do | Reference material. Do not replay an old plan without checking code and newer records. |
| Other targeted plans | [PLAN-31](PLAN-31-econet-org-consolidation.md) to [PLAN-35](PLAN-35-aria-policy-authoring-flow.md), [demo requests](PLAN-demo-requests.md), [WA bridge](PLAN-wa-bridge-setup.md) | Tenant operations, administration, policy flow and separate integrations | Separate work streams; status and rollout conditions must be checked individually. |

## Dependency order for the new product work

| Gate | Work | Unlocks |
| --- | --- | --- |
| **0. Establish truth** | Reconcile PLAN-36, Vault Phase 1a, current branch, PostgreSQL behavior, and live permissions. Observe a few real audit/evidence/risk journeys and record baseline time and error rates. | A trustworthy starting point and a narrow first release. |
| **1. Scope and relationship safety** | Complete PLAN-37 Slice 1: fix Related Items/topbar search disclosure, centralize permission-checked deep links and relationship resolution, finish Vault scope/search gates. Complete the applicable SBU authorization work. | Cross-module counts, quality results, audit reuse, assignments and AI retrieval that cannot reveal out-of-scope records. |
| **2. Shared action and evidence contracts** | Stabilize Vault versions/requests, source event delivery and My Work projections under PLAN-37. PLAN-37 Slice 1b supplies the AI policy wrapper before new AI workflows. | Reviewable proof, dependable next actions, later contextual assistance. |
| **3. First assurance value** | [CISO 01: quality inspector](ciso-assistant-features/01-assurance-quality-inspector.md). Start with deterministic rules over existing records and deep links; AI summary comes later. In parallel, inventory framework IDs/editions and obtain one authorized customer example for [CISO 05](ciso-assistant-features/05-framework-library-import.md). | A useful “what needs fixing?” view and a defensible library pilot design. |
| **4. Reduce repeat work** | [CISO 02: assessment reuse](ciso-assistant-features/02-cross-framework-assessment-reuse.md) and [CISO 03: signed-in respondent assignments](ciso-assistant-features/03-respondent-assignments.md) once mapping and evidence scope are reliable. Pilot one governed framework edition only after historic-reference and rights checks. | Faster, reviewable audits, easier control-owner contribution and a versioned content path. |
| **5. Close decision gaps** | [CISO 04: formal ERM risk acceptance](ciso-assistant-features/04-risk-acceptance-and-exceptions.md), aligned to [VerifyWise approval gates](verifywise-features/03-approval-gates.md); add exceptions only after acceptance decisions work. | Clear distinction between proposed, approved and expired exposure. |
| **6. Guided AI and bounded sharing** | Execute the relevant [VerifyWise plans](verifywise-features/README.md) and PLAN-37 later slices. Extend [auditor sharing](verifywise-features/06-auditor-sharing-trust.md) only after source-version and quality gates. Explore [external questionnaire invitations](ciso-assistant-features/06-external-questionnaire-invitations.md) as a separate named-recipient pilot after signed-in assignments and Vault intake. | Connected journeys, citation-backed assistance and reviewable external contributions. |
| **Later, demand-led** | Scale [framework import](ciso-assistant-features/05-framework-library-import.md) after its one-framework pilot; consider generic quick forms, deeper workflow branching, custom fields, public trust publication and specialist integrations after discovery. | Expansion without bloating the primary workflow. |

These gates are dependencies, not a mandate to complete every VerifyWise feature before CISO work. Quality rules can begin after scope and evidence semantics are reliable; GRID assignment and formal ERM acceptance can advance independently once their own prerequisites hold.

The supplied feature list's 3–4 week Tier 1 estimate is not a delivery commitment. Framework content rights, PostgreSQL edition migration and an accountless upload threat model make those features materially different in size. [The attachment review](ciso-assistant-features/ATTACHMENT-REVIEW-2026-10-08.md) records every accept, adapt and defer decision.

## Ownership map: where a new idea belongs

| Concern | Owning plan/module | Consuming surfaces |
| --- | --- | --- |
| Evidence item, version, verification, search, request | Evidence Vault | GRID, ARIA, BCM, Sentinel, ERM, ORM, inspector, reports |
| Framework requirement and control mapping | ARIA/GRID plus [CISO 02](ciso-assistant-features/02-cross-framework-assessment-reuse.md) | Relationship explorer, quality inspector |
| Audit answer, respondent assignment and reviewer decision | GRID plus [CISO 03](ciso-assistant-features/03-respondent-assignments.md) | My Work, Vault requests, Command Centre |
| External questionnaire invitation and response review | GRID plus conditional [CISO 06](ciso-assistant-features/06-external-questionnaire-invitations.md); Vault owns proof intake | Named external respondent, GRID reviewer, My Work |
| Risk score, treatment and approved acceptance | ERM plus [CISO 04](ciso-assistant-features/04-risk-acceptance-and-exceptions.md) | Inspector, board pack, impact explorer |
| Assurance issue | [CISO 01](ciso-assistant-features/01-assurance-quality-inspector.md) derives it from owner records | My Work, module record pages, pre-publication checks |
| AI system identity and approvals | Canonical application plus [PLAN-37](PLAN-37-connected-compliance-experience.md) and [VerifyWise intake/approval](verifywise-features/README.md) | AIIA, DPIA, ORM AI controls, policies, evidence |
| Scope/focus | Server-side BU permissions, then [SBU-04](PLAN-SBU-04-scope-legibility-and-filter.md) for visible filter | Search, dashboards, lists, exports and AI retrieval |
| Auditor sharing / public trust | [VerifyWise 06](verifywise-features/06-auditor-sharing-trust.md) | GRID, Vault, ARIA and later public page |
| Customer framework edition and import rights | ARIA/GRID plus [CISO 05](ciso-assistant-features/05-framework-library-import.md) | Assessment reuse, assignments and historical audit export |

## Duplicate-work rules

- Do not build another evidence store, risk register, generic task board, regulatory inbox, or free-standing assessment portal.
- Do not use a mapping, file attachment, AI answer, or quality check as automatic proof of compliance. Keep applicability, implementation, test, current evidence and reviewer decision separate.
- Do not move historical plan files just to tidy folders: they are linked from code, progress records and earlier discussions. This portfolio and the two feature-folder indexes provide the new navigation layer.
- The [CISO assessment](CISO-ASSISTANT-COMMUNITY-ASSESSMENT.md) and [VerifyWise overview](verifywise-features/README.md) explain product inspiration. Their source descriptions are not implementation or production verification.
