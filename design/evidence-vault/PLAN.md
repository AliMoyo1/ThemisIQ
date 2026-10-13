# Evidence Vault: library, navigation, and intelligence plan

Status: draft product and implementation plan. No application behavior is changed by this document. Reviewed against the code on 2026-10-07 (see Appendix A). Phase 1a is split out, implemented in the working tree (not yet committed), and tracked in [PHASE-1A.md](PHASE-1A.md); the Phase 0 decisions it deliberately did not make are listed in section 9.

## 1. Product decision

Make Evidence Vault a dependable library first and an intelligent guide second. A small **Find evidence** assistant should help people describe what they need in ordinary language, then lead them to visible, permission-checked results. It should not replace search, filters, or the user's ability to inspect the source record.

Example: “Show the latest approved access review evidence for ISO 27001” should yield a short ranked list, the filters the assistant inferred, why each item matched, its current/expired state, and links to the relevant control or audit. If nothing is supported by the accessible records, say so and offer a broader search or an evidence request. Do not invent a document or a compliance conclusion.

The first implementation should use structured metadata and PostgreSQL full-text search. Add semantic retrieval only if a measured set of real user queries shows that lexical search misses important results. This keeps the initial feature understandable, fast, and easier to govern at 500–5,000 items.

## 2. Current baseline and problems to solve

The existing page already has a card/list toggle, module and category filters, saved views, recent items, coverage summaries, a detail drawer, versions, hash-based duplicate detection, bulk archive, and AI-suggested links. Evidence collection campaigns and Ask ARIA also exist elsewhere in the platform. Preserve and connect these capabilities.

| Current behavior | Effect as the library grows | Planned change |
| --- | --- | --- |
| `GET /evidence/api/items` sorts by update time and stops at 200 rows | Older records disappear from ordinary browsing | Server-side pagination, total count, stable sort, and page controls |
| Search is a plain `LIKE` over title, tags, and description, which is case sensitive on PostgreSQL (so “access” does not find “Access Review”) | A user cannot reliably find a file by case, filename, contents, or linked control | Case-insensitive metadata search including filename now (1a); then accessible extracted text, linked entity names, and references (Phase 3) |
| Card grid is the default; titles and filenames are clipped | Scanning and comparing hundreds of records is slow | Compact list as default; cards remain optional |
| Four fixed counters plus one per module with linked evidence (seven in the screenshot), a recent strip, coverage panel, selection bar, and saved views all precede the results | The actual library starts too far down the page | One compact work bar; move coverage to an expandable Insights view |
| Auto-generated breach records appear as “No file · 0 B” | They look broken or incomplete | Label “System record”, show source and related event; show file metadata only for uploaded files |
| “Unlinked” includes items with different purposes | A raw count can imply work where none is needed | Define an actionable “Needs filing” queue with reasons and exclusions |
| Upload asks for raw tags and category, then linking is separate | People may postpone filing, creating orphaned items | Guided intake with suggested metadata and links, confirmed by the user |
| Removed links still count as links: the list's link count, the Unlinked view, and stats ignore the soft-delete marker | An item whose only link was removed shows “1 link” and never appears under Unlinked, while its detail panel shows none | Count live links only, in every read path (1a) |
| The business-unit boundary is applied in the list and single-item lookups but not in stats “recently added”, topbar search, the GRID and BCM evidence pickers, or the entity evidence panels | A business-unit-scoped user can see titles of other units' evidence, and counters disagree with the list | One shared scope predicate for every read path, plus a static test against new copies (1a) |
| “All evidence” shows superseded versions beside current ones | The same document appears several times | Default views show current items; superseded and archived are explicit views (1a) |
| Coverage percentages count expired and superseded evidence | Coverage can read higher than the proof actually in force | Phase 0 defines “current proof”; coverage and Insights use it |
| Bulk import of evidence inserts into a column that does not exist and never sets the organization | Every evidence import fails; had it succeeded, the rows would be invisible to their own organization | Valid columns; organization and uploader taken from the caller (1a) |
| Evidence expiry already creates Task Board items through the daily scheduler job | A second reminder path would sit beside evidence requests | Decide in Phase 0: keep it, or move expiry reminders onto evidence requests |

