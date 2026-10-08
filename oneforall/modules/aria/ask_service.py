"""
Ask ARIA: AI Q&A over the ARIA corpus (policies, controls, documents, risks).

Design:
  * SQLite: FTS5 virtual table `aria_ask_index` (BM25 ranking via bm25()).
  * PostgreSQL: regular table with `body_tsv tsvector GENERATED ALWAYS AS ...`
    + GIN index; ranking via ts_rank_cd().
  * Policies (long markdown) are chunked by H2 section headings.
  * Controls, risks, and document metadata are single chunks.
  * Top-N chunks are handed to Claude with strict grounding instructions.
  * If no chunk scores above trust threshold (or Claude says "not covered"),
    we decline and suggest the nearest owner.

Tenancy:
  Every chunk carries org_id and business_unit_id in the index itself, and
  search() filters on them in SQL, before ranking and the top-k cut, so one
  organization's chunks can neither reach another's prompt nor crowd its own
  results out of the top k. Documents copy both columns from aria_documents.
  Controls and risks have no org column in their source tables (PostgreSQL
  isolates them by tenant schema), so they are stamped with the tenant bound
  when they are indexed; NULL (no tenant bound) stays visible to everyone in
  that schema or database, as it was before scoping existed.
  _filter_chunks_by_scope remains as a live-row check on document chunks.

Engine-specific entry points:
  _search_sqlite(): FTS5 MATCH + bm25()
  _search_pg()     : tsvector @@ to_tsquery() + ts_rank_cd()
  rebuild_index()  : drop/recreate + reindex all (use after PG cutover)
"""
from __future__ import annotations

import logging
import re
import json
from datetime import datetime
from typing import Optional

log = logging.getLogger("oneforall.aria")

from config import settings
from database import get_db, get_current_org, insert_returning_id
from modules.aria.ai_generator import _call_ai


# ── Search index DDL: engine-specific ───────────────────────────────────────

_FTS_DDL_SQLITE = """
CREATE VIRTUAL TABLE IF NOT EXISTS aria_ask_index USING fts5(
    content_type,
    content_id,
    title,
    section,
    body,
    owner,
    framework,
    control_ref,
    url_path,
    org_id UNINDEXED,
    business_unit_id UNINDEXED,
    tokenize = 'porter unicode61'
);
"""

_FTS_DDL_PG = """\
CREATE TABLE IF NOT EXISTS aria_ask_index (
    id           SERIAL PRIMARY KEY,
    content_type TEXT NOT NULL DEFAULT '',
    content_id   TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL DEFAULT '',
    section      TEXT NOT NULL DEFAULT '',
    body         TEXT NOT NULL DEFAULT '',
    owner        TEXT NOT NULL DEFAULT '',
    framework    TEXT NOT NULL DEFAULT '',
    control_ref  TEXT NOT NULL DEFAULT '',
    url_path     TEXT NOT NULL DEFAULT '',
    org_id       INTEGER,
    business_unit_id INTEGER,
    body_tsv     tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(section, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(body, '')), 'C')
    ) STORED
);
CREATE INDEX IF NOT EXISTS idx_aria_ask_index_tsv ON aria_ask_index USING GIN(body_tsv);
CREATE INDEX IF NOT EXISTS idx_aria_ask_index_cid ON aria_ask_index(content_type, content_id);
"""


def _index_columns(db) -> set:
    """Column names of aria_ask_index in the CURRENT schema (empty if absent)."""
    if settings.is_postgres():
        rows = db.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'aria_ask_index'"
        ).fetchall()
        return {r["column_name"] for r in rows}
    return {r["name"] for r in db.execute("PRAGMA table_info(aria_ask_index)").fetchall()}


