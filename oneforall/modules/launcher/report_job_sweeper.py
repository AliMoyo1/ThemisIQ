"""Persisted, bounded register generation outside the request worker.

Each tenant owns its report_runs queue. An atomic pending -> running update
claims a job once across Uvicorn processes. A stopped worker leaves a visible
failed job after the deadline; it never publishes a partial register.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.timeutils import utcnow
from database import get_db_background, list_active_tenants, tenant_context

log = logging.getLogger("oneforall.report_jobs")
_scheduler: BackgroundScheduler | None = None
_REGISTER_TYPES = ("framework_auditor_register", "ai_systems_register", "ai_risk_register")


def _now() -> str:
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _claim() -> int | None:
    db = get_db_background()
    try:
        cutoff = (utcnow() - timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute(
            "UPDATE report_runs SET status='failed',progress_stage='timed_out',"
            "completed_at=%s,error='The export worker timed out. Generate the register again.' "
            "WHERE status='running' AND started_at<%s", (_now(), cutoff))
        rows = db.execute(
            "SELECT rr.id FROM report_runs rr JOIN report_definitions rd ON rd.id=rr.definition_id "
            "WHERE rr.status='pending' AND rd.report_type IN (%s,%s,%s) ORDER BY rr.id LIMIT 4",
            _REGISTER_TYPES).fetchall()
        for row in rows:
            cursor = db.execute(
                "UPDATE report_runs SET status='running',progress_stage='reading',started_at=%s "
                "WHERE id=%s AND status='pending'", (_now(), row["id"]))
            if cursor.rowcount == 1:
                db.commit()
                return row["id"]
        db.commit()
        return None
    finally:
        db.close()


def _fail(run_id: int, message: str, db=None) -> None:
    own_connection = db is None
    if own_connection:
        db = get_db_background()
    try:
        db.execute(
            "UPDATE report_runs SET status='failed',progress_stage='failed',completed_at=%s,error=%s "
            "WHERE id=%s AND status='running'", (_now(), message[:200], run_id))
        db.commit()
    finally:
        if own_connection:
            db.close()


def _generate(run_id: int, org_id: int, slug: str) -> None:
    from modules.launcher import report_builders as builders, report_snapshot as snap
    from modules.launcher import routes_reports as reports
    from modules.launcher.scoped_metrics import run_scope_key

    db = get_db_background()
    try:
        pending = db.execute(
            "SELECT rr.id,rr.definition_id,rr.triggered_by,rr.previous_run_id,"
            "rd.report_type,rd.created_by,rd.is_active FROM report_runs rr "
            "JOIN report_definitions rd ON rd.id=rr.definition_id WHERE rr.id=%s AND rr.status='running'",
            (run_id,)).fetchone()
        if not pending or not pending["is_active"] or pending["report_type"] not in _REGISTER_TYPES:
            _fail(run_id, "This report definition is no longer available.", db)
            return
        user_id = snap.actor_id(pending["triggered_by"])
        user = reports._recipient(db, user_id) if user_id else None
        if (not user or user.get("org_id") != org_id or
                run_scope_key(user) != pending["triggered_by"] or
                (not user.get("is_super_admin") and pending["created_by"] != user_id)):
            _fail(run_id, "Your access changed before the register could be generated.", db)
            return
    finally:
        db.close()
    # The effective user's current scope is still checked by each source
    # builder. The tenant context also binds RLS to this one organization.
    with tenant_context(org_id, slug, is_super_admin=bool(user.get("is_super_admin"))):
        db = get_db_background()
        try:
            row = db.execute(
                "SELECT rr.previous_run_id,rr.triggered_by,rd.* FROM report_runs rr "
                "JOIN report_definitions rd ON rd.id=rr.definition_id "
                "WHERE rr.id=%s AND rr.status='running'", (run_id,)).fetchone()
            if not row or row["triggered_by"] != run_scope_key(user):
                _fail(run_id, "Your access changed before the register could be generated.", db)
                return
            defn = dict(row)
            previous = None
            if row["previous_run_id"]:
                old = db.execute(
                    "SELECT result_json,snapshot_hash FROM report_runs WHERE id=%s AND status='completed' "
                    "AND triggered_by=%s", (row["previous_run_id"], run_scope_key(user))).fetchone()
                if old and snap.intact(old["result_json"], old["snapshot_hash"]):
                    previous = row["previous_run_id"], reports.json_lib.loads(old["result_json"])
            else:
                previous = reports._previous_for(db, user, row["id"])
            env = reports._envelope(db, user, row["id"], row["name"], row["report_type"],
                                    reports._parameters(defn), previous)
            current_user = reports._recipient(db, user["id"])
            if (not current_user or run_scope_key(current_user) != row["triggered_by"] or
                    not reports._shareable(db, env, current_user, owner=True)):
                db.rollback()
                _fail(run_id, "A source or your access changed during generation. No result was saved.", db)
                return
            db.execute("UPDATE report_runs SET progress_stage='sources_read' "
                       "WHERE id=%s AND status='running'", (run_id,))
            db.commit()
            text, digest = snap.encode(env)
            generated = reports.date.fromisoformat(env["run"]["generated_at"][:10])
            delete_after = (generated + reports.timedelta(days=reports._retention_days(db))).isoformat()
            cursor = db.execute(
                "UPDATE report_runs SET status='completed',progress_stage='complete',completed_at=%s,"
                "result_json=%s,snapshot_hash=%s,previous_run_id=%s,error=NULL "
                "WHERE id=%s AND status='running'",
                (env["run"]["generated_at"], text, digest, previous[0] if previous else None, run_id))
            if cursor.rowcount != 1:
                db.rollback()
                return
            db.execute("INSERT INTO report_run_retention (run_id,delete_after,set_by) VALUES (%s,%s,%s)",
                       (run_id, delete_after, user["id"]))
            db.execute(
                "INSERT INTO audit_log (user_id,username,module,action,entity_type,entity_id,details,ip_address,org_id) "
                "VALUES (%s,%s,'platform','report_run','report_run',%s,%s,'',%s)",
                (user["id"], user["username"], run_id,
                 f"{row['report_type']} v{env['run']['definition_version']} sha256={digest[:16]}", org_id))
            db.commit()
        except builders.RecordNotAvailable:
            db.rollback()
            _fail(run_id, "A selected source is no longer available in your scope.", db)
        except Exception as exc:
            db.rollback()
            log.error("Register job %s failed: %s", run_id, type(exc).__name__)
            _fail(run_id, "The register could not be generated. No partial result was saved.", db)
        finally:
            db.close()


def run_once(max_jobs: int = 2) -> int:
    completed = 0
    try:
        tenants = list_active_tenants()
    except Exception as exc:
        log.warning("Register queue could not list tenants: %s", type(exc).__name__)
        return 0
    for org_id, slug in tenants:
        if completed >= max_jobs:
            break
        try:
            with tenant_context(org_id, slug, is_super_admin=False):
                run_id = _claim()
                if run_id is not None:
                    _generate(run_id, org_id, slug)
                    completed += 1
        except Exception as exc:
            log.error("Register queue failed in org %s: %s", org_id, type(exc).__name__)
    return completed


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(run_once, IntervalTrigger(seconds=15), id="report_register_queue",
                       replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=10)
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
