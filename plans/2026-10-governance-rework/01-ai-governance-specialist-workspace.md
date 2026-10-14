# 01. AI Governance specialist workspace

**Status:** Proposed rework. No schema, permission, navigation, or rollout change is made by this document. Read with the [programme index](README.md), the existing [AI Governance programme](../ai-governance/README.md), the G7 oversight plan in the later release, and [delivery gates](05-delivery-and-acceptance.md).

## 1. Purpose and changed product decision

AI Governance is a workbench for the governance team. Its first screen is a dashboard and decision queue, not the AI inventory or a staff request form. A governance specialist receives an external request, reviews it against known applications, providers, models, audits, controls and policies, resolves what remains, records a decision, and produces a bounded response. The requester normally does not need a ThemisIQ account.

For the first intake release, the requester completes a Google or Microsoft Form controlled by the customer's organization. A specialist exports responses and imports one response or a batch into ThemisIQ. A later, invitation-based form may reduce manual handling, but it needs its own threat model and pilot. Direct email parsing, anonymous self-service accounts, and arbitrary public upload links are not part of the first release.

The current learner-facing AI literacy page leaves this module's main navigation. Future staff training belongs in a separate project. Existing `ai_literacy_courses`, versions and completions remain available for historical audit until a separately approved migration preserves them. The AI Governance specialist may see only the training status relevant to a use, with a source and freshness indicator; no learner workflow is recreated here.

## 2. Existing behavior to preserve

- `applications` is the canonical system identity. `ai_use_profiles` stores reviewed use facts, tier, rule version and profile fingerprint. `ai_use_intake_requests` stores drafts, submissions and reviewer outcomes.
- Current service and route code already supports AIIA, profile guidance, versioned decisions and conditions, evaluations, monitoring, regulatory impact, review packs, platform feature oversight and G7 design/operation oversight. Keep their event and audit histories.
- The current screening tier is an internal aid. It is not a legal classification or approval. Material profile changes can reopen decision work.
- Review packs are frozen, recipient-bound artifacts. The rework may improve their layout and export but must preserve the current permission, expiry, revocation and audit constraints.
- The existing AI call policy layer controls provider use. New import and review assistance must use it. A deterministic path works with AI disabled.

## 3. Information architecture

### Main navigation

1. **Overview**: urgent decisions, intake aging, outstanding information, approvals with conditions, reviews due, material changes, monitoring alerts and quality gaps.
2. **Requests**: imported, manual and later invited submissions in one queue. Tabs: New, Needs clarification, In assessment, Awaiting decision, Responded, Closed. Retain a separate source label for each path.
3. **AI Systems**: searchable inventory of applications with AI profiles, owner, provider, business unit, adopted tier, decision, next review and change flags.
4. **Reviews**: assessments, evidence and controls, evaluation results, independent decision, conditions and reviewer history, grouped by AI use.
5. **Monitoring**: overdue reviews, failed evaluations, incidents, regulatory impacts, owner or provider changes, and G7 oversight status.
6. **Reports and packs**: specialist portfolio, management, board and external response views with scope and source manifest.
7. **Platform AI features**: remain a platform-operator view under Super Admin, not mixed into a customer AI inventory.

The person opening an AI system sees a compact summary first, then Profile, Related records, Assessments, Controls and proof, Evaluations, Decision, Monitoring and History. Every tab displays its owning module, current or frozen state, and direct link. The side navigation should remain short even as source modules add more features.

### Dashboard and metrics

| Element | Exact meaning and action |
| --- | --- |
| New requests | Imported/manual/invited requests not yet triaged, scoped to the viewer. Opens the filtered request queue. |
| Waiting for information | Requests with one or more open outstanding questions; shows age and responsible specialist. Does not count a pending external reply as an internal decision failure. |
| Awaiting independent decision | Complete review packages with a proposed decision, eligible decider and no final decision. Opens the decision desk. |
| Approved with conditions | Current standing approvals with at least one open condition, including due/overdue counts. A changed profile shows a separate reassessment flag. |
| Reviews due | AI uses with a next review date in the selected window and no current completed review. Count by owner and tier. |
| Material change | Uses whose provider, purpose, data, autonomy, deployment or other fingerprinted fact changed after the standing decision. Opens the difference view. |
| Evaluation and oversight gaps | Uses with failed or overdue recorded evaluations, absent source proof, or a G7 oversight arrangement that is stale against the profile. Distinguish not measured from passing. |
| Decision funnel | Counts new, triaged, assessed, decided, responded and closed by cohort and as-of period. Denominators and exclusions are visible. |

Charts should answer a management question: intake aging by week, review-to-decision time by tier, conditions overdue, approval status by business unit, evaluations by outcome, and material changes awaiting reassessment. The dashboard shows source timestamp, scope and data availability. An empty tenant gets a guided first action; an unavailable source gets an unavailable state, never a sample count.

## 4. External Forms import, first release

### Form contract

