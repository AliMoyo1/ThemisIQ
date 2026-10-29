"""Frozen figures a tenant publishes about itself, and the group's three views of them (plan 21).

No query crosses a tenant. A tenant runs its own Command Centre builders inside its own schema and writes the result to
`public.group_figure_snapshots`; the parent reads those rows only while an active, reviewed relationship exists and only
for the people holding a named, unexpired `figure.view` grant. A subsidiary that has not published recently is **not
reporting** and never counts as zero.
"""
import hashlib
import json
import logging
import math
import re
import uuid
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


# The measures a child may publish are the Command Centre ones; which of them cross to a parent is decided per
# relationship, in its reviewed sharing terms (`figure_measures`). Nothing crosses that the terms do not list.
PUBLISHABLE = tuple(sorted(k for k in registry.REGISTRY if k.startswith("cc.")))


def publishable_measures() -> "list[dict]":
    """The measures a relationship's terms may approve, for the proposal form."""
    return [{"key": k, "label": registry.REGISTRY[k].label,
             "module": registry.REGISTRY[k].module or ""} for k in PUBLISHABLE]


def validate_measures(raw) -> "list[str]":
    if raw is None:
        return []
    if (not isinstance(raw, list) or len(raw) > len(PUBLISHABLE) or len(raw) != len(set(raw))
            or not all(isinstance(k, str) and k in PUBLISHABLE for k in raw)):
        raise HTTPException(422, "Choose group figures from the list")
    return sorted(raw)


def _approved(terms_json) -> "set[str]":
    try:
        terms = json.loads(terms_json or "{}")
    except ValueError:
        return set()
    listed = terms.get("figure_measures")
    return {k for k in listed if k in PUBLISHABLE} if isinstance(listed, list) else set()


def approved_for_child(db, org_id: int) -> "set[str] | None":
    """What the parents of this organization approved it to publish; None when it is nobody's child (no limit)."""
    rows = db.execute(
        f"SELECT terms_json FROM {_table('org_relationships')} WHERE child_org_id=%s AND status='active'",
        (org_id,)).fetchall()
    if not rows:
        return None
    allowed = set()
    for row in rows:
        allowed |= _approved(row["terms_json"])
    return allowed


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


def _build(org_id: int, slug: str):
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
    rows = {}
    for metric in list(built["metrics"].values()) + list(built["health"]):
        row = sanitize(metric)
        if row is None:
            continue
        # A module the organization is not licensed for contributes nothing, not a row of zeros.
        if licensed is not None and row["module"] and row["module"] not in licensed:
            continue
        rows[row["measure_key"]] = row
    return rows


def reconcile(row: dict, again: "dict | None") -> str:
    """'' when the figure reconciles, otherwise the reason it does not. A figure is only published as a number when
    two independent builds in the tenant agree and the number is possible for what it measures."""
    if again is None:
        return "the figure could not be read a second time"
    if row["state"] != again["state"] or row["value"] != again["value"]:
        return "the figure changed between two reads"
    value = row["value"]
    if row["state"] in ("measured", "partial", "stale"):
        if value is None or not math.isfinite(value):
            return "the figure has no valid number"
        if value < 0:
            return "a count or share cannot be negative"
        if _base(row["measure_key"]) == "cc.module_health" and value > 100:
            return "a share cannot exceed 100 percent"
    return ""


def collect_with_lineage(org_id: int, slug: str) -> "tuple[list[dict], list[dict]]":
    """(figures to publish, how each was made). A figure that does not reconcile is published as unavailable, never as
    the last value relabelled as current."""
    first, second = _build(org_id, slug), _build(org_id, slug)
    rows, lineage = [], []
    for key, row in first.items():
        reason = reconcile(row, second.get(key))
        definition = registry.REGISTRY[_base(key)]
        if reason:
            row = {**row, "state": "unavailable", "value": None, "detail": {}}
        rows.append(row)
        lineage.append({"measure_key": key, "state": row["state"], "value": row["value"],
                        "definition": definition.definition, "eligibility": definition.eligibility,
                        "denominator": definition.denominator, "window": definition.window,
                        "reconciliation": "failed" if reason else "ok", "reason": reason})
    return rows, lineage


