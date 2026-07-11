"""
Launcher sub-router: Dashboard — Launcher home (/), My Dashboard.
"""
import json as json_lib
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse

from database import insert_returning_id, sql_now_offset, sql_now_ts, sql_date_offset, sql_date_ts, sql_current_date, sql_current_timestamp
from modules.launcher._route_helpers import (
    _JSONResp, require_auth, has_capability, user_modules, user_capabilities,
    ROLE_LABELS, shell_ctx, templates, shell_templates, get_db,
    _json_body,)

router = APIRouter()


# ── Health check (no auth required — used by load balancers / orchestrators) ──

@router.get("/health")
async def health_check():
    """Liveness + readiness probe. Returns DB connectivity status."""
    db = get_db()
    try:
        db.execute("SELECT 1").fetchone()
        db_ok = True
    except Exception:
        db_ok = False
    finally:
        db.close()
    status = "ok" if db_ok else "degraded"
    return JSONResponse(
        {"status": status, "db": db_ok, "version": "1.0"},
        status_code=200 if db_ok else 503,
    )


# ── Module info for launcher tiles ──────────────────────────────────────────

MODULE_INFO = {
    "aria": {
        "name": "Governance",
        "subtitle": "Policy & Compliance",
        "description": "Policy management, controls tracking, and cross-framework compliance across ISO 27001, SOC 2, GDPR, PCI DSS, HIPAA, Zimbabwe CDPA, and ISO 42001.",
        "icon": "shield-check",
        "color": "#7E8062",
        "gradient": "linear-gradient(135deg, #7E8062 0%, #5C5F3D 100%)",
    },
    "grid": {
        "name": "Audit",
        "subtitle": "Audit Management",
        "description": "Compliance audit lifecycle management with AI-powered checklist parsing, gap analysis, evidence repository, and executive reporting.",
        "icon": "clipboard-check",
        "color": "#1a6b3a",
        "gradient": "linear-gradient(135deg, #1a6b3a 0%, #0f4424 100%)",
    },
    "bcm": {
        "name": "Resilience",
        "subtitle": "Business Continuity",
        "description": "Business impact analysis, risk register, continuity plans, incident management, tabletop exercises, and ISO 22301 compliance.",
        "icon": "activity",
        "color": "#8a8a5b",
        "gradient": "linear-gradient(135deg, #0f1116 0%, #1b1e26 100%)",
    },
    "sentinel": {
        "name": "Privacy",
        "subtitle": "Data Protection",
        "description": "RoPA, DPIA, breach management, data subject requests, consent management, vendor assessments, and privacy notice tracking.",
        "icon": "lock",
        "color": "#00d4ff",
        "gradient": "linear-gradient(135deg, #050914 0%, #0d1a2e 100%)",
    },
    "erm": {
        "name": "Enterprise Risk",
        "subtitle": "Enterprise Risk Management",
        "description": "Strategic risk register, appetite framework, regulatory obligations, pre-built risk library, self-assessments, and AI-powered board reporting.",
        "icon": "shield-alert",
        "color": "#dc3c50",
        "gradient": "linear-gradient(135deg, #3a0a0e 0%, #6b1220 100%)",
    },
    "orm": {
        "name": "Operations Risk",
        "subtitle": "Operational Risk",
        "description": "Operational event logging, financial loss tracking, key risk indicators, root cause analysis, and real-time KRI threshold monitoring.",
        "icon": "alert-triangle",
        "color": "#e67828",
        "gradient": "linear-gradient(135deg, #2a1200 0%, #6b3010 100%)",
    },
}


@router.get("/", response_class=HTMLResponse)
@require_auth
async def launcher(request: Request):
    user = request.state.user
    mods = user_modules(user)
    available = []
    for mod_key in mods:
        info = MODULE_INFO.get(mod_key, {})
        available.append({"key": mod_key, **info})

    return shell_templates.TemplateResponse(request, "command_centre.html", {
        **shell_ctx(request, active_module="platform", active_section="overview"),
        "modules": available,
        "role_labels": ROLE_LABELS,
    })


# ── Role-Specific Dashboard ──────────────────────────────────────────────────

@router.get("/my-dashboard", response_class=HTMLResponse)
@require_auth
async def my_dashboard(request: Request):
    """Role-specific dashboard with contextual widgets."""
    ctx = shell_ctx(request, active_module="platform", active_section="my-dashboard")
    ctx["user_caps"] = list(user_capabilities(request.state.user))
    return shell_templates.TemplateResponse(request, "my_dashboard.html", ctx)


# ── Command Centre Stats API ────────────────────────────────────────────────

