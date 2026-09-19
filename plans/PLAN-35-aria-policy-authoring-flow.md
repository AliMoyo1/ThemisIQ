# PLAN-35: ARIA policy authoring, immutable versions, and named approval

Status: NOT STARTED. This is an implementation specification, not a completion report.
Original draft: 2026-09-18. Revised: 2026-09-19.
Repository baseline inspected: `d66f4da`.
Scope: ThemisIQ only.
Production target: Hetzner Ubuntu VPS, PostgreSQL, and the systemd service
`themisiq-app.service`, as recorded in the updated project instructions.
Keep the app in that deployment mode and add only the converter container.
Windows is the development environment. Verify live service paths, permissions
and resource capacity in T00 before preparing deployment commands.

Navigation: [decisions](#1-product-decisions-already-selected),
[data model](#4-data-model-and-migration-contract),
[authorization](#5-authorization-contract),
[state machines](#6-state-machines-and-version-behavior),
[API](#8-api-contract), [tasks](#12-ordered-implementation-tasks),
[tests](#13-test-organization-and-commands),
[execution ledger](#16-execution-ledger-for-the-implementing-model).

## 0. How to execute this plan

The objective is a complete in-app journey: generate, edit, brand, preview,
confirm, submit, and approve. The original plan's same-row AI draft design is
superseded by this document.

Read sections 1-11 before implementing. Execute the tasks in section 12 in
order. Each task names its dependencies, files, required behavior, and pass
condition. Do not skip a failed gate or mark a task complete because its code
has been written.

Working rules:

1. Recheck `git status --short` and the named function anchors before editing.
   Line numbers from older reviews are navigation hints, not authoritative.
2. Preserve unrelated work. Do not reset the checkout, rewrite existing
   policies, run migrations against production, or install system software as
   an incidental test step.
3. Implement the selected design below. Do not substitute an `AI Draft` row
   in `aria_documents`, direct status edits, a download-only preview, or an
   approval that refers only to a mutable document.
4. Keep routes thin. Business rules belong in the new services named below.
   Pure DOCX construction belongs in `branding_engine.py`.
5. Write regression tests for the invariants before completing each task.
   Mock the AI provider for automated tests. A mocked converter does not
   satisfy the real preview acceptance test.
6. Use the existing synchronous DB adapters and parameterized `%s` SQL.
   Use `insert_returning_id` for generated integer IDs and `utcnow()` for UTC.
7. A failed database transaction must roll back completely. Do not catch an
   SQL error and continue: `_PgConnWrapper.execute` already rolls back the
   connection after an error.
8. Update the execution ledger in section 16 with commands, results, and
   unresolved limits. Never record a skipped PostgreSQL/browser check as passed.
9. Keep feature code behind `ARIA_POLICY_AUTHORING_ENABLED=false` until all
   release gates pass. Disabling the feature must not restore insecure legacy
   approval or mutation routes.
10. Task file paths beginning with `modules/`, `core/`, or `static/` are
    relative to `oneforall/`. Other paths state their repository-relative location.
11. This document does not request deployment, a push, or creation of live
    administrator accounts. Follow the user's authorization for those actions.
    If commits are authorized, use one focused commit per completed task group.

## 1. Product decisions, already selected

| Topic | Required decision |
|---|---|
| Editing | Markdown textarea, saved draft, sanitized reading preview. Keep the existing ARIA visual style. |
| Temporary draft | New `aria_policy_drafts` table, separate from the document library. |
| Committed content | New `aria_policy_versions` table. Each confirmation creates an immutable content/artifact snapshot. |
| Existing document | `aria_documents` remains the document identity and the projection used by existing consumers. |
| Existing approved policy | Remains current and downloadable while a replacement version is drafted or reviewed. |
| Branding | Generate source DOCX on the server, apply an authorized template, then convert that exact branded DOCX to PDF. |
| Dependency management | Separate VPS converter container with tested LibreOffice/fonts, immutable image digest, health checks, and controlled updates. |
| In-app preview | Serve the resulting PDF through an authenticated endpoint; render it with locally hosted PDF.js. |
| Preview outage | Saving/editing remains available. New builds report a recoverable error. An existing ready build can still be viewed/confirmed if all freshness and integrity checks pass. |
| Approval | One named approver per submission, checked against current account, capability, organization, BU, and authorship. |
| Approval override | None in this release, including for super administrators. Withdrawal and resubmission recover incorrect assignments. |
| Revision after rejection | Clone the rejected snapshot into a new editable draft. Never edit the rejected snapshot. |
| Versions | New policy starts at `1.0`. Subsequent reserved versions increment the minor component. Gaps are allowed; reuse is forbidden. |
| Publication | Approval promotes the exact snapshot. Evidence Vault, GRID, and search consume the approved version through a retryable publication job. |
| Integration | Preserve single-framework and IMS generation, existing exports, historical records, and existing document deep links. |
| Deferred | Legal e-signatures, WYSIWYG editing, collaborative editing, multi-stage approval, and automated future effective-date activation. |

Local PDF conversion is an additional deployment dependency. It is selected
because a DOCX download is not an in-app preview. The preview is a rendering
of the exact branded DOCX, not a screenshot of the markdown editor. Display
"Preview rendered from the branded Word document; Word pagination may vary."
Approval records identify both the DOCX and the rendered PDF.

Terms used throughout this plan:

- **Draft:** editable workspace with no library record for a new policy.
- **Build:** a source DOCX, branded DOCX, and preview PDF created from one
  saved draft revision and one immutable template snapshot.
- **Confirmed version:** retained content and files that can no longer be edited.
- **Current version:** the version `aria_documents` exposes. Once a version
  has been approved, it stays current until another version is approved.
- **Candidate:** a confirmed replacement version awaiting submission or decision.
- **Publication:** the approval transaction promotes the version; integrations
  then synchronize from that version, not from whatever is current later.

## 2. Verified source map and pitfalls

Paths below are relative to `C:/Projects/One For All/One For All`.

| Existing file / symbol | What was verified; implementation implication |
|---|---|
| `oneforall/modules/aria/routes.py:api_generate_policy` | Updates a matching document by control/framework, even when it is already approved. Replace that persistence block entirely. |
| `routes.py:export_word` | Contains the reusable markdown-to-DOCX parser. Extract and characterize it before changing its behavior. |
| `routes.py:apply_template_to_document` | Requires a real uploaded file. Repeated calls create new branded filenames. Reuse the branding engine, not the unsafe record mutation. |
| `routes.py:upload_document_revision` | Mutates the live file/version/status and archives an earlier file in `aria_doc_revisions`. This must not replace a managed approved version. |
| `routes.py:update_document` | Accepts status/version/owner/approver fields. Ownership uses display names. Close this bypass before enabling the feature. |
| `routes.py:documents_page` | List and totals read `aria_documents` without BU filtering. |
| `routes.py:api_templates_list` | Returns template rows; templates currently have no active flag or BU scope. Add explicit scope and soft retirement. |
| `oneforall/modules/aria/branding_engine.py:apply_template` | Skips source preamble heuristically. Arbitrary first headings can cause content to be lost. Add an explicit mode for generated source bodies. |
| `oneforall/modules/aria/templates/ai_generator.html` | Direct `marked.parse(...)` to `innerHTML` for policy and gap output; no sanitizer on those paths. |
| `oneforall/database.py` | ARIA file/branding/BU fields are mostly column migrations. `aria_doc_revisions` is a historical upload archive, not an approval snapshot model. |
| `database.py:_apply_tenant_schema_ddl` | PostgreSQL tenant provisioning and upgrade share canonical DDL. Both must receive all new tables, columns, indexes, and backfills. |
| `database.py:_PgConnWrapper.execute` | Rolls back the whole transaction on SQL error. Do not depend on savepoint recovery through this wrapper. |
| `oneforall/modules/governance/data_service.py:bu_scope_ids` | `None` is super-admin unrestricted; `[-1]` means no BU; other lists are own BU plus active descendants. Existing queries also allow explicitly organization-wide NULL-BU rows. |
| `oneforall/core/middleware.py` | Sets organization context; shared users still need explicit org filtering. Origin protection already exists for mutations. Audit helper uses its own connection. |
| `oneforall/core/middleware.py:security_headers_middleware` | Frames are denied and `object-src 'none'` is set. Do not weaken those protections to embed a PDF plugin. |
| `oneforall/core/events.py:emit` | Commits separately and runs handlers after saving an event. Do not call it inside the approval transaction. |
| `oneforall/core/event_handlers.py` and `modules/grid/data_service.py` | Existing publication integrations load the mutable document and may copy/attach evidence. Managed versions need a version-specific path. |
| `oneforall/modules/aria/ask_service.py` | Maintains a separate content index. Authorization must be enforced before indexed policy text becomes AI context. |
| `oneforall/tests/conftest.py` | Tests force `DATABASE_URL=""` and use temporary SQLite. Ordinary pytest cannot prove PostgreSQL behavior. |

Do not copy `grid_approvals` as a complete security implementation. The
assigned-user and pending-state checks in
`oneforall/modules/launcher/routes_workflows.py` are useful reference behavior,
but ARIA still needs the explicit version and scope rules in this plan.

## 3. Invariants: requirements that every layer must preserve

Use these identifiers in tests and review notes.

| ID | Invariant |
|---|---|
| I01 | Generating, editing, or building a draft never changes an existing document body, file, status, version, coverage, or published evidence. |
| I02 | A new policy in the authoring flow has no `aria_documents` row until confirmation. Legacy metadata-only entry remains distinct. Reserved document numbers can have gaps. |
| I03 | Every content/branding change invalidates the previous build. Confirmation accepts only the current saved revision and its successful build. |
| I04 | Confirmed version bodies, metadata, author lists, source files, branded files, template snapshots, and PDF previews never change. Only lifecycle fields change. |
| I05 | Approval identifies a specific version and its hashes. It cannot approve a later edit or silently rebuilt file. |
| I06 | Every request uses the authenticated organization and current BU scope. Client IDs, URLs, ownership, and approver names confer no access. |
| I07 | Ownership is a user ID. Names are display/audit snapshots, never authorization keys. |
| I08 | Only the assigned, currently eligible approver decides. Owners, requesters, and content contributors cannot approve their own work. |
| I09 | At most one pending approval and one open candidate per document. At most one editable revision draft per existing document. |
| I10 | Repeated confirmation/submission cannot create duplicate records, notifications, or version numbers. Competing decisions have one winner. |
| I11 | Once approved, the current version stays available throughout revision, rejection, withdrawal, and publication-sync failures. |
| I12 | Drafts and unapproved candidate bodies never become Ask ARIA context, GRID approved evidence, or Evidence Vault published policy content. |
| I13 | Files are private, addressed through authorized records, and kept inside configured storage roots. A cleanup job never deletes a referenced version or historical evidence file. |
| I14 | Database changes, lifecycle audit rows, and in-app notifications succeed or roll back together. External side effects happen after commit. |
| I15 | A person moving from EcoCash to Omni retains historical authorship/approval attribution. Their future access is recalculated; policies stay in their original BU. |
| I16 | SQLite and PostgreSQL fresh installs and upgrades implement the same application rules. Missing tenant tables cannot silently fall back to public data. |

## 4. Data model and migration contract

### 4.1 General schema rules

- All new business tables below are tenant module tables in `_ARIA_TABLES`.
  All include `org_id INTEGER NOT NULL REFERENCES organizations(id)` and
  `business_unit_id INTEGER NULL REFERENCES business_units(id)`, except the
  singleton number allocator.
- Always require matching `org_id` in queries, including on SQLite.
  Do not accept `org_id` in a client payload.
- Use integer surrogate PKs for versions, approvals, and publication jobs.
  Draft IDs and build IDs are server-generated UUID strings.
- User FKs use `ON DELETE SET NULL` with immutable identity display snapshots.
  At creation/submission the service requires valid non-null users. A later
  deleted account cannot decide or regain access through its saved name.
  This preserves the existing account-deletion model without cascading away
  policy history.
- Document/version/draft references use `RESTRICT` for retained records.
  Managed policy deletion becomes soft archival. Never cascade away approval history.
- Status values use both DB `CHECK` constraints on new tables and service
  validation. A status dropdown is not an enum or an authorization boundary.
- Time fields are UTC `TEXT` populated by the application with one consistent
  `utcnow().isoformat()` format. Normalize old timestamps before comparison.
- JSON fields are serialized deterministic JSON in `TEXT`, not Python repr.
  Services validate their shape; do not require engine-specific JSON SQL.
- Add indexes after their referenced columns exist. Existing tables receive
  indexes in a post-column-migration step, not prematurely in base DDL.

### 4.2 Changes to existing tables

`aria_documents`:

| Field | Definition / behavior |
|---|---|
| `org_id` | Nullable legacy migration FK to organizations; required by the service for all new/adopted records. |
| `owner_user_id` | Nullable FK to users, `ON DELETE SET NULL`. Existing `owner` remains display text only. |
| `current_policy_version_id` | Nullable FK to `aria_policy_versions`, `ON DELETE RESTRICT`. Add after new tables exist to avoid circular DDL ordering. |
| `policy_workflow_managed` | INTEGER NOT NULL DEFAULT 0, only 0/1. Set to 1 at creation/adoption. Cannot be unset through a route. |
| `archived_at` | Nullable UTC text. Hide archived policies by default; retain their files/history. |
| `lock_version` | INTEGER NOT NULL DEFAULT 1 for conditional mutation and metadata conflict detection. |

Keep existing `body`, `version`, `status`, `file_path`, `branded_file_path`,
`template_id` and reviewer fields. They are a projection of the current
version for managed records, never an independent editable copy.
`file_path` references the current source; `branded_file_path` references the
current branded artifact. Downloads prefer the branded artifact.

`aria_doc_templates`:

- Add `org_id`, `business_unit_id`, `is_active INTEGER NOT NULL DEFAULT 1`,
  `file_sha256`, and `updated_at`.
- Existing fields and upload size limit remain supported.
- All mutations get an ownership/capability and organization/BU check.
- Retire templates instead of deleting referenced files. A draft build stores
  a private copy and hash, so later template changes cannot change a version.
- A source template changing or being retired before confirmation invalidates
  that draft build; ask the user to select/rebuild. After confirmation, the
  retained snapshot remains valid even if the template is retired.

`aria_doc_revisions` remains the legacy upload archive. Do not reinterpret
old rows as approvals or rewrite its historical files. Managed history APIs
combine it with `aria_policy_versions` and label their provenance.

### 4.3 New table: `aria_policy_drafts`

Required fields, with NULL only where stated:

| Field(s) | Type / purpose |
|---|---|
| `id` | TEXT PRIMARY KEY, server UUID |
| `org_id`, `business_unit_id` | Scope as above |
| `owner_user_id`, `created_by`, `last_edited_by` | User FKs; required at creation; preserved display snapshots in `identity_json` |
| `source_document_id` | Nullable FK to `aria_documents.id`; NULL means a new policy |
| `base_version_id` | Nullable FK to versions; current document snapshot this revision was based on |
| `copied_from_version_id` | Nullable FK to versions; records a rejected/withdrawn snapshot used to seed the editor |
| `reserved_doc_id` | TEXT, e.g. DOC-0042; new policies reserve a number without creating a document |
| `version_major`, `version_minor` | INTEGER, nonnegative; proposed version already fixed before preview |
| `content_kind` | TEXT CHECK: markdown or uploaded_docx |
| `body` | TEXT, editable normalized markdown; empty for file-based drafts |
| `uploaded_source_path`, `uploaded_source_sha256` | Nullable private source reference/hash for file-based drafts |
| `metadata_json` | TEXT, exact schema in section 4.7 |
| `author_user_ids_json` | TEXT array of contributing user IDs; start with creator, append distinct content editors |
| `state` | TEXT: editing, ready, committed, discarded, expired |
| `lock_version` | INTEGER NOT NULL DEFAULT 1; optimistic concurrency token |
| `body_sha256`, `input_sha256` | TEXT; content and canonical build-input hashes |
| `template_id` | Nullable FK until selected |
| `build_id`, `build_input_sha256`, `template_sha256` | Nullable until successful build |
| `source_path`, `branded_path`, `preview_path`, `template_snapshot_path` | Nullable, relative storage paths for one successful build |
| `source_sha256`, `branded_sha256`, `preview_sha256` | Nullable until successful build |
| `renderer_manifest_json`, `renderer_manifest_sha256` | Nullable until build; converter, font and image provenance |
| `generation_request_id` | Nullable client UUID for recovering/retrying successful AI generation |
| `created_at`, `updated_at`, `expires_at` | UTC text |
| `committed_version_id` | Nullable FK, set exactly once on confirm |
| `discarded_at` | Nullable UTC text |

Constraints/indexes:

- Unique `(org_id, created_by, generation_request_id)` when request ID exists.
- One open revision draft per `(org_id, source_document_id)` where source is
  non-null and state is `editing` or `ready`.
- Index `(org_id, owner_user_id, state, updated_at)` and `(state, expires_at)`.
- A `ready` draft must have all successful-build fields.
- A `committed` draft must have a `committed_version_id`.
- Editing increments the token, sets `state=editing`, and clears successful
  build fields. Old paths become cleanup candidates, not immediate deletions.

A markdown confirmation requires a nonblank body. A file-based confirmation
instead requires its validated uploaded source and complete artifact set.

The author list survives copying a rejected version. Renaming the owner or
cloning content must not allow an original author to approve their own text.

### 4.4 New table: `aria_policy_versions`

| Field(s) | Type / purpose |
|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT, via existing PG conversion |
| `org_id`, `business_unit_id` | Scope snapshot |
| `document_id` | Required document FK |
| `draft_id` | Nullable unique draft FK; NULL only for a legacy baseline |
| `base_version_id` | Nullable version FK |
| `version_major`, `version_minor`, `version` | Integers plus canonical display text `N.M` |
| `state` | TEXT: draft, pending, approved, rejected, withdrawn, legacy |
| `origin` | TEXT: authored, uploaded, legacy |
| `body`, `metadata_json`, `identity_json`, `author_user_ids_json` | Immutable content and attribution snapshots |
| `input_sha256`, `source_sha256`, `branded_sha256`, `preview_sha256`, `template_sha256` | Immutable hashes; nullable only for incomplete legacy baselines |
| `build_id`, `source_path`, `branded_path`, `preview_path`, `template_snapshot_path` | Immutable relative references; nullable only for legacy baselines |
| `template_id` | Nullable FK plus template description in metadata snapshot |
| `renderer_manifest_json`, `renderer_manifest_sha256` | Immutable converter/font/image provenance; nullable only on legacy baselines |
| `created_by`, `created_at` | Confirmation actor and time, with identity snapshot |
| `approved_by`, `approved_at` | Nullable decision attribution; only approval service sets these |
| `lock_version` | INTEGER NOT NULL DEFAULT 1; lifecycle token |

Constraints/indexes:

- Unique `(document_id, version)` and unique non-null `draft_id`.
- One open candidate per document where state is `draft` or `pending`.
- Index `(org_id, document_id, created_at)`.
- New authored/uploaded versions must contain the required artifact hashes.
- Content is immutable at the service/API layer. There is no version-body
  update endpoint. Lifecycle updates use an explicit allowed-column list.

A withdrawal closes its approval round and leaves the immutable version in
state `withdrawn`. Resubmitting it uses a new
approval round and returns it to `pending` only if no newer draft/candidate
exists and the base current version still matches. Editing always clones it.

### 4.5 New table: `aria_document_approvals`

Fields:

- Integer `id` PK; `org_id`; `business_unit_id`.
- Required `document_id` and `policy_version_id` FKs.
- `round_number INTEGER NOT NULL`.
- `approver_id` and `requested_by` user FKs, valid and non-null on submission.
- `approver_identity_json` and `requester_identity_json` snapshots.
- `status` CHECK: pending, approved, rejected, withdrawn.
- `submitted_version TEXT`, `submitted_input_sha256 TEXT`,
  `submitted_branded_sha256 TEXT`, `submitted_preview_sha256 TEXT`.
- `request_note TEXT`, `requested_at TEXT`.
- Nullable `decision_by` user FK, `decision_identity_json`, `decided_at`.
- `comments TEXT` default empty; required nonblank on reject/withdraw.
- `request_id TEXT NOT NULL` for submission idempotency.
- `lock_version INTEGER NOT NULL DEFAULT 1`.

Constraints:

- Unique `(org_id, requested_by, request_id)`.
- Unique `(policy_version_id, round_number)`.
- Unique partial index on `document_id` where `status='pending'`.
- Index `(org_id, approver_id, status)`.
- Index `(document_id, requested_at)`.

Approved/rejected/withdrawn rows are historical. Resubmission creates a new
row. Never reset or delete the previous decision to make a retry work.

### 4.6 Supporting tables

`aria_document_number_sequence`:

- `id INTEGER PRIMARY KEY CHECK(id=1)`, `next_value INTEGER NOT NULL`.
- One singleton per tenant schema; one global singleton in SQLite because
  SQLite's existing `doc_id` uniqueness is global.
- Initialize after legacy data inspection to one greater than the highest
  numeric `DOC-<digits>` suffix. Ignore nonnumeric legacy identifiers.
- Reserve under a write transaction/row lock. Return `DOC-{number:04d}`;
  formatting expands naturally beyond 9999. Never use `MAX()+1` in a route.
- Migrate every existing document-creation path to this allocator before
  enabling drafts. It is infrastructure, so it has no BU field.

`aria_policy_publication_jobs`:

- Integer `id` PK; `org_id`; `business_unit_id`.
- Unique `policy_version_id` FK, plus `document_id`.
- `publication_key TEXT UNIQUE`: organization ID and immutable version ID.
- `state` CHECK: pending, running, complete, failed.
- `attempts INTEGER DEFAULT 0`, `next_attempt_at`, nullable `lease_until`,
  `lease_token`, `last_error`.
- Nullable `event_id`; `created_at`, `updated_at`.
- Index `(state, next_attempt_at)`.
- Created in the approval transaction; stores no document body in logs/errors.

### 4.7 Exact metadata shape

Use the following keys for draft metadata, then freeze the same object into
the version. Reject unknown keys in API requests; derive IDs and scope on the
server rather than accepting this whole object from the browser.

```json
{
  "title": "Access Control Policy",
  "doc_type": "Policy",
  "org_name": "Example Group",
  "control_id": 123,
  "control_ref": "A.5.15",
  "primary_framework_id": 7,
  "framework_ids": [7, 9],
  "framework_label": "ISO 27001, SOC 2 Type II",
  "integrated_controls": [
    {"framework_id": 9, "control_id": 456, "ref": "CC6.1"}
  ],
  "effective_date": null,
  "review_date": null
}
```

Preserve IDs separately from the display label. Never identify a policy by a
comma-joined framework string. The source document ID is explicit when revising.
Effective date is descriptive in this release; approval activates immediately.
Do not offer scheduled activation without implementing it.

### 4.8 Migration and adoption, in order

1. Add new tables and additive columns. Keep cross-reference columns such as
   draft-to-version and document-to-version in a late migration if needed.
   PostgreSQL requires referenced tables to exist first. Do not blindly move
   all branding columns into base CREATE TABLE before fixing table ordering.
2. Apply indexes and singleton initialization after columns are present.
3. Run the same post-migration function for public, new tenant schemas, and
   existing tenant schemas. Run it twice in tests to prove idempotence.
4. Produce a dry-run ownership/scope report before backfilling real records.
   For PostgreSQL, the owning schema identifies the organization only after
   validating its mapping to `organizations.slug`. In SQLite, use an explicit
   verified mapping if more than one organization exists.
5. Resolve legacy owners only through a unique exact username/full-name match
   inside that organization. Ambiguous/unmatched owners remain unresolved;
   a scoped manager must explicitly select an owner before adoption.
6. Keep legacy NULL BU records organization-wide only where their organization
   provenance is resolved and that is their existing declared scope. Never
   infer a historical policy's BU from the owner's current BU.
7. Unresolved-org records are hidden from ordinary endpoints and listed by a
   restricted repair report. Never treat NULL org as "visible to everyone".
8. Before enabling authoring for a tenant, verify all required relations exist
   in the intended schema, not only somewhere in `search_path`. A failed
   tenant migration disables the feature for that tenant with diagnostics.
9. On the first revision/submission of a legacy document, adopt it under a
   document lock: create a baseline with `origin=legacy`, retain its actual
   status/files/metadata, link `current_policy_version_id`, and set managed=1.
   If the policy was already Approved, set the baseline state to `approved`
   and label its provenance as imported; leave unavailable approver/time fields
   NULL. Otherwise use state `legacy` and preserve its old status in a server-only
   `imported_status` metadata snapshot field (the one legacy-only extension
   to the authored metadata schema). Do not invent an approval decision.
10. If old version text is not valid `N.M`, require a reviewed mapping before
    reserving the next version. Do not silently reset it to `1.0`.
11. Imported file-only documents without reliable markdown do not get a
    fabricated editable body. Offer the validated upload-candidate path.
12. Keep historical `AI Draft` library rows classified as legacy. Do not
    automatically delete, hide, or convert them based only on that label.

## 5. Authorization contract

Implement one shared `policy_access.py`; routes, services, search, downloads,
and integration adapters use it. Do not rely solely on route decorators.

### 5.1 Organization and BU rules

Resolve the actor from the authenticated session, reload current activity,
organization, roles and BU at mutations, and require active, non-deleted
accounts. Assert that the request organization matches the database context.

For reads:

- A record must belong to the active organization.
- A real super administrator may read all BUs in that active organization.
  This does not authorize selecting a user from another organization.
- Otherwise, a record's BU must be in `bu_scope_ids(actor)`, or the record must
  be explicitly organization-wide (`business_unit_id IS NULL`).
- A user with no assigned BU has `[-1]` and sees only organization-wide rows,
  never all subsidiary rows.
- Inaccessible object IDs return 404. Visible objects with an unauthorized
  action return 403. Lists omit inaccessible entries and counts.

For creation:

- Default to the actor's own active BU.
- A requested BU must be in the actor's authorized subtree; super admins
  may choose an active BU in the current organization.
- Explicit organization-wide creation requires `aria.policy.edit_any` and
  an intentional "Organization-wide" selection. Never turn a missing BU into
  broad scope accidentally.
- Scope is frozen on confirmation. Moving an existing policy to another BU
  is outside this release; do not offer a scope-change field on revision
  forms. A user's SBU transfer does not move content.
- SQLite does not have per-schema BU isolation, and the current BU table
  does not establish multi-organization ownership. For this release, enable
  authoring only in a SQLite database with one explicitly configured active
  organization. Multiple active organizations make tenant readiness fail.
  Use PostgreSQL tenant schemas for multi-organization authoring. Continue
  explicit org predicates on every SQLite record query and fail closed where
  legacy BU provenance is unresolved. Never guess from colliding numeric IDs.

### 5.2 Action matrix

All rows below also require ARIA module access and the organization/BU check.

| Action | Additional requirement |
|---|---|
| Generate | `aria.policy.generate_ai` and `aria.policy.create`; preserve rate limit |
| Read/edit own draft | `aria.policy.edit_own` and `owner_user_id == actor.id` |
| Read/edit another draft | `aria.policy.edit_any` |
| Create revision / confirm / submit | Own-document `edit_own` or `edit_any`, plus valid draft/version state |
| Read new unapproved policy body/files | Owner, contributor still in scope, `edit_any`, or assigned pending approver |
| Read approved policy | Normal ARIA document read access within scope |
| Read approval candidate | Assigned approver, author/owner, or `edit_any`, all still in scope |
| Decide | `aria.policy.approve`, assigned user, eligible current account, and separation of duties |
| Withdraw pending submission | Requester or `edit_any`, in scope, with reason |
| Archive managed document | `aria.policy.delete`, in scope, no pending approval/open draft/candidate |
| Change a template | Existing template capability plus its organization/BU rules |

Approver eligibility:

1. Query `users.org_id = active_org_id`, `is_active=1`, `deleted_at IS NULL`.
2. Load `user_roles` and evaluate `has_capability(..., "aria.policy.approve")`.
   Do not hardcode display role names or query every platform user.
3. Evaluate the candidate approver's ability to read this document's scope.
   A group BU ancestor can approve a subsidiary document; an unrelated
   sibling BU cannot.
4. Exclude the document owner, draft creator, all content contributor IDs,
   and the submission requester. Apply this rule to super admins too.
5. Re-evaluate at submission and decision. Role removal, deactivation,
   account deletion, and an EcoCash-to-Omni transfer can remove eligibility.
6. If no eligible approver exists, show an actionable message and leave the
   version in Draft. Never auto-approve or select the requester.

Read audit/history with the same scope rules. Include original identity
snapshots when a user is renamed or deleted; never reuse them for access checks.

## 6. State machines and version behavior

### 6.1 Editable draft

| From | Operation | To | Guard |
|---|---|---|---|
| absent | Generate / start revision | editing | Scope/capabilities; revision slot available |
| editing / ready | Save body or metadata | editing | Expected lock token; invalidate all build fields |
| editing / ready | Successful build | ready | Saved input unchanged; authorized active template; conversion succeeds |
| ready | Confirm | committed | Matching build ID/token/hashes; no stale base version |
| editing / ready | Discard | discarded | Edit permission |
| editing / ready | Inactivity expiry | expired | Retention condition; no confirmation/build attachment race |
| committed | Retry confirm | committed | Return the same version ID after authorization |
| discarded / expired | Recovery | new editing draft | New draft ID; keep original record as history |

A build in progress does not lock the editor for a minute. It works from a
snapshot outside the database transaction. If the user saves meanwhile, the
build fails its final conditional attach and becomes an unreferenced artifact.

### 6.2 Confirmed version and approval

| Version state | Operation | Version result | Approval result |
|---|---|---|---|
| draft | Submit | pending | New pending row |
| pending | Approve | approved | Same row becomes approved |
| pending | Reject with comment | rejected | Same row becomes rejected |
| pending | Withdraw with reason | withdrawn | Same row becomes withdrawn |
| withdrawn | Resubmit unchanged | pending | New round, only if still current candidate and base matches |
| rejected / withdrawn / approved | Edit | New editable draft | Old approval rows unchanged |

A rejected version cannot be resubmitted unchanged. The author must create a
new draft, make/review the correction, rebuild, and confirm a new version.

### 6.3 Document projection rules

For a new policy:

1. Generate/build: no document row.
2. Confirm: create document and version `1.0`; current pointer = version;
   document status = Draft.
3. Submit: document status = Under Review.
4. Approve: document status = Approved.
5. Reject/withdraw before first approval: document status = Draft; show the
   decision beside the retained snapshot. Editing still requires a new draft.

For an already approved policy:

1. Start a revision with explicit source document ID and current version ID.
2. Reserve the next unused minor number under a document lock. Include all
   previously reserved draft and confirmed numbers; abandoned numbers are not reused.
3. Confirm a candidate without changing the current pointer, body, version,
   files, approval fields, or Approved status.
4. Show "Current: 1.0 Approved" and "Candidate: 1.1 Under Review" separately.
5. Rejection/withdrawal leaves 1.0 current.
6. Approval atomically makes 1.1 current and updates the document projection.
   The old 1.0 snapshot and its approval remain readable as history.

Only one open draft/candidate is allowed for an existing document. Starting
another returns `OPEN_REVISION_EXISTS` with a link only if the actor may read it.
Before confirming/submitting/approving, verify that the saved base pointer
still equals the actual current pointer. A stale candidate is never promoted.

## 7. Storage, building, preview, and recovery

### 7.1 Pure DOCX builder and branding

Extract `build_policy_docx(content, org_name="", doc_heading="",
control_label="", include_preamble=True)` into `branding_engine.py`.

- Preserve export behavior through `include_preamble=True`.
- The authoring path uses `include_preamble=False`: the branding template
  supplies the cover and document metadata.
- Extend `apply_template` with an explicit generated-body mode that copies
  all supplied policy body paragraphs/tables. Keep the existing heuristic
  mode for legacy uploaded documents.
- Do not silently drop an arbitrary first heading, paragraph, table, or
  unnumbered policy section.
- Preserve heading levels, bullet/number lists, table cells and bold/italic.
- Test semantic structure, not identical DOCX ZIP bytes. ZIP timestamps and
  package metadata can legitimately differ.

### 7.2 Input limits and safe content

Set constants once in the service; use them in API validation and UI hints:

| Input | Limit |
|---|---|
| Markdown | 50,000 Unicode characters; reject over-limit input with 413 |
| Title / organization display name | 200 characters each |
| Custom AI instructions / approval comments / reasons | 2,000 characters |
| New JSON mutation body | 256 KiB before parsing |
| DOCX template/upload | Existing `ARIA_MAX_FILE` limit, plus ZIP checks below |
| Uncompressed DOCX ZIP | 100 MiB total, 2,000 entries, bounded expansion ratio |
| Converter wall time | 60 seconds |
| Preview PDF | 50 MiB, maximum 200 pages |

Normalize Unicode and line endings and remove XML-invalid control characters.
Preserve markdown syntax. Reject an empty markdown body for confirmation;
file-based drafts instead require a validated source file.
Do not use a truncating sanitizer and then claim the complete policy was saved.
Enforce the size limit before any middleware/helper could truncate it.

For markdown reading preview, use one renderer:
`DOMPurify.sanitize(marked.parse(text), explicitAllowlist)`.
Allow only headings, paragraphs, lists, emphasis, code, blockquotes, and
tables needed by the editor. Render links as plain text in this release;
disable raw HTML, images, SVG, MathML, styles, forms, and event attributes.
If either library fails to load, render with `textContent` and disable the
HTML preview. Never fall back to unsanitized `innerHTML`.
Use the same renderer for policy, gap, reopened draft and print preview.

Validate DOCX before parsing/conversion: extension, ZIP signature, expected
OOXML members, entry paths and expanded size. Reject encrypted archives,
macros, embedded executables/OLE, external relationships, linked images and
remote template references. Parse XML without DTD/entity resolution.
Existing templates that fail this check are blocked with a clear remediation
message, not silently trusted because they were previously uploaded.

### 7.3 Artifact layout and build algorithm

Use a private subtree below `ARIA_UPLOAD_DIR`:

```text
policy_workflow/
  org_<server_org_id>/
    staging/<build_uuid>/
    artifacts/<build_uuid>/
      source.docx
      branded.docx
      preview.pdf
      template.docx
    trash/<cleanup_uuid>/
```

Store paths relative to `ARIA_UPLOAD_DIR`. Never expose paths to the browser.
Use generated filenames; user titles are only sanitized download names.
Resolve and verify containment with `Path.relative_to` / `is_relative_to`,
not string `startswith`. Reject absolute paths, traversal, UNC paths,
symlinks/reparse points escaping the root, and files outside the authorized
record's organization directory. Do not mount this tree as static content. Cleanup reference checks include
`uploaded_source_path` as well as the successful-build paths.

Build sequence:

1. Read/authorize the draft and expected token; compute a canonical input
   fingerprint from body, metadata, reserved doc ID/version, scope, template
   bytes hash, builder format version, and renderer/font manifest hash.
2. If a ready draft already has this fingerprint and all files/hash checks
   succeed, return its existing build. This makes retries inexpensive.
3. Copy the selected authorized template to a new server UUID staging
   directory. Capture its original DB identity and hash.
4. Generate source DOCX and apply branding with the reserved document ID and
   version that will be committed. Do not brand with a temporary ID and
   rebuild after the user's confirmation.
5. Validate both DOCX outputs, then convert the branded file to PDF.
6. Validate the PDF and calculate every stored SHA-256 hash. The restricted
   worker uses a pinned `pypdf` reader with strict parsing to check page count,
   encryption and parse errors within its resource/time limits. Reject invalid,
   encrypted, over-limit or active-content-bearing output rather than repairing
   it silently. The app verifies size/signature/hash again on receipt.
7. Atomically rename staging to artifacts on the same volume. Paths become
   immutable after successful attachment to a draft/version.
8. In a short write transaction, reauthorize and check draft state/token,
   input fingerprint, source base version, and template freshness.
   Attach the artifact set and advance the draft token/state to ready.
9. If attachment fails, leave the draft unchanged and remove/quarantine only
   that request's unreferenced build directory.
10. Previous builds are cleanup candidates after successful replacement.
    Never overwrite a committed path in place.

Crash recovery: before DB attach, an artifact is an orphan and can be swept
after the grace period. After DB attach, it is retained by its references.
A crash after DB commit but before HTTP response is handled by retry/read.

### 7.4 Local conversion and PDF viewer

Implement `policy_preview.py` as the app-side spool client and
`oneforall/scripts/aria_policy_preview_worker.py` as a separate converter
container on the VPS, running as a non-root user. The container owns the tested
LibreOffice executable and fonts; the application only exchanges private spool
jobs. Validate the executable path inside the image. Prefer the same container
for local development. If a native Windows development fallback is needed, use
the console-capable executable, run hidden, and keep the same worker contract.

Invoke with an argument array and `shell=False`. Use the documented headless
conversion options, a unique `-env:UserInstallation=<file URI>` per build,
`--convert-to pdf:writer_pdf_Export`, and a controlled output directory.
Never let the request supply executable arguments, filters, or filesystem paths.

Worker protocol:

1. Configure a private local spool outside static/public directories. ACLs
   permit only the app account and conversion account to access it. The worker
   can access this spool and its program/profile directories, not the app's
   database, .env file, upload root or arbitrary tenant folders.
2. The app atomically writes `inbox/<job_uuid>/input.docx` and a small request
   manifest containing only job UUID and deadline. It copies the already
   validated branded bytes; no caller-supplied paths or converter arguments.
3. The worker validates UUID, manifest size, deadline and input again, claims
   the directory with an atomic rename, and converts in a unique work/profile
   directory. It runs one conversion at a time across processes using a lock.
4. It writes `output.pdf` then an atomic terminal `result.json` with `ok` or a
   bounded error code. The app polls asynchronously up to its deadline, reads
   the result, validates/hashes the PDF, and copies it to its staging build.
5. Expired/cancelled jobs kill the conversion process tree. Stale spool jobs
   are swept with the same path checks. There is no publicly reachable HTTP
   conversion endpoint and the browser never accesses the spool.
6. Document Linux VPS container deployment, shared-spool permissions, startup,
   readiness, upgrades and rollback. A systemd-hosted app may use the same
   container via a host bind-mounted spool. Windows-specific instructions are
   for development only. The web app must not auto-install services or elevate.

Operational requirements:

- Run conversion under a restricted account/process boundary with no access
  to application secrets or unrelated tenant data and no outbound network.
  A profile directory or headless flag alone is not a sandbox.
- Disable macros and automatic link updates in the conversion profile.
- Pass a minimal environment rather than the app's secret-bearing environment.
- Enforce a timeout and terminate the converter process tree, including
  `soffice.bin`, on timeout. Do not leave detached converters running.
- Start with one conversion at a time on the VPS using a cross-process
  file lock; a Python in-memory semaphore is insufficient with multiple workers.
  Use bounded lock acquisition and return 429 with Retry-After when busy.
- Do not hold a DB transaction or block an async event loop while converting.
  Use a bounded worker/thread offload; handle cancellation and clean up.
- Verify executable/version, required fonts, profile policy and a sample
  conversion during deployment readiness. Missing setup produces 503 for new
  builds; confirmation still requires a complete ready build. Previously built
  and still-valid artifacts remain viewable/confirmable. Never fall back to a
  public converter.

Use PDF.js's display layer in the ARIA page with canvas plus selectable text,
page controls, zoom, and an accessible text view. Fetch the authenticated
same-origin PDF; do not use a public viewer URL. Use a same-origin worker,
disable PDF scripting/unsafe evaluation and external navigation, and bound
rendering to visible pages. Keep `object-src 'none'` and frame denial. If
needed, add only `worker-src 'self'` to CSP.

Vendor pinned, reviewed versions of Marked, DOMPurify and PDF.js under
`oneforall/static/vendor/`. Record upstream version, checksum, license and
source in `oneforall/static/vendor/aria-policy/README.md`. Do not use an
unpinned runtime CDN URL. Check the chosen releases' security advisories at
implementation time; this plan does not assert an evergreen safe version.

Preview/download responses require session and object authorization, use the
correct media type, `Cache-Control: private, no-store` and `nosniff`.
PDFs may use inline disposition; DOCX remains an optional download.
A browser successfully loading the PDF is a UX confirmation, not proof that
a human read it. Do not represent it as a legally binding signature.

### 7.5 Cleanup policy

Defaults: 30 days of draft inactivity before expiry; 24 hours before removing
unreferenced staging/artifact directories; 7 days in restricted trash.

- A save refreshes draft expiry. Display the inactivity policy in My Drafts.
- Expiry changes the row to expired and removes its file references in a
  guarded transaction. Keep text/metadata for recovery; do not automatically
  hard-delete draft bodies in this release.
- Committed drafts, versions, approvals, pending submissions, legacy revision
  files and published evidence are never age-deleted by this job.
- Before moving a directory to trash, check references from drafts, versions,
  documents, legacy revisions and relevant evidence records.
- Run per organization with explicit tenant context and a lease. Avoid
  cleaning another worker's active staging directory.
- Enumerate only the workflow subtree, validate each resolved target, then
  use native path operations. Never recursively delete a workspace/upload root.
- Provide dry-run mode listing counts and IDs, without policy bodies/secrets.
- Cleanup failure is logged and retried; it does not block normal editing.

### 7.6 Managing LibreOffice as a VPS dependency

The application depends on a document-conversion contract. LibreOffice is the
first implementation, supplied inside a dedicated worker image. Browser users
install nothing. The host needs its existing container runtime; do not add an
office installation to the production web-app image or install packages at
application startup.

For the documented Hetzner deployment, `themisiq-app.service` uses the host
spool path and the converter mounts that directory at `/spool`. Preserve the
existing systemd app and PostgreSQL setup. Containerized-app instructions below
are compatibility notes, not a requirement to migrate the app into Docker.

Repository facts checked during this clarification:

- The root `Dockerfile` packages the Python app and does not install LibreOffice.
- `docker-compose.yml` defines PostgreSQL and an optional containerized app.
- `oneforall/scripts/deploy.py` also defines a Linux systemd-hosted app.
- The current Compose app mounts backup, GRID and Evidence directories, but
  does not mount the default ARIA upload/template directories. Add durable
  mounts for the effective `ARIA_UPLOAD_DIR` and `ARIA_TEMPLATE_DIR` before
  container-based authoring is enabled. Confirm actual paths/configuration;
  the repository definitions do not prove the live host's deployment mode.

Implement this deployment contract:

1. Add `deploy/aria-preview/Dockerfile`. Build from a supported Linux/Python
   base pinned by digest. Install LibreOffice Writer, required runtime libraries,
   and the approved font bundle at image build time. Copy only the worker,
   validation helpers and its pinned requirements. The worker must not import
   the application config/database modules or receive the app's `.env` file.
2. Produce `runtime-manifest.json` containing the base-image identity,
   installed LibreOffice/package versions, font versions, worker build ID and
   dependency versions. Record the final published image digest in release
   configuration. No placeholder version/checksum may pass readiness.
   If reproducible rebuilding is required, retain the package artifacts or use
   a controlled package snapshot; an unpinned apt repository is not a lockfile.
3. Add an `aria-preview` Compose service using an explicitly configured,
   tested image digest. Do not use `latest` or run package upgrades inside a
   running worker. Keep previous tested images available for rollback.
4. Run as a fixed non-root UID/GID with a read-only root filesystem, bounded
   writable temporary space, dropped capabilities, no-new-privileges and
   `network_mode: none`. Publish no ports. Never mount the Docker socket,
   database, application secrets, or the full document archive into the worker.
5. Share only a private spool, for example a host directory
   `/var/lib/themisiq/preview-spool` mounted at `/spool`. If the app is also a
   container, mount that same directory there and use `/spool` in its config.
   If the app uses systemd, use the host path in its config. Match ownership
   through a dedicated group and restrictive permissions; never chmod 777.
6. Keep final DOCX/PDF artifacts in the app's persistent ARIA storage. The
   spool is temporary exchange space, not the policy archive. Include retained
   policy versions/templates in backup and restore verification. Replacing the
   worker image must not touch final files or database versions.
7. Start with one worker and one active conversion. Configure CPU, memory,
   process-count and temporary-space limits against measured VPS capacity.
   Measure representative long policies, tables, logos and multilingual text
   before enabling; do not infer a safe memory allowance from page count alone.
8. Set a restart policy and maintain a worker heartbeat, queue-age metric and
   bounded error log. Readiness verifies the expected runtime manifest, spool
   permissions and a known DOCX-to-PDF conversion. Routine liveness checks use
   the heartbeat; do not repeatedly launch LibreOffice for every health probe.
9. Do not make overall app availability depend on converter health. During an
   outage the rest of ThemisIQ and draft saving remain available. New builds
   fail clearly; existing verified PDFs, approved documents and otherwise-valid
   ready-build confirmations remain accessible.
10. Standardize the fonts in policy templates and in the image. Test font
    substitution, tables, logos, headers/footers, page counts and Unicode.
    Do not assume a font installed on a developer's Windows laptop exists on
    the VPS. Use fonts approved for the deployment's distribution/use.
11. Before a LibreOffice or font update, build a new candidate image and run
    the same conversion/visual regression corpus in isolation. Validate current
    security advisories and the distribution's patch/backport status. Pinning
    provides controlled releases, not permission to leave vulnerabilities unpatched.
12. For release, stop accepting new build jobs briefly, let active work finish
    or expire safely, replace only the converter, run readiness/smoke conversion,
    and resume builds. The web app need not stop. Roll back to the previous
    tested image if validation fails, unless it is security-revoked; in that
    case keep new conversion disabled until a fixed image passes.
13. Retain approved DOCX/PDF bytes across updates. Do not regenerate historical
    previews in place. Record renderer provenance with every new build and
    version so a layout change can be traced to its runtime.
14. Keep the spool request/result contract independent of LibreOffice-specific
    arguments. A future converter can replace the worker without changing
    document ownership, version IDs, approval rules or recorded file hashes.

Worker config uses `ARIA_POLICY_PREVIEW_EXECUTABLE` inside its image. App
config uses only its spool path and timeout. A deployment-selected image
variable, such as `ARIA_POLICY_PREVIEW_IMAGE`, belongs to Compose/release
configuration, not a user-editable application setting.

## 8. API contract

Implement new endpoints in `oneforall/modules/aria/routes_policy_workflow.py`,
an APIRouter with the `/aria` prefix, registered once in `main.py`.
Existing `api_generate_policy` remains in `routes.py` and delegates draft
persistence to the service.

New mutation endpoints use strict JSON models. Existing generation/export
forms remain forms for compatibility. Unknown fields are rejected. IDs in
paths are not authorization. User identity, organization, hashes, files,
statuses and reserved versions are server-owned.

Common success envelope: `{"ok": true, ...}`.
Common error envelope:
`{"ok": false, "error": {"code": "STALE_DRAFT", "message": "...", "retryable": false}}`.
Do not expose SQL, absolute paths, converter output or secrets.

| Method and path | Request / result |
|---|---|
| GET `/aria/api/policy-drafts` | Scoped My Drafts, pagination; metadata only, no body in list |
| GET `/aria/api/policy-drafts/{draft_id}` | Authorized draft, metadata, state, lock_version, build_id and permitted actions |
| POST `/aria/api/generate-policy` | Keep form inputs; add optional request_id, target BU and explicit source_document_id; success also returns draft_id, state, lock_version, content, resume_url |
| POST `/aria/api/documents/{doc_id}/revision-drafts` | Optional copied_from_version_id; adopt legacy if valid; reserve next version; return new draft |
| PUT `/aria/api/policy-drafts/{draft_id}` | body, title, doc_type, allowed dates, expected_lock_version; save, invalidate build, return fresh token |
| POST `/aria/api/policy-drafts/{draft_id}/source` | Multipart DOCX and expected_lock_version; file-based draft only; replace private source and invalidate build |
| POST `/aria/api/policy-drafts/{draft_id}/build` | template_id, expected_lock_version; return build_id, fresh token and authenticated preview_url |
| GET `/aria/api/policy-drafts/{draft_id}/preview` | Requires matching build_id query parameter; current ready draft PDF only |
| POST `/aria/api/policy-drafts/{draft_id}/confirm` | build_id, expected_lock_version; return document_id, doc_id, version_id, version, detail_url |
| POST `/aria/api/policy-drafts/{draft_id}/discard` | expected_lock_version; mark discarded |
| POST `/aria/api/policy-drafts/{draft_id}/recover` | Expired/discarded source; create a fresh scoped draft with a new token |
| GET `/aria/api/documents/{doc_id}/policy-versions` | Scoped version metadata/history; no file paths or bodies by default |
| GET `/aria/api/policy-versions/{version_id}` | Authorized exact snapshot and permitted actions |
| GET `/aria/api/policy-versions/{version_id}/preview` | Exact retained PDF |
| GET `/aria/api/policy-versions/{version_id}/download` | Exact branded DOCX, never resolve through current document pointer |
| GET `/aria/api/policy-versions/{version_id}/approvers` | Eligible active same-org users; paginated minimal identity fields |
| POST `/aria/api/policy-versions/{version_id}/submit-approval` | approver_id, request_note, request_id UUID, expected_lock_version |
| GET `/aria/api/policy-approvals?assigned_to=me` | Scoped pending queue, paginated |
| POST `/aria/api/policy-approvals/{approval_id}/decide` | decision approve/reject, comments, expected_lock_version |
| POST `/aria/api/policy-approvals/{approval_id}/withdraw` | reason, expected_lock_version; requester/edit_any |
| GET `/aria/api/documents/{doc_id}/approval-history` | Scoped request/decision snapshots with times/comments |
| POST `/aria/api/policy-publications/{job_id}/retry` | Scoped edit_any; failed job only; reset next attempt without altering approved content |
| POST `/aria/api/documents/{doc_id}/upload-candidate` | Multipart validated DOCX plus notes and expected document token; create origin=uploaded draft/build using the same confirmation flow |

Uploaded candidates use a private source file and are labelled "File-based
draft". They have no fabricated markdown body. Their only edit operation is
replacement with another validated DOCX, which invalidates the build and adds
the uploader to the author list. Use the `uploaded_source_path`, `uploaded_source_sha256` and `content_kind`
fields specified in section 4.3. A markdown save on a file-based
draft returns 409. Unsupported legacy formats remain retained/downloadable;
they cannot be converted or approved by pretending they are DOCX.

JSON examples:

```json
{
  "body": "# Access Control\n\nAccess is reviewed quarterly.",
  "title": "Access Control Policy",
  "doc_type": "Policy",
  "expected_lock_version": 3
}
```

```json
{
  "ok": true,
  "draft_id": "server-generated-uuid",
  "state": "ready",
  "lock_version": 5,
  "build_id": "server-generated-build-uuid",
  "preview_url": "/aria/api/policy-drafts/server-generated-uuid/preview?build_id=server-generated-build-uuid"
}
```

Error mapping:

| HTTP | Code examples | Client behavior |
|---|---|---|
| 401 | Authentication required | Preserve unsaved editor text in memory; prompt sign-in |
| 403 | ACTION_FORBIDDEN, APPROVER_INELIGIBLE | Explain permission/assignment issue; do not retry automatically |
| 404 | NOT_FOUND | Do not disclose another org/BU record |
| 409 | STALE_DRAFT, STALE_BASE, BUILD_REQUIRED, OPEN_REVISION_EXISTS, ALREADY_DECIDED, LEGACY_REPAIR_REQUIRED | Reload authorized state or guide recovery; never overwrite automatically |
| 410 | DRAFT_EXPIRED | Offer recovery into a new draft if still authorized |
| 413 | CONTENT_TOO_LARGE, ARCHIVE_TOO_LARGE | Preserve input; explain limit |
| 422 | INVALID_INPUT, EMPTY_POLICY, INVALID_TEMPLATE, INVALID_DECISION | Show field-specific validation |
| 429 | AI_RATE_LIMITED, PREVIEW_BUSY | Retry-After; retain draft |
| 503 | PREVIEW_UNAVAILABLE, TENANT_SCHEMA_NOT_READY | Save/edit where safe; confirmation blocked |
| 504 | PREVIEW_TIMEOUT | Keep saved draft; allow a fresh build retry |

Generate must not return success if draft persistence fails. A successful AI
response followed by a DB failure gets an explicit "content generated but
not saved" error and the content can remain in the existing browser editor.
A repeated successful generation request_id returns the saved draft. A
concurrent duplicate provider call may occur, but the unique key prevents a
second saved draft. Never use the control/framework pair to overwrite content.

## 9. Transaction algorithms and idempotency

Create `policy_workflow_service.py` with one transaction owner per operation.
Internal helpers receive the caller's `db` and never commit/close it.

Lock order for existing records: document, draft/version, approval. Follow the
same order in confirmation, submission, decisions, withdrawal and archive.
SQLite: `BEGIN IMMEDIATE` before reading mutable state. PostgreSQL: row locks
with `SELECT ... FOR UPDATE`. File work occurs outside these transactions.

### 9.1 Confirm

1. Authorize draft, validate token/state/build and hash all attached files.
2. For an existing document, lock document before draft and recheck the base,
   absence of another candidate, scope and current actor eligibility.
3. For a new policy, lock the draft and create the document with its reserved
   doc_id. The unique draft-to-version relation prevents duplicate creation.
4. Insert the immutable version with body/metadata/artifact/author snapshots.
5. Set managed=1 and owner_user_id on the document. If there is no approved
   current version, set the current pointer/projection to the new Draft.
   Otherwise preserve the approved projection.
6. Mark draft committed, set committed_version_id and increment its token.
7. Insert lifecycle audit row using the same connection; commit once.
8. On retry of a committed draft, reauthorize and return the original result.
   Do not demand the old pre-confirm token just to return that result.

No files are regenerated or renamed at confirmation. What was previewed is
what is committed. No Vault/GRID publish action occurs here.

### 9.2 Submit

1. Check request_id for an existing submission by this actor/org. Same
   payload returns its existing result; different payload returns 409.
2. Lock document and version. Validate state, current base, no open competing
   revision and no pending approval.
3. Rehash retained artifacts and validate the immutable fingerprint.
4. Resolve approver eligibility using section 5, including current roles/BU.
5. Insert approval with next round number and all submitted hashes.
6. Set version pending; for the first unpublished document set Under Review.
   An existing Approved document stays Approved.
7. Insert notification and audit row on the same connection; commit once.
8. After a unique-conflict rollback, open a fresh transaction to retrieve the
   winning idempotent result. Do not continue on the rolled-back connection.

### 9.3 Decide

1. Load approval identity to determine the document, then lock document,
   version, approval in that order and reload their state.
2. Require pending state and expected token; verify assigned actor eligibility
   and separation of duties again.
3. Validate document/version linkage, base pointer, submitted version/hash
   snapshots and current file hashes. Hash mismatch returns 409, logs an
   integrity incident, and leaves the submission pending for recovery.
4. Conditional update approval `WHERE status='pending' AND lock_version=%s`.
   Require exactly one affected row.
5. On approve, mark version approved; copy its immutable values into the
   document projection; set current pointer/reviewed_by/reviewed_at; insert
   one publication job.
6. On reject, mark version rejected. Preserve the existing approved current
   version, or display Draft if none has ever been approved.
7. Insert requester notification and audit row; commit once.
8. Start/queue post-commit publication work only on approval.

Competing decisions: the first committed decision wins, later requests return
409. The UI may read the existing result to explain it; no second notification.
Decision comments do not change the approved DOCX or PDF. Approval attribution
is shown in the audit panel, not stamped into the file after approval.

### 9.4 Withdraw, archive, and editing confirmed content

Withdrawal locks and verifies the same records, closes the pending approval
with a reason, marks the version withdrawn, and notifies the prior approver.
An already-decided submission cannot be withdrawn.

Archive is soft and fails if any open draft/candidate/submission exists.
Users resolve those first. Archived documents keep history and authorized
version downloads; archive never unlinks evidence files.

To edit a confirmed version, create a new draft. Do not provide an "unlock
version" endpoint or silently reuse its version number.

## 10. Existing routes, integrations, and bypass closure

### 10.1 Legacy route behavior after the change

| Existing operation | Required behavior |
|---|---|
| Add/import document | Use shared ID allocator and explicit owner/org/BU; create Draft only. Ignore no status silently: reject unsupported lifecycle fields. |
| Edit document | Remove arbitrary status/version/approver/body/file changes. Managed content edits start a revision. Allow only explicitly listed non-content metadata when no pending submission exists. |
| Assign owner | Scoped manager selects a real same-org user ID; update display name from that identity. Never authorize by free text. |
| Upload revision | Managed document routes to the upload-candidate flow. Legacy non-DOCX history remains readable; unsupported new candidate types get a clear validation error. |
| Apply template | For managed records, operate only on an editable draft/candidate creation flow. Never rebrand approved/pending files in place. |
| Set Approved / Under Review / AI Draft | Remove from generic forms. Approval and submission services own these transitions. Preserve historical labels read-only. |
| Delete | Managed records use soft archive and state guards; legacy delete also gets scope and file-reference safeguards. |
| Download / revision history | Use shared visibility helper and explicit version checks. Do not return stored filesystem paths. |
| Template list/upload/delete/download | Same organization/BU authorization; soft retirement; validated DOCX input. |

Close these paths even when the feature flag is off. If an older workflow
cannot satisfy the new approval requirements, show a migration-required
response; do not retain a hidden direct-approval escape hatch.

### 10.2 Scope every policy consumer

Search all `aria_documents`, `aria_doc_revisions`, `aria_ask_index` and
`aria://documents` references. Update policy reads in:

- ARIA list/detail/download/history/export/dashboard/framework coverage.
- Generator recent documents/stats, gap context and Ask ARIA suggestions.
- `oneforall/modules/aria/ask_service.py` retrieval and indexing.
- `oneforall/modules/launcher/routes_platform.py` search/deep links.
- `oneforall/modules/launcher/routes_dashboard.py` recent policy cards.
- `oneforall/modules/grid/data_service.py` and
  `oneforall/modules/grid/routes.py` policy-reference/download handlers.
- `oneforall/modules/evidence/routes.py` policy import/file resolution; its
  current-document fallbacks must not bypass exact-version access.
- Relevant policy handlers in `oneforall/core/event_handlers.py`.

Differentiate "draft/confirmed document exists" from "approved policy covers
this control". Coverage and downstream published-policy use require Approved.
Do not count a pre-confirmation draft as either.

The Ask ARIA index is not an authorization database. Join/validate every
document hit against the current authorized document before sending text to
an AI provider, and reject stale indexed content whose current version/hash
does not match. Do not fetch a global top-N and then leak snippets through
debug output. Rebuild affected index entries after migration/publication;
never index editable drafts or candidate bodies.

For generic mixed-entity search, this plan requires correct policy filtering.
Do not claim it completes an unrelated audit of every other module.

### 10.3 Publication jobs and evidence

Implement `policy_publication.py` and scheduler registration.

- Job reads the immutable version ID from the approval transaction.
- Claim with a short DB lease and random token; renew/check before writes.
- Apply side effects with deterministic version-based keys. A crash can
  replay a job; design for at-least-once execution.
- Evidence Vault stores the approved branded bytes and their hash, tagged
  with exact org/document/version IDs. Add a nullable typed
  `aria_policy_version_id` reference and unique per-version constraint for
  managed policy evidence; do not deduplicate by a broad LIKE substring.
- GRID evidence references an immutable version ID. Add a nullable typed
  `aria_policy_version_id` to `grid_evidence_files` and uniqueness per
  `(control_id, aria_policy_version_id)`. Preserve older audit attachments;
  do not make an old audit's evidence silently point at a newer policy.
- Before GRID auto-attachment, validate the audit/control's organization and
  BU against the policy scope. Never attach subsidiary-private evidence to
  an unrelated subsidiary's audit.
- Update GRID policy-reference resolution to authorize both the GRID record
  and the ARIA version before serving the file.
- Existing legacy evidence uses its existing path; typed version references
  take precedence only when present.
- Emit ARIA_POLICY_PUBLISHED with a publication_key and version_id.
  Extend `emit` to return its event ID without changing existing callers.
  Persist that ID on the job and expose failed event-handler status.
- For managed-version events, existing policy handlers must read the
  specified snapshot or delegate to this adapter. Avoid calling both the
  old mutable-document Vault copy and the new copy.
- Make first-party policy handlers replay-safe. A crash between an external
  event delivery and checkpoint can still redeliver; external webhook
  consumers receive the stable publication_key for deduplication.
- Retry at bounded backoff, e.g. 1, 5, 30 minutes, then mark failed after
  five attempts. Show "Approved; evidence synchronization needs attention"
  to scoped managers with a retry action. Never reverse an approval because
  a downstream copy failed.
- Readiness requires duplicate replay, stale worker, and copy-failure tests.

Lifecycle audit and in-app notifications are inserted in the source
transaction, not through helpers that open/commit a second connection.
Record IDs, old/new state, hashes and actor, not entire policy bodies.

## 11. UI specification

Reuse the existing generator output area and Documents page. Put behavior in
`oneforall/static/js/aria_policy_workflow.js` and the sanitized markdown helper
in `oneforall/static/js/aria_markdown.js`.

User journey:

1. Generate returns an editable draft. Show "Draft saved" and its scope,
   owner, reserved reference/version, and "My drafts" resume link.
2. Markdown editor has explicit Save, unsaved indicator and reading preview.
   Save before build. Warn on navigation with unsaved edits. Do not put policy
   bodies in localStorage/sessionStorage; keep unsaved content in memory.
3. "Apply template and preview" chooses authorized active templates, defaults
   to an eligible default, and shows progress while server builds.
4. PDF preview displays the branded artifact, selected template and reserved
   version. "Back to editing" is available. Any subsequent save invalidates
   the PDF and disables confirm until rebuilt.
5. "Confirm version" sends the current build ID/token. For a new policy this
   creates the library document. For a revision it creates a candidate and
   clearly states that the approved version remains current.
6. Documents drawer shows current approved version, candidate if present,
   owner, scope, version history and approval history.
7. "Submit for approval" offers only eligible named users and an optional note.
   Show a useful empty state when nobody is eligible.
8. "Pending my approval" lists only currently accessible assignments.
   Reviewer opens the exact submitted preview, then approves or rejects;
   rejection requires a comment. A stale token reloads state with a message.
9. Rejected/withdrawn versions offer "Create revised draft", not an editable
   version form. Withdrawal/resubmission handles an unavailable approver.
10. Approval history shows requester, assigned approver, actual decision actor,
    UTC-derived display time, comment, version and integrity identifiers.
    Hash details can sit in a details panel, not in the primary user journey.

Use disabled buttons for pending requests, but enforce all rules on the server.
Handle 401/403/409/413/429/503/504 explicitly; never discard local edits on error.
Keep optional markdown, raw Word, branded Word and print exports secondary.
Label raw exports "Unapproved working copy"; do not show "Saved to library"
until confirmation succeeds.

Accessibility: labels, keyboard-operable controls/modals, focus restoration,
announced saving/build/error states, and a readable non-canvas text view.
No visual redesign or unrelated navigation changes.

## 12. Ordered implementation tasks

Every task ends with its pass gate. Record the result in section 16.

### T00. Establish the implementation baseline

Dependencies: none.
Files: existing source map, this plan and execution ledger.

- [ ] Record HEAD/worktree state and recheck function anchors with `rg`.
- [ ] Read fresh DDL, column migrations, tenant migration flow and test fixtures.
- [ ] Inventory every policy read/write/file route and legacy consumer.
- [ ] Run the existing isolated SQLite suite and record pre-existing failures.
- [ ] Verify the documented Ubuntu/systemd production service paths, container
      runtime, available resources and storage ownership. Preserve the current
      app deployment mode when adding the converter.
- [ ] Verify whether a disposable PostgreSQL DB and converter container exist.
      Their absence blocks the corresponding release gate, not schema/editor work.
- [ ] Record legacy owner/scope/version anomalies from fixtures or a safe
      read-only report. Do not inspect or print secrets from `.env`.

Pass: exact file/function inventory and baseline test evidence recorded.

### T01. Add schema, migration checks, and safe adoption

Dependencies: T00.
Files: `oneforall/database.py`;
`oneforall/scripts/prepare_aria_policy_workflow.py` (new);
`oneforall/tests/test_aria_policy_schema.py` (new).

- [ ] Add fields/tables/indexes from section 4, including upload draft fields
      and version references on Evidence Vault/GRID.
- [ ] Order circular FKs/post-migration indexes correctly for both engines.
- [ ] Implement dry-run repair report and explicit mapping input; no default
      write action. Never guess ambiguous legacy organization/owner/version values.
- [ ] Implement idempotent legacy baseline adoption.
- [ ] Add schema readiness check that verifies current-schema ownership.
- [ ] Test fresh creation, old-schema upgrade, repeated migration, preservation
      of old policy/file/approval-like display data, and malformed version values.

Pass: SQLite schema/adoption tests pass; generated PostgreSQL DDL is inspected
and the dedicated PG gate is ready to run.

### T02. Centralize policy access and safe document numbering

Dependencies: T01.
Files: `modules/aria/policy_access.py` (new), `policy_workflow_service.py` (new),
`routes.py`, scoped consumers in section 10, access tests.

- [ ] Implement explicit actor/org/BU resolution and read/edit predicates.
- [ ] Implement owner-ID matching and current approver eligibility.
- [ ] Implement locked number allocator and replace all old MAX()+1 paths.
- [ ] Add scope enforcement to document/template lists, by-ID routes and counts.
- [ ] Cover unassigned users, group BU ancestors, sibling SBUs, deleted users,
      super-admin current-org limits, and organization-wide visibility.
- [ ] Prove an SBU transfer changes future access without changing record scope.

Pass: forbidden actors cannot read/mutate/download/count another BU's private
policy; concurrent allocation never duplicates a document ID.

### T03. Extract and characterize DOCX generation

Dependencies: T00; can be prepared independently but land before T05.
Files: `branding_engine.py`, `routes.py:export_word`,
`oneforall/tests/test_aria_policy_builder.py` (new).

- [ ] Add pure builder and refactor export to call it.
- [ ] Add explicit generated-body branding mode.
- [ ] Preserve all sections including unnumbered initial text/headings/tables.
- [ ] Preserve export filename behavior with sanitized headers.
- [ ] Test headings, lists, tables, emphasis, Unicode and control characters.

Pass: semantic DOCX/export tests pass; no content lost in branded output.

### T04. Implement draft lifecycle and AI persistence replacement

Dependencies: T01, T02.
Files: `policy_workflow_service.py`, `routes_policy_workflow.py` (new),
`routes.py:api_generate_policy`, `main.py`, draft tests.

- [ ] Implement draft create/read/list/save/discard/recover.
- [ ] Replace generator's document upsert with draft persistence.
- [ ] Preserve IMS mapping, prompt inputs, provider/rate-limit behavior.
- [ ] Implement version reservation, explicit source document, authorship
      tracking, lock tokens and one-open-revision guard.
- [ ] Reject over-limit inputs before truncation.
- [ ] Return no library success on persistence failure.
- [ ] Validate input kind for markdown versus uploaded DOCX drafts.

Pass: creating/generating/re-generating never changes any approved record;
two editors get an explicit conflict instead of lost edits.

### T05. Implement private artifacts and local PDF conversion

Dependencies: T02, T03, T04.
Files: `policy_storage.py` and `policy_preview.py` (new),
`oneforall/scripts/aria_policy_preview_worker.py` (new), `config.py`,
`oneforall/.env.example`, `oneforall/requirements-preview.txt` (new),
`deploy/aria-preview/Dockerfile` (new), `docker-compose.yml`,
`deploy/aria-preview/runtime-manifest.json` (new), storage/preview tests.

- [ ] Add feature/converter/spool/timeout/retention settings with documented defaults.
      Use `ARIA_POLICY_AUTHORING_ENABLED=false`, explicit
      `ARIA_POLICY_AUTHORING_ORG_IDS` (empty enables no tenants),
      `ARIA_POLICY_PREVIEW_SPOOL_DIR`, `ARIA_POLICY_PREVIEW_EXECUTABLE`,
      `ARIA_POLICY_PREVIEW_TIMEOUT_SECONDS=60`,
      `ARIA_POLICY_DRAFT_EXPIRY_DAYS=30`,
      `ARIA_POLICY_ORPHAN_GRACE_HOURS=24`, and
      `ARIA_POLICY_TRASH_RETENTION_DAYS=7`. Validate numeric bounds at startup.
      The executable setting belongs to the worker environment; the app uses
      the spool and timeout settings.
- [ ] Implement scoped paths, DOCX validation, hashes and atomic build attach.
- [ ] Pin a reviewed `pypdf` release in `oneforall/requirements-preview.txt`;
      keep worker dependencies separate from the app, preserve the project's
      dependency audit process and record the version.
- [ ] Implement converter timeout/process cleanup/cross-process lock.
- [ ] Build the dedicated worker image and Compose service from section 7.6;
      preserve the active app deployment mode and add durable ARIA file mounts.
- [ ] Record the runtime/font manifest with builds and immutable versions.
- [ ] Verify readiness, worker replacement, controlled update and image rollback.
- [ ] Add exact-build preview endpoint and immutable version-file access helper.
- [ ] Inject failures at source build, branding, conversion, rename and DB attach.
- [ ] Demonstrate no stale build attaches after concurrent save/discard.

Pass: mocked fault tests pass and one real branded DOCX renders to PDF using
the configured converter. Record real converter/font versions.

### T06. Implement confirmation and immutable versions

Dependencies: T01-T05.
Files: `policy_workflow_service.py`, workflow routes, version tests.

- [ ] Implement section 9.1 with one commit boundary.
- [ ] New confirm creates doc/version 1.0; retry returns the same IDs.
- [ ] Revision confirm preserves current Approved projection.
- [ ] Validate exact hashes, reserved reference/version, source base and scope.
- [ ] Add version/history/download responses with no filesystem paths.
- [ ] Test double confirm and stale/missing/tampered artifact refusal.

Pass: confirmed bytes equal previewed build bytes, retries create one version,
and no API can change a confirmed snapshot's content.

### T07. Implement submission, decision, withdrawal, audit and notifications

Dependencies: T02, T06.
Files: workflow service/routes, `policy_access.py`, approval tests.

- [ ] Implement eligible approver list and named submission.
- [ ] Bind hashes, request IDs and round numbers to the immutable version.
- [ ] Enforce requester/owner/all-contributors separation of duties.
- [ ] Implement approve/reject/withdraw/resubmit transitions.
- [ ] Add transaction-local audit/notification helpers.
- [ ] Decision rejects removed roles, moved SBUs, deleted accounts and stale tokens.
- [ ] Implement atomic current-version promotion and publication-job insert.
- [ ] Exercise two simultaneous submitters/deciders with real separate connections.

Pass: state machine, assignment, self-approval, version integrity, concurrency
and rollback tests all pass. Exactly one decision/notification wins.

### T08. Close legacy bypasses and preserve downstream scope

Dependencies: T02, T06, T07.
Files: `routes.py`, `documents.html`, `ask_service.py`, launcher/grid consumers,
legacy-route and retrieval tests.

- [ ] Enforce the complete legacy compatibility table in section 10.1.
- [ ] Route managed upload/template changes into draft/candidate operations.
- [ ] Remove generic lifecycle selectors and free-text authorization.
- [ ] Gate document search, counts, exports and AI context by scope/visibility.
- [ ] Filter stale Ask ARIA index entries by current version.
- [ ] Ensure feature-flag rollback does not re-enable legacy bypasses.
- [ ] Search all document mutations again and record any remaining justified path.

Pass: an HTTP caller cannot bypass approval by using any old add/import/update/
upload/template/delete endpoint, and draft/candidate text never leaks downstream.

### T09. Implement publication, retention, and scheduler lifecycle

Dependencies: T06-T08.
Files: `policy_publication.py`, `scheduler.py` (new ARIA files), `main.py`,
`core/events.py`, `core/event_handlers.py`, GRID/Evidence adapters,
publication/cleanup tests.

- [ ] Implement version-keyed Vault and GRID evidence references and retry jobs.
- [ ] Add current-version-aware search indexing.
- [ ] Register scheduler start/stop and explicit per-tenant context.
- [ ] Use leases so multiple app workers do not process the same job unsafely.
- [ ] Implement safe expiry/orphan detection/dry-run/trash behavior.
- [ ] Surface job failures and scoped retry without reversing approval.
- [ ] Test job replay, partial copy failure, tenant context leakage and cleanup races.

Pass: repeat publication creates no duplicate first-party evidence; retained
versions survive cleanup; approved current files remain available during failures.

### T10. Deliver the complete browser experience

Dependencies: T04-T09.
Files: `ai_generator.html`, `documents.html`, new ARIA JS/helpers,
`static/vendor/aria-policy/`, `core/middleware.py` only for narrow CSP support.

- [ ] Implement section 11 including My Drafts, resumed editor and status badges.
- [ ] Vendor and pin renderer/sanitizer/PDF assets with licenses/checksums.
- [ ] Remove the unpinned Marked import for affected ARIA pages.
- [ ] Use safe markdown rendering in every policy/gap/print/reopened view.
- [ ] Show actual PDF preview, error states and current/candidate distinction.
- [ ] Test keyboard navigation, focus, unsaved changes and duplicate clicks.
- [ ] Preserve existing exports and normal document deep links.

Pass: browser scenario in section 14 completes with no manual file download or
upload, no unsafe rendering, and no console/network failures on the happy path.

### T11. Release verification and handoff

Dependencies: T00-T10.
Files: tests, this plan, `plans/README.md`,
`oneforall/docs/aria-policy-authoring.md` (new operator/user guide).

- [ ] Run targeted tests, full regression suite, compilation and dedicated PG tests.
- [ ] Complete real conversion and browser scenarios, including rejection/revision.
- [ ] Verify upgrade, restart, feature disable, failed converter and failed sync.
- [ ] Document installation/feature flags, retained files, repair report and retry.
- [ ] Clean only temporary test accounts/data/files in disposable test environments.
- [ ] Record commands/results/limitations and mark only proven tasks complete.
- [ ] Enable in the intended deployment only under the applicable authorization.

Pass: every release acceptance item in section 15 is supported by evidence.

## 13. Test organization and commands

Create focused test files rather than one very large test module:

| Test file under `oneforall/tests/` | Required coverage |
|---|---|
| `test_aria_policy_schema.py` | Fresh/upgrade/idempotence, FK ordering, legacy adoption, unmapped owner/org/version |
| `test_aria_policy_access.py` | Roles, org/BU, organization-wide rules, transfer, assigned reviewers, list/count/download scope |
| `test_aria_policy_builder.py` | Semantic markdown/export/branding and no lost preamble content |
| `test_aria_policy_drafts.py` | Generate/save/recover/IMS/idempotency/limits/stale edits |
| `test_aria_policy_storage.py` | Traversal, sibling-prefix paths, malicious ZIP, atomicity, hash mismatch, cleanup references |
| `test_aria_policy_preview.py` | Converter argv/profile/timeout/missing tool/concurrent lock; real-converter marker |
| `test_aria_policy_versions.py` | Confirm, replay, existing approved projection, candidate numbering and immutability |
| `test_aria_policy_approvals.py` | Assignment, authorship, roles/BU changing, rejection/withdrawal, concurrency and transaction rollback |
| `test_aria_policy_legacy.py` | Every legacy status/edit/upload/template bypass and flag-off behavior |
| `test_aria_policy_publication.py` | Version-bound evidence, replay, stale leases, retry failures, no cross-BU attachment |
| `test_aria_policy_retrieval.py` | Ask/search/dashboard/coverage and stale-index protection |
| `test_aria_policy_http.py` | Real middleware/decorators, CSRF origin, response schemas, file headers and unauthorized IDs |

Test fixtures must isolate database, tenant context, upload/template/evidence
directories, AI provider, event handlers and schedulers. Do not start production
schedulers by importing the app in a test. Build a test app using the real
middleware/auth routing behavior with temporary sessions. Mocking all
authorization helpers is not an authorization test.

Dedicated PostgreSQL suite:
`oneforall/integration_tests/test_aria_policy_postgres.py` with its own fixture.
Run in a separate process outside `tests/conftest.py`, which clears DATABASE_URL.

- Require `THEMISIQ_TEST_DATABASE_URL` pointing to a disposable database whose
  name is explicitly test-only. Fail closed on absent/production-like targets.
- Do not print connection credentials or reuse the application's production URL.
- Build public/shared and two tenant schemas in that disposable database.
- Exercise old-schema upgrade, fresh tenant provision, repeated migration,
  same numeric IDs in different tenants, missing tenant relation, concurrent
  reservations/confirmations/decisions, and forced rollback.
- Clean only fixture-created schemas/database content. Never enumerate and
  delete arbitrary tenant schemas.
- A skipped suite is an outstanding release gate, not PostgreSQL validation.

PowerShell commands from the repository root; the inspected Python is
`.venv/Scripts/python.exe`. Run each command separately:

```powershell
.\.venv\Scripts\python.exe -m pytest oneforall/tests -k aria_policy
```

```powershell
.\.venv\Scripts\python.exe -m pytest oneforall/tests
```

```powershell
.\.venv\Scripts\python.exe -m pytest oneforall/integration_tests/test_aria_policy_postgres.py
```

Compile every touched Python file with `python -m py_compile`, listing the
actual touched files after implementation. Run browser XSS checks in an actual
browser; checking that a sanitizer function name appears in source is not a test.

Do not use `scripts/verify_pg_parity.py` as proof of the new workflow: it compares
existing row data, not schema upgrade, tenant safety or transaction behavior.

## 14. Browser acceptance scenarios

Use an isolated demo organization, EcoCash and Omni sibling SBUs, a group
parent BU, a policy author, an eligible approver, and an unrelated Omni user.
Use temporary storage and provider fixtures unless a controlled live AI test
is explicitly authorized.

### Scenario A: first policy, entirely in-app

1. Author generates an EcoCash policy for a control, including an IMS variant.
2. Check My Drafts contains it and Documents/Ask/coverage do not.
3. Edit, save, refresh, and verify the saved text returns.
4. Select template, build, and inspect cover/title/reference/version,
   headings, lists, a table, Unicode text, header/footer and page breaks.
5. Return to editing. Verify the old build cannot be confirmed.
6. Save, rebuild, confirm. Verify one DOC record, one version 1.0 and real files.
7. Submit to eligible approver. Verify one in-app notification/deep link.
8. Log in as approver, open exact submitted preview and approve with a comment.
9. Verify current Approved policy, recorded actor/time/hash, author
   notification, and eventual exact-version evidence/index synchronization.

### Scenario B: approved policy revision and rejection

1. Start revision of Scenario A; modify content and confirm candidate 1.1.
2. As an ordinary reader, verify current download/body remain approved 1.0.
3. Submit 1.1, reject with a required comment, verify 1.0 remains current.
4. Clone rejected content, edit, rebuild and confirm the next reserved version.
5. Approve it. Verify current pointer changes once and older approval/evidence
   history still identifies the original files.
6. Attempt a raw legacy status update, old template-apply request and old
   upload-revision request; verify none alters approved bytes.

### Scenario C: scope, transfer, failures and recovery

1. Omni user guesses draft/version/approval/file URLs: no private EcoCash data.
2. Assigned approver moves from EcoCash to Omni: reloaded scope removes
   eligibility; past decisions retain their original identity.
3. Scoped manager withdraws/resubmits to an eligible approver without override.
4. Two tabs save different text: one receives a conflict; no silent overwrite.
5. Repeated confirm/submit and two competing decisions produce one result.
6. Converter missing/timed out: saved text survives, confirm stays disabled.
7. Template retired or body edited after preview: rebuild required.
8. Tamper with a fixture artifact: submission/decision refuses hash mismatch.
9. Inject unsafe markdown/HTML into editor and generated output: no script,
   image beacon, active link, form or raw HTML execution.
10. Expire a fixture draft and sweep storage: recoverable text remains and
    all committed/version/evidence files survive.
11. Restart after a publication failure: approved file remains available and
    a retry does not duplicate first-party evidence.

Record screenshots/observations and the exact test data identifiers. Cleanup
uses only the disposable environment. Do not create then silently delete live
customer records to simulate this test.

## 15. Release acceptance and rollback

All items are required for calling PLAN-35 complete:

- [ ] I01-I16 have behavioral test coverage and pass.
- [ ] No happy-path manual download/upload is required.
- [ ] Actual branded DOCX-to-PDF conversion and browser rendering are verified.
- [ ] Fresh and upgraded SQLite and PostgreSQL schemas pass.
- [ ] An approved current policy remains intact during all revision states.
- [ ] Approvals bind immutable versions/files and enforce named assignment,
      current scope, authorship rules and server-controlled transitions.
- [ ] Legacy endpoints and feature-disable mode cannot bypass the workflow.
- [ ] Search/Ask/dashboard/GRID/Vault do not leak drafts, candidates or other BUs.
- [ ] File failure/cleanup/publication retry and concurrent-request tests pass.
- [ ] Scoped users can recover drafts and deal with an unavailable approver.
- [ ] Full regression suite, compilation and browser scenarios are recorded.
- [ ] Operator instructions and plan index reflect actual completion state.

Rollout: deploy additive schema with the feature disabled; run readiness and
legacy mapping checks; verify the pinned VPS converter container, persistent
ARIA storage and self-hosted assets; enable
for a test tenant; run scenarios; then enable for intended organizations.
The feature is available only where tenant readiness and deployment flags pass.

Rollback: disable new authoring/submission entry points and stop new
conversion/publication claims. Keep authorized read/history/download and
recorded approvals available. Retain tables, snapshots, migration columns and
files. Resume retry jobs after resolving the issue. Do not deploy older code
that reintroduces direct status writes or drop new tables as a rollback.
An actual database restore requires a separately coordinated backup/restore
operation, not an automatic migration reversal.

## 16. Execution ledger for the implementing model

Planning revision completed on 2026-09-19. No feature implementation, migration,
application test execution or converter installation is claimed by this edit.

| Task | State | Evidence / notes |
|---|---|---|
| T00 baseline | Mostly complete | See detailed notes below. HEAD still `d66f4da` (no drift). Two items need VPS access and remain open. |
| T01 schema/adoption | Complete (SQLite gate) | See detailed notes below. PG dedicated-suite gate not yet run, no disposable PG instance in this session (open since T00). |
| T02 authorization/numbering | Complete | See detailed notes below. |
| T03 builder | Complete | See detailed notes below. |
| T04 drafts | Not started | |
| T05 artifacts/preview | Not started | Requires VPS converter image, persistent storage and readiness |
| T06 confirmation | Not started | |
| T07 approvals | Not started | |
| T08 legacy/scope closure | Not started | |
| T09 publication/cleanup | Not started | |
| T10 UI | Not started | |
| T11 verification/handoff | Not started | Requires dedicated PostgreSQL and browser evidence |

After each task append: files changed, behavioral checks and command results,
any reviewed deviation, and next task. If blocked, name the exact missing
dependency and continue independent tasks. Never replace a release criterion
with a mock or a claim that code "should work".

### T00 detailed notes (2026-09-19)

Repository state: HEAD `d66f4da`, matches the plan's inspected baseline, no
drift. Worktree carried unrelated in-progress edits (`AGENTS.md`,
`plans/README.md`) which are this session's own prior, separate work, not a
conflict with this plan.

Function anchors rechecked with `rg`/direct read, all present at current
locations: `api_generate_policy` (routes.py:2466), `export_word`
(routes.py:2658), `apply_template_to_document` (routes.py:1727),
`upload_document_revision` (routes.py:1420), `update_document`
(routes.py:1099), `documents_page` (routes.py:824), `api_templates_list`
(routes.py:1615), `branding_engine.apply_template` (branding_engine.py:136),
`_apply_tenant_schema_ddl` (database.py:5560), `_PgConnWrapper`
(database.py:179), `bu_scope_ids` (governance/data_service.py:33).

New finding not in section 2's source map: `update_document` (routes.py:1099)
has a partial separation-of-duties guard already, `_can_approve_policy()`
(routes.py:161), BUT it explicitly carves out an exception: a user with
`platform.manage_users` may approve their own document
(`if has_capability(user, "platform.manage_users"): return True`, checked
*before* the owner-match test). This directly conflicts with this plan's I08
and section 5.1 ("Approval override: None in this release, including for
super administrators") and must be closed in T07/T08, not just left as an
existing behavior to preserve.

Column migration mechanism confirmed: a single module-level `_COLUMN_MIGRATIONS`
list of `(table, column, definition)` tuples (starts ~database.py:3874) is
consumed by both `_run_sqlite_alters` (database.py:4191) and `_run_pg_alters`
(database.py:5479, simple `ADD COLUMN IF NOT EXISTS` loop). All existing
`aria_documents` additive columns (`file_path`, `branded_file_path`,
`template_id`, `business_unit_id`, etc.) were added this way. T01 should
append new tuples to this same list rather than inventing a separate
mechanism. `_run_pg_fk_cascades` (database.py:5489) is the separate function
that patches ON DELETE behavior for auto-named PG FK constraints after the
fact; new tables should get correct ON DELETE inline in their CREATE TABLE
where possible instead of relying on this patch step.
`_apply_tenant_schema_ddl` (database.py:5560) is confirmed as the single
canonical function shared by both `provision_tenant_schema` (new tenants) and
tenant upgrades; it runs all `_TABLES_PG` scripts, then `_run_pg_alters`,
`_run_pg_fk_cascades`, then `_seed_baseline_data`. New tables' PG DDL and the
new columns both need to land inside this same call chain.

Additional legacy consumers found beyond section 10.2's list (grep across the
whole `oneforall/` tree, not just the named files): `governance/data_service.py`
references `aria_documents` only in a generic "is this BU referenced anywhere"
guard before allowing BU deletion (not a content consumer, no change needed
beyond keeping the table name in that list). `launcher/routes_super_admin.py`
references `aria_doc_templates` in what appears to be a generic per-table
admin listing/count utility alongside many other tables. Section 10.2's
named files (`ask_service.py`, `routes_platform.py`, `routes_dashboard.py`,
`grid/data_service.py`, `grid/routes.py`, `evidence/routes.py`,
`event_handlers.py`) were all individually re-verified and do reference
`aria_documents` as stated.

Baseline test evidence: full `pytest -q` run clean, 0 failures (exact count
not printed by this repo's pytest config, but progress output showed 100%
with no F/E markers across all three progress segments). No pre-existing
failures to account for.

Local dev DB (`oneforall/data/oneforall.db`, SQLite, gitignored) read-only
anomaly check: `aria_documents` has 4 rows, all with clean `N.M` version
strings, no blank owners, 0 rows with `file_path` set (nothing generated/
uploaded yet in this dev DB), 0 rows with `business_unit_id` set (all NULL,
i.e. organization-wide under the existing convention). `organizations` has
**0 rows**; `business_units` has 1 row; `aria_doc_templates` has 0 rows. This
is a clean, small dataset locally, no messy legacy data to reconcile in this
DB specifically. This says nothing about production's actual row counts,
which have not been checked (no production DB access in this session) and
should not be assumed equally clean.

`ARIA_UPLOAD_DIR` / `ARIA_TEMPLATE_DIR` defaults confirmed at
routes.py:1240-1241: `data/aria_uploads` / `data/aria_templates`, both
overridable via env var, both relative to the app's working directory.

**Open, blocks nothing in T01-T04, needed before T05**: production Ubuntu/
systemd service paths, container runtime availability, VPS resource capacity,
and storage ownership were not verified, no VPS access in this session.
Exact commands to run are needed from Ali. A disposable PostgreSQL DB and
a converter-container environment were also not confirmed to exist; their
absence blocks only the T05/T11 real-conversion and dedicated-PG gates, not
schema or editor work, per T00's own instruction.

### T01 detailed notes (2026-09-19)

Files touched: `oneforall/database.py` (5 new tables appended to the end of
`_ARIA_TABLES`, auto-translated to PG by the existing `_to_pg_schema`; 12 new
`_COLUMN_MIGRATIONS` entries across `aria_documents`, `aria_doc_templates`,
`evidence_items`, `grid_evidence_files`; a new `aria_policy_workflow_schema_ready()`
check); `oneforall/scripts/prepare_aria_policy_workflow.py` (new); `oneforall/tests/test_aria_policy_schema.py` (new, 17 tests).

Placement: the 5 new tables (`aria_policy_drafts`, `aria_policy_versions`,
`aria_document_approvals`, `aria_document_number_sequence`,
`aria_policy_publication_jobs`, in that FK-dependency order) went at the end
of `_ARIA_TABLES` (was `governance_advisories`), since everything they
reference (`aria_documents`, `aria_doc_templates`, `organizations`,
`business_units`, `users`) is already defined earlier in the executescript.
`current_policy_version_id` on `aria_documents` went through
`_COLUMN_MIGRATIONS` instead of the base CREATE TABLE specifically to avoid
the circular-ordering problem the plan calls out (`aria_policy_versions`
doesn't exist yet at that point in the base table script); confirmed this
is safe because `_COLUMN_MIGRATIONS`/`_run_pg_alters` always run AFTER all
`_TABLES_PG` executescripts in `_apply_tenant_schema_ddl`.

Two partial/unique indexes are genuine correctness constraints, not
performance indexes: "at most one pending approval per document" and "at
most one open draft/candidate per document" (invariants I09/I10). These are
inline in the new tables' own CREATE TABLE text, so they reach both engines
automatically via the existing `_to_pg_schema` translation, verified
directly (dumped the translated PG DDL and confirmed CHECK constraints,
partial `WHERE` clauses, `SERIAL`, and `TIMESTAMPTZ DEFAULT NOW()` all
translate correctly).

**Real, pre-existing gap found and narrowly fixed**: `_run_sqlite_alters`'s
`_POST_MIGRATION_INDEXES` list has no PostgreSQL equivalent runner at all —
`_run_pg_alters` only ever added columns, never indexes. This meant every
prior table's post-migration index in that list has silently never reached
production Postgres. Did not fix that broader pre-existing gap (out of
scope for this plan). Did fix it narrowly for the two NEW indexes that are
correctness constraints, not performance (`evidence_items` and
`grid_evidence_files`'s version-dedup uniques, per section 10.3): duplicated
verbatim into `_run_pg_alters` with a comment on both copies to keep them in
sync. The two purely-performance indexes on `aria_documents.org_id`/
`owner_user_id` were left SQLite-only, consistent with the existing
(imperfect but out-of-scope-to-fix) pattern.

**Real, pre-existing bug found, not fixed (T02 already retires the code path
that has it)**: `api_generate_policy` (routes.py:~2596) and
`upload_new_document` (routes.py:~1025) compute the next `DOC-XXXX` number
via `SUBSTRING(doc_id FROM 5)`, which is PostgreSQL-only syntax. Confirmed
directly against real SQLite that this raises `OperationalError: near
"FROM": syntax error` — a genuine, currently-latent bug that would crash the
"create a brand-new document" path on SQLite (evidently never exercised by
the existing test suite, or masked by every test document already existing).
`prepare_aria_policy_workflow.py`'s own number-sequence initializer needed
the identical MAX-suffix query and initially copied this exact broken
syntax, caught by its own test (`test_number_sequence_initializes_past_highest_existing_doc_id`
failed with the same SQLite error) and fixed to the portable
`SUBSTR(doc_id, 5)`. Not fixing the two existing call sites here: T02's own
checklist already says "replace all old MAX()+1 paths" with the new locked
allocator, which retires both of them.

`prepare_aria_policy_workflow.py` deliberately does NOT bulk-create
`aria_policy_versions` "legacy" baseline rows. Section 4.8 item 9 specifies
that adoption happens lazily, per document, at first revision/submission
under a document lock — a bulk script doing it here would race with that
later, service-owned path. This script's scope is the dry-run
org/owner/version repair report, the document-number sequence
initialization, and an explicit `--apply-org-id` path for the single-org
case (refuses if zero, or more than one, organizations exist — never
guesses which org a legacy NULL-org row belongs to).

One logic bug caught and fixed by its own tests before this was reported
done: the report's owner-matching originally searched for users scoped to
the DOCUMENT's own (often NULL) `org_id`, which made owner resolution
impossible for exactly the common case it exists to handle. Fixed to search
within the single existing organization when the document's org_id is NULL
and exactly one organization exists (the only case where that search scope
is unambiguous); left unresolved (correctly) when zero or multiple
organizations exist.

Test evidence: `test_aria_policy_schema.py` 17/17 passing (fresh creation,
all new tables/columns present, schema-readiness check both positive and
negative, repeated `init_db()` idempotence with pre-existing row data
preserved and not duplicated, number-sequence initialization and
non-rewind, and eight report-classification scenarios including the
malformed-version-is-reported-not-reset case from item 10). Full regression
suite re-run clean after these changes, no failures. `py_compile` clean on
all three touched/new files.

Not yet done, correctly deferred: PostgreSQL DDL was inspected by direct
translation dump (not executed against a real PostgreSQL server, none
available in this session) — the dedicated `test_aria_policy_postgres.py`
suite T01 mentions is T11's gate, not built yet, and would need
`THEMISIQ_TEST_DATABASE_URL` to actually run.

### T02 detailed notes (2026-09-19)

Files touched: `oneforall/modules/aria/policy_access.py` (new: `document_read_ok`,
`document_scope_sql`, `template_scope_sql`, `document_edit_ok`,
`resolve_create_bu`, `eligible_approvers`, `is_eligible_approver`,
`can_decide`, `reserve_document_number`); `oneforall/modules/aria/routes.py`
(`documents_page`'s list query and all 5 count queries, `templates_page`,
`api_templates_list` now scope-filtered); `oneforall/tests/test_aria_policy_access.py`
(new, 19 tests).

**Adapted one plan detail to this codebase's actual reality**: `users.deleted_at`
does not exist anywhere in this codebase (confirmed directly, no such column
or migration entry). User removal here is `is_active=0` (soft) or the row
being hard-deleted entirely (several FKs use `ON DELETE CASCADE`). Every
"account still valid" check uses `is_active=1` combined with a real JOIN
against `users` (which already excludes hard-deleted rows), not a
`deleted_at` comparison. Documented in `policy_access.py`'s module docstring
so this isn't rediscovered later.

**Scoped T02 deliberately to what section 2's source map flagged as
currently unscoped** (`documents_page | List and totals read aria_documents
without BU filtering`, and the equivalent for templates): the document list
+ its 5 count queries, and both template list endpoints (`templates_page`,
`api_templates_list`). Did NOT retrofit the individual by-ID routes
(`update_document`, `download_document`, `apply_template_to_document`,
`upload_document_revision`) to use the new scope helpers -- T08's own
checklist explicitly owns that ("Route managed upload/template changes into
draft/candidate operations", "Search all document mutations again").
Doing it here too would duplicate T08's work against routes that are
themselves being replaced/closed by T06-T08, not extended.

**Legacy-visibility design carried over from T01's ledger note, restated
here since it's this module's core judgment call**: a document with
`org_id IS NULL AND policy_workflow_managed=0` (i.e. every existing document
today) keeps its current, unrestricted visibility rather than becoming
invisible to everyone until manually adopted. `document_read_ok`,
`document_scope_sql`, and `template_scope_sql` all implement this the same
way. T08 is where the remaining legacy-visibility exception actually closes.

**Bug caught by its own test before being called done**: `eligible_approvers`'
candidate query selected `id, username, full_name, business_unit_id,
is_super_admin` but not `org_id` or any roles, so `has_capability()` (which
reads `user["roles"]`) silently evaluated every candidate as roleless and
never eligible. `test_eligible_approvers_excludes_owner_and_requester_and_deactivated`
failed on first run (expected user 3, got nobody) and caught it. Fixed by
loading `org_id` and each candidate's `user_roles` before the capability check.

**Verified rather than assumed**: `core/auth.get_session_user` (routes.py's
actual auth path via `core/middleware.get_current_user`) already re-queries
`sessions` then `users` fresh on every single HTTP request, no caching --
`request.state.user` is therefore already current as of request time for
the acting user. The plan's "reload current activity, organization, roles
and BU at mutations" requirement is substantially already satisfied by this
existing mechanism for the actor; where it actually matters going forward is
re-evaluating OTHER users (approver candidates) with a fresh query each
time, which `eligible_approvers` already does (no caching of candidate rows
across calls).

**SBU-transfer invariant tested directly, not via the full production
workflow**: `governance.transfer_user_business_unit` requires
`handover_confirmed`, `roles_reviewed`, a 10-1000 character reason, and
touches the People Directory and an assignment ledger -- machinery unrelated
to authorization itself. `test_sbu_transfer_changes_future_access_without_touching_record_scope`
proves the actual property this module owns (changing a user's
`business_unit_id` flips `document_read_ok`'s answer for a BU-scoped
document, while the document's own recorded scope is provably untouched)
without coupling an access-control test to an unrelated workflow's
preconditions.

**Concurrency claim proven empirically, twice**: an ad hoc 20-thread run
during development and a permanent 25-thread pytest test
(`test_concurrent_reservations_never_duplicate_a_document_number`) both
fire real concurrent `reserve_document_number()` calls against a real
file-based SQLite DB (not `:memory:`, which isn't shared across
connections) and confirm zero duplicate numbers, zero errors. `BEGIN
IMMEDIATE` correctly serializes the read-modify-write on SQLite; the
PostgreSQL path uses `SELECT ... FOR UPDATE` (matching the existing lock
idiom already used by `governance.transfer_user_business_unit`), not yet
concurrency-tested against a real PostgreSQL server (no instance available
this session, same open item as T00/T01).

Test evidence: `test_aria_policy_access.py` 19/19 passing (unassigned user,
group-BU ancestor, sibling-BU exclusion, super-admin org limit, legacy
passthrough, SQL-fragment/predicate parity, template retirement, the
SBU-transfer invariant, three create-time BU resolution cases, three
approver-eligibility exclusion cases, the no-override decide check, and two
number-allocator tests including real concurrency). Full regression suite
re-run clean after these changes. `py_compile` clean on all touched/new files.

### T03 detailed notes (2026-09-19)

Files touched: `oneforall/modules/aria/branding_engine.py` (new
`build_policy_docx()`; `apply_template()` gains `generated_body: bool =
False`); `oneforall/modules/aria/routes.py` (`export_word` reduced from
~115 lines to a ~15-line wrapper around the extracted builder, filename
generation and the StreamingResponse untouched); `oneforall/tests/test_aria_policy_builder.py`
(new, 13 tests).

**Confirmed the exact bug section 2 flagged, by reading `_is_content_start()`
directly**: the legacy heuristic in `apply_template()` sets
`content_started = True` only when a paragraph's text starts with
"purpose"/"scope"/"introduction"/"objective", or is a numbered Heading1/2
(`^\d+[\.\)]?\s`), or when any table appears. If a source document's first
heading matches none of those (e.g. a generated policy titled "# Data
Retention Policy"), `content_started` never flips and every single
paragraph is silently skipped, since the loop's `else: continue` branch
runs for the whole document. `test_heuristic_mode_drops_content_with_an_unrecognized_first_heading`
reproduces this exactly against the legacy `generated_body=False` path
(asserting the content is indeed absent, not present) before proving the
fix (`generated_body=True`) preserves the same content.

**The fix is a one-line change**: `content_started = generated_body`
instead of `content_started = False`. When `generated_body=True`, every
element in the source body is copied unconditionally (still filtered to
`p`/`tbl` tags and excluding `sectPr`, unchanged from before) — correct
because a source built via `build_policy_docx(include_preamble=False)` has
no preamble to strip in the first place, unlike an uploaded legacy document
which might carry its own cover page.

**Added control-character sanitization that did not exist in the original
`export_word`**: the plan's own T03 checklist asks to test control
characters, and the original inline parser had no sanitization at all —
raw control characters could either crash `python-docx` or corrupt the
saved package. `build_policy_docx` now runs each line through
`branding_engine._sanitise()` (the same stripping this file already uses
for template metadata fields: removes `\x00-\x08`, `\x0b`, `\x0c`,
`\x0e-\x1f`, explicitly preserving tab/newline/CR) before parsing. This is
new, additive hardening on a path that previously had none, not a
behavior change for any input that was already valid.

**One test bug caught and fixed before reporting complete** (not a builder
bug): `test_unicode_content_preserved` initially asserted against the wrong
paragraph index, having miscounted the blank-line paragraph that a `\n\n`
in the source markdown produces between the heading and the following
text. Fixed the index, not the assertion's intent.

Test evidence: `test_aria_policy_builder.py` 13/13 passing — preamble
on/off behavior (proving `include_preamble=True` reproduces the exact prior
`export_word` heading structure), heading levels 1-3, bullet and numbered
lists, table parsing with header-row bolding, bold/italic/bold-italic
emphasis, Unicode text (French accents, Japanese, an emoji) preserved
verbatim, control characters stripped without crashing `doc.save()`,
tab/newline explicitly NOT stripped, the heuristic-drops-content regression
proof, the generated_body-preserves-content fix proof (including tables),
and a regression guard that the legacy heuristic path is completely
unchanged for a properly-prefaced legacy-shaped upload. Full regression
suite re-run clean. `py_compile` clean on all touched/new files.

Tests check semantic structure (paragraph text, style names, table cell
values, run.bold/run.italic) rather than raw DOCX bytes, per the plan's own
instruction that ZIP timestamps and package metadata can legitimately
differ between runs.

Suggested implementation-session prompt:

> Execute PLAN-35 from the first incomplete task. Read its selected decisions,
> data model, authorization and transaction rules before editing. Keep the
> feature disabled until all release gates pass. Preserve approved documents,
> unrelated work and historical evidence. Record actual checks and remaining
> blockers in the execution ledger. Do not substitute the old AI Draft row,
> download-only preview or direct approval/status changes.

## 17. Primary references for the selected preview/rendering components

These establish component capabilities, not a security endorsement of any
future release. Pin and review versions when implementing.

- [LibreOffice command-line parameters](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html):
  headless conversion, output directory and separate user-profile options.
- [Mozilla PDF.js getting started](https://mozilla.github.io/pdf.js/getting_started/):
  display-layer rendering and local worker/build structure.
- [DOMPurify project documentation](https://github.com/cure53/DOMPurify):
  HTML sanitization and explicit allowlist configuration.
- [Docker build best practices](https://docs.docker.com/build/building/best-practices/):
  immutable image references and deliberate rebuild/update management.
- [Docker Compose service settings](https://docs.docker.com/reference/compose-file/services/):
  worker isolation, resource limits, networking and health checks.
- [LibreOffice security advisories](https://www.libreoffice.org/security/):
  security fixes to evaluate when selecting/updating the converter runtime.
- [pypdf reader documentation](https://pypdf.readthedocs.io/en/stable/modules/PdfReader.html):
  strict PDF parsing, encryption detection and page inspection.

The schema, workflow, authorization, resource limits, version policy and task
order above are design decisions for ThemisIQ based on the inspected codebase.
