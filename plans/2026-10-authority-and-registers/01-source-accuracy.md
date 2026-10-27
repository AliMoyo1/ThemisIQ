# 01. Source accuracy spine

**Status:** Proposed. The current Sentinel checker remains the working baseline until an incremental migration passes parity tests. This plan does not authorize any new source, legal rule or provider.

## 1. Why this is needed

Sentinel's `living_law.SOURCES`, `_fetch`, `check_source` and capture-review path already separate page comparison from DPO approval. Governance's `run_drift_check` instead accepts a manually entered update and asks `create_message` to summarize its title, summary and control references; it does not read a preserved authoritative text. ERM's `scan_emerging_risks_grounded` uses an allowed-domain web search, while its fallback may record explicitly labelled model-knowledge leads. The AI client's URL citation allowlist does not bind each output sentence to a locally retained source passage.

The goal is one **source and capture contract**, with different consumers and reviewer authority. A legal source, a standards publication notice and a news lead are not the same kind of evidence.

## 2. Source registry, S1

Start with a versioned, code-reviewed catalogue and tenant subscriptions; do not expose an arbitrary URL entry box to the background fetcher. A registry entry records:

| Field group | Required information |
| --- | --- |
| Identity | Immutable source key; authority/publisher; jurisdiction, sector and document kind (primary instrument, regulator guidance, standards publication notice, horizon lead) |
| Retrieval | Exact pinned HTTPS URL or separately reviewed discovery-feed URL; expected MIME; parser type/version; stable content selector or PDF page strategy; byte/page/text limits; locale |
| Applicability | Framework and jurisdiction candidates, source hierarchy, publication versus commencement dates where confirmed; reviewer and review date; deprecated/replacement source |
| Rights | Separately reviewed permissions for capture, private retention, display, quoted excerpts, AI processing and export; evidence of permission/licence and review date |
| Operations | Cadence allowed for this source, last successful capture, last attempt/error, monitoring owner, change history and source-registry version |

The code-reviewed exact fetch URL and the wider domain list that a provider may cite are **different projections**. A domain on ERM's horizon allowlist is not automatically a legally authoritative monitor. A new or moved URL becomes a review candidate, not an automatic redirect. Existing Sentinel keys and capture IDs remain readable. Per-organization source selection follows active jurisdictions and the existing 24-hour/weekly/monthly cadence; framework-specific sources are enabled only when relevant and rights-cleared. A shared public fetch may be fanned out to tenants without mixing their review, status or content rights.

For ISO and other licensed standards, default to publication metadata and a pointer; never assume paid clause text may be copied into a shared SaaS database, included in an export or sent to an AI model. ISO's current [copyright notice](https://www.iso.org/copyright.html) specifically restricts reproduction and AI use. Rights checks are source- and licence-specific; NIST or legislation should not receive a universal rights flag either.

## 3. Guarded fetch and capture, S2

Reuse Sentinel's exact-URL, HTTPS, no-redirect, MIME, size, extraction and review behavior; share only security primitives that fit this job. `core.outbound_http.validate_outbound_url` is useful for public-address validation, but its current response cap is 64 KiB for webhook acknowledgements and its sender is not a legal-PDF fetcher. The new fetch client has its own capped profiles for HTML/PDF; `trust_env=False`; explicit phase/total timeouts; no embedded credentials, cookies or redirects; strict DNS/IP checks at connection time; bounded retries/backoff; and response metadata. Resolve DNS rebinding and proxy behavior in a focused security review before exposing more domains.

Perform PDF extraction in the existing resource-limited, networkless child; cap pages, decompressed size, CPU, memory and extraction time. Keep HTML parsing deterministic, versioned and source-specific. Exclude navigation, scripts, timestamps and dynamic boilerplate only through reviewed selectors; retain raw bytes so the filter can be audited. A parser failure is an error, not a zero-length baseline.

Store an immutable capture with source-registry version, final requested URL, retrieval timestamp, HTTP status/content type, raw SHA-256, raw private storage reference, extracted-text SHA-256, parser version, section/page anchors and the previous capture ID. Record separate outcomes:

1. `fetch_error` or `parse_error`: current state unknown; keep last good capture visibly dated and retry.
2. `raw_only_change`: bytes changed, normalized relevant text did not; record provenance, avoid an obligation task.
3. `no_relevant_text_change`: same normalized text; no review task.
4. `baseline_pending_review`: first successful source copy, not a legal conclusion.
5. `source_change_pending_review`: text diff worth human triage; do not say “law changed.”
6. `reviewed_no_impact`, `reviewed_guidance_change` or `approved_regulatory_impact`: specialist decision with actor, reason, version and applicability.

Store the full bounded diff and a short UI excerpt; do not infer that a page edit is legally effective. Compare against the last suitable baseline by an explicit rule; do not let a rejected or stale capture silently become the comparison anchor. Idempotency key is source key + raw hash + parser version + tenant where applicable. A scheduler lease prevents parallel duplicate work; the current Sentinel tenant-fanout/cadence logic is the migration reference.

