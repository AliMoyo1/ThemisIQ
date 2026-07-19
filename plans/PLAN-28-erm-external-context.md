# PLAN-28: ERM External Context (emerging risk inbox + AI horizon scan)

## Status: OPEN (requires PLAN-23; PLAN-27 recommended first for
risk_context = external)

## Goal

The mind map's External Context: "the system should also be able to scan the
internet and reliable internet sources for any new emerging risks for the
organization that affect any of the Risk Pillars or the ISO Standards
implemented and the user can choose to add these to the risk register".

Scope decision (revised 2026-07-18): live internet scanning IS feasible
today. The Anthropic Messages API, which core/ai_client.py already calls
over raw HTTP, offers a server-side web search tool: add a `tools` entry to
the request body and the API runs real searches during the call and returns
results with cited source URLs. Pricing is 10 USD per 1,000 searches plus
standard token costs; `max_uses` caps searches per request and
`allowed_domains` restricts results to a curated list of reliable sources,
which matches the mind map's "reliable internet sources" requirement
exactly. No feed partnership, scraper, or new dependency is needed.

This plan therefore ships an EMERGING RISK INBOX with two feeds:

1. Manual entries (a CGRCO or the platform team posts items).
2. An AI horizon scan with two modes:
   - GROUNDED (primary, when AI_PROVIDER is anthropic): the scan request
     includes the web search tool, so candidates come from live, cited
     sources and each stored item carries its real source URL.
   - KNOWLEDGE-ONLY (fallback, for other providers, when web search is
     disabled for the org, or when the grounded call fails): candidates
     from model knowledge, clearly labelled with a verify-before-acting
     caveat and no URLs.

The inbox, review workflow, and add-to-register flow are identical for
both modes; only the generator and the provenance labelling differ.

## Files to touch (exact)

1. `oneforall/database.py` (one table)
2. `oneforall/core/ai_client.py` (one new function for the grounded call)
3. `oneforall/config.py` (three new settings with defaults)
4. `oneforall/modules/erm/data_service.py`
5. `oneforall/modules/erm/routes.py`
6. The module imported as `ai` in erm/routes.py (two new functions)
7. `oneforall/modules/erm/templates/index.html`
8. `oneforall/tests/test_erm_emerging.py` (NEW)
9. `plans/README.md`

## Step-by-step order

### Step 0: create `plans/PLAN-28-active.md`; log every change as you go.

### Step 1: database.py - table

In `_ERM_ORM_TABLES` after erm_objectives (or after erm_pillars when
PLAN-27 has not run: order inside the string does not matter, tables have
no cross-FKs here):

```sql
-- ── ERM v2: Emerging risk inbox (external context) ─────────────────────
CREATE TABLE IF NOT EXISTS erm_emerging_risks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    summary       TEXT,
    source_note   TEXT,
    source_url    TEXT,
    pillar        TEXT,
    standard_ref  TEXT,
    origin        TEXT DEFAULT 'manual',
    status        TEXT DEFAULT 'new',
    added_risk_id INTEGER REFERENCES erm_enterprise_risks(id),
    business_unit_id INTEGER,
    created_by    INTEGER REFERENCES users(id),
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_erm_emerging_status ON erm_emerging_risks(status);
```

origin values: manual, ai_scan_web (grounded), ai_scan (knowledge-only).
status values: new, dismissed, added. source_url may only ever be set from
a web-search citation or a manual entry; a knowledge-only scan must never
write one.

### Step 2: data_service.py

- `list_emerging(status=None)`: ordered created_at DESC, joined creator
  name.
- `create_emerging(data, origin='manual')`: title required; source_url
  accepted and length-capped (500) with a scheme check (http/https only,
  else stored NULL).
- `dismiss_emerging(eid)` / `reopen_emerging(eid)` (status flips; reopen
  only from dismissed).
- `add_emerging_to_register(eid, user_id)`: refuse (ValueError) when
  status is already added; build a risk dict: title, description from
  summary plus a "Source: external context inbox. {source_note}" suffix,
  category "Strategic Risk" fallback (use the pillar-to-category mapping
  ONLY if trivially derivable, else default), impacted_pillar, likelihood
  3, impact 3, status open, risk_context 'external' IF the column exists
  (wrap in a capability check: SELECT the column list or try/except so the
  plan works pre-PLAN-27), created_by user_id; call
  create_enterprise_risk; UPDATE the inbox row to status added +
  added_risk_id; return the new risk id.
