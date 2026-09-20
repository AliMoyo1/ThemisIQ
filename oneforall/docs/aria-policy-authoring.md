# ARIA in-app policy authoring: operator guide

Status as of 2026-09-20: built (PLAN-35 T00-T10), verification in progress
(T11). **`ARIA_POLICY_AUTHORING_ENABLED` must remain `false` in every real
deployment until the "Known limitations" section below is resolved or
explicitly accepted, and until enabling it is separately authorized** --
see `plans/PLAN-35-aria-policy-authoring-flow.md` section 15 for the full
release-acceptance checklist this guide supports.

This document is for whoever operates the app (deploys it, sets its
environment, watches its logs), not for policy authors. It assumes you can
already read `plans/PLAN-35-aria-policy-authoring-flow.md`; it does not
repeat that plan's design rationale, only the parts an operator needs.

## 1. What this feature is

Replaces the old "AI generates a policy, it lands directly as a document"
path with a full authoring workflow: generate or upload into an editable
draft, build a real DOCX/PDF preview, confirm into an immutable version,
route it for approval, publish the approved version into the Evidence
Vault/GRID. None of this is reachable by any organization until the
feature flag below is turned on for it.

## 2. Feature flags

| Setting | Default | Meaning |
|---|---|---|
| `ARIA_POLICY_AUTHORING_ENABLED` | `false` | Master switch. Accepts `1`/`true`/`yes`/`on` (case-insensitive); anything else is off. |
| `ARIA_POLICY_AUTHORING_ORG_IDS` | empty | Comma-separated organization IDs allowed to use the workflow, e.g. `ARIA_POLICY_AUTHORING_ORG_IDS=4,7`. **An empty list means no tenant is enabled, even if the master switch is on** -- this is an explicit per-org allowlist, never a blanket default-on. |

Both are read by `policy_authoring_enabled_for(org_id)` in
`modules/aria/policy_access.py`, which gates every route that advances a
draft/version toward publication: `POST /aria/generate-policy`
(`routes.py:api_generate_policy`), and in `routes_policy_workflow.py`,
`api_start_revision_draft`, `api_build_policy_draft`,
`api_confirm_policy_draft`, `api_submit_for_approval`, and
`api_retry_publication_job` (the last four share one `_authoring_gate(actor)`
helper). A disabled org gets a `403` with a message telling the user to
contact their administrator, before any AI call or database write
happens. Reading an existing draft/document, saving draft text,
discarding/recovering a draft, and deciding/withdrawing an already-submitted
approval are never gated -- disabling authoring stops new work from
advancing, it does not strand work already in flight.

The background publication scheduler (`modules/aria/scheduler.py`,
`policy_publication.claim_next_job`) respects the same setting: it will
not claim a job belonging to a currently-disabled org, filtered at the
database query level so a disabled org's older job can never block a
still-enabled org's newer one from being claimed. Re-enabling an org makes
its queued jobs claimable again automatically, with no separate "resume"
action needed.

**Operator-relevant history**: these two settings existed since the
project's earliest work on this feature but were not actually read
anywhere in the code until 2026-09-20 -- setting `ARIA_POLICY_AUTHORING_ENABLED=false`
did not, in fact, disable anything before that date. A first fix that same
day only covered generation and starting a revision; a same-day follow-up
review found it still let an already-open draft be built, confirmed,
submitted for approval, and published while "disabled," which is the
scope now described above. If this application has been running with an
earlier build of this feature, its authoring and submission endpoints
were reachable regardless of this setting. `plans/PLAN-35-aria-policy-authoring-flow.md`'s
"T11 progress notes" and "T11 external review-fix pass" sections have the
full account.

To pilot with one organization: set both variables, restart the app, and
confirm with a real login from a user in that organization and a second
user in a different (or no) organization -- the second user should see the
draft/generate entry points refuse with the "not yet enabled" message.

## 3. Other settings

| Setting | Default | Purpose |
|---|---|---|
| `ARIA_POLICY_PREVIEW_SPOOL_DIR` | `<app>/data/aria_preview_spool` | Shared exchange directory with the DOCX-to-PDF converter worker. App-side only; the worker's own executable path is its own container's setting, never the app's. |
| `ARIA_POLICY_PREVIEW_TIMEOUT_SECONDS` | `60` | How long the app waits for a preview conversion before returning a `PREVIEW_TIMEOUT` error. The draft is never lost on timeout; the user can retry the build. |
| `ARIA_POLICY_DRAFT_EXPIRY_DAYS` | `30` | Days of draft inactivity before it's marked expired. A save resets the clock. |
| `ARIA_POLICY_ORPHAN_GRACE_HOURS` | `24` | Hours an unreferenced staging/artifact directory waits before being moved to trash. |
| `ARIA_POLICY_TRASH_RETENTION_DAYS` | `7` | Days a trashed directory is kept before permanent deletion. |