## 4. Grounding contract, S3

The **default** interpretation path uses only a rights-permitted, preserved before/after capture. It produces candidate JSON with: claim, change kind, source/capture ID, exact section or PDF page and bounded quote, hash, why it may matter, jurisdiction/applicability questions, confidence expressed as a review cue, and `cannot_verify` reasons. Deterministic validation checks every quote/anchor against the stored extracted text and exact capture, rejects unknown IDs, unsupported dates, missing sources and unapproved rights. It does not use a provider-generated URL as proof. A specialist sees the diff and quote next to the candidate and records an independent verdict.

No external model call is needed for detection, scheduling, diffing, exact-reference matching or extractive answers. Provider interpretation is optional, budgeted per organization, and gated by AI policy, allowed data categories, source rights, approved provider/route and minimization. Only necessary public excerpts leave the tenant; log the policy decision and model/version without copying source text to general logs. Prompt injection within source pages is untrusted content; it cannot modify tools, controls or reviewer instructions. On provider failure or unsupported output, show the deterministic diff and `interpretation unavailable`.

`create_message_web_search` may help discover candidate sources or obtain a separately labelled horizon lead, but domain filtering and URL citations alone do not establish support for an auditable regulatory claim. OpenRouter's [server-tool documentation](https://openrouter.ai/tool/web-search/) says the model decides whether and what to search; that is not deterministic change detection. A discovered URL must enter source review and local capture before an approved-impact claim. The optional Gemini grounding adapter is a later provider-specific project with URL-normalization, rights, privacy, retention, model-drift and citation-parity review; it is not a precondition.

## 5. Consumer workflows

### Governance regulatory inbox: first consumer after S1/S2

An approved source subscription yields a captured `regulatory_update_candidate` linked to its exact before/after captures. A governance specialist reviews whether the source edit describes a publication, commencement, guidance revision, formatting change or unrelated news; confirms framework and applicable control references; records effective date only from reviewed source evidence; and accepts or dismisses it with reason. Only the accepted candidate creates/updates `regulatory_updates` and launches the existing `run_drift_check` task path. Preserve its exact lower/trim control-reference equality; do not use fuzzy SQL or AI to make authoritative matches. AI summary becomes a source-bound **draft** requiring independent review, never an automatic control-impact decision. Dismissal creates no control task.

### Sentinel living law

Keep existing active-jurisdiction checks, per-tenant cadence, DPO capture approval and separately approved operational rule cards. Offer an optional short explanation of an already captured diff with exact passage/page references. It appears as an AI draft beside the source inspector, never changes a statutory clock or approved rule. Ask Sentinel continues to prefer approved, permission-checked captures and visibly dates stale or superseded evidence. An approved extractive source is not itself an approved legal interpretation.

### ERM horizon scan

Consume the registry's **horizon** domain projection, with a distinct trust label for official authorities, reputable reporting and other leads. Keep an emerging risk unreviewed until a risk specialist connects it to an actual source and decides relevance. The existing knowledge-only fallback may remain only as a clearly separate, uncited **research lead**; it cannot satisfy “no citation, no verified claim,” create a regulatory update or appear as a verified current-event finding. A failed grounded scan is not “no emerging risks.”

## 6. Reviewer experience and alerts

Jurisdiction Manager and Regulatory Inbox share a source inspector pattern: source and rights, last successful check, fetch error, exact prior/current capture, highlighted relevant diff, parser version, integrity status, proposed impacts, affected record candidates, and a single review action. Reviewers can say “irrelevant edit,” “needs legal interpretation,” “applicable change,” or “cannot verify”; they can assign and reopen review. My Work/notifications link to that exact review item and never quote sensitive tenant content into a global alert. Executives see reviewed impacts and open decisions, not raw page-change counts presented as legal changes.

## 7. Acceptance and failure cases

- Golden fixtures: unchanged bytes; changed bytes with identical relevant text; HTML navigation-only change; genuine legal-text change; first baseline; moved URL/redirect; MIME mismatch; PDF extraction failure; source removed; duplicate scheduled check; parser-version upgrade.
- Security negatives: private/reserved IP or rebinding, proxy-env influence, oversized/decompression-bomb response, cross-tenant capture access, poisoned HTML/PDF instructions, stale citation and rights-denied AI call.
- Grounding negatives: allowed-domain citation to the wrong page, correct URL but unsupported sentence, altered quote, wrong PDF page, invented effective date, output without capture ID/hash, and model unavailable. All fail closed into reviewable source facts.
- Workflow: no task from unchanged or failed fetch; no legal status without specialist verdict; no automatic Sentinel clock change; exact control-ref matches stay exact; ERM fallback never becomes a reviewed fact; organization AI-off path remains useful.

## Source notes

Primary external references: [ISO copyright](https://www.iso.org/copyright.html) for source-specific content/AI rights and [OpenRouter web search](https://openrouter.ai/tool/web-search/) for the nondeterministic server-tool boundary. Recheck provider and licence terms at implementation time. The source registry itself is a reviewed product record, not a substitute for legal advice or primary publication.
