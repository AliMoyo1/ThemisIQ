"""
The business continuity dashboard, read through the viewer's own scope (plans/2026-10-governance-rework/04 section 2).

It used to count every unit's plans, incidents, exercises and analyses for everyone, and the page showed made up figures when
the read failed. Every number here is a `core.metric_state` metric: measured, not measured (nothing to measure), or
unavailable (could not be read). The legacy field names are kept, now scoped, so the reports summary and the board
narrative see only what the person may open.
"""
from core import metric_registry as registry, metric_state as ms
from database import get_db
from modules.launcher.scoped_metrics import scoped_count, table_scope

RISK_BANDS = (("critical", 20), ("high", 12), ("medium", 6))


def _hidden(table, user) -> bool:
    return table_scope(table, user)[0] == "(1 = 0)"


def _guard(key, build):
    d = registry.get(key)
    return ms.guarded(key, d.label, build, definition=d.definition, drilldown=d.drilldown, window=d.window)


def _percent(done, total):
    return round(done / total * 100)


def metrics(db, user) -> dict:
    out = {}

    def put(m):
        if m is not None:
            out[m["key"]] = m

    if not _hidden("bcm_bia_records", user):
        def bia():
            total = scoped_count(db, user, "bcm_bia_records")
            if not total:
                return registry.build("bcm.bia_with_plan", ms.not_measured, "No business impact analysis is recorded yet.",
                                      detail={"unit": "percent", "covered": 0, "total": 0},
                                      action={"label": "Add an analysis", "href": "/bcm/bia"})
            scope, params = table_scope("bcm_bia_records", user, "b")
            covered = db.execute(
                "SELECT COUNT(*) FROM bcm_bia_records b WHERE "
                f"{scope} AND EXISTS (SELECT 1 FROM bcm_bia_plan_links l WHERE l.bia_id = b.id)", params).fetchone()[0]
            return registry.build("bcm.bia_with_plan", ms.measured, _percent(covered, total),
                                  detail={"unit": "percent", "covered": covered, "total": total})
        put(_guard("bcm.bia_with_plan", bia))

    if not _hidden("bcm_plans", user):
        def plans():
            total = scoped_count(db, user, "bcm_plans")
            approved = scoped_count(db, user, "bcm_plans", "status = 'approved'")
            review = scoped_count(db, user, "bcm_plans", "status IN ('review', 'in_review')")
            activated = scoped_count(db, user, "bcm_plans", "is_active_plan = 1")
            return registry.build("bcm.plans", ms.measured, total,
                                  detail={"approved": approved, "in_review": review, "activated": activated})
        put(_guard("bcm.plans", plans))

    if not _hidden("bcm_incidents", user):
        def incidents():
            return registry.build("bcm.active_incidents", ms.measured,
                                  scoped_count(db, user, "bcm_incidents", registry.INCIDENT_ACTIVE),
                                  detail={"all": scoped_count(db, user, "bcm_incidents")})
        put(_guard("bcm.active_incidents", incidents))

    if not _hidden("bcm_exercises", user):
        def exercises():
            total = scoped_count(db, user, "bcm_exercises")
            if not total:
                return registry.build("bcm.exercises_completed", ms.not_measured, "No exercise is recorded yet.",
                                      detail={"unit": "percent", "completed": 0, "total": 0},
                                      action={"label": "Plan an exercise", "href": "/bcm/exercises"})
            done = scoped_count(db, user, "bcm_exercises",
                                registry.EXERCISE_COMPLETED)
            return registry.build("bcm.exercises_completed", ms.measured, _percent(done, total),
                                  detail={"unit": "percent", "completed": done, "total": total})
        put(_guard("bcm.exercises_completed", exercises))

    if not _hidden("bcm_risks", user):
        put(_guard("bcm.open_risks", lambda: registry.build(
            "bcm.open_risks", ms.measured, scoped_count(db, user, "bcm_risks", "status = 'open'"))))

        def levels():
            scope, params = table_scope("bcm_risks", user)
            counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
            for r in db.execute(f"SELECT score FROM bcm_risks WHERE {scope} AND status != 'closed'", params).fetchall():
                score = int(r["score"] or 0)
                for name, floor in RISK_BANDS:
                    if score >= floor:
                        counts[name] += 1
                        break
                else:
                    counts["low"] += 1
            return registry.build("bcm.risk_levels", ms.measured, sum(counts.values()), detail=counts)
        put(_guard("bcm.risk_levels", levels))
    return out