All four numeric settings fail app startup with a clear `RuntimeError` if
set to zero or negative (`config.py:_validate_aria_policy_workflow_settings`)
rather than surfacing as a confusing failure later inside a build or
cleanup job.

## 4. Background jobs

`modules/aria/scheduler.py` registers two jobs at app startup,
unconditionally -- they are always registered, whether or not any
organization has the feature enabled:

1. **Publication queue drain**, every 60 seconds. Claims and processes due
   `aria_policy_publication_jobs` rows: copies an approved version into
   the Evidence Vault/GRID and emits `ARIA_POLICY_PUBLISHED`.
2. **Retention sweep**, daily at 02:00 UTC. Expires inactive drafts past
   `ARIA_POLICY_DRAFT_EXPIRY_DAYS`, moves orphaned staging/artifact
   directories to trash past `ARIA_POLICY_ORPHAN_GRACE_HOURS`, and
   permanently deletes trash past `ARIA_POLICY_TRASH_RETENTION_DAYS`. Runs
   per organization with its own referenced-paths snapshot, so one
   organization's cleanup never touches another's live files.

Both jobs are safe no-ops for an organization with nothing in the
workflow yet -- registration is not gated behind the feature flag, only
the ability to *create* new drafts/versions is. This is intentional: it
lets the retention sweep keep working even while the feature is off for
everyone, so nothing accumulates unbounded before a pilot begins.

## 5. Dependencies

- **Vendored browser libraries** (`oneforall/static/vendor/aria-policy/`):
  `marked` 18.0.13 (markdown parsing), `dompurify` 3.4.15 (sanitization --
  the actual XSS defense; `marked` alone does not sanitize), `pdfjs-dist`
  6.3.289 (in-browser PDF preview). Pinned, checksummed against jsdelivr's
  own published per-file hashes, and recorded in that directory's
  `MANIFEST.json`. Do not point these script tags at a CDN; a CDN-hosted
  unpinned copy of `marked` is exactly the stored-XSS exposure this
  vendoring replaced.
- **LibreOffice conversion worker**: a separate, sandboxed container the
  app talks to only through the shared spool directory -- never installed
  into the main app image or invoked directly by app code. Full deployment
  contract (image build, capabilities, resource limits, update procedure)
  is `plans/PLAN-35-aria-policy-authoring-flow.md` section 7.6. This
  worker has never been installed or exercised in this development
  environment -- see "Known limitations" below.

## 6. Storage layout and retained files

Everything lives under `ARIA_UPLOAD_DIR/policy_workflow/<org_id>/`
(`modules/aria/policy_storage.py`). Every path stored in the database is
relative to `ARIA_UPLOAD_DIR` and re-validated to stay inside it on every
read (`resolve_stored_path` refuses an absolute path or a `..` segment).

- Confirmed policy versions' DOCX/PDF bytes are permanent records, never
  touched by the retention sweep.
- Draft bodies are kept (not hard-deleted) when a draft expires, so an
  expired draft can still be recovered/inspected; only its file references
  are cleared.
- Orphaned staging directories move to a trash subtree before permanent
  deletion, giving a recovery window (`ARIA_POLICY_ORPHAN_GRACE_HOURS` +
  `ARIA_POLICY_TRASH_RETENTION_DAYS` total).
- The cleanup job supports a dry-run mode (counts and IDs only, no policy
  content) -- use it before trusting a retention change on a real database.

## 7. Operational scripts

- **`scripts/prepare_aria_policy_workflow.py`** -- run this against any
  database that has pre-existing `aria_documents` rows *before* enabling
  the workflow for that organization. Dry-run by default: reports which
  legacy rows can be unambiguously mapped to an org/owner/version, and
  initializes `aria_document_number_sequence` from the highest existing
  `DOC-<digits>` suffix so new allocations can't collide with un-sequenced
  legacy numbers. `--apply-org-id N` assigns organization `N` to clean
  NULL-org rows; it refuses if more than one organization exists in the
  database, since the correct assignment is then genuinely ambiguous, not
  a default. It does not backfill legacy version rows -- that adoption is
  intentionally lazy, per document, at first revision or submission.
- **`scripts/aria_policy_preview_worker.py`** -- the conversion worker
  entry point referenced by the section 7.6 deployment contract.

## 8. Repair and retry: publication failures

`GET /aria/api/documents/{doc_id}/publication-status` reports whether a
document's current approved version finished publishing:

- Any user with read access to the document sees `{state, needs_attention}` --
  `needs_attention` is `true` only when the job's state is `failed`.
