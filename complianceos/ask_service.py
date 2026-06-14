"""
ask_service.py — AI Q&A over the ARIA corpus (policies, controls, documents, risks).

Design:
  * SQLite FTS5 virtual table `ask_index` holds all searchable chunks.
  * Policies (long markdown) are chunked by H2 section headings.
  * Controls, risks, and document metadata are single chunks.
  * Retrieval uses BM25 ranking. We take top N chunks, hand them to Claude
    with strict grounding instructions, and parse answer + citations.
  * If no chunk scores above a trust threshold (or Claude says "not covered"),
    we decline and suggest the nearest owner.
"""
from __future__ import annotations
import os, re, json, sqlite3, asyncio, httpx
from datetime import datetime
from typing import Optional

from database import DB_PATH
from ai_generator import get_api_key, CLAUDE_MODEL

# ── FTS5 index setup ──────────────────────────────────────────────────────────

FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS ask_index USING fts5(
    content_type,     -- 'document' | 'control' | 'risk'
    content_id,       -- stable id: doc_id, control.id, risk_id
    title,
    section,          -- H2 section name for policy chunks, else ''
    body,             -- searchable text
    owner,
    framework,
    control_ref,
    url_path,         -- where to link in the UI
    tokenize = 'porter unicode61'
);
"""

ASK_LOG_DDL = """
CREATE TABLE IF NOT EXISTS ask_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    question TEXT,
    answer TEXT,
    covered INTEGER DEFAULT 1,
    citations TEXT,
    latency_ms INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_index():
    """Create the FTS5 virtual table and ask_log table if they don't exist."""
    conn = _db()
    conn.execute(FTS_DDL)
    conn.execute(ASK_LOG_DDL)
    conn.commit()
    conn.close()


# ── Chunking ──────────────────────────────────────────────────────────────────

H2_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")


def _chunk_markdown(md: str) -> list[tuple[str, str]]:
    """
    Split markdown into (section_title, section_body) pairs by H2 headings.
    Preamble (before the first H2) is returned with section_title='Overview'.
    Returns at least one chunk even if no H2 is found.
    """
    if not md:
        return []
    positions = [(m.start(), m.group(1).strip()) for m in H2_RE.finditer(md)]
    if not positions:
        return [("Overview", md.strip())]
    chunks: list[tuple[str, str]] = []
    # Preamble
    if positions[0][0] > 0:
        pre = md[: positions[0][0]].strip()
        if pre:
            chunks.append(("Overview", pre))
    for i, (pos, title) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(md)
        body = md[pos:end]
        # Drop the heading line itself to keep chunk text focused
        body = re.sub(r"^##\s+.+?\n", "", body, count=1).strip()
        if body:
            chunks.append((title, body))
    return chunks


# ── Index build / sync ────────────────────────────────────────────────────────

def _clear_by(content_type: str, content_id: str):
    conn = _db()
    conn.execute("DELETE FROM ask_index WHERE content_type=? AND content_id=?",
                 (content_type, str(content_id)))
    conn.commit()
    conn.close()


def remove_from_index(content_type: str, content_id: str):
    """Public helper: remove all chunks for a given content_type/content_id.

    Call this from delete endpoints to keep the FTS index in sync.
    """
    _clear_by(content_type, str(content_id))