def _lists(db, user) -> dict:
    out = {"plan_status": None, "active_incidents": None, "recent_activity": None}

    def rows(sql, params):
        return [dict(r) for r in db.execute(sql, params).fetchall()]

    if not _hidden("bcm_plans", user):
        scope, params = table_scope("bcm_plans", user)
        out["plan_status"] = rows(
            "SELECT id, title, owner, status, is_active_plan FROM bcm_plans "
            f"WHERE {scope} ORDER BY is_active_plan DESC, updated_at DESC LIMIT 6", params)
    if not _hidden("bcm_incidents", user):
        scope, params = table_scope("bcm_incidents", user)
        found = rows(
            "SELECT id, title, severity, status, commander, created_at, affected_systems FROM bcm_incidents "
            f"WHERE {scope} AND status NOT IN ('resolved', 'closed') ORDER BY created_at DESC LIMIT 5", params)
        for row in found:
            row["assigned"], row["impact"], row["declared_at"] = row.get("commander") or "", row.get("affected_systems") or "", row.get("created_at")
        out["active_incidents"] = found
    recent = []
    for table, label, title_col, when in (("bcm_incidents", "Incident declared", "title", "created_at"),
                                          ("bcm_exercises", "Exercise", "title", "updated_at"),
                                          ("bcm_plans", "Plan", "title", "updated_at")):
        if _hidden(table, user):
            continue
        scope, params = table_scope(table, user)
        status = "" if table == "bcm_incidents" else "COALESCE(status, 'updated')"
        select = (f"SELECT {title_col} AS title, {when} AS created_at" + (f", {status} AS status" if status else "") +
                  f" FROM {table} WHERE {scope} ORDER BY {when} DESC LIMIT 3")
        for r in rows(select, params):
            action = label if table == "bcm_incidents" else f"{label} {r.get('status')}"
            recent.append({"text": f"{action}: {r['title']}", "created_at": r["created_at"]})
    recent.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    out["recent_activity"] = recent[:5]
    return out


def stats(user) -> dict:
    """The dashboard payload for one viewer: legacy field names (scoped) and the metrics the cards read."""
    db = get_db()
    try:
        m = metrics(db, user)
        lists = {}
        try:
            lists = _lists(db, user)
        except Exception:
            ms.log.warning("BCM dashboard lists could not be read", exc_info=True)
            lists = {"plan_status": None, "active_incidents": None, "recent_activity": None}

        def value(key, default=None):
            got = m.get(key)
            return got["value"] if got and got["value"] is not None else default

        def detail(key):
            return (m.get(key) or {}).get("detail") or {}
        bia = detail("bcm.bia_with_plan")
        ex = detail("bcm.exercises_completed")
        plans = detail("bcm.plans")
        out = {
            "metrics": m,
            "plan_count": value("bcm.plans"), "active_plans": plans.get("activated"),
            "open_incidents": value("bcm.active_incidents"), "incident_count": detail("bcm.active_incidents").get("all"),
            "exercise_count": ex.get("total"), "bia_count": bia.get("total"), "open_risks": value("bcm.open_risks"),
            "risk_distribution": detail("bcm.risk_levels") or None,
            "bia_coverage_pct": value("bcm.bia_with_plan"), "exercise_pct": value("bcm.exercises_completed"),
            "plans": value("bcm.plans"), "bia_records": bia.get("total"), "exercises": ex.get("total"),
            "coverage": {"total_bia": bia.get("total"), "covered": bia.get("covered"),
                         "pct": value("bcm.bia_with_plan")},
            **lists,
        }
        return out
    finally:
        db.close()


def for_narrative(stats: dict) -> dict:
    """What a model is given to write the board narrative: the scoped figures and their states, never a title."""
    return {
        "plans": stats.get("plans"), "open_incidents": stats.get("open_incidents"),
        "exercise_pct": stats.get("exercise_pct"), "bia_coverage_pct": stats.get("bia_coverage_pct"),
        "metrics": {key: {"label": m["label"], "state": m["state"], "value": m["value"], "detail": m["detail"]}
                    for key, m in (stats.get("metrics") or {}).items()},
    }