@router.get("/api/command-centre/stats")
@require_auth
async def api_command_centre_stats(request: Request):
    """Real-time stats for the Command Centre dashboard."""
    db = get_db()
    try:
        # ── Overall compliance (ARIA controls) ──
        total_controls = db.execute("SELECT COUNT(*) FROM aria_controls").fetchone()[0]
        compliant_controls = db.execute(
            "SELECT COUNT(*) FROM aria_controls WHERE status = 'compliant'"
        ).fetchone()[0]
        compliance_pct = round((compliant_controls / total_controls) * 100) if total_controls else 0

        # ── Active projects (active frameworks) ──
        active_fws = db.execute(
            "SELECT name FROM frameworks WHERE is_active = 1 ORDER BY name"
        ).fetchall()
        active_projects = len(active_fws)
        projects_list = " · ".join(r["name"] for r in active_fws[:5])
        if len(active_fws) > 5:
            projects_list += f" (+{len(active_fws) - 5} more)"

        # ── Overdue counts (SLA + task board) — computed after both queries below ──

        # ── Evidence collected ──
        evidence_count = db.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0]
        evidence_expiring = db.execute(
            "SELECT COUNT(*) FROM evidence_items "
            "WHERE status = 'current' AND expiry_date IS NOT NULL "
            f"  AND expiry_date <= {sql_date_offset('+30 days')} AND expiry_date >= {sql_current_date()}"
        ).fetchone()[0]

        # ── Module health (compliance % per module) ──
        module_health = []
        # ARIA
        aria_total = total_controls
        aria_ok = compliant_controls
        aria_pct = round((aria_ok / aria_total) * 100) if aria_total else 0
        module_health.append({"key": "aria", "name": "Governance", "pct": aria_pct})

        # GRID — audit completion
        grid_total = db.execute("SELECT COUNT(*) FROM grid_audits").fetchone()[0]
        grid_done = db.execute(
            "SELECT COUNT(*) FROM grid_audits WHERE status IN ('Completed','Complete')"
        ).fetchone()[0]
        grid_pct = round((grid_done / grid_total) * 100) if grid_total else 0
        module_health.append({"key": "grid", "name": "Audit", "pct": grid_pct})

        # BCM — plan coverage
        bcm_total = db.execute("SELECT COUNT(*) FROM bcm_plans").fetchone()[0]
        bcm_approved = db.execute(
            "SELECT COUNT(*) FROM bcm_plans WHERE status = 'approved'"
        ).fetchone()[0]
        bcm_pct = round((bcm_approved / bcm_total) * 100) if bcm_total else 0
        module_health.append({"key": "bcm", "name": "Resilience", "pct": bcm_pct})

        # Sentinel — open breach rate (inverted: 0 open = 100%, no breaches = 100%)
        sent_total = db.execute("SELECT COUNT(*) FROM sentinel_breaches").fetchone()[0]
        sent_open = db.execute(
            "SELECT COUNT(*) FROM sentinel_breaches WHERE status != 'closed'"
        ).fetchone()[0]
        sent_pct = round((1 - sent_open / max(1, sent_total)) * 100) if sent_total else 100
        module_health.append({"key": "sentinel", "name": "Privacy", "pct": sent_pct})

        # ERM — % of appetite categories within threshold (no breach)
        try:
            erm_cats = db.execute(
                "SELECT COUNT(*) FROM erm_risk_appetite"
            ).fetchone()[0]
            if erm_cats:
                erm_breach = db.execute(
                    "SELECT COUNT(*) FROM erm_risk_appetite a "
                    "WHERE (SELECT MAX(e.likelihood*e.impact) FROM erm_enterprise_risks e "
                    "       WHERE e.category=a.category AND e.status NOT IN ('closed','accepted')) > a.max_score"
                ).fetchone()[0]
                erm_pct = round((1 - erm_breach / max(1, erm_cats)) * 100)
            else:
                # No appetite defined yet — use risk mitigation rate instead
                erm_total_r = db.execute(
                    "SELECT COUNT(*) FROM erm_enterprise_risks WHERE status != 'closed'"
                ).fetchone()[0]
                erm_treated = db.execute(
                    "SELECT COUNT(*) FROM erm_enterprise_risks "
                    "WHERE status IN ('mitigated','accepted') OR treatment != 'mitigate'"
                ).fetchone()[0]
                erm_pct = round((erm_treated / max(1, erm_total_r)) * 100) if erm_total_r else 100
            # Only include if user has erm access (always include in stats, visibility filtered by template)
            module_health.append({"key": "erm", "name": "Enterprise Risk", "pct": erm_pct})
        except Exception:
            pass  # ERM tables may not exist in all deployments

        # ORM — % of events resolved
        try:
            orm_total = db.execute("SELECT COUNT(*) FROM orm_events").fetchone()[0]
            orm_closed = db.execute(
                "SELECT COUNT(*) FROM orm_events WHERE status IN ('resolved','closed')"
            ).fetchone()[0]
            orm_pct = round((orm_closed / max(1, orm_total)) * 100) if orm_total else 100
            module_health.append({"key": "orm", "name": "Operations Risk", "pct": orm_pct})
        except Exception:
            pass  # ORM tables may not exist in all deployments

        # ── SLA performance ──
        sla_met = db.execute(
            "SELECT COUNT(*) FROM sla_instances WHERE status IN ('completed','resolved') AND breached = 0"
        ).fetchone()[0]
        sla_breached = db.execute(
            "SELECT COUNT(*) FROM sla_instances WHERE breached = 1"
        ).fetchone()[0]
        sla_at_risk = db.execute(
            "SELECT COUNT(*) FROM sla_instances WHERE status = 'active' AND breached = 0"
        ).fetchone()[0]
        sla_total_resolved = sla_met + sla_breached
        sla_pct = round((sla_met / sla_total_resolved) * 100) if sla_total_resolved else 100

        # ── Recent activity (from audit log) ──
        # Org isolation: non-super-admins only see their own org's activity.
        is_super = user.get("is_super_admin")
        caller_org_id = user.get("org_id")
        org_filter = "" if is_super or caller_org_id is None else " WHERE al.org_id = %s"
        org_arg = () if is_super or caller_org_id is None else (caller_org_id,)
        activity_rows = db.execute(
            f"SELECT al.action AS text, al.module, al.created_at "
            f"FROM audit_log al{org_filter} ORDER BY al.created_at DESC LIMIT 6",
            org_arg,
        ).fetchall()
        activity = [dict(r) for r in activity_rows]

        # ── Overdue action items: SLA instances (Bug 2 fixed: entity_module, resolution_due) ──
        overdue_rows = db.execute(
            "SELECT si.id, si.entity_type AS item, si.entity_module AS module, "
            "       si.resolution_due AS due, "
            "       CASE WHEN si.breached = 1 THEN 'breached' ELSE 'at_risk' END AS sla, "
            "       'high' AS priority "
            "FROM sla_instances si "
            "WHERE si.status = 'active' "
            f"  AND (si.breached = 1 OR si.resolution_due < {sql_current_timestamp()}) "
            "ORDER BY si.resolution_due ASC LIMIT 20"
        ).fetchall()
        overdue_items = []
        for r in overdue_rows:
            overdue_items.append({
                "id": f"SLA-{r['id']}",
                "item": r["item"] or "SLA Action",
                "module": r["module"] or "",
                "assigned": "",
                "due": r["due"] or "",
                "sla": r["sla"],
                "priority": r["priority"],
            })

        # Improvement F: also pull overdue task_board items
        task_rows = db.execute(
            "SELECT t.id, t.title AS item, t.module, "
            "       t.due_date AS due, t.priority, u.full_name AS assigned_name "
            "FROM task_board t LEFT JOIN users u ON t.assigned_to = u.id "
            "WHERE t.status != 'done' AND t.due_date IS NOT NULL "
            f"  AND t.due_date < {sql_current_date()} "
            "ORDER BY t.due_date ASC LIMIT 20"
        ).fetchall()
        for r in task_rows:
            overdue_items.append({
                "id": f"TASK-{r['id']}",
                "item": r["item"] or "Task",
                "module": r["module"] or "platform",
                "assigned": r["assigned_name"] or "",
                "due": r["due"] or "",
                "sla": "breached",
                "priority": r["priority"] or "medium",
            })
        # ERM overdue obligations
        try:
            erm_obl_rows = db.execute(
                "SELECT id, regulation_name, due_date FROM erm_regulatory_obligations "
                f"WHERE status NOT IN ('compliant') AND due_date < {sql_current_date()} "
                "ORDER BY due_date ASC LIMIT 10"
            ).fetchall()
            for r in erm_obl_rows:
                overdue_items.append({
                    "id": f"ERM-OBL-{r['id']}",
                    "item": r["regulation_name"] or "Regulatory Obligation",
                    "module": "erm",
                    "assigned": "",
                    "due": r["due_date"] or "",
                    "sla": "breached",
                    "priority": "high",
                })
        except Exception:
            pass

        # ORM overdue events (open/investigating past resolved date)
        try:
            orm_evt_rows = db.execute(
                "SELECT id, title FROM orm_events "
                f"WHERE status IN ('open','investigating') AND detected_at < {sql_now_offset('-7 days')} "
                "ORDER BY detected_at ASC LIMIT 5"
            ).fetchall()
            for r in orm_evt_rows:
                overdue_items.append({
                    "id": f"ORM-{r['id']}",
                    "item": r["title"] or "Operational Event",
                    "module": "orm",
                    "assigned": "",
                    "due": "",
                    "sla": "at_risk",
                    "priority": "medium",
                })
        except Exception:
            pass

        overdue_items.sort(key=lambda x: x["due"] or "9999")
        overdue_items = overdue_items[:20]

        # Compute combined overdue count now that both sources are queried
        sla_overdue_count = db.execute(
            "SELECT COUNT(*) FROM sla_instances WHERE breached = 1 AND status = 'active'"
        ).fetchone()[0]
        task_overdue_count = db.execute(
            "SELECT COUNT(*) FROM task_board "
            f"WHERE status != 'done' AND due_date IS NOT NULL AND due_date < {sql_current_date()}"
        ).fetchone()[0]
        overdue_count = sla_overdue_count + task_overdue_count

        # ── Trend metrics (compare today vs yesterday via analytics_snapshots) ──
        today_date     = db.execute("SELECT CURRENT_DATE").fetchone()[0]
        yesterday_date = db.execute(f"SELECT {sql_date_offset('-1 day')}").fetchone()[0]

        def _prev_snap(metric: str, default: int) -> int:
            row = db.execute(
                "SELECT metric_value FROM analytics_snapshots "
                "WHERE snapshot_date=%s AND metric_name=%s AND module='platform'",
                (yesterday_date, metric),
            ).fetchone()
            return int(row[0]) if row else default

        prev_compliance = _prev_snap("compliance_pct", compliance_pct)
        prev_overdue    = _prev_snap("overdue_count",  overdue_count)
        prev_evidence   = _prev_snap("evidence_count", evidence_count)

        def _pct_trend(cur: int, prev: int) -> str:
            d = cur - prev
            if d > 0:  return f"▲ +{d}% vs yesterday"
            if d < 0:  return f"▼ {d}% vs yesterday"
            return "stable vs yesterday"

        def _count_trend(cur: int, prev: int, unit: str = "") -> str:
            d = cur - prev
            if d > 0:  return f"▲ +{d}{unit} since yesterday"
            if d < 0:  return f"▼ {abs(d)}{unit} since yesterday"
            return "unchanged since yesterday"

        compliance_trend = _pct_trend(compliance_pct, prev_compliance)
        overdue_trend    = _count_trend(overdue_count,  prev_overdue)
        evidence_trend   = _count_trend(evidence_count, prev_evidence, " items")

        # Persist today's snapshot (ON CONFLICT DO NOTHING — write once per day)
        try:
            for metric, val in (
                ("compliance_pct", compliance_pct),
                ("overdue_count",  overdue_count),
                ("evidence_count", evidence_count),
            ):
                db.execute(
                    "INSERT INTO analytics_snapshots "
                    "(snapshot_date, metric_name, metric_value, module) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (today_date, metric, val, "platform"),
                )
            db.commit()
        except Exception:
            pass  # snapshot write failure must not break the response

        # ── Open risk counts (for risk register widget) ──
        risk_rows = db.execute(
            "SELECT risk_level, COUNT(*) AS c FROM risk_register "
            "WHERE status != 'closed' GROUP BY risk_level"
        ).fetchall()
        risk_counts = {r["risk_level"]: r["c"] for r in risk_rows}

        # ── Active workflows ──
        workflow_active = db.execute(
            "SELECT COUNT(*) FROM workflow_instances WHERE status = 'active'"
        ).fetchone()[0]

        # ── Module-specific headline stats (4 new stat cards) ──
        # Sentinel: open high/critical breaches
        sentinel_open_breaches = 0
        sentinel_breach_severity = None
        try:
            s_row = db.execute(
                "SELECT COUNT(*) AS c, "
                "MAX(CASE severity WHEN 'critical' THEN 2 WHEN 'high' THEN 1 ELSE 0 END) AS sev "
                "FROM sentinel_breaches "
                "WHERE status NOT IN ('closed','resolved') AND severity IN ('high','critical')"
            ).fetchone()
            sentinel_open_breaches = s_row["c"] if s_row else 0
            sentinel_breach_severity = ("critical" if (s_row and s_row["sev"] == 2)
                                        else "high" if (s_row and s_row["sev"] == 1)
                                        else None)
        except Exception:
            pass

        # Sentinel: breach notification countdown alerts
        breach_alerts = []
        try:
            from modules.sentinel.jurisdictions import JURISDICTION_RULES
            alert_rows = db.execute(
                "SELECT id, ref_number, title, severity, status, regulation, "
                "notify_deadline, discovery_date, authority_notified "
                "FROM sentinel_breaches "
                "WHERE status NOT IN ('closed','resolved') "
                "AND notify_deadline IS NOT NULL "
                "ORDER BY notify_deadline ASC"
            ).fetchall()
            for r in alert_rows:
                jur = JURISDICTION_RULES.get(r["regulation"] or "GDPR", {})
                breach_alerts.append({
                    "id": r["id"],
                    "ref": r["ref_number"],
                    "title": r["title"],
                    "severity": r["severity"],
                    "regulation": r["regulation"] or "GDPR",
                    "authority": jur.get("authority_short", "DPA"),
                    "breach_hours": jur.get("breach_hours", 72),
                    "deadline": r["notify_deadline"],
                    "authority_notified": bool(r["authority_notified"]),
                })
        except Exception:
            pass

        # ERM: appetite breach count
        erm_appetite_breaches = 0
        try:
            erm_appetite_breaches = db.execute(
                "SELECT COUNT(*) FROM erm_risk_appetite a "
                "WHERE (SELECT MAX(e.likelihood*e.impact) FROM erm_enterprise_risks e "
                "       WHERE e.category=a.category AND e.status NOT IN ('closed','accepted')) > a.max_score"
            ).fetchone()[0]
        except Exception:
            pass

        # ORM: open events (last 30 days)
        orm_open_events = 0
        try:
            orm_open_events = db.execute(
                "SELECT COUNT(*) FROM orm_events "
                "WHERE status IN ('open','investigating') "
                f"AND created_at >= {sql_date_ts('-30 days')}"
            ).fetchone()[0]
        except Exception:
            pass

        # BCM: active incidents
        bcm_active_incidents = 0
        try:
            bcm_active_incidents = db.execute(
                "SELECT COUNT(*) FROM bcm_incidents "
                "WHERE status NOT IN ('closed','resolved')"
            ).fetchone()[0]
        except Exception:
            pass

        # ── IMS stats (from aria_control_mappings) ────────────────────────
        ims_integrated_controls = 0
        ims_unique_controls     = 0
        ims_effort_saved_pct    = 0
        ims_active_fws          = 0
        try:
            total_ctrls = db.execute("SELECT COUNT(*) FROM controls").fetchone()[0]
            integrated_ctrls = db.execute("""
                SELECT COUNT(DISTINCT c.id) FROM controls c
                WHERE EXISTS (
                    SELECT 1 FROM aria_control_mappings m
                    WHERE (m.source_control_id=c.id OR m.target_control_id=c.id)
                    AND m.mapping_type IN ('equivalent','related','ims_equivalent')
                )
            """).fetchone()[0]
            unique_ctrls = total_ctrls - integrated_ctrls
            ims_integrated_controls = integrated_ctrls
            ims_unique_controls     = unique_ctrls
            ims_effort_saved_pct    = round((integrated_ctrls / total_ctrls * 50)) if total_ctrls else 0
            ims_active_fws          = db.execute(
                "SELECT COUNT(*) FROM frameworks WHERE is_active=1"
            ).fetchone()[0]
        except Exception:
            pass

        # ERM: critical/high open risks
        erm_critical_high = 0
        try:
            erm_critical_high = db.execute(
                "SELECT COUNT(*) FROM erm_enterprise_risks "
                "WHERE qualitative_score IN ('critical','high') "
                "AND status NOT IN ('closed','accepted')"
            ).fetchone()[0]
        except Exception:
            pass

        # GRID: open audit findings
        grid_open_findings = 0
        try:
            grid_open_findings = db.execute(
                "SELECT COUNT(*) FROM grid_controls "
                "WHERE status NOT IN ('compliant','not_applicable','closed')"
            ).fetchone()[0]
        except Exception:
            pass

        # Upcoming reviews (risks or plans due in next 30 days)
        upcoming_reviews = 0
        try:
            upcoming_reviews += db.execute(
                "SELECT COUNT(*) FROM erm_enterprise_risks "
                f"WHERE review_date IS NOT NULL AND review_date <= {sql_date_ts('+30 days')} "
                "AND status NOT IN ('closed','accepted')"
            ).fetchone()[0]
        except Exception:
            pass
        try:
            upcoming_reviews += db.execute(
                "SELECT COUNT(*) FROM bcm_plans "
                f"WHERE last_reviewed IS NOT NULL AND last_reviewed <= {sql_date_ts('-335 days')}"
            ).fetchone()[0]
        except Exception:
            pass

    finally:
        db.close()

    return _JSONResp({
        "compliance_pct":    compliance_pct,
        "compliance_trend":  compliance_trend,
        "active_projects":   active_projects,
        "projects_list":     projects_list,
        "overdue_count":     overdue_count,
        "overdue_trend":     overdue_trend,
        "evidence_count":    evidence_count,
        "evidence_trend":    evidence_trend,
        "evidence_target":   max(evidence_count, 1),
        "evidence_expiring": evidence_expiring,
        "module_health":     module_health,
        "sla":               {"pct": sla_pct, "met": sla_met, "at_risk": sla_at_risk, "breached": sla_breached},
        "activity":          activity,
        "overdue_items":     overdue_items,
        "risk_counts":       risk_counts,
        "workflow_active":   workflow_active,
        # Module headline stats
        "sentinel_open_breaches":   sentinel_open_breaches,
        "sentinel_breach_severity": sentinel_breach_severity,
        "breach_alerts":            breach_alerts,
        "erm_appetite_breaches":    erm_appetite_breaches,
        "orm_open_events":          orm_open_events,
        "bcm_active_incidents":     bcm_active_incidents,
        # Row 3 action-oriented stats
        "erm_critical_high":   erm_critical_high,
        "grid_open_findings":  grid_open_findings,
        "upcoming_reviews":    upcoming_reviews,
        "ims_active_frameworks": ims_active_fws,
        "fetched_at":        datetime.now(timezone.utc).isoformat(),
    })


