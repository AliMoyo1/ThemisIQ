"""Reviewed company labels for source-tenant Vault items.

These labels help people browse. They never grant access to an item or to a
different tenant. An unconfirmed label is not presented as a company filing.
"""

from fastapi import HTTPException

from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.evidence.scope import evidence_scope_sql
from modules.governance.data_service import bu_scope_ids


def _org(actor):
    org_id = actor.get("org_id")
    if not isinstance(org_id, int) or org_id < 1:
        raise HTTPException(403, "Select an organization")
    return org_id


def _item(db, actor, evidence_id):
    scope, params = evidence_scope_sql({**actor, "is_super_admin": False})
    row = db.execute(
        f"SELECT e.id,e.org_id,e.company_id,e.company_state,e.company_proposed_by "
        f"FROM evidence_items e WHERE e.id=%s AND e.org_id=%s AND {scope}",
        [evidence_id, _org(actor), *params],
    ).fetchone()
    if not row:
        raise HTTPException(404, "Evidence not found")
    return row


def _reason(value):
    if not isinstance(value, str) or not 5 <= len(value.strip()) <= 500:
        raise HTTPException(422, "Record a reason of 5 to 500 characters")
    return value.strip()


def create_company(db, actor, name):
    if not has_capability(actor, "evidence.company.manage"):
        raise HTTPException(403, "Company catalogue permission required")
    if not isinstance(name, str) or not 2 <= len(name.strip()) <= 120:
        raise HTTPException(422, "Use a company name of 2 to 120 characters")
    cleaned = " ".join(name.split())
    existing = db.execute(
        "SELECT id FROM evidence_companies WHERE org_id=%s AND LOWER(name)=LOWER(%s)",
        (_org(actor), cleaned),
    ).fetchone()
    if existing:
        raise HTTPException(409, "Company already exists")
    return insert_returning_id(db,
        "INSERT INTO evidence_companies(org_id,name,created_by) VALUES(%s,%s,%s)",
        (_org(actor), cleaned, actor["id"]))


def companies(db, actor):
    if not (has_capability(actor, "evidence.company.manage") or
            has_capability(actor, "evidence.company.review")):
        return [{"id": row["id"], "name": row["name"]} for row in facets(db, actor)["companies"]]
    return [dict(row) for row in db.execute(
        "SELECT id,name FROM evidence_companies WHERE org_id=%s AND is_active=1 ORDER BY name,id",
        (_org(actor),)).fetchall()]


def propose(db, actor, evidence_id, company_id, reason):
    if not has_capability(actor, "evidence.company.manage"):
        raise HTTPException(403, "Company assignment permission required")
    if not isinstance(company_id, int) or isinstance(company_id, bool) or company_id < 1:
        raise HTTPException(422, "Choose a company")
    row = _item(db, actor, evidence_id)
    company = db.execute(
        "SELECT id FROM evidence_companies WHERE id=%s AND org_id=%s AND is_active=1",
        (company_id, _org(actor)),
    ).fetchone()
    if not company:
        raise HTTPException(404, "Company not found")
    if row["company_state"] == "pending":
        raise HTTPException(409, "This company assignment awaits review")
    why = _reason(reason)
    db.execute("UPDATE evidence_items SET company_id=%s,company_state='pending',"
               "company_proposed_by=%s,company_reviewed_by=NULL,company_reviewed_at=NULL,"
               "company_reason=%s WHERE id=%s AND org_id=%s",
               (company_id, actor["id"], why, evidence_id, _org(actor)))
    db.execute("INSERT INTO evidence_company_events(org_id,evidence_id,company_id,action,actor_id,reason) "
               "VALUES(%s,%s,%s,'proposed',%s,%s)",
               (_org(actor), evidence_id, company_id, actor["id"], why))


def review(db, actor, evidence_id, decision, reason):
    if not has_capability(actor, "evidence.company.review"):
        raise HTTPException(403, "Company review permission required")
    row = _item(db, actor, evidence_id)
    if row["company_state"] != "pending":
        raise HTTPException(409, "No company assignment awaits review")
    if row["company_proposed_by"] == actor["id"]:
        raise HTTPException(409, "A different specialist must review this assignment")
    if decision not in ("confirm", "reject"):
        raise HTTPException(422, "Choose confirm or reject")
    state = "confirmed" if decision == "confirm" else "rejected"
    why = _reason(reason)
    changed = db.execute("UPDATE evidence_items SET company_state=%s,company_reviewed_by=%s,"
               "company_reviewed_at=%s,company_reason=%s WHERE id=%s AND org_id=%s "
               "AND company_state='pending'",
               (state, actor["id"], utcnow().isoformat(), why,
                evidence_id, _org(actor)))
    if changed.rowcount != 1:
        raise HTTPException(409, "This assignment changed. Reload and try again")
    db.execute("INSERT INTO evidence_company_events(org_id,evidence_id,company_id,action,actor_id,reason) "
               "VALUES(%s,%s,%s,%s,%s,%s)",
               (_org(actor), evidence_id, row["company_id"], state, actor["id"], why))
    return state


