"""
The numbers on the Command Centre cards, each with the state it is in (plans/2026-10-governance-rework/04 section 2).

Every number is read through the viewer's own scope. A source that cannot be read becomes `unavailable`, never a zero; a
number with nothing to measure is `not_measured`, never a good looking 100 per cent; a number that adds several sources and
lost one is `partial` and names what is missing. A module the viewer may not open contributes no metric at all, so neither
its count nor its existence is sent.
"""
from core import metric_registry as registry, metric_state as ms
from database import sql_current_date, sql_date_offset, sql_date_ts
from modules.launcher.scoped_metrics import scoped_count, table_scope

MODULE_HEALTH = (
    # (module, name, table, the good state of its main records)
    ("aria", "Governance", "controls", registry.CONTROL_IMPLEMENTED),
    ("grid", "Audit", "grid_audits", "status IN ('Completed','Complete')"),
    ("bcm", "Resilience", "bcm_plans", "status = 'approved'"),
    ("sentinel", "Privacy", "sentinel_breaches", "status = 'closed'"),
    ("erm", "Enterprise Risk", "erm_enterprise_risks", "status = 'closed'"),
    ("orm", "Operations Risk", "orm_events", "status IN ('resolved','closed')"),
)


def _hidden(table, user) -> bool:
    return table_scope(table, user)[0] == "(1 = 0)"


def _kept(key):
    d = registry.get(key.split(":", 1)[0])
    return {"definition": d.definition, "drilldown": d.drilldown, "window": d.window}


def _guard(key, build):
    return ms.guarded(key, registry.get(key.split(":", 1)[0]).label, build, **_kept(key))


def _count(db, user, key, table, condition="", *, detail=None):
    """A count of rows of one table the viewer may open; None when the viewer may open none of that kind."""
    if _hidden(table, user):
        return None
    return _guard(key, lambda: registry.build(key, ms.measured, scoped_count(db, user, table, condition), detail=detail))


def _sum(key, parts):
    """One number from several sources: measured when all were read, partial when some were, unavailable when none."""
    got, missing = {}, []
    for name, read in parts:
        try:
            got[name] = read()
        except Exception:
            ms.log.warning("Metric %s: source %s could not be read", key, name, exc_info=True)
            missing.append(name)
    if not got and not missing:
        return None
    if not got:
        return registry.build(key, ms.unavailable, sources={"available": [], "missing": missing})
    total = sum(got.values())
    if missing:
        return registry.build(key, ms.partial, total, sources_ok=sorted(got), sources_missing=missing, detail=got)
    return registry.build(key, ms.measured, total, detail=got)


def _percent(done, total):
    return round(done / total * 100) if total else None


def _controls(db, user):
    if _hidden("controls", user):
        return None

    def build():
        total = scoped_count(db, user, "controls")
        if not total:
            return registry.build("cc.controls_implemented", ms.not_measured,
                                  "No controls are recorded yet. Add a framework to start.",
                                  action={"label": "Open Governance", "href": "/aria/frameworks"})
        done = scoped_count(db, user, "controls", registry.CONTROL_IMPLEMENTED)
        approved = scoped_count(db, user, "controls", "status = 'Approved'")
        return registry.build("cc.controls_implemented", ms.measured, _percent(done, total),
                              detail={"unit": "percent", "implemented": done, "total": total,
                                      "approved_not_implemented": approved})
    return _guard("cc.controls_implemented", build)


def _frameworks(db, user):
    if _hidden("frameworks", user):
        return None

    def build():
        count = scoped_count(db, user, "frameworks", "is_active = 1")
        scope, params = table_scope("frameworks", user)
        names = [r["name"] for r in db.execute(
            f"SELECT name FROM frameworks WHERE is_active = 1 AND {scope} ORDER BY name LIMIT 5", params).fetchall()]
        return registry.build("cc.active_frameworks", ms.measured, count, detail={"names": names})
    return _guard("cc.active_frameworks", build)