@router.get("/api/my-dashboard/data")
@require_auth
async def api_my_dashboard_data(request: Request):
    """Get role-specific dashboard data."""
    user = request.state.user
    uid = user["id"]
    role = user.get("role", "employee")
    db = get_db()
    data = {"role": role, "role_label": ROLE_LABELS.get(role, role)}

    try:
        # Pending workflow actions for this user
        data["pending_actions"] = db.execute(
            "SELECT COUNT(*) FROM workflow_actions WHERE assigned_to = %s AND status = 'pending'", (uid,)
        ).fetchone()[0]

        # Active SLA breaches
        data["sla_breaches"] = db.execute(
            "SELECT COUNT(*) FROM sla_instances WHERE breached = 1 AND status = 'active'"
        ).fetchone()[0]

        # Unread notifications
        data["unread_notifications"] = db.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = %s AND is_read = 0", (uid,)
        ).fetchone()[0]

        # Open risks by level
        risk_rows = db.execute(
            "SELECT risk_level, COUNT(*) as c FROM risk_register WHERE status != 'closed' GROUP BY risk_level"
        ).fetchall()
        data["risks"] = {r["risk_level"]: r["c"] for r in risk_rows}

        # Role-specific data
        if role in ("super_admin", "compliance_mgr"):
            # Overview of all modules
            data["aria_controls_total"] = db.execute("SELECT COUNT(*) FROM aria_controls").fetchone()[0]
            data["aria_controls_compliant"] = db.execute(
                "SELECT COUNT(*) FROM aria_controls WHERE status = 'compliant'"
            ).fetchone()[0]
            data["grid_audits_active"] = db.execute(
                "SELECT COUNT(*) FROM grid_audits WHERE status IN ('Planning','Active')"
            ).fetchone()[0]
            data["bcm_plans_total"] = db.execute("SELECT COUNT(*) FROM bcm_plans").fetchone()[0]
            data["sentinel_breaches_open"] = db.execute(
                "SELECT COUNT(*) FROM sentinel_breaches WHERE status != 'closed'"
            ).fetchone()[0]
            data["sentinel_dsrs_open"] = db.execute(
                "SELECT COUNT(*) FROM sentinel_dsr WHERE status NOT IN ('completed','closed')"
            ).fetchone()[0]
            data["recent_audit_entries"] = [dict(r) for r in db.execute(
                f"SELECT al.*, u.full_name FROM audit_log al LEFT JOIN users u ON al.user_id = u.id "
                f"{org_filter} ORDER BY al.created_at DESC LIMIT 10",
                org_arg
            ).fetchall()]

        elif role in ("audit_lead", "auditor"):
            data["my_audits"] = [dict(r) for r in db.execute(
                "SELECT id, name, status, start_date FROM grid_audits ORDER BY created_at DESC LIMIT 10"
            ).fetchall()]
            data["open_ncs"] = db.execute(
                "SELECT COUNT(*) FROM grid_non_conformances WHERE status = 'open'"
            ).fetchone()[0]

        elif role in ("dpo", "privacy_analyst"):
            data["ropa_count"] = db.execute("SELECT COUNT(*) FROM sentinel_ropa").fetchone()[0]
            data["dpia_pending"] = db.execute(
                "SELECT COUNT(*) FROM sentinel_dpias WHERE status IN ('draft','in_progress')"
            ).fetchone()[0]
            data["dsr_open"] = db.execute(
                "SELECT COUNT(*) FROM sentinel_dsr WHERE status NOT IN ('completed','closed')"
            ).fetchone()[0]
            data["breaches_open"] = db.execute(
                "SELECT COUNT(*) FROM sentinel_breaches WHERE status != 'closed'"
            ).fetchone()[0]

        elif role in ("bcm_manager", "incident_commander", "bcm_responder"):
            data["bcm_plans"] = db.execute("SELECT COUNT(*) FROM bcm_plans").fetchone()[0]
            data["bcm_incidents_active"] = db.execute(
                "SELECT COUNT(*) FROM bcm_incidents WHERE status IN ('open','responding')"
            ).fetchone()[0]
            data["bcm_exercises_upcoming"] = db.execute(
                "SELECT COUNT(*) FROM bcm_exercises WHERE status = 'planned'"
            ).fetchone()[0]

        elif role in ("policy_author", "policy_approver", "control_owner", "risk_owner"):
            data["my_docs"] = [dict(r) for r in db.execute(
                "SELECT id, doc_id, title, status FROM aria_documents ORDER BY updated_at DESC LIMIT 10"
            ).fetchall()]
            data["controls_needing_review"] = db.execute(
                "SELECT COUNT(*) FROM aria_controls WHERE status IN ('not_implemented','partially_implemented')"
            ).fetchone()[0]

    finally:
        db.close()

    return _JSONResp(data)