- A user who can also approve or edit-any (`aria.policy.approve` /
  `aria.policy.edit_any`) additionally sees `attempts`, `last_error`, and
  `event_handler_status` (a publication job can be `complete` while a
  downstream event handler still failed independently -- this surfaces
  that too). This split is deliberate: ARIA module access alone is enough
  to pass the read check, so internal error text is withheld from anyone
  who isn't actually a scoped manager.

To repair a failed publication: `POST /aria/api/publication-jobs/{job_id}/retry`
(`policy_publication.retry_now`), available to the same manager
capabilities. This does not re-run approval; it only retries the
copy-into-evidence step for an already-approved version.

## 9. Known limitations as of 2026-09-20

Stated explicitly rather than assumed proven -- do not enable this feature
against any real tenant on the strength of automated tests alone:

- **No PostgreSQL testing was possible in this development environment**
  (no PG instance available). Every automated test in this plan has run
  against SQLite only. This matters: this exact workflow has already
  produced one real SQLite-vs-thread bug that ~350 passing direct-call
  tests could not catch (see T10 notes), so "tests pass on SQLite" is not
  by itself evidence the workflow behaves identically on PostgreSQL.
  Dedicated PG acceptance testing is a prerequisite for production
  enablement, not an optional extra.
- **Real LibreOffice conversion has never been observed.** The worker has
  never been installed in this environment; only the plumbing around a
  conversion job's success/failure/timeout has been exercised (a
  build against a non-running converter times out cleanly and returns
  `PREVIEW_TIMEOUT` without crashing or losing draft content). Actual
  rendering quality -- fonts, tables, headers/footers, Unicode, page
  breaks -- is unverified.
- ~~The approval-decision UI was verified only against a fully
  mocked-conversion draft, never a second, genuinely separate logged-in
  approver.~~ **Resolved 2026-09-20**: a real second-user reject decision
  and a real "start a revision" pass are now both verified live (a same-origin
  `fetch('/logout', {method:'POST'})` reliably switches sessions despite
  httpOnly cookies, where menu-driven logout previously did not). See
  `plans/PLAN-35-aria-policy-authoring-flow.md`'s "T11 live verification
  pass" notes. Still not observed live: the *approve* path specifically
  (only *reject* was driven end-to-end) and a same-document second
  approval round after a revision.
- **No dedicated accessibility audit** (keyboard navigation, focus traps,
  focus restoration after modals) has been performed on the new editor,
  approval, or publication-status UI.
- **No manual rapid-double-click race test** was performed against
  Save/Build/Confirm, though each button disables itself for the duration
  of its own in-flight request, which is the intended mechanism.
- **The `ARIA_POLICY_PUBLISHED` workflow-auto-trigger handler is not
  idempotent against a replay.** `core/events.py`'s event delivery now
  correctly retries a handler that failed or never finished (see the "T11
  external review-fix pass" notes), but the one handler on this path
  today (`workflow_trigger_on_aria_policy` -> `_auto_trigger_workflows`)
  unconditionally creates a new `workflow_instances` row with nothing to
  recognize its own earlier attempt by. In the narrow case where that
  handler already succeeded once but the event's overall status was never
  recorded (a crash, or a later step failing), a replay can create a
  second workflow instance for the same publication. Accepted as strictly
  better than the alternative it replaced (a guaranteed, silent, permanent
  loss of that handler's delivery on the same crash) rather than fixed --
  a real fix needs a schema change so `workflow_instances` can identify
  which event occurrence created it.
- **The retention sweep can run concurrently on a multi-worker deployment.**
  The production systemd unit runs `--workers 2`; each worker's own
  APScheduler instance only guards against overlapping *itself*, not the
  other worker. This is a platform-wide pattern (nine other module
  schedulers share the identical shape), not specific to this feature, and
  its actual failure mode is bounded -- a caught-and-logged warning on a
  path the other worker already moved or deleted, not data loss -- but it
  was not fixed as part of this plan. The publication drain job is
  unaffected: it claims work through a real database-level lock, not
  APScheduler's per-process guard.

## 10. Before enabling in a real deployment

1. Resolve or explicitly accept every item in section 9 above.
2. Confirm `plans/PLAN-35-aria-policy-authoring-flow.md` section 15's
   release-acceptance checklist is satisfied.
3. Get explicit authorization for the specific organization(s) being
   enabled -- this is not a decision this guide or any automated process
   makes on its own.
4. Run `scripts/prepare_aria_policy_workflow.py` against the target
   database first if it has any pre-existing `aria_documents` rows.
5. Set `ARIA_POLICY_AUTHORING_ENABLED=true` and
   `ARIA_POLICY_AUTHORING_ORG_IDS` to the authorized org ID(s) only, then
   restart the app.
