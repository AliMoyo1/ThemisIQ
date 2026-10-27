# 02. Auditor registers and in-app maintenance

**Status:** Proposed. The three supplied XLSX files are user examples and possible import inputs, not a template to copy verbatim or proof that their content is current. Do not populate production records from them without an organization's scoped import review.

## 1. Product placement and common journey

The primary button is **Governance → Framework → Auditor register** because the framework defines the requirements. **GRID Audit → Audit → Evidence pack** opens the same builder with the audit context preselected. **Vault → Saved view** lets a specialist find and correct source artifacts but does not own the auditor declaration. **Reports → Registers** lists frozen runs and permits authorized reruns, comparison, sign-off, sharing and retention. AI Governance provides **AI Systems → Export register** and **Risks → Export AI risk register**; the latter is a permission-checked projection of ORM AIMS records.

The builder shows framework, organization, business-unit scope, optional audit and as-of date; then a live preview of total requirements, documents, evidence, accepted proof, gaps and unavailable sources. Each number opens the equivalent authorized row list. A specialist can fix links and metadata in their owning module, then regenerate. Exports are not edited as substitutes for their source records. A review copy is visibly dated and can be signed off independently; its stored snapshot does not silently change later.

An existing document-control workbook may be imported through the same staged mapping pattern as the AI registers: map code, title, type, version, owner, dates, approval and candidate control references to ARIA/Vault records. Match an exact organization-scoped document code plus reviewed version; let the policy-intake service preserve the original and propose control links. An import may not replace an approved policy, promote a superseded document, or turn a text control reference into an accepted relationship on its own. The example filename/banner/revision-history version conflict must be shown before confirmation.

## 2. Framework document and evidence register

### Source joins and semantics

- Framework and requirement: active Governance/ARIA framework, exact canonical control/reference and applicable mapping. Use the same framework/control read as the page; a selected framework may have zero records and still produce an honest empty register.
- Controlled document: ARIA policy/document identity, reviewed clause-to-control mapping, exact in-force immutable version, owner, approver, effective/review dates and approval provenance. Existing policy intake can propose mappings but only accepted mappings count. A procedure, record or file that is not an ARIA policy can still be represented through a reviewed Vault relationship, with its source owner and status.
- Artifact: Vault family/version ID, checksum, title/type, owner, uploaded/source date, evidence period, review/expiry, source module and download permission. Do not infer document approval from Vault `status=current` or from an asserted external approval.
- Claim: active `evidence_links` and the owning module's acceptance verdict. Distinguish `linked`, `current`, `accepted for this control and period`, `returned/rejected`, and `not assessed`. A policy describing a process is design coverage, not proof that the control operated. GRID test verdicts and findings remain GRID-owned.
- Scope: select only records the requester may read at generation and recheck access at opening/download. Organization-wide items are visible according to their source rule, not because a nullable unit is presumed public. A row with an inaccessible source is excluded without title, count, ID or existence leak.

### Workbook and PDF

One frozen run produces an **XLSX** with Cover and method, Control crosswalk, Controlled documents, Evidence and review outcomes, Gaps/exceptions, and Source/version manifest. A control with several policies or pieces of proof appears in clear relationship rows; counts use distinct control/record IDs so the summary cannot double count. The **PDF** carries a short assurance summary and **every authorized detailed register row**, with page breaks and a contents/index when needed. There is no “first 60” or UI pagination limit. For large exports, use a bounded background job and split XLSX sheets at safe row limits; if a file cannot be completed, mark the run failed rather than deliver a partial register as complete.

Suggested detailed columns: framework/version; control reference and title; applicability; document code/type/title/version; document owner and independent approver; effective, reviewed and next-review dates; approval state; Vault artifact/version/hash; linked claim and review verdict; evidence period; reviewer/date; status (current, expired, superseded, missing or restricted); audit ID/finding if selected; and a scoped internal reference. External copies use stable exported references, not links an auditor cannot open. Include a method sheet explaining `linked` versus `accepted`, as-of time, omitted data and source failures.

### Filing and access

Reuse saved report run integrity, independent sign-off, tenant-editable retention, legal hold, audit logging and scoped sharing. Default retention is a configurable product starting point, **not** a claimed legal period. Store the issued output and source-version manifest with hashes. A later policy or evidence replacement does not rewrite an issued register; a new run marks changed/removed records. Sharing cannot grant a recipient access to underlying records they were not entitled to view. External auditor invitations and bundled source files are a separate gated step with named recipient, expiry, revocation, redaction and explicit per-artifact permission. Never put raw Vault paths in XLSX.

## 3. AI systems register

### Authoritative record and in-app editing

Use `applications` + `ai_use_profiles` as the one system/use identity; connect canonical vendor, business process, data assets, assessments, decisions, evaluations and review dates through existing scoped services. AI Governance's current **AI Systems** page becomes the register workspace: create/register, update versioned facts, retire/restore, filters, completeness checks and **Export register**. Separate an organization's AI uses from ThemisIQ's own platform AI-feature inventory. Avoid calling a pending intake or an unapproved request an approved operational system.