# ── Dashboard Preferences API ─────────────────────────────────────────────

_ALLOWED_PREF_KEYS = frozenset({
    "hidden_widgets",   # JSON list of widget IDs to hide
    "widget_order",     # JSON list of widget IDs in display order
    "theme_accent",     # accent colour override (future)
})

_MAX_PREF_VALUE_LEN = 2048


@router.get("/api/my-dashboard/preferences")
@require_auth
async def api_my_dashboard_preferences_get(request: Request):
    """Return all dashboard preferences for the current user."""
    uid = request.state.user["id"]
    db = get_db()
    try:
        rows = db.execute(
            "SELECT pref_key, pref_value FROM user_preferences WHERE user_id = %s",
            (uid,),
        ).fetchall()
    finally:
        db.close()
    prefs = {}
    for r in rows:
        key = r["pref_key"]
        if key not in _ALLOWED_PREF_KEYS:
            continue
        raw = r["pref_value"] or ""
        # Attempt JSON parse for structured values
        try:
            prefs[key] = json_lib.loads(raw)
        except (json_lib.JSONDecodeError, ValueError):
            prefs[key] = raw
    return _JSONResp(prefs)


@router.put("/api/my-dashboard/preferences")
@require_auth
async def api_my_dashboard_preferences_put(request: Request):
    """Upsert dashboard preferences for the current user.

    Body: ``{ "key": "<pref_key>", "value": <any JSON-serialisable> }``
    """
    uid = request.state.user["id"]
    try:
        body = await _json_body(request)
    except Exception:
        return _JSONResp({"ok": False, "error": "Invalid JSON body"}, status_code=400)

    key = str(body.get("key", "")).strip()
    if key not in _ALLOWED_PREF_KEYS:
        return _JSONResp({"ok": False, "error": f"Unknown preference key: {key}"}, status_code=400)

    value = body.get("value")
    serialised = json_lib.dumps(value) if not isinstance(value, str) else value
    if len(serialised) > _MAX_PREF_VALUE_LEN:
        return _JSONResp({"ok": False, "error": "Value too large"}, status_code=400)

    db = get_db()
    try:
        db.execute(
            "INSERT INTO user_preferences (user_id, pref_key, pref_value, updated_at) "
            "VALUES (%s, %s, %s, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id, pref_key) DO UPDATE SET pref_value = excluded.pref_value, "
            "updated_at = excluded.updated_at",
            (uid, key, serialised),
        )
        db.commit()
    finally:
        db.close()
    return _JSONResp({"ok": True})