def _overdue(db, user):
    parts = []
    if not _hidden("task_board", user):
        parts.append(("tasks", lambda: scoped_count(
            db, user, "task_board", "status != 'done' AND due_date IS NOT NULL "
            f"AND due_date < {sql_current_date()}")))
    if not _hidden("sla_instances", user):
        parts.append(("service clocks", lambda: scoped_count(db, user, "sla_instances", "breached = 1 AND status = 'active'")))
    return _sum("cc.overdue_actions", parts) if parts else None


def _open_breaches(db, user):
    if _hidden("sentinel_breaches", user):
        return None

    def build():
        condition = registry.BREACH_ACTIVE
        critical = scoped_count(db, user, "sentinel_breaches", condition + " AND severity = 'critical'")
        high = scoped_count(db, user, "sentinel_breaches", condition + " AND severity = 'high'")
        return registry.build("cc.open_breaches", ms.measured, critical + high,
                              detail={"critical": critical, "high": high,
                                      "worst": "critical" if critical else "high" if high else None})
    return _guard("cc.open_breaches", build)


def _appetite(db, user):
    if _hidden("erm_enterprise_risks", user):
        return None
    scope, params = table_scope("erm_enterprise_risks", user, "e")

    def build():
        categories = db.execute("SELECT COUNT(*) FROM erm_risk_appetite").fetchone()[0]
        if not categories:
            return registry.build("cc.appetite_breaches", ms.not_measured,
                                  "No limit is set for any risk category, so no category can be over its limit.",
                                  action={"label": "Set risk appetite", "href": "/erm/appetite"})
        over = db.execute(
            "SELECT COUNT(*) FROM erm_risk_appetite a "
            "WHERE (SELECT MAX(e.likelihood*e.impact) FROM erm_enterprise_risks e "
            f"       WHERE e.category=a.category AND e.status != 'closed' AND {scope}) > a.max_score",
            params).fetchone()[0]
        return registry.build("cc.appetite_breaches", ms.measured, over, detail={"categories": categories})
    return _guard("cc.appetite_breaches", build)


def _reviews(db, user):
    parts = []
    if not _hidden("erm_enterprise_risks", user):
        parts.append(("risks", lambda: scoped_count(
            db, user, "erm_enterprise_risks", "review_date IS NOT NULL "
            f"AND review_date <= {sql_date_offset('+30 days')} AND status != 'closed'")))
    if not _hidden("bcm_plans", user):
        parts.append(("plans", lambda: scoped_count(
            db, user, "bcm_plans", f"last_reviewed IS NOT NULL AND last_reviewed <= {sql_date_offset('-335 days')}")))
    return _sum("cc.upcoming_reviews", parts) if parts else None


def _evidence(db, user):
    if _hidden("evidence_items", user):
        return None, None
    files = _guard("cc.evidence_files", lambda: registry.build(
        "cc.evidence_files", ms.measured,
        scoped_count(db, user, "evidence_items", "status NOT IN ('archived', 'superseded')")))
    expiring = _guard("cc.evidence_expiring", lambda: registry.build(
        "cc.evidence_expiring", ms.measured,
        scoped_count(db, user, "evidence_items", "status = 'current' AND expiry_date IS NOT NULL "
                     f"AND expiry_date <= {sql_date_offset('+30 days')} AND expiry_date >= {sql_current_date()}")))
    return files, expiring


def _sla(db, user):
    if _hidden("sla_instances", user):
        return None

    def build():
        met = scoped_count(db, user, "sla_instances", "status IN ('completed','resolved') AND breached = 0")
        breached = scoped_count(db, user, "sla_instances", "breached = 1")
        at_risk = scoped_count(db, user, "sla_instances", "status = 'active' AND breached = 0")
        detail = {"unit": "percent", "met": met, "breached": breached, "at_risk": at_risk}
        if met + breached == 0:
            return registry.build("cc.sla_on_time", ms.not_measured, "No service clock has ended yet.", detail=detail)
        return registry.build("cc.sla_on_time", ms.measured, _percent(met, met + breached), detail=detail)
    return _guard("cc.sla_on_time", build)