def init_index():
    """Create the search index table/virtual-table if it doesn't exist, and
    upgrade one built before scoping existed (no org_id column).

    The check is one catalog read, cheap enough to run before every question
    and every write. It also guarantees the table exists in the CURRENT tenant
    schema: an unqualified table name otherwise falls through the PostgreSQL
    search_path to the shared public table, so a tenant that has not built its
    own index yet would read and write the default organization's.
    """
    pg = settings.is_postgres()
    db = get_db()
    try:
        cols = _index_columns(db)
        if "org_id" in cols:
            return
        if cols and not pg:
            # FTS5 virtual tables cannot be altered. The index is derived data,
            # so drop it; "Rebuild index" repopulates it (same as a fresh install).
            db.execute("DROP TABLE aria_ask_index")
        db.executescript(_FTS_DDL_PG if pg else _FTS_DDL_SQLITE)
        if cols and pg:
            # Keep the existing rows so search keeps answering during the upgrade.
            # Documents take their scope from the source row now; controls and
            # risks stay NULL (visible, as before) until the next rebuild stamps them.
            db.execute("ALTER TABLE aria_ask_index ADD COLUMN IF NOT EXISTS org_id INTEGER")
            db.execute("ALTER TABLE aria_ask_index ADD COLUMN IF NOT EXISTS business_unit_id INTEGER")
            db.execute(
                "UPDATE aria_ask_index SET "
                "org_id = (SELECT d.org_id FROM aria_documents d "
                "          WHERE d.doc_id = aria_ask_index.content_id), "
                "business_unit_id = (SELECT d.business_unit_id FROM aria_documents d "
                "          WHERE d.doc_id = aria_ask_index.content_id) "
                "WHERE content_type = 'document'"
            )
        db.commit()
    finally:
        db.close()


def rebuild_index() -> int:
    """
    Drop and recreate the search index then reindex all content.
    Use once after PostgreSQL cutover to populate the tsvector GIN index,
    or after major schema changes.  Returns the number of indexed chunks.
    """
    # DROP resolves the unqualified name through the PostgreSQL search_path: make
    # sure this tenant's own table exists first so it, not public's, is dropped.
    init_index()
    db = get_db()
    try:
        db.execute("DROP TABLE IF EXISTS aria_ask_index")
        db.commit()
    finally:
        db.close()
    return rebuild_all()


# ── Chunking ────────────────────────────────────────────────────────────────

_H2_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")


def _chunk_markdown(md: str) -> list[tuple[str, str]]:
    """
    Split markdown into (section_title, section_body) pairs by H2 headings.
    Preamble (before the first H2) is returned with section_title='Overview'.
    Returns at least one chunk even if no H2 is found.
    """
    if not md:
        return []
    positions = [(m.start(), m.group(1).strip()) for m in _H2_RE.finditer(md)]
    if not positions:
        return [("Overview", md.strip())]
    chunks: list[tuple[str, str]] = []
    if positions[0][0] > 0:
        pre = md[: positions[0][0]].strip()
        if pre:
            chunks.append(("Overview", pre))
    for i, (pos, title) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(md)
        body = md[pos:end]
        body = re.sub(r"^##\s+.+?\n", "", body, count=1).strip()
        if body:
            chunks.append((title, body))
    return chunks


# ── Index build / sync ──────────────────────────────────────────────────────

def _clear_by(content_type: str, content_id: str):
    # Every write path (reindex_*, remove_from_index) starts here and inserts
    # afterwards in the same tenant context, so this is the one place that
    # guarantees the table exists in the current schema before any write.
    init_index()
    db = get_db()
    try:
        db.execute(
            "DELETE FROM aria_ask_index "
            "WHERE content_type=%s AND content_id=%s",
            (content_type, str(content_id)),
        )
        db.commit()
    finally:
        db.close()


def remove_from_index(content_type: str, content_id: str):
    """Public helper: remove all chunks for a given content_type/content_id."""
    _clear_by(content_type, str(content_id))


