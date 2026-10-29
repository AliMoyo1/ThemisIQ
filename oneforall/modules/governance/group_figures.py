"""Frozen figures a tenant publishes about itself, and the group's three views of them (plan 21).

No query crosses a tenant. A tenant runs its own Command Centre builders inside its own schema and writes the result to
`public.group_figure_snapshots`; the parent reads those rows only while an active, reviewed relationship exists and only
for the people holding a named, unexpired `figure.view` grant. A subsidiary that has not published recently is **not
reporting** and never counts as zero.
"""
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta

from fastapi import HTTPException

from config import settings
from core import metric_registry as registry
from core.rbac import has_capability
from core.timeutils import utcnow
from database import get_db, get_db_bypass_rls, tenant_context

log = logging.getLogger("oneforall.group_figures")

METHOD_VERSION = "command-centre-1"
STALE_HOURS = 48
_STATES = {"measured", "partial", "not_measured", "unavailable", "stale"}
_MODULES = {"aria", "grid", "bcm", "sentinel", "erm", "orm"}

# Which module families each group role may see. None means every published figure. A figure outside a role's families
# is omitted, so neither its number nor its existence is sent. The platform's own figures ("") are cross-module.
ROLE_FAMILIES = {
    "grc_officer": None,
    "compliance_manager": None,
    "audit_lead": {"grid", "aria", ""},
    "dpo": {"sentinel"},
}

# Detail keys whose text is fixed by the code, never typed by a person. Every other detail value must be a number.
_TEXT_DETAIL = {"module", "unit", "name"}
_DETAIL_KEY = re.compile(r"[a-z0-9_ -]{1,40}")


def _table(name: str) -> str:
    return f"public.{name}" if settings.is_postgres() else name


def _now() -> datetime:
    return utcnow()


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _base(key: str) -> str:
    return key.split(":", 1)[0]


def family_of(key: str) -> str:
    """The module family of a measure: its registered module, or the module a health figure is about."""
    definition = registry.REGISTRY.get(_base(key))
    if definition is None:
        return ""
    if definition.module:
        return definition.module
    suffix = key.split(":", 1)[1] if ":" in key else ""
    return suffix if suffix in _MODULES else ""


def sanitize(metric: dict) -> "dict | None":
    """The part of one metric that may leave the tenant, or None. Only registered keys, known states, a number, the
    registered window text and a detail made of numbers (plus the fixed text keys above) are kept."""
    key = metric.get("key")
    if not isinstance(key, str) or _base(key) not in registry.REGISTRY or metric.get("state") not in _STATES:
        return None
    value = metric.get("value")
    if value is not None and not _num(value):
        return None
    detail = {}
    for name, item in (metric.get("detail") or {}).items():
        if not isinstance(name, str) or not _DETAIL_KEY.fullmatch(name):
            continue
        if _num(item):
            detail[name] = item
        elif name in _TEXT_DETAIL and isinstance(item, str) and len(item) <= 40:
            detail[name] = item
    definition = registry.REGISTRY[_base(key)]
    return {"measure_key": key, "module": family_of(key), "state": metric["state"],
            "value": None if value is None else float(value), "window": definition.window or "",
            "detail": detail}


def _hash(source_org_id: int, row: dict, as_of: str, version: int) -> str:
    payload = json.dumps({"org": source_org_id, "key": row["measure_key"], "state": row["state"],
                          "value": row["value"], "window": row["window"], "detail": row["detail"],
                          "method": METHOD_VERSION, "as_of": as_of, "version": version},
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def collect(org_id: int, slug: str) -> "list[dict]":
    """The publishable figures of one tenant, built inside that tenant for the whole organization."""
    from core.auth import licensed_modules_for
    from modules.launcher import command_metrics
    actor = {"id": 0, "org_id": org_id, "is_super_admin": True, "roles": ["super_admin"], "business_unit_id": None}
    with tenant_context(org_id, slug, is_super_admin=True):
        db = get_db()
        try:
            built = command_metrics.build(db, actor)
            licensed = licensed_modules_for(db, org_id)
        finally:
            db.close()
    metrics = list(built["metrics"].values()) + list(built["health"])
    rows = []
    for metric in metrics:
        row = sanitize(metric)
        if row is None:
            continue
        # A module the organization is not licensed for contributes nothing, not a row of zeros.
        if licensed is not None and row["module"] and row["module"] not in licensed:
            continue
        rows.append(row)
    return rows


def publish_tenant(org_id: int, slug: str) -> int:
    """Freeze the tenant's current figures. Returns how many rows were written."""
    rows = collect(org_id, slug)
    as_of = _now().isoformat()
    db = get_db_bypass_rls()
    try:
        written = 0
        for row in rows:
            last = db.execute(
                f"SELECT MAX(publication_version) AS v FROM {_table('group_figure_snapshots')} "
                "WHERE source_org_id=%s AND measure_key=%s", (org_id, row["measure_key"])).fetchone()
            version = int((last["v"] if last else 0) or 0) + 1
            db.execute(
                f"INSERT INTO {_table('group_figure_snapshots')} "
                "(source_org_id,measure_key,module,state,value,window_text,detail_json,method_version,as_of,"
                "publication_version,content_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (org_id, row["measure_key"], row["module"], row["state"], row["value"], row["window"],
                 json.dumps(row["detail"], sort_keys=True), METHOD_VERSION, as_of, version,
                 _hash(org_id, row, as_of, version)))
            written += 1
        db.commit()
        return written
    finally:
        db.close()