Map the example workbook's fields explicitly: System ID → stable external reference (new field or reviewed alias); name/version/category/type → application/profile; vendor → canonical vendor; purpose, processed data, affected people and scope → profile/linked assets; PII involvement → reviewed data-category fact, not an AI guess; accountability → named role and provider relationship; risk → adopted tier with its rule/version or `Not assessed`; status → lifecycle/decision state; notes/tooling → attributed supplementary metadata; decommission year → actual retirement event. Any field without a trustworthy source remains `Not recorded` or requires a new versioned fact field, not a generated sentence.

XLSX tabs: Cover and definitions, Systems inventory (all authorized systems including retired when selected), Review/decision status, Linked AIIA/DPIA/AIMS assessment references, Data-quality exceptions, and Source/version manifest. PDF is a readable, fully detailed counterpart if requested. The register includes the selected organization and scope, status filters, as-of date and generation/sign-off identities.

### Workbook intake

Allow XLSX upload to a private, bounded staging area. Detect the example inventory tab by reviewed template profile or explicit column mapping; display row-by-row create/update/unchanged/conflict and unknown fields. Match by an organization-scoped stable system ID or an explicitly confirmed mapping to application ID, **not by name alone**. Preserve the original workbook in the Vault if authorized and allowed. No row becomes active, approved or linked to another module until a specialist confirms the import; external approval claims remain attestations requiring separate verification. The example cover says version 1.1 while its inventory says version 1.2: preview flags this and asks for the authoritative value.

## 4. AI risk register

### Authoritative risk and relationships

ORM AIMS owns `aims_assessments`, `aims_risks` and `aims_risk_controls`. The assessment already has an `application_id` migration path, but some risks span several systems. Add a permission-checked, explicit many-to-many risk-to-application relationship (using the shared connected-record service if it enforces these typed edges, otherwise a constrained join table). Preserve one risk ID and one treatment history; do not duplicate the risk for each system. AI Governance shows risks linked to visible uses and an **unlinked AI risks** worklist. ERM acceptance remains its own independent authority; a treatment field is not approval to accept a risk.

The in-app risk desk lets an authorized specialist create/maintain risks through the AIMS owner service, attach controls and proof, propose treatment, assign owner/due date, record residual assessment and trigger independent acceptance where required. Present the exact scoring rubric and effective version. Do not equate the workbook's 1–5 likelihood × impact with ORM's current AIMS computation or silently translate `CRITICAL`/`HIGH`; store imported values and a reconciliation decision. Names and vendor relationships are looked up via authorized system IDs, never free-text joins.

XLSX tabs: Cover and rubric, complete Risk register, Treatment actions (including risks with no action as an explicit gap), Linked systems, Controls/evidence, Exceptions and Source/version manifest. Include inherent and residual inputs/scores, category, impacts, control effectiveness basis, treatment and acceptance state, owner, target/next-review dates and linked source IDs. PDF includes all authorized detail rows. A single risk can appear in the relationship tab once per linked system while remaining one risk in totals.

### Workbook intake and reconciliation

Preview risk IDs against existing ORM references in the same organization and assessment. Unknown systems, duplicate IDs, missing treatments, values outside the selected rubric, free-text ISO references, unapproved acceptance and contradictory score labels become explicit review items. In the supplied example there are ten risk rows but nine treatment rows; the cover defines CRITICAL as 20–25 while one 16-point risk is labelled CRITICAL, and its treatment row calls it HIGH. These are **import warnings**, not data to “correct” automatically. A specialist can confirm a mapping, leave a documented exception, or reject the import. Imported rows remain draft until confirmed.

## 5. Security and quality

- Use source-module authorization for every preview, count, row, link, report build, file inclusion, re-open and download; capability checks alone do not widen business-unit scope. Foreign IDs return a non-disclosing response. Freeze the permitted row set, source versions and scope fingerprint in a run, then recheck the recipient's current rights before serving it.
- Treat workbook cells, hidden sheets, formulas, document metadata and files as untrusted. Reject macros/external links, cap bytes/sheets/rows/cells, never evaluate formulas, neutralize spreadsheet formula injection on export, sanitize filenames/HTML/PDF and do not follow file paths or URLs found in a workbook.
- Do not send workbook or Vault contents to an AI provider for mandatory import/export. Local deterministic parsing and reviewer mapping are the default. An optional suggestion feature needs the organization's AI policy, rights and human confirmation.
- Do not claim completeness when a source module is unavailable, a matching record is restricted, a row has unknown approval, or a capture is stale. Show `Partial`, `Not assessed`, `Unknown` or `Omitted by scope` as appropriate without revealing another unit's existence.
- Audit import mapping, row acceptance/rejection, risk-scoring reconciliation, export generation, sign-off, share, open, download, revocation and retention decisions. Never log private spreadsheet cell values into generic logs.