def reindex_document(doc_id: str):
    """(Re)index a single document by doc_id.

    PLAN-35 T09 (section 10.2): "never index editable drafts or candidate
    bodies" and index the *current* version. For a policy-workflow-managed
    document, aria_documents.body is set once at confirm time and never
    refreshed on later revisions -- the durable content lives on the
    immutable aria_policy_versions row instead, promoted only on approval.

    A managed document's current_policy_version_id is NOT itself proof of
    approval: confirm_draft sets it immediately for a brand-new document's
    very first version, which is inserted with state='draft' and stays
    that way until someone actually approves it (this is deliberate --
    section 6.3's projection rules need a "points at itself" candidate
    before it is ever decided). aria_documents.body holds that exact same
    unapproved candidate text at that point, so falling back to it here
    would index a draft/candidate body after all -- confirmed reachable
    directly through the admin "rebuild index" action, not just a
    theoretical race. A managed document therefore indexes its current
    version's body only when that version's state is actually 'approved';
    otherwise it is removed from the index (nothing effective exists yet
    to search), never backed by the document row's own body/comments.
    Legacy (non-managed) documents are unaffected: they keep reading
    aria_documents.body/comments exactly as before.
    """
    db = get_db()
    try:
        doc = db.execute(
            "SELECT * FROM aria_documents WHERE doc_id=%s", (doc_id,)
        ).fetchone()
        if not doc:
            return
        doc = dict(doc)
        is_managed = bool(doc.get("policy_workflow_managed"))
        if is_managed:
            body_source = None
            if doc.get("current_policy_version_id"):
                version = db.execute(
                    "SELECT body, state FROM aria_policy_versions WHERE id=%s",
                    (doc["current_policy_version_id"],),
                ).fetchone()
                if version and version["state"] == "approved":
                    body_source = version["body"] or ""
            if body_source is None:
                _clear_by("document", doc_id)
                return
        else:
            body_source = doc.get("body") or doc.get("comments") or ""
    finally:
        db.close()

    _clear_by("document", doc_id)

    body = body_source
    if body.strip():
        chunks = _chunk_markdown(body)
    else:
        chunks = [("Metadata",
            f"{doc['title']} -- {doc['doc_type']} "
            f"({doc['framework']} {doc['control_ref'] or ''}). "
            f"Owner: {doc['owner'] or 'unassigned'}. "
            f"Status: {doc['status']}.")]

    db = get_db()
    try:
        for section, text in chunks:
            db.execute(
                "INSERT INTO aria_ask_index "
                "(content_type, content_id, title, section, body, "
                " owner, framework, control_ref, url_path, "
                " org_id, business_unit_id) "
                "VALUES ('document', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (doc_id, doc["title"], section, text,
                 doc["owner"] or "", doc["framework"] or "",
                 doc["control_ref"] or "",
                 f"/aria/documents",
                 doc.get("org_id"), doc.get("business_unit_id")),
            )
        db.commit()
    finally:
        db.close()


def reindex_control(control_id: int):
    """(Re)index a single control by its numeric id."""
    db = get_db()
    try:
        ctrl = db.execute(
            "SELECT c.*, f.name AS fw_name, f.id AS fw_id "
            "FROM controls c "
            "JOIN frameworks f ON c.framework_id = f.id "
            "WHERE c.id=%s",
            (control_id,),
        ).fetchone()
    finally:
        db.close()
    if not ctrl:
        return

    _clear_by("control", str(control_id))

    body_parts = [ctrl["description"] or ""]
    if ctrl["notes"]:
        body_parts.append(f"Notes: {ctrl['notes']}")
    body_parts.append(
        f"Status: {ctrl['status']}. "
        f"Owner: {ctrl['owner'] or 'unassigned'}."
    )
    body = "\n\n".join(p for p in body_parts if p)

    db = get_db()
    try:
        db.execute(
            "INSERT INTO aria_ask_index "
            "(content_type, content_id, title, section, body, "
            " owner, framework, control_ref, url_path, org_id) "
            "VALUES ('control', %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (str(control_id),
             f"{ctrl['ref']} -- {ctrl['name']}",
             ctrl["category"] or "",
             body,
             ctrl["owner"] or "",
             ctrl["fw_name"],
             ctrl["ref"],
             f"/aria/framework/{ctrl['fw_id']}",
             get_current_org()),
        )
        db.commit()
    finally:
        db.close()