The screenshot also shows the evidence search, view toggle, and upload action crowding one another in the header. The new toolbar must wrap or stack cleanly at narrower widths and at 200% zoom.

## 3. Information architecture and page layout

Use **Evidence Vault** consistently in the sidebar, page title, and cross-module links. Today the sidebar says Evidence Vault and the page title says Evidence Repository.

```text
Evidence Vault                                             [Upload evidence]
[Search title, filename, record, control, or content…]     [Find with AI]

All evidence   Needs filing   Review due   Recent   My work   Requests   Saved views ▾
Type ▾   Module ▾   Status ▾   Owner ▾   Review date ▾   More filters ▾
Active: [Policy ×] [ARIA ×] [Current ×]                 Clear all

Showing 1–25 of [total]                Sort: Updated ▾   [List] [Cards]   Insights ▾
□  Name / source       Type       Linked to       Owner       Updated      Review due
   ...
                                   [Previous] 1 2 3 [Next]
```

- Default to a readable list with columns for title, source/type, linked context, owner, updated date, review date, and status. Use two lines for long titles before truncation; expose the full title on focus and in the detail drawer. Keep cards for visual assets and users who prefer them.
- Put search, filters, sort, view choice, saved views, and upload in a coherent toolbar. Show active filter chips and a single clear-all action. Filters must combine across categories; module may be multiselect because one item can support several modules.
- Smart views are saved queries, not physical folders: **All evidence**, **Needs filing**, **Review due**, **Recently updated**, **My work**, **Requests**, and user-named saved views. The same canonical item can appear in several views without making duplicate copies.
- Replace the seven permanent KPI cards with a small action summary: items needing filing, reviews due soon, and requests awaiting me. Move detailed coverage and historical activity to an expandable Insights panel. Every metric drills into the corresponding filtered list; define the denominator and date behind coverage percentages.
- Selection reveals a contextual toolbar for permitted actions: link, apply tags, assign owner, set review date, export metadata, and archive. Do not show destructive batch actions until something is selected.
- Open a right-side detail drawer from a row, preserving list position and filters. Present preview/source, metadata, linked records, versions, activity, integrity status, and suggestions in that order. A system record should show the generating event and no misleading file size or download control.
- On mobile and at zoom, use a single search row, a horizontally scrollable view switcher, a filter sheet, and a simplified result row. Preserve keyboard navigation and reduced-motion behavior.

## 4. Core workflows

### Find and reuse

The user can search by title, filename, tags, description, linked entity name/reference, and, after extraction, document contents. Search results show matching terms or a matched section, source, current version, and links. From an ARIA control, GRID audit, BCM plan or exercise, Sentinel assessment or breach, ERM risk, ORM event, or evidence request, offer **Attach existing evidence** before **Upload new**. Attach a link to the canonical item; do not copy the file. Provide a return path to the originating workflow.

### Upload and file

Step 1: select or drop one or more allowed files. Step 2: review suggested title, type, owner, review date, and possible target records. Step 3: confirm each link and finish. A duplicate hash must offer **Use existing item**; a genuinely revised document should offer **Add version**. A near-duplicate suggestion should be presented for review, never merged automatically. Optional tags should come from a governed vocabulary with free-text fallback rather than requiring comma-separated input.

Versions today are separate rows chained by `parent_id`. The upload API marks the older row `superseded` but does not carry its links to the new row, and no screen sends a replace request, so **Add version** will be the first UI path that creates versions. Settle the rule before building it (Phase 0): carry live links forward to the new version, keep the superseded row's links as history, and exclude superseded rows from counts and coverage. “Canonical item” is not an entity in the current schema; define it as the version chain, or add a root pointer.

### Keep evidence current

Expose review date and expiry as distinct concepts. Review due, expired, superseded, and integrity-failure states need different labels and actions. Reuse existing evidence campaigns and request state machines for missing proof; an action from a gap should create or open a campaign request rather than a second task system. Retain version and link activity so reviewers can see which version supported a decision at a given time.

## 5. Small AI navigation feature: Find evidence

Place a quiet **Find with AI** action beside ordinary search and offer examples such as “latest approved BCP exercise evidence”, “policies supporting access control”, and “proof linked to the July audit”. It opens a compact panel, not a full-screen chatbot.