def collect(org_id: int, slug: str) -> "list[dict]":
    """The publishable figures of one tenant, built inside that tenant for the whole organization."""
    return collect_with_lineage(org_id, slug)[0]


def publish_tenant(org_id: int, slug: str) -> int:
    """Freeze the tenant's current figures. Returns how many rows were written."""
    rows, lineage = collect_with_lineage(org_id, slug)
    by_key = {entry["measure_key"]: entry for entry in lineage}
    as_of = _now().isoformat()
    run_id = uuid.uuid4().hex
    db = get_db_bypass_rls()
    try:
        allowed = approved_for_child(db, org_id)
        if allowed is not None:
            rows = [r for r in rows if _base(r["measure_key"]) in allowed]
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
            entry = by_key[row["measure_key"]]
            snapshot_id = db.execute(
                f"SELECT MAX(id) AS i FROM {_table('group_figure_snapshots')} WHERE source_org_id=%s AND measure_key=%s",
                (org_id, row["measure_key"])).fetchone()["i"]
            db.execute(
                f"INSERT INTO {_table('group_figure_lineage')} (run_id,source_org_id,measure_key,state,value,"
                "definition_text,eligibility_text,denominator_text,window_text,reconciliation,reason,built_at,snapshot_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (run_id, org_id, row["measure_key"], row["state"], row["value"], entry["definition"],
                 entry["eligibility"], entry["denominator"], entry["window"], entry["reconciliation"],
                 entry["reason"], as_of, snapshot_id))
            written += 1
        db.commit()
        return written
    finally:
        db.close()


def interval_hours() -> int:
    """The publish cadence: the platform setting `group.figures.interval_hours`, daily by default, 1 to 168 hours."""
    db = get_db_bypass_rls()
    try:
        row = db.execute("SELECT value FROM settings WHERE key=%s", ("group.figures.interval_hours",)).fetchone()
    except Exception:
        row = None
    finally:
        db.close()
    try:
        return max(1, min(168, int(row["value"]))) if row else 24
    except (TypeError, ValueError):
        return 24


def _due(db, org_id: int, hours: int) -> bool:
    row = db.execute(f"SELECT MAX(as_of) AS a FROM {_table('group_figure_snapshots')} WHERE source_org_id=%s",
                     (org_id,)).fetchone()
    if not row or not row["a"]:
        return True
    try:
        return datetime.fromisoformat(row["a"]) <= _now() - timedelta(hours=hours)
    except ValueError:
        return True


def publish_all(*, only_due: bool = False) -> dict:
    """Publish every active tenant that is a party to an active relationship (as child or parent). With `only_due`,
    skip tenants that published within the configured interval, so an hourly schedule honours the setting."""
    from database import list_active_tenants
    hours = interval_hours()
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
        if only_due:
            check = get_db_bypass_rls()
            try:
                if not _due(check, org_id, hours):
                    continue
            finally:
                check.close()
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


