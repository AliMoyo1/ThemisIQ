"""
The privacy dashboard, read on the server through the viewer's own scope (plans/2026-10-governance-rework/04 section 2).

The page used to fetch four lists and count them in the browser, falling back to a made up set of records when any read
failed or was refused, and it computed RoPA coverage against a constant. Here every number is a `core.metric_state` metric.
The coverage denominator is a real list: the active business processes recorded in Governance that the viewer may open. A
process counts as covered when a processing record the viewer may also open is connected to it by a confirmed link.
"""
from core import metric_registry as registry, metric_state as ms
from database import get_db
from modules.launcher.scoped_metrics import scoped_count, table_scope


def _hidden(table, user) -> bool:
    return table_scope(table, user)[0] == "(1 = 0)"


def _guard(key, build):
    d = registry.get(key)
    return ms.guarded(key, d.label, build, definition=d.definition, drilldown=d.drilldown, window=d.window)


def _covered_clause(user):
    """SQL and params: process alias `p` has a processing record the viewer may open, through a confirmed link."""
    rscope, rparams = table_scope("sentinel_ropa", user, "r")
    one = ("EXISTS (SELECT 1 FROM cross_module_links l JOIN sentinel_ropa r ON r.id = {rid} "
           "WHERE COALESCE(l.status, 'confirmed') = 'confirmed' "
           "AND l.{a}_module = 'governance' AND l.{a}_type = 'process' AND l.{a}_id = p.id "
           "AND l.{b}_module = 'sentinel' AND l.{b}_type = 'ropa' AND " + rscope + ")")
    outgoing = one.format(rid="l.target_id", a="source", b="target")
    incoming = one.format(rid="l.source_id", a="target", b="source")
    return f"({outgoing} OR {incoming})", [*rparams, *rparams]


def coverage_gaps(db, user, limit=200) -> "list | None":
    """Active business processes the viewer may open with no processing record connected, or None when the viewer may open
    no business processes or no processing records (there is then nothing to list)."""
    if _hidden("business_processes", user) or _hidden("sentinel_ropa", user):
        return None
    pscope, pparams = table_scope("business_processes", user, "p")
    covered, cparams = _covered_clause(user)
    rows = db.execute(
        "SELECT p.id, p.name, p.business_unit_id FROM business_processes p "
        f"WHERE p.is_active = 1 AND {pscope} AND NOT {covered} ORDER BY p.name LIMIT %s",
        [*pparams, *cparams, limit]).fetchall()
    return [{"id": r["id"], "name": r["name"], "url": "/governance/#bp"} for r in rows]


def metrics(db, user) -> dict:
    out = {}

    def put(m):
        if m is not None:
            out[m["key"]] = m

    if not _hidden("sentinel_ropa", user):
        put(_guard("sentinel.ropa_records", lambda: registry.build(
            "sentinel.ropa_records", ms.measured, scoped_count(db, user, "sentinel_ropa"))))

        if not _hidden("business_processes", user):
            def coverage():
                pscope, pparams = table_scope("business_processes", user, "p")
                total = db.execute(
                    f"SELECT COUNT(*) FROM business_processes p WHERE p.is_active = 1 AND {pscope}", pparams).fetchone()[0]
                if not total:
                    return registry.build(
                        "sentinel.ropa_coverage", ms.not_measured,
                        "No business process is recorded in Governance, so there is nothing to measure coverage against.",
                        detail={"unit": "percent", "covered": 0, "total": 0},
                        action={"label": "Record business processes", "href": "/governance/"})
                covered, cparams = _covered_clause(user)
                done = db.execute(
                    f"SELECT COUNT(*) FROM business_processes p WHERE p.is_active = 1 AND {pscope} AND {covered}",
                    [*pparams, *cparams]).fetchone()[0]
                return registry.build("sentinel.ropa_coverage", ms.measured, round(done / total * 100),
                                      detail={"unit": "percent", "covered": done, "total": total})
            put(_guard("sentinel.ropa_coverage", coverage))

    if not _hidden("sentinel_dpias", user):
        def dpias():
            active = scoped_count(db, user, "sentinel_dpias", "status NOT IN ('completed', 'closed')")
            total = scoped_count(db, user, "sentinel_dpias")
            level = {lvl: scoped_count(db, user, "sentinel_dpias", "risk_level = %s", (lvl,)) for lvl in ("high", "medium", "low")}
            return registry.build("sentinel.dpia_active", ms.measured, active, detail={"total": total, **level})
        put(_guard("sentinel.dpia_active", dpias))

    if not _hidden("sentinel_dsr", user):
        def dsrs():
            opened = scoped_count(db, user, "sentinel_dsr", "status IN ('open', 'new')")
            progress = scoped_count(db, user, "sentinel_dsr", "status = 'in_progress'")
            done = scoped_count(db, user, "sentinel_dsr", "status IN ('completed', 'closed')")
            total = scoped_count(db, user, "sentinel_dsr")
            return registry.build("sentinel.dsr_open", ms.measured, opened + progress,
                                  detail={"open": opened, "in_progress": progress, "completed": done, "total": total})
        put(_guard("sentinel.dsr_open", dsrs))

    if not _hidden("sentinel_breaches", user):
        put(_guard("sentinel.breaches_active", lambda: registry.build(
            "sentinel.breaches_active", ms.measured,
            scoped_count(db, user, "sentinel_breaches", registry.BREACH_ACTIVE))))
    return out


def _dsr_items(db, user, limit=10):
    if _hidden("sentinel_dsr", user):
        return None
    scope, params = table_scope("sentinel_dsr", user)
    rows = db.execute(
        "SELECT id, ref_number, request_type, status, received_date, deadline_date, created_at FROM sentinel_dsr "
        f"WHERE {scope} ORDER BY created_at DESC, id DESC LIMIT %s", [*params, limit]).fetchall()
    return [{"id": r["ref_number"] or f"DSR-{r['id']}", "type": r["request_type"] or "", "status": r["status"] or "open",
             "submitted": r["received_date"] or r["created_at"] or "", "due": r["deadline_date"] or ""} for r in rows]


def _activity(user, limit=5):
    from modules.sentinel import data_service as ds
    org_id = None if (user.get("is_super_admin") or user.get("org_id") is None) else user.get("org_id")
    rows = ds.list_audit(limit=limit, org_id=org_id)
    return [{"text": a.get("action") or a.get("description") or a.get("title") or "",
             "created_at": a.get("created_at") or a.get("timestamp") or ""} for a in rows]


def stats(user) -> dict:
    """{"metrics": ..., "dsr_items": [...] | None, "activity": [...] | None} for one viewer."""
    db = get_db()
    try:
        got = {"metrics": metrics(db, user)}
        try:
            got["dsr_items"] = _dsr_items(db, user)
        except Exception:
            ms.log.warning("Sentinel dashboard: request list could not be read", exc_info=True)
            got["dsr_items"] = None
            got["dsr_items_unavailable"] = True
    finally:
        db.close()
    try:
        got["activity"] = _activity(user)
    except Exception:
        ms.log.warning("Sentinel dashboard: activity could not be read", exc_info=True)
        got["activity"] = None
        got["activity_unavailable"] = True
    return got