def publish_all() -> dict:
    """Publish every active tenant that is a party to an active relationship (as child or parent)."""
    from database import list_active_tenants
    db = get_db_bypass_rls()
    try:
        involved = {r["org_id"] for r in db.execute(
            f"SELECT parent_org_id AS org_id FROM {_table('org_relationships')} WHERE status='active' "
            f"UNION SELECT child_org_id FROM {_table('org_relationships')} WHERE status='active'").fetchall()}
    finally:
        db.close()
    done = {}
    for org_id, slug in list_active_tenants():
        if org_id not in involved:
            continue
        try:
            done[org_id] = publish_tenant(org_id, slug)
        except Exception:
            log.warning("Group figures: publishing failed for organization %s", org_id, exc_info=True)
    return done


# ── reading ────────────────────────────────────────────────────────────────

def _allowed_families(actor: dict):
    """The module families this person may see: the union over their group roles, or None for every one."""
    allowed = set()
    for role in actor.get("roles") or []:
        if role in ROLE_FAMILIES:
            if ROLE_FAMILIES[role] is None:
                return None
            allowed |= ROLE_FAMILIES[role]
    return allowed


def _children(db, actor: dict) -> "list[dict]":
    """Subsidiaries whose figures this person may read: an active, reviewed, current relationship and a named,
    unexpired figure.view grant for exactly this person."""
    now = _now().isoformat()
    rows = db.execute(
        "SELECT DISTINCT r.id AS relationship_id, o.id AS org_id, o.name AS name "
        f"FROM {_table('org_relationships')} r "
        "JOIN organizations o ON o.id=r.child_org_id AND o.status='active' "
        f"JOIN {_table('group_view_grants')} g ON g.relationship_id=r.id AND g.viewer_org_id=r.parent_org_id "
        "AND g.source_org_id=r.child_org_id AND g.user_id=%s AND g.capability='figure.view' "
        "AND g.revoked_at IS NULL AND g.expires_at>%s AND g.review_due_at>%s "
        "WHERE r.parent_org_id=%s AND r.status='active' "
        "AND (r.child_ack_by IS NOT NULL OR r.notice_deemed_at IS NOT NULL) "
        "AND r.privacy_review_by IS NOT NULL AND r.legal_review_by IS NOT NULL AND r.review_due_at>%s "
        "ORDER BY o.name, o.id", (actor["id"], now, now, actor["org_id"], now)).fetchall()
    return [dict(r) for r in rows]


def _latest(db, org_id: int, families) -> "dict[str, dict]":
    """{measure_key: {latest row, previous value}} for one organization, limited to the allowed families."""
    rows = db.execute(
        "SELECT * FROM (SELECT s.*, ROW_NUMBER() OVER (PARTITION BY measure_key ORDER BY id DESC) AS rn "
        f"FROM {_table('group_figure_snapshots')} s WHERE source_org_id=%s) t WHERE rn<=2 ORDER BY measure_key, rn",
        (org_id,)).fetchall()
    out = {}
    for row in rows:
        row = dict(row)
        if families is not None and row["module"] not in families:
            continue
        if row["rn"] == 1:
            out[row["measure_key"]] = {"row": row, "previous": None}
        elif row["measure_key"] in out:
            out[row["measure_key"]]["previous"] = row["value"]
    return out


def _reporting(latest: dict):
    """(reporting?, last as_of). Not reporting when nothing was published, or the newest figure is older than the
    allowed age. Judged on all rows the person can see, so a role filter cannot make a reporting tenant look absent."""
    newest = max((v["row"]["as_of"] for v in latest.values()), default=None)
    if not newest:
        return False, None
    try:
        age_ok = datetime.fromisoformat(newest) >= _now() - timedelta(hours=STALE_HOURS)
    except ValueError:
        age_ok = False
    return age_ok, newest