Publish a versioned field guide and sample form for the customer's administrator to configure. The minimum external questions are: use name, purpose, requester organization/contact, provider or product, how it is provided, intended users, types of data, whether the use affects decisions about people, intended launch/use date, and the business owner as a name or email. Optional questions include affected people, autonomy, jurisdictions, outside access, known model/version, existing approval or audit reference, and supporting documents. A form never asks the requester to choose an internal `owner_user_id` or business-unit database ID.

The ThemisIQ import accepts a supported CSV or XLSX export only after the real customer export shape, encoding and date behavior are inspected. The upload screen requires a saved mapping from source column to `rules.FIELDS`, mapping version, source system, organization, source form name and export date. Unknown columns remain visible in preview, are not silently copied into the AI profile, and may be retained only under an approved data classification. Attachments are referenced through a reviewed Vault upload path, not fetched from arbitrary URLs.

### Import workflow

1. Specialist selects the organization, form mapping and file. The app checks size, content type, row bounds, malware/scanning policy and parse errors before storing any request.
2. Preview displays each row's mapped answers, raw source field labels, missing required answers, invalid choices, suspected duplicate responses and possible matching applications. The specialist can change mapping or reject individual rows.
3. Deterministic normalization handles dates, Boolean choices and allowed vocabulary. The app never guesses a legal conclusion or silently maps an unknown owner. Name/email matching yields candidates, and the specialist confirms an in-scope internal owner or leaves an explicit owner gap.
4. Exact reimport of the same source response is idempotent. Store a source fingerprint and correlation key with the mapping version and import batch. A corrected response becomes a new revision with a visible diff; it does not overwrite a previously decided use.
5. On confirmation, create an imported request draft in the existing intake lifecycle. The signed-in specialist is `submitted_by` as the importing actor; requester name/contact are separate external-submitter facts. Do not impersonate the external requester or grant them an account.
6. A triage specialist checks completeness, classification, owner, business unit and access. Submission into formal review uses the existing version check and audit trail. Malformed rows remain import errors and cannot appear as assessed uses.

Proposed data addition: an import batch record, per-row outcome/correlation, source mapping version and a bounded external-requester record. The exact table design follows a schema and retention review. Store a hash of the uploaded export and a minimal encrypted/private original only if needed for provenance; otherwise keep the approved field snapshot and a short-lived source file. Do not put raw requester contact information into a shared AI prompt or audit message.

### Later invitation path

Only after import proves the field contract and the pilot establishes volume: issue a single-use or limited-use invitation to a named external contact, expiring after a short period, scoped to one organization and request. The form has no access to the inventory, other requests, Vault search or reports. Require rate limits, anti-abuse controls, attachment scanning, revocation, ownership verification, privacy notice and auditable submission. The specialist still triages and resolves identity and owner. Reuse the same field schema and review queue; do not build a second intake engine.

## 5. Precedent-assisted review and outstanding work

The request workbench compares the submitted use with records that the specialist may open: canonical applications and AI profiles, approved vendor identities, prior evaluations, GRID audit outcomes, ARIA policies/controls, Sentinel RoPA/DPIA, ORM AI controls and incidents, ERM risks/acceptances, BCM dependencies, and current Vault evidence. An optional future model-component catalogue is considered only if source version and ownership can be maintained. A matching name alone is weak evidence.

Present results in four bands: **verified same use**, **possible match**, **related precedent**, and **no relevant record found**. Each candidate has match reasons, source ID/version, owner, status, last review, data/deployment differences and a deep link. Only a specialist can confirm or reject a relationship. A prior approval is never transferred automatically to a new use, vendor version, jurisdiction or data category.

Deterministic rules generate an outstanding-items checklist: missing request facts; owner and sponsor; relevant Privacy work; AIIA; vendor and data flow review; technical/security controls; evaluation method and result; human oversight; continuity impact; regulatory applicability; current proof; and independent decider. Each line has one owning module, severity/priority reason, assignee, due date, source or rule version, and a resolution path. The list distinguishes **not applicable with reason**, **not yet assessed**, **waiting on another party**, **failed**, and **complete**. AI may draft a plain-language explanation or suggest a precedent, but cannot change a line's formal status.

Specialists can create a bounded question set for the requester and export it for email or the customer's chosen channel. The response is imported/entered by a specialist and linked to the same request with provenance. Requests and clarifications should not spawn a second generic task system: use existing My Work/workflow and source-module actions.

## 6. Assessment, decision and response

After triage, the AI use is linked to an existing `applications` record or promoted once into a new one. The workbench routes each specialist review to its owner: AI Governance AIIA and decision, Sentinel personal-data assessment, ORM AI control and event, ERM risk and formal acceptance, ARIA policy/control, GRID audit, BCM continuity and Vault proof. A reviewer can see the status and a scoped deep link without copying the full source record into AI Governance.

