# Evidence Vault guided upload and version safety

## Scope

Build the next Evidence Vault slice from plan 02 on the existing artifact chain. A specialist can select one permitted claim while uploading a file; the file row and pending review link succeed or fail together. The selected claim supplies the file's business unit when the claim has one. A new version must replace a visible current version, and version history returns only versions the viewer may open.

## Sequence

1. Add focused regressions for scoped target selection, atomic upload and link, invalid replacement, and hidden versions.
2. Validate target, owner, replacement and file metadata before writing bytes. Roll back rows and remove bytes on a failed upload.
3. Add a guided target picker to the upload dialog using the existing scoped entity search.
4. Show current version and history clearly, run focused backend and browser checks, and record remaining extraction and 500-item work.

## Boundaries

- A link starts pending. Upload does not accept a claim or evidence on behalf of a reviewer.
- No new artifact family table or legal freshness rule is introduced in this slice.
- Keep the current list and saved views. Do not move or delete existing files.
- Real PostgreSQL migration checks and the live specialist pilot follow the completed build.

## Progress

- 2026-10-18: Proved the missing target fields, invalid replacement handling and hidden version leak with five failing focused checks. Added a scoped claim picker to the upload dialog, stored the selected claim and file together with a pending review link, used the claim's business unit, and cleaned up the file and database changes on failure. Replacement now requires a visible current version. History only walks visible versions and offers a way to open each one.
- 2026-10-18: Focused browser checks passed for uploading to an ERM claim and navigating a 500-file library through all 20 pages. The existing upload, library and proof checks passed. Guided upload and replacement checks passed again after the final visible-chain and conditional replacement adjustments.

## Remaining gates

- Document text extraction and image OCR are still unbuilt. Metadata search and Find evidence continue to work without them. The plan calls for bounded, isolated extraction and scoped retrieval before document text may appear in search results or AI prompts.
- The 500-file browser check proves reachability in the local test environment. It does not establish production p95 search latency or a 5,000-file capacity target.
- Upload cleanup handles ordinary database and link failures. A process crash between a file write and the database commit still needs an orphan-file reconciliation job before the disk and database can be claimed to be crash atomic.
- Real PostgreSQL and the live specialist pilot remain separate acceptance gates.

## Next build: scoped document indexing

The repository has `python-docx` and `openpyxl`, but no pinned PDF extraction or OCR runtime. Build a separate per-version text index instead of adding text to `evidence_items`: existing list routes select `e.*`, which would otherwise send entire documents to the browser. The index needs an organization and business-unit scope, a source file hash, extraction status, bounded page or sheet text, and an idempotent retry state. Apply PostgreSQL RLS before exposing the table and verify it against the existing tenant-schema creation and migration paths.

Process untrusted files in an isolated worker with limits on file size, expanded archive size, pages, cells, text bytes and wall time. Unsupported files and extraction failures must leave metadata search available and display a truthful `not indexed` state. Search must select accessible evidence rows before joining text, return short snippets with version/page attribution, and never send extracted text to the filter-parsing AI. Choose and pin PDF and OCR dependencies with a production installation path, then verify failure, replacement, archival and business-unit access against SQLite and real PostgreSQL before release.

Update, 2026-10-18: the local text-indexing build is recorded in `PLAN_EVIDENCE_VAULT_TEXT_INDEX_2026-10-18.md`. The historical remaining-gates list above predates that build. Image OCR, focused text-index tests, real PostgreSQL migration checks and the worker-isolation release decision remain open.