def reindex_document(doc_id: str):
    """(Re)index a single document by doc_id."""
    conn = _db()
    doc = conn.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if not doc:
        conn.close()
        return
    conn.close()
    _clear_by("document", doc_id)

    body = doc["body"] or doc["comments"] or ""
    chunks = _chunk_markdown(body) if body.strip() else [("Metadata",
        f"{doc['title']} — {doc['doc_type']} ({doc['framework']} {doc['control_ref'] or ''}). "
        f"Owner: {doc['owner'] or 'unassigned'}. Status: {doc['status']}.")]

    conn = _db()
    for section, text in chunks:
        conn.execute(
            """INSERT INTO ask_index (content_type, content_id, title, section, body,
                                      owner, framework, control_ref, url_path)
               VALUES ('document', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (doc_id, doc["title"], section, text,
             doc["owner"] or "", doc["framework"] or "",
             doc["control_ref"] or "", f"/documents/{doc_id}"))
    conn.commit()
    conn.close()


def reindex_control(control_id: int):
    conn = _db()
    ctrl = conn.execute(
        """SELECT c.*, f.name as fw_name, f.id as fw_id
           FROM controls c JOIN frameworks f ON c.framework_id=f.id
           WHERE c.id=?""", (control_id,)).fetchone()
    conn.close()
    if not ctrl:
        return
    _clear_by("control", str(control_id))

    body_parts = [ctrl["description"] or ""]
    if ctrl["notes"]:
        body_parts.append(f"Notes: {ctrl['notes']}")
    body_parts.append(f"Status: {ctrl['status']}. Owner: {ctrl['owner'] or 'unassigned'}.")
    body = "\n\n".join(p for p in body_parts if p)

    conn = _db()
    conn.execute(
        """INSERT INTO ask_index (content_type, content_id, title, section, body,
                                  owner, framework, control_ref, url_path)
           VALUES ('control', ?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(control_id),
         f"{ctrl['ref']} — {ctrl['name']}",
         ctrl["category"] or "",
         body,
         ctrl["owner"] or "",
         ctrl["fw_name"],
         ctrl["ref"],
         f"/framework/{ctrl['fw_id']}"))
    conn.commit()
    conn.close()


def reindex_risk(risk_id: str):
    conn = _db()
    risk = conn.execute("SELECT * FROM risks WHERE risk_id=?", (risk_id,)).fetchone()
    conn.close()
    if not risk:
        return
    _clear_by("risk", risk_id)

    body = f"{risk['description']}"
    if risk["mitigation"]:
        body += f"\n\nMitigation: {risk['mitigation']}"
    body += (f"\n\nLikelihood: {risk['likelihood']}/5. Impact: {risk['impact']}/5. "
             f"Owner: {risk['owner'] or 'unassigned'}. Status: {risk['status']}.")

    conn = _db()
    conn.execute(
        """INSERT INTO ask_index (content_type, content_id, title, section, body,
                                  owner, framework, control_ref, url_path)
           VALUES ('risk', ?, ?, ?, ?, ?, ?, ?, ?)""",
        (risk_id,
         f"{risk_id} — {risk['description'][:60]}",
         risk["category"] or "",
         body,
         risk["owner"] or "",
         risk["framework"] or "",
         risk["control_ref"] or "",
         "/risks"))
    conn.commit()
    conn.close()


def rebuild_all():
    """Full rebuild of the search index. Use sparingly; O(n) over all corpora."""
    init_index()
    conn = _db()
    conn.execute("DELETE FROM ask_index")
    conn.commit()

    # Documents
    doc_ids = [r["doc_id"] for r in conn.execute("SELECT doc_id FROM documents").fetchall()]
    # Controls
    ctrl_ids = [r["id"] for r in conn.execute("SELECT id FROM controls").fetchall()]
    # Risks
    risk_ids = [r["risk_id"] for r in conn.execute("SELECT risk_id FROM risks").fetchall()]
    conn.close()

    for d in doc_ids: reindex_document(d)
    for c in ctrl_ids: reindex_control(c)
    for r in risk_ids: reindex_risk(r)

    # Return counts
    conn = _db()
    n = conn.execute("SELECT COUNT(*) FROM ask_index").fetchone()[0]
    conn.close()
    return n


# ── Retrieval ─────────────────────────────────────────────────────────────────

