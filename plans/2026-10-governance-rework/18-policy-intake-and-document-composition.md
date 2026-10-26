# 18. Existing-policy intake, governed document composition, and connected references

**Status:** Implemented on a release branch, 2026-10-26; production rollout depends on merge and release verification. The original plan below remains the target contract. The implementation and remaining gates are recorded in section 11. Earlier observations describe the starting point and are historical.

**Product outcome:** A governance specialist can bring an organization's already approved policies into ThemisIQ without rewriting them or labeling every file by hand. ThemisIQ preserves the original, proposes metadata and clause-level framework links with source citations, lets a person verify those proposals, and exposes the exact authorized policy version to other modules when relevant. The specialist can rebrand a subsidiary document or compose a new one with diagrams while retaining provenance and approval history.

## 1. Decisions and relationship to existing plans

This is a delivery companion to [PLAN-35 policy authoring](../PLAN-35-aria-policy-authoring-flow.md), [the Vault assurance contract](02-evidence-vault-and-assurance.md), [the Vault product plan](../../design/evidence-vault/PLAN.md), and [PLAN-37 connected compliance](../PLAN-37-connected-compliance-experience.md). Their immutable policy versions, named internal approvals, scope rules, reviewer verdicts, and current-version publication contract remain the foundation. This plan adds intake, external approval provenance, clause-level mapping, composition, and safe reference reuse; it does not establish a second policy register.

| Decision | Default for this build |
| --- | --- |
| Primary journey | Import an existing policy; the generator remains an optional authoring path. |
| Upload requirement | Require a file and an authorized organization/scope. Suggest title, type and frameworks after extraction; never preselect the first framework. |
| Original | Preserve the submitted bytes and hash. Transformations create separate immutable renditions or candidate versions. |
| Approval | An imported assertion that a policy was approved elsewhere is recorded as an assertion until a specialist checks its approval evidence. Never fabricate an in-app approval decision. |
| Framework link | AI and rules propose candidates against active control records. A specialist confirms a version-specific clause-to-control relationship before it affects coverage. |
| Evidence meaning | A policy can address a requirement. Its existence does not prove that the required control operates or is effective. GRID and other modules retain their own evidence verdicts. |
| AI use | Local extraction and deterministic matching first. Provider-assisted interpretation requires the organization's AI policy, classification permission, token budget and explicit review. |
| Other modules | Read the owning ARIA policy version and Vault artifact through one scoped reference service; do not copy policy bytes into each module. |
| Change | Identical bytes do not create a new version. A new original, material content change, or approval decision has explicit provenance and its own immutable identity. |

## 2. Verified starting point and gaps

- `modules/aria/templates/documents.html` offers `Extract Metadata`, but the form marks frameworks as required and checks the first framework when opened. Its JavaScript fills only title, version, dates, owner, approver and type.
- `modules/aria/routes.py:parse_document_upload` calls `_extract_document_metadata`. The latter reads DOCX properties and paragraph text; its PDF route uses a narrow raw-byte pattern. Other accepted extensions receive a filename-based result rather than real body extraction. No clause-to-control proposal is returned.
- The legacy upload path creates an ARIA Draft and `_sync_aria_to_vault` copies the file to the Vault. Its existing-row update changes the file path. The PLAN-35 managed path instead confirms immutable `aria_policy_versions` and publishes an approved version to the Vault through a retryable job. The build must converge these paths without rewriting historical records blindly.
- `modules/aria/branding_engine.py:apply_template` currently guesses the source body's beginning from headings such as Purpose or Scope. Its own comment records a case where an unmatched first heading can cause all content to be dropped. Deep copying DOCX body XML alone does not establish that embedded diagram relationships, footnotes and section-specific headers survive; test the actual produced package and rendered pages.
- The Vault already has scoped items, versions, exact-hash duplicate detection, links, a text index and generated-record deduplication. Extend these services rather than creating an ARIA-only search or another file library. The Vault plan's richer artifact-family and proof semantics are still design work; verify their implementation before using them as a dependency.
- PLAN-35 defines `aria_documents` as policy identity and `aria_policy_versions` as immutable versions. Existing policies stay current during a replacement review. The new import flow must honor that rule.