# ── Predictive AI Risk Analytics ─────────────────────────────────────────────

@router.get("/api/predictive-risk")
@require_auth
async def api_predictive_risk(request: Request, background_tasks: BackgroundTasks):
    """
    Returns the latest risk prediction, computing a fresh one if the cache is stale.

    The response includes:
      - delta_p          : global ΔP_risk (0–100)
      - delta_cyber/operational/compliance : domain sub-scores
      - risk_level       : low | medium | high | critical
      - confidence       : 0–1 data completeness indicator
      - signal_contributions : per-signal % of total score
      - advisory_text    : Claude advisory (present only if delta_p > 15)
      - telemetry        : raw metric snapshot
      - history          : last 7 predictions for sparkline
      - cached           : true if returned from cache
    """
    from core.predictive_risk import (
        collect_telemetry, compute_delta_p,
        build_advisory_prompt, ADVISORY_SYSTEM_PROMPT,
        ADVISORY_THRESHOLD, ESCALATION_THRESHOLD, CACHE_TTL_MINUTES,
    )

    force = request.query_params.get("force") == "1"
    db = get_db()
    try:
        # ── Return cached prediction if fresh ──
        if not force:
            cached = db.execute(
                "SELECT * FROM ai_risk_predictions WHERE is_active = 1 "
                f"AND computed_at > {sql_now_ts(f'-{CACHE_TTL_MINUTES} minutes')} ORDER BY id DESC LIMIT 1",
            ).fetchone()
            if cached:
                history = _prediction_history(db)
                return _JSONResp({**dict(cached), "cached": True, "history": history,
                                  "telemetry": json_lib.loads(cached["telemetry_json"] or "{}"),
                                  "signal_contributions": json_lib.loads(cached["contributions_json"] or "{}")})

        # ── Compute fresh prediction ──
        metrics = collect_telemetry(db)
        result  = compute_delta_p(metrics)

        # ── Generate Claude advisory if above threshold ──
        advisory = None
        if result["delta_p"] >= ADVISORY_THRESHOLD:
            try:
                from modules.sentinel.ai_service import call_ai
                advisory, _ = await call_ai(
                    ADVISORY_SYSTEM_PROMPT,
                    build_advisory_prompt(metrics, result),
                    max_tokens=600,
                )
            except Exception as exc:
                import logging
                logging.getLogger("oneforall.predictive_risk").warning(
                    "Advisory generation failed: %s", exc
                )

        # ── Store prediction ──
        prediction_id = insert_returning_id(db,
            "INSERT INTO ai_risk_predictions "
            "(delta_p, delta_cyber, delta_operational, delta_compliance, "
            " confidence, risk_level, telemetry_json, contributions_json, advisory_text) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                result["delta_p"], result["delta_cyber"],
                result["delta_operational"], result["delta_compliance"],
                result["confidence"], result["risk_level"],
                json_lib.dumps(metrics),
                json_lib.dumps(result.get("signal_contributions", {})),
                advisory,
            ),
        )

        # ── Notify admins on first high/critical prediction in this period ──
        if result["risk_level"] in ("high", "critical"):
            from core.event_handlers import _notify_admins
            level_emoji = "🔴" if result["risk_level"] == "critical" else "🟠"
            _notify_admins(
                db, "platform",
                f"{level_emoji} Predictive Risk Alert: ΔP +{result['delta_p']}%",
                f"The AI risk engine has flagged a {result['risk_level'].upper()} risk probability increase. "
                f"Cyber: {result['delta_cyber']}% | Ops: {result['delta_operational']}% | "
                f"Compliance: {result['delta_compliance']}%",
                "/",
            )

        db.commit()

        # ── Auto-escalate to ERM in background if critical ──
        if result["risk_level"] == "critical" and result["delta_p"] >= ESCALATION_THRESHOLD:
            background_tasks.add_task(
                _auto_escalate_to_erm, prediction_id, result, metrics, advisory
            )

        history = _prediction_history(db)
        return _JSONResp({
            **result,
            "advisory_text": advisory,
            "telemetry": metrics,
            "cached": False,
            "history": history,
            "prediction_id": prediction_id,
        })

    finally:
        db.close()