STOPWORDS = set("""
a an the of for to in on is are was were be been being do does did
have has had can could should would may might will shall must
i you he she it we they me him her us them my your his its our their
what when where why how which who whom whose that this these those
and or but not if else also as at by from with into onto over under
about against through during before after above below between
""".split())

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def _build_fts_query(question: str) -> str:
    """
    Turn a natural-language question into a safe FTS5 query.
    Strategy: tokenize, drop stopwords, add prefix wildcard, OR-join.
    """
    tokens = [t.lower() for t in TOKEN_RE.findall(question)]
    tokens = [t for t in tokens if t not in STOPWORDS and len(t) > 2]
    if not tokens:
        # Fall back to raw alpha tokens (even stopwords) to avoid empty query
        tokens = [t.lower() for t in TOKEN_RE.findall(question)][:6]
    # De-dup preserving order
    seen, uniq = set(), []
    for t in tokens:
        if t not in seen:
            uniq.append(t); seen.add(t)
    uniq = uniq[:12]
    # Prefix-match OR join → good recall on keyword variants
    return " OR ".join(f"{t}*" for t in uniq)


def search(question: str, k: int = 8) -> list[dict]:
    """Return top-k chunks as dicts with a relevance score (lower = better for bm25)."""
    q = _build_fts_query(question)
    if not q:
        return []
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT content_type, content_id, title, section, body,
                      owner, framework, control_ref, url_path,
                      bm25(ask_index) AS score
               FROM ask_index
               WHERE ask_index MATCH ?
               ORDER BY score
               LIMIT ?""",
            (q, k)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return [dict(r) for r in rows]


# ── Prompt assembly + Claude call ─────────────────────────────────────────────

ASK_SYSTEM_PROMPT = """You are ARIA's policy assistant. You answer employee questions \
ONLY using the organisation's own policies, controls, and risk register entries \
provided to you in the <context> block. You never use outside knowledge.