def reindex_risk(risk_id: str):
    """(Re)index a single risk by its risk_id string."""
    db = get_db()
    try:
        risk = db.execute(
            "SELECT * FROM aria_risks WHERE risk_id=%s", (risk_id,)
        ).fetchone()
    finally:
        db.close()
    if not risk:
        return

    _clear_by("risk", risk_id)

    body = f"{risk['description']}"
    if risk["mitigation"]:
        body += f"\n\nMitigation: {risk['mitigation']}"
    body += (
        f"\n\nLikelihood: {risk['likelihood']}/5. "
        f"Impact: {risk['impact']}/5. "
        f"Owner: {risk['owner'] or 'unassigned'}. "
        f"Status: {risk['status']}."
    )

    db = get_db()
    try:
        db.execute(
            "INSERT INTO aria_ask_index "
            "(content_type, content_id, title, section, body, "
            " owner, framework, control_ref, url_path, org_id) "
            "VALUES ('risk', %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (risk_id,
             f"{risk_id} -- {risk['description'][:60]}",
             risk["category"] or "",
             body,
             risk["owner"] or "",
             risk["framework"] or "",
             risk["control_ref"] or "",
             "/aria/risks",
             get_current_org()),
        )
        db.commit()
    finally:
        db.close()


def rebuild_all() -> int:
    """Full rebuild of the search index.  Returns number of indexed chunks."""
    init_index()
    db = get_db()
    try:
        db.execute("DELETE FROM aria_ask_index")
        db.commit()
        doc_ids = [
            r["doc_id"]
            for r in db.execute("SELECT doc_id FROM aria_documents").fetchall()
        ]
        ctrl_ids = [
            r["id"]
            for r in db.execute("SELECT id FROM controls").fetchall()
        ]
        risk_ids = [
            r["risk_id"]
            for r in db.execute("SELECT risk_id FROM aria_risks").fetchall()
        ]
    finally:
        db.close()

    for d in doc_ids:
        reindex_document(d)
    for c in ctrl_ids:
        reindex_control(c)
    for r in risk_ids:
        reindex_risk(r)

    db = get_db()
    try:
        n = db.execute("SELECT COUNT(*) FROM aria_ask_index").fetchone()[0]
    finally:
        db.close()
    return n


# ── Retrieval ───────────────────────────────────────────────────────────────

_STOPWORDS = set(
    "a an the of for to in on is are was were be been being do does did "
    "have has had can could should would may might will shall must "
    "i you he she it we they me him her us them my your his its our their "
    "what when where why how which who whom whose that this these those "
    "and or but not if else also as at by from with into onto over under "
    "about against through during before after above below between".split()
)

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def _build_fts_query(question: str) -> str:
    """Return an engine-appropriate FTS query string from a natural-language question."""
    tokens = [t.lower() for t in _TOKEN_RE.findall(question)]
    tokens = [t for t in tokens if t not in _STOPWORDS and len(t) > 2]
    if not tokens:
        tokens = [t.lower() for t in _TOKEN_RE.findall(question)][:6]
    seen, uniq = set(), []
    for t in tokens:
        if t not in seen:
            uniq.append(t)
            seen.add(t)
    uniq = uniq[:12]
    if settings.is_postgres():
        # tsquery prefix-match; sanitize to [a-z0-9] to avoid parse errors
        clean = [re.sub(r'[^a-z0-9]', '', t) for t in uniq]
        return " | ".join(f"{t}:*" for t in clean if t)
    # FTS5 prefix-match syntax
    return " OR ".join(f"{t}*" for t in uniq)