Implementation must first verify the current checkout, fresh PostgreSQL and SQLite schemas, tenant-schema migration path, module capability inventory and production feature flags. This snapshot is a plan baseline, not a claim that every PLAN-35 or Vault proposal is enabled for every organization.

## 3. User journeys and information architecture

### 3.1 Upload existing policies

1. From **Policies & Documents** or **Evidence Vault**, choose **Import existing documents**. Offer a single file, multiple files and a bounded batch. The first screen asks for the authorized organization and optional business unit; organization-wide scope needs its existing manage capability. It does not require a framework or control guess.
2. Validate the actual file type, size and archive complexity, scan in a constrained worker and quarantine a failed file. Show each file as **waiting**, **extracting**, **needs review**, **ready to register**, **failed** or **registered**. A failed extractor must leave a safe manual registration route and a clear reason.
3. For each file, show a two-pane workspace: paginated source preview on the left; suggested title, type, version, effective/review dates, named roles, classification, applicability, related records and framework matches on the right. Every extracted value opens the page/section/paragraph that produced it. Allow **unknown** and **not found** rather than inventing a value.
4. Present possible duplicates inside the caller's authorized scope: **same bytes**, **possible new version**, or **similar title/different document**. Do not expose the title, count, hash or existence of an inaccessible item. A specialist chooses reuse, new version or separate identity.
5. A reviewer accepts or edits fields and control links. Bulk accept is allowed only for selected, evidenced suggestions; no blanket “approve all compliance” action. Rejected suggestions retain a reason and do not reappear unchanged after a rerun.
6. Register the original in a canonical Vault artifact family and connect its exact version to `aria_documents`. Display source provenance and the state of external approval verification. Indexing, cross-module references and publication run idempotently and report failed synchronization without pretending it succeeded.

The default list becomes an **Import review queue** with source, detected type, organization/BU, likely policy family, review blocker and next action. A specialist can review 20 files without reopening the full upload form 20 times. Keep keyboard access, narrow-screen reading order, persistent filter position and clear progress for long-running extraction.

### 3.2 Existing external approval

An imported policy may already be in force. Capture the supplied approval statement, approver identity or role, approval date, signed page or separate approval artifact, effective date, scope and verifier. States must distinguish `claimed in force / unverified`, `externally approved / verified`, `internal approval pending` and `internally approved`. A specialist may attest that external approval evidence was seen; that attestation records who, when, the source hash and limitations. It is not an `aria_document_approvals` decision made by an in-app approver. If approval cannot be established, retain the policy and mark the uncertainty. A rebranded output is a new rendition; changes to normative content need a new candidate version and the PLAN-35 approval path.

### 3.3 Rebrand or replace content

After import, offer four explicit actions:

| Action | Source content | Target presentation | Review consequence |
| --- | --- | --- | --- |
| Register unchanged | Entire original | Original | Verify supplied metadata and approval provenance. |
| Use content with our template | Reviewer-selected body, tables and diagrams | Organization or subsidiary template | Compare content and media; a reviewer attests presentation-only changes. |
| Keep cover, replace body | Approved cover/layout | Selected existing or drafted body | Creates a new candidate version; content approval required. |
| Recompose | Reviewer-selected sections and replacement blocks | Chosen template | Creates a new candidate version if normative content changes. |

The reviewer sees a structural outline and rendered pages. They mark the cover, cover letter/foreword, document-control table, table of contents, body sections, appendices, headers, footers and watermarks **keep**, **exclude** or **replace**. “Table of contents” and “document body” are separate controls. Do not infer that page 1 is always the cover. Show the exact selected boundaries and a side-by-side original/output preview. A renamed subsidiary, legal entity, system owner or jurisdiction inside the body is a review suggestion, not an automatic global replacement.

Offer **preserve source body formatting** and **adopt target styles**. Regenerate the table of contents and page numbers only after the final rendering; report unsupported fields or media instead of shipping a plausible-looking incomplete file. DOCX imports must preserve relationships for embedded images, diagrams, hyperlinks and footnotes or fail with a specific review item. For PDFs, offer an unchanged original with a new cover as a reliable first path. An OCR-derived editable version is explicitly a reviewed reconstruction, never a silent conversion. Store the transformation manifest, source and target hashes, template snapshot, excluded ranges, reviewer and visual-comparison outcome.