1. Parse the request into a proposed query: terms, entity reference, type, module, lifecycle state, and date intent. Show these as editable chips. For unambiguous references, use deterministic parsing before an LLM call.
2. Retrieve only records the current user may see. Apply tenant, business-unit, module, classification, and item permissions before ranking and before producing snippets. Rank exact references and current linked items ahead of older or superseded matches. Use the same search service for normal and AI search.
3. Return up to five evidence cards with title, version, source, status, why it matched, and a direct link. A text match cites the actual page/section or metadata field. An answer such as “I found three likely items” is acceptable; a compliance assertion needs its own reviewed workflow.
4. When there is no good match, say “I couldn't find accessible evidence for this request” and offer broadened filters, a link to the source module, or a campaign request. Preserve the user's query when switching back to normal search.
5. Keep the assistant read-only in its first release. Linking, filing, ownership, deletion, and renewal require explicit user confirmation through existing permission-checked APIs.

Data minimization: in the navigation release the model receives only the user's query text and the allowed filter vocabulary. It never receives evidence titles, snippets, or document text; ranking and snippets come from the search service. The existing AI link suggestion sends evidence titles and descriptions to the model and should be reviewed against the same rule.

Do not launch a broad “chat with all evidence” feature as the navigation MVP. Add grounded Q&A later, after extraction quality, permissions, citation coverage, and user evaluation are established.

## 6. Additional intelligence, in order

| Capability | User value | Safeguard and release gate |
| --- | --- | --- |
| Filing suggestions | Suggest category, owner, tags, and likely controls/audits on upload | Explain each suggestion; user confirms; log acceptance/rejection |
| Reuse suggestions | Show that a current item already supports a new control, audit, plan, or request | Check target access and context; linking remains explicit |
| Similarity and version guidance | Detect same file, likely revision, and near-duplicate titles | Exact hash first; never auto-merge distinct evidence |
| Freshness watch | Flag expired or soon-due evidence, superseded files still linked, missing owner, and unresolved requests | Separate clear rules from model-generated suggestions; show triggering record |
| Coverage opportunities | Identify requirements with no current linked proof and propose existing candidate items | Treat as a review queue, not an automatic claim of compliance |
| Image/PDF understanding | OCR scanned PDFs and images; expose searchable text and thumbnails | Bounded extraction, quality indicator, human review for critical references |
| Grounded Q&A | Answer questions about accessible evidence with exact sources and version-aware citations | Release only after retrieval quality and security evaluations pass |

## 7. Data, APIs, and search architecture

