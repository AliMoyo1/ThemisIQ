"""
The connected view of one record (plans/2026-10-governance-rework/03 section 2).

A specialist opens a system, a process, a data asset, a vendor or any other linkable record and sees what is connected to it,
grouped by the module that owns each connected record, with the proof held for it and any change signals that name it. The
view stores nothing and copies nothing: every line is read at the moment of asking, through the viewer's own scope.

* A connection appears only when the viewer may open both ends. A record they cannot open is not named, counted or hinted at,
  and a hidden record answers exactly like one that does not exist (None).
* Each section is read on its own. A source that fails says "could not be read"; it is never shown as empty.
* A connection that nobody confirmed is shown apart, as proposed, so a disputed relationship is not read as settled.
"""
import logging

from modules.evidence import proof
from modules.evidence.scope import evidence_scope_sql
from modules.governance import change_signals, relationships
from modules.governance.entity_scope import canonical_key, describe_record, describe_records, is_linkable

log = logging.getLogger("oneforall.entity360")

MODULE_TITLES = {
    "governance": "Governance", "aria": "Policies and controls (ARIA)", "grid": "Audits (GRID)", "bcm": "Continuity (BCM)",
    "sentinel": "Privacy (Sentinel)", "erm": "Enterprise risk (ERM)", "orm": "Operational risk (ORM)", "platform": "Platform",
    "evidence": "Evidence",
}
_ORDER = ["governance", "sentinel", "aria", "grid", "bcm", "orm", "erm", "platform", "evidence"]
KIND_LABELS = {
    ("governance", "application"): "Application", ("governance", "process"): "Business process",
    ("governance", "data_asset"): "Data asset", ("sentinel", "vendor"): "Privacy vendor", ("grid", "vendor"): "Audit vendor",
    ("bcm", "vendor"): "Continuity vendor", ("sentinel", "ropa"): "Processing record", ("sentinel", "dpia"): "Privacy impact assessment",
    ("sentinel", "breach"): "Breach", ("sentinel", "dsr"): "Data subject request", ("sentinel", "aiia"): "AI impact assessment",
    ("aria", "control"): "Control", ("aria", "document"): "Policy document", ("aria", "risk"): "Risk",
    ("grid", "audit"): "Audit", ("grid", "nc"): "Finding", ("grid", "control"): "Audit control",
    ("bcm", "plan"): "Continuity plan", ("bcm", "bia"): "Business impact analysis", ("bcm", "incident"): "Incident",
    ("erm", "risk"): "Enterprise risk", ("erm", "scenario"): "Risk scenario", ("orm", "event"): "Operational event", ("orm", "aims"): "AI management assessment",
    ("orm", "ai_control"): "AI control",
}
# Facts a header can read from the record's own table: (table, owner column, business unit column, updated column).
_FACTS = {
    ("governance", "application"): ("applications", "owner_user_id", "business_unit_id", "updated_at"),
    ("governance", "process"): ("business_processes", "owner_user_id", "business_unit_id", "updated_at"),
    ("governance", "data_asset"): ("data_assets", "owner_user_id", "business_unit_id", "updated_at"),
    ("erm", "risk"): ("erm_enterprise_risks", "owner_id", "business_unit_id", "updated_at"),
    ("orm", "event"): ("orm_events", "owner_id", "business_unit_id", "updated_at"),
}


def _guarded(title, build):
    try:
        return build()
    except Exception:
        log.warning("Connected view: %s could not be read", title, exc_info=True)
        return {"title": title, "state": "unavailable", "items": [], "note": "This could not be read just now. That is not the same as nothing connected."}


def _header(db, user, key, record_id, shown) -> dict:
    out = {"module": key[0], "entity_type": key[1], "entity_id": record_id, "title": shown["title"], "url": shown["url"],
           "kind_label": KIND_LABELS.get(key, key[1].replace("_", " ").capitalize()),
           "module_title": MODULE_TITLES.get(key[0], key[0]), "owner": None, "business_unit": None, "updated_at": None}
    facts = _FACTS.get(key)
    if facts:
        table, owner_col, unit_col, updated_col = facts
        try:
            row = db.execute(
                f"SELECT t.{owner_col} AS owner_id, t.{unit_col} AS unit_id, t.{updated_col} AS updated_at, u.full_name AS owner_name, "
                f"bu.name AS unit_name FROM {table} t LEFT JOIN users u ON u.id = t.{owner_col} "
                f"LEFT JOIN business_units bu ON bu.id = t.{unit_col} WHERE t.id = %s", (record_id,)).fetchone()
        except Exception:
            row = None
            log.warning("Connected view: facts of %s %s could not be read", key, record_id, exc_info=True)
        if row is not None:
            out.update({"owner": row["owner_name"], "business_unit": row["unit_name"] or "Whole organization",
                        "updated_at": str(row["updated_at"] or "")[:10] or None})
    return out


