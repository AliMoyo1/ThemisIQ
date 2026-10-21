# 02. Evidence Vault and assurance at scale

**Status:** Proposed extension and correction of the existing [Evidence Vault plan](../../design/evidence-vault/PLAN.md). No Vault behavior changes here. Read with the [programme index](README.md) and [delivery gates](05-delivery-and-acceptance.md).

## 1. Product outcome

At 500 to 5,000 documents, images and generated records, a specialist can find the right current proof, understand what it supports, see who accepted it, and request or renew what is missing. The Vault holds the canonical artifact and its versions. A specialist module owns the decision that an artifact is sufficient for that module's claim or assessment.

This plan does not create a folder tree as the source of truth. One artifact may support several controls, audits, assessments and risks. Saved views and scoped links provide the navigation. Physical and logical copies should be exceptional and explicit.

## 2. Verified source baseline and unresolved semantics

- The reviewed source has a paginated, scoped list and case-insensitive metadata search. It also has cards/list, recent items, saved views, a detail panel, hash duplicate detection, versions, links, AI link suggestions, bulk archive and evidence campaigns. The older plan's claim of a fixed 200-item list is historical and must not be repeated as current behavior.
- The page currently places stats, recent cards, coverage and saved-view controls ahead of the library results, and defaults to cards. At scale, the primary search result starts too far down the screen.
- Upload asks for title, category, comma-separated tags and a combined expiry/review date. Linking is a separate action. A replacement supersedes the prior row and creates a child version, but the upload path does not carry live links to the new version.
- `compute_confidence` rewards verification method, expiry, link count and a hash. This is a metadata signal, not proof that the document is relevant or sufficient for a requirement.
- The coverage query counts a target with a linked non-archived item, including an expired or superseded item. Before changing that number, define which of *linked*, *current proof* and *reviewer accepted* the UI means.
- GRID maintains audit-specific `grid_evidence_items` and `grid_evidence_files` and mirrors files into `evidence_items`. BCM has module evidence and Vault links. A migration must retain audit and continuity decisions while converging on one artifact identity.

## 3. Information architecture

### Default library

Top line: **Evidence Vault**, a full-width search, **Upload or connect evidence**, and a small **Find evidence** action. Second line: **All**, **Needs filing**, **For my review**, **Review due**, **Requests**, **Recently updated**, **Saved views**. Third line: type, module, owner, period, status, source, business unit and sort filters; active filter chips and a clear action. Results default to a list with columns Name and source, Linked claims, Owner, Review due, State, and Updated. The file thumbnail appears in a compact preview, not as the only navigational shape.

Move detailed metrics to an expandable Insights panel. The small visible work summary contains counts of actionable items only, each opening an equivalent filtered list. Saved views store query/filter definitions, not copies of artifacts. Keep the user's list position and filter context when opening and closing a detail drawer. Show full names on focus, keyboard actions, narrow-screen row layout, 200 percent zoom and reduced motion.

### Item detail

Show, in order: current preview or generated source record; plain-language status; owner and source; evidence period, review due and expiry separately; all linked claims with each review outcome; versions and differences; integrity/provenance; activity; suggestions. A system-generated record has a deep link to its source event and no misleading file download or `0 B` file size. A restricted target appears as a generic hidden relationship or is omitted according to the source permission rule, never as a title leak.

## 4. Canonical model and proof contract

| Concept | Meaning | Owner and behavior |
| --- | --- | --- |
| Artifact family | One logical document, screenshot set or system record through revisions | Vault; stable root ID and source kind. Historical file rows remain linked to this family. |
| Version | Immutable content bytes or frozen generated record with hash, upload actor, source, created time and classification | Vault. A new file never overwrites old bytes. |
| Link | A proposed or confirmed relationship between a version/family and a target record | Vault relationship service; target authorization checked at creation and read. |
| Claim or requirement | What the module says must be proved | ARIA/GRID/BCM/Sentinel/ERM/ORM/AI Governance source record. |
| Applicability review | Whether a specific version supports a specific claim for a specified period and scope | Reviewing module, exposed through a shared contract. Outcome: pending, accepted, returned, rejected or out of scope with reason. |
| Freshness | Whether a version was effective for the claim's period and is not superseded or expired | Deterministic Vault rule with source timestamps. |
| Integrity | File hash, signature or source-system provenance | Vault. Integrity alone does not establish sufficiency. |
| Collection request | Who owes what proof by when, and who decides if it meets the request | Existing evidence campaign/request lifecycle, not a new task table. |