def facets(db, actor):
    """Visible current rows only. A hidden company's name never reaches the list."""
    scope, params = evidence_scope_sql({**actor, "is_super_admin": False})
    rows = db.execute(
        "SELECT c.id,c.name,COUNT(*) AS count FROM evidence_items e "
        "JOIN evidence_companies c ON c.id=e.company_id AND c.org_id=e.org_id "
        f"WHERE e.org_id=%s AND {scope} AND e.company_state='confirmed' "
        "AND c.is_active=1 AND e.status NOT IN ('archived','superseded') "
        "GROUP BY c.id,c.name ORDER BY c.name,c.id",
        [_org(actor), *params],
    ).fetchall()
    unconfirmed = db.execute(
        f"SELECT COUNT(*) FROM evidence_items e WHERE e.org_id=%s AND {scope} "
        "AND e.status NOT IN ('archived','superseded') "
        "AND NOT EXISTS (SELECT 1 FROM evidence_companies c WHERE c.id=e.company_id "
        "AND c.org_id=e.org_id AND c.is_active=1 AND e.company_state='confirmed')",
        [_org(actor), *params],
    ).fetchone()[0]
    return {"companies": [dict(row) for row in rows], "unconfirmed": unconfirmed}


def selected_company(db, actor, raw):
    if raw == "unconfirmed":
        return None
    if not isinstance(raw, str) or not raw.isdecimal() or int(raw) < 1:
        raise HTTPException(404, "Company view not found")
    company_id = int(raw)
    scope, params = evidence_scope_sql({**actor, "is_super_admin": False})
    visible = db.execute(
        "SELECT 1 FROM evidence_items e JOIN evidence_companies c "
        "ON c.id=e.company_id AND c.org_id=e.org_id "
        f"WHERE e.org_id=%s AND {scope} AND c.id=%s AND c.is_active=1 "
        "AND e.company_state='confirmed' LIMIT 1",
        [_org(actor), *params, company_id],
    ).fetchone()
    if not visible:
        raise HTTPException(404, "Company view not found")
    return company_id


def history(db, actor, evidence_id):
    _item(db, actor, evidence_id)
    return [dict(row) for row in db.execute(
        "SELECT action,actor_id,reason,created_at FROM evidence_company_events "
        "WHERE org_id=%s AND evidence_id=%s ORDER BY id DESC LIMIT 100",
        (_org(actor), evidence_id)).fetchall()]


