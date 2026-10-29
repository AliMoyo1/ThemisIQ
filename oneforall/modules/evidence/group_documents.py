"""Explicit cross-tenant document catalogue, grants and source rechecks.

The platform registry contains reviewed metadata only. A group viewer never
acquires the source tenant's user identity or a general cross-tenant query.
"""

import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from config import settings
from core.rbac import has_capability
from core.sql_like import ci_like, like_pattern
from core.timeutils import utcnow
from database import get_db, insert_returning_id, tenant_context
from modules.evidence.scope import evidence_scope_sql

_CATALOGUE_FIELDS = {"title", "category", "version", "source_name", "classification", "expires_at"}
_AUDIENCE_ROLES = {"grc_officer", "compliance_manager", "audit_lead", "dpo"}


def _approved_terms(raw) -> dict:
    if not isinstance(raw, dict):
        raise HTTPException(422, "Record the sharing terms")
    classes, classifications = raw.get("data_classes"), raw.get("classifications")
    audiences, fields, jurisdictions = raw.get("audiences"), raw.get("fields"), raw.get("jurisdictions")
    for values, allowed in ((classes, {"document_metadata", "document_bytes"}),
                            (classifications, {"internal", "confidential"}),
                            (audiences, _AUDIENCE_ROLES), (fields, _CATALOGUE_FIELDS)):
        if (not isinstance(values, list) or not 1 <= len(values) <= 10
                or not all(isinstance(v, str) for v in values)
                or len(values) != len(set(values)) or not set(values) <= allowed):
            raise HTTPException(422, "Review the exact sharing classes, audience and fields")
    if "document_metadata" not in classes or not _CATALOGUE_FIELDS <= set(fields):
        raise HTTPException(422, "The approved catalogue needs its exact display fields")
    if (not isinstance(jurisdictions, list) or not 1 <= len(jurisdictions) <= 20
            or not all(isinstance(v, str) and 2 <= len(v.strip()) <= 80 for v in jurisdictions)
            or len(jurisdictions) != len(set(jurisdictions))):
        raise HTTPException(422, "Record the sharing jurisdictions")
    from modules.governance import group_figures
    measures = group_figures.validate_measures(raw.get("figure_measures"))
    for key, maximum in (("legal_basis", 500), ("agreement_ref", 250)):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise HTTPException(422, f"Record the {key.replace('_', ' ')}")
    return {"data_classes": classes, "classifications": classifications, "audiences": audiences,
            "fields": fields, "jurisdictions": [v.strip() for v in jurisdictions],
            "legal_basis": raw["legal_basis"].strip(), "agreement_ref": raw["agreement_ref"].strip(),
            "figure_measures": measures}


def _table(name: str) -> str:
    return f"public.{name}" if settings.is_postgres() else name


def _now() -> str:
    return utcnow().isoformat()


# Grants and releases are reviewed at least yearly: a far-future expiry would make the review date the only gate.
MAX_GRANT_DAYS = 366
# Group oversight is mandatory: a child acknowledges as notice, and an unanswered notice is deemed given after this.
NOTICE_DAYS = 14


def _deadline(raw: str, max_days: int | None = None) -> str:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if value.tzinfo is None:
            raise ValueError
        normalized = value.astimezone(timezone.utc).replace(tzinfo=None)
        if normalized <= utcnow():
            raise ValueError
        if max_days is not None and normalized > utcnow() + timedelta(days=max_days):
            raise HTTPException(422, f"Choose a date within {max_days} days")
        return normalized.isoformat()
    except (TypeError, AttributeError, ValueError):
        raise HTTPException(422, "Choose a future UTC date and time with a timezone") from None


