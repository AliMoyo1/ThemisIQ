# Implementation and release record

This record describes the October 2026 build. The plan files remain the product contract; a code merge is not evidence that a live organization has reviewed its sources or imported its spreadsheets.

## Open-source approach review

The project instruction to compare existing implementations arrived after this branch's first build pass. Before committing, the following public projects were compared at their upstream repositories. This was a design review, not a dependency audit or permission to copy third-party code.

| Project | Approach and fit | Licence and maintenance | Supply-chain/privacy decision |
| --- | --- | --- | --- |
| [CISO Assistant Community](https://github.com/intuitem/ciso-assistant-community) | Versioned evidence reused across controls, requirement assessments and audits. Its explicit requirement/evidence split supports the Vault relationship design; its Django/Svelte stack is not a drop-in for ThemisIQ. | Active upstream; community files are AGPLv3, and `enterprise/` has a separate commercial licence. | No source or packages copied. AGPL/commercial terms need legal review for reuse; direct integration would import a much broader application and dependency graph. |
| [VerifyWise](https://github.com/verifywise-ai/verifywise) | AI use, risk, vendor and report journeys support a joined specialist register, but its domain model and user flows differ from ThemisIQ's ORM/AIMS owner records. | Active upstream; source-available BSL 1.1 and enterprise dual licensing are shown by upstream. | No source or packages copied; direct code reuse would require licence review. |
| [changedetection.io](https://github.com/dgtlmoon/changedetection.io) | Watch history, text snapshots and change notifications are useful reference patterns. ThemisIQ needs exact reviewed authority URLs, retained hashes, source rights and legal review, so a generic website monitor would be too broad. | Active releases; upstream repository identifies Apache 2.0 (review any commercial terms before reuse). | No dependency, install script or code copied. Its broad URL and browser-fetch features would expand SSRF, content and credential exposure for this use case. |

The build therefore adapts the *patterns* with existing ThemisIQ modules and dependencies. No third-party project install scripts, postinstall hooks, telemetry, obfuscated code, credential readers or network clients were added from these projects. This is a scope-limited supply-chain conclusion, not a claim that their repositories have been audited file by file.

## Built in the integration branch

- Shared exact-URL authority registry and bounded fetch path, with preserved Sentinel source keys, raw/text hashes, parser version and separate raw versus text change states. Standards publication pages have pointer-only rights; their clause text is not ingested or sent to a model.
- Capture-bound draft interpretation verifies an exact short passage against the stored text hash. Sentinel's DPO gate remains in place. Governance receives a source candidate that a specialist must promote before the existing exact-reference drift check. ERM's horizon domains are projected from the shared reviewed list and remain unreviewed leads.
- Three frozen report types use the existing report-run integrity, recipient scope recheck, sharing, independent sign-off and organization-editable retention controls. Framework, AI systems and AI risk previews expose scoped coverage and gaps. PDF includes every authorized detail row; XLSX detail sheets split below Excel's row ceiling.
- AI Governance provides specialist maintenance and reviewed system/risk spreadsheet preview and confirmation. Imports create draft or pending records; workbook claims and score discrepancies are shown separately from adopted facts. The document-control workbook creates review claims, not approved ARIA policies, Vault evidence or accepted control links. GRID audits can open the framework register with the framework preselected.
- The login video and locally hosted fonts are part of the same integration branch; the new register changes do not reintroduce remote font dependencies.

## Deliberate boundaries and release gates

- Source catalogue additions and legal effects still need named human source/legal review. The ISO pointers are not automated clause monitors. A fetch error is not a no-change result. DNS rebinding is an operational egress-filter gate: the outbound client validates DNS before connecting, so host networking must deny private and metadata destinations at connection time.
- GRID's entry point currently preselects the framework. An audit-specific verdict and finding pack is a separate filter and must not be labelled as completed by this register.
- The workbook bytes are identified by hash in import batches, but the original workbook is not automatically retained as a Vault artifact. A specialist must file the original under the organization's Vault retention and permissions if required for the audit trail.
- Report generation and preview currently run in the request path. Sheet splitting prevents silent XLSX truncation, but a bounded persistent background export job and progress view remain for very large registers. Until that is built, load testing and an operational row ceiling are release gates for large customers; do not claim unlimited throughput.
- No live workbook import, legal sign-off, AI policy change, email setup or VPS deployment is performed by the code merge. Imported records need organization review and source-file matching before use as audit proof.

## Deployment handoff (run only when separately authorized)

1. Verify the pinned master SHA and CI results, clean tracked checkout, host egress policy, service role without RLS bypass, installed dependencies and current `/health` and `/ready`.
2. Take a fresh database backup and verify its checksum and disposable restore. Preserve the prior application commit and static assets for code rollback. The new tables and columns are additive in public and tenant schemas; a database restore, rather than a code checkout, is needed to reverse migrated data.
3. Run the existing deployment preflight and migration path against the pinned commit. Check the new authority provenance, regulatory candidate, AI-profile/risk link, register-import and document-register tables in both public and tenant schemas. Avoid a root-only working tree: verify the `themisiq` service account can read changed code before restart.
4. Restart the service and allow at least four minutes for schema initialization. Verify `/health`, `/ready`, the three preview routes with two scoped test users, import preview without confirmation, and a small PDF/XLSX report with every expected row. Check source fetch errors are visible and no model output bypasses review.
5. On failed startup, stop the service, restore the prior pinned code and static assets, verify file permissions, restart and recheck health. Do not automatically restore the database over new writes; assess the additive migration and backup before any data rollback.