Present three distinct coverage measures: **has a live link**, **has current proof**, and **reviewed as sufficient**. Each measure declares its denominator, business-unit scope, as-of time, target kinds included and exclusions. Do not count superseded, expired, archived, removed or out-of-scope links as current proof. A claim with a current but unreviewed artifact remains pending, not complete. The acceptance rules may differ by source module, but the shared API must state which definition it used.

Rename or explain the existing `confidence_score` as metadata health until a reviewed quality model exists. Do not convert it into a compliance percentage. The proposed assurance inspector should report concrete defects such as missing owner, no current version, unsupported assertion, wrong period, absent reviewer or conflicting source facts, each with a route to fix. This extends the [CISO assurance quality plan](../ciso-assistant-features/01-assurance-quality-inspector.md).

## 5. Core user journeys

### Find and reuse

From any control, audit, BIA, privacy case, risk, operational event or AI use, **Attach existing** opens the same scoped Vault search used by the main library and global search. Search title, filename, reference, owner, target name and approved extracted text; show current version, period, status and why it matched. A person confirms the link and the target-specific reviewer later accepts its sufficiency. A single artifact can be reused across framework requirements after a reviewer sees the mapping and applicable period. Never infer that reuse makes every mapped control compliant.

### Upload and file

Upload wizard: choose allowed files or a generated source; review title/type, source, sensitivity, owner, period, review due and expiry; compare exact hash and likely revisions; select one or more permitted target records; confirm. A duplicate hash offers **Use existing**. A revised file offers **Add version** with a link-impact preview. Near duplicates are suggestions, never merged automatically. Source-system connectors, if later authorized, must record connection, retrieval time and query/resource ID rather than presenting a collected file as a manual upload.

### Review and renew

A source-module reviewer sees the exact version, target claim, period and context; accepts, returns with a question or marks not applicable with a reason. The owner sees renewal due in My Work. A new version prompts an impact review for every live link and does not silently inherit an accepted verdict. Existing request campaigns collect missing or renewed proof with due dates and independent acceptance; manual expiry tasks must be reconciled with those requests so one need does not appear twice.

### Produce an audit or board pack

Before issue, select as-of time, target scope and included versions. The manifest records item family/version, hash or source revision, claim link, reviewer outcome, exceptions, unavailable sources and redactions. A pack must be reproducible after a newer version arrives. Freeze the contents or cryptographic references under an authorized retention policy; never substitute the latest file when reopening an issued pack.

## 6. Search and limited AI navigation

Phase A uses server-side metadata and link-aware search with stable pagination, a consistent scope predicate and useful indexes. Phase B adds bounded extraction for PDF, Office documents and images through an isolated worker, storing version- and page-tagged text with tenant/business-unit metadata. Extraction failure leaves metadata search working and shows `not indexed`. Snippets are generated only after access checks. At 5,000 items, measure p95 latency and known-item find time before considering embeddings.

The first AI feature is **Find evidence**: parse a natural-language question into editable filters, then return up to five permitted records with match explanation, version, freshness and deep link. It is read-only and may answer `no accessible match`. The model initially receives only the query and allowed filter vocabulary; it does not need raw document content to choose filters. AI-assisted document answers are a later gate requiring page citations, scope-before-ranking, prompt-injection handling, deletion and version tests, and measured retrieval quality. No model may create links, mark evidence accepted or update a score without a person's confirmed action.

## 7. Cross-module convergence

