"""
Ask ARIA — AI Q&A over the ARIA corpus (policies, controls, documents, risks).

Design:
  * SQLite: FTS5 virtual table `aria_ask_index` (BM25 ranking via bm25()).
  * PostgreSQL: regular table with `body_tsv tsvector GENERATED ALWAYS AS ...`
    + GIN index; ranking via ts_rank_cd().
  * Policies (long markdown) are chunked by H2 section headings.
  * Controls, risks, and document metadata are single chunks.
  * Top-N chunks are handed to Claude with strict grounding instructions.
  * If no chunk scores above trust threshold (or Claude says "not covered"),
    we decline and suggest the nearest owner.

Engine-specific entry points:
  _search_sqlite() — FTS5 MATCH + bm25()
  _search_pg()     — tsvector @@ to_tsquery() + ts_rank_cd()
  rebuild_index()  — drop/recreate + reindex all (use after PG cutover)
"""
from __future__ import annotations

import re
import json
import httpx
from datetime import datetime
from typing import Optional

from config import settings
from database import get_db, insert_returning_id, OperationalError
from modules.aria.ai_generator import CLAUDE_MODEL, _call_ai


# ── Search index DDL — engine-specific ──────────────────────────────────────

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
    body_tsv     tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(section, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(body, '')), 'C')
    ) STORED
);
CREATE INDEX IF NOT EXISTS idx_aria_ask_index_tsv ON aria_ask_index USING GIN(body_tsv);
CREATE INDEX IF NOT EXISTS idx_aria_ask_index_cid ON aria_ask_index(content_type, content_id);
"""


def init_index():
    """Create the search index table/virtual-table if it doesn't exist."""
    ddl = _FTS_DDL_PG if settings.is_postgres() else _FTS_DDL_SQLITE
    db = get_db()
    try:
        db.executescript(ddl)
        db.commit()
    finally:
        db.close()


def rebuild_index() -> int:
    """
    Drop and recreate the search index then reindex all content.
    Use once after PostgreSQL cutover to populate the tsvector GIN index,
    or after major schema changes.  Returns the number of indexed chunks.
    """
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
    """(Re)index a single document by doc_id."""
    db = get_db()
    try:
        doc = db.execute(
            "SELECT * FROM aria_documents WHERE doc_id=%s", (doc_id,)
        ).fetchone()
    finally:
        db.close()
    if not doc:
        return

    _clear_by("document", doc_id)

    body = doc["body"] or doc["comments"] or ""
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
                " owner, framework, control_ref, url_path) "
                "VALUES ('document', %s, %s, %s, %s, %s, %s, %s, %s)",
                (doc_id, doc["title"], section, text,
                 doc["owner"] or "", doc["framework"] or "",
                 doc["control_ref"] or "",
                 f"/aria/documents"),
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
            "FROM aria_controls c "
            "JOIN aria_frameworks f ON c.framework_id = f.id "
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
            " owner, framework, control_ref, url_path) "
            "VALUES ('control', %s, %s, %s, %s, %s, %s, %s, %s)",
            (str(control_id),
             f"{ctrl['ref']} -- {ctrl['name']}",
             ctrl["category"] or "",
             body,
             ctrl["owner"] or "",
             ctrl["fw_name"],
             ctrl["ref"],
             f"/aria/framework/{ctrl['fw_id']}"),
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
            " owner, framework, control_ref, url_path) "
            "VALUES ('risk', %s, %s, %s, %s, %s, %s, %s, %s)",
            (risk_id,
             f"{risk_id} -- {risk['description'][:60]}",
             risk["category"] or "",
             body,
             risk["owner"] or "",
             risk["framework"] or "",
             risk["control_ref"] or "",
             "/aria/risks"),
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
            for r in db.execute("SELECT id FROM aria_controls").fetchall()
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