def _scope_sql(user: dict) -> tuple[str, list]:
    """WHERE fragment (parenthesized) + params limiting the index to what
    `user` may see, over the index's own org_id/business_unit_id columns.

    Same rule as policy_access.document_read_ok. A NULL org_id is unscoped
    (a legacy document, or a control/risk indexed with no tenant bound) and
    stays visible. A scoped row needs the user's org and, when the row has a
    business unit, a unit inside the user's scope (None scope = super admin,
    any unit in their own org). Documents are re-checked against the live
    row afterwards by _filter_chunks_by_scope.
    """
    from modules.governance.data_service import bu_scope_ids
    scope = bu_scope_ids(user)
    if scope is None:
        return "(org_id IS NULL OR org_id = %s)", [user.get("org_id")]
    marks = ",".join(["%s"] * len(scope))
    return (
        "(org_id IS NULL OR (org_id = %s AND "
        f"(business_unit_id IS NULL OR business_unit_id IN ({marks}))))",
        [user.get("org_id"), *scope],
    )


def indexed_count(user: dict) -> int:
    """How many index chunks `user` may retrieve: the figure on the Ask ARIA page header."""
    init_index()  # so a tenant that has not built an index yet reads its own empty table, not public's
    scope_sql, scope_params = _scope_sql(user)
    db = get_db()
    try:
        return db.execute(
            f"SELECT COUNT(*) FROM aria_ask_index WHERE {scope_sql}", scope_params
        ).fetchone()[0]
    finally:
        db.close()


def search(question: str, k: int = 8, framework_filter: str = "",
           user: Optional[dict] = None) -> list[dict]:
    """Return top-k chunks the asking user may see, as dicts with a relevance score.
    The user's org/BU scope is part of the query, so it is applied before
    ranking and the top-k cut: another tenant's chunks can neither be
    returned nor crowd this user's out. No user means no results (the index
    is not an authorization database).
    If framework_filter is set, restricts to that framework; falls back
    to unfiltered (but still scoped) results if the filtered set is empty.
    A failed query raises: it is an outage, not "nothing matched", and ask()
    reports it as one instead of telling the user no policy covers them.
    """
    q = _build_fts_query(question)
    if not q or not user:
        return []
    scope_sql, scope_params = _scope_sql(user)
    fw = (framework_filter or "").strip()
    db = get_db()
    try:
        if settings.is_postgres():
            return _search_pg(db, q, k, fw, scope_sql, scope_params)
        return _search_sqlite(db, q, k, fw, scope_sql, scope_params)
    finally:
        db.close()


def _search_sqlite(db, q: str, k: int, fw: str,
                   scope_sql: str, scope_params: list) -> list[dict]:
    """FTS5-backed search for SQLite."""
    base_sql = (
        "SELECT content_type, content_id, title, section, body, "
        "       owner, framework, control_ref, url_path, "
        "       bm25(aria_ask_index) AS score "
        "FROM aria_ask_index "
        "WHERE aria_ask_index MATCH %s AND " + scope_sql + " "
    )
    args = (q, *scope_params)
    rows = []
    if fw:
        rows = db.execute(
            base_sql + "AND framework = %s ORDER BY score LIMIT %s", (*args, fw, k)
        ).fetchall()
    if not rows:
        rows = db.execute(base_sql + "ORDER BY score LIMIT %s", (*args, k)).fetchall()
    return [dict(r) for r in rows]