- `build_org_context(db)`: dict for the AI prompt: active pillar names,
  active framework names (SELECT name FROM frameworks LIMIT 20, table
  exists platform-wide), count of open risks by category (top 5). No PII,
  no user names.

### Step 3: AI generator (two modes)

a) `oneforall/config.py`: three settings with env-var overrides, matching
the existing settings pattern in that file:

```python
ERM_SCAN_MODEL = os.getenv("ERM_SCAN_MODEL", "claude-sonnet-5")
ERM_SCAN_MAX_SEARCHES = int(os.getenv("ERM_SCAN_MAX_SEARCHES", "8"))
ERM_SCAN_ALLOWED_DOMAINS = [d.strip() for d in os.getenv(
    "ERM_SCAN_ALLOWED_DOMAINS",
    "enisa.europa.eu,edpb.europa.eu,ico.org.uk,nist.gov,cisa.gov,"
    "iso.org,weforum.org,reuters.com,csoonline.com,darkreading.com"
).split(",") if d.strip()]
```

The domain list is the "reliable internet sources" control; the CGRCO can
change it via env var without a code change. 8 searches cost 0.08 USD at
the published 10 USD per 1,000 searches rate.

b) `oneforall/core/ai_client.py`: new function
`create_message_web_search(messages, system, max_tokens, model,
max_searches, allowed_domains)` used ONLY when `_provider()` is
"anthropic" (raise RuntimeError otherwise so callers must guard). Same
raw-httpx shape as the existing `_anthropic()` (line ~169) with these
differences, each of which matters:

- Body gains: `"tools": [{"type": "web_search_20250305",
  "name": "web_search", "max_uses": max_searches,
  "allowed_domains": allowed_domains}]`. Use the basic tool version:
  the newer `web_search_20260209` defaults to running searches through
  code execution, which adds response block types this parser does not
  need. Never send both allowed_domains and blocked_domains (API 400).
- The response `content` is a LIST OF MIXED BLOCKS (text,
  server_tool_use, web_search_tool_result). The existing
  `data["content"][0]["text"]` pattern is WRONG here: concatenate the
  `text` of every block with `"type" == "text"`, and collect citations
  from each text block's optional `citations` array (each carries `url`
  and `title` for type web_search_result_location).
- `pause_turn` continuation: if `data.get("stop_reason") == "pause_turn"`,
  append `{"role": "assistant", "content": data["content"]}` UNCHANGED
  (the blocks include encrypted_content that must not be modified) to the
  messages and re-POST; cap at 3 continuations, then use whatever text
  has accumulated.
- A search error arrives inside a 200: a `web_search_tool_result` block
  whose `content` is a dict (error object with `error_code`) instead of a
  list. Ignore such blocks; they must not crash parsing. A 400 whose
  message says web search is not enabled means the org admin disabled the
  feature in the provider console: raise a distinct RuntimeError so the
  caller can fall back.
- Return `{"text": joined_text, "citations": [{"url", "title"}, ...],
  "searches_used": usage["server_tool_use"]["web_search_requests"]}` with
  the usual usage metadata.

c) In the erm `ai` module, two functions:

- `scan_emerging_risks_grounded(org_context)`: builds a prompt asking for
  STRICT JSON, a list of at most 5 objects {title, summary, pillar,
  standard_ref, source_url, rationale} where source_url MUST be copied
  from one of the search citations, plus the instruction: search the
  allowed sources for risks that are NEW or RISING in the last 12 months
  for an organisation with this profile; respond with JSON only; if
  uncertain, return fewer items. Calls create_message_web_search. After
  parsing, DISCARD any item whose source_url is not in the returned
  citations list (exact string match against citation urls); such items
  are stored with source_url NULL and the knowledge caveat instead. Store
  survivors via create_emerging with origin='ai_scan_web' and source_note
  "Live web scan ({title of cited page}). " + rationale.
- `scan_emerging_risks(org_context)`: the knowledge-only fallback,
  prompting the existing ai_client for the same JSON shape WITHOUT
  source_url; prompt forbids fabricating citations or URLs; items stored
  with origin='ai_scan' and source_note
  "AI-generated (model knowledge, verify before acting). " + rationale.