- Replace the fixed 200-row list with a paginated API returning `items`, `total`, `page` or cursor, and stable sort information. Support page sizes of 25 and 50. Count and list queries must apply identical permission and filter predicates. Archived and superseded records remain accessible through explicit views, not mixed silently into current results.
- Add indexes for common scoped filters and sort keys. Search title, filename, tags, description, source references, and linked entity labels. Use PostgreSQL full-text indexing for extracted text and, if enabled, `pg_trgm` for misspellings. Ask ARIA already has a PostgreSQL `tsvector`/GIN pattern to adapt (see the Ask ARIA bullet below for what not to reuse). Keep search ranking and count behavior deterministic before adding semantic retrieval.
- Store searchable content by evidence item **and version**, including org, business unit, extraction state, page/section reference, and index timestamp. Extract text asynchronously after accepted uploads; bound document size, processing time, archive expansion, and OCR workload. Reindex on new version and relevant metadata edits; remove or hide index entries when source access changes or records are deleted. A failed extraction must leave metadata search working and display a clear status.
- Extend metadata only where needed: source kind (`uploaded_file` or `system_record`), source module/entity, assigned owner, review due date, and optional sensitivity classification. Preserve the existing canonical item, link, hash, and version models; migrate historical records by inference only where the source is unambiguous.
- Candidate API shape: `GET /evidence/api/items` for paginated/filterable lists, `GET /evidence/api/search` for normal search, `POST /evidence/api/find` for natural-language navigation, and existing link/version/request endpoints for confirmed actions. Natural-language query bodies and extracted document text should not appear in access logs or analytics.
- Use one permission-aware search service for Evidence Vault and the topbar's global search. Global search currently includes evidence titles/tags but should use the same scope rules and deep links as the Vault. Cross-module “Attach existing evidence” should call that service instead of maintaining parallel search behavior.
- Defer embeddings/vector search. Evaluate it only against a representative anonymized query set after full-text search, metadata, and OCR are working. Any embedding store would need the same versioning, deletion, tenant isolation, and access checks as the primary search index.
- **One scope rule, one list shape.** A single predicate (`evidence_scope_sql`) decides which rows a user may see, and is used by the list, count, stats, coverage, topbar search, entity evidence panels, and the GRID and BCM pickers. A static test fails if evidence search appears outside the shared helpers. `GET /evidence/api/items` returns one envelope (`items`, `total`, `page`, `page_size`, `pages`). Its consumers are the Vault page, the campaigns evidence picker (which treats a non-array response as empty), and three test files, all changed together.
- **Ask ARIA is a pattern to adapt selectively.** Reuse the dual backend (PostgreSQL `tsvector` with GIN, SQLite FTS5) so the SQLite test suite can exercise ranking. Do not reuse its authorization model: its index has no org or business-unit column, authorization is a post-filter applied after the top results are chosen, control and risk chunks skip it, search errors become empty results, and terms are OR-ed. The evidence index needs org and business-unit columns filtered in SQL before ranking, an RLS policy added in `core/rls.py` (policies exist for `evidence_items`, campaigns, and requests; `evidence_links` is not policed), errors that are distinguishable from “no match”, AND semantics (`websearch_to_tsquery`), and org and business unit assigned by the application at ingestion, never by the worker.
- **Extraction worker.** Follow the PLAN-35 preview worker (`scripts/aria_policy_preview_worker.py`): a separate process and trust boundary, a spool directory, timeouts and size limits, its own requirements file, and no database access. Do not extract inside the web process (one uvicorn worker, in-process scheduler).
- **PostgreSQL test lane.** Search and permission behavior that matters on PostgreSQL must be covered in the `TEST_DATABASE_URL` lane (`tests/test_postgres_init.py` shows the pattern); the default suite runs on SQLite only.
- **Search method and logs.** uvicorn access logging is on by default and `scripts/systemd/themisiq-app.service` does not disable it, so a GET query string is written to the server log. Use POST for `search` and `find`, or record the decision to accept it.

## 8. Security, privacy, and trust requirements

- Authorization is enforced in the database/service layer for every list result, match snippet, suggestion, count, citation, preview, download, and link target. PostgreSQL RLS is a defense layer; application-level org, business-unit, module, and item checks still apply. Test the exact same query under users with different scopes.
- Treat uploaded text and OCR output as untrusted data, never instructions to the assistant. No autonomous writes, remote URL fetches, arbitrary tool calls, or hidden cross-tenant cache reuse. Validate output IDs again before rendering links or accepting a confirmed action. OWASP identifies repository documents as a prompt-injection path for RAG systems.
- AI policy and audit are new work. The platform has deployment-level provider controls (zero data retention, no provider data collection, price caps) but no per-organization AI switch, and the existing AI link suggestion writes no audit record. The navigation feature needs both before release.
- Keep AI usage within the configured organization policy. Record model/provider, feature invocation, source IDs/versions, time, and user in an audit event without logging raw sensitive excerpts unnecessarily. Set request size, rate, token, and cost limits. Offer non-AI search when AI is unavailable.
- Preserve file validation, integrity hashes, version history, and audit trails. Use least-privilege extraction workers and bounded parsing for PDFs, Office files, images, and archives. Confirm that thumbnails and indexed text inherit the same retention and deletion controls as their source evidence.
- Never use AI confidence as a compliance score. Explain match confidence as a navigation cue and distinguish “verified by integrity hash” from “reviewed and accepted as sufficient evidence”.

## 9. Delivery sequence and completion gates

