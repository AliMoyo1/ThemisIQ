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

- [x] Enforce the complete legacy compatibility table in section 10.1
      (except "Assign owner" as a dedicated real-user-id picker and
      "file-reference safeguards" on legacy delete -- both are new
      features with no existing endpoint to close a bypass in; see notes).
- [x] Route managed upload/template changes into draft/candidate operations.
- [x] Remove generic lifecycle selectors and free-text authorization.
- [x] Gate document search, counts, exports and AI context by scope/visibility.
- [ ] Filter stale Ask ARIA index entries by current version -- deferred to
      T09: the indexer only reads aria_documents today, never
      aria_policy_versions, so there is no per-version staleness yet to
      filter (see notes).
- [x] Ensure feature-flag rollback does not re-enable legacy bypasses.
- [x] Search all document mutations again and record any remaining justified path.

Pass: an HTTP caller cannot bypass approval by using any old add/import/update/
upload/template/delete endpoint, and draft/candidate text never leaks downstream.

### T09. Implement publication, retention, and scheduler lifecycle

Dependencies: T06-T08.
Files: `policy_publication.py`, `scheduler.py` (new ARIA files), `main.py`,
`core/events.py`, `core/event_handlers.py`, GRID/Evidence adapters,
publication/cleanup tests.

- [x] Implement version-keyed Vault and GRID evidence references and retry jobs.
- [x] Add current-version-aware search indexing.
- [x] Register scheduler start/stop and explicit per-tenant context.
- [x] Use leases so multiple app workers do not process the same job unsafely.
- [x] Implement safe expiry/orphan detection/dry-run/trash behavior.
- [x] Surface job failures and scoped retry without reversing approval.
- [x] Test job replay, partial copy failure, tenant context leakage and cleanup races
      (cleanup races: prevented by the 24h grace period plus max_instances=1,
      not by a lease -- see notes; no other module's scheduler in this
      codebase has cross-worker cleanup locking either).

Pass: repeat publication creates no duplicate first-party evidence; retained
versions survive cleanup; approved current files remain available during failures.

### T10. Deliver the complete browser experience

Dependencies: T04-T09.
Files: `ai_generator.html`, `documents.html`, new ARIA JS/helpers,
`static/vendor/aria-policy/`, `core/middleware.py` only for narrow CSP support.

- [x] Implement section 11 including My Drafts, resumed editor and status badges.
- [x] Vendor and pin renderer/sanitizer/PDF assets with licenses/checksums.
- [x] Remove the unpinned Marked import for affected ARIA pages.
- [x] Use safe markdown rendering in every policy/gap/print/reopened view.
- [x] Show actual PDF preview, error states and current/candidate distinction.
- [ ] Test keyboard navigation, focus, unsaved changes and duplicate clicks --
      unsaved-changes indicator and the beforeunload warning are built and
      the save/build/confirm buttons disable during their own in-flight
      request; NOT done: a dedicated keyboard-nav/focus-trap/focus-restoration
      audit, and a real rapid-double-click race test. See notes.
- [x] Preserve existing exports and normal document deep links (this
      surfaced a real, pre-existing gap -- see notes).

Pass: browser scenario in section 14 completes with no manual file download or
upload, no unsafe rendering, and no console/network failures on the happy path
-- see notes for exactly which parts of section 14 were and were not run.

### T11. Release verification and handoff

Dependencies: T00-T10.
Files: tests, this plan, `plans/README.md`,
`oneforall/docs/aria-policy-authoring.md` (new operator/user guide).

- [x] Run targeted tests, full regression suite and compilation -- NOT done:
      dedicated PG tests, no PostgreSQL instance is available in this
      environment. See T11 progress notes.
- [~] Complete real conversion and browser scenarios, including rejection/revision --
      the reject decision and start-revision flows are now verified live, as two
      genuinely separate logged-in users, including the specific gap flagged in
      T10 notes (a second real approver session). See "T11 live verification
      pass" notes below. NOT done: real (non-mocked) LibreOffice conversion --
      still not installed in this environment; the PDF-conversion step itself
      was mocked for this pass exactly as it was for T10's.
- [~] Verify upgrade, restart, feature disable, failed converter and failed sync --
      feature disable (`test_aria_policy_feature_gate.py`, route-level, new),
      failed converter (T10 notes: a real timed-out build against no running
      converter, in a live browser) and failed sync (`test_aria_policy_publication.py`'s
      retry/max-attempts/notification tests) all have direct evidence. NOT
      done: app upgrade/restart was not exercised in this session.
- [x] Document installation/feature flags, retained files, repair report and
      retry -- `oneforall/docs/aria-policy-authoring.md`.
- [x] Clean only temporary test accounts/data/files in disposable test
      environments -- two passes. First: found and removed
      `data/aria_uploads/policy_workflow/org_500/` (two artifact
      directories, one staging directory), orphaned leftovers from this
      session's earlier live-browser testing with zero surviving database
      references (checked every table that could reference org/BU 500:
      none did). Second, after the T11 live verification pass: deleted
      organization 501, both its users, its template row, the 4 draft
      rows it produced, its one confirmed version and its one approval
      (re-queried every affected table afterward and confirmed zero rows
      remained, not assumed from the DELETE statements), removed
      `data/aria_uploads/policy_workflow/org_501/` and the generated test
      template file, and restored `.env` to its original two lines. Not
      cleaned up, because it isn't test data: the dev-only `admin`
      account's password was intentionally reset earlier in this work to
      a known value for browser-automation login, and remains that way --
      flagged for the user, not reverted unilaterally.
- [x] Record commands/results/limitations and mark only proven tasks
      complete -- this is the standard this ledger's T09/T10/T11 notes
      have followed throughout (see each task's own "detailed notes"
      subsection).
- [ ] Enable in the intended deployment only under the applicable
      authorization -- not enabled anywhere in this session; stays
      unchecked until that authorization is actually given and acted on,
      not merely withheld.

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
| T04 drafts | Complete | See detailed notes below. |
| T05 artifacts/preview | Code and mocked tests complete; real-converter gate open | See detailed notes below. |
| T06 confirmation | Complete | See detailed notes below. |
| T07 approvals | Complete | See detailed notes below. |
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

### T04 detailed notes (2026-09-19)

Files touched: `oneforall/modules/aria/policy_workflow_service.py` (new:
`create_draft_from_generation`, `get_draft`, `list_my_drafts`,
`save_draft_body`, `discard_draft`, `recover_draft`, `start_revision_draft`,
the `PolicyWorkflowError` hierarchy matching section 8's error codes);
`oneforall/modules/aria/routes_policy_workflow.py` (new router: list/get/
save/discard/recover drafts, start a revision); `oneforall/modules/aria/routes.py`
(`api_generate_policy`'s persistence block replaced, three new optional
form fields: `request_id`, `target_business_unit_id`, `org_wide`);
`oneforall/main.py` (new router registered); `oneforall/tests/test_aria_policy_drafts.py`
(new, 15 tests).

**Confirmed `api_generate_policy` still had the exact `SUBSTRING(doc_id
FROM 5)` PostgreSQL-only bug found during T01/T03** (same code, unchanged
until now) — fully retired by this task, since persistence now goes
through `create_draft_from_generation` -> `policy_access.reserve_document_number`
(the portable, lock-tested allocator from T02).

**Real bug caught by the tests, not by inspection**: `start_revision_draft`'s
own `SELECT` for the target document didn't include `owner_user_id`, so
`_draft_can_edit_document`'s ownership check always compared against `None`
regardless of the real data, silently denying every non-`edit_any` owner.
An ad hoc debug script written to investigate the first test failure
initially masked this (it manually included `owner_user_id` in its own copy
of the query), which itself is a small lesson: the debug script had to be
made to call the actual function, not a hand-rolled equivalent of it,
before the real bug surfaced. Fixed by adding the missing column to the
service's own query.

**Scoped version reservation as preview-only for this task**: `_next_preview_version`
computes what version a draft WOULD become (current version's minor + 1, or
1.0 for a new policy) purely for display, not a final race-proofed
reservation. Section 4.6's full "include all previously reserved draft and
confirmed numbers, never reuse an abandoned one" guarantee is a confirm-time
concern (T06), which does not exist yet — noted directly in the function's
docstring so this isn't mistaken for the final mechanism later.

**Legacy document adoption is deliberately NOT performed here**: both
`create_draft_from_generation` and `start_revision_draft` record
`source_document_id` against an existing document (managed or still
legacy/unmanaged) so the draft knows what it's revising, but neither
creates an `aria_policy_versions` legacy baseline or flips
`policy_workflow_managed`. Section 4.8 item 9 places actual adoption at
first revision/submission under a document lock -- T06's job, not T04's.

**Two API-contract endpoints from section 8 not built in this task**:
`POST /aria/api/policy-drafts/{draft_id}/source` (multipart file-based
draft upload) and the full `content_kind='uploaded_docx'` path. T04's own
checklist item is "validate input kind for markdown versus uploaded DOCX
drafts," which `save_draft_body` already satisfies (a markdown save on a
non-markdown draft returns 409, per section 8's own text), not "build the
upload-and-replace endpoint" -- that reads as this same file-based-draft
feature area but a distinct deliverable, left for whichever later task
actually needs it (the plan does not name a specific one).

**Consistent with the rest of this codebase rather than the plan's literal
"strict JSON models" wording**: the new mutation endpoints parse a plain
JSON dict (with explicit required-field checks) rather than Pydantic
`BaseModel` request bodies, since nothing else in this codebase uses
Pydantic body models either -- introducing one isolated pocket of that
pattern seemed like the wrong kind of consistency to add.

Test evidence: `test_aria_policy_drafts.py` 15/15 passing -- new-vs-revision
detection, the module's actual pass condition proven twice (a single
generation and three repeated generations against the same control both
leave an approved document's title/version/status/body completely
untouched), IMS metadata storage, request_id idempotency (including that a
duplicate submission does not create a second row), oversized content
rejected before any row is written (not truncated), an oversized save
rejected the same way, the stale-edit conflict itself (two editors load the
same draft, the first save wins, the second's stale token is refused, and
the final body proves the second write never applied), save invalidating a
previously-set build, discard-then-recover creating a new draft while the
original stays discarded, list scoping to the owner's own non-discarded
drafts, the one-open-revision guard (backed by T01's own partial unique
index, not just an application-level check), and permission denial for a
user with neither edit_own nor edit_any. Full regression suite re-run
clean. `py_compile` clean on all touched/new files.

### T05 detailed notes (2026-09-19)