Before proposing a decision, require a frozen decision brief containing the profile fingerprint, tier and rule version, applicable reviews, evidence version IDs, evaluation outcomes, unresolved gaps, proposed conditions, intended scope of use, owner and expiry/review date. Missing data remains a gap, not a pass. The existing G4 independent-decision control applies; a specialist may review a request yet cannot be the independent decider where separation is required. A material later change creates new review work and never edits the prior signed brief.

An **external response pack** is separate from the internal decision and the existing signed-in review pack. It contains an approved summary, outcome, scope, conditions, outstanding requester actions, expiry/review date, source reference and response date. A specialist previews and redacts it; the decider or authorized communicator approves release. Export PDF and structured JSON/CSV as appropriate, with a frozen manifest and revision. The first release downloads for the specialist to send externally; ThemisIQ does not email the requester or create an anonymous evidence link. Record that a response was exported and allow a person to mark sent with date/channel/reference. Do not claim delivery merely because a file was downloaded.

## 7. Roles and access

| Role | May do | May not infer or access |
| --- | --- | --- |
| Governance specialist | Import, triage, review in-scope requests, resolve links, assign actions, draft response | Cannot decide their own use where independent approval is required; cannot browse another unit's hidden records |
| Specialist reviewer | Complete the relevant AIIA, Privacy, risk, audit or control review in the owning module | Cannot silently change an earlier decision or another module's source state |
| Independent decider | Read the frozen brief and permitted sources, decide/condition/reject, request rework | Cannot approve without required evidence or bypass separation by changing requester identity |
| Management viewer | See aggregates and drill down within permitted scope | Cannot see hidden request names, source excerpts or personal training results |
| External requester | Uses the customer's external form; in a later phase, a bounded invitation | No ThemisIQ login or inventory access in the first release |
| Platform operator | Reviews first-party AI features and global provider policy | No customer-tenant content in a shared operator inventory |

Every import, match, snippet, count, report, pack and citation applies source authorization. Returned links do not grant access. The portal, when built, uses its own narrow auth boundary and cannot inherit specialist privileges.

## 8. Literacy separation and history

Inventory current courses, completions, My Work assignments, quality checks, report consumers and links before changing navigation. Hide learner and course management from the specialist sidebar only when those references have a safe route or are clearly archived. Preserve old versions and completion audit history in read-only mode for its retention period. A separate staff-facing project may later supply a signed, minimal status contract: employee identifier, course/version, completion or expiry, effective date and verification source. No raw quiz answers or staff application code belongs in this repository. AI-use approval may require a current status only if the organization's policy explicitly says so and the status source is available; unknown is not complete.

## 9. Guardrails and design requirements

- No auto-approval, legal classification, publishing, external response, risk acceptance or source-record write by an AI model.
- A file or web page is untrusted data. Ignore embedded instructions, show citation provenance, and never retrieve from an arbitrary external URL during import.
- No raw request file, personal data, hidden evidence, or full document text in provider prompts unless the organization policy permits that data class and the exact feature requires it. Minimize before sending.
- Use stable tenant and business-unit scope before ranking or AI generation. Recheck source access when a match, citation, export or pack is opened.
- Keep statuses distinct: imported, triaged, in assessment, awaiting decision, decided, externally responded and closed. History is append-only or versioned where a decision depends on it.
- Loading, empty, partial, stale, conflict, provider-disabled and unavailable states are explicit. Tables and charts are keyboard usable, work at 200 percent zoom, and offer reduced motion.

## 10. Acceptance examples

1. Two identical imports of one response create one request and one auditable duplicate outcome. A corrected export creates a visible revision, without replacing a decided brief.
2. An external requester without a ThemisIQ account can submit through the customer's form; the specialist can import and review it. The importer's identity and external requester's identity remain separate.
3. A specialist can identify a true prior use and a similar but materially different use; neither is treated as approved until the relevant source and differences are reviewed.
4. Missing owner, DPIA, evidence or evaluation appears as an outstanding item with a source and next action. A previous approval cannot turn the current gap green.
5. A decision is reproducible from source versions, rule version, actor and time. A profile change reopens review without changing the historical decision.
6. A downloaded external response has the approved outcome and conditions, a version, as-of time and source manifest. Its state remains `exported` until a person records that it was sent.
7. Removing AI literacy from the specialist navigation does not delete courses or completions, break My Work, or change a recorded decision silently.
8. Wrong-organization, wrong-unit, requester and recipient roles reveal no hidden request title, count, existence, link, snippet, source ID or report content.

## 11. Open product decisions before implementation

- Who owns the customer form template and retention of its original responses? Default: customer administrator owns the form; ThemisIQ stores reviewed snapshots and source references.
- Is external requester contact required in the saved request, or only in the source form? Decide after privacy and response-process review.
- Which business units may share precedent across a parent group? Default: only records the specialist can independently open.
- Which fields must be present before formal review and which may remain open for assessment? Use the existing `rules.REQUIRED_TO_SUBMIT` as a starting contract, then validate with governance specialists.
- What is the exact external response sign-off role and approved export format? Pilot with one named specialist and decider before offering templates to all tenants.