### 3.4 Diagram blocks in new documents

The editor offers manual upload of an approved figure and structured blocks for process flow, swimlane, data flow, responsibility map and system block diagram. A block stores editable nodes, edges, labels, captions, alt text, dimensions and source record references. A deterministic renderer produces a preview and export image; the editable source remains with the immutable policy candidate. AI may propose a diagram from visible, approved applications, processes, assets and owners; it may not invent topology or assert that a drawn control exists. The author confirms every node/edge and an approver sees the exact rendered version. Diagram changes participate in semantic diff and approval. Imported diagrams remain in the unchanged source even if extraction cannot understand them.

## 4. Extraction, suggestion and review contract

1. **Parse and locate.** Use a resource-limited parser/converter worker for PDF, DOCX and explicitly supported legacy formats. Extract headings, paragraphs, tables, document properties and figures in reading order with page/section anchors and parser version. Add OCR only for pages without usable text. Inspect image captions and visual content only where the organization's AI/data policy allows it. A figure's presence alone supplies no control claim.
2. **Classify.** Suggest document type, owner, applicability, review cycle, lifecycle dates and confidentiality. Separate exact quoted values from inferred values. Show confidence and the visible source span; ambiguous dates and names remain unresolved.
3. **Match.** Retrieve candidate controls only from active frameworks visible to that organization. Use exact cited references first, then curated framework equivalences, then bounded semantic ranking for ambiguous clauses. The proposal records source version, clause/page, target control ID and catalogue version, relationship type (`addresses`, `partially addresses`, `related`), confidence and rationale.
4. **Adjudicate.** A specialist confirms, edits or rejects each consequential mapping. Accepted policy coverage is separate from implementation/effectiveness evidence. Changes to the policy, control catalogue or equivalence map raise a re-review task for affected links; no silent carry-forward to a new version.
5. **Find gaps.** Show requirements with no accepted policy clause, policy statements with no mapped requirement, expired review dates and conflicting versions. Call these **review candidates**, not compliance failures. A policy coverage map opens the exact clause, framework control and reviewer verdict.

Do not send full files to an AI provider by default. Run deterministic extraction locally; transmit only minimized, authorized snippets for ambiguous tasks if the tenant's AI policy permits that feature and data category. Save model/version, prompt class, token use and suggestion outcome without logging unnecessary document text. Upload content is untrusted data, never an instruction to a model or a tool. AI outage leaves the manual path usable.

## 5. Record ownership, versions and API boundaries

| Logical record | Owning service | Required invariant |
| --- | --- | --- |
| Policy identity and lifecycle | ARIA `aria_documents` and PLAN-35 workflow | One policy family, current approved version remains available during revision. |
| Immutable policy content and decision | `aria_policy_versions`, approval history | Approval identifies exact body, source, branded output, diagram and preview hashes. External attestation stays distinct. |
| Original bytes and presentation renditions | Evidence Vault artifact family | One discoverable family; original, branded DOCX, preview PDF and editable diagram source are typed renditions with hashes and provenance, not four unrelated top-level cards. |
| Extraction/index | Version-scoped Vault text index plus an intake run record | Page/section offsets, parser version, status and errors; source change invalidates index and suggestions. |
| Candidate metadata/control relationships | Review queue keyed by source version and catalogue version | Candidate links do not enter approved coverage, scores, search answers or reports until accepted. |
| Confirmed cross-module reference | Existing `evidence_links` and `cross_module_links` rules | Both ends visible and link action authorized. The target points to an exact policy/Vault version, with a separate relevance or evidence verdict. |
| Composition manifest | New immutable rendition/candidate metadata | Selection rules, template snapshot, content/media comparison and reviewer attribution are replayable. |