def _search_pg(db, q: str, k: int, fw: str,
               scope_sql: str, scope_params: list) -> list[dict]:
    """tsvector-backed search for PostgreSQL."""
    base_sql = (
        "SELECT content_type, content_id, title, section, body, "
        "       owner, framework, control_ref, url_path, "
        "       ts_rank_cd(body_tsv, to_tsquery('english', %s)) AS score "
        "FROM aria_ask_index "
        "WHERE body_tsv @@ to_tsquery('english', %s) AND " + scope_sql + " "
    )
    args = (q, q, *scope_params)
    rows = []
    if fw:
        rows = db.execute(
            base_sql + "AND framework = %s ORDER BY score DESC LIMIT %s", (*args, fw, k)
        ).fetchall()
    if not rows:
        # Only reached after the filtered query succeeded and matched nothing.
        # A failed query raises: it is an outage, not an empty answer.
        rows = db.execute(base_sql + "ORDER BY score DESC LIMIT %s", (*args, k)).fetchall()
    return [dict(r) for r in rows]


# ── Prompt assembly + Claude call ───────────────────────────────────────────

_ASK_SYSTEM_PROMPT = (
    "You are ARIA's policy assistant. You answer employee questions "
    "ONLY using the organisation's own policies, controls, and risk register "
    "entries provided to you in the <context> block. You never use outside "
    "knowledge.\n\n"
    "Rules:\n"
    "1. If the context contains a clear answer, answer plainly in 1-3 short "
    "paragraphs. Use everyday language -- no legalese unless the policy "
    "itself uses it.\n"
    "2. After the answer, list the specific source citations you used as a "
    "JSON array in a fenced ```json block, with entries of the form "
    '{"title": "...", "section": "...", "url_path": "...", '
    '"content_type": "..."}.\n'
    "3. If the context does NOT contain enough information to answer "
    "confidently, respond with exactly the single word NOT_COVERED on its "
    "own line, followed by a JSON block "
    '{"nearest_owner": "...", "framework": "...", "reason": "..."} '
    "identifying the most relevant policy owner to direct the employee to.\n"
    "4. Never invent policy text, dates, or names. Never speculate.\n"
    "5. Keep the answer concise and actionable. Prefer bullet points for "
    "procedural steps."
)


def _format_context(chunks: list[dict]) -> str:
    lines = []
    for i, c in enumerate(chunks, 1):
        lines.append(
            f"[{i}] type={c['content_type']} | title={c['title']} "
            f"| section={c['section'] or chr(8212)} "
            f"| framework={c['framework'] or chr(8212)} "
            f"| owner={c['owner'] or chr(8212)} "
            f"| url={c['url_path']}\n{c['body']}\n"
        )
    return "\n---\n".join(lines)


def _extract_json_block(text: str) -> tuple[str, Optional[dict | list]]:
    """Return (text_without_json_block, parsed_json_or_none)."""
    m = re.search(r"```json\s*(.+?)\s*```", text, re.S)
    if not m:
        return text.strip(), None
    try:
        parsed = json.loads(m.group(1))
    except Exception:
        return text.strip(), None
    cleaned = (text[: m.start()] + text[m.end():]).strip()
    return cleaned, parsed


_GREETING_RE = re.compile(
    r"^(hi+|hello+|hey+|good\s+(morning|afternoon|evening|day)|howdy|greetings|"
    r"sup|what'?s\s+up|yo+|hiya|hola|salut|bonjour|ciao|namaste|"
    r"how\s+are\s+you|how('?s|\s+is)\s+(it\s+going|things)|"
    r"nice\s+to\s+meet\s+you|who\s+are\s+you|what\s+(can|do)\s+you\s+do|"
    r"thanks?|thank\s+you|cheers|bye|goodbye|see\s+you|take\s+care|"
    r"ok(ay)?|sure|got\s+it|understood|noted|cool|great|awesome)"
    r"[!?.]*\s*$",
    re.IGNORECASE,
)

_GREETING_RESPONSE = (
    "Hi! I'm ARIA, your AI policy assistant. I can answer questions grounded in "
    "your organisation's published compliance policies, controls, and risk register. "
    "Try asking things like: \"What is our data retention policy?\", "
    "\"Who is responsible for access control reviews?\", or "
    "\"What controls do we have for third-party vendor risk?\""
)


