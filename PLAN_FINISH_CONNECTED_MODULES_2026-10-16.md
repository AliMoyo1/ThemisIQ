# Finish connected module work

## Scope

Complete items 1 and 2 from the 2026-10-16 status review. Preserve existing user edits and historical records. The source module keeps its decision; the Evidence Vault owns file bytes and versions. All reads and writes must respect organization, business unit, capability, and record scope.

## Sequence

1. Inventory the current uncommitted slices and check their schema, route, UI, and rollback behavior. Correct defects and run focused backend, PostgreSQL where available, and browser checks.
2. Converge GRID and BCM files on one Vault artifact identity. Inventory historical rows, build an idempotent organization-scoped crosswalk and migration, keep previous audit and compliance decisions, and stop writing duplicate new file bytes.
3. Add source-backed module home views and extend Related Items entry points to the module records used in the connected journey. Empty and unavailable states must remain distinct.
4. Add versioned Sentinel jurisdiction cards and multiple breach obligations. Until a legal owner approves rule text, source, effective dates, and trigger, a card remains draft and has no authoritative countdown.
5. Reconcile the implementation ledger, verify focused security and UX behavior, then report build, verification, and release status separately.

## Progress

- 2026-10-16: Inspected repository status and specialist module plan. Existing local edits cover ERM acceptance, AI form mappings, My Work grouping, report traceability, GRID and BCM Vault links, and Related Items. No current-turn tests or deployment yet.
- 2026-10-16: Verified the earlier local slices with focused backend checks. Corrected stale My Work and GRID test expectations after the new ERM acceptance source and GRID access requirement. The release remains local and uncommitted.
- 2026-10-16: New GRID uploads and replacements now store bytes only in the Vault. Historical current files and older GRID versions can be reconciled through idempotent crosswalks while retaining module review decisions and original source files. Prior best-effort Vault copies are adopted only after scope and byte-hash checks. Legacy version reads no longer expose filesystem paths.
- 2026-10-16: BCM compliance proof now attaches scoped Vault artifacts and offers a human-confirmed legacy match. Old client-supplied paths remain metadata only and are never used for a download.
- 2026-10-16: Source-backed connected overview cards are present on the six specialist module homes. Five module homes passed real Chromium checks. GRID control, BCM incident, and Sentinel breach record views gained Related Items entry points.
- 2026-10-16: Sentinel has draft and DPO-approved, versioned jurisdiction rule cards and multiple per-breach obligations. A clock is authoritative only with an approved card, a sourced trigger and an effective rule date. Existing single-regulation clocks are labelled indicative. Three focused obligation tests and the existing breach clock tests pass.
- 2026-10-16: Focused module home, historical migration, canonical Vault, Sentinel, ERM acceptance, My Work, and evidence scope checks pass after one stale source-list assertion was updated. Real PostgreSQL validation is still pending because Docker Desktop is unavailable on this host. No full suite was run.
- 2026-10-16: Removed internal GRID storage paths from file detail, file list and version list responses. The all-evidence collection now applies the same row scope as audit records. Added a focused unit-scope regression. Browser checks passed for the BCM legacy match action and Sentinel DPO draft form. Draft and approval actions are shown only to roles with the matching capabilities.
- 2026-10-16: Final focused backend group passed 18 checks. Seven focused Chromium checks passed across five specialist homes, the BCM legacy evidence dialog and the Sentinel DPO rule card form. The first final backend attempt stalled at the local HTTP test because Windows sandbox sockets were blocked; the rerun in the permitted local test environment passed. `git diff --check` reports only line-ending notices.
- 2026-10-16: A final review found that newly replaced GRID versions already had Vault pointers but no historical crosswalk row. The version response now derives the artifact ID from its internal pointer and still hides that pointer. The focused canonical upload checks passed again.
- 2026-10-18: Added a guarded disposable PostgreSQL regression for creating the GRID crosswalk and Sentinel obligation tables in public and existing tenant schemas. Docker Desktop is unavailable on this host, so this test has not executed. Static DDL review is not a substitute for the PostgreSQL run.
- 2026-10-18: A failing GRID regression proved that a status update exception could occur after the Vault and GRID records were committed. The new canonical upload path now updates status before one commit, rolling back records and deleting the new file on failure. A second regression confirms failed replacement preserves the prior approved version. Replacing an approved file now reopens a completed control for review. Five focused GRID upload tests passed; the connected module backend group passed 22 checks. No full suite, live pilot, commit, push or deployment was performed.
- 2026-10-18: Closed the direct-form part of the ARIA change-signal gap. Risk status, likelihood and impact and document status, version and review date now inform confirmed linked records after the edit is saved. Owner names, mitigation prose and document comments are excluded from signals. Two form regressions failed before wiring and passed afterward; the focused change-signal file and form checks passed 44 checks. Two existing policy approval signal checks also passed. ARIA imports and bulk signal batching remain open.

## Release gates still open

- Run the focused schema and tenant migration checks on a disposable PostgreSQL database before deployment. The local SQLite checks do not prove PostgreSQL DDL or row security.
- Have a privacy legal owner populate and approve actual jurisdiction sources, trigger interpretations, effective periods and notice channels. The build does not ship legal deadlines as facts.
- Walk through the specialist workflows with pilot data, including BCM historical evidence matching, GRID version downloads, approval roles and audit exports. No production evidence was migrated here.
- Review all existing local changes together before making a commit or release. This working tree contains user edits beyond this connected-module stage.
