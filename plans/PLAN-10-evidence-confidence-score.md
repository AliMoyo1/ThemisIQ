# PLAN-10: Evidence Confidence Score

## Goal

Roadmap item T2.1. Today a screenshot uploaded by an intern and a
digitally signed Big-Four audit report are indistinguishable rows in
`evidence_items`. This plan adds a deterministic confidence score
(0-100) per evidence item, a verification workflow (who vouched for it),
and visible badges in the Evidence Vault — so auditors and the future
control-effectiveness engine (T1.3) can weight evidence by
trustworthiness. Scoring is pure math (no AI, no cost).

Score model (deterministic, recomputed on demand):

| Factor | Points |
|---|---|
| Verification method: `digitally_signed` | +35 |
| Verification method: `auditor_signed` | +30 |
| Verification method: `peer_reviewed` | +20 |
| Verification method: `self_asserted` (default) | +5 |
| Freshness: no expiry set | +10 |
| Freshness: >30 days until expiry | +25 |
| Freshness: 8-30 days until expiry | +15 |
| Freshness: <=7 days until expiry | +5 |
| Freshness: expired | +0 |
| Reference count (evidence_links rows): 0 | +0 |
| 1-2 links | +10 |
| 3+ links | +20 |
| Has file hash (`file_hash` non-null) | +10 |
| Total cap | 100 |

## Exact files to touch

1. `oneforall/database.py` — 4 entries in `_COLUMN_MIGRATIONS`
2. `oneforall/modules/evidence/data_service.py` — scoring + verify
   functions (if the module keeps logic in routes.py instead, put them at
   the top of routes.py; CHECK which file holds list/detail logic first)
3. `oneforall/modules/evidence/routes.py` — verify endpoint + score in
   list/detail responses
4. `oneforall/modules/evidence/scheduler.py` — nightly recompute hook in
   the existing 09:00 job
5. `oneforall/modules/evidence/templates/evidence_index.html` — badges + verify UI
6. `oneforall/tests/test_evidence_confidence.py` — new tests

## Step-by-step order

### Step 1 — Columns

Append to `_COLUMN_MIGRATIONS` in database.py:

```python
        # ── Evidence confidence (T2.1) ─────────────────────────────────────────
        ("evidence_items", "verification_method", "TEXT DEFAULT 'self_asserted'"),
        ("evidence_items", "verified_by",         "INTEGER"),
        ("evidence_items", "verified_at",         "TEXT"),
        ("evidence_items", "confidence_score",    "INTEGER"),
]
```

### Step 2 — Scoring function

In the evidence module's logic file, add a PURE function (no db):

```python
_VERIFICATION_POINTS = {"digitally_signed": 35, "auditor_signed": 30,
                        "peer_reviewed": 20, "self_asserted": 5}

def compute_confidence(item: dict, link_count: int) -> int:
```

Implement the table above exactly. Freshness: parse
`item.get("expiry_date")` as `YYYY-MM-DD` with try/except (malformed or
NULL → treat as "no expiry"). Compare against `core.timeutils.utcnow()`
date. Cap at 100, floor at 0, return int.

And a db wrapper:

```python
def recompute_confidence(db, evidence_id: int) -> int:
```

Fetch the item row, count its `evidence_links` rows, compute, UPDATE
`confidence_score`, return the score. No commit inside (caller commits) —
UNLESS the surrounding module code commits inside helpers; READ two
neighboring functions and match whichever convention they use.

### Step 3 — Verify endpoint

In `modules/evidence/routes.py` add
`POST /api/items/{eid}/verify` with body
`{method: "peer_reviewed" | "auditor_signed" | "digitally_signed"}`:

- Guard: copy the decorator/capability used by the existing evidence
  DELETE route (grep `evidence.delete` usage in this file); verification
  should require the same seniority. Reject `self_asserted` as a target
  method (400) — that is the unverified default, not a grantable state.
- Set verification_method, verified_by = session user id, verified_at =
  now; then `recompute_confidence`; commit; return
  `{ok: True, confidence_score: n}`.
- Also add an "unverify" path: `DELETE /api/items/{eid}/verify` resets
  method to `self_asserted` and clears verified_by/verified_at, then
  recomputes.

### Step 4 — Score everywhere it is read

- The list endpoint that powers the vault grid: include
  `confidence_score` and `verification_method` in its SELECT (find the
  main list function; it likely does `SELECT *` — then nothing to do
  server-side).
