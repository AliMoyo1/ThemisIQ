"""
AI governance: the inventory list and the connected workspace of one AI use.

Everything here only reads. The list is the applications that have an AI profile, narrowed to what the viewer may open
(the same business-unit rule as every scoped table), filtered and paged on the server. The workspace loads one tab at a
time; each tab asks the owning module's records through the viewer's own scope, so a record the viewer cannot open
contributes no title, no count and no hint that it exists. A section the viewer has no right to says so in one generic
sentence. A source that fails to answer says it is unavailable and is never shown as empty or fine.
"""
import json
import logging

from core.rbac import has_capability
from core.sql_like import ci_like, like_pattern
from core.timeutils import utcnow
from modules.ai_governance import rules
from modules.ai_governance import service
from modules.ai_governance.service import APP, ServiceError
from modules.governance import relationships
from modules.governance.entity_scope import describe_record, entity_scope_sql, may_view_kind

log = logging.getLogger("oneforall.ai_governance")

PAGE_MAX = 100
TABS = ("overview", "assessments", "risks_controls", "data_vendors", "evidence", "decisions", "monitoring", "activity")
STATES = ("active", "retired", "needs_action", "review_due", "all")
_SORTS = {
    "name": "a.name, a.id",
    "tier": "COALESCE(p.adopted_tier, p.provisional_tier), a.name",
    "review": "CASE WHEN p.next_review_at IS NULL THEN 1 ELSE 0 END, p.next_review_at, a.name",
    "updated": "p.updated_at DESC, a.id",
}
_AIIA, _DPIA, _ROPA = ("sentinel", "aiia"), ("sentinel", "dpia"), ("sentinel", "ropa")
_AIMS, _AI_CONTROL = ("orm", "aims"), ("orm", "ai_control")
_RISKS = {("erm", "risk"), ("platform", "risk"), ("aria", "risk"), ("bcm", "risk")}
_INCIDENTS = {("bcm", "incident"), ("orm", "event"), ("sentinel", "breach")}
_OBLIGATIONS = {("erm", "obligation")}
_VENDORS = {("sentinel", "vendor"), ("grid", "vendor"), ("bcm", "vendor")}


def _today() -> str:
    return utcnow().strftime("%Y-%m-%d")