def _visible_unit(db, actor, unit_id):
    if not isinstance(unit_id, int) or isinstance(unit_id, bool) or unit_id < 1:
        raise HTTPException(404, "Business unit not found")
    allowed = bu_scope_ids(actor)
    if allowed is not None and unit_id not in allowed:
        raise HTTPException(404, "Business unit not found")
    row = db.execute("SELECT id,name FROM business_units WHERE id=%s AND is_active=1",
                     (unit_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Business unit not found")
    return row


def unit_mappings(db, actor):
    """An approved map suggests a filing label; it never changes an item's scope."""
    if not (has_capability(actor, "evidence.company.manage") or
            has_capability(actor, "evidence.company.review")):
        raise HTTPException(403, "Company catalogue permission required")
    allowed = bu_scope_ids(actor)
    if allowed is not None and not [unit for unit in allowed if unit > 0]:
        return []
    scope = "" if allowed is None else "AND u.id IN (" + ",".join("%s" for _ in allowed) + ") "
    rows = db.execute(
        "SELECT u.id AS unit_id,u.name AS unit_name,m.confirmed_company_id,"
        "m.proposed_company_id,m.proposed_by,m.proposed_reason,m.reviewed_by,m.review_reason,"
        "c.name AS confirmed_company_name,p.name AS proposed_company_name "
        "FROM business_units u LEFT JOIN evidence_unit_company_mappings m "
        "ON m.business_unit_id=u.id AND m.org_id=%s "
        "LEFT JOIN evidence_companies c ON c.id=m.confirmed_company_id AND c.org_id=m.org_id "
        "LEFT JOIN evidence_companies p ON p.id=m.proposed_company_id AND p.org_id=m.org_id "
        "WHERE u.is_active=1 " + scope + "ORDER BY u.name,u.id",
        [_org(actor), *([] if allowed is None else allowed)],
    ).fetchall()
    return [dict(row) for row in rows]


def propose_unit_mapping(db, actor, unit_id, company_id, reason):
    if not has_capability(actor, "evidence.company.manage"):
        raise HTTPException(403, "Company assignment permission required")
    _visible_unit(db, actor, unit_id)
    if not isinstance(company_id, int) or isinstance(company_id, bool) or company_id < 1:
        raise HTTPException(422, "Choose a company")
    org_id = _org(actor)
    company = db.execute("SELECT id FROM evidence_companies WHERE id=%s AND org_id=%s AND is_active=1",
                         (company_id, org_id)).fetchone()
    if not company:
        raise HTTPException(404, "Company not found")
    why = _reason(reason)
    row = db.execute("SELECT id,proposed_company_id,confirmed_company_id FROM evidence_unit_company_mappings "
                     "WHERE org_id=%s AND business_unit_id=%s", (org_id, unit_id)).fetchone()
    if row and row["proposed_company_id"] is not None:
        raise HTTPException(409, "This unit mapping awaits review")
    if row and row["confirmed_company_id"] == company_id:
        raise HTTPException(409, "This unit is already mapped to that company")
    if row:
        db.execute("UPDATE evidence_unit_company_mappings SET proposed_company_id=%s,proposed_by=%s,"
                   "proposed_reason=%s WHERE id=%s AND org_id=%s",
                   (company_id, actor["id"], why, row["id"], org_id))
    else:
        db.execute("INSERT INTO evidence_unit_company_mappings "
                   "(org_id,business_unit_id,proposed_company_id,proposed_by,proposed_reason) "
                   "VALUES(%s,%s,%s,%s,%s)", (org_id, unit_id, company_id, actor["id"], why))
    db.execute("INSERT INTO evidence_unit_company_events "
               "(org_id,business_unit_id,company_id,action,actor_id,reason) "
               "VALUES(%s,%s,%s,'proposed',%s,%s)",
               (org_id, unit_id, company_id, actor["id"], why))


def review_unit_mapping(db, actor, unit_id, decision, reason):
    if not has_capability(actor, "evidence.company.review"):
        raise HTTPException(403, "Company review permission required")
    _visible_unit(db, actor, unit_id)
    org_id = _org(actor)
    row = db.execute("SELECT id,proposed_company_id,proposed_by FROM evidence_unit_company_mappings "
                     "WHERE org_id=%s AND business_unit_id=%s", (org_id, unit_id)).fetchone()
    if not row or row["proposed_company_id"] is None:
        raise HTTPException(409, "No unit mapping awaits review")
    if row["proposed_by"] == actor["id"]:
        raise HTTPException(409, "A different specialist must review this mapping")
    if decision not in ("confirm", "reject"):
        raise HTTPException(422, "Choose confirm or reject")
    why = _reason(reason)
    target = row["proposed_company_id"]
    if decision == "confirm":
        company = db.execute("SELECT id FROM evidence_companies WHERE id=%s AND org_id=%s AND is_active=1",
                             (target, org_id)).fetchone()
        if not company:
            raise HTTPException(409, "The proposed company is no longer active")
    changed = db.execute(
        "UPDATE evidence_unit_company_mappings SET "
        "confirmed_company_id=CASE WHEN %s='confirm' THEN proposed_company_id ELSE confirmed_company_id END,"
        "proposed_company_id=NULL,proposed_by=NULL,proposed_reason=NULL,"
        "reviewed_by=%s,reviewed_at=%s,review_reason=%s "
        "WHERE id=%s AND org_id=%s AND proposed_company_id=%s AND proposed_by=%s",
        (decision, actor["id"], utcnow().isoformat(), why, row["id"], org_id,
         target, row["proposed_by"]),
    )
    if changed.rowcount != 1:
        raise HTTPException(409, "This mapping changed. Reload and try again")
    db.execute("INSERT INTO evidence_unit_company_events "
               "(org_id,business_unit_id,company_id,action,actor_id,reason) "
               "VALUES(%s,%s,%s,%s,%s,%s)",
               (org_id, unit_id, target, "confirmed" if decision == "confirm" else "rejected",
                actor["id"], why))
    return decision


def suggested_company_for_unit(db, actor, unit_id):
    if unit_id is None:
        return None
    _visible_unit(db, actor, unit_id)
    row = db.execute("SELECT m.confirmed_company_id FROM evidence_unit_company_mappings m "
                     "JOIN evidence_companies c ON c.id=m.confirmed_company_id "
                     "AND c.org_id=m.org_id AND c.is_active=1 "
                     "WHERE m.org_id=%s AND m.business_unit_id=%s",
                     (_org(actor), unit_id)).fetchone()
    return row["confirmed_company_id"] if row else None