def search(question: str, k: int = 8,
           framework_filter: str = "") -> list[dict]:
    """Return top-k chunks as dicts with a relevance score.
    If framework_filter is set, restricts to that framework; falls back
    to unfiltered results if the filtered set is empty.
    """
    q = _build_fts_query(question)
    if not q:
        return []
    db = get_db()
    try:
        if settings.is_postgres():
            return _search_pg(db, q, k, (framework_filter or "").strip())
        return _search_sqlite(db, q, k, (framework_filter or "").strip())
    finally:
        db.close()


def _search_sqlite(db, q: str, k: int, fw: str) -> list[dict]:
    """FTS5-backed search for SQLite."""
    base_sql = (
        "SELECT content_type, content_id, title, section, body, "
        "       owner, framework, control_ref, url_path, "
        "       bm25(aria_ask_index) AS score "
        "FROM aria_ask_index "
        "WHERE aria_ask_index MATCH %s "
    )
    if fw:
        try:
            rows = db.execute(
                base_sql + "AND framework = %s ORDER BY score LIMIT %s",
                (q, fw, k),
            ).fetchall()
        except OperationalError:
            rows = []
        if not rows:
            try:
                rows = db.execute(
                    base_sql + "ORDER BY score LIMIT %s", (q, k)
                ).fetchall()
            except OperationalError:
                rows = []
    else:
        try:
            rows = db.execute(
                base_sql + "ORDER BY score LIMIT %s", (q, k)
            ).fetchall()
        except OperationalError:
            rows = []
    return [dict(r) for r in rows]


def _search_pg(db, q: str, k: int, fw: str) -> list[dict]:
    """tsvector-backed search for PostgreSQL."""
    import logging as _logging
    _log = _logging.getLogger(__name__)
    base_sql = (
        "SELECT content_type, content_id, title, section, body, "
        "       owner, framework, control_ref, url_path, "
        "       ts_rank_cd(body_tsv, to_tsquery('english', %s)) AS score "
        "FROM aria_ask_index "
        "WHERE body_tsv @@ to_tsquery('english', %s) "
    )
    if fw:
        try:
            rows = db.execute(
                base_sql + "AND framework = %s ORDER BY score DESC LIMIT %s",
                (q, q, fw, k),
            ).fetchall()
        except Exception as exc:
            _log.warning("ARIA PG search (fw=%s) failed: %s", fw, exc)
            db.rollback()
            rows = []
        if not rows:
            try:
                rows = db.execute(
                    base_sql + "ORDER BY score DESC LIMIT %s", (q, q, k)
                ).fetchall()
            except Exception as exc:
                _log.warning("ARIA PG search (no-fw fallback) failed: %s", exc)
                db.rollback()
                rows = []
    else:
        try:
            rows = db.execute(
                base_sql + "ORDER BY score DESC LIMIT %s", (q, q, k)
            ).fetchall()
        except Exception as exc:
            _log.warning("ARIA PG search failed: %s", exc)
            db.rollback()
            rows = []
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


async def ask(question: str, user: Optional[dict] = None,
              framework_filter: str = "") -> dict:
    """
    Answer a question grounded in the corpus.

    Returns dict with keys: success, covered, answer, citations,
    nearest_owner, framework, chunks_retrieved, latency_ms, error, log_id.
    """
    started = datetime.now()
    ms = lambda: int((datetime.now() - started).total_seconds() * 1000)

    init_index()
    chunks = search(question, k=8, framework_filter=framework_filter)
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
        raw_text, _meta = await _call_ai(
            _ASK_SYSTEM_PROMPT, user_msg, max_tokens=1200
        )
        raw = raw_text.strip()
    except RuntimeError as e:
        return {
            "success": False, "covered": False, "answer": "",
            "citations": [], "nearest_owner": None, "framework": None,
            "chunks_retrieved": len(chunks), "latency_ms": ms(),
            "error": str(e), "log_id": None,
        }
    except Exception as e:
        return {
            "success": False, "covered": False, "answer": "",
            "citations": [], "nearest_owner": None, "framework": None,
            "chunks_retrieved": len(chunks), "latency_ms": ms(),
            "error": str(e), "log_id": None,
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