| Phase | Deliverable | Gate to proceed |
| --- | --- | --- |
| 0. Define | Agree the meaning of document, evidence file, system record, current version, owner, review due, and “needs filing”; map representative user journeys. Also settle: what counts as “current proof” for coverage (expired and superseded evidence are counted today); the canonical item and link carry-forward rule for new versions; the module-permission rule for items linked to several modules or none; whether expiry reminders stay on the Task Board; whether GRID's own evidence files are in scope | Product copy and data definitions approved; representative, non-sensitive search queries collected |
| 1a. Correct data layer (no redesign; see PHASE-1A.md) | One shared scope predicate on every read path; paginated list with stable sort and a total; case-insensitive search; removed links and superseded versions no longer counted as live; evidence bulk import fixed; a “Showing X to Y of N” pager | Every item reachable beyond row 200; stats total equals list total; no out-of-scope row from the list, stats, topbar search, pickers, or entity panels; PostgreSQL lane run before release |
| 1b. Library foundation | Responsive toolbar, list-first view, smart views, contextual Insights, accessible details | Keyboard and zoom review passes; metrics drill into filtered lists |
| 2. Guided intake and reuse | Upload review, metadata suggestions, exact duplicate/version choices, Attach existing evidence from modules and campaigns | One canonical file can support several records without duplication; links and version lineage remain auditable |
| 3. Search foundation | Permission-aware metadata/full-text service; extraction jobs; filename and linked-entity search; relevant snippets | Representative queries retrieve expected accessible items; failures fall back to metadata; no cross-scope result/snippet |
| 4. Find evidence assistant | Natural-language query interpretation, editable filter chips, ranked source cards, no-match path, audit and cost limits | Every displayed item and citation is accessible and resolvable; no write action occurs without confirmation |
| 5. Proactive intelligence | Freshness, reuse, gap, OCR, and later grounded Q&A where validated | Human review remains in control; false positives measured; reports link to exact source/version |

Proposed acceptance targets to validate on the actual VPS and with representative users: search and filter remain usable at 500 and 5,000 items; metadata search returns in under one second at the 95th percentile; a user can find a known item in under 30 seconds; the assistant's top five results include the expected item for at least 90% of the agreed evaluation queries; zero unauthorized item titles, snippets, or citations are returned. Do not treat these as measured current performance.

## 10. Recommended first release

Build Phase 0 and Phase 1a first (1a changes no layout), then Phase 1b and the metadata part of Phase 3. This removes the immediate 200-item ceiling, closes the scope gaps, and gives users a coherent library before any AI expansion. The first small AI release is **Find evidence** over this shared search service, using visible filters and source-backed results. Guided upload and proactive intelligence can follow without forcing users to relearn navigation.

## Appendix A. Baseline verification (2026-10-07, HEAD eec119f)

Confirmed against the code: the 200-row cap and update-time sort (`api_evidence_list` in `modules/evidence/routes.py`); search over title, tags, and description only; card view as the default (`evidence_index.html`); “No file” and a 0 B size for rows without a file; saved views, recent strip, coverage bar, bulk archive, detail drawer, version chain, SHA-256 duplicate detection, and AI link suggestions; row level security on `evidence_items`, `evidence_campaigns`, `evidence_requests`, and saved views (`core/rls.py`); Ask ARIA's `tsvector`/GIN table and SQLite FTS5 table (`modules/aria/ask_service.py`).

Demonstrated by running a throwaway script against a fresh SQLite database (kept outside the repository): a removed link still counted by the list, the Unlinked view, and stats; a business-unit-B item hidden from a business-unit-A user by the list and by id lookup but returned by stats “recently added” and by topbar search; stats total 2 against list length 1; a superseded row in the default list; and the evidence bulk import failing with “table evidence_items has no column named created_by”.

Established by reading the code only: case-sensitive `LIKE` on PostgreSQL (no local PostgreSQL was available and the Docker daemon was not running); unscoped GRID and BCM pickers; coverage counting expired and superseded evidence; no per-organization AI setting; no access-log customization.

Not measured: every performance target in section 9.

## References

- [IBM Carbon: data table](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines) and [filtering](https://www.carbondesignsystem.com/building-blocks/core/patterns/filtering) patterns.
- [U.S. Web Design System: table](https://designsystem.digital.gov/components/table/) and [pagination](https://designsystem.digital.gov/components/pagination/) guidance.
- [PostgreSQL: full-text search](https://www.postgresql.org/docs/17/textsearch.html) and [`pg_trgm`](https://www.postgresql.org/docs/17/pgtrgm.html) documentation.
- [OWASP: prompt injection risks, including retrieved documents](https://genai.owasp.org/llmrisk/llm01-prompt-injection/).