Both parse defensively (json.loads inside try/except, tolerate a fenced
code block by stripping ``` lines); return [] on any failure.

### Step 4: routes.py

- `GET  /api/emerging` (erm.risk.view): optional status param.
- `POST /api/emerging` (erm.risk.manage): manual create.
- `POST /api/emerging/{eid}/dismiss`, `POST /api/emerging/{eid}/reopen`
  (erm.risk.manage).
- `POST /api/emerging/{eid}/add-to-register` (erm.risk.manage): returns
  {risk_id}; fire the same ERM_RISK_IDENTIFIED emit the normal create
  endpoint fires (copy the emit block from api_risk_create at line ~105).
- `POST /api/emerging/scan` (erm.ai.use + the existing
  check_ai_rate_limit/record_ai_call pair, copy from suggest-scores at
  line ~659): runs build_org_context, then tries
  scan_emerging_risks_grounded when the provider is anthropic, falling
  back to scan_emerging_risks on RuntimeError or empty grounded result.
  Returns {created: n, grounded: true|false} so the UI can label the
  batch.

### Step 5: UI

New SPA page "external" ("External Context") following the established
_SPA_PAGES pattern, nav-visible to every ERM user:

- Header: "Scan for emerging risks" button (spinner while POSTing /scan;
  toast "{n} candidates added" plus "(live web scan)" when the response
  says grounded, "(model knowledge only)" otherwise; disabled note when
  the tenant has AI off, reuse however the chat page detects that).
- Caveat banner, mode-aware: for ai_scan items:
  "Generated from model knowledge, not a live source. Verify
  independently before acting." For ai_scan_web items no banner; each
  card instead shows its source link. Render the banner per-card (or as
  a chip), not page-wide, since both origins can coexist in the inbox.
- Inbox list with status chips filter (New / Dismissed / Added / All):
  cards showing title, summary, pillar + standard_ref chips, origin badge
  (Manual / Web scan / AI knowledge), a "Source" link opening source_url
  in a new tab when present (citations must be displayed with API
  outputs; rel="noopener noreferrer" and esc() the URL into the href),
  created date, and actions per status: Dismiss + Add to register (new),
  Reopen (dismissed), View risk link (added, deep-link to the register
  drawer via the existing entity deep-link pattern).
- Manual add modal: title, summary, source_note, source_url (plain text
  input, optional), pillar select (ERM_PILLARS), standard_ref text.
- Add to register: on success toast + navigate to the register with the
  drawer open on the new risk.

### Step 6: tests - `oneforall/tests/test_erm_emerging.py`

1. create manual item; list filters by status.
2. dismiss then reopen; reopen from new raises ValueError.
3. add_emerging_to_register creates a risk carrying title, pillar and the
   source suffix in description; inbox row flips to added with the risk
   id; second add attempt raises.
4. AI parse hardening: feed scan_emerging_risks a monkeypatched ai_client
   returning (a) valid JSON, (b) fenced JSON, (c) garbage: item counts
   5 max / parsed / 0 respectively, no exception. (Monkeypatch at the ai
   module boundary; never call the real API in tests: follow the
   existing AI test patterns in the tests folder if present, else patch
   with monkeypatch.setattr.)
5. deleting the created risk does not delete the inbox row (FK is
   nullable reference; delete_enterprise_risk should NULL added_risk_id:
   add that UPDATE to its cleanup block and assert it).
6. grounded parse: monkeypatch create_message_web_search to return a
   payload with (a) two items whose source_url matches a citation and one
   whose does not: the two are stored as ai_scan_web with source_url, the
   third falls back to NULL source_url with the knowledge caveat;
   (b) citations list empty: all items stored without source_url.
7. grounded fallback: monkeypatch create_message_web_search to raise
   RuntimeError (web search disabled case) and assert the scan endpoint
   logic falls through to the knowledge-only generator and still returns
   created items with grounded false. Exercise via the data-service or a
   small routes-level helper, whichever the file structure makes direct.
8. pause_turn handling in create_message_web_search: monkeypatch
   httpx.Client.post to return a pause_turn response then a final one;
   assert both text parts are joined and the continuation resent the
   assistant content unchanged.

### Step 7: verify

- py_compile + full pytest.
- Live browser: manual item add, dismiss, reopen, add-to-register lands in
  the register with context badge; run one real grounded scan if an
  Anthropic API key is configured in dev (skip gracefully otherwise and
  note it in the active plan file): confirm items carry working source
  links from the allowed domains and the toast says live web scan.
  Clean up all test rows.
- Update plans/README.md. One focused commit.

## Edge cases a weaker model would miss

- NEVER let the scan endpoint block the event loop: the existing AI
  endpoints are async and call the client the same way; copy that pattern
  exactly rather than inventing a thread.
- The AI response is untrusted input: length-cap title (200) and summary
  (2000) before INSERT; strip control characters; sanitize through the
  same helpers other ERM endpoints use on body fields.
- URL provenance is the trust boundary: a stored source_url must come
  from the API's citations array (grounded mode) or a manual entry,
  NEVER from generated JSON text alone. The citation cross-check in
  scan_emerging_risks_grounded is mandatory; a model can still write a
  plausible-looking URL into its JSON, and only the citations array
  proves a page was actually retrieved. Knowledge-only mode continues to
  forbid URLs entirely.
- Web search response shape traps: content is a list of mixed block
  types, so never read content[0]["text"]; a tool error is a dict-typed
  content INSIDE a 200, so branch on isinstance before iterating; a
  successful search with no results is an empty list, not an error.
- pause_turn continuations must resend the assistant blocks byte-for-byte
  (encrypted_content validation fails on any modification) and must be
  capped to avoid an infinite loop.
- max_uses is the cost cap: keep ERM_SCAN_MAX_SEARCHES small (default 8,
  about 0.08 USD per scan) and never expose it as a client-supplied
  parameter.
- The org admin can disable web search in the provider console; that
  surfaces as a 400 on the request, not an error block. Catch it and fall
  back to the knowledge-only scan instead of failing the endpoint.
- The grounded call must pin a current model (ERM_SCAN_MODEL, default
  claude-sonnet-5) rather than inheriting the client's default model
  setting, which may be older and lack the tool.
- allowed_domains and blocked_domains are mutually exclusive in one tool
  definition (API 400): the settings only expose the allowlist.
- add-to-register must be idempotent-guarded server-side (status check),
  not just a hidden button client-side: double-click protection.
- delete_enterprise_risk cleanup: add
  `UPDATE erm_emerging_risks SET added_risk_id=NULL WHERE added_risk_id=%s`
  or the FK will block risk deletion on PG (SQLite without enforcement
  would silently orphan instead: both are bugs).
- risk_context column may not exist if PLAN-27 was skipped: feature-detect
  and omit the field rather than crashing (test on a PLAN-23-only DB).
- business_unit_id follows the Round 5 federation rule (every standalone
  new table carries it): set it from the creating user's BU when the
  session has one, apply bu_scope_ids filtering in list_emerging exactly
  like the risk list endpoints, and copy it onto the created risk in
  add_emerging_to_register. Child-of-risk tables in the other Round 6
  plans (CFs, treatments, history) inherit scope through risk_id and
  correctly do NOT carry their own column.
- Relationship to the PLAN-13 regulatory inbox: that inbox holds
  regulator/framework CHANGE notices consumed by drift detection; this
  one holds emerging RISK candidates for the register. They stay separate
  surfaces; do not merge them, but an emerging item citing a regulation
  may mention the regulatory inbox in source_note.
- Rate limiting: the scan uses the shared AI limiter; do not add a second
  bespoke limiter.
- The scan can legitimately return 0 items; the UI toast must handle
  "0 candidates added" without implying an error.

## Acceptance criteria

- [ ] All 8 test cases pass; suite green; py_compile clean.
- [ ] Every stored source_url is traceable to a web-search citation or a
      manual entry; knowledge-only items never carry one.
- [ ] ai_scan items show the knowledge caveat; ai_scan_web items show a
      working source link instead.
- [ ] A grounded scan against the real API (dev key) returns items only
      from the allowed domains, and the response records searches_used
      no higher than ERM_SCAN_MAX_SEARCHES.
- [ ] Web search disabled or non-anthropic provider degrades to the
      knowledge-only scan with grounded false in the response, never a
      500.
- [ ] Add-to-register produces a fully scored register risk (irr, rrr set
      by the PLAN-23 engine defaults) and deep-links to it.
- [ ] Manual-only flow works with AI disabled entirely.
