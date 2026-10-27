"""Authorized, exact-version policy references for other modules.

Callers pass the record they already show. This service resolves only confirmed
relationships (or reviewed clause links on a control) and returns no hint for
an inaccessible source, policy or Vault item. Coverage is not proof.
"""
from __future__ import annotations

from datetime import date

from modules.aria.policy_access import document_read_ok
from modules.evidence.scope import evidence_scope_sql
from modules.governance import relationships
from modules.governance.entity_scope import canonical_key, describe_record, may_view_kind


def resolve_policy_references(db, viewer: dict, source_record: tuple[str, str, int], limit: int | None = 30) -> list[dict]:
    module, kind, record_id = source_record
    key = canonical_key(module, kind)
    if not isinstance(record_id, int) or isinstance(record_id, bool) or record_id < 1:
        return []
    if describe_record(db, key, record_id, viewer) is None:
        return []
    if not may_view_kind(viewer, ("aria", "document")):
        return []
    wanted: dict[int, tuple[str | None, int | None]] = {}
    if key == ("aria", "control"):
        cap = " LIMIT %s" if limit is not None else ""
        params = [record_id, viewer.get("org_id")]
        if limit is not None:
            params.append(limit)
        for row in db.execute("SELECT i.document_id,i.policy_version_id,l.anchor FROM aria_policy_clause_links l "
                              "JOIN aria_policy_imports i ON i.id=l.import_id "
                              "WHERE l.control_id=%s AND l.state='confirmed' AND i.org_id=%s "
                              "AND i.document_id IS NOT NULL ORDER BY l.id DESC" + cap, params).fetchall():
            wanted[row["document_id"]] = (row["anchor"], row["policy_version_id"])
    else:
        for link in relationships.list_links(db, viewer, key, record_id, limit=limit or 30):
            if (link["module"], link["entity_type"]) == ("aria", "document") and link["status"] == "confirmed":
                wanted[link["entity_id"]] = (None, None)
    if not wanted:
        return []
    scope_sql, scope_params = evidence_scope_sql(viewer, "e")
    items = []
    for doc_id, (anchor, linked_version_id) in list(wanted.items())[:limit] if limit is not None else wanted.items():
        doc = db.execute("SELECT id,title,status,effective_date,org_id,business_unit_id,policy_workflow_managed,"
                         "current_policy_version_id FROM aria_documents WHERE id=%s AND org_id=%s",
                         (doc_id, viewer.get("org_id"))).fetchone()
        if not doc or not document_read_ok(viewer, dict(doc)) or doc["status"] != "Approved":
            continue
        if doc["effective_date"]:
            try:
                if date.fromisoformat(str(doc["effective_date"])[:10]) > date.today():
                    continue
            except ValueError:
                continue
        version_id = doc["current_policy_version_id"]
        if not version_id:
            continue  # legacy rows without an immutable version cannot support an exact citation
        if linked_version_id is not None and linked_version_id != version_id:
            continue  # a reviewed clause does not silently apply to a later policy revision
        version = db.execute("SELECT id,version,state,approved_at FROM aria_policy_versions "
                             "WHERE id=%s AND document_id=%s AND org_id=%s",
                             (version_id, doc_id, viewer.get("org_id"))).fetchone()
        if not version:
            continue
        origin = "internal"
        if version["state"] != "approved":
            attestation = db.execute("SELECT external_status,external_approved_at FROM aria_policy_imports "
                                     "WHERE document_id=%s AND policy_version_id=%s AND org_id=%s",
                                     (doc_id, version_id, viewer.get("org_id"))).fetchone()
            if not attestation or attestation["external_status"] != "verified":
                continue
            origin = "external_verified"
        evidence = db.execute("SELECT e.id,e.title,e.file_hash FROM evidence_items e "
                              f"WHERE e.aria_policy_version_id=%s AND e.org_id=%s "
                              f"AND e.status NOT IN ('archived','superseded') AND {scope_sql} "
                              "ORDER BY e.id DESC LIMIT 1", [version_id, viewer.get("org_id"), *scope_params]).fetchone()
        if not evidence:
            continue
        rendition = db.execute("SELECT e.id FROM aria_policy_renditions r "
                               "JOIN evidence_items e ON e.id=r.evidence_id "
                               "WHERE r.source_version_id=%s AND r.state='approved' AND r.org_id=%s "
                               f"AND e.org_id=%s AND e.status='current' AND {scope_sql} "
                               "ORDER BY r.created_at DESC LIMIT 1",
                               [version_id, viewer.get("org_id"), viewer.get("org_id"), *scope_params]).fetchone()
        items.append({"document_id": doc_id, "title": doc["title"], "version_id": version_id,
                      "version": version["version"], "evidence_id": evidence["id"],
                      "url": f"/evidence/?open=item:{evidence['id']}", "anchor": anchor,
                      "presentation_url": f"/evidence/?open=item:{rendition['id']}" if rendition else None,
                      "approval": origin, "meaning": "Policy reference; operating proof requires separate review"})
    return items
