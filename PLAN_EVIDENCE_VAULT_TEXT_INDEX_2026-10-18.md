# Evidence Vault scoped text indexing

## Outcome

Search may find permitted current evidence by text inside PDF, DOCX, XLSX, TXT, CSV and JSON files. Results show a short passage and its page, sheet or document label. The index is tied to one immutable file hash and version. The question-to-filter AI still receives only the person's question and allowed filter vocabulary.

## Build sequence

1. Add an evidence text table in the public and new tenant schemas, with a row per file version, organization, business unit, hash, status and bounded extracted text. Apply public-table row security. Never add extracted text to `evidence_items`, whose rows are returned by existing list APIs.
2. Run parsers in a separate process with a short timeout, input and output limits, archive expansion limits and a restricted environment. Pin the PDF reader to `pypdf==6.21.1`; PDF, Office and text formats are supported. Image OCR and legacy binary Office formats report `not indexed` until a bounded OCR/import worker is available.
3. Use an idempotent background batch per tenant to index files that have no matching current hash/indexer version. Record `indexed`, `empty`, `unsupported` or `failed` without interrupting metadata search. Re-index when the source hash changes; never reuse text from an earlier version.
4. Join the text table only after applying the evidence scope and current-view predicates. Give matched results a short highlighted passage with a page or sheet label, while preserving list pagination and exact count. A viewer of another business unit sees no match, snippet, count or timing-dependent branch through a hidden file.
5. Verify supported and unsupported formats, parser failure, replacement, archival, tenant and business-unit scoping, and a 500-file search. Use focused SQLite and real PostgreSQL checks. Keep the live specialist pilot for after the larger build.

## Boundaries

- Extracted text is untrusted document content. It never becomes an instruction to the AI and cannot approve evidence or a claim.
- The helper process must run inside a Linux Bubblewrap filesystem and network namespace when indexing is enabled. The deployment still needs a verified Bubblewrap installation and an extraction check under the app service identity.
- An extraction failure does not make the evidence itself missing or invalid. The UI states what was and was not indexed.
- No existing file is moved or deleted by indexing.

## Local build record, 2026-10-18

- Added the per-version index table to public and tenant schema creation, with public organization RLS. Search checks matching file hash, organization and business unit before text can match a result.
- Added a bounded child process for PDF, DOCX, XLSX, TXT, CSV and JSON extraction. The parent verifies the hash of a private temporary copy before parsing it. Input, output, CPU, memory (Linux) and wall-time limits are bounded. Missing or unsupported files retain metadata search.
- A leased scheduler processes up to 12 documents every five minutes, at most three per PostgreSQL tenant per pass, rotating the starting tenant. Failed items are retried after a day; changed versions are indexed immediately on a subsequent pass.
- Library and Find evidence searches share the text predicate. Only a short escaped passage and its page or sheet label reach the browser. Item details show whether indexing succeeded, is pending, or was unsupported or failed.
- Syntax parsing and whitespace checks passed. No automated tests or real PostgreSQL migration check were run in this turn. Live pilot and production rollout remain deferred. Before production, run focused tenant isolation and migration checks and prove the parser's OS isolation on the target Linux service.

## Follow-up, 2026-10-18

- Automatic extraction is disabled by default. `EVIDENCE_TEXT_INDEX_ENABLED=1` takes effect only on Linux when `bwrap` is installed. The child sees read-only interpreter and package roots, its script and one frozen document, with no app data mount or network namespace. This sandbox has not been exercised under the production service identity; do not enable it until that check and the tenant-isolation and migration checks are complete. When disabled, a file without an existing index says indexing is disabled rather than pending forever.
- The Evidence Vault download, PDF preview, verification and permanent-delete paths now require a resolved file path to be inside the exact configured directory. A sibling directory whose name begins with the same text is no longer accepted.
- The AI Governance overview now includes evaluation outcome and tier attention views derived from the same scoped portfolio list as Monitoring. Filter links include the previously missing not-measured outcomes. When the portfolio exceeds 500 uses, the views identify their partial coverage.
- The AI Governance Requests page now has a paginated specialist worklist derived from request, decision, question and external-response records. The counts and rows share the reviewer's organization and business-unit scope. It distinguishes an explicitly sent response from a decision. A specialist can close an accepted request only after its latest external response is marked sent; closing a triage rejection requires a recorded communication channel, reference and reason. Closure records actor and time on the request.
- Syntax and whitespace checks are the only checks run for these changes. Automated, PostgreSQL and browser checks remain open, as does proving the parser sandbox under the target Linux service.