def _children(db, actor: dict, capability: str = "figure.view") -> "list[dict]":
    """Subsidiaries whose figures this person may read: an active, reviewed, current relationship and a named,
    unexpired grant of `capability` (figure.view, or issue.view for the issue register) for exactly this person."""
    now = _now().isoformat()
    rows = db.execute(
        "SELECT DISTINCT r.id AS relationship_id, o.id AS org_id, o.name AS name, r.terms_json AS terms_json "
        f"FROM {_table('org_relationships')} r "
        "JOIN organizations o ON o.id=r.child_org_id AND o.status='active' "
        f"JOIN {_table('group_view_grants')} g ON g.relationship_id=r.id AND g.viewer_org_id=r.parent_org_id "
        "AND g.source_org_id=r.child_org_id AND g.user_id=%s AND g.capability=%s "
        "AND g.revoked_at IS NULL AND g.expires_at>%s AND g.review_due_at>%s "
        "WHERE r.parent_org_id=%s AND r.status='active' "
        "AND (r.child_ack_by IS NOT NULL OR r.notice_deemed_at IS NOT NULL) "
        "AND r.privacy_review_by IS NOT NULL AND r.legal_review_by IS NOT NULL AND r.review_due_at>%s "
        "ORDER BY o.name, o.id", (actor["id"], capability, now, now, actor["org_id"], now)).fetchall()
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
            "restated": bool(row.get("restates_snapshot_id")), "restatement_reason": row.get("restatement_reason"),
            "detail": detail, "additive": bool(definition and definition.denominator is None
                                                and not row["measure_key"].startswith("cc.module_health"))}


def _entity(db, org_id: int, name: str, families, approved=None) -> dict:
    latest = _latest(db, org_id, families)
    if approved is not None:  # defence in depth: terms may have been narrowed after publication
        latest = {k: v for k, v in latest.items() if _base(k) in approved}
    reporting, last = _reporting(latest)
    figures = [_figure(v) for v in latest.values()] if reporting else []
    return {"org_id": org_id, "name": name, "state": "reporting" if reporting else "not_reporting",
            "last_reported": last, "figures": figures}


# ── correcting a published figure ───────────────────────────────────────────

def _possible(key: str, value) -> None:
    if not _num(value) or not math.isfinite(value) or value < 0:
        raise HTTPException(422, "Enter a number that is possible for this figure")
    if _base(key) == "cc.module_health" and value > 100:
        raise HTTPException(422, "A share cannot exceed 100 percent")


def propose_restatement(db, actor: dict, measure_key: str, new_value, reason: str, period: str = "") -> int:
    """The source organization proposes a corrected value for its own latest published figure."""
    if not actor.get("org_id") or not has_capability(actor, "group.figure.restate"):
        raise HTTPException(403, "Figure correction access required")
    if not isinstance(measure_key, str) or _base(measure_key) not in registry.REGISTRY:
        raise HTTPException(422, "Choose a published figure")
    _possible(measure_key, new_value)
    if not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 500:
        raise HTTPException(422, "Record the reason for the correction")
    if not isinstance(period, str) or len(period) > 80:
        raise HTTPException(422, "Describe the period briefly")
    latest = db.execute(
        f"SELECT id, value FROM {_table('group_figure_snapshots')} WHERE source_org_id=%s AND measure_key=%s "
        "ORDER BY id DESC LIMIT 1", (actor["org_id"], measure_key)).fetchone()
    if not latest:
        raise HTTPException(404, "No published figure to correct")
    pending = db.execute(
        f"SELECT id FROM {_table('group_figure_restatements')} WHERE source_org_id=%s AND measure_key=%s AND status='proposed'",
        (actor["org_id"], measure_key)).fetchone()
    if pending:
        raise HTTPException(409, "A correction for this figure is already waiting for review")
    from database import insert_returning_id
    return insert_returning_id(
        db, f"INSERT INTO {_table('group_figure_restatements')} (source_org_id,measure_key,original_snapshot_id,"
        "old_value,new_value,period_text,reason,proposed_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (actor["org_id"], measure_key, latest["id"], latest["value"], float(new_value), period.strip(),
         reason.strip(), actor["id"]))