Keep the storage design additive until a schema review resolves whether Vault renditions need a dedicated table or can be modeled on the current version family. Do not point two modules at mutable copies of the same file. Migrate the legacy ARIA upload copy path and the managed publication copy path through a count/hash/permission crosswalk, reader-by-reader; retain old bytes and links until downloads, historical audits and rollback have been checked. The Vault owns artifact storage in the target design; ARIA owns policy approval and lifecycle.

Expose a shared, typed service such as `resolve_policy_references(viewer, source_record, as_of, purpose)`. It checks the source record, ARIA policy, Vault artifact, organization, BU, classification, version and link verdict before returning a title, status, excerpt citation and deep link. Default to current, in-force, reviewer-confirmed references. An auditor's saved pack resolves the frozen as-of version. A caller cannot discover a hidden title, count, snippet, hash or candidate link. Drafts remain visible only through their authoring permissions. Add stable deep links to page/section in the exact artifact version.

## 6. Connected-module behavior

| Consumer | How it calls or contributes a policy reference | Ownership retained |
| --- | --- | --- |
| ARIA frameworks and canonical controls | Show accepted clause-to-control coverage, gaps, policy owner and exact current/previous version. An imported policy may cover several frameworks without duplicating the file. | ARIA owns policy state; control library owns requirement identity. |
| GRID audits | From a checklist item, open the applicable policy clause and request operating proof if needed. Include the frozen version in an audit pack. | GRID owns audit test, finding and acceptance; a policy link is not audit approval. |
| BCM | Plans, BIAs and exercises may cite a current policy or diagram as context. A policy revision prompts the plan owner to reassess only affected references. | BCM owns continuity decisions and exercises. |
| Sentinel | DPIA, RoPA and breach work may cite data-handling policies under case and sensitivity gates. Citation is version- and jurisdiction-aware; do not derive a legal deadline from policy prose. | Sentinel owns privacy assessment and jurisdiction decisions. |
| ERM and ORM | Risk treatment and control design may reference policy statements; closure still requires proof of action and reviewer acceptance. | Risk modules own risk/acceptance decisions. |
| AI Governance | AI-use screening, AIIA and oversight can cite a verified AI policy clause and flag an outdated or absent policy. | AI Governance owns use/impact decisions. |
| Evidence Vault | Shows the one artifact family with original, approved renditions, versions, links, review verdicts and provenance. | Vault owns bytes and artifact integrity. |
| Ask ARIA, Themis, reports and Command Centre | Retrieve only authorized, in-force versions with exact page/section citations and an explicit “cannot verify” state. Issued reports freeze the version manifest. | The owning module remains source of status; summaries are scoped projections. |

The shared reference action is read-only by default. Creating a link, accepting a proof claim, approving a policy, changing a diagram, or publishing a rendition requires the applicable module capability and a named person. In-app My Work alerts the owner about review dates, broken references and materially changed clauses. Email is optional and remains behind the sender setup planned separately; notification delivery is never treated as acknowledgement.

## 7. Security, privacy and reliability

