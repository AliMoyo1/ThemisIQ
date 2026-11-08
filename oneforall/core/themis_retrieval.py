"""Local, cited excerpts from current Vault versions linked to an authorized record.

Candidate record IDs and document text are never authority. Scope, link state,
review outcome, current version and the index's exact file hash are rechecked
before text is ranked. No source text leaves the application for a provider.
"""
from __future__ import annotations

import json
import re
from datetime import date

from core.rbac import has_capability
from core.sql_like import ci_like, like_pattern
from modules.evidence.scope import evidence_scope_sql
from modules.governance.entity_scope import describe_record

_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = {"about", "attached", "can", "does", "document", "documents", "evidence", "file", "files",
         "find", "for", "from", "have", "how", "linked", "mention", "our", "passage", "policy", "quote",
         "require", "say", "search", "section", "show", "state", "text", "that", "the", "this", "what",
         "where", "which", "with"}
_MAX_RECORDS = 11
_QUERY_BATCH = 250
_MATCHES_PER_BATCH = 12
_MAX_TEXT = 200_000
_MAX_QUOTES = 3


def _terms(question: str) -> set[str]:
    return {word for word in _WORD.findall(question.casefold()) if word not in _STOP}


def _records(db, user: dict, key: tuple[str, str], record_id: int) -> list[tuple[tuple[str, str], int]]:
    from modules.governance import relationships

    if describe_record(db, key, record_id, user) is None:
        return []
    records = [(key, record_id)]
    for link in relationships.list_links(db, user, key, record_id, limit=_MAX_RECORDS - 1):
        other = (link["module"], link["entity_type"])
        if other == ("governance", "application") and not has_capability(user, "ai_use.view"):
            continue
        records.append((other, link["entity_id"]))
    return list(dict.fromkeys(records))[:_MAX_RECORDS]


def _candidate_ids(db, user: dict, records: list[tuple[tuple[str, str], int]]) -> list[int]:
    from modules.aria.policy_references import resolve_policy_references
    from modules.evidence import proof

    found: set[int] = set()
    scope, scope_params = evidence_scope_sql(user, "e")
    for key, record_id in records:
        if key == ("evidence", "item"):
            found.add(record_id)
        # Read every accepted link directly. The connected-record panel shows
        # only its first 50 files; that display limit cannot bound retrieval.
        rows = db.execute(
            "SELECT DISTINCT e.id FROM evidence_links el JOIN evidence_items e ON e.id=el.evidence_id "
            f"WHERE el.module=%s AND el.entity_type=%s AND el.entity_id=%s AND {scope} "
            f"AND {proof.accepted_sql()}",
            [*key, record_id, *scope_params, proof.today()],
        ).fetchall()
        found.update(row[0] for row in rows)
        for policy in resolve_policy_references(db, user, (*key, record_id), limit=10):
            found.add(policy["evidence_id"])
    return sorted(found)


def _section(raw: str, position: int) -> str:
    try:
        segments = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return "Document"
    if not isinstance(segments, list):
        return "Document"
    for segment in segments:
        if (isinstance(segment, dict) and isinstance(segment.get("start"), int)
                and isinstance(segment.get("end"), int)
                and segment["start"] <= position < segment["end"]):
            return str(segment.get("label") or "Document")[:80]
    return "Document"


def search(db, user: dict, key: tuple[str, str], record_id: int, question: str) -> list[dict] | None:
    """None means the selected record is inaccessible; [] means no verifiable passage."""
    records = _records(db, user, key, record_id)
    if not records:
        return None
    terms = set(sorted(_terms(question))[:8])
    if not terms:
        return []
    ids = _candidate_ids(db, user, records)
    if not ids:
        return []
    scope, params = evidence_scope_sql(user, "e")
    rows = []
    ordered_terms = sorted(terms)
    # Each batch is independently ranked in SQL. A cap on candidate IDs or
    # newest matching files would silently discard relevant older documents.
    for offset in range(0, len(ids), _QUERY_BATCH):
        batch = ids[offset:offset + _QUERY_BATCH]
        marks = ",".join(["%s"] * len(batch))
        predicates = [ci_like("ti.content_text") for _ in ordered_terms]
        relevance = " + ".join(f"CASE WHEN {predicate} THEN 1 ELSE 0 END" for predicate in predicates)
        rows.extend(db.execute(
            "SELECT e.id,e.title,e.version,e.file_hash,ti.content_text,ti.segments_json "
            "FROM evidence_items e JOIN evidence_text_index ti ON ti.evidence_id=e.id "
            f"WHERE e.id IN ({marks}) AND {scope} AND e.status='current' "
            "AND (e.expiry_date IS NULL OR substr(e.expiry_date,1,10)>=%s) "
            "AND ti.status='indexed' AND e.file_hash IS NOT NULL AND ti.file_hash=e.file_hash "
            "AND COALESCE(ti.org_id,-1)=COALESCE(e.org_id,-1) "
            "AND COALESCE(ti.business_unit_id,-1)=COALESCE(e.business_unit_id,-1) "
            f"AND ({' OR '.join(predicates)}) ORDER BY ({relevance}) DESC,e.updated_at DESC,e.id DESC LIMIT %s",
            [*batch, *params, date.today().isoformat(),
             *[like_pattern(term) for term in ordered_terms],
             *[like_pattern(term) for term in ordered_terms], _MATCHES_PER_BATCH],
        ).fetchall())
    scored = []
    for row in rows:
        content = (row["content_text"] or "")[:_MAX_TEXT]
        folded = content.casefold()
        positions = [(folded.find(term), term) for term in terms]
        positions = [(offset, term) for offset, term in positions if offset >= 0]
        if not positions:
            continue
        position, term = min(positions)
        start = max(0, position - 70)
        end = min(len(content), position + max(len(term), 180))
        # The quote is an exact slice of the indexed text; offsets refer to that text.
        quote = content[start:end]
        score = sum(1 for candidate in terms if candidate in quote.casefold())
        scored.append((score, dict(row), start, end, quote, _section(row["segments_json"], position)))
    scored.sort(key=lambda item: (-item[0], item[1]["id"]))
    return [{"evidence_id": row["id"], "title": row["title"], "version": row["version"],
             "file_hash": row["file_hash"], "start": start, "end": end, "quote": quote, "section": section,
             "path": f"/evidence/?open=item:{row['id']}"}
            for _, row, start, end, quote, section in scored[:_MAX_QUOTES]]