def list_restatements(db, actor: dict) -> "list[dict]":
    if not actor.get("org_id") or not (has_capability(actor, "group.figure.restate")
                                       or has_capability(actor, "group.figure.restate_review")):
        raise HTTPException(403, "Figure correction access required")
    rows = db.execute(
        f"SELECT id,measure_key,old_value,new_value,period_text,reason,status,proposed_by,reviewed_at,review_reason "
        f"FROM {_table('group_figure_restatements')} WHERE source_org_id=%s ORDER BY id DESC LIMIT 100",
        (actor["org_id"],)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        definition = registry.REGISTRY.get(_base(item["measure_key"]))
        item["label"] = definition.label if definition else item["measure_key"]
        item["can_review"] = (item["status"] == "proposed" and item.pop("proposed_by") != actor["id"]
                              and has_capability(actor, "group.figure.restate_review"))
        item.pop("proposed_by", None)
        out.append(item)
    return out


def review_restatement(db, actor: dict, restatement_id: int, decision: str, reason: str) -> dict:
    """A different person decides. Approval publishes a new snapshot that points at the original; nothing is edited."""
    if not actor.get("org_id") or not has_capability(actor, "group.figure.restate_review"):
        raise HTTPException(403, "Figure correction review required")
    if decision not in ("approved", "rejected") or not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 500:
        raise HTTPException(422, "Choose a decision and record the reason")
    row = db.execute(f"SELECT * FROM {_table('group_figure_restatements')} WHERE id=%s AND source_org_id=%s",
                     (restatement_id, actor["org_id"])).fetchone()
    if not row or row["status"] != "proposed":
        raise HTTPException(404, "Correction not found")
    if row["proposed_by"] == actor["id"]:
        raise HTTPException(409, "A different person must review this correction")
    now = _now().isoformat()
    replacement = None
    if decision == "approved":
        original = db.execute(f"SELECT * FROM {_table('group_figure_snapshots')} WHERE id=%s AND source_org_id=%s",
                              (row["original_snapshot_id"], actor["org_id"])).fetchone()
        newest = db.execute(
            f"SELECT MAX(publication_version) AS v FROM {_table('group_figure_snapshots')} "
            "WHERE source_org_id=%s AND measure_key=%s", (actor["org_id"], row["measure_key"])).fetchone()
        version = int(newest["v"] or 0) + 1
        corrected = {"measure_key": row["measure_key"], "state": "measured", "value": float(row["new_value"]),
                     "window": original["window_text"] or "", "detail": {}}
        db.execute(
            f"INSERT INTO {_table('group_figure_snapshots')} (source_org_id,measure_key,module,state,value,window_text,"
            "detail_json,method_version,as_of,publication_version,content_hash,restates_snapshot_id,restatement_reason) "
            "VALUES (%s,%s,%s,'measured',%s,%s,'{}',%s,%s,%s,%s,%s,%s)",
            (actor["org_id"], row["measure_key"], original["module"], corrected["value"], corrected["window"],
             original["method_version"], now, version, _hash(actor["org_id"], corrected, now, version),
             row["original_snapshot_id"], row["reason"]))
        replacement = db.execute(
            f"SELECT MAX(id) AS i FROM {_table('group_figure_snapshots')} WHERE source_org_id=%s AND measure_key=%s",
            (actor["org_id"], row["measure_key"])).fetchone()["i"]
    db.execute(
        f"UPDATE {_table('group_figure_restatements')} SET status=%s,reviewed_by=%s,review_reason=%s,reviewed_at=%s,"
        "replacement_snapshot_id=%s WHERE id=%s AND status='proposed'",
        (decision, actor["id"], reason.strip(), now, replacement, restatement_id))
    return {"id": restatement_id, "status": decision, "replacement_snapshot_id": replacement}


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
            "group": bool(children),
            "can_restate": has_capability(actor, "group.figure.restate"),
            "can_review_restatement": has_capability(actor, "group.figure.restate_review")}


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
        entity = _entity(db, child["org_id"], child["name"], families, _approved(child["terms_json"]))
        _log(db, actor, child["relationship_id"], child["org_id"], "figures_view")
        return {"view": "subsidiary", "entities": [entity], "totals": []}
    if which != "group":
        raise HTTPException(422, "Choose a view")
    if not children:
        raise HTTPException(404, "Company not found")
    entities = [_entity(db, org["id"], org["name"], families)]
    for child in children:
        entities.append(_entity(db, child["org_id"], child["name"], families, _approved(child["terms_json"])))
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