def _connections(db, user, key, record_id) -> list:
    links = relationships.list_links(db, user, key, record_id, include_candidates=True, include_rejected=True)
    grouped = {}
    for link in links:
        grouped.setdefault(link["module"], []).append({
            "title": link["title"], "url": link["url"], "entity_type": link["entity_type"], "entity_id": link["entity_id"],
            "kind_label": KIND_LABELS.get(canonical_key(link["module"], link["entity_type"]), link["entity_type"].replace("_", " ")),
            "relationship": link["label"], "confirmed": link["status"] == "confirmed", "state": link["state"],
            "provenance": link["provenance"]})
    sections = []
    for module in sorted(grouped, key=lambda m: _ORDER.index(m) if m in _ORDER else 99):
        items = grouped[module]
        sections.append({"key": module, "title": MODULE_TITLES.get(module, module), "state": "ok", "items": items,
                         "proposed": sum(1 for i in items if i["state"] == "suggested"),
                         "disputed": sum(1 for i in items if i["state"] == "disputed")})
    return sections


def _proof(db, user, key, record_id) -> dict:
    scope, params = evidence_scope_sql(user)
    rows = db.execute(
        "SELECT e.id, e.title, e.version, e.status, e.expiry_date, l.review_status, l.reviewed_at FROM evidence_links l "
        "JOIN evidence_items e ON e.id = l.evidence_id WHERE l.module = %s AND l.entity_type = %s AND l.entity_id = %s "
        f"AND l.deleted_at IS NULL AND e.status != 'archived' AND {scope} ORDER BY e.updated_at DESC, e.id DESC LIMIT 50",
        [key[0], key[1], record_id, *params]).fetchall()
    today = proof.today()
    items = []
    for r in rows:
        if r["status"] == "superseded":
            state, tone = "Replaced by a newer version", "muted"
        elif proof.expired(r["expiry_date"], today):
            state, tone = "Expired", "bad"
        else:
            status = r["review_status"] or "pending"
            state = proof.OUTCOME_LABELS.get(status, status)
            tone = {"accepted": "good", "pending": "warn"}.get(status, "bad")
        items.append({"title": r["title"], "url": f"/evidence/?open=item:{r['id']}", "version": r["version"], "state": state,
                      "tone": tone, "expiry_date": str(r["expiry_date"] or "")[:10] or None})
    counts = {"files": len(items), "accepted": sum(1 for i in items if i["state"] == "Accepted")}
    return {"key": "evidence", "title": MODULE_TITLES["evidence"], "state": "ok" if items else "empty", "items": items,
            "counts": counts,
            "note": None if items else "No file is linked to this record."}


def _signals(db, user, key, record_id) -> dict:
    items = change_signals.for_entity(db, user, key, record_id)
    return {"key": "changes", "title": "Changes to look at", "state": "ok" if items else "empty", "items": items,
            "note": None if items else "No connected record has changed since anything was published."}


def get_connected(db, user: dict, module, entity_type, record_id) -> "dict | None":
    """The connected view of one record, or None when the viewer may not open it (a hidden record answers like a missing one)."""
    key = canonical_key(module, entity_type)
    if not is_linkable(key) or isinstance(record_id, bool) or not isinstance(record_id, int) or record_id < 1:
        return None
    shown = describe_record(db, key, record_id, user)
    if shown is None:
        return None
    header = _header(db, user, key, record_id, shown)
    connections = _guarded("Connected records", lambda: _connections(db, user, key, record_id))
    return {
        "entity": header,
        "connections": connections if isinstance(connections, list) else [],
        "unavailable": [connections] if isinstance(connections, dict) else [],
        "proof": _guarded("Proof held in the Evidence Vault", lambda: _proof(db, user, key, record_id)),
        "changes": _guarded("Changes to look at", lambda: _signals(db, user, key, record_id)),
        "note": ("Read just now through your own access. A connected record you cannot open is not shown or counted. A "
                 "connection nobody has confirmed is marked as proposed, and one somebody declined is marked as disputed."),
    }