Rules:
1. If the context contains a clear answer, answer plainly in 1–3 short paragraphs. \
Use everyday language — no legalese unless the policy itself uses it.
2. After the answer, list the specific source citations you used as a JSON array in a \
fenced ```json block, with entries of the form \
{"title": "...", "section": "...", "url_path": "...", "content_type": "..."}.
3. If the context does NOT contain enough information to answer confidently, \
respond with exactly the single word NOT_COVERED on its own line, followed by \
a JSON block {"nearest_owner": "...", "framework": "...", "reason": "..."} \
identifying the most relevant policy owner to direct the employee to.
4. Never invent policy text, dates, or names. Never speculate.
5. Keep the answer concise and actionable. Prefer bullet points for procedural steps."""


def _format_context(chunks: list[dict]) -> str:
    lines = []
    for i, c in enumerate(chunks, 1):
        lines.append(
            f"[{i}] type={c['content_type']} | title={c['title']} | section={c['section'] or '—'} "
            f"| framework={c['framework'] or '—'} | owner={c['owner'] or '—'} | "
            f"url={c['url_path']}\n{c['body']}\n")
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


async def ask(question: str, user: Optional[dict] = None) -> dict:
    """
    Answer a question grounded in the corpus. Returns:
        {
          success: bool,
          covered: bool,
          answer: str,
          citations: [...],
          nearest_owner: str | None,
          framework: str | None,
          chunks_retrieved: int,
          latency_ms: int,
          error: str | None,
        }
    """
    started = datetime.now()
    api_key = get_api_key()
    if not api_key:
        return {"success": False, "covered": False,
                "answer": "AI assistant is not configured. Add an ANTHROPIC_API_KEY to enable it.",
                "citations": [], "nearest_owner": None, "framework": None,
                "chunks_retrieved": 0, "latency_ms": 0,
                "error": "missing_api_key"}

    init_index()
    chunks = search(question, k=8)
    if not chunks:
        result = {
            "success": True, "covered": False,
            "answer": "I couldn't find anything in our policies or controls that speaks to that. "
                      "Try rephrasing, or ask your manager or the Compliance team.",
            "citations": [], "nearest_owner": None, "framework": None,
            "chunks_retrieved": 0,
            "latency_ms": int((datetime.now() - started).total_seconds() * 1000),
            "error": None,
        }
        _log_qa(user, question, result)
        return result

    context_block = _format_context(chunks)
    user_msg = (
        f"<context>\n{context_block}\n</context>\n\n"
        f"<question>{question.strip()}</question>\n\n"
        "Answer following the rules. Remember: if the context is insufficient, "
        "respond with NOT_COVERED + JSON as described."
    )

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 1200,
                    "system": ASK_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_msg}],
                },
            )
        if resp.status_code != 200:
            err = resp.json().get("error", {}).get("message", f"status {resp.status_code}")
            return {"success": False, "covered": False, "answer": "",
                    "citations": [], "nearest_owner": None, "framework": None,
                    "chunks_retrieved": len(chunks),
                    "latency_ms": int((datetime.now() - started).total_seconds() * 1000),
                    "error": err}
        raw = resp.json()["content"][0]["text"].strip()
    except Exception as e:
        return {"success": False, "covered": False, "answer": "",
                "citations": [], "nearest_owner": None, "framework": None,
                "chunks_retrieved": len(chunks),
                "latency_ms": int((datetime.now() - started).total_seconds() * 1000),
                "error": str(e)}

    # Parse Claude's response
    if raw.startswith("NOT_COVERED"):
        rest, parsed = _extract_json_block(raw[len("NOT_COVERED"):].strip())
        parsed = parsed or {}
        nearest_owner = parsed.get("nearest_owner") or _guess_nearest_owner(chunks)
        framework = parsed.get("framework") or (chunks[0]["framework"] if chunks else None)
        reason = parsed.get("reason", "")
        owner_line = f" Try asking **{nearest_owner}**" if nearest_owner else ""
        result = {
            "success": True, "covered": False,
            "answer": ("We don't have a policy that directly answers that." +
                       (f" {reason}" if reason else "") + owner_line + "."),
            "citations": [], "nearest_owner": nearest_owner, "framework": framework,
            "chunks_retrieved": len(chunks),
            "latency_ms": int((datetime.now() - started).total_seconds() * 1000),
            "error": None,
        }
        _log_qa(user, question, result)
        return result

    answer_text, citations_json = _extract_json_block(raw)
    citations = citations_json if isinstance(citations_json, list) else []
    result = {
        "success": True, "covered": True,
        "answer": answer_text, "citations": citations,
        "nearest_owner": None, "framework": None,
        "chunks_retrieved": len(chunks),
        "latency_ms": int((datetime.now() - started).total_seconds() * 1000),
        "error": None,
    }
    _log_qa(user, question, result)
    return result


def _guess_nearest_owner(chunks: list[dict]) -> Optional[str]:
    """Fall back to the most common owner in the top chunks when Claude doesn't pick one."""
    counts: dict[str, int] = {}
    for c in chunks:
        o = (c.get("owner") or "").strip()
        if o:
            counts[o] = counts.get(o, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _log_qa(user: Optional[dict], question: str, result: dict):
    try:
        init_index()
        conn = _db()
        conn.execute(
            """INSERT INTO ask_log (user_id, username, question, answer, covered,
                                    citations, latency_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ((user or {}).get("id"), (user or {}).get("username"),
             question, result.get("answer", ""),
             1 if result.get("covered") else 0,
             json.dumps(result.get("citations", [])),
             result.get("latency_ms", 0)))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "rebuild":
        n = rebuild_all()
        print(f"Indexed {n} chunks")
    elif len(sys.argv) > 1 and sys.argv[1] == "ask":
        q = " ".join(sys.argv[2:]) or "what is our password policy?"
        out = asyncio.run(ask(q))
        print(json.dumps(out, indent=2))
    else:
        print("Usage: python ask_service.py [rebuild | ask <question>]")
