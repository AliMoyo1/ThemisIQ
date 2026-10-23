"""
What a search result says about a record, and searching inside one case
(plans/2026-10-governance-rework/04 section 4).

A result is a title and a link plus the facts a person needs to tell two records apart without opening them: the owning
module, its status, its date, the business unit and a short snippet. Every fact is read through the same unit scope as
the result itself, so a number or a word never reaches someone who could not open the record. The sensitive narrative
of a privacy record (a breach or a data subject request) is never used as a snippet.

`case` mode searches only the records connected to one record, through the relationship service: a record the viewer may
not open is not a node, so neither its title nor its count can be inferred from the answer.
"""
import logging

from modules.governance import relationships
from modules.governance.entity_scope import _KINDS, canonical_key, describe_record, entity_scope_sql, is_linkable

log = logging.getLogger("oneforall.search")

SNIPPET_LENGTH = 160

# What search calls a kind, where the result's own naming differs from the registry's.
RESULT_NAME = {("evidence", "item"): ("platform", "evidence")}
REGISTRY_NAME = {v: k for k, v in RESULT_NAME.items()}

# registry key -> (status column, date column, snippet column). None where the record has no such column or where the
# column is a narrative that must not travel in a list.
FACETS = {
    ("aria", "control"): ("status", "last_updated", "description"),
    ("aria", "document"): ("status", "updated_at", None),
    ("sentinel", "ropa"): ("status", "updated_at", "purpose"),
    ("grid", "audit"): ("status", "audit_date", "objective"),
    ("grid", "nc"): ("status", "due_date", "description"),
    ("bcm", "plan"): ("status", "updated_at", "description"),
    ("bcm", "incident"): ("status", "created_at", None),
    ("platform", "risk"): ("status", "updated_at", "description"),
    ("evidence", "item"): ("status", "updated_at", "description"),
    ("sentinel", "breach"): ("status", "updated_at", None),
    ("sentinel", "dpia"): ("status", "updated_at", "description"),
    ("sentinel", "dsr"): ("status", "updated_at", None),
    ("sentinel", "vendor"): (None, "updated_at", "services"),
    ("sentinel", "aiia"): ("status", "updated_at", "system_description"),
    ("erm", "risk"): ("status", "updated_at", "description"),
    ("erm", "scenario"): ("status", "updated_at", "description"),
    ("erm", "obligation"): ("status", "updated_at", None),
    ("orm", "event"): ("status", "updated_at", "description"),
    ("orm", "kri"): ("status", "updated_at", "description"),
    ("governance", "application"): ("is_active", "updated_at", "description"),
    ("governance", "process"): ("is_active", "updated_at", "description"),
    ("governance", "data_asset"): ("is_active", "updated_at", "description"),
}
_ACTIVE_WORDS = {1: "Active", 0: "Retired", True: "Active", False: "Retired"}


def parse_case(value) -> "tuple | None":
    """`module:entity_type:id` -> (registry key, id), or None when it is not a linkable record reference."""
    parts = str(value or "").split(":")
    if len(parts) != 3 or not parts[2].isdecimal():
        return None
    key = canonical_key(parts[0], parts[1])
    record_id = int(parts[2])
    if not is_linkable(key) or not (0 < record_id < 2 ** 31):
        return None
    return key, record_id


def _snippet(text, term) -> "str | None":
    """A short, single-line excerpt, centred on the first match when the text has one."""
    text = " ".join(str(text or "").split())
    if not text:
        return None
    at = text.lower().find(term.lower()) if term else -1
    if at <= SNIPPET_LENGTH // 2 or len(text) <= SNIPPET_LENGTH:
        shown = text[:SNIPPET_LENGTH]
        return shown + ("…" if len(text) > SNIPPET_LENGTH else "")
    start = at - SNIPPET_LENGTH // 4
    shown = text[start:start + SNIPPET_LENGTH]
    return "…" + shown + ("…" if start + SNIPPET_LENGTH < len(text) else "")


def enrich(db, user, results, term="") -> None:
    """Add status, date, business_unit and snippet to each result, in place. A kind that cannot be read leaves its
    results as they were: a missing fact is never a made up one."""
    wanted = {}
    for r in results:
        key = REGISTRY_NAME.get((r["module"], r["type"]), (r["module"], r["type"]))
        if key in FACETS and key in _KINDS:
            wanted.setdefault(key, set()).add(r["id"])
    facts = {}
    for key, ids in wanted.items():
        status_col, date_col, snippet_col = FACETS[key]
        kind = _KINDS[key]
        scope, params = entity_scope_sql(key, user, "t")
        cols = ["t.id AS id"]
        for alias, col in (("status", status_col), ("date", date_col), ("snippet", snippet_col)):
            cols.append(f"t.{col} AS {alias}" if col else f"NULL AS {alias}")
        join, unit = "", "NULL AS unit"
        if kind.bu:
            join, unit = f" LEFT JOIN business_units bu ON bu.id = t.{kind.bu}", "bu.name AS unit"
        try:
            rows = db.execute(
                f"SELECT {', '.join(cols)}, {unit} FROM {kind.table} t{join} "
                f"WHERE t.id IN ({','.join(['%s'] * len(ids))}) AND {scope}", [*sorted(ids), *params]).fetchall()
        except Exception:
            log.warning("Search facts of %s could not be read", key, exc_info=True)
            try:
                db.rollback()
            except Exception:
                pass
            continue
        for row in rows:
            facts[(key, row["id"])] = row
    for r in results:
        key = REGISTRY_NAME.get((r["module"], r["type"]), (r["module"], r["type"]))
        row = facts.get((key, r["id"]))
        status = row["status"] if row is not None else None
        if status is not None and FACETS.get(key, (None,))[0] == "is_active":
            status = _ACTIVE_WORDS.get(status, str(status))
        r["status"] = str(status) if status not in (None, "") else None
        r["date"] = str(row["date"])[:10] if row is not None and row["date"] else None
        r["business_unit"] = (row["unit"] or "Whole organization") if row is not None and key in _KINDS and _KINDS[key].bu else None
        r["snippet"] = _snippet(row["snippet"], term) if row is not None else None


def case_results(db, user, case, term) -> "list | None":
    """The records connected to one record whose title matches `term`, shaped like the global search results.

    None when the reference is not a record the viewer may open (a hidden record answers like a missing one)."""
    parsed = parse_case(case)
    if parsed is None:
        return None
    key, record_id = parsed
    subject = describe_record(db, key, record_id, user)
    if subject is None:
        return None
    wanted = str(term or "").strip().lower()
    nodes = [{"key": key, "id": record_id, "title": subject["title"], "url": subject["url"], "how": "This case"}]
    for link in relationships.list_links(db, user, key, record_id):
        nodes.append({"key": canonical_key(link["module"], link["entity_type"]), "id": link["entity_id"],
                      "title": link["title"], "url": link["url"], "how": link["label"]})
    seen, out = set(), []
    for node in nodes:
        ident = (node["key"], node["id"])
        if ident in seen or (wanted and wanted not in str(node["title"]).lower()):
            continue
        seen.add(ident)
        module, kind = RESULT_NAME.get(node["key"], node["key"])
        out.append({"module": module, "type": kind, "id": node["id"], "title": node["title"],
                    "subtitle": node["how"], "link": node["url"], "in_case": True})
    return out