def _filter_chunks_by_scope(chunks: list[dict], user: Optional[dict]) -> list[dict]:
    """PLAN-35 T08 (section 10.2): "The Ask ARIA index is not an
    authorization database. Join/validate every document hit against the
    current authorized document before sending text to an AI provider."

    search() now applies the asking user's org/BU scope inside the query
    (see _scope_sql), before ranking and the top-k cut. This post-filter
    stays as defense in depth for documents because it checks the LIVE
    aria_documents row: it catches an index row that went stale (document
    deleted, or moved to another BU or org after it was indexed) and one with
    no stamp (NULL org_id, e.g. written before the scoping columns existed).

    Scoped to content_type == 'document' only: aria_documents rows carry
    org_id/business_unit_id/policy_workflow_managed (T01) and
    policy_access.document_read_ok (T02) is the rule. Control and risk
    chunks have no live source row to re-check (their tables have no org
    column), so for them the stamp applied in SQL is the only scope; they
    pass through here unchanged.
    """
    if not user:
        return []  # no actor at all: nothing is authorized to retrieve
    document_chunks = [c for c in chunks if c.get("content_type") == "document"]
    other_chunks = [c for c in chunks if c.get("content_type") != "document"]
    if not document_chunks:
        return chunks

    from modules.aria.policy_access import document_read_ok
    doc_ids = {c["content_id"] for c in document_chunks}
    db = get_db()
    try:
        placeholders = ",".join(["%s"] * len(doc_ids))
        rows = db.execute(
            f"SELECT doc_id, org_id, business_unit_id, policy_workflow_managed "
            f"FROM aria_documents WHERE doc_id IN ({placeholders})",
            list(doc_ids),
        ).fetchall()
    finally:
        db.close()
    scope_by_doc_id = {r["doc_id"]: dict(r) for r in rows}

    allowed_document_chunks = [
        c for c in document_chunks
        if c["content_id"] in scope_by_doc_id and document_read_ok(user, scope_by_doc_id[c["content_id"]])
    ]
    return other_chunks + allowed_document_chunks