- Validate signatures and parsed type, cap bytes/pages/embedded objects, scan uploads, disable macros and remote fetches, and run parsers/OCR/converters with bounded CPU, memory, time, filesystem and network privileges. Quarantine unsafe files. See [OWASP File Upload guidance](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html).
- Treat extracted text, hidden fields, image text and model output as hostile input. Never let them set capabilities, choose another tenant, invoke arbitrary tools or override review. See [OWASP prompt-injection guidance](https://genai.owasp.org/llmrisk/llm01-prompt-injection/).
- Apply authorization **before** extraction-result list, duplicate search, candidate ranking, page preview, download, citation, related-record count and AI retrieval. RLS is defense in depth. A foreign object ID gets the module's existing non-disclosing response. Version text must not survive an access revocation in a cache.
- Store original and derived files outside the public webroot; serve via authorized endpoints. Audit import, extraction failure, field correction, link suggestion/verdict, transformation, approval attestation, publication, download and retention actions without copying sensitive policy text into generic logs.
- Guard transactional creation of file references and link rows; retry idempotently after worker failure. A partial import is visibly incomplete, not approved. Verify startup and tenant migrations in SQLite and real PostgreSQL.
- Use each organization's retention policy, legal hold and version rules. Exact duplicates can be reused; historical approved policies and issued-report manifests are not deleted merely because only the latest version appears in the default library. The earlier two-copy convenience rule for generated review documents does not govern approved policy history.

## 8. Delivery slices and exit gates

### P0: Correct the promise of “Extract Metadata”

Remove the prechecked framework. Make title and framework optional until review. Show extraction provenance and unsupported-file behavior honestly. Replace the weak PDF heuristic with a safe bounded parser; support DOC/DOT/ODT only after an isolated conversion and round-trip test, or narrow the UI's extraction promise. Add an import identity and a reviewed ownership/scope decision. **Gate:** a policy with no framework, an ambiguous date or a scanned page imports safely without a fabricated label; a wrong-unit user sees no hint.

### P1: Canonical intake and review queue

Create batch staging, per-file progress, exact-hash deduplication, original Vault artifact/version, reviewer-confirmed metadata and external approval attestation. Reconcile legacy ARIA/Vault copies before switching readers. **Gate:** the same file does not add clutter; a changed file remains a candidate until reviewed; original bytes and prior approved version remain downloadable.

### P2: Clause mapping and connected references

Use the active control library and existing relationship registry to propose, adjudicate and serve exact-version clause links. Build a coverage map and shared reference resolver. **Gate:** a suggested link cannot change control coverage; a confirmed clause opens from GRID, BCM, Sentinel, ERM/ORM and AI Governance only if both records are authorized. Issued packs retain the cited version.

### P3: Composition and diagram studio

Add the section picker, organization/subsidiary branding profiles, provenance manifest, content/media diff, approved diagram blocks and deterministic exports. Replace the current start-of-body heuristic with explicit selection. **Gate:** tests cover title/cover, first-page and later headers, TOC, tables, links, footnotes, images, diagrams, mixed portrait/landscape pages, and a PDF-only source. Any loss is shown before confirmation and blocks publication.

### P4: Pilot and measured rollout

Pilot with at least one clean DOCX policy, scanned PDF, subsidiary-branded document with cover letter, diagram-heavy plan and a revised policy across two business units. Measure time to file a policy, manual fields per import, extraction precision, mapping acceptance/rejection, duplicate rate, diagram/export fidelity, retrieval citation accuracy, unauthorized-existence signals and token use. Compare 500- and 5,000-artifact navigation with the Vault plan's targets. Enable by organization only after specialist and security review; preserve feature-off and rollback paths.

## 9. Decisions to verify before code, with proposed defaults

1. **External approval authority:** default to a named specialist attestation with original approval evidence and explicit `external_verified` provenance. Do not manufacture an in-app approval event.
2. **Artifact family/rendition schema:** default to one Vault family with source plus typed derived renditions. Validate against existing `evidence_items`, `aria_policy_versions` and publication jobs before migration.
3. **Presentation-only adoption:** default to requiring a human visual/content comparison and attestation; any substantive clause or diagram change becomes a new candidate for named approval.
4. **PDF editability:** default to preserving the PDF as source and attaching it behind a new cover. OCR reconstruction stays a separate reviewed choice.
5. **Diagram scope:** default to structured, editable, deterministic diagrams. Visual generation from a prompt alone is out of scope until sources and review controls are proven.
6. **Provider choice:** no document content goes to an external parser or LLM without a tenant-level data-processing and AI-policy decision. The core path must work locally and without an AI provider.

## 10. Source notes

- The reviewed repository is the authority for current behavior. PLAN-35 and the Vault plan are design contracts whose individual gates must be checked against current code and deployment.
- [NIST OSCAL SSP model](https://pages.nist.gov/OSCAL/documentation/schema/ssp/) models control satisfaction down to specific statements and components. This supports the choice to store clause-level relationships instead of a document-level “compliant” flag; it does not make an imported policy proof of implementation.
- [Microsoft Document Intelligence layout documentation](https://learn.microsoft.com/azure/ai-services/document-intelligence/prebuilt/layout) demonstrates that text, tables, sections and figures can be extracted with structure. This is a feasibility reference, not a provider selection or accuracy guarantee.
- [python-docx header/footer documentation](https://python-docx.readthedocs.io/en/latest/user/hdrftr.html) explains first-page and section-specific headers that composition tests must cover.

## 11. Implementation ledger, 2026-10-26

### Built in the isolated worktree

- Existing-policy intake accepts DOCX and PDF, requires an explicit business-unit or organization-wide ownership decision, stores the original privately, and runs bounded local extraction in a separate process without the web service's environment variables. The review workspace shows source anchors, editable metadata, control candidates and manual control search. An unknown version must be entered by the reviewer; a scanned PDF is marked as having no extractable text.
- Exact-byte duplicates are reused only within the same organization and ownership scope. Registration creates an ARIA identity, an immutable source version, one Vault original and a link. Suggested control links have no effect until individually accepted. External approval has a separate independent human attestation and never creates an in-app approval event.
- A specialist can explicitly match a changed annual upload to an approved policy in the same organization and business unit. The new source version and Vault child remain pending while the previous approved version stays current. Only an independent external-approval verification adopts the replacement; concurrent changes to the current version stop adoption. The old original remains accessible as a superseded version.
- DOCX composition uses an explicit source block boundary and reviewer-selected exclusions. It can replace a cover, body, or both, add a supplied logo, a reviewer-supplied PNG/JPEG figure with caption and accessible description, and deterministic structured diagrams. It records source/output and embedded-media hashes in a transformation manifest. A changed DOCX enters the existing named policy draft and approval workflow. New generated policies can also contain reviewed diagram blocks.
- PDF intake preserves the original. A new cover is a separate rendition whose retained body pages are compared by page content, embedded images and dimensions. An independent approver must record the presentation comparison before the rendition is linked as a Vault child artifact.
- A scoped reference service returns an exact, current, in-force policy version and Vault artifact only for confirmed links. Connected-record panels and report sections use it. The policy remains context or coverage, not proof of operating effectiveness. The old upload's metadata extraction uses the same isolated parser, and its Vault synchronization now creates immutable child versions instead of overwriting an existing file path.

### Verification and release gates still open

- Verification completed locally: focused backend and browser tests exercise intake, authorization, duplicate handling, annual updates, original/Vault provenance, DOCX media retention, diagrams, PDF cover review, schema and linked references. A disposable PostgreSQL 18 database verified fresh initialization, a reviewed policy registration, and the old unique-index upgrade in both public and tenant schemas, including idempotent reinitialization. The new upload and version-creation routes honor the existing per-organization ARIA policy-authoring rollout flag. A two-business-unit pilot, visual page-by-page comparison and production storage/backup test have not been performed. Keep customer rollout limited until those checks are complete.
- Extraction is intentionally local and rule based. OCR, DOC/DOT/ODT conversion, classification of jurisdiction and applicability, provider-assisted interpretation, figure understanding and semantic matching are not shipped. Failed extraction can be reviewed manually. The parser has time, CPU, memory and descriptor limits on Linux, but does not yet have a dedicated unprivileged account or network namespace; production hardening must address that isolation.
- The UI offers an explicit DOCX block outline and downloaded preview, not a rendered side-by-side visual diff. Source XML and media are retained in tested cases, but complex footnotes, generated TOCs, fields, headers and mixed page layouts still require rendered comparison before approval. Tenant-managed branding profiles, swimlanes and data-flow-specific layouts remain open. A supplied figure is embedded with its hash, caption and alt text; the author and approver must verify its provenance and reuse rights.
- The shared policy reference service is used by connected-record views and report sections. Module-specific clause entry points, frozen as-of citations in issued packs, revision alerts, coverage-gap dashboards and 500/5,000-artifact navigation tests remain open. Existing legacy ARIA/Vault rows require a count/hash/permission crosswalk before any reader migration.
- The annual-version path supports externally approved replacements after independent verification. Internally authored annual updates still use PLAN-35's draft and approval path. The old one-import-per-document unique index is replaced by a nonunique index; public and tenant upgrades were verified in disposable PostgreSQL. The production backup and rollout remain release checks.
- An approver must verify external approval against original evidence. Legal accuracy, wording and control applicability are human decisions. No source document is sent to an AI provider by this build.