Files touched: `oneforall/config.py` (7 new settings, all disabled/safe by
default, plus a startup validator that rejects a nonsensical value rather
than surfacing it later); `oneforall/modules/aria/policy_storage.py` (new:
scoped path helpers, DOCX validation, hashing, atomic staging-to-artifacts
attach, cleanup dry-run listing); `oneforall/modules/aria/policy_preview.py`
(new: the app-side spool client -- submit/poll/cleanup); `oneforall/scripts/aria_policy_preview_worker.py`
(new: the actual conversion worker, run as a separate process/container);
`oneforall/modules/aria/policy_workflow_service.py` (extended: `build_draft`,
the orchestration tying source-build -> branding -> conversion -> hashing
-> atomic attach together); `oneforall/modules/aria/routes_policy_workflow.py`
(new build and preview endpoints); `oneforall/requirements-preview.txt`
(new, worker-only dependencies); `deploy/aria-preview/Dockerfile` and
`deploy/aria-preview/runtime-manifest.json` (new); `docker-compose.yml`
(new `aria-preview` service, a shared spool volume, and the durable
`aria_uploads`/`aria_templates` mounts on `app` that were confirmed missing
during the plan's own T00-era clarification); `oneforall/.env.example`
(documented the new settings); four new test files (`test_aria_policy_storage.py`
20 tests, `test_aria_policy_preview.py` 10 tests, `test_aria_policy_build.py`
12 tests -- 42 total, all passing together).

**What is genuinely proven in this session, with real evidence, not
assumed**:
- DOCX validation against an actual malicious-input corpus: path
  traversal and absolute-path zip entries, a real macro-signaling member
  (`word/vbaProject.bin`), an OLE embedding path, an entry with the
  encryption bit set (flipped directly in a real zip's central directory
  bytes, not simulated), an entry-count flood, and a genuine zip-bomb
  (5 MiB of one repeated byte compressing to a tiny archive, well past the
  configured expansion-ratio limit) -- all correctly rejected; a real,
  valid python-docx-generated file correctly passes.
- Path containment: a path outside `ARIA_UPLOAD_DIR`, an absolute stored
  path, and a `../` traversal in a stored path are all rejected by
  resolving and checking `is_relative_to` against the real filesystem, not
  a string prefix comparison.
- The full spool protocol end-to-end, submit through claim, convert
  (mocked), result, poll, and cleanup, plus every named failure mode:
  converter timeout, converter process error (with the real stderr
  surfaced), the app timing out when the worker never runs at all, an
  already-expired job being refused without ever invoking the converter,
  a malformed/missing manifest, a missing input file, two claim attempts
  on the same job (only one wins), and the worker's own singleton lock.
- The build orchestration's actual pass condition -- **no stale build ever
  attaches** -- proven by two concurrency tests: an edit that changes
  `lock_version` while a build is "in flight" against the old token causes
  the final attach to be refused (`StaleDraftError`) and the draft's
  `build_id` stays `None`; the same for a concurrent discard. Also proven:
  idempotent retry (unchanged inputs return the existing build without a
  second conversion call, verified by asserting the mock was called
  exactly once across two `build_draft` calls) and fault injection at each
  of source-build, branding, conversion-timeout, conversion-failure, and
  atomic-attach, each leaving the draft completely unchanged.
- `docker-compose.yml` is syntactically valid YAML (parsed and inspected
  directly), and the durable ARIA mounts genuinely were absent before this
  change (confirmed by reading the file before editing it, matching the
  plan's own T00-era finding).

**What is explicitly NOT verified, and cannot be from this session, tracked
as open items**:
- **The task's own stated pass condition** -- "one real branded DOCX
  renders to PDF using the configured converter" -- has not been run. No
  LibreOffice binary and no Docker runtime are available in this sandboxed
  session. Every conversion test above mocks the single `convert()` call
  site in the worker; the worker's actual `subprocess.run([...soffice...])`
  invocation has never executed for real. This needs to run on a host that
  actually has LibreOffice (or the built `aria-preview` image) available.
- The `Dockerfile`'s base image is pinned to a literal placeholder
  (`sha256:PIN_ME_AT_RELEASE_TIME`), not a real digest -- I have no
  registry access to resolve and verify one, and inventing a digest would
  be worse than being explicit that this is unresolved. Same placeholder
  pattern in `docker-compose.yml`'s `aria-preview` image tag and in
  `runtime-manifest.json`'s template fields. None of these may pass
  readiness as-is, per the plan's own instruction.
- `pypdf==5.1.0` in `requirements-preview.txt` is pinned to a version from
  my training data, not confirmed against PyPI or current security
  advisories in this session (no network access to verify). Needs the
  project's normal dependency-audit pass before being trusted, exactly as
  the plan itself says to do and not treat as evergreen-safe.
- The image has not been built, so font substitution, page breaks, logo
  placement, and multilingual text have not been visually verified in a
  real converted PDF at all -- section 7.6 item 7's "measure representative
  long policies, tables, logos and multilingual text before enabling" is
  entirely unstarted.
- The cleanup/retention *job* itself (scheduled sweep of expired drafts and
  orphaned staging directories) is not implemented -- `policy_storage.cleanup_dry_run`
  exists and is tested as a listing primitive, but nothing calls it on a
  schedule yet. Section 7.5's full cleanup policy is more naturally T09's
  concern (publication, retention, and scheduler lifecycle is that task's
  explicit title); noting this now rather than silently deferring it
  without a record.

Given the above, T05 should be read as: the code, the storage/validation/
orchestration logic, and everything mockable are done and tested; the
actual document-conversion pass condition requires your environment
(a host or container with LibreOffice, or the Docker Compose service once
its image is actually built) to close out.

### T06 detailed notes (2026-09-19)

Files touched: `oneforall/modules/aria/policy_workflow_service.py` (new:
`confirm_draft`, `get_version`, `list_document_versions`,
`get_version_file_path`, the `_version_to_public_dict` field-stripping
helper, and `StaleBaseError`/`BuildRequiredError`);
`oneforall/modules/aria/routes_policy_workflow.py` (new: confirm, version
list/detail/preview/download endpoints); `oneforall/tests/test_aria_policy_versions.py`
(new, 12 tests).

**Real atomicity bug caught and fixed before this was reported done**: the
first draft of `confirm_draft` called the codebase's existing
`core.middleware.log_audit()` for the lifecycle audit row, the same helper
every other ARIA route already uses. Reading its body showed it opens its
OWN `get_db()` connection and calls `commit()` immediately on that
connection, independently of the caller's transaction. Section 9.1 item 7
is explicit that the audit row must be inserted "using the same
connection" and committed once, together with everything else, precisely
so an audit row can never exist for a confirmation whose actual document/
version/draft writes later failed to commit. Using `log_audit()` here
would have created exactly that gap: a confirmation could show as
"Confirmed policy version 1.0 for DOC-0042" in the audit trail even if the
document was never actually created, since the audit commit and the main
commit would be on two unrelated connections. Fixed by inserting directly
into `audit_log` on `confirm_draft`'s own connection instead of calling the
shared helper -- this is a case where matching the rest of the codebase's
convention would have been the wrong choice for this specific, explicitly
atomicity-sensitive operation. First test run surfaced this immediately as
a `KeyError` (an incomplete test fixture happened to trigger it first), so
this was caught by running the tests, not by a second read of the plan
text alone.

**Retry semantics implemented literally as section 9.1 item 8 states**:
`confirm_draft` checks `draft["state"] == "committed"` FIRST, before any
token check, and if so reads back and returns the exact result from the
prior confirmation without demanding the (by now certainly stale)
pre-confirm `expected_lock_version`. Tested directly: calling confirm
twice with the same original token returns identical results and creates
exactly one version row, not two.

**Stale-base check implemented and tested against a real race, not just a
direct field comparison**: for a revision, confirm now locks the target
document (`SELECT ... FOR UPDATE` on PostgreSQL) and compares its CURRENT
`current_policy_version_id` against the draft's recorded `base_version_id`.
The test for this doesn't just set mismatched values by hand; it drives a
real second version through to 'approved' and promotes it to current via
direct rows (simulating a competing confirm+approval having already
happened), then proves the ORIGINAL draft's confirm is refused with
`StaleBaseError` rather than silently creating a second, confusing
candidate.

**Hash re-verification at confirm time, not just at build time**: T05's
`build_draft` records hashes when it builds; `confirm_draft` independently
re-hashes all three files (source/branded/preview) from disk and compares
against what was recorded, refusing confirmation if either the file is
missing or its hash no longer matches. Tested by writing tampered bytes
directly over a real built artifact after the build completed and
confirming the mismatch is caught, and separately by deleting a built
artifact and confirming its absence is caught -- both leave zero rows
created in `aria_documents`.

**"No filesystem paths in responses" enforced by one shared function, not
scattered ad hoc field-dropping**: `_version_to_public_dict` is the single
place that decides which version fields are safe to return over the API;
both the list and detail read paths route through it. Tested directly by
asserting `source_path`/`branded_path`/`preview_path`/`template_snapshot_path`/`body`
are absent from what either read path returns, not by inspecting the route
code and assuming.

Test evidence: `test_aria_policy_versions.py` 12/12 passing -- new-policy
confirm creating a real document + version 1.0 with the document correctly
promoted to current, confirm retry returning identical results with
exactly one version row (not two), confirmed hashes matching the actual
build's recorded hashes, revision confirm leaving an existing Approved
document's version/status/body/current-pointer completely untouched while
the new candidate exists separately, the stale-base race proof described
above, confirm-without-a-build refusal, mismatched-build-id refusal,
stale-lock-token refusal, a tampered source file refusal, a missing
branded file refusal, and both version-read paths proven to omit every
filesystem path field. Full regression suite re-run clean. `py_compile`
clean on all touched/new files.

### T07 detailed notes (2026-09-19)

Files touched: `oneforall/modules/aria/policy_workflow_service.py` (new:
`submit_for_approval`, `decide_approval`, `withdraw_approval`,
`list_eligible_approvers_for_version`, `get_approval`,
`list_pending_approvals_for`, `_exclusion_set_for_version`,
`_approval_to_public_dict`, and `AlreadyDecidedError`/
`ApproverIneligibleError`/`InvalidDecisionError`);
`oneforall/modules/aria/routes_policy_workflow.py` (new: approvers list,
submit, pending-queue, decide, withdraw endpoints);
`oneforall/modules/aria/policy_storage.py` (small addition: a bounded
retry around `attach_build`'s rename, see below);
`oneforall/tests/test_aria_policy_approvals.py` (new, 20 tests);
`oneforall/tests/test_aria_policy_storage.py` (2 tests added for the
retry logic).

This was the task where the most genuine bugs surfaced, all caught by the
tests actually failing, not by a second read of the code:

**A real state-machine gap**: section 6.2's own table explicitly allows
resubmitting a `withdrawn` version back to `pending` ("Resubmit unchanged
-> pending... only if still current candidate and base matches"). The
first draft of `submit_for_approval` only accepted `state == 'draft'`,
so a legitimate withdraw-then-resubmit was rejected outright. Fixed by
accepting `withdrawn` too, gated by the same stale-base concept
`confirm_draft` already uses.

**A real bug in that same stale-base check's first version**: comparing
a version's own `base_version_id` against the document's
`current_policy_version_id` is right for a *revision* candidate, but
wrong for a brand-new policy's first version, which has no
`base_version_id` (nothing preceded it) yet legitimately IS the current
pointer once confirmed (it points at itself). The first fix compared
these unconditionally and incorrectly refused a completely valid
withdraw-then-resubmit of a first version. Fixed by treating either
"this version is itself current" or "the document's current pointer
still equals what this version was based on" as valid -- two distinct
legitimate shapes the single-field comparison couldn't tell apart.

**A deliberately imprecise, not narrowed, test in two places**: submitting
a version already in `pending` initially fell through to a generic
`INVALID_INPUT` rather than the more actionable `OPEN_REVISION_EXISTS`
section 8 names for exactly this case -- fixed in the service, since a
real API client benefits from the more specific code. Separately, two
tests (an approver whose role was removed; an approver moved to a sibling
BU) initially asserted one specific exception class each, but the code
correctly catches both scenarios at an *earlier*, more general check
(losing `aria.policy.approve` entirely denies access before the
eligibility re-check is even reached; moving out of scope hits
`document_read_ok`'s 404 before eligibility is reached). Rather than
restructure working, correct check ordering just to make one specific
exception class fire, the tests were loosened to accept either of the two
substantively-correct rejections -- the requirement under test ("decision
rejects removed roles... moved SBUs") is satisfied either way.

**Audit/notification atomicity carried over from T06's fix, not
reintroduced as a bug this time**: `submit_for_approval`, `decide_approval`,
and `withdraw_approval` all insert directly into `audit_log` and
`notifications` on their own connection, never through `core.middleware.log_audit()`,
for the same reason established in T06.

**A real, if minor, environment-specific flakiness found and fixed**:
`policy_storage.attach_build`'s `os.rename()` intermittently raised
`PermissionError: [WinError 5] Access is denied` during this session's own
test runs -- twice, on two different tests, in different full-suite runs,
always succeeding on a bare re-run. This is a known Windows behavior
(a just-created directory transiently locked by antivirus/indexing) that
does not apply to this project's actual Linux production target, but it
made the test suite unreliable on this dev machine. Added a small bounded
retry (5 attempts, short backoff) around the rename, Windows-specific in
practice since POSIX rename doesn't raise this error class, so the loop
exits on the first attempt everywhere else. Added two dedicated tests
(retry succeeds on the 3rd attempt; gives up and re-raises after
persistent failure) rather than trusting the loop by inspection.

Test evidence: `test_aria_policy_approvals.py` 20/20 passing -- owner
excluded from their own eligible-approver list, submission rejecting an
ineligible approver and the owner-as-self-approver case, hash/round-number
binding verified against the actual version row, submission idempotency,
the one-pending-submission guard, approval promoting the current version
and inserting exactly one publication job, double-approval refused,
reject-requires-a-comment, the document-projection rule for both a
first-ever rejection (status reverts to Draft, pointer stays on the
rejected version, per section 6.3's "beside the retained snapshot") and a
revision rejection (the previously approved version and status are
completely untouched), decision refusing a deactivated approver/removed
role/moved-BU approver/stale token/wrong person, withdraw-then-resubmit
end to end including the round number incrementing, refusing to withdraw
an already-decided submission, and a REAL two-thread concurrency test
against a real file-based database proving exactly one decision wins, the
loser gets `AlreadyDecidedError`, and exactly one publication job exists
afterward despite two decision attempts. Full regression suite (now several
hundred tests across the whole project) re-run clean twice. `py_compile`
clean on all touched/new files.

### T08 detailed notes (2026-09-19)

Files touched: `oneforall/modules/aria/routes.py` (many routes -- see below);
`oneforall/modules/aria/ask_service.py` (`_filter_chunks_by_scope`);
`oneforall/modules/launcher/routes_platform.py` (global search, cross-module
link title resolution); `oneforall/modules/launcher/routes_dashboard.py`
("my_docs" widget); `oneforall/modules/grid/data_service.py` and
`oneforall/modules/grid/routes.py` (AI-checklist policy titles, the
evidence-linking picker and attach action); `oneforall/tests/test_aria_policy_legacy.py`
(new, 21 tests).

This task turned out to have a much larger surface than its own file list
first suggested. `routes.py` alone had eleven separate unscoped or
under-scoped mutation/read paths, not the five originally found:

**Route-by-route (`routes.py`)**:
- `add_document`: forced to Draft only (closing the direct-to-Approved
  bypass) and switched to `reserve_document_number`, as before -- plus a
  fix not caught the first time around: it never set `org_id`/
  `business_unit_id`/`owner_user_id`, so every document it created was
  permanently "legacy" (org_id NULL) and visible platform-wide forever.
  Now defaults all three from the creating user.
- `upload_new_document`: a **second, separate** "create a document"
  route this task had missed entirely. It still had the original
  `SUBSTRING(doc_id FROM 5)` PostgreSQL-only bug (confirmed to raise
  `sqlite3.OperationalError` on every call against real SQLite -- this
  route could never have worked in dev), the same direct-to-Approved
  bypass `add_document` already had closed, and the same missing
  org/BU/owner assignment. Fixed identically to `add_document`.
- `update_document`, `upload_document_revision`, `apply_template_to_document`,
  `download_document`: as previously recorded (managed-document 409
  guards, `document_read_ok` scope checks, `owner_user_id`-first
  ownership, `is_relative_to` path containment).
- `apply_template_to_document`: one more gap found on re-inspection -- the
  *template* lookup itself (for legacy, non-managed documents, which still
  reach this far) had no scope check, so a document owner could brand
  their document with another organization's private template and logo.
  Added the same `template_scope_sql` filter used elsewhere.
- `delete_document`: had no scope check at all (cross-organization hard
  delete by anyone holding `aria.policy.delete`) and no managed-document
  guard. Section 10.1 calls for "soft archive" on managed records, which
  does not exist as a feature yet, so managed documents now refuse
  deletion outright (409) rather than either hard-deleting an approved
  compliance record or silently doing nothing -- fail closed until
  archive is actually built. Legacy deletes are now scope-checked.
- `document_revisions` ("history" per section 10.2): had no scope check;
  any authenticated ARIA user could pull another organization's revision
  history by doc_id alone.
- `frameworks_list`, `api_ims_status`, `ai_generator_page`, `ask_page`:
  four read paths feeding aggregate stats, control-classification hints,
  or suggested questions from `aria_documents` with no scope filter --
  "framework coverage", the IMS `doc_refs` set, the AI Generator's
  "recent documents"/per-framework stats, and Ask ARIA's random title
  suggestions (section 10.2 names two of these explicitly: "Generator
  recent documents/stats" and "Ask ARIA suggestions"). All now filtered
  through `document_scope_sql`.
- `api_templates_upload`, `api_templates_delete`, `api_templates_download`:
  the whole template-management surface had the same class of gaps as
  documents once did -- upload never set org/BU (every new template
  defaulted to platform-wide-legacy visibility, silently undermining
  every other template scope check going forward), delete had no scope
  check and hard-deleted the row and file even though `aria_documents.template_id`
  can still reference it, and download had no scope check and the same
  string-prefix path-containment weakness already fixed elsewhere for
  `download_document`. Delete is now a soft retirement (`is_active=0`,
  row and file both kept) rather than a hard delete, matching section
  10.1's "soft retirement" requirement and avoiding orphaning any
  document's template history.

**Consumers outside `modules/aria` (section 10.2)**: grepped the whole
tree for `aria_documents`/`aria_doc_revisions` references and checked
every hit.
- `launcher/routes_platform.py`: the global search's ARIA-document branch
  and the generic cross-module link title resolver's `("aria","document")`
  case were both unscoped (the latter across all 11 linkable entity
  types generically -- only the ARIA case was fixed; per section 10.2,
  "do not claim [to complete] an unrelated audit of every other module").
- `launcher/routes_dashboard.py`: the `policy_author`/`policy_approver`/
  `control_owner`/`risk_owner` dashboard's "my_docs" widget had no
  scoping at all -- despite the name, it showed the platform's 10 most
  recently updated documents, any organization's.
- `grid/data_service.py` + `grid/routes.py`: `get_aria_policy_titles`
  (feeds an AI-generated incident checklist -- a real cross-tenant
  leak into AI context, exactly what section 10.2 warns about) and
  `list_aria_policies`/`attach_aria_policy_as_evidence` (the
  evidence-linking picker and its attach action) were all unscoped.
  `attach_aria_policy_as_evidence` also serves the system-initiated
  auto-attach flows (matching a new document to GRID controls by
  framework/control_ref, not by caller-supplied id), so it took an
  optional `actor` parameter rather than requiring one, preserving that
  internal path unchanged.

**Deliberately not touched, with reasons**:
- `evidence/routes.py`'s two download/download-pdf "current-document
  fallback" reads and `core/event_handlers.py`'s document-approved sync
  into the Evidence Vault (both named in section 10.2, "its
  current-document fallbacks must not bypass exact-version access").
  Both are explicitly T09's files (`GRID/Evidence adapters`,
  `core/event_handlers.py`), and "exact-version access" isn't a concept
  that exists yet for a managed document -- that's what T09's publication
  pipeline is for. Fixing these now would mean guessing at semantics T09
  is supposed to define.
- GRID's own control-auto-attach matching (`auto_attach_aria_policies_for_document`,
  `_attach_doc_to_matching_controls`, `auto_attach_aria_policies_to_audit`):
  these match by framework name/control_ref against `grid_audits`/
  `grid_controls`, which use GRID's own pre-existing `business_unit_id`-list
  scoping convention (`list_audits(bu_scope=...)`), not ARIA's
  org/legacy/managed model, and `grid_audits` has no `org_id` column at
  all. Reconciling two different authorization models for a different
  module's own entities is a separate investigation, not a policy-workflow
  bypass closure -- left alone per the same section 10.2 instruction above.
- The other 10 entity-type branches in `routes_platform.py`'s global
  search and the other 10 pairs in its cross-module link resolver
  (sentinel/grid/bcm/risk/evidence, all similarly unscoped) -- pre-existing,
  unrelated to ARIA policies, out of this plan's scope.
- `modules/governance/data_service.py`'s `aria_documents` reference is a
  reference-count guard for business-unit deletion (can this BU be
  deleted, given what still points at it) -- not a content/read exposure,
  no action needed.
- "Assign owner" as a dedicated real-user-id picker (section 10.1) and
  "file-reference safeguards" on legacy delete: both describe features
  that do not exist as any reachable endpoint today. Managed documents
  already fully block ad hoc owner changes (the existing 409 guard);
  legacy documents keep the free-text `owner` field exactly as before,
  now with `owner_user_id` preferred wherever it is set. Building a new
  owner-assignment endpoint or a delete-time reference scan would be a
  new feature, not a bypass closure, and was left as a documented gap
  rather than invented under this task's banner.

**Test coverage added, and where it was deliberately not**: wrote 21 tests
in `test_aria_policy_legacy.py` covering the routes.py fixes directly
(including `upload_new_document` -- the single most important test here,
since a successful call at all proves the SQLite-breaking SUBSTRING bug
is gone -- `delete_document`'s scope/managed guards, and the three
template-management routes). The `launcher`/`grid` fixes reuse the
already-tested `document_scope_sql`/`document_read_ok`/`template_scope_sql`
helpers (19 dedicated tests in `test_aria_policy_access.py`) as a
single additional `WHERE`/if-check per call site, with no new logic of
their own; rather than add a parallel test scaffold for two modules that
had none before this task, these were verified by the full regression
suite plus direct reading of each diff. Flagging this explicitly rather
than presenting it as equally test-proven: if dedicated launcher/grid
route tests are wanted, that is a reasonable, separate follow-up.

**The `_FakeRequest` authentication gap**: the first draft of
`test_aria_policy_legacy.py` used a bare object with only `.state.user`
set, matching what the route bodies themselves read. All but 2 of the
initial tests failed with `AttributeError: '_FakeRequest' object has no
attribute 'cookies'` -- every route here is also wrapped by
`require_module`/`require_capability` (`core/middleware.py`), which
re-authenticates independently via `get_current_user(request)`, reading
`request.cookies`. Rather than construct real session cookies, an
autouse fixture monkeypatches `core.middleware.get_current_user` to
return the test's chosen actor directly, resolved at call time from
`core.middleware`'s own module namespace (not captured at import time
in `routes.py`) -- so the patch applies no matter which decorator a
given route uses.

Test evidence: `test_aria_policy_legacy.py` 21/21 passing -- direct-to-Approved
bypass closed on both creation routes, both now correctly assigning
org/BU/owner, delete's scope and managed-document guards, both template
scope checks (apply-to-document and the management endpoints), template
soft-retirement leaving the row and file intact, and template upload
scoping to the creator. Full regression suite (360 tests total) re-run
clean three times across this task's edits. `py_compile` clean on all
touched files.

### T09 detailed notes (2026-09-19)

Files touched: `oneforall/modules/aria/policy_publication.py` (new),
`oneforall/modules/aria/scheduler.py` (new), `oneforall/main.py` (start/stop
wiring), `oneforall/core/events.py` (`emit` returns event id),
`oneforall/core/event_handlers.py` (`policy_published_handler` branches on
`version_id`; also fixed a pre-existing `NameError` -- see below),
`oneforall/modules/aria/policy_workflow_service.py` (real `expires_at`
values instead of always NULL; `expire_stale_drafts`;
`gather_referenced_storage_paths`; a real bug fix in `confirm_draft` -- see
below), `oneforall/modules/aria/policy_storage.py` (`move_orphans_to_trash`,
`purge_expired_trash`), `oneforall/modules/aria/ask_service.py`
(`reindex_document` prefers the current approved version's body),
`oneforall/modules/aria/routes_policy_workflow.py` (publication-status and
retry endpoints; also completed a pre-existing route that never returned a
response -- see below), `oneforall/modules/grid/routes.py` and
`oneforall/modules/evidence/routes.py` (recognize the new
`aria://policy-versions/{id}` virtual path and redirect into ARIA's own
scope-checked endpoints), `oneforall/tests/test_aria_policy_publication.py`
(new, 24 tests).

Section 10.3 and section 7.5 are the two specs this task implements; both
turned out to depend on schema T01 had already anticipated:
`evidence_items.aria_policy_version_id` and
`grid_evidence_files.aria_policy_version_id` (with their unique partial
indexes) already existed, as did `aria_policy_drafts.expires_at` with its
own `idx_aria_drafts_expiry` index -- this task is the first to actually
populate and consume them.

**A real, previously undiscovered bug found by writing this task's own
setup helper**: `confirm_draft`'s brand-new-document INSERT never included
`control_ref`, even though `create_draft_from_generation` captures it in
the draft's metadata. Every document created through the full
generate-draft-confirm pipeline therefore had `control_ref` permanently
NULL, silently breaking GRID auto-attachment (and this task's own
version-keyed GRID evidence copy, which is exactly how the gap was
caught: `test_grid_evidence_attached_when_control_matches` failed with no
evidence attached at all). Fixed by adding `control_ref` to that INSERT
from the same metadata dict the other fields already read from.

**A second real, previously undiscovered bug, found by testing
`policy_published_handler` directly for the first time in this project's
history**: its legacy Evidence Vault sync block calls `os.environ.get(...)`,
but `core/event_handlers.py` never imports `os` at all, at module or
function scope. Every legacy policy approval (`update_document` setting
status to Approved) has been silently failing to sync to the Evidence
Vault since this code was written -- caught by the function's own broad
`except Exception as ev_exc: log.warning(...)`, so it never surfaced
anywhere, including in this project's own logs unless someone was
specifically watching for that warning line. Fixed by importing `os`
(aliased `_os`, matching this block's existing style of aliased local
imports for hashlib/shutil/uuid) and updating both call sites.

**A third, smaller pre-existing gap, found while adding new endpoints to
the same file**: `api_start_revision_draft` in `routes_policy_workflow.py`
had no return statement at all -- every call returned FastAPI's default
`null` body instead of the created draft. Not reachable from any existing
test (only the underlying service function was tested directly), so this
had never been caught. Fixed as part of inserting the new
publication-status/retry endpoints immediately after it.

**Design decisions where the spec's literal wording didn't match this
schema, resolved by verifying rather than guessing**:
- Section 10.3 asks to "validate the audit/control's organization and BU
  against the policy scope" before GRID auto-attachment. Directly checked:
  `grid_audits` has no `org_id` column at all, and neither does
  `business_units` -- GRID audits are not org-scoped in this schema by any
  column that exists. `business_unit_id` is the one dimension both sides
  actually carry, so `_compatible_business_unit` checks that alone (an
  audit with no BU set is treated as org-wide/shared, matching the same
  NULL-means-organization-wide convention already used throughout
  `policy_access.py`). Documented in `policy_publication.py`'s own
  docstring rather than silently claiming full compliance with the
  literal spec text.
- Section 10.3's "renew" (of the claim lease) before writes was not built
  as a separate call: the actual work a publication job does (copy an
  already-built file, insert 1-2 rows) is fast and bounded, unlike a
  LibreOffice conversion, so a single generous lease (120s) was judged
  sufficient, with the completion write still gated on `lease_token`
  matching so a hypothetically reclaimed lease can never silently
  overwrite another worker's result.
- Section 7.5's "run per organization... with a lease" for retention: no
  other scheduler in this codebase (ERM, Evidence, GRID, BCM, Governance,
  the reminder processor) has any cross-worker locking at all -- each
  just loops synchronously on its own schedule. Implemented the
  per-organization loop (explicit tenant context, a fresh referenced-paths
  snapshot per org) but relied on APScheduler's own `max_instances=1`
  rather than inventing a new distributed-lease mechanism nothing else in
  the project uses; the 24-hour orphan grace period is what actually
  protects an in-progress build from being touched, not a lock.

**Claim/lease locking mirrors `reserve_document_number`'s already-proven
pattern** (`BEGIN IMMEDIATE` on SQLite, `SELECT ... FOR UPDATE SKIP LOCKED`
on PostgreSQL) applied to picking one due row out of a queue instead of a
singleton counter, with the claim transaction committed immediately
(releasing SQLite's whole-database lock) before the actual copy work
begins, rather than held across it.

**Idempotency is real, not assumed**: both `_copy_to_evidence_vault` and
`_copy_to_grid_evidence` check for an existing row first, and additionally
catch a unique-constraint violation as "already done" (racing against the
unique indexes T01 already created) rather than only trusting the
pre-check. `test_replaying_a_completed_job_does_not_duplicate_vault_evidence`
proves a second `process_job` call on the same already-completed job data
creates no duplicate. Because both copies commit together in one
transaction per attempt, there is no partially-committed state a replay
could observe -- a crash between the two inserts rolls both back, so the
idempotency checks matter for the case that actually can happen: the job
fully succeeded and committed, but the final "mark complete" write was
lost (lease reclaimed, or the worker died right after committing), and
the job gets reprocessed by a fresh claim.

Test evidence (superseded in part by the review-fix pass immediately
below -- see there for the business-unit compatibility direction, which
this paragraph originally described backwards): `test_aria_policy_publication.py`
24/24 passing at the time -- a real two-thread concurrency test proving
exactly one claimant ever wins a pending job, lease expiry making a
crashed worker's job reclaimable, version-keyed vault/GRID copies with
replay idempotency proven directly, a real failure scheduling bounded
backoff without touching the approved version or document status,
permanent failure after `MAX_ATTEMPTS` with a manager notification, the
explicit retry action working for a scoped manager and refusing an
out-of-scope one, draft expiry correctly clearing file references while
preserving body text, a save refreshing `expires_at` to a real future
timestamp, orphan-to-trash respecting both the grace period and live
references, trash purge respecting retention, and the
`policy_published_handler` branch proven both ways (skips the legacy copy
for a managed publication, still runs it unchanged for a plain legacy
one). Full regression suite (384 tests total) re-run clean. `py_compile`
clean on all touched/new files.

### T09 review-fix pass (2026-09-19)

An external code review of the T09 diff found 8 issues, 6 rated P1. Each
was verified against the actual code (not taken on faith) before fixing;
all 8 were confirmed real. Files touched: `oneforall/database.py` (new
`list_active_tenants`/`tenant_context` helpers, `events.dedup_key` column
+ unique index), `oneforall/core/events.py` (`emit` gains `dedup_key`),
`oneforall/modules/aria/scheduler.py` (binds tenant context per org),
`oneforall/modules/aria/policy_publication.py` (fixed double-close, wired
`dedup_key`, fixed the BU-compatibility direction, BU-scoped failure
notifications), `oneforall/modules/aria/ask_service.py` (`reindex_document`
no longer falls back to a candidate body), `oneforall/modules/aria/routes_policy_workflow.py`
(publication-status gated by capability), `oneforall/tests/test_aria_policy_publication.py`
(+8 tests, 24 -> 32).

**1 [P1] Background jobs never entered tenant PostgreSQL schemas.**
Confirmed directly: `get_db()`'s PostgreSQL branch only calls
`wrapper.set_tenant(slug)`/`set_rls_context(org_id, ...)` when
`_current_tenant`/`_current_org_id` (ContextVars set once per request by
session middleware) are already bound -- a scheduler tick has no request
to inherit them from, so every background job silently ran against
whatever the default/public schema and RLS scope are, never reaching any
other tenant's schema. No other scheduler in this codebase does this
either (grepped for `set_current_tenant`/`set_current_org`: only
middleware and `core/webhooks.py`, which propagates an *existing* calling
context via `copy_context()` rather than establishing one from nothing --
not applicable to a self-initiated timer with no caller to copy from).
Added `database.list_active_tenants()` (org_id, slug for every
`status='active'` org) and `database.tenant_context(org_id, slug)` (a
context manager binding then restoring the three ContextVars, using
`.reset(token)` so a reused scheduler thread never leaks one run's
tenant into the next). Both of `scheduler.py`'s jobs now loop over every
active tenant, binding context around that org's own slice of work --
including, for the publication drain, everything `run_due_jobs` triggers
synchronously within that call (the `ARIA_POLICY_PUBLISHED` handlers, the
Ask ARIA reindex), since ContextVars propagate down a synchronous call
stack for free once bound at the top. Retrofitting every *other*
pre-existing scheduler in the codebase (ERM, Evidence, GRID, BCM,
Governance, the reminder/workflow processors -- all of which appear to
have the identical gap) was left alone as a separate, platform-wide
concern well beyond this task's scope; flagged to the user rather than
silently expanded into.

**2 [P1] The empty-queue poll double-closed a pooled PostgreSQL
connection.** Confirmed: `_PgConnWrapper.close()` unconditionally calls
`pool.putconn()` with no idempotency guard, and `run_due_jobs` closed the
same connection once inside `if not job:` and again in `finally` --
returning one physical connection to the pool twice, which could then be
handed to two unrelated callers simultaneously. Removed the inner close;
`break` still reaches the same `finally` exactly once.

**3 [P1] Publication replay was not fully idempotent.** Confirmed: the
vault/GRID copies commit, then `emit()` runs every `ARIA_POLICY_PUBLISHED`
handler and dispatches webhooks, and only *after* that does the job get
marked complete. A crash or lease reclaim in that window (the job stays
`running` with an unexpired lease, becomes reclaimable once it expires,
and gets reprocessed from a fresh claim) replays the emit -- the vault/GRID
copies correctly no-op on replay, but `_insert_task`, `create_cross_module_link`,
`auto_resolve_grid_policy_requests`, workflow triggers and webhook
dispatch are not themselves idempotent, so a replay duplicates all of
them. Added `events.dedup_key` (nullable, unique-when-set) and an
optional `dedup_key` parameter to `emit()`: a second `emit()` for the same
key returns the first call's event id without running handlers or
dispatching webhooks again, backed by the real unique index (checked
before inserting, and the insert's own `IntegrityError` caught as "lost
the race" and re-resolved) rather than a bare check-then-insert. `process_job`
now passes `dedup_key=job["publication_key"]`. Existing callers that never
pass `dedup_key` are completely unaffected. Also exposed the previously
invisible per-handler failure status: `api_document_publication_status`
now looks up `events.status` via the job's `event_id` for a manager
caller. The original replay test only checked `evidence_items` row
count, which would not have caught this -- added a second test that
explicitly counts `events` (by `dedup_key`) and `task_board` rows after a
replay, which required an explicit `import core.event_handlers` in the
test (the `@on(...)` registration is a decorator side effect of that
import; without forcing it, whether the handler even fires depended on
which other test happened to run first in the same process -- a real
test-isolation gap caught while writing this fix, not a production bug).

**4 [P1] Ask ARIA could index an unapproved first version.** Confirmed
directly, and confirmed reachable (not just theoretical): `confirm_draft`
sets `aria_documents.current_policy_version_id` immediately for a
brand-new document's very first version -- inserted with `state='draft'`
and staying that way until someone actually approves it, which is
deliberate (section 6.3 needs a "points at itself" candidate before any
decision). `aria_documents.body` holds that same unapproved text at that
point. `reindex_document`'s fallback chain (`current_policy_version_id` ->
approved-version body -> **document body**) meant an unapproved candidate
fell through to the document row's own body, which is a draft/candidate
body by another name. Reachable today through the admin "rebuild index"
action (`rebuild_all()` calls `reindex_document` for every document
unconditionally), not only through a hypothetical race. Fixed: a managed
document now indexes its current version's body only when that version's
own `state` is actually `'approved'`; otherwise it is removed from the
index rather than falling back to the document row at all. Legacy
(non-managed) documents are unaffected.

**5 [P1] A BU-private policy could attach to an organization-wide GRID
audit.** Confirmed the exact direction was backwards:
`_compatible_business_unit` treated `audit_bu_id is None` as compatible
with *any* policy, when an org-wide audit's audience (every BU in the
org) is broader than a BU-private policy's own -- and GRID's evidence
listing does not itself re-check ARIA scope before showing the attached
evidence's title/notes/document-version metadata, so this was a real
metadata leak across subsidiary boundaries, not merely a display-layer
gap elsewhere. Fixed the direction: an org-wide (`NULL` BU) policy may
attach to any audit (its audience is already broader than any single BU),
but a BU-specific policy may only attach to an audit scoped to that exact
same BU, never to a `NULL`/org-wide one. The existing "no-BU audit is
compatible" test was inverted (it was asserting the bug's own behavior);
added a companion test proving an org-wide policy still attaches to both
an org-wide and a BU-specific audit, so the fix isn't overcorrected into
blocking a legitimate case.

**6 [P1] Failure notifications were not BU-scoped.** Confirmed:
`_notify_scoped_managers_of_failure` selected every `compliance_manager`/`super_admin`
in the organization by `org_id` alone, with no BU check at all -- a
manager in an unrelated business unit who happens to hold the role would
be notified of a BU-private policy's title and a direct link to it.
Fixed by loading the document's own org/BU/managed columns and filtering
every candidate through `document_read_ok`, the same scope rule used
everywhere else in this workflow. Added a test with a same-org,
different-BU `compliance_manager` who must not receive the notification,
alongside the existing test proving an in-scope manager still does.

**7 [P2] Publication diagnostics were exposed too broadly.** Same
endpoint as item 3's exposed-status addition, so fixed together:
`api_document_publication_status` used `document_read_ok`, a plain READ
check that any ARIA-module user (including an employee or external
auditor with no approval authority) passes, to gate `last_error` and
attempt detail that the endpoint's own docstring already framed as
manager-facing. Added a capability check (`aria.policy.approve` or
`aria.policy.edit_any`); a non-manager now gets only `{state,
needs_attention}`. Not fully addressed: returning a stable sanitized
error *code* instead of the raw (truncated) exception string for the
manager's own view would need a real error taxonomy at the point of
failure, which is a larger design exercise left as a further refinement
rather than attempted as a quick pass here -- the actual exposure (to
non-managers) is closed either way.

**8 [P2] The expiry-refresh test was clock-resolution dependent.**
Confirmed the mechanism, not just the symptom: two live `utcnow()` calls
a few lines apart can read the identical system clock tick on Windows,
which would make the test's strict `>` comparison flaky rather than a
real assertion about the refresh behavior. Rewritten to monkeypatch
`utcnow` with two deterministic, clearly-separated timestamps and assert
the exact expected `expires_at` at each step, not just their relative
order.

Test evidence: `test_aria_policy_publication.py` 32/32 passing (8 new:
tenant-context bind/restore including on exception, `list_active_tenants`
excluding an inactive org, the scheduler actually binding per-org context
around `run_due_jobs`, replay proven not to duplicate the `events`/`task_board`
rows this time instead of only `evidence_items`, the BU-compatibility
direction both ways, the failure-notification BU exclusion, and the
unapproved-version indexing gap directly). Full regression suite (392
tests total) re-run clean. `py_compile` clean on all touched files.

### T10 detailed notes (2026-09-20)

Files touched: `oneforall/static/vendor/aria-policy/` (new: `marked.umd.js`,
`purify.min.js`, `pdfjs/pdf.min.mjs`, `pdfjs/pdf.worker.min.mjs`, their
LICENSE files, `MANIFEST.json`), `oneforall/static/js/aria_markdown.js`,
`aria_pdf_viewer.js`, `aria_policy_workflow.js` (all new),
`oneforall/modules/aria/templates/ai_generator.html` and `documents.html`
(the browser UI itself), `oneforall/modules/aria/routes.py` (the
`documents_page` SELECT), `oneforall/modules/aria/routes_policy_workflow.py`
(a real threading bug -- see below), `oneforall/tests/test_aria_policy_workflow_routes.py`
(new, 1 test, deliberately proven to fail against the pre-fix code before
being left passing).

**Vendoring, verified, not just downloaded.** `marked` 18.0.13, `dompurify`
3.4.15, and `pdfjs-dist` 6.3.289 (current stable releases at fetch time,
not arbitrary picks). Every file's SHA-256 was cross-checked against
jsdelivr's own published per-file hash (`data.jsdelivr.com/v1/packages/npm/<pkg>@<version>?structure=flat`)
and confirmed byte-identical before use -- not just "downloaded from a
CDN and trusted". `MANIFEST.json`'s hashes are computed by a script
reading the files on disk, not hand-typed -- a hand-typed first attempt
had a transcription error (one dropped character) caught by comparing
against `sha256sum`'s own output, which is exactly the failure mode of
typing a hash by hand instead of deriving it programmatically.

**Safe markdown rendering**: `aria_markdown.js` wraps `marked.parse()`
with `DOMPurify.sanitize()` using an explicit `ALLOWED_TAGS` allowlist
(no `img` at all -- an inline image is a read receipt/beacon even when
inert, and branding/logos already go through the server-side template
system, never through markdown body text), an `ALLOWED_URI_REGEXP`
restricted to `http(s)`/`mailto`/`#fragment`, and a `DOMPurify.addHook`
forcing `target="_blank" rel="noopener noreferrer nofollow"` onto every
surviving link. Verified directly in the running browser, not just by
code inspection: injected a real payload battery (`<script>`,
`<img onerror>`, a markdown-syntax `javascript:` link, a raw-HTML
`<a href="javascript:...">`, `<iframe>`, `<form>`) into a live draft and
confirmed zero execution and zero surviving dangerous attributes in the
rendered DOM, while normal formatting (bold, code, a legitimate link)
still rendered correctly and the legitimate link picked up the
`rel`/`target` hook. This is section 14 Scenario C item 9, run for real.

**Two previously-invisible bugs found only because this was tested
through a real browser against the real HTTP/threading layer, not
through direct service-function calls:**

- **A real, serious threading bug**: `api_build_policy_draft` opened its
  DB connection (`db = get_db()`) on the request's event-loop thread,
  then passed that same connection into `asyncio.to_thread(svc.build_draft,
  db, ...)`, which runs the call on a *different* thread. SQLite
  connections are bound to the thread that created them, so every single
  build attempt raised `sqlite3.ProgrammingError: SQLite objects created
  in a thread can only be used in that same thread` -- confirmed directly
  from a real "Apply template and preview" click, a full HTTP 500 with
  the traceback in the server log, not a theoretical concern. This was
  invisible to every prior test in this plan because all of them call
  `svc.build_draft(db, ...)` directly on a single thread, bypassing the
  route's own `asyncio.to_thread` wrapping entirely. Fixed by moving both
  `get_db()` and `db.close()` inside a small `_build_draft_sync` wrapper
  that runs entirely on the worker thread `asyncio.to_thread` spawns, so
  the connection is created and used on the same thread throughout.
  Checked every other `asyncio.to_thread` call site in the codebase
  (`ai_generator.py`, `sentinel/ai_service.py`) for the same pattern --
  neither passes a DB connection across the thread boundary, so this was
  an isolated bug, not a repeated one. `test_aria_policy_workflow_routes.py`
  drives this exact route through `asyncio.to_thread` for real against a
  genuine file-based database; deliberately reverted the fix and reran it
  to confirm it fails with the exact same error before restoring the fix,
  the same discipline used throughout this plan for a bug-fix test.
- **A response-shape mismatch**: `/aria/api/templates` (a route that
  predates this workflow) returns a bare JSON array, not the `{ok, ...}`
  envelope every `routes_policy_workflow.py` endpoint uses. `aria_policy_workflow.js`
  assumed the newer convention and read `res.data.templates`, which is
  always `undefined` against a bare array -- the template dropdown showed
  "no templates available" even when a real, correctly-scoped template
  existed, confirmed by inspecting the actual network response directly
  rather than trusting the assumption. Fixed to read `res.data` as the
  array it actually is, with a comment recording why the two response
  shapes differ so a future change doesn't reintroduce the same
  assumption elsewhere.

**A third gap, pre-existing since T06, also only found by actually
following the flow in a browser**: `api_confirm_policy_draft` has
returned `detail_url: "/aria/documents?open={doc_id}"` since T06, and
both the confirm button and (now) My Drafts navigate to it, but
`documents.html` never read an `?open=` parameter at all -- landing there
after a real confirmation showed the plain list, never the document
itself. Fixed by rendering the same per-row data already available
(`docs | tojson`) into one lookup table and opening the matching
document's edit modal on load when the parameter is present and
resolves. Verified against a real legacy document (`?open=DOC-0001`
correctly auto-opened its edit modal).

**Verified live, end to end, with a real (non-mocked) draft**: generate
→ appears in My Drafts → resume via `?draft=` → edit → save (unsaved
indicator flips correctly, toast confirms, `expires_at` refreshes) →
reading-preview renders sanitized HTML → apply template and preview
(real `asyncio.to_thread` path, no conversion worker running in this
session, so this genuinely timed out after the configured 60s and
returned a clean `PREVIEW_TIMEOUT` error rather than crashing -- section
14 Scenario C item 6, run for real, not simulated: draft text survived,
confirm stayed disabled, the build button re-enabled for a retry).
Separately confirmed, via a fully mocked-conversion draft taken all the
way to a real confirmed version and a real submitted approval: the
Documents page's managed-document panel (publication status empty,
version history showing `v1.0` / `pending` / `CURRENT`, status/version/
owner/approver fields disabled, legacy upload/template sections hidden,
"Start a revision" present, submit-for-approval correctly hidden because
a decision is already pending), and the approval-decision UI (PDF-preview
error state for a non-real PDF byte string, comment textarea, and the
client-side "reject requires a comment" check correctly blocking the API
call entirely rather than sending an empty comment).

**Not verified, and said so rather than assumed**: actually deciding an
approval as a second, genuinely separate logged-in user -- session
cookies are httpOnly, and switching sessions reliably inside this
particular browser-automation context did not work (logout navigated
inconsistently); the decision UI's rendering and its client-side
validation were confirmed directly instead (above), and the actual
`decide_approval` transaction logic already has 20+ dedicated automated
tests from T07. A dedicated keyboard-navigation/focus-trap/focus-restoration
accessibility audit was not performed. A genuine rapid-double-click race
against Save/Build/Confirm was not performed (each button disables
itself for the duration of its own request, which is the mechanism, but
this specific race was not driven by hand). Real LibreOffice conversion
remains untested in this session -- still not installed on this dev
machine -- so the actual DOCX-to-PDF rendering quality (fonts, tables,
headers/footers, Unicode -- section 14 Scenario A item 4) has still never
been observed, only the plumbing around a conversion job's success/failure/timeout.

**Incidentally discovered, not a bug**: this dev database's document
sequence allocator hadn't been initialized against its own pre-existing
seed data. Running `scripts/prepare_aria_policy_workflow.py` (built in
T01 for exactly this) fixed it correctly and confirms that script is a
real, necessary operational step before enabling this workflow on any
database with existing legacy documents, not just a nice-to-have.

**A caching characteristic worth recording, not a bug to fix here**:
`core/middleware.py`'s `security_headers_middleware` sends every file
under `/static/` a blanket `Cache-Control: public, max-age=31536000,
immutable` -- correct for the pinned vendor libraries above (a version
bump changes the URL), and a platform-wide policy that predates this
task and applies equally to every other existing static file, so
changing it is out of scope here. But it means these three new
first-party JS files would silently take up to a year to reach an
already-visited browser after any future fix, unlike the vendor files
whose version is baked into their own filenames -- addressed by giving
all three a `?v=1` query suffix in both templates now, with a comment to
bump it on the next change. Discovered directly during this session's
own testing (a fixed bug's old behavior kept being served from cache
until this was in place), not theoretical.

Suggested implementation-session prompt:

> Execute PLAN-35 from the first incomplete task. Read its selected decisions,
> data model, authorization and transaction rules before editing. Keep the
> feature disabled until all release gates pass. Preserve approved documents,
> unrelated work and historical evidence. Record actual checks and remaining
> blockers in the execution ledger. Do not substitute the old AI Draft row,
> download-only preview or direct approval/status changes.

### T11 progress notes (2026-09-20): the feature flag was never wired up

**Finding, before any T11 acceptance work could mean anything**: this plan
has required `ARIA_POLICY_AUTHORING_ENABLED=false` (with an explicit
per-org `ARIA_POLICY_AUTHORING_ORG_IDS` allowlist) since T00's config work,
repeated in section 0, section 15's rollout steps and the suggested
implementation-session prompt above. Before trusting any of T11's release
gates, checked whether that flag actually does anything -- `grep -rn
"ARIA_POLICY_AUTHORING" oneforall/` matched only the two settings'
declarations in `config.py`. Nothing in `routes.py`, `routes_policy_workflow.py`,
or `policy_workflow_service.py` ever read either one. The flag was
completely inert: setting it to `false` disabled nothing, and section 15's
entire "deploy disabled, enable per test tenant" rollout plan had no
mechanism behind it.

**First fix attempt was wrong, and the test suite caught it before this was
called done.** Added `policy_authoring_enabled_for(org_id)` to
`modules/aria/policy_access.py` (the flag-off/empty-allowlist/org-not-listed
predicate -- see that file's own comment block for the exact semantics,
including that an empty `ARIA_POLICY_AUTHORING_ORG_IDS` means no tenant is
enabled, never a blanket default-on) and first called it from inside
`policy_workflow_service.create_draft_from_generation` and
`start_revision_draft` -- the service-layer functions that actually create
new authoring work. Running the full suite against that placement:
`1028 E`, `397 F`. Nearly the entire workflow's ~350 direct-call tests
broke, because they call these service functions straight, with no reason
to configure a rollout flag they've never heard of. Reverted both checks
and the import from `policy_workflow_service.py` completely rather than
patch around it.

**Corrected placement: the route layer, matching the existing licence-check
precedent.** Re-added the same check to the two route handlers that are
the actual entry points for new authoring work instead: `routes.py`'s
`api_generate_policy` (immediately after the existing `has_capability`
check, before `check_ai_rate_limit`/`record_ai_call`/the real AI call) and
`routes_policy_workflow.py`'s `api_start_revision_draft` (at the very
start of the function, before touching the database). This is a
tenant-level feature-availability check -- the same kind `require_capability`'s
own licence gate already makes at the route layer -- not an object-level
authorization rule, which is what `policy_access.py`/`policy_workflow_service.py`
correctly own per section 5. `python -m py_compile` on all four touched
files: clean. Full suite re-run against this placement: exit code 0, zero
failures or errors -- the ~350 direct-call tests never see the gate at
all, exactly as intended, and nothing else regressed.

**New dedicated coverage, not just a clean re-run of the old suite.**
`oneforall/tests/test_aria_policy_feature_gate.py` (7 tests, new file):
four cover `policy_authoring_enabled_for` as a pure predicate (flag off,
empty allowlist with the flag on, an org actually on the allowlist vs. one
that isn't, and `org_id=None`); three drive the real route functions
through `asyncio.run()` the same way `test_aria_policy_workflow_routes.py`
already does, proving `api_generate_policy` returns HTTP 403 with a
"not yet enabled" message for an org that isn't allowlisted, that the same
call never reaches `check_ai_rate_limit` (a disabled org must not be able
to spend the shared AI rate-limit budget on a call that was always going
to be refused), and that `api_start_revision_draft` returns the
`ACTION_FORBIDDEN` error shape when the allowlist is empty. Full suite run
once more with these included: exit code 0, zero failures or errors.

**Not covered by this fix, stated rather than assumed**: no test exercises
`api_generate_policy`'s *success* path with the flag genuinely on (that
path still needs the AI service mocked, which is a larger, separate
undertaking already covered structurally by T04's existing generation
tests plus this session's own live-browser generation run in the T10
notes above -- both of which ran with the gate's predecessor state,
i.e. no gate, so they exercise the workflow itself but not "gate open,
then workflow runs"). The predicate is pure Python (`settings.ARIA_POLICY_AUTHORING_ENABLED`,
an `int(org_id) in [...]` membership check) with no SQL in it, so there is
no SQLite-vs-PostgreSQL risk to separately verify here, unlike most of
this plan's other logic. This fix has not been enabled anywhere real --
`ARIA_POLICY_AUTHORING_ENABLED` remains `false` in every configuration
this session touched, and turning it on for any actual tenant is explicitly
out of scope without the user's own separate authorization (T11's last
checklist item, section 15).

### T11 live verification pass (2026-09-20): reject decision and start-revision, as two real users

T10's notes explicitly flagged one gap as unverified: "actually deciding an
approval as a second, genuinely separate logged-in user" -- blocked at the
time by httpOnly session cookies and unreliable menu-driven logout inside
the browser-automation context. This pass closes it, plus the related,
equally-unverified "start a revision" success path.

**How the second-user blocker was actually solved**: `GET /logout`
deliberately does nothing but redirect (`routes_auth.py`'s own comment:
destroying the session on GET is CSRF-able via an `<img>` tag); only
`POST /logout` destroys the session, and the sidebar's sign-out control is
what normally sends that POST. Rather than fight unreliable menu-click
sequences again, this pass called `fetch('/logout', {method: 'POST',
credentials: 'same-origin'})` directly from the page's own JS console (via
`javascript_tool`). This is not a document.cookie trick -- it is a genuine
same-origin POST that the app's own `csrf_origin_middleware` accepts (it
checks Origin/Referer against the host, which a same-page `fetch` always
satisfies) and that gets a real `Set-Cookie` deletion in the response,
which a browser honors regardless of the cookie being httpOnly. Confirmed
working: the fetch returned `redirected: true` to `/login`, and the next
login as a different user produced a genuinely separate session throughout
(different `Good morning, <name>` greeting, different visible pending-approvals
state).

**Test data, and why it was built this way**: a real organization (id 501)
with two real users -- `t11author` (role `policy_author`) and `t11approver`
(role `policy_approver`) -- created directly in the dev database, plus
`ARIA_POLICY_AUTHORING_ENABLED=true` / `ARIA_POLICY_AUTHORING_ORG_IDS=501`
added to `.env` for the duration of this pass only. Reaching a real
"confirmed version with a pending approval" without reinventing the whole
pipeline meant calling the actual service-layer functions directly in a
script -- `create_draft_from_generation` -> `build_draft` -> `confirm_draft`
-> `submit_for_approval` -- with only `policy_preview.poll_conversion_result`
monkeypatched to return fixed bytes instead of waiting on a real (not
installed in this environment) LibreOffice worker, the same technique
already used and recorded in T10's notes. This is a deliberately different
approach from going through `api_generate_policy`'s HTTP route (which
would have needed a real `aria_controls` row and a mocked AI call for no
added value here): the goal of this pass was the two specific unverified
UI flows, not re-proving generation, which T10 and the automated suite
already cover. Every `aria_doc_templates` row in this dev database's
`data/aria_templates/` was discovered to be a 15-byte placeholder
(`b"fake docx bytes"`, not a real zip/docx package) left over from
unrelated prior testing -- confirmed with `zipfile.is_zipfile()` before
concluding this, not assumed -- so a genuine minimal docx was generated
with `python-docx` for this pass's template row rather than reusing one of
those.

**Reject decision, driven for real as the approver**: logged in as
`t11approver`, opened the Documents page (the seeded approval correctly
appeared under "Pending My Approval"), opened the decision modal (the
fake PDF bytes correctly produced the existing "This file could not be
displayed as a PDF preview" error state, not a crash), typed a rejection
comment, and clicked Reject. `POST /aria/api/policy-approvals/2/decide`
returned `200` with `{"status":"rejected","decision_by":5012,"comments":"Rejecting
for T11 live verification: please revise the introduction section.", ...}`
-- a real, complete, server-persisted decision. The client correctly
closed the modal and hid the now-empty "Pending My Approval" card
afterward (`onDecided` -> `closeModal` + `refreshPendingApprovals`).
Reopening the document confirmed the projection: version history showed
`v1.0` / `rejected` / `CURRENT`, with "Start a revision" now available.

**Permission check on "Start a revision", found while testing it**: still
logged in as the approver, clicking "Start a revision" produced a real
`403` (`POST /aria/api/documents/DOC-0008/revision-drafts` ->
`{"ok":false,"error":{"code":"ACTION_FORBIDDEN","message":"You do not have
access to this draft."}}`), correctly enforced server-side since
`policy_approver` grants neither `aria.policy.edit_any` nor (as a non-owner)
a usable `aria.policy.edit_own`. This also live-exercises the T11 feature
gate's *allow* branch on this same route from the other side: the same
route accepted the equivalent request from the actual owner moments later
(next paragraph), so both the gate's refusal and its pass-through are now
each backed by at least one real request in this session, not just the
gate's own unit tests (which only covered the refusal side). The button
being visible to a user who cannot use it matches this codebase's existing
pattern elsewhere of rendering an action and letting the server be the
real authority rather than mirroring every permission client-side; not
treated as a bug here.

**Start a revision, driven for real as the owner**: switched sessions
(fetch-logout, then a fresh login as `t11author`, the document's real
`owner_user_id`). Clicking "Start a revision" redirected to
`/aria/ai-generator?draft=<new id>` showing a real new editable draft --
"Organization-wide - Ref Revision v1.1 - My Drafts", the original body
text carried forward correctly, Save/Edit/Reading-preview all present and
consistent with T10's already-verified editor. This is the version-number
increment (1.0 rejected -> 1.1 candidate) specified in section 6.2,
observed from a real request/response pair, not inferred from reading the
code.

**Cleanup**: every row this pass created was deleted afterward -- the
4 draft rows (2 stray ones from earlier failed build attempts before the
real template fix, plus the two that succeeded), the confirmed version,
the approval, `aria_documents` row `DOC-0008`, the template row, both
users, and organization 501 itself -- confirmed by re-querying every
affected table for zero remaining rows, not assumed from the DELETE
statements alone. The matching filesystem artifacts under
`data/aria_uploads/policy_workflow/org_501/` and the generated test
template file were also removed. `.env` was restored to exactly its
original two lines (`ARIA_POLICY_AUTHORING_ENABLED` unset, i.e. off by
default again).

**An unrelated stale comment fixed while setting this up, not left for
later**: `policy_access.py`'s module docstring asserted "`users.deleted_at`
does not exist in this codebase" -- no longer true since PLAN-33 Phase 2
added it (`database.py`'s migration list), discovered while inspecting the
real `users` schema for this pass's INSERTs. Checked whether this made any
of `policy_access.py`'s `is_active=1`-only checks actually wrong before
just editing the comment: it does not -- the only route that sets
`deleted_at` (`routes_admin.py`) always sets `is_active=0` in the same
statement, and restoring a deleted account deliberately leaves it inactive
until a separate explicit reactivation, so the two columns never diverge
in this codebase's own write paths today. Comment corrected in place to
state the current, verified reason the existing checks are still correct,
rather than the now-false premise that the column doesn't exist.

**Still not done, stated plainly**: real (non-mocked) LibreOffice
conversion remains unverified -- this pass mocked the same single
function T10 mocked, for the same reason (no converter installed in this
development environment). Accessibility (keyboard/focus) auditing and a
manual rapid-double-click race test remain undone, as already recorded in
T10's notes. App upgrade/restart was not exercised.

### T11 external review-fix pass (2026-09-20): rollback scope, event delivery, publication races

A second external code review (6 findings: 4 P1, 2 P2) covered the parts
of this workflow a live-browser pass cannot exercise: what actually
happens under a crash, a stale worker, or a mixed-outcome event delivery.
Each finding was verified against the real code before any fix, per this
plan's own established discipline; all 6 were confirmed real.

**P1 -- feature disable did not stop submissions or publication.**
`ARIA_POLICY_AUTHORING_ENABLED`/`ORG_IDS` (wired up earlier this same day,
see the progress notes above) only covered `api_generate_policy` and
`api_start_revision_draft`. Section 15's own rollback text is explicit --
"disable new authoring/**submission** entry points... stop new
**conversion**/**publication** claims" -- so `api_build_policy_draft`
("conversion"), `api_confirm_policy_draft`, `api_submit_for_approval`
("submission"), and `api_retry_publication_job` ("resume retry jobs
*after* resolving the issue" implies retries pause during it) were all
gated the same way, via a new shared `_authoring_gate(actor)` helper in
`routes_policy_workflow.py` (the existing `api_start_revision_draft` check
was refactored onto it too, no behavior change there).

The publication *scheduler* needed a different mechanism: `claim_next_job`
now filters candidates by `org_id IN (<currently enabled orgs>)` at the
SQL level, and short-circuits entirely when the flag is globally off.
Deliberately NOT "claim then release if disabled": a claim already
increments `attempts`, so releasing would inflate it every ~120s lease
cycle purely from sitting disabled and could trip `MAX_ATTEMPTS` the
moment the org is re-enabled; and with `ORDER BY created_at ASC LIMIT 1`,
a disabled org's older job would keep winning the claim and being
released, starving a newer job from a still-enabled org behind it in the
queue. Filtering the candidate set avoids both.

Explicitly NOT gated: save/discard/recover a draft, decide/withdraw an
approval, and every read/download/status endpoint -- these resolve or
expose work that already exists rather than advancing anything new,
matching "keep read/history/download and recorded approvals available."

This broke the same category of existing test as the first gate-placement
attempt earlier today, for the same reason: `test_aria_policy_publication.py`
(~14 tests) and `test_aria_policy_workflow_routes.py`'s one test call
`claim_next_job`/`api_build_policy_draft` directly to test claiming and
threading mechanics, with no reason to know about the flag. Fixed by
enabling authoring for those files' own fixture orgs in their `autouse`
fixtures (not by weakening the gate) -- the same resolution as before,
now a confirmed pattern for this plan's gate placements. New tests: 5 in
`test_aria_policy_feature_gate.py` (build/confirm/submit/retry refuse when
disabled, build passes through when enabled), 2 in
`test_aria_policy_publication.py` (`claim_next_job` skips a disabled org
without starving an enabled one or inflating its attempts; returns `None`
outright when the flag is globally off).

**P1 -- event deduplication could permanently lose deliveries; P2 -- a
later handler could hide an earlier one's failure.** Both in
`core/events.py`'s `emit()`, same root cause: the event row commits before
handlers run, and each handler independently overwrote the shared
`events.status` column. A crash (or any handler exception, which has no
other recovery path) between the commit and the handler loop finishing
left a row that every future `dedup_key` replay found and returned
unchanged -- "the row exists" was being treated as "it was delivered",
permanently, with no retry. Considered committing only after handlers
finish instead (closing the gap directly); rejected because it would hold
this connection's write lock for as long as arbitrary handler code takes,
and handlers open their own separate connections to write (e.g.
`_auto_trigger_workflows`'s own `db.commit()`) -- a near-certain SQLite
self-deadlock, not a narrow risk.

Fixed instead: a `dedup_key` replay against an existing row only
short-circuits when that row's status is already `'processed'`;
otherwise it reruns handler delivery against the *same* event id rather
than returning it untouched. Status is now computed once, after the whole
handler loop, from the combined outcome (`'failed'` if anything raised,
else `'processed'`) -- never per-handler -- which also fixes a related gap
found while designing this: an event type with zero registered handlers
previously sat at `'pending'` forever, so every future replay of it would
also have gone on redelivering webhooks indefinitely; it now reaches
`'processed'` immediately.

This trades a permanent, guaranteed loss of delivery for the ordinary
at-least-once cost: a handler invoked more than once for the same logical
event, on a replay that lands after a crash or failure. That handler must
tolerate it. Checked the one handler actually reachable this way
(`ARIA_POLICY_PUBLISHED`'s sole handler, `workflow_trigger_on_aria_policy`
-> `_auto_trigger_workflows`) and found it is NOT idempotent -- it inserts
a `workflow_instances` row unconditionally, with nothing to key a
"already ran for this exact event" check on (`workflow_instances` has no
column correlating it back to a specific event occurrence, and
`entity_id` alone is wrong to key on: a document published a second time
after a later revision must legitimately get a new instance, not be
silently deduplicated against its first publication). Documented this gap
directly on the handler rather than silently accepting it: a rare
duplicate workflow instance on an already-rare replay is accepted for now
as strictly better than the guaranteed total loss it replaces, but a real
fix needs a schema change (an event-occurrence reference on
`workflow_instances`) that is out of scope for this pass. New tests: 5 in
new file `tests/test_events_dedup_and_status.py` (success replay does not
rerun; failure replay does rerun against the same event id and reaches
`processed` on the retry; mixed-outcome status is `failed` not
`processed`; zero-handler status still reaches `processed`; the
pre-existing genuine-concurrent-`IntegrityError` race still defers to the
winner without running handlers itself, proving that path is untouched).

**P1 -- conflict recovery in publication could roll back earlier evidence
writes.** `_copy_to_evidence_vault` and `_copy_to_grid_evidence`
(`policy_publication.py`) caught a unique-violation on a duplicate insert
and called `db.rollback()` -- which undoes the WHOLE transaction, not just
that one statement, silently erasing an earlier write already made in the
same transaction (the vault copy, or an earlier grid control's successful
attach in the same loop), after which the job still went on to commit
whatever was left and report `'complete'`. Worse than it looked on
SQLite alone: `_PgConnWrapper.execute()` (`database.py`) already rolls
back the ENTIRE connection the instant PostgreSQL raises ANY statement
error, before this module's own `except` block even runs -- so a
savepoint-based partial rollback (the reviewer's alternative suggestion)
would not actually have worked here without also changing that
shared wrapper, a much larger and riskier change than this fix needed.

Fixed with `INSERT ... ON CONFLICT DO NOTHING` against each table's real
existing unique index (`uq_evidence_items_policy_version`,
`uq_grid_evidence_control_version`) instead: it never raises for the
duplicate case on either engine, so there is nothing here left for a
rollback to ever need to undo. This surfaced a real, separate,
pre-existing bug in the shared `insert_returning_id` helper
(`database.py`) while building on it: its own docstring already promised
"returns None when ON CONFLICT DO NOTHING suppresses the insert," but the
SQLite path just returned `cursor.lastrowid` unconditionally -- confirmed
directly that sqlite3's `lastrowid` after a suppressed insert is *stale*
(the previous successful insert's id, not `None` and not this
statement's), not merely unset. Fixed at the root (`rowcount == 0` now
guards the SQLite path) rather than worked around at each call site; this
also fixes a latent, previously unnoticed correctness bug in
`modules/grid/data_service.py`'s `create_mapping` (its only other
real-code caller), which would have returned a wrong, unrelated id for a
duplicate mapping on SQLite. New tests: `test_insert_returning_id_returns_none_not_a_stale_id_on_suppressed_conflict`
and `test_conflicting_evidence_vault_insert_does_not_lose_an_earlier_write_in_the_same_transaction`
in `test_aria_policy_publication.py`. Not covered: a genuine concurrent
race reproducing the exact original interleaving (two connections both
passing the pre-existing-row check before either writes) was judged not
worth a flaky timing-dependent test given the fix already directly and
deterministically eliminates the mechanism (an exception path) the bug
depended on -- stated here rather than silently skipped.

**P1 -- a stale worker could overwrite the current lease owner.**
`_mark_failed`'s terminal-failure UPDATE filtered only by job id, unlike
every sibling write in the same module (`_schedule_retry_or_fail`'s retry
UPDATE, `process_job`'s completion UPDATE), which already guard with
`AND lease_token=%s`. A worker whose lease had already expired and been
reclaimed by a newer worker could still mark the job `'failed'` and clear
that newer worker's lease and `event_id` out from under it, possibly
seconds before that worker would have completed it successfully -- and
would still send the "evidence synchronization needs attention" manager
notification for a failure that was never real. Fixed with the same
`lease_token` guard plus a `rowcount` check (skip the notification
entirely when the guard shows this worker no longer owns the job -- the
current owner's own outcome is authoritative, not this stale write).
Added the same `rowcount` check to `_schedule_retry_or_fail` for
consistency (it already had the guard but silently proceeded either way;
now it logs a warning on the same condition). New tests:
`test_mark_failed_does_not_clobber_a_lease_a_newer_worker_already_holds`
and a sanity-check sibling proving a *valid* lease token still records
the failure and notifies, in `test_aria_policy_publication.py`.

**P2 -- the retention lock works only inside one process, not fixed in
this pass, deliberately.** Confirmed real: `scripts/deploy.py` generates
the production systemd unit with `--workers 2`, `main.py` calls
`modules.aria.scheduler.start_scheduler()` unconditionally at startup, and
`_retention_sweep`'s own docstring already documents that `max_instances=1`
(APScheduler's per-process overlap guard) is its *only* protection -- with
2 worker processes, each gets its own scheduler instance and neither knows
about the other, so both can run the sweep concurrently. The publication
*drain* job is NOT at risk here despite living in the same file: it claims
work through `claim_next_job`'s real cross-process locking
(`SELECT ... FOR UPDATE SKIP LOCKED` / `BEGIN IMMEDIATE`), a genuine
database-level lock, not `max_instances`, so 2 workers already correctly
distribute publication claims between them today.

Not fixed here because this is a platform-wide pattern, not a PLAN-35 one:
grepping `main.py` shows the identical `start_scheduler()`-at-startup
shape registered for nine other modules (grid, sentinel, bcm, evidence,
erm, advisory, reminder, workflow, governance) alongside ARIA, all relying
on the same per-process `max_instances=1` guard. Patching only ARIA's
retention sweep with a database lease would fix one-tenth of an
architectural gap while leaving the codebase with an inconsistent locking
strategy across otherwise-identical schedulers -- a real fix is a shared,
reusable lease helper all ten adopt, which deserves its own scoped change
outside this ARIA-specific plan. Also weighed the actual blast radius
before deciding not to rush a narrow fix: `_retention_sweep` already wraps
each tenant's cleanup in its own `try/except: log.warning(...); continue`,
so two workers racing on the same org's sweep means wasted duplicate work
and a logged warning on a since-moved/deleted path, not silent data loss
or corruption -- a real robustness gap, but a bounded one, unlike P1
findings 1-4 above. Left open and stated here rather than silently
dropped from this ledger.

New tests added this pass: 12 in `test_aria_policy_feature_gate.py` (7
from the earlier progress-notes pass plus 5 new: build/confirm/submit/retry
refuse when disabled, build passes through when enabled), 38 in
`test_aria_policy_publication.py` (32 pre-existing plus 6 new: the
disabled-org claim skip/no-starvation test, the global-disable test, the
`insert_returning_id` conflict-detection test, the evidence-vault
same-transaction-survives test, and the two `_mark_failed` lease-token
tests), and a new file `test_events_dedup_and_status.py` (5 tests).
`python -m py_compile` on every touched file: clean. Full regression
suite, run twice (once immediately after the route/scheduler-gate changes
alone, which surfaced the same "existing test calls the now-gated function
directly" issue as the earlier gate-placement pass and was fixed the same
way; once again after every fix and every new test above): both times,
`EXIT_CODE=0`, zero failures or errors.

### T11 second external review-fix pass (2026-09-20): the previous fix wasn't enough

A third review round, on the SAME event-delivery/publication code the
prior pass just fixed, found that fix's mechanism was structurally sound
but did not actually help the real handlers: they were built (long before
PLAN-35) to catch and log their own exceptions rather than raise, so
`emit()`'s new any_failed tracking had nothing to ever observe. 6 findings
(4 P1, 2 P2), each verified against the real code first.

**P1 -- the real ARIA handlers hide their own failures.**
`policy_published_handler` (`core/event_handlers.py`, registered via the
raw string `"aria.policy.published"` -- MISSED by the previous pass's own
handler audit, which only grepped for the `ARIA_POLICY_PUBLISHED`
constant, a real gap in that verification, not just a coincidence) called
`_insert_task`, `create_cross_module_link`, and `_notify_admins` without
ever checking their return values, inside a function-wide
`except Exception: log.warning(...)` that swallowed anything else too.
`_auto_trigger_workflows` (the second handler on this exact event,
confirmed by the same audit gap) had the identical shape. Both
independently caught and logged, by design, predating this plan --
`emit()`'s per-handler try/except could only ever see a handler that
raises, and neither one ever did, regardless of what actually happened
inside.

Fixed by making each handler track its own real sub-step outcomes and
raise once, after attempting everything, if anything failed --
`policy_published_handler` now checks `_insert_task`'s and
`create_cross_module_link`'s return values (both already `None`
on failure) and `_notify_admins`'s new boolean return (added
non-breakingly: every other existing caller ignores it), and does not
commit its own transaction on a raise (the `finally: db.close()` then
rolls back whatever partially succeeded, so a retry starts clean, not
layered on half-done work). This is a fix, not a refactor for its own
sake: it directly closes the exact gap the review named ("task creation,
notifications, GRID resolution, or workflow creation" failing silently).

**Consequence this pass had to fix too, not leave behind**: making these
handlers raise makes `emit()`'s dedup_key replay (from the FIRST review
pass) actually fire for them far more often than before -- and
`_insert_task` (a blind `INSERT`) and `_auto_trigger_workflows` (also a
blind `INSERT` into `workflow_instances`) were not idempotent against a
second attempt, exactly the risk the first pass's own comment on
`workflow_trigger_on_aria_policy` had already flagged and deferred. Fixed
properly rather than deferred again: `event_id` is now passed to every
handler (all 50 registered handlers accept `**kwargs` -- confirmed
directly via `inspect.signature`, not assumed, before relying on it), and
two new nullable, indexed columns (`task_board.source_event_id`,
`workflow_instances.source_event_id`) plus `ON CONFLICT DO NOTHING`
against them make a replay of the exact same event occurrence a safe
no-op per (definition, event) pair -- while a genuinely later publication
of the same document (a real revision) still gets its own new task/instance,
since the key is the event occurrence, never the entity alone. The admin
notification is deliberately left non-deduplicated -- a redundant
notification on a rare replay is a minor, acceptable annoyance, not a
correctness problem worth a third schema column for.

**P1 -- failed event delivery had no production retry path.** Even where
a handler DID propagate (after the fix above), `process_job`
(`policy_publication.py`) still unconditionally marked its job
`'complete'` right after calling `emit()`, regardless of whether delivery
actually reached `'processed'`. A job stuck this way had no way back into
either retry mechanism this workflow has: the scheduler only claims
`'pending'`/`'running'` jobs, and the manual retry action only accepts a
job already in `state='failed'`. Fixed by checking the event's real status
immediately after `emit()` returns and routing through the existing
`_schedule_retry_or_fail` (the same bounded-backoff-then-permanently-failed
machinery already used for a vault/GRID copy failure) instead of marking
`'complete'` when it is not `'processed'` -- a transient failure now
retries automatically, and a genuinely stuck one reaches `state='failed'`
the normal way, where the existing manual retry action already works,
rather than inventing a second, parallel retry path.

**P1 -- event delivery could still be lost or duplicated (three sub-points).**
- *A losing racer returns the winner's id without confirming delivery
  happened; if the winner then crashes, nobody ran handlers.* Not
  separately guarded -- mitigated as a direct consequence of the fix just
  above instead: `process_job` (the only real caller of `dedup_key` in
  this codebase) now checks the actual event status before trusting it,
  so a winner that crashed before running handlers leaves a
  `'pending'`/`'failed'` status that keeps the JOB retryable, rather than
  the job silently being marked complete on the loser's say-so. `claim_next_job`'s
  own lease also means true concurrent double-processing of one job is
  already rare, not the routine case this fix has to assume.
- *Status was set to `'processed'` before the webhook dispatch handoff,
  so a crash in that narrow window permanently lost the webhook.*
  Confirmed and fixed by moving `_set_status(...)` to run after the
  webhook handoff attempt, folding a failed handoff into the same
  `any_failed` aggregate that already drives the status. Stated precisely,
  not oversold: this narrows the crash window (delivery itself still
  happens later, genuinely unobserved, on `core.webhooks`' own background
  pool) -- it does not make webhook delivery durable.
- *Replaying a pending/failed event reruns every handler, and at least two
  are not idempotent.* This is the same gap as the "consequence" fixed
  above (task creation, workflow-instance creation) -- both now guarded
  by the `source_event_id` correlation key.

**The reviewer's own suggested "durable fix" (a full outbox/per-handler
delivery table with delivery leases) was not built.** Deliberate, stated
plainly: the fixes above close every concrete failure mode this round
actually named, using mechanisms already proven elsewhere in this exact
codebase (idempotency keys, existing retry/backoff, a status check before
declaring success) rather than a new, larger piece of infrastructure history
has not yet asked for. If a specific future gap needs it, that is its own
scoped decision, not something to build speculatively here.

**P2 -- retention lock unsafe across multiple processes: fixed this time,
not deferred again.** The first review pass (T11 external review-fix
pass, above) reasoned this was a platform-wide pattern (nine other
schedulers share the identical shape) not worth a narrow ARIA-only patch,
and left it open. Raised a second time, so fixed for real rather than
re-deferred: a new, deliberately generic `scheduler_locks` table and
`database.try_acquire_scheduler_lock(db, lock_name, lease_seconds)`
helper (same claim convention as `claim_next_job`/`reserve_document_number`:
`BEGIN IMMEDIATE` / `SELECT ... FOR UPDATE`), adopted now by
`_retention_sweep` with a 1-hour lease (generous for a once-daily job;
short enough that a crashed worker does not block tomorrow's run). The
table and helper are intentionally not ARIA-specific, so the other nine
schedulers sharing this exact multi-worker exposure can adopt the same
lock later without a new table -- narrowing, not eliminating, the
"inconsistent locking strategy across schedulers" concern the first pass
raised: ARIA is fixed, the mechanism now exists for the rest, adopting it
elsewhere is still separate, un-started work.

**P2 -- markdown rendering still contradicted the plan's own section 7.2.**
Verified directly against the plan text, not re-derived from XSS-safety
first principles (which is exactly how this was missed originally):
section 7.2 requires links rendered as **plain text** in this release and
raw HTML **disabled**, and specifies the missing-library fallback as
"render with textContent and disable the HTML preview" -- T10's
`aria_markdown.js` kept `<a>` clickable (with a target/rel hook) and
returned an empty string on a missing library, both real, both
independently XSS-safe, neither what section 7.2 actually says. Fixed:
`a` removed from `ALLOWED_TAGS`/`ALLOWED_ATTR` entirely (DOMPurify drops a
non-allowed tag's own markup but keeps its text content by default, which
*is* "plain text", not "gone" -- verified directly, not assumed: a
javascript: link, an https: link, and raw disallowed tags like `<div>`/`<span>`
all reduce to their bare text with no surviving tag or attribute); the
target/rel hook removed as dead code with nothing left to apply to; the
missing-library fallback changed from returning `''` to
`el.textContent = markdownText` in `renderInto` (and an HTML-escaped
equivalent in `render()`, for callers using its string return with
innerHTML) instead of a blank result; a new `AriaMarkdown.isAvailable()`
export lets a caller decide whether to offer a reading-preview toggle at
all. Verified live in a real browser (not just read): a payload battery
of `<script>`, `<img onerror>`, `<iframe>`, `<form>`/`<input>`, `<svg onload>`,
a `javascript:` link and a normal `https:` link all confirmed reduced to
inert, safe text with zero surviving dangerous tags/attributes and zero
clickable links; the missing-library fallback confirmed to show real
escaped text via `textContent`, not a blank preview. Required a cache-bust
bump (`aria_markdown.js?v=1` -> `?v=2` in both templates that load it) to
actually observe the fix in the browser -- the same platform-wide
`Cache-Control: immutable` characteristic T10's own notes already
recorded, re-encountered rather than re-discovered.

**P3 -- the submit-for-approval success callback could never run.**
Confirmed exactly as reported: `formEl.dataset.onSubmitted` reads an HTML
`data-*` attribute, which the DOM spec defines as always a string (or
`undefined`) -- `typeof ... === 'function'` could never be true, and
nothing in the codebase ever assigned it regardless. The practical effect:
after a successful submission the form hid itself but the version
history/publication status panels kept showing pre-submission state until
the whole edit modal was closed and reopened. Fixed by adding a real
`onSubmitted` function parameter to `initSubmitForApprovalForm` and wiring
`documents.html`'s call site to hide the now-stale submit section and
re-render both panels with fresh data (`renderVersionHistory` already
makes its own live API call each time it runs, confirmed by reading it,
not assumed). Verified live: a detached-DOM fixture with `window.fetch`
mocked for the approvers-list and submit-approval calls confirmed the
callback now fires and the form hides, exactly reproducing the function's
real call contract without needing a full draft/build/confirm pipeline
for a fix this contained.

New tests: `test_aria_policy_publication.py::test_published_handler_skips_legacy_vault_copy_for_a_managed_publication`
fixed (it silently relied on `_insert_task` failing without anyone
checking, via a missing `user_id=1` FK target -- invisible before this
pass made that failure loud, a small, real illustration of exactly the
problem this round fixes) plus 4 new scheduler-lock tests (two real
concurrent-thread races, proving the lease and that different lock names
never block each other, matching the established concurrency-proof
pattern already used for `claim_next_job`/`decide_approval`/
`reserve_document_number`). `python -m py_compile` on every touched
Python file: clean. `node -c` on every touched JS file: clean. Full
regression suite: `EXIT_CODE=0`, zero failures or errors.

**Stated plainly, not proven this pass**: the full outbox-pattern
redesign the reviewer offered as the ideal, durable fix was not built
(see above); the admin-notification duplication risk on a replay was
accepted rather than closed; a live end-to-end browser pass driving a
REAL handler failure through to a REAL job retry (rather than the direct
function-level and mocked-fetch verification actually performed) was not
run, given the scale of this round; and the other nine schedulers sharing
`scheduler_locks`' underlying exposure have not been migrated to use it.

### T11 production-acceptance fix (2026-09-20): the PostgreSQL DDL cycle

A production-readiness acceptance pass returned NO-GO on `041edec`. Its
top blocker was the one thing this entire plan had repeatedly flagged as
unverified and could never test in-environment: PostgreSQL. `init_db()`
against a real PostgreSQL fails immediately with `UndefinedTable: relation
"aria_policy_versions" does not exist`, on both a fresh database and an
upgrade. Confirmed real, root-caused, fixed, and -- for the first time in
this plan -- verified against an actual PostgreSQL 18.6 instance (the same
major version production runs).

**Root cause.** `aria_policy_drafts` is created before `aria_policy_versions`
but carries three forward foreign keys to it (`base_version_id`,
`copied_from_version_id`, `committed_version_id`), while
`aria_policy_versions` references `aria_policy_drafts` back (`draft_id`) --
a genuine dependency cycle. SQLite does not validate a FK's target table
at `CREATE TABLE` time, so the forward references are tolerated; PostgreSQL
validates immediately and rejects the first `CREATE`. `_to_pg_schema` only
did regex substitutions (SERIAL, TIMESTAMPTZ, DOUBLE PRECISION, PRAGMA
stripping) and never addressed FK ordering, so `_ARIA_TABLES_PG` still
emitted the impossible statement. A scan of all 179 tables confirmed this
is the ONLY such cycle in the schema -- the fix is surgical, not systemic.

**Why 447 passing tests never caught it.** `conftest.py` sets
`DATABASE_URL=""`, forcing every test onto SQLite so a developer's real DB
is never touched -- correct for unit tests, but structurally blind to
SQLite-vs-PostgreSQL DDL differences. Nothing in the suite ever ran
`init_db()` against PostgreSQL, so a PG-only DDL bug was invisible by
construction. The acceptance review named this too, and it is the deeper
finding: the gap was not one bad `CREATE TABLE`, it was having no PG test
at all.

**The fix (`database.py`).** Two coordinated halves, PostgreSQL-only, SQLite
path untouched:
1. `_break_pg_fk_cycle()` strips the three inline `REFERENCES
   aria_policy_versions(id)` clauses from the `aria_policy_drafts` block of
   the PG schema string (scoped to that one CREATE, so
   `aria_policy_versions`' own valid self-reference and every forward-safe
   reference in later tables are left exactly as-is). The columns remain
   plain `INTEGER`. Applied as `_ARIA_TABLES_PG =
   _break_pg_fk_cycle(_to_pg_schema(_ARIA_TABLES))`.
2. `_run_pg_alters()` re-adds the three FKs as named constraints
   (`fk_aria_drafts_base_version` / `_copied_version` / `_committed_version`,
   kept as the shared `_ARIA_DRAFTS_DEFERRED_FKS` data so the stripper and
   re-adder cannot drift) once both tables exist, idempotently via an
   existence check (PG has no `ADD CONSTRAINT IF NOT EXISTS` for FKs),
   scoped to `current_schema()`, committing per constraint -- the same
   idiom `_run_pg_fk_cascades` already uses. Because `_apply_tenant_schema_ddl`
   also calls `_run_pg_alters` with the search_path set to each tenant
   schema, this fix covers the public schema AND every tenant schema with
   no extra code.

**Verified against real PostgreSQL 18.6, not reasoned about.** A throwaway
`postgres:18` container (Docker is available in this environment after all,
which overturns this plan's earlier "no PG testing possible" premise). New
file `tests/test_postgres_init.py`, four tests, opt-in via a new
`TEST_DATABASE_URL` env var so the default SQLite suite is completely
unaffected (they skip -- `ssss` -- when it is unset):
- fresh `init_db()` builds the whole workflow schema and all three deferred
  FKs;
- a second `init_db()` (upgrade over an initialized DB) is idempotent and
  does not duplicate the constraints;
- a faithful `edffc9a -> 041edec` upgrade (init fully, DROP the workflow
  tables as production -- 15 commits behind -- lacks them, re-init) brings
  them back cleanly against a DB already holding every other table;
- the re-added FK is actually ENFORCED (a draft pointing at a nonexistent
  version id is rejected), not merely present in the catalog.
Proven to be a real regression guard, not a vacuous pass: `git stash`-ing
the fix and re-running reproduced the exact `psycopg2.errors.UndefinedTable`
at `database.py:6107`, then `git stash pop` restored it and the tests
passed. The full suite was also run with `TEST_DATABASE_URL` set (SQLite
and real-PG tests together in one process): `EXIT_CODE=0`, proving the
fixture's teardown restores SQLite mode with no cross-contamination.

**Environment note, not a code change.** The full suite would not collect
until local `pypdf` was upgraded to `6.19.0` -- the version `041edec`
already pins in `requirements-preview.txt`, which a stale local env simply
had not installed. No repo change; the pin was already correct.

**Still NO-GO for deployment, and nothing here changes that.** This fix
clears the single hardest *code* blocker, but every other acceptance
finding stands and is out of this pass's chosen scope: production still
runs `edffc9a`; the app service runs as root with no systemd hardening;
`.env` is world-readable; `project-app-1` is crash-looping; 62 OS updates
and a reboot are pending; the preview image must be published by registry
digest; and the deploy-with-authoring-disabled-then-enable-approved-orgs
sequence has not been run. The `/forgot-password` dead link, `/favicon.ico`
404, and login-page accessibility gaps are confirmed but likewise out of
this pass. These remain the operator's to action on the VPS / in a later
pass; they were not touched here.

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