- **GRID:** retain its audit-specific checklist and reviewer decisions. Map each existing `grid_evidence_files` row to a Vault artifact/version or record an explicit legacy exception. Stop new duplicate file storage only after both upload and download paths, historical audits, evidence bundles and permissions have a proven replacement. A Vault link is not GRID approval.
- **BCM:** a plan, exercise or incident can reference the Vault version that supports it. BCM retains plan/exercise approval and review dates. A plan revision or missed exercise can invalidate a previously adequate claim.
- **ARIA:** published policy versions remain ARIA records. The Vault exposes a managed artifact and version reference; framework mapping is a candidate link, not automatic proof of implementation.
- **Sentinel:** DPIA, breach and DSR evidence may carry personal data. Search, preview, export and AI retrieval require case permission and classification checks beyond generic Vault access.
- **ERM and ORM:** link treatment or event closure to source proof. A closure check asks whether current evidence actually demonstrates the completed action.
- **AI Governance:** use the same current-version and reviewer-verdict contract for AIIA, evaluations, oversight, approvals and external response packs.

Migration inventory must include all existing module file stores, generated records, path references, link rows, soft-deleted links, report exports, and historical version chains. Build a crosswalk and compare counts/hashes before altering readers. Avoid a one-step delete or move of old files.

## 8. Data, security and operational guardrails

- Use one authorization service for list/count/search/preview/download/link/duplicate/version/coverage/export. RLS is a second layer; the app still checks organization, business unit, module capability, target visibility and sensitivity. A duplicate response must not reveal a hidden item title or ID.
- Define ownership and retention of both the artifact and extracted text, thumbnail, OCR result and search index. Archiving or permission changes remove them from current retrieval promptly without destroying required audit history.
- Bound file size while streaming, inspect actual type, scan according to the approved malware policy, limit decompression and OCR time, quarantine failures and make worker credentials narrower than app credentials. Do not fetch arbitrary external URLs supplied in a document.
- Store raw search queries and extracted personal data only when policy permits; query strings in access logs need a deliberate decision. Use POST for sensitive searches or redact query logging.
- Version creation, link carry-forward proposal, target review reset, score recomputation and notifications must commit consistently or retry safely. An unavailable worker or module adapter is shown as unavailable, not `0` or current.
- Audit upload, version, link, unlink, reviewer verdict, pack issue, download, failed access and retention action with metadata but without unnecessary document text.

## 9. Acceptance gates

1. A library with 500 and 5,000 mixed files remains navigable by keyboard and at narrow widths; a named item and its linked claim can be found with ordinary search. Proposed performance targets are p95 metadata search under one second and known-item discovery under 30 seconds, measured in the target environment rather than asserted here.
2. The list total, stats and drill-down agree for the same authorized scope and filters; a wrong-unit user gets no item name, snippet, version, count difference or duplicate hint for a hidden artifact.
3. One artifact reused in two modules appears once in the Vault, while each target has its own reviewer outcome and date. Updating it shows an impact list and leaves old report manifests reproducible.
4. Expired, superseded, unreviewed and accepted current versions produce distinct coverage outcomes with documented denominators. No hash or link count alone turns an item accepted.
5. A request raised from GRID, Privacy, BCM or AI Governance appears in the campaign queue and My Work with the correct source link, assignee, reviewer and one reminder path.
6. A PDF/image extraction failure does not erase metadata search; unauthorized text never enters results, snippets, prompts, caches or issued packs.
7. Historical GRID and BCM references resolve through the crosswalk, with no file loss, no unexplained duplicate current items and an independently checked rollback path.

## 10. Decisions to close in Phase 0

Choose whether the artifact family is an explicit row or a stable root pointer on the existing version chain; define review due versus expiry; set the current-proof time rule; decide when a new version carries a candidate link and when target-specific approval resets; define generated-record retention and business-unit visibility; select the first two source modules for convergence. These choices must be reviewed with a governance specialist, auditor and data owner before migration design.