async def ask(question: str, user: Optional[dict] = None,
              framework_filter: str = "",
              conversation_history: list = None) -> dict:
    """
    Answer a question grounded in the corpus.

    Returns dict with keys: success, covered, answer, citations,
    nearest_owner, framework, chunks_retrieved, latency_ms, error, log_id.
    """
    started = datetime.now()
    ms = lambda: int((datetime.now() - started).total_seconds() * 1000)

    if _GREETING_RE.match(question.strip()):
        result = {
            "success": True, "covered": True,
            "answer": _GREETING_RESPONSE,
            "citations": [], "nearest_owner": None, "framework": None,
            "chunks_retrieved": 0, "latency_ms": ms(), "error": None,
        }
        result["log_id"] = _log_qa(user, question, result)
        return result

    try:
        init_index()
        chunks = search(question, k=8, framework_filter=framework_filter, user=user)
        chunks = _filter_chunks_by_scope(chunks, user)
    except Exception:
        # An outage, not "nothing matched". Say so, and keep it out of the Q&A
        # log so it is not counted as a question the policies do not cover.
        log.exception("Ask ARIA retrieval failed")
        return {
            "success": False, "covered": False, "answer": "",
            "citations": [], "nearest_owner": None, "framework": None,
            "chunks_retrieved": 0, "latency_ms": ms(),
            "error": "Search is temporarily unavailable. Please try again in a moment.",
            "log_id": None,
        }
    if not chunks:
        result = {
            "success": True, "covered": False,
            "answer": (
                "I couldn't find anything in our policies or controls "
                "that speaks to that. Try rephrasing, or ask your manager "
                "or the Compliance team."
            ),
            "citations": [], "nearest_owner": None, "framework": None,
            "chunks_retrieved": 0, "latency_ms": ms(), "error": None,
        }
        result["log_id"] = _log_qa(user, question, result)
        return result

    context_block = _format_context(chunks)
    user_msg = (
        f"<context>\n{context_block}\n</context>\n\n"
        f"<question>{question.strip()}</question>\n\n"
        "Answer following the rules. Remember: if the context is "
        "insufficient, respond with NOT_COVERED + JSON as described."
    )

    try:
        prior = list(conversation_history or [])[-6:]
        msgs = prior + [{"role": "user", "content": user_msg}]
        raw_text, _meta = await _call_ai(
            _ASK_SYSTEM_PROMPT, user_msg, max_tokens=1200, messages=msgs
        )
        raw = raw_text.strip()
    except RuntimeError as exc:
        log.exception("Ask ARIA runtime error during AI call")
        _msg = str(exc).lower()
        if "not configured" in _msg or "api_key" in _msg:
            user_error = "The AI assistant is not configured on this platform. Please contact your administrator."
        else:
            user_error = "The AI assistant is temporarily unavailable. Please try again in a moment."
        return {
            "success": False, "covered": False, "answer": "",
            "citations": [], "nearest_owner": None, "framework": None,
            "chunks_retrieved": len(chunks), "latency_ms": ms(),
            "error": user_error, "log_id": None,
        }
    except Exception:
        log.exception("Ask ARIA unexpected error during AI call")
        return {
            "success": False, "covered": False, "answer": "",
            "citations": [], "nearest_owner": None, "framework": None,
            "chunks_retrieved": len(chunks), "latency_ms": ms(),
            "error": "Something went wrong. Please try again in a moment.", "log_id": None,
        }

    # ── Parse response ────────────────────────────────────────────────────
    if raw.startswith("NOT_COVERED"):
        _rest, parsed = _extract_json_block(raw[len("NOT_COVERED"):].strip())
        parsed = parsed or {}
        nearest_owner = (parsed.get("nearest_owner") or
                         _guess_nearest_owner(chunks))
        framework = parsed.get("framework") or (
            chunks[0]["framework"] if chunks else None)
        reason     = parsed.get("reason", "")
        owner_line = f" Try asking **{nearest_owner}**" if nearest_owner else ""
        result = {
            "success": True, "covered": False,
            "answer": (
                "We don't have a policy that directly answers that."
                + (f" {reason}" if reason else "")
                + owner_line + "."
            ),
            "citations": [], "nearest_owner": nearest_owner,
            "framework": framework,
            "chunks_retrieved": len(chunks), "latency_ms": ms(), "error": None,
        }
        result["log_id"] = _log_qa(user, question, result)
        return result

    answer_text, citations_json = _extract_json_block(raw)
    citations = citations_json if isinstance(citations_json, list) else []
    result = {
        "success": True, "covered": True,
        "answer": answer_text, "citations": citations,
        "nearest_owner": None, "framework": None,
        "chunks_retrieved": len(chunks), "latency_ms": ms(), "error": None,
    }
    result["log_id"] = _log_qa(user, question, result)
    return result


def _guess_nearest_owner(chunks: list[dict]) -> Optional[str]:
    """Fall back to the most common owner in the top chunks."""
    counts: dict[str, int] = {}
    for c in chunks:
        o = (c.get("owner") or "").strip()
        if o:
            counts[o] = counts.get(o, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _log_qa(user: Optional[dict], question: str, result: dict) -> Optional[int]:
    """Log the Q&A interaction to aria_ask_log. Returns the inserted row id."""
    try:
        db = get_db()
        try:
            cur = insert_returning_id(db,
                "INSERT INTO aria_ask_log "
                "(user_id, username, question, answer, covered, "
                " citations, latency_ms) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    (user or {}).get("id"),
                    (user or {}).get("username"),
                    question,
                    result.get("answer", ""),
                    1 if result.get("covered") else 0,
                    json.dumps(result.get("citations", [])),
                    result.get("latency_ms", 0),
                ),
            )
            db.commit()
            return cur
        finally:
            db.close()
    except Exception:
        return None