def _risk_levels(db, user):
    parts = []

    def levels_of(rows):
        out = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for r in rows:
            score = (r["likelihood"] or 0) * (r["impact"] or 0)
            out["critical" if score >= 20 else "high" if score >= 12 else "medium" if score >= 6 else "low"] += 1
        return out

    if not _hidden("erm_enterprise_risks", user):
        scope, params = table_scope("erm_enterprise_risks", user)

        def enterprise():
            return levels_of(db.execute(
                f"SELECT likelihood, impact FROM erm_enterprise_risks WHERE {scope} AND status != 'closed'", params).fetchall())
        parts.append(("enterprise risks", enterprise))
    if not _hidden("risk_register", user):
        pscope, pparams = table_scope("risk_register", user)

        def platform():
            out = {"critical": 0, "high": 0, "medium": 0, "low": 0}
            for r in db.execute(
                    f"SELECT risk_level, COUNT(*) AS c FROM risk_register WHERE {pscope} AND status != 'closed' "
                    "GROUP BY risk_level", pparams).fetchall():
                if r["risk_level"] in out:
                    out[r["risk_level"]] += r["c"]
            return out
        parts.append(("platform risks", platform))
    if not parts:
        return None
    got, missing = {}, []
    for name, read in parts:
        try:
            got[name] = read()
        except Exception:
            ms.log.warning("Metric cc.open_risks: source %s could not be read", name, exc_info=True)
            missing.append(name)
    if not got:
        return registry.build("cc.open_risks", ms.unavailable, sources={"available": [], "missing": missing})
    levels = {k: sum(v[k] for v in got.values()) for k in ("critical", "high", "medium", "low")}
    total = sum(levels.values())
    if missing:
        return registry.build("cc.open_risks", ms.partial, total, sources_ok=sorted(got), sources_missing=missing,
                              detail=levels)
    return registry.build("cc.open_risks", ms.measured, total, detail=levels)


def _health(db, user) -> list:
    out = []
    for module, name, table, good in MODULE_HEALTH:
        if _hidden(table, user):
            continue
        key = f"cc.module_health:{module}"
        base = {"module": module, "name": name, "unit": "percent"}

        def build(key=key, table=table, good=good, name=name, base=base):
            total = scoped_count(db, user, table)
            if not total:
                got = registry.build("cc.module_health", ms.not_measured, f"Nothing is recorded in {name} yet.", detail=base)
            else:
                got = registry.build("cc.module_health", ms.measured, _percent(scoped_count(db, user, table, good), total),
                                     detail={**base, "of": total})
            got["key"] = key
            return got
        got = _guard(key, build)
        got["detail"] = got.get("detail") or base  # an unavailable one still says which module it is
        out.append(got)
    return out


def build(db, user) -> dict:
    """{"metrics": {key: metric}, "health": [metric, ...]} for the cards of the Command Centre, in the viewer's scope."""
    metrics = {}

    def put(m):
        if m is not None:
            metrics[m["key"]] = m

    put(_controls(db, user))
    put(_frameworks(db, user))
    put(_overdue(db, user))
    put(_count(db, user, "cc.critical_high_risks", "erm_enterprise_risks",
               "qualitative_score IN ('critical','high') AND status != 'closed'"))
    put(_open_breaches(db, user))
    put(_appetite(db, user))
    put(_count(db, user, "cc.orm_open_events", "orm_events",
               f"status IN ('open','investigating') AND created_at >= {sql_date_ts('-30 days')}"))
    put(_count(db, user, "cc.bcm_active_incidents", "bcm_incidents", registry.INCIDENT_ACTIVE))
    put(_count(db, user, "cc.grid_open_audit_controls", "grid_controls",
               "status NOT IN ('compliant','not_applicable','closed')"))
    put(_reviews(db, user))
    files, expiring = _evidence(db, user)
    put(files)
    put(expiring)
    put(_sla(db, user))
    put(_count(db, user, "cc.workflows_active", "workflow_instances", "status = 'active'"))
    put(_risk_levels(db, user))
    return {"metrics": metrics, "health": _health(db, user)}