def _org(db, org_id: int):
    row = db.execute("SELECT id, name, slug FROM organizations WHERE id=%s AND status='active'",
                     (org_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Organization not found")
    return row


def _relationship(db, relation_id: int):
    row = db.execute(f"SELECT * FROM {_table('org_relationships')} WHERE id=%s", (relation_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Relationship not found")
    return row


def _notified(row) -> bool:
    """The child acknowledged, or the notice period passed and the platform recorded the notice as given."""
    return bool(row["child_ack_by"] or row["notice_deemed_at"])


def _reviewed(row) -> bool:
    return _notified(row) and bool(row["privacy_review_by"] and row["legal_review_by"])


def _assert_edge(db, row):
    if row["status"] != "active" or not _reviewed(row):
        raise HTTPException(404, "Relationship not active")
    if row["review_due_at"] and row["review_due_at"] <= _now():
        raise HTTPException(404, "Relationship review overdue")
    _org(db, row["parent_org_id"])
    _org(db, row["child_org_id"])


def management_workspace(db, actor: dict) -> dict:
    """Small, role-filtered work queue for the group sharing page.

    The ordinary user sees only edges containing their organization. Source
    evidence and recipients are always drawn from their own tenant scope.
    """
    org_id = actor.get("org_id")
    if not org_id:
        raise HTTPException(403, "Organization required")
    caps = {key: has_capability(actor, key) for key in (
        "group.relationship.manage", "group.relationship.ack", "group.terms.privacy",
        "group.terms.legal", "group.grant.manage", "group.rights.review",
        "group.document.publish")}
    if not any(caps.values()):
        raise HTTPException(403, "Group sharing access required")
    if caps["group.relationship.manage"]:
        organizations = [dict(row) for row in db.execute(
            "SELECT id,name FROM organizations WHERE status='active' ORDER BY name,id").fetchall()]
        where, args = "", []
    else:
        organizations = []
        where, args = "WHERE r.parent_org_id=%s OR r.child_org_id=%s", [org_id, org_id]
    relations = [dict(row) for row in db.execute(
        f"SELECT r.*, p.name AS parent_name, c.name AS child_name "
        f"FROM {_table('org_relationships')} r "
        "JOIN organizations p ON p.id=r.parent_org_id AND p.status='active' "
        "JOIN organizations c ON c.id=r.child_org_id AND c.status='active' "
        f"{where} ORDER BY r.created_at DESC,r.id DESC LIMIT 100", args).fetchall()]
    for row in relations:
        row["terms"] = json.loads(row.pop("terms_json"))
        row["is_child"] = row["child_org_id"] == org_id
        row["can_decide"] = row["status"] == "proposed" and org_id in (row["parent_org_id"], row["child_org_id"])
        row["can_deem_notice"] = (caps["group.relationship.manage"] and row["status"] == "proposed"
                                  and not _notified(row) and _notice_elapsed(row))
        row["can_grant"] = (row["status"] == "active" and org_id in
                            (row["parent_org_id"], row["child_org_id"]))
        row["can_publish"] = row["can_grant"]
    recipients = []
    if caps["group.grant.manage"]:
        recipients = [dict(row) for row in db.execute(
            "SELECT id,full_name FROM users WHERE org_id=%s AND is_active=1 "
            "AND deleted_at IS NULL ORDER BY full_name,id LIMIT 250", (org_id,)).fetchall()]
    evidence = []
    if caps["group.rights.review"] or caps["group.document.publish"]:
        scope, params = evidence_scope_sql(actor)
        evidence = [dict(row) for row in db.execute(
            "SELECT e.id,e.title,e.category,e.version FROM evidence_items e "
            f"WHERE e.org_id=%s AND e.status='current' AND e.file_hash IS NOT NULL AND {scope} "
            "ORDER BY e.updated_at DESC,e.id DESC LIMIT 250", [org_id, *params]).fetchall()]
    publications = []
    if caps["group.document.publish"]:
        publications = [dict(row) for row in db.execute(
            f"SELECT id,relationship_id,evidence_id,title,version,expires_at "
            f"FROM {_table('group_document_publications')} WHERE source_org_id=%s "
            "AND revoked_at IS NULL ORDER BY id DESC LIMIT 100", (org_id,)).fetchall()]
    from modules.governance import group_figures
    return {"capabilities": caps, "organizations": organizations,
            "figure_measures": group_figures.publishable_measures() if caps["group.relationship.manage"] else [],
            "relationships": relations, "recipients": recipients,
            "evidence": evidence, "publications": publications}


def grant_review_queue(db, actor: dict, *, page: int = 1) -> dict:
    """Page every active grant in the caller's organization for access review."""
    org_id = actor.get("org_id")
    if not org_id or not has_capability(actor, "group.grant.manage"):
        raise HTTPException(403, "Grant management required")
    if not isinstance(page, int) or not 1 <= page <= 10000:
        raise HTTPException(422, "Invalid grant page")
    rows = db.execute(
        f"SELECT g.id,g.relationship_id,g.source_org_id,g.user_id,g.capability,"
        "g.expires_at,g.review_due_at,g.granted_by,u.full_name AS recipient_name,"
        "o.name AS source_name,"
        f"(SELECT MAX(a.created_at) FROM {_table('group_access_events')} a "
        "WHERE a.relationship_id=g.relationship_id AND a.source_org_id=g.source_org_id "
        "AND a.viewer_org_id=g.viewer_org_id AND a.actor_id=g.user_id "
        "AND a.action=CASE WHEN g.capability='document.download' THEN 'download' ELSE 'open' END "
        "AND a.created_at>=g.created_at) AS last_matching_access_at "
        f"FROM {_table('group_view_grants')} g "
        "LEFT JOIN users u ON u.id=g.user_id AND u.org_id=g.viewer_org_id "
        "JOIN organizations o ON o.id=g.source_org_id "
        "WHERE g.viewer_org_id=%s AND g.revoked_at IS NULL "
        "ORDER BY g.review_due_at ASC,g.id DESC LIMIT %s OFFSET %s",
        (org_id, 51, (page - 1) * 50),
    ).fetchall()
    items = [dict(row) for row in rows[:50]]
    now = _now()
    for item in items:
        item["can_review"] = item["granted_by"] != actor["id"] and item["user_id"] != actor["id"]
        item["review_overdue"] = item["review_due_at"] <= now
        # Several grants for the same person and edge can overlap. The event
        # is a matching observed action, not proof that this exact grant was used.
        item.pop("granted_by")
    return {"items": items, "page": page, "has_more": len(rows) > 50}


def source_candidates(db, actor: dict, query: str, page: int = 1) -> dict:
    """Search exact source-tenant scope; the page never searches another company."""
    if not actor.get("org_id") or not any(has_capability(actor, cap) for cap in
                                          ("group.rights.review", "group.document.publish")):
        raise HTTPException(403, "Source document access required")
    if not isinstance(query, str) or len(query) > 120 or not 1 <= page <= 1000:
        raise HTTPException(422, "Invalid document search")
    scope, params = evidence_scope_sql(actor)
    filter_sql = f" AND {ci_like('e.title')}" if query.strip() else ""
    values = [actor["org_id"], *params]
    if query.strip():
        values.append(like_pattern(query))
    values.extend((51, (page - 1) * 50))
    rows = db.execute(
        "SELECT e.id,e.title,e.category,e.version FROM evidence_items e "
        f"WHERE e.org_id=%s AND e.status='current' AND e.file_hash IS NOT NULL AND {scope}"
        f"{filter_sql} ORDER BY e.updated_at DESC,e.id DESC LIMIT %s OFFSET %s", values).fetchall()
    return {"items": [dict(row) for row in rows[:50]], "page": page, "has_more": len(rows) > 50}


def propose_relationship(db, actor: dict, parent_id: int, child_id: int, purpose: str,
                         terms: dict, review_due: str) -> int:
    if not has_capability(actor, "group.relationship.manage"):
        raise HTTPException(403, "Relationship management required")
    if parent_id == child_id or not purpose.strip() or len(purpose) > 300:
        raise HTTPException(422, "Choose two organizations and a concise purpose")
    terms = _approved_terms(terms)
    parent, child = _org(db, parent_id), _org(db, child_id)
    if parent["id"] == child["id"]:
        raise HTTPException(422, "An organization cannot parent itself")
    edges = db.execute(f"SELECT parent_org_id, child_org_id FROM {_table('org_relationships')} "
                       "WHERE status='active'").fetchall()
    if any(r["child_org_id"] == child_id for r in edges):
        raise HTTPException(409, "Child already has an active parent")
    # Adding parent -> child is cyclic when the proposed parent already sits
    # below this child in the active tree.
    current = parent_id
    for _ in range(len(edges) + 1):
        if current == child_id:
            raise HTTPException(409, "Relationship cycle")
        upstream = next((r["parent_org_id"] for r in edges if r["child_org_id"] == current), None)
        if upstream is None:
            break
        current = upstream
    return insert_returning_id(db, f"INSERT INTO {_table('org_relationships')} "
                               "(parent_org_id,child_org_id,purpose,terms_json,review_due_at,created_by) "
                               "VALUES (%s,%s,%s,%s,%s,%s)",
                               (parent_id, child_id, purpose.strip(), json.dumps(terms, sort_keys=True),
                                _deadline(review_due), actor["id"]))


def _notice_elapsed(row) -> bool:
    created = str(row["created_at"] or "")[:19].replace(" ", "T")
    try:
        return datetime.fromisoformat(created) <= utcnow() - timedelta(days=NOTICE_DAYS)
    except ValueError:
        return False


def _activate_if_ready(db, relation_id: int, child_org_id: int) -> bool:
    reviewed = db.execute(f"SELECT * FROM {_table('org_relationships')} WHERE id=%s", (relation_id,)).fetchone()
    if not _reviewed(reviewed):
        return False
    # One active parent is also enforced by a partial unique index. The
    # app-level check gives a legible result before that index rejects it.
    other = db.execute(f"SELECT id FROM {_table('org_relationships')} "
                       "WHERE child_org_id=%s AND status='active'", (child_org_id,)).fetchone()
    if other:
        raise HTTPException(409, "Child already has an active parent")
    db.execute(f"UPDATE {_table('org_relationships')} SET status='active',effective_at=%s "
               "WHERE id=%s AND status='proposed'", (_now(), relation_id))
    return True


def deem_notice(db, actor: dict, relation_id: int) -> dict:
    """Group oversight is not an opt-in: after the notice period an unanswered acknowledgement is recorded as given.

    Privacy and legal review are still required before the relationship becomes active."""
    if not has_capability(actor, "group.relationship.manage"):
        raise HTTPException(404, "Relationship not found")
    row = _relationship(db, relation_id)
    if row["status"] != "proposed" or _notified(row):
        raise HTTPException(409, "Notice is already recorded")
    if not _notice_elapsed(row):
        raise HTTPException(409, f"The child has {NOTICE_DAYS} days to acknowledge")
    db.execute(f"UPDATE {_table('org_relationships')} SET notice_deemed_at=%s WHERE id=%s AND status='proposed'",
               (_now(), relation_id))
    active = _activate_if_ready(db, relation_id, row["child_org_id"])
    return {"id": relation_id, "status": "active" if active else "proposed"}


def record_relationship_decision(db, actor: dict, relation_id: int, kind: str) -> dict:
    row = _relationship(db, relation_id)
    if actor.get("org_id") not in (row["parent_org_id"], row["child_org_id"]) or row["status"] != "proposed":
        raise HTTPException(404, "Relationship not found")
    if kind == "ack" and actor.get("org_id") != row["child_org_id"]:
        raise HTTPException(404, "Relationship not found")
    cols = {"ack": ("child_ack_by", "group.relationship.ack"),
            "privacy": ("privacy_review_by", "group.terms.privacy"),
            "legal": ("legal_review_by", "group.terms.legal")}
    if kind not in cols:
        raise HTTPException(422, "Unknown decision")
    col, capability = cols[kind]
    if not has_capability(actor, capability):
        raise HTTPException(403, "Reviewer capability required")
    if row[col] and row[col] != actor["id"]:
        raise HTTPException(409, "Decision already recorded")
    # The acknowledging administrator is never also a reviewer. Privacy and legal may be the same person only when
    # that person is a Data Protection Officer, because legal review sits with the DPO.
    others = {"ack": ("privacy_review_by", "legal_review_by"), "privacy": ("child_ack_by", "legal_review_by"),
              "legal": ("child_ack_by", "privacy_review_by")}[kind]
    shared_dpo = "dpo" in (actor.get("roles") or []) and kind in ("privacy", "legal")
    for other in others:
        if row[other] == actor["id"] and not (shared_dpo and other in ("privacy_review_by", "legal_review_by")):
            raise HTTPException(409, "Acknowledgement and the reviews need separate people")
    db.execute(f"UPDATE {_table('org_relationships')} SET {col}=%s WHERE id=%s AND status='proposed'",
               (actor["id"], relation_id))
    active = _activate_if_ready(db, relation_id, row["child_org_id"])
    return {"id": relation_id, "status": "active" if active else "proposed"}


def grant_view(db, actor: dict, relation_id: int, user_id: int, capability: str,
               expires_at: str, review_due_at: str) -> int:
    row = _relationship(db, relation_id)
    if actor.get("org_id") not in (row["parent_org_id"], row["child_org_id"]):
        raise HTTPException(404, "Relationship not found")
    if not has_capability(actor, "group.grant.manage") or capability not in (
            "document.view", "document.download", "figure.view"):
        raise HTTPException(403, "Grant management required")
    _assert_edge(db, row)
    target = db.execute("SELECT org_id FROM users WHERE id=%s AND is_active=1 AND deleted_at IS NULL",
                        (user_id,)).fetchone()
    if not target or target["org_id"] != actor["org_id"]:
        raise HTTPException(404, "Recipient not found")
    source = row["child_org_id"] if actor["org_id"] == row["parent_org_id"] else row["parent_org_id"]
    expiry = _deadline(expires_at, MAX_GRANT_DAYS)
    review = _deadline(review_due_at, MAX_GRANT_DAYS)
    if review > expiry:
        raise HTTPException(422, "Review date cannot follow expiry")
    return insert_returning_id(db, f"INSERT INTO {_table('group_view_grants')} "
                               "(relationship_id,source_org_id,viewer_org_id,user_id,capability,expires_at,review_due_at,granted_by) "
                               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                               (relation_id, source, actor["org_id"], user_id, capability,
                                expiry, review, actor["id"]))


def reviewed_rights(db, actor: dict, evidence_id: int, rights_state: str,
                    group_view: bool, group_download: bool, basis: str) -> int:
    if not actor.get("org_id") or not has_capability(actor, "group.rights.review"):
        raise HTTPException(403, "Rights review required")
    if rights_state not in ("unknown", "owned", "licensed") or not basis.strip() or len(basis) > 500:
        raise HTTPException(422, "Record the rights state and basis")
    if rights_state == "unknown" and (group_view or group_download):
        raise HTTPException(422, "Unknown rights cannot permit redistribution")
    scope, params = evidence_scope_sql(actor)
    item = db.execute(f"SELECT e.id,e.file_hash,e.status FROM evidence_items e WHERE e.id=%s AND {scope}",
                      [evidence_id, *params]).fetchone()
    if not item or item["status"] != "current" or not item["file_hash"]:
        raise HTTPException(404, "Evidence not found")
    existing = db.execute(f"SELECT id FROM {_table('group_document_rights')} "
                          "WHERE source_org_id=%s AND evidence_id=%s AND file_hash=%s",
                          (actor["org_id"], evidence_id, item["file_hash"])).fetchone()
    if existing:
        db.execute(f"UPDATE {_table('group_document_rights')} SET rights_state=%s,permit_group_view=%s, "
                   "permit_group_download=%s,basis=%s,reviewed_by=%s,reviewed_at=%s WHERE id=%s",
                   (rights_state, int(group_view), int(group_download), basis.strip(), actor["id"], _now(), existing["id"]))
        return existing["id"]
    return insert_returning_id(db, f"INSERT INTO {_table('group_document_rights')} "
                               "(source_org_id,evidence_id,file_hash,rights_state,permit_group_view, "
                               "permit_group_download,basis,reviewed_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                               (actor["org_id"], evidence_id, item["file_hash"], rights_state,
                                int(group_view), int(group_download), basis.strip(), actor["id"]))


def publish(db, actor: dict, relation_id: int, evidence_id: int,
            classification: str, purpose: str, expires_at: str) -> int:
    row = _relationship(db, relation_id)
    if actor.get("org_id") not in (row["parent_org_id"], row["child_org_id"]):
        raise HTTPException(404, "Relationship not found")
    if not has_capability(actor, "group.document.publish"):
        raise HTTPException(403, "Publication capability required")
    _assert_edge(db, row)
    terms = json.loads(row["terms_json"])
    if "document_metadata" not in terms.get("data_classes", []):
        raise HTTPException(404, "Publication not approved")
    if classification not in ("internal", "confidential") or not purpose.strip() or len(purpose) > 300:
        raise HTTPException(422, "Record classification and purpose")
    if classification not in terms.get("classifications", []) or purpose.strip() != row["purpose"]:
        raise HTTPException(409, "Publication exceeds approved sharing terms")
    scope, params = evidence_scope_sql(actor)
    item = db.execute(f"SELECT e.id,e.org_id,e.title,e.category,e.version,e.file_hash,e.status,e.file_path, "
                      "e.aria_policy_version_id "
                      f"FROM evidence_items e WHERE e.id=%s AND {scope}", [evidence_id, *params]).fetchone()
    if not item or item["org_id"] != actor["org_id"] or item["status"] != "current" or not item["file_hash"]:
        raise HTTPException(404, "Evidence not found")
    if item["category"] == "policy":
        version_id = item["aria_policy_version_id"]
        approved = db.execute("SELECT id FROM aria_policy_versions WHERE id=%s AND org_id=%s AND state='approved'",
                              (version_id, actor["org_id"])).fetchone() if version_id else None
        if not approved:
            raise HTTPException(409, "A group policy needs an approved ARIA version")
    rights = db.execute(f"SELECT * FROM {_table('group_document_rights')} "
                        "WHERE source_org_id=%s AND evidence_id=%s AND file_hash=%s",
                        (actor["org_id"], evidence_id, item["file_hash"])).fetchone()
    if not rights or rights["rights_state"] == "unknown" or not rights["permit_group_view"]:
        raise HTTPException(409, "Distribution rights are not approved")
    if rights["reviewed_by"] == actor["id"]:
        raise HTTPException(409, "An independent publisher must approve this version")
    target = row["child_org_id"] if actor["org_id"] == row["parent_org_id"] else row["parent_org_id"]
    active = db.execute(f"SELECT id FROM {_table('group_document_publications')} "
                        "WHERE relationship_id=%s AND viewer_org_id=%s AND evidence_id=%s AND revoked_at IS NULL",
                        (relation_id, target, evidence_id)).fetchone()
    if active:
        raise HTTPException(409, "This version is already published")
    return insert_returning_id(db, f"INSERT INTO {_table('group_document_publications')} "
                               "(relationship_id,source_org_id,viewer_org_id,evidence_id,version,file_hash,title, "
                               "category,classification,purpose,rights_id,expires_at,approved_by) "
                               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                               (relation_id, actor["org_id"], target, evidence_id, item["version"],
                                item["file_hash"], item["title"], item["category"], classification,
                                purpose.strip(), rights["id"], _deadline(expires_at, MAX_GRANT_DAYS), actor["id"]))


def _source_current(row, *, download: bool = False):
    """Narrow, version-bound source read after the viewer grant is checked.

    This is a service context switch, not user impersonation. RLS is bound to
    the source org on a fresh connection, and the query is pinned to the
    approved id, organization and hash. It never accepts caller SQL.
    """
    with tenant_context(row["source_org_id"], row["source_slug"], is_super_admin=False):
        source = get_db()
        try:
            rights = source.execute(f"SELECT permit_group_view,permit_group_download,rights_state,reviewed_by "
                                    f"FROM {_table('group_document_rights')} WHERE id=%s AND source_org_id=%s "
                                    "AND evidence_id=%s AND file_hash=%s",
                                    (row["rights_id"], row["source_org_id"], row["evidence_id"],
                                     row["file_hash"])).fetchone()
            if not rights or rights["rights_state"] == "unknown" or not rights["permit_group_view"]:
                return None
            if rights["reviewed_by"] == row["approved_by"]:
                return None
            if download and not rights["permit_group_download"]:
                return None
            item = source.execute(
                "SELECT id, file_path, file_name, mime_type, category, aria_policy_version_id FROM evidence_items "
                "WHERE id=%s AND org_id=%s AND file_hash=%s AND version=%s AND status='current'",
                (row["evidence_id"], row["source_org_id"], row["file_hash"], row["version"]),
            ).fetchone()
            if item and item["category"] == "policy":
                version_id = item["aria_policy_version_id"]
                approved = source.execute(
                    "SELECT id FROM aria_policy_versions WHERE id=%s AND org_id=%s AND state='approved'",
                    (version_id, row["source_org_id"])).fetchone() if version_id else None
                if not approved:
                    return None
            return dict(item) if item else None
        finally:
            source.close()


def _granted_rows(db, actor: dict, *, publication_id: int | None = None,
                  page: int = 1, page_size: int = 50, category: str | None = None,
                  source_org_id: int | None = None, before_id: int | None = None):
    if not actor.get("org_id") or not has_capability(actor, "group.document.view"):
        return []
    if not 1 <= page <= 100000 or not 1 <= page_size <= 100:
        raise HTTPException(422, "Invalid catalogue page")
    exact = "AND p.id=%s " if publication_id is not None else ""
    paging = "" if publication_id is not None else (
        "LIMIT %s" if before_id is not None else "LIMIT %s OFFSET %s")
    now = _now()
    parameters = [actor["id"], now, now, actor["org_id"], now, now]
    category_sql = "AND p.category=%s " if category else ""
    if category:
        parameters.append(category)
    source_sql = "AND p.source_org_id=%s " if source_org_id is not None else ""
    if source_org_id is not None:
        parameters.append(source_org_id)
    cursor_sql = "AND p.id<%s " if before_id is not None else ""
    if before_id is not None:
        parameters.append(before_id)
    if publication_id is not None:
        parameters.append(publication_id)
    else:
        parameters.extend((page_size,) if before_id is not None else
                          (page_size, (page - 1) * page_size))
    rows = db.execute(
        f"SELECT p.*, o.slug AS source_slug, o.name AS source_name, "
        "r.terms_json AS sharing_terms, r.purpose AS sharing_purpose "
        f"FROM {_table('group_document_publications')} p "
        f"JOIN {_table('org_relationships')} r ON r.id=p.relationship_id "
        "JOIN organizations o ON o.id=p.source_org_id AND o.status='active' "
        "JOIN organizations v ON v.id=p.viewer_org_id AND v.status='active' "
        f"WHERE EXISTS (SELECT 1 FROM {_table('group_view_grants')} g "
        "WHERE g.relationship_id=p.relationship_id AND g.source_org_id=p.source_org_id "
        "AND g.viewer_org_id=p.viewer_org_id AND g.user_id=%s "
        "AND g.capability='document.view' AND g.revoked_at IS NULL "
        "AND g.expires_at>%s AND g.review_due_at>%s) "
        "AND p.viewer_org_id=%s AND p.revoked_at IS NULL AND p.expires_at>%s "
        "AND r.status='active' AND (r.child_ack_by IS NOT NULL OR r.notice_deemed_at IS NOT NULL) "
        "AND r.privacy_review_by IS NOT NULL "
        "AND r.legal_review_by IS NOT NULL AND r.review_due_at>%s "
        "AND r.parent_org_id IN (p.source_org_id,p.viewer_org_id) "
        "AND r.child_org_id IN (p.source_org_id,p.viewer_org_id) " + category_sql + source_sql + cursor_sql + exact +
        ("ORDER BY p.id DESC " if before_id is not None else "ORDER BY p.created_at DESC,p.id DESC ") + paging,
        parameters,
    ).fetchall()
    return [dict(r) for r in rows]


def catalogue(db, actor: dict, *, page: int = 1, page_size: int = 50,
              category: str | None = None) -> list[dict]:
    out = []
    for row in _granted_rows(db, actor, page=page, page_size=page_size, category=category):
        entry = _catalogue_entry(db, actor, row)
        if entry:
            out.append(entry)
    return out


def _catalogue_entry(db, actor: dict, row: dict) -> dict | None:
    terms = json.loads(row["sharing_terms"])
    if ("document_metadata" in terms.get("data_classes", [])
            and set(actor.get("roles") or []) & set(terms.get("audiences", []))
            and row["classification"] in terms.get("classifications", [])
            and row["purpose"] == row["sharing_purpose"] and _source_current(row)):
        can_download = False
        if ("document_bytes" in terms.get("data_classes", [])
                and has_capability(actor, "group.document.download")):
            grant = db.execute(f"SELECT id FROM {_table('group_view_grants')} "
                               "WHERE relationship_id=%s AND source_org_id=%s AND viewer_org_id=%s "
                               "AND user_id=%s AND capability='document.download' AND revoked_at IS NULL "
                               "AND expires_at>%s AND review_due_at>%s LIMIT 1",
                               (row["relationship_id"], row["source_org_id"], row["viewer_org_id"],
                                actor["id"], _now(), _now())).fetchone()
            can_download = bool(grant and _source_current(row, download=True))
        return {"id": row["id"], "source_org_id": row["source_org_id"],
                "source_name": row["source_name"], "title": row["title"],
                "category": row["category"], "version": row["version"],
                "classification": row["classification"], "expires_at": row["expires_at"],
                "can_download": can_download}
    return None


def source_companies(db, actor: dict) -> list[dict]:
    """A name is shown only for an active relationship and named view grant."""
    if not actor.get("org_id") or not has_capability(actor, "group.document.view"):
        return []
    rows = db.execute(
        f"SELECT DISTINCT o.id,o.name FROM {_table('group_view_grants')} g "
        f"JOIN {_table('org_relationships')} r ON r.id=g.relationship_id "
        "JOIN organizations o ON o.id=g.source_org_id AND o.status='active' "
        "WHERE g.viewer_org_id=%s AND g.user_id=%s AND g.capability='document.view' "
        "AND g.revoked_at IS NULL AND g.expires_at>%s AND g.review_due_at>%s "
        "AND r.status='active' AND (r.child_ack_by IS NOT NULL OR r.notice_deemed_at IS NOT NULL) "
        "AND r.privacy_review_by IS NOT NULL AND r.legal_review_by IS NOT NULL "
        "AND r.review_due_at>%s AND r.parent_org_id IN (g.source_org_id,g.viewer_org_id) "
        "AND r.child_org_id IN (g.source_org_id,g.viewer_org_id) ORDER BY o.name,o.id",
        (actor["org_id"], actor["id"], _now(), _now(), _now()),
    ).fetchall()
    return [dict(row) for row in rows]


def catalogue_cursor(db, actor: dict, *, source_org_id: int, before_id: int | None = None,
                     page_size: int = 50) -> dict:
    """Fill a page from source-rechecked releases. Invalidated rows do not make empty pages."""
    if not isinstance(source_org_id, int) or source_org_id < 1:
        raise HTTPException(422, "Choose a source company")
    if before_id is not None and (not isinstance(before_id, int) or before_id < 1):
        raise HTTPException(422, "Invalid catalogue cursor")
    if not 1 <= page_size <= 100:
        raise HTTPException(422, "Invalid catalogue page size")
    if not any(row["id"] == source_org_id for row in source_companies(db, actor)):
        # An unknown source and a source without a current named grant look alike.
        raise HTTPException(404, "Company not found")
    found = []
    cursor = before_id
    exhausted = False
    # Each candidate is rechecked in the source tenant, so bound the work of one page: at most ten batches of 100.
    # When the bound is reached first, the page is shorter and the cursor continues from where the scan stopped.
    for _batch in range(10):
        if len(found) > page_size:
            break
        rows = _granted_rows(db, actor, page_size=100, source_org_id=source_org_id,
                             before_id=cursor if cursor is not None else 2**63 - 1)
        if not rows:
            exhausted = True
            break
        for row in rows:
            cursor = row["id"]
            entry = _catalogue_entry(db, actor, row)
            if entry:
                found.append(entry)
            if len(found) > page_size:
                break
        if len(rows) < 100 and len(found) <= page_size:
            exhausted = True
            break
    items = found[:page_size]
    if len(found) > page_size:
        next_cursor = items[-1]["id"]
    else:
        next_cursor = None if exhausted else cursor
    return {"items": items, "next_cursor": next_cursor}


def released_item(db, actor: dict, publication_id: int, *, download: bool = False):
    if download and not has_capability(actor, "group.document.download"):
        raise HTTPException(404, "Publication not found")
    row = next(iter(_granted_rows(db, actor, publication_id=publication_id)), None)
    if row is None:
        raise HTTPException(404, "Publication not found")
    terms = json.loads(row["sharing_terms"])
    if ("document_metadata" not in terms.get("data_classes", [])
            or not set(actor.get("roles") or []) & set(terms.get("audiences", []))
            or row["classification"] not in terms.get("classifications", [])
            or row["purpose"] != row["sharing_purpose"]):
        raise HTTPException(404, "Publication not found")
    if download:
        if "document_bytes" not in terms.get("data_classes", []):
            raise HTTPException(404, "Publication not found")
        grant = db.execute(f"SELECT id FROM {_table('group_view_grants')} WHERE relationship_id=%s "
                           "AND source_org_id=%s AND viewer_org_id=%s AND user_id=%s "
                           "AND capability='document.download' AND revoked_at IS NULL "
                           "AND expires_at>%s AND review_due_at>%s LIMIT 1",
                           (row["relationship_id"], row["source_org_id"], row["viewer_org_id"],
                            actor["id"], _now(), _now())).fetchone()
        if not grant:
            raise HTTPException(404, "Publication not found")
    item = _source_current(row, download=download)
    if not item:
        raise HTTPException(404, "Publication not found")
    return row, item


def access_event(db, row, actor: dict, action: str):
    db.execute(f"INSERT INTO {_table('group_access_events')} "
               "(relationship_id,source_org_id,viewer_org_id,publication_id,actor_id,action) "
               "VALUES (%s,%s,%s,%s,%s,%s)",
               (row["relationship_id"], row["source_org_id"], row["viewer_org_id"],
                row["id"], actor["id"], action))


def revoke_grant(db, actor: dict, grant_id: int) -> None:
    if not has_capability(actor, "group.grant.manage"):
        raise HTTPException(404, "Grant not found")
    row = db.execute(f"SELECT g.*, r.parent_org_id,r.child_org_id FROM {_table('group_view_grants')} g "
                     f"JOIN {_table('org_relationships')} r ON r.id=g.relationship_id "
                     "WHERE g.id=%s AND g.viewer_org_id=%s", (grant_id, actor.get("org_id"))).fetchone()
    if not row:
        raise HTTPException(404, "Grant not found")
    db.execute(f"UPDATE {_table('group_view_grants')} SET revoked_at=%s WHERE id=%s AND revoked_at IS NULL",
               (_now(), grant_id))
    db.execute(f"INSERT INTO {_table('group_access_events')} "
               "(relationship_id,source_org_id,viewer_org_id,actor_id,action,detail) "
               "VALUES (%s,%s,%s,%s,'revoke_grant',%s)",
               (row["relationship_id"], row["source_org_id"], row["viewer_org_id"],
                actor["id"], str(grant_id)))


def review_grant(db, actor: dict, grant_id: int, decision: str, reason: str,
                 expires_at: str | None = None, review_due_at: str | None = None) -> dict:
    """Replace a grant after independent review; preserve its immutable decision trail."""
    if not has_capability(actor, "group.grant.manage"):
        raise HTTPException(404, "Grant not found")
    row = db.execute(f"SELECT * FROM {_table('group_view_grants')} "
                     "WHERE id=%s AND viewer_org_id=%s AND revoked_at IS NULL",
                     (grant_id, actor.get("org_id"))).fetchone()
    if not row:
        raise HTTPException(404, "Grant not found")
    if actor["id"] in (row["granted_by"], row["user_id"]):
        raise HTTPException(403, "A different specialist must review this grant")
    if decision not in ("keep", "narrow", "revoke") or not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 500:
        raise HTTPException(422, "Choose a review outcome and record a reason")
    if decision == "narrow" and row["capability"] != "document.download":
        raise HTTPException(422, "Only download access can be narrowed to view")
    relation = _relationship(db, row["relationship_id"])
    _assert_edge(db, relation)
    replacement_id = None
    if decision != "revoke":
        capability = "document.view" if decision == "narrow" else row["capability"]
        replacement_id = grant_view(db, actor, row["relationship_id"], row["user_id"],
                                    capability, expires_at, review_due_at)
    changed = db.execute(f"UPDATE {_table('group_view_grants')} SET revoked_at=%s "
                         "WHERE id=%s AND revoked_at IS NULL", (_now(), grant_id))
    if changed.rowcount != 1:
        raise HTTPException(409, "Grant changed during review")
    db.execute(f"INSERT INTO {_table('group_access_events')} "
               "(relationship_id,source_org_id,viewer_org_id,actor_id,action,detail) "
               "VALUES (%s,%s,%s,%s,'review_grant',%s)",
               (row["relationship_id"], row["source_org_id"], row["viewer_org_id"], actor["id"],
                json.dumps({"grant_id": grant_id, "outcome": decision,
                            "replacement_id": replacement_id, "reason": reason.strip()}, sort_keys=True)))
    return {"status": decision, "replacement_id": replacement_id}


def revoke_publication(db, actor: dict, publication_id: int) -> None:
    if not has_capability(actor, "group.document.publish"):
        raise HTTPException(404, "Publication not found")
    row = db.execute(f"SELECT * FROM {_table('group_document_publications')} "
                     "WHERE id=%s AND source_org_id=%s AND revoked_at IS NULL",
                     (publication_id, actor.get("org_id"))).fetchone()
    if not row:
        raise HTTPException(404, "Publication not found")
    db.execute(f"UPDATE {_table('group_document_publications')} SET revoked_at=%s WHERE id=%s",
               (_now(), publication_id))
    access_event(db, row, actor, "revoke_publication")


def exit_impact(db, actor: dict, relation_id: int) -> dict:
    if not has_capability(actor, "group.relationship.manage"):
        raise HTTPException(404, "Relationship not found")
    row = _relationship(db, relation_id)
    if row["status"] == "ended":
        raise HTTPException(404, "Relationship not found")
    grants = db.execute(f"SELECT COUNT(*) FROM {_table('group_view_grants')} "
                        "WHERE relationship_id=%s AND revoked_at IS NULL", (relation_id,)).fetchone()[0]
    publications = db.execute(f"SELECT COUNT(*) FROM {_table('group_document_publications')} "
                              "WHERE relationship_id=%s AND revoked_at IS NULL", (relation_id,)).fetchone()[0]
    return {"relationship_id": relation_id, "status": row["status"],
            "active_grants": grants, "active_publications": publications}


def end_relationship(db, actor: dict, relation_id: int, reason: str) -> dict:
    impact = exit_impact(db, actor, relation_id)
    if not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 500:
        raise HTTPException(422, "Record a reason for ending this relationship")
    db.execute(f"UPDATE {_table('org_relationships')} "
               "SET status='ended',ended_at=%s,ended_by=%s,end_reason=%s WHERE id=%s",
               (_now(), actor["id"], reason.strip(), relation_id))
    return impact