def _int(value, default=None, low=1, high=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < low or (high is not None and number > high):
        return default
    return number


def _needs_action(row, today) -> list:
    reasons = []
    if row["owner_user_id"] is None:
        reasons.append("No owner")
    if rules.effective_tier(row["provisional_tier"], row["adopted_tier"]) == "needs_review":
        reasons.append("Questions unanswered")
    if row["next_review_at"] and str(row["next_review_at"])[:10] <= today:
        reasons.append("Review due")
    return reasons


# ── The inventory ───────────────────────────────────────────────────────────

def list_systems(db, user, *, q=None, owner_id=None, bu_id=None, vendor_id=None, capability_type=None, tier=None,
                 state="active", page=1, page_size=25, sort="name") -> dict:
    """One page of the AI uses the viewer may open, and the total those filters match."""
    service._require(user, "ai_use.view")
    if state not in STATES:
        raise ServiceError(400, "Unknown state filter.")
    if tier is not None and tier not in rules.TIERS:
        raise ServiceError(400, "Unknown tier filter.")
    if capability_type is not None and capability_type not in rules.CAPABILITY_TYPES:
        raise ServiceError(400, "Unknown use type filter.")
    page, page_size = _int(page, 1), _int(page_size, None, high=PAGE_MAX)
    if page_size is None:
        raise ServiceError(400, f"The page size must be 1 to {PAGE_MAX}.")
    order = _SORTS.get(sort)
    if order is None:
        raise ServiceError(400, "Unknown sort.")

    scope, where_params = entity_scope_sql(APP, user, "a")
    where, params = [scope], list(where_params)
    today = _today()
    if state == "active":
        where.append("a.is_active = 1")
    elif state == "retired":
        where.append("a.is_active = 0")
    elif state == "needs_action":
        where.append("a.is_active = 1 AND (a.owner_user_id IS NULL OR COALESCE(p.adopted_tier, p.provisional_tier) = 'needs_review' "
                     "OR (p.next_review_at IS NOT NULL AND p.next_review_at <= %s))")
        params.append(today)
    elif state == "review_due":
        where.append("a.is_active = 1 AND p.next_review_at IS NOT NULL AND p.next_review_at <= %s")
        params.append(today)
    if q:
        where.append(f"({ci_like('a.name')} OR {ci_like('p.purpose')})")
        params += [like_pattern(q), like_pattern(q)]
    for column, value in (("a.owner_user_id", _int(owner_id)), ("a.business_unit_id", _int(bu_id)), ("a.vendor_id", _int(vendor_id))):
        if value is not None:
            where.append(f"{column} = %s")
            params.append(value)
    if capability_type:
        where.append("p.capability_type = %s")
        params.append(capability_type)
    if tier:
        where.append("COALESCE(p.adopted_tier, p.provisional_tier) = %s")
        params.append(tier)

    source = ("FROM applications a JOIN ai_use_profiles p ON p.application_id = a.id "
              "LEFT JOIN business_units bu ON bu.id = a.business_unit_id LEFT JOIN users u ON u.id = a.owner_user_id "
              "LEFT JOIN canonical_vendors cv ON cv.id = a.vendor_id")
    clause = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) {source} WHERE {clause}", params).fetchone()[0]
    rows = db.execute(
        "SELECT a.id, a.name, a.is_active, a.business_unit_id, bu.name AS bu_name, a.owner_user_id, u.full_name AS owner_name, "
        "a.vendor_id, cv.name AS vendor_name, a.criticality, p.capability_type, p.deployment, p.provisional_tier, "
        f"p.adopted_tier, p.last_reviewed_at, p.next_review_at, p.updated_at {source} WHERE {clause} ORDER BY {order} "
        "LIMIT %s OFFSET %s", [*params, page_size, (page - 1) * page_size]).fetchall()
    items = []
    for r in rows:
        tier_now = rules.effective_tier(r["provisional_tier"], r["adopted_tier"])
        items.append({
            "id": r["id"], "name": r["name"], "active": bool(r["is_active"]), "business_unit": r["bu_name"],
            "owner": r["owner_name"], "owner_id": r["owner_user_id"], "vendor": r["vendor_name"],
            "criticality": r["criticality"], "use_type": rules.CAPABILITY_TYPES.get(r["capability_type"]),
            "deployment": rules.DEPLOYMENT.get(r["deployment"]), "tier": tier_now, "tier_label": rules.TIER_LABELS[tier_now],
            "tier_adopted": r["adopted_tier"] is not None, "next_review_at": str(r["next_review_at"] or "")[:10] or None,
            "needs_action": _needs_action(r, today), "url": f"/ai-governance/systems/{r['id']}",
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": max(1, -(-total // page_size))}


def filter_choices(db, user) -> dict:
    """What the list's filters may offer: owners, units and providers of uses the viewer may open, nothing else."""
    service._require(user, "ai_use.view")
    scope, params = entity_scope_sql(APP, user, "a")

    foreign_key = {"users": "owner_user_id", "business_units": "business_unit_id", "canonical_vendors": "vendor_id"}

    def distinct(table, alias, column):
        return db.execute(
            f"SELECT DISTINCT {alias}.id, {alias}.{column} FROM applications a "
            f"JOIN ai_use_profiles p ON p.application_id = a.id JOIN {table} {alias} ON {alias}.id = a.{foreign_key[table]} "
            f"WHERE {scope} ORDER BY {alias}.{column}", params).fetchall()

    owners = distinct("users", "u", "full_name")
    units = distinct("business_units", "bu", "name")
    vendors = distinct("canonical_vendors", "cv", "name")
    return {
        "owners": [{"id": r[0], "name": r[1]} for r in owners], "business_units": [{"id": r[0], "name": r[1]} for r in units],
        "vendors": [{"id": r[0], "name": r[1]} for r in vendors],
        "use_types": [{"id": k, "name": v} for k, v in rules.CAPABILITY_TYPES.items()],
        "tiers": [{"id": t, "name": rules.TIER_LABELS[t]} for t in rules.TIERS],
    }


# ── One system ──────────────────────────────────────────────────────────────

def _can_link(db, user, application_id) -> bool:
    if has_capability(user, "ai_use.link"):
        return True
    row = db.execute("SELECT owner_user_id FROM applications WHERE id = %s", (application_id,)).fetchone()
    return bool(row and row[0] is not None and row[0] == user["id"])


def _next_actions(app, profile, can_review) -> list:
    actions = []
    if app["owner_user_id"] is None:
        actions.append({"text": "Name an owner for this use.", "who": "reviewer"})
    if profile is None:
        actions.append({"text": "Add the AI profile so this use can be assessed.", "who": "reviewer"})
    else:
        if profile["missing"]:
            actions.append({"text": "Answer the open questions: " + ", ".join(rules.label(f) for f in profile["missing"]) + ".",
                            "who": "reviewer"})
        if profile["next_review_at"] and profile["next_review_at"][:10] <= _today():
            actions.append({"text": "The review is due. Look over the profile and mark it reviewed.", "who": "reviewer"})
    return [dict(a, mine=can_review) for a in actions]


def get_system(db, user, application_id: int) -> "dict | None":
    """The application, its profile and the facts every tab shares. None when the viewer may not open it."""
    service._require(user, "ai_use.view")
    if not describe_record(db, APP, application_id, user):
        return None
    app = db.execute(
        "SELECT a.*, bu.name AS bu_name, d.name AS dept_name, cv.name AS vendor_name, u.full_name AS owner_name "
        "FROM applications a LEFT JOIN business_units bu ON bu.id = a.business_unit_id "
        "LEFT JOIN departments d ON d.id = a.department_id LEFT JOIN canonical_vendors cv ON cv.id = a.vendor_id "
        "LEFT JOIN users u ON u.id = a.owner_user_id WHERE a.id = %s", (application_id,)).fetchone()
    profile = service.get_profile(db, user, application_id)
    can_review = has_capability(user, "ai_use.review")
    return {
        "application": {
            "id": app["id"], "name": app["name"], "description": app["description"],
            "hosting": rules.DEPLOYMENT.get(app["hosting"], app["hosting"]),
            "criticality": app["criticality"], "business_unit": app["bu_name"], "department": app["dept_name"],
            "vendor": app["vendor_name"], "owner": app["owner_name"], "owner_id": app["owner_user_id"],
            "active": bool(app["is_active"]), "retired_reason": app["retired_reason"], "retired_at": str(app["retired_at"] or "") or None,
        },
        "profile": profile,
        "labels": {
            "capability_type": rules.CAPABILITY_TYPES, "autonomy": rules.AUTONOMY, "deployment": rules.DEPLOYMENT,
            "data_categories": rules.DATA_CATEGORIES, "affected_people": rules.AFFECTED_PEOPLE,
            "jurisdictions": rules.JURISDICTIONS, "tiers": rules.TIER_LABELS,
        },
        "can": {"review": can_review, "packs": has_capability(user, "ai_pack.manage"),
                "link": _can_link(db, user, application_id),
                "assessments": may_view_kind(user, _AIIA), "evidence": may_view_kind(user, ("evidence", "item"))},
        "next_actions": _next_actions(dict(app), profile, can_review),
        "tabs": list(TABS),
    }


# ── Tabs ────────────────────────────────────────────────────────────────────

def _item(title, url=None, status=None, subtitle=None, source=None, updated_at=None, **extra) -> dict:
    return {"title": title or "(untitled)", "url": url, "status": status, "subtitle": subtitle, "source": source,
            "updated_at": str(updated_at)[:10] if updated_at else None, **extra}


def _section(title, items=None, state=None, note=None) -> dict:
    items = items or []
    return {"title": title, "state": state or ("ok" if items else "empty"), "items": items, "note": note}


def _no_access(title) -> dict:
    return {"title": title, "state": "no_access", "items": [], "note": "You do not have access to this part of the workspace."}


def _unavailable(title, where) -> dict:
    log.warning("AI governance workspace: %s could not be read", where, exc_info=True)
    return {"title": title, "state": "unavailable", "items": [],
            "note": "This could not be loaded just now. It is not shown as empty because it may not be."}


def _guarded(title, where, build):
    try:
        return build()
    except Exception:
        return _unavailable(title, where)


def _linked(db, user, application_id, kinds, verbs=None) -> list:
    """The records this use is linked to, of the given kinds, that the viewer may open (the relationship service)."""
    out = []
    for link in relationships.list_links(db, user, APP, application_id):
        if (link["module"], link["entity_type"]) in kinds and (verbs is None or link["relationship"] in verbs):
            out.append(link)
    return out


def _link_item(link) -> dict:
    return _item(link["title"], link["url"], status=link["label"], source=f"{link['module']} {link['entity_type']}".replace("_", " "),
                 link_id=link["link_id"], provenance=link["provenance"])


def _assessments(db, user, application_id) -> list:
    sections = []
    if not may_view_kind(user, _AIIA):
        return [_no_access("AI impact assessments")]

    def aiia():
        scope, params = entity_scope_sql(_AIIA, user, "a")
        rows = db.execute(
            "SELECT a.id, a.ref_number, a.title, a.status, a.overall_classification, a.updated_at FROM sentinel_aiia a "
            f"WHERE a.application_id = %s AND {scope} ORDER BY a.updated_at DESC LIMIT 50", [application_id, *params]).fetchall()
        return _section("AI impact assessments", [
            _item(f"{r['ref_number']}: {r['title']}", f"/ai-governance/assessments/{r['id']}", status=r["status"],
                  subtitle=(f"Classification: {r['overall_classification']}" if r["overall_classification"] else None),
                  source="AI Governance", updated_at=r["updated_at"]) for r in rows])

    sections.append(_guarded("AI impact assessments", "AIIA", aiia))
    sections.append(_guarded("Privacy assessments linked to this use", "assessment links", lambda: _section(
        "Privacy assessments linked to this use", [_link_item(l) for l in _linked(db, user, application_id, {_DPIA, _ROPA})])))
    return sections


def _decisions(db, user, application_id) -> list:
    """The standing state of the use and its decisions as list sections (the tab itself draws the interactive panel from
    the same service; this keeps the JSON tab call truthful for anything that reads it)."""
    from modules.ai_governance import decisions

    def build():
        got = decisions.get_decisions(db, user, application_id)
        if got is None:
            return _section("Decisions", [], state="unavailable", note="Could not be read.")
        items = []
        if got["open_request"]:
            r = got["open_request"]
            items.append(_item("Waiting for a decision", f"/ai-governance/systems/{application_id}#decisions", status="proposed",
                               subtitle=r["request_note"], source="AI Governance", updated_at=r["requested_at"]))
        for d in got["history"]:
            items.append(_item(f"Decision {d['status'].replace('_', ' ')}", f"/ai-governance/systems/{application_id}#decisions",
                               status=d["status"], subtitle=d["rationale"], source="AI Governance", updated_at=d["decided_at"]))
        note = None if items else "No decision has been recorded for this use."
        return _section(f"Decisions ({got['state']['label']})", items, note=note)

    return [_guarded("Decisions", "decisions", build)]


def _risks_controls(db, user, application_id) -> list:
    sections = []
    if may_view_kind(user, _AIMS):
        def aims():
            scope, params = entity_scope_sql(_AIMS, user, "m")
            rows = db.execute(
                "SELECT m.id, m.ref, m.title, m.status, m.updated_at FROM aims_assessments m "
                f"WHERE m.application_id = %s AND {scope} ORDER BY m.updated_at DESC LIMIT 50", [application_id, *params]).fetchall()
            return _section("AI management assessments", [
                _item(f"{r['ref']}: {r['title']}", "/orm/aims", status=r["status"], source="Operational risk", updated_at=r["updated_at"])
                for r in rows])
        sections.append(_guarded("AI management assessments", "AIMS", aims))
    else:
        sections.append(_no_access("AI management assessments"))
    sections.append(_guarded("Linked risks, controls and incidents", "risk links", lambda: _section(
        "Linked risks, controls and incidents",
        [_link_item(l) for l in _linked(db, user, application_id, _RISKS | _INCIDENTS | _OBLIGATIONS | {_AI_CONTROL, _AIMS})])))
    return sections


def _data_vendors(db, user, application_id) -> list:
    sections = []

    def provider():
        row = db.execute("SELECT cv.id, cv.name FROM applications a JOIN canonical_vendors cv ON cv.id = a.vendor_id "
                         "WHERE a.id = %s", (application_id,)).fetchone()
        items = [_item(row["name"], "/vendors", source="Vendor directory")] if row else []
        items += [_link_item(l) for l in _linked(db, user, application_id, _VENDORS, {"provided_by"})]
        return _section("Provider", items)

    sections.append(_guarded("Provider", "provider", provider))

    def assets():
        scope, params = entity_scope_sql(("governance", "data_asset"), user, "d")
        rows = db.execute(
            "SELECT d.id, d.name, d.classification, d.contains_pii, d.updated_at FROM data_assets d "
            f"WHERE d.application_id = %s AND d.is_active = 1 AND {scope} ORDER BY d.name LIMIT 100", [application_id, *params]).fetchall()
        seen = {r["id"] for r in rows}
        items = [_item(r["name"], "/governance/", status=r["classification"],
                       subtitle=("Contains personal data" if r["contains_pii"] else None), source="Governance") for r in rows]
        items += [_link_item(l) for l in _linked(db, user, application_id, {("governance", "data_asset")}, {"uses_data"})
                  if l["entity_id"] not in seen]
        return _section("Data it uses", items)

    sections.append(_guarded("Data it uses", "data assets", assets))
    sections.append(_guarded("Processes it supports", "process links", lambda: _section(
        "Processes it supports", [_link_item(l) for l in _linked(db, user, application_id, {("governance", "process")}, {"supports", "depends_on"})])))
    return sections


def _evidence(db, user, application_id) -> list:
    if not may_view_kind(user, ("evidence", "item")):
        return [_no_access("Evidence")]

    def build():
        scope, params = entity_scope_sql(("evidence", "item"), user, "e")
        rows = db.execute(
            "SELECT e.id, e.title, e.status, e.expiry_date, e.version, e.updated_at FROM evidence_links l "
            "JOIN evidence_items e ON e.id = l.evidence_id WHERE l.module = 'governance' AND l.entity_type = 'application' "
            f"AND l.entity_id = %s AND l.deleted_at IS NULL AND {scope} ORDER BY e.updated_at DESC LIMIT 100",
            [application_id, *params]).fetchall()
        today = _today()
        items = []
        for r in rows:
            expired = bool(r["expiry_date"]) and str(r["expiry_date"])[:10] < today
            detail = ", ".join(part for part in (f"Version {r['version']}" if r["version"] else "",
                                                 f"expires {str(r['expiry_date'])[:10]}" if r["expiry_date"] else "") if part)
            items.append(_item(r["title"], f"/evidence/?open=item:{r['id']}", status="Expired" if expired else (r["status"] or "current"),
                               subtitle=detail or None, source="Evidence Vault", updated_at=r["updated_at"]))
        return _section("Attached evidence", items, note=None if items else "No evidence is attached to this use yet.")

    return [_guarded("Attached evidence", "evidence", build)]


_ACTIVITY = {
    "ai_use_approved": "Accepted into the inventory", "application_created": "Application created",
    "ai_profile_created": "AI profile created", "ai_profile_updated": "AI profile edited", "ai_profile_reviewed": "Profile reviewed",
    "ai_tier_adopted": "Tier adopted by a reviewer", "ai_use_retired": "Retired", "ai_use_restored": "Restored",
}


def _activity(db, user, application_id) -> list:
    def build():
        sql = ("SELECT username, action, details, created_at FROM audit_log WHERE module = 'ai_governance' "
               "AND entity_type = 'application' AND entity_id = %s")
        params = [application_id]
        if user.get("org_id") is not None:
            sql, params = sql + " AND org_id = %s", [*params, user["org_id"]]
        rows = db.execute(sql + " ORDER BY id DESC LIMIT 50", params).fetchall()
        return _section("Recent activity", [
            _item(_ACTIVITY.get(r["action"]) or r["action"].replace("_", " ").capitalize(), subtitle=r["details"],
                  source=r["username"], updated_at=r["created_at"])
            for r in rows])
    return [_guarded("Recent activity", "activity", build)]


def get_tab(db, user, application_id: int, tab: str) -> "dict | None":
    """The sections of one tab, or None when the viewer may not open this use."""
    service._require(user, "ai_use.view")
    if tab not in TABS:
        raise ServiceError(404, "Unknown tab.")
    if not describe_record(db, APP, application_id, user):
        return None
    if tab == "overview":
        return {"tab": tab, "sections": [], "state": "ok"}
    if tab == "decisions":
        return {"tab": tab, "state": "ok", "sections": _decisions(db, user, application_id)}
    if tab == "monitoring":
        from modules.ai_governance import monitoring
        got = monitoring.get_monitoring(db, user, application_id)
        sections = []
        for s in got["sources"]:
            items = [_item(i["title"], i["url"], subtitle=i["detail"], source="AI Governance") for i in s["items"]]
            state = s["state"] if s["state"] in ("not_measured", "no_access", "unavailable") else ("ok" if items else "empty")
            sections.append(_section(s["title"], items, state=state, note=s["note"]))
        return {"tab": tab, "state": "ok", "sections": sections}
    build = {"assessments": _assessments, "risks_controls": _risks_controls, "data_vendors": _data_vendors,
             "evidence": _evidence, "activity": _activity}[tab]
    return {"tab": tab, "state": "ok", "sections": build(db, user, application_id)}


# ── Linking from the workspace ──────────────────────────────────────────────

def link_kinds() -> list:
    """What a use can be linked to from its workspace: each typed verb with the other end's kinds, read from the
    relationship service's rules so the screen cannot offer a pair the service would refuse."""
    from core.links import RELATIONSHIP_LABELS
    out = []
    for verb, pairs in relationships.PAIR_RULES.items():
        for source, target in sorted(pairs):
            if APP not in (source, target):
                continue
            other = target if source == APP else source
            forward, inverse = RELATIONSHIP_LABELS[verb]
            out.append({"verb": verb, "label": forward if source == APP else inverse,
                        "direction": "outgoing" if source == APP else "incoming", "module": other[0], "type": other[1]})
    return out


def link_candidates(db, user, application_id: int, verb: str, module: str, entity_type: str, q=None, limit=20) -> list:
    """Records of one allowed kind the viewer may open, to pick from when linking. Bounded and scoped like every read."""
    service._require(user, "ai_use.view")
    if not describe_record(db, APP, application_id, user):
        raise ServiceError(404, "Application not found.")
    allowed = {(k["verb"], k["module"], k["type"]) for k in link_kinds()}
    if (verb, module, entity_type) not in allowed:
        raise ServiceError(400, "That kind of record cannot be linked this way.")
    from modules.governance.entity_scope import _KINDS, canonical_key
    key = canonical_key(module, entity_type)
    kind = _KINDS[key]
    scope, params = entity_scope_sql(key, user, "t")
    sql = f"SELECT t.id AS id, t.{kind.title} AS title FROM {kind.table} t WHERE {scope}"
    if q:
        sql, params = sql + f" AND {ci_like('t.' + kind.title)}", [*params, like_pattern(q)]
    rows = db.execute(sql + f" ORDER BY t.{kind.title} LIMIT %s", [*params, max(1, min(int(limit), 50))]).fetchall()
    return [{"id": r["id"], "title": r["title"] or "(untitled)"} for r in rows]
