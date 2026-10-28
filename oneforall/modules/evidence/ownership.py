"""Reviewed company labels for source-tenant Vault items.

These labels help people browse. They never grant access to an item or to a
different tenant. An unconfirmed label is not presented as a company filing.
"""

from fastapi import HTTPException

from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.evidence.scope import evidence_scope_sql


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
