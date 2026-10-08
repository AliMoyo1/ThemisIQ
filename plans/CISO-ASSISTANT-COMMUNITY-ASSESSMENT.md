# CISO Assistant Community: feature assessment for ThemisIQ

**Date:** 2026-10-07  
**Status:** Assessment and product proposals only. No feature or deployment change is implied.  
**Basis:** [CISO Assistant's repository](https://github.com/intuitem/ciso-assistant-community/), linked product documentation, its [Community/Pro comparison](https://intuitem.com/compare), and the ThemisIQ checkout and plans reviewed on this date. This is a documentation and source review, not a hands-on evaluation of a configured CISO Assistant instance or the live ThemisIQ tenant.

**Build plans:** [CISO Assistant feature sequence](ciso-assistant-features/README.md) and the [cross-plan portfolio](ROADMAP-2026-10.md). The assessment below explains the original choice; those files own the proposed delivery slices. The supplied feature list was assessed separately on 2026-10-08 in the [attachment review](ciso-assistant-features/ATTACHMENT-REVIEW-2026-10-08.md), which advances framework-import discovery and separates accountless external invitations from signed-in respondent mode.

## Decision

The best ideas to adapt are **continuous assurance checks**, **reviewable reuse of assessments across frameworks**, **guided assignment of small assessment sections**, and **formal, expiring risk acceptance**. These would make ThemisIQ's existing modules feel like one system and reduce repeat work. They are stronger near-term opportunities than adding a large catalogue of frameworks or another dashboard.

CISO Assistant's central design [separates requirements, implemented controls, and evidence](https://github.com/intuitem/ciso-assistant-community/blob/main/documentation/architecture/data-model.md), which allows controls and assessments to be reused. ThemisIQ already has canonical controls, ARIA and GRID mappings, Evidence Vault, My Work, and a connected-compliance direction. The opportunity is to make **the strength, freshness, and approval state of each reused claim visible**. A linked control or document alone should never turn a requirement green.

## Feature comparison and recommendation

| CISO Assistant pattern | ThemisIQ starting point and plan overlap | Recommendation |
| --- | --- | --- |
| [X-rays / automated quality checks](https://github.com/intuitem/ciso-assistant-community/blob/main/product-docs/features/x-rays.md) find contradictory or incomplete records | Vault verification and confidence, control effectiveness, advisories, and [PLAN-37](PLAN-37-connected-compliance-experience.md) already provide ingredients, but no single deterministic assurance sweep was located in the reviewed surfaces | **Build first.** Add a focused “Needs attention” view with rules, source records, explanation, owner, and a direct Fix action. Reuse My Work and notifications; do not create another task system. |
| [Audit mapping and assessment projection](https://github.com/intuitem/ciso-assistant-community/blob/main/documentation/audit-mapping.md) carry results between mapped requirements | `aria_control_mappings`, `grid_control_mappings`, canonical controls, and [VerifyWise relationship explorer](verifywise-features/02-relationship-explorer.md) cover linkage; assessment-result reuse with a review preview is a distinct gap | **Build early.** Show source and target requirements side by side, mapping strength, version, proposed status, and evidence relevance; require reviewer acceptance before applying. |
| [Assignments / respondent mode](https://github.com/intuitem/ciso-assistant-community/blob/main/product-docs/features/assignments.md) let people answer only assigned requirement sections | GRID audits and Evidence Vault campaigns/requests already exist; [PLAN-37](PLAN-37-connected-compliance-experience.md) uses My Work as the common action surface | **Build in GRID and campaigns.** Assign a bounded set of questions or evidence requests to a named person/team; support submit, item-level changes requested, resubmit, accept. Avoid a new generic questionnaire module. |
| [Risk acceptance and exceptions](https://github.com/intuitem/ciso-assistant-community/blob/main/product-docs/concepts/risk-assessments.md) | ERM has an `accept` treatment option and workflow history, but a formal acceptance record with approver, rationale, scope, expiry, and re-review was not located in the reviewed modules; [approval gates](verifywise-features/03-approval-gates.md) are planned | **Build in ERM.** Distinguish a selected treatment from an approved acceptance. Make accepted risk expire and return to review when its basis changes. Add scoped policy/control exceptions as a later extension. |
| [Focus mode](https://github.com/intuitem/ciso-assistant-community/blob/main/product-docs/features/focus-mode.md) narrows work to a domain | [PLAN-SBU-04](PLAN-SBU-04-scope-legibility-and-filter.md) already plans a scope indicator and single-business-unit filter | **Fold into that plan.** Let the selected scope persist across lists, search, Command Centre, and reports. The UI filter must intersect server-enforced access, never replace it. |
| [Portals and trust center](https://github.com/intuitem/ciso-assistant-community/blob/main/product-docs/features/portals.md) curate internal journeys and external claims | Customizable Command Centre exists; [VerifyWise auditor sharing and trust](verifywise-features/06-auditor-sharing-trust.md) already plans bounded GRID review packs and a later approved public page | **Extend existing plan.** Curated role-based starting points can improve navigation soon. Public trust publication belongs after reviewed snapshots and explicit publishing permission. |
| [Custom framework libraries](https://github.com/intuitem/ciso-assistant-community/blob/main/product-docs/configuration/libraries/custom-libraries.md) support portable, versioned requirements and mappings | ARIA/GRID frameworks and mapping tables exist; no general versioned customer import workflow was confirmed in this review | **Later.** Offer import preview, validation, duplicate/version handling, impact diff, and rollback before adding broad catalogue volume. Check rights to framework text and mapping data. |
| BIA, TPRM, policies, evidence, incidents, tasks, command palette, dashboards, reports | BCM, vendor modules, ARIA, Vault, ORM/Sentinel, My Work, search and Command Centre already cover these categories | **Improve connections and usability**, rather than creating parallel stores or menus. |
| Vulnerability / technical posture, DORA-specific registers, EBIOS, cyber-risk quantification, SCIM, Jira/ServiceNow | Some risk, external-context and operational signals exist; no customer demand or source-system contract is established by this assessment | **Discovery first.** Ingest a small set of trusted signals into ERM/ORM if customers need it; do not build a scanner, SIEM, or jurisdiction-specific specialist suite speculatively. |

The [repository README](https://github.com/intuitem/ciso-assistant-community/) lists capabilities across the product. Its [edition comparison](https://intuitem.com/compare) places some adjacent capabilities, including focus mode, domain analytics, integrations and several portal/management refinements, in Pro. This assessment borrows the *workflow ideas* and does not assume that every README feature is present in the Community edition or production-ready there. Where public pages differ in edition labels, confirm the exact behavior before treating it as a benchmark.

## Proposed implementation sequence

### 0. Finish the existing trust and usability gates

Use [PLAN-36](PLAN-36-themisiq-stabilization-and-product-improvements/task_plan.md), [Evidence Vault](../design/evidence-vault/PLAN.md), and [PLAN-37 Slice 1](PLAN-37-connected-compliance-experience.md) as prerequisites. The current checkout includes unfinished local Vault work, and PLAN-37 records business-unit title exposure in Related Items and topbar search. Recheck status before work starts. A cross-module inspector or assessment projection must not widen those access paths. Keep evidence search, pagination, stable deep links, and scoped relationships as shared services.

### 1. Assurance quality inspector

Start with deterministic, explainable rules over existing records. Each result should carry rule ID/version, organization and business-unit scope, source IDs and versions, evaluated time, severity, owner, and a Fix link. Initial rules:

1. A requirement is marked compliant or a control implemented without current, reviewed evidence required for that claim.
2. A linked evidence version is expired, rejected, superseded, or inaccessible to the current reviewer.
3. Residual risk is reported lower than inherent risk without a linked, effective treatment/control and assessment rationale.
4. An overdue audit, BCM exercise, DPIA/AIIA review, or policy review has no accountable owner or action.
5. Once formal acceptance exists, an accepted risk is expired, lacks approval, or rests on a materially changed source record.

Show “why flagged” and “what resolves it”, suppress duplicates, and let a reviewer record a reasoned exception. Use the inspector in ARIA, GRID, ERM, Vault and the Command Centre, with one underlying result rather than five alerts. AI may summarize findings or suggest the next step; rules determine the flag. Do not compute a compliance percentage from an AI summary.

**First acceptance outcome:** a reviewer can open a finding, inspect the exact record/evidence version and rule, correct the source in its owning module, and see the finding close on reevaluation; out-of-scope users cannot infer that the record exists.

### 2. Reviewable cross-framework audit reuse

CISO Assistant's [mapping design](https://github.com/intuitem/ciso-assistant-community/blob/main/documentation/audit-mapping.md) distinguishes equal/superset mappings from subset/intersection and previews projected values before applying them. Adapt that to ThemisIQ's ARIA/GRID mappings, but keep **requirement applicability, implementation, test result, evidence currency, and reviewer decision** separate. A mapping expresses possible reuse, not equivalence by default.

For a target framework or audit, show: source assessment, source date/version, mapping type and confidence, differences in wording/scope, applicable evidence and its current review state, proposed fields, and fields that remain unanswered. A reviewer can accept or reject each projection and inspect an audit trail. Re-running the projection should be idempotent and should not overwrite a later manual assessment. On partial mappings, suggest relevant controls/evidence but leave the target decision pending.

**First acceptance outcome:** one reviewed control assessment can reduce duplicate entry across two frameworks without silently marking an unmapped or partly mapped requirement compliant.

### 3. Small, reviewable assignments

Start inside GRID audit sections and Vault evidence campaigns. Show a respondent only the assigned items, due date, context, allowed evidence picker, and what the reviewer needs. Support draft → in progress → submitted → changes requested → accepted, with per-item review so one weak answer does not bounce the entire package. Route the assignment into My Work; keep GRID or Vault as the state owner. Reuse evidence by *linking a selected, versioned item* after access and relevance checks, rather than uploading another copy.

**First acceptance outcome:** a control owner can finish a five-item assignment without navigating GRID's whole framework; the auditor sees precisely which two answers need revision and the accepted three remain accepted.

### 4. Expiring risk acceptance and exceptions

Add a formal decision to the ERM treatment path, not a second risk register. Capture risk snapshot, rationale, owner, approver, scope, residual exposure, evidence/control basis, start and expiry dates, conditions, and review history. An `accept` treatment option can begin the request, but the risk should only display **accepted by authority** after the permitted approval. Material changes to score, control effectiveness, incident history, or scope trigger re-review. The quality inspector flags stale approvals. Follow [VerifyWise approval gates](verifywise-features/03-approval-gates.md) for the shared decision contract.

**First acceptance outcome:** a board report can distinguish proposed acceptance, approved acceptance, expired acceptance, and untreated risk, with a direct path to the signed decision.

### 5. Curated scope and publication, then optional imports

Complete [PLAN-SBU-04](PLAN-SBU-04-scope-legibility-and-filter.md) and use the customized Command Centre to offer a few role-specific entry points such as “Answer my audit requests”, “Review proof needing attention”, and “Prepare a board pack”. Follow the existing [auditor-sharing plan](verifywise-features/06-auditor-sharing-trust.md) for named, revocable review packs. Consider public trust snapshots only after publication controls and redaction have been proven. Versioned framework imports are a separate later slice, once the mapping and assessment semantics are stable.

## Where this changes the already drafted plans

| Existing plan | Add or clarify |
| --- | --- |
| [PLAN-37 connected compliance](PLAN-37-connected-compliance-experience.md) | Add the assurance inspector as a deterministic projection over source records; add reviewable cross-framework assessment projection to the audit journey. Keep scope fixes and AI wrapper ahead of cross-module AI. |
| [Evidence Vault plan](../design/evidence-vault/PLAN.md) | Feed evidence freshness/verification into the inspector; use versioned evidence pickers in respondent assignments. Preserve the Vault's search and intake ownership. |
| [VerifyWise relationship explorer](verifywise-features/02-relationship-explorer.md) | Show mapping strength, source/target requirement comparison, and where reuse is only a suggestion. Assessment projection requires a reviewer and belongs in GRID/ARIA workflows. |
| [VerifyWise approval gates](verifywise-features/03-approval-gates.md) | Extend the same versioned decision model to formal ERM risk acceptance and, later, policy/control exceptions. |
| [VerifyWise auditor sharing and trust](verifywise-features/06-auditor-sharing-trust.md) | Add a pre-publication quality sweep and stable snapshot diff; keep the first release authenticated and recipient-specific. |
| [PLAN-SBU-04](PLAN-SBU-04-scope-legibility-and-filter.md) | Persist the selected scope across relevant surfaces, with an always-visible indicator and server-side intersection with permissions. |

## Product advantage for ThemisIQ

CISO Assistant demonstrates efficient reuse and strong GRC structure. ThemisIQ can go further by turning a single event into a **guided, explainable journey**: a vendor outage links to BCM dependency and exercise history, ERM/ORM exposure, relevant controls, evidence freshness, assigned actions, and a reviewed board narrative. That journey uses each module's existing record, shows missing links and uncertainty, and gives the user one next action. [PLAN-37](PLAN-37-connected-compliance-experience.md) already describes this product direction. The four recommended additions above make it measurable and trustworthy.

## Guardrails and evidence limits

- **Edition and licensing:** The [repository license](https://github.com/intuitem/ciso-assistant-community/blob/main/LICENSE.md) identifies AGPLv3 terms for the public code and a separate commercial license for `enterprise/`. Adapt ideas independently; do not paste their code, UI assets, wording, bundled framework content, or mapping data into ThemisIQ without a deliberate rights review.
- **Scope and security:** Recheck the current branch and live tenant before implementation. Every relationship, quality result, assignment, export, search result, and AI citation must enforce organization, business-unit, role, and module access at read time. A focus filter is a convenience, not authorization.
- **Accuracy:** Keep “applicable”, “implemented”, “tested”, “evidenced”, and “approved” as different states. Missing data is unknown. Every assertion needs an inspectable source and version.
- **Delivery:** This document proposes product slices only. It neither marks previous plans complete nor changes application code, schema, tests, or production configuration.