def _figure(entry: dict) -> dict:
    row = entry["row"]
    definition = registry.REGISTRY.get(_base(row["measure_key"]))
    detail = json.loads(row["detail_json"] or "{}")
    return {"key": row["measure_key"], "label": definition.label if definition else row["measure_key"],
            "module": row["module"], "state": row["state"], "value": row["value"], "window": row["window_text"],
            "as_of": row["as_of"], "method": row["method_version"], "previous": entry["previous"],
            "detail": detail, "additive": bool(definition and definition.denominator is None
                                                and not row["measure_key"].startswith("cc.module_health"))}


def _entity(db, org_id: int, name: str, families) -> dict:
    latest = _latest(db, org_id, families)
    reporting, last = _reporting(latest)
    figures = [_figure(v) for v in latest.values()] if reporting else []
    return {"org_id": org_id, "name": name, "state": "reporting" if reporting else "not_reporting",
            "last_reported": last, "figures": figures}


def _log(db, actor: dict, relationship_id: int, source_org_id: int, action: str) -> None:
    db.execute(
        f"INSERT INTO {_table('group_access_events')} "
        "(relationship_id,source_org_id,viewer_org_id,actor_id,action,detail) VALUES (%s,%s,%s,%s,%s,%s)",
        (relationship_id, source_org_id, actor["org_id"], actor["id"], action, ""))


def views(db, actor: dict) -> dict:
    """What the caller may open: their own organization and each subsidiary they hold a figure grant for."""
    if not actor.get("org_id") or not has_capability(actor, "group.figure.view_exact"):
        raise HTTPException(403, "Group figure access required")
    org = db.execute("SELECT id, name FROM organizations WHERE id=%s", (actor["org_id"],)).fetchone()
    children = _children(db, actor)
    return {"own": {"org_id": org["id"], "name": org["name"]},
            "subsidiaries": [{"org_id": c["org_id"], "name": c["name"]} for c in children],
            "group": bool(children)}


def view(db, actor: dict, which: str, org_id: "int | None" = None) -> dict:
    """The figures for one view: 'own' (this organization alone), 'subsidiary' (one child) or 'group' (own plus
    every child the person may read, with totals for counts)."""
    if not actor.get("org_id") or not has_capability(actor, "group.figure.view_exact"):
        raise HTTPException(403, "Group figure access required")
    families = _allowed_families(actor)
    org = db.execute("SELECT id, name FROM organizations WHERE id=%s", (actor["org_id"],)).fetchone()
    children = _children(db, actor)
    if which == "own":
        return {"view": "own", "entities": [_entity(db, org["id"], org["name"], families)], "totals": []}
    if which == "subsidiary":
        child = next((c for c in children if c["org_id"] == org_id), None)
        if child is None:
            raise HTTPException(404, "Company not found")  # an unknown company and an ungranted one look alike
        entity = _entity(db, child["org_id"], child["name"], families)
        _log(db, actor, child["relationship_id"], child["org_id"], "figures_view")
        return {"view": "subsidiary", "entities": [entity], "totals": []}
    if which != "group":
        raise HTTPException(422, "Choose a view")
    if not children:
        raise HTTPException(404, "Company not found")
    entities = [_entity(db, org["id"], org["name"], families)]
    for child in children:
        entities.append(_entity(db, child["org_id"], child["name"], families))
        _log(db, actor, child["relationship_id"], child["org_id"], "figures_view")
    return {"view": "group", "entities": entities, "totals": _totals(entities)}


def _totals(entities: "list[dict]") -> "list[dict]":
    """Sums for counts only, over the entities that are reporting. A share or a level is not additive and has no
    total. Not reporting entities add nothing, and the total says how many of the group it covers."""
    reporting = [e for e in entities if e["state"] == "reporting"]
    keys = {}
    for entity in reporting:
        for figure in entity["figures"]:
            if figure["additive"]:
                keys.setdefault(figure["key"], figure["label"])
    totals = []
    for key, label in sorted(keys.items(), key=lambda kv: kv[1]):
        parts = [f for e in reporting for f in e["figures"] if f["key"] == key]
        if any(p["state"] not in ("measured",) or p["value"] is None for p in parts):
            counted = [p for p in parts if p["state"] == "measured" and p["value"] is not None]
        else:
            counted = parts
        totals.append({"key": key, "label": label, "value": sum(p["value"] for p in counted),
                       "entities_counted": len(counted), "entities_total": len(entities)})
    return totals