- Recompute triggers: after link create and link delete (the link
  endpoints exist — grep `api/links` in evidence/routes.py, seen at
  line ~754 for DELETE) call `recompute_confidence` for the affected
  evidence id. Also after item create/update (expiry may have changed).

### Step 5 — Nightly recompute

In `modules/evidence/scheduler.py`, extend the existing daily job: after
the expiry-warning section, loop all `evidence_items` ids (SELECT id
only) and `recompute_confidence` each — freshness decays daily, so
scores must too. Wrap the loop body per-item in try/except so one bad
row cannot abort the job. Log the count recomputed.

### Step 6 — UI

In `evidence_index.html`:

- Card/list badge: colored chip showing the score — >=80 green "High",
  50-79 amber "Medium", <50 red "Low", NULL → gray "Unscored". Grep the
  template for an existing chip/badge class and reuse.
- Detail drawer: score, method (humanized), verified-by name + date, and
  a "Verify…" button (opens a small method-picker) for users whose page
  context says they may (pass a `can_verify` boolean from the route into
  the template context, mirroring how other capability flags reach
  templates — grep `can_` in evidence routes/template).
- After verify, update the badge in place from the response.

### Step 7 — Tests + verify + commit

`tests/test_evidence_confidence.py`:
1. `compute_confidence` unit cases: default self-asserted item, no
   expiry, 0 links, no hash → 15. Digitally signed + fresh (>30d) +
   3 links + hash → 100 (35+25+20+10 = 90… assert the exact expected
   value from YOUR implementation of the table — compute by hand and
   pin it).
2. Expired item scores lower than the same item unexpired.
3. `recompute_confidence` persists to the row.
4. Verify endpoint flow at the data layer: set method, recompute,
   assert score increased. Cleanup rows.

Live: upload an item, see "Unscored/Low", verify as peer_reviewed, badge
updates; link it to a control from the vault UI, score rises. Commit:
`Add evidence confidence scoring and verification workflow`.

## Edge cases a weaker model would miss

- **`SELECT *` list queries pick up the new columns automatically — but
  code that builds INSERT column lists explicitly will NOT set defaults
  on PG for pre-existing rows.** The migration adds the column with a
  DEFAULT, which on both engines backfills existing rows with
  'self_asserted' — verify with one SELECT after startup; if PG left
  NULLs (ALTER ... ADD COLUMN ... DEFAULT backfills on modern PG, but
  the codebase's `_run_pg_alters` may use a form that doesn't), add a
  one-line idempotent UPDATE in `_seed_baseline_data`:
  `UPDATE evidence_items SET verification_method='self_asserted' WHERE verification_method IS NULL`.
- **Score must never be computed client-side** — the badge reads the
  stored `confidence_score` so vault sorting/filtering can use it later;
  do not duplicate the formula in JS.
- **The freshness clock makes scores decay silently** — that is the
  point of the nightly recompute (Step 5). Without it, scores freeze at
  upload-time values and auditors see stale "High" badges on expired
  evidence. Do not skip Step 5 as "optional".
- **Version chains:** `evidence_items.parent_id` links versions. Score
  each row independently; do NOT aggregate up the chain (the current
  version is the one that matters and it has its own links).
- **`verified_by` has no FK** (migration-added column, consistent with
  the codebase's bare-INTEGER convention for late columns). Resolve the
  name with a LEFT JOIN in the detail query; tolerate deleted users
  (NULL name → show "—").
- **Do not gate READING scores by capability** — everyone who can see
  the vault sees badges; only granting verification is restricted.
- **Self-asserted is not failure** — the UI copy must say "Unverified",
  never "Untrusted"; users upload in good faith and the score is a
  maturity signal, not an accusation.
- **evidence_links count query must filter by evidence_id, not entity**
  — READ the evidence_links CREATE (`evidence_id, module, entity_type,
  entity_id`) and count on `evidence_id=%s`.

## Acceptance criteria

1. All 4 unit/integration tests pass with hand-pinned expected scores;
   full suite green.
2. Fresh startup migrates the 4 columns (verify via PRAGMA table_info /
   information_schema on both a fresh temp SQLite DB and the dev DB).
3. Live flow: upload → Unscored/Low → verify → badge rises → link to an
   entity → score rises again → next nightly job (or manual call to the
   job function) leaves scores consistent.
4. Verify endpoint rejects `self_asserted` (400) and unauthorized users
   (403).
5. No AI calls anywhere in this feature (grep the diff for `ai_client` —
   zero matches).