@router.post("/api/predictive-risk/acknowledge")
@require_auth
async def api_predictive_risk_acknowledge(request: Request):
    """Mark the latest active prediction as acknowledged by the current user."""
    uid = request.state.user["id"]
    db = get_db()
    try:
        db.execute(
            "UPDATE ai_risk_predictions SET acknowledged_by = %s, acknowledged_at = CURRENT_TIMESTAMP "
            "WHERE id = (SELECT id FROM ai_risk_predictions WHERE is_active = 1 ORDER BY id DESC LIMIT 1)",
            (uid,),
        )
        db.commit()
        return _JSONResp({"ok": True})
    finally:
        db.close()


# ── Predictive risk helpers ───────────────────────────────────────────────────

def _prediction_history(db, limit: int = 7) -> list:
    """Return last N predictions for the sparkline."""
    rows = db.execute(
        "SELECT computed_at, delta_p, risk_level FROM ai_risk_predictions "
        "WHERE is_active = 1 ORDER BY id DESC LIMIT %s", (limit,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def _auto_escalate_to_erm(prediction_id: int, result: dict, metrics: dict, advisory: str | None):
    """
    Background task: create an ERM enterprise risk for a critical prediction.
    Runs outside the request lifecycle.
    """
    try:
        from modules.erm.data_service import create_enterprise_risk
        from database import get_db_background
        db = get_db_background()  # background task — fail fast, never block UI writes
        try:
            # Check not already escalated
            existing = db.execute(
                "SELECT erm_risk_id FROM ai_risk_predictions WHERE id = %s", (prediction_id,)
            ).fetchone()
            if existing and existing["erm_risk_id"]:
                return

            risk_data = {
                "title": f"AI Predictive Alert — Platform Risk ΔP +{result['delta_p']}%",
                "description": (
                    f"Auto-escalated from Predictive AI Risk Analytics.\n\n"
                    f"Global ΔP_risk: +{result['delta_p']}%\n"
                    f"Cyber: {result['delta_cyber']}%  |  Operational: {result['delta_operational']}%  |  Compliance: {result['delta_compliance']}%\n\n"
                    + (advisory or "No advisory generated.")
                ),
                "category": "operational",
                "likelihood": 4,
                "impact": 4,
                "treatment": "mitigate",
                "status": "open",
                "board_visibility": 1,
                "source_module": "platform",
                "created_by": None,
            }
            erm_risk_id = create_enterprise_risk(risk_data)
            db.execute(
                "UPDATE ai_risk_predictions SET erm_risk_id = %s WHERE id = %s",
                (erm_risk_id, prediction_id),
            )
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        import logging
        logging.getLogger("oneforall.predictive_risk").error(
            "ERM auto-escalation failed: %s", exc
        )
