"""
GRID module — Background scheduler.

Runs periodic compliance tasks on cron schedules (Africa/Harare = CAT = UTC+2).
Ported from the original AuditSphere scheduler.js.

IMPORTANT: Jobs only run on schedule, never on startup.
Mail is asked for through the email outbox (core/email_outbox.py), never sent from a job.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import urllib.parse
import zipfile
from datetime import date, timedelta
from core.timeutils import utcnow
from pathlib import Path

from config import settings

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import get_db_background as get_db, sql_date_offset, sql_current_date  # scheduler: fail-fast, never block UI
from core import email_outbox as outbox
from core import email_templates as templates
from core.best_effort import swallowed

log = logging.getLogger("grid.scheduler")
TZ = "Africa/Harare"

_scheduler: BackgroundScheduler | None = None


# ═════════════════════════════════════════════════════════════════════════
# Mail jobs (1 to 4, 7, 8 and 9)
#
# A job decides who should be told and asks the outbox (core/email_outbox.py) for one message per person, action and
# threshold. The outbox sends it and, at that moment, checks that the person is still active, may open the record and
# that the work is still open. Nothing here records "notified" because a mail was attempted: the outbox row holds what
# the provider said, and a second run asks for the same message and gets the one that exists.
# Every job visits each organization in turn: a scheduler has no request to take a tenant from.
# ═════════════════════════════════════════════════════════════════════════

def _week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def _in_each_organization(name: str, job) -> None:
    """Run job(db, org_id, today) once per organization on one short connection and commit what it asked for."""
    def run(org_id):
        db = get_db()
        try:
            asked = job(db, org_id, utcnow().date())
            db.commit()
            log.info("%s: %d message(s) asked for in organization %s", name, asked, org_id)
        except Exception as exc:
            db.rollback()
            log.error("%s error in organization %s: %s", name, org_id, exc)
        finally:
            db.close()
    outbox.for_each_tenant(run, name)


def _escalation_recipients(db, org_id, audit_id, assignee_id) -> list:
    """Who an overdue item is escalated to: the audit's lead when there is an active one who is not the assignee,
    otherwise the administrators of the organization. Never every administrator of every organization, and never a
    platform operator."""
    if audit_id:
        lead = db.execute(
            "SELECT u.id FROM grid_audits a JOIN users u ON u.id = a.lead_id WHERE a.id = %s AND u.is_active = 1",
            (audit_id,)).fetchone()
        if lead and lead["id"] != assignee_id:
            return [lead["id"]]
    return [uid for uid in outbox.organization_people(db, org_id, outbox.ADMIN_ROLES) if uid != assignee_id]


# ═════════════════════════════════════════════════════════════════════════
# Job 1: Reminders (daily 08:00 CAT)
# ═════════════════════════════════════════════════════════════════════════

def _remind(db, org_id, today) -> int:
    """One message per subscriber and control for each day, week or month, as the subscriber chose."""
    periods = {"daily": today.isoformat(), "weekly": _week(today), "monthly": today.strftime("%Y-%m")}
    rows = db.execute(
        "SELECT r.user_id, r.control_id, r.frequency, c.due_date, c.audit_id "
        "FROM grid_reminders r JOIN grid_controls c ON r.control_id = c.id "
        "WHERE r.active = 1 AND c.status != 'Complete'").fetchall()
    asked = 0
    for r in rows:
        period = periods.get((r["frequency"] or "weekly").lower())
        if period and outbox.enqueue_safely(
                db, "control.reminder", recipient_user_id=r["user_id"], org_id=org_id, route="/grid/controls",
                fields={"reference": f"AU-{r['audit_id']}", "due": templates.iso_or_none(r["due_date"])},
                source=("grid", "control", r["control_id"]), purpose="reminder", threshold=period):
            asked += 1
    return asked


def process_reminders() -> None:
    log.info("Running reminders...")
    _in_each_organization("GRID reminders", _remind)


# ═════════════════════════════════════════════════════════════════════════
# Job 2: Expiry alerts for evidence files attached to a control (daily 08:30 CAT)
# ═════════════════════════════════════════════════════════════════════════

def _expiring_files(db, org_id, today) -> int:
    """The assignee of a control hears once per file and expiry date that the file expires within 30 days."""
    rows = db.execute(
        "SELECT ef.id, ef.control_id, ef.expires_at, c.assignee_id "
        "FROM grid_evidence_files ef JOIN grid_controls c ON ef.control_id = c.id "
        f"WHERE ef.expires_at IS NOT NULL AND ef.expires_at > {sql_current_date()} "
        f"AND ef.expires_at <= {sql_date_offset('+30 days')} AND ef.status != 'Rejected' "
        "AND c.assignee_id IS NOT NULL").fetchall()
    asked = 0
    for ef in rows:
        due = templates.iso_or_none(ef["expires_at"])
        if due and outbox.enqueue_safely(
                db, "evidence.renew", recipient_user_id=ef["assignee_id"], org_id=org_id, route="/grid/controls",
                fields={"reference": f"GE-{ef['id']}", "due": due},
                source=("grid", "control", ef["control_id"]), purpose=f"expiry:{ef['id']}", threshold=due):
            asked += 1
    return asked


def process_expiry_alerts() -> None:
    log.info("Running expiry alerts...")
    _in_each_organization("GRID expiry alerts", _expiring_files)


# ═════════════════════════════════════════════════════════════════════════
# Job 3: Escalations of overdue high-risk controls (daily 09:00 CAT)
# ═════════════════════════════════════════════════════════════════════════

def _escalate_controls(db, org_id, today) -> int:
    """A control that has been overdue for a week is escalated once a week to the audit lead, or to the organization's
    administrators when the audit has no lead."""
    cutoff = (today - timedelta(days=7)).isoformat()
    rows = db.execute(
        "SELECT c.id, c.audit_id, c.due_date, c.assignee_id FROM grid_controls c "
        "WHERE c.due_date < %s AND c.status != 'Complete' AND c.assignee_id IS NOT NULL "
        "AND c.risk_level IN ('Critical', 'High') ORDER BY c.due_date LIMIT 200", (cutoff,)).fetchall()
    asked = 0
    for c in rows:
        due = templates.iso_or_none(c["due_date"])
        for uid in _escalation_recipients(db, org_id, c["audit_id"], c["assignee_id"]):
            if outbox.enqueue_safely(
                    db, "audit.escalation", recipient_user_id=uid, org_id=org_id, route="/grid/controls",
                    fields={"reference": f"AU-{c['audit_id']}", "due": due},
                    source=("grid", "control", c["id"]), purpose="escalation", threshold=f"overdue:{_week(today)}"):
                asked += 1
    return asked


def process_escalations() -> None:
    log.info("Running escalations...")
    _in_each_organization("GRID escalations", _escalate_controls)


# ═════════════════════════════════════════════════════════════════════════
# Job 4: Weekly summary (Mondays 07:00 CAT)
# ═════════════════════════════════════════════════════════════════════════

def _summaries(db, org_id, today) -> int:
    """One weekly summary per subscriber who has an account, counting only the audits that person may open, so the
    count and the list behind the link are the same set. A subscriber with no account, or who can open none of the
    audits they chose, gets nothing."""
    from modules.governance.entity_scope import describe_records
    subs = db.execute(
        "SELECT id, user_id, email, audit_ids FROM grid_digest_subscriptions WHERE active = 1").fetchall()
    if not subs:
        return 0
    audits = [r["id"] for r in db.execute("SELECT id FROM grid_audits ORDER BY id").fetchall()]
    asked = 0
    for sub in subs:
        account = None
        if sub["user_id"]:
            account = db.execute("SELECT * FROM users WHERE id = %s AND is_active = 1", (sub["user_id"],)).fetchone()
        if account is None and sub["email"]:
            account = db.execute(
                "SELECT * FROM users WHERE LOWER(email) = LOWER(%s) AND is_active = 1", (sub["email"],)).fetchone()
        if account is None:
            continue
        chosen = (sub["audit_ids"] or "all").strip()
        wanted = audits
        if chosen != "all":
            ids = {x.strip() for x in chosen.split(",") if x.strip()}
            wanted = [a for a in audits if str(a) in ids]
        visible = sorted(describe_records(db, ("grid", "audit"), wanted, outbox.user_for_scope(db, account)))
        if not visible:
            continue
        overdue = db.execute(
            f"SELECT COUNT(*) FROM grid_controls WHERE audit_id IN ({','.join(['%s'] * len(visible))}) "
            f"AND status != 'Complete' AND due_date IS NOT NULL AND due_date < {sql_current_date()}",
            visible).fetchone()[0]
        if outbox.enqueue_safely(
                db, "summary.weekly", recipient_user_id=account["id"], org_id=org_id, route="/grid/",
                fields={"audits": len(visible), "overdue": overdue}, source=("grid", "digest", sub["id"]),
                purpose="weekly", threshold=_week(today)):
            asked += 1
    return asked


def send_weekly_digest() -> None:
    log.info("Sending weekly digest...")
    _in_each_organization("GRID weekly summary", _summaries)


# ═════════════════════════════════════════════════════════════════════════
# Job 5 — Compliance Score Snapshot (midnight CAT)
# ═════════════════════════════════════════════════════════════════════════

def snapshot_scores() -> None:
    db = get_db()
    try:
        rows = db.execute("""
            SELECT a.id, COUNT(c.id) AS total,
                   SUM(CASE WHEN c.status='Complete' THEN 1 ELSE 0 END) AS complete
            FROM grid_audits a
            LEFT JOIN grid_controls c ON c.audit_id = a.id
            GROUP BY a.id
        """).fetchall()
        for r in rows:
            total = r["total"] or 0
            complete = r["complete"] or 0
            score = round(complete / total * 100) if total > 0 else 0
            db.execute(
                "INSERT INTO grid_compliance_scores (audit_id, score, total_controls, complete_controls) "
                "VALUES (%s, %s, %s, %s)",
                (r["id"], score, total, complete),
            )
        db.commit()
        log.info("Score snapshot recorded for %d audits", len(rows))
    except Exception as exc:
        log.error("Score snapshot error: %s", exc)
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════
# Job 6 — Database Backup (02:00 CAT)
# ═════════════════════════════════════════════════════════════════════════

def perform_backup() -> None:
    log.info("Running backup...")
    try:
        backup_dir = Path(os.getenv("BACKUP_PATH", "data/backups"))
        backup_dir.mkdir(parents=True, exist_ok=True)

        stamp = utcnow().strftime("%Y%m%d_%H%M%S")
        zip_path = backup_dir / f"themisiq-{stamp}.zip"

        if zip_path.exists():
            log.info("Backup already exists: %s", zip_path.name)
            return

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            if settings.is_postgres():
                parsed = urllib.parse.urlparse(settings.DATABASE_URL)
                pg_user = parsed.username or "themisiq"
                pg_env = {
                    **os.environ,
                    "PGPASSWORD": os.getenv("PGPASSWORD", parsed.password or ""),
                    "PGSSLMODE": os.getenv("PGSSLMODE", "prefer"),
                }
                # Scope the bypass to pg_dump's own connection. Never change
                # the role default: new app sessions could inherit it while
                # the dump runs, and a failed reset could leave it enabled.
                # pg_dump normally sets row_security=off, which rejects RLS
                # tables for a non-bypassing role. Keep it on so our policy's
                # session-local bypass setting can include every row.
                pg_env["PGOPTIONS"] = "-c app.bypass_rls=true"
                cmd = [
                    "pg_dump", "--no-owner", "--no-acl", "--format=custom",
                    "--enable-row-security",
                    "-h", parsed.hostname or "localhost",
                    "-p", str(parsed.port or 5432),
                    "-U", pg_user,
                    "-d", (parsed.path or "/themisiq").lstrip("/"),
                ]
                res = subprocess.run(cmd, capture_output=True, env=pg_env, timeout=600)
                if res.returncode != 0:
                    log.error("pg_dump failed: %s", res.stderr.decode()[:500])
                    zip_path.unlink(missing_ok=True)
                    return
                zf.writestr("themisiq.dump", res.stdout)
            else:
                db_path = Path("data/oneforall.db")
                if db_path.exists():
                    zf.write(db_path, "oneforall.db")

            # Include uploads + evidence for both engines
            for src_dir, arc_prefix in [
                (Path("data/grid_uploads"), "grid_uploads"),
                (Path("data/evidence"), "evidence"),
            ]:
                if src_dir.is_dir():
                    for fpath in src_dir.rglob("*"):
                        if fpath.is_file():
                            zf.write(fpath, f"{arc_prefix}/{fpath.relative_to(src_dir)}")

        # Verify the archive before keeping it
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                if zf.testzip() is not None:
                    raise RuntimeError("zip integrity check failed")
        except Exception as verify_exc:
            log.error("Backup verify failed, removing: %s", verify_exc)
            zip_path.unlink(missing_ok=True)
            return

        # Best-effort offsite copy via rclone (e.g., Cloudflare R2)
        remote = os.getenv("BACKUP_OFFSITE_RCLONE_REMOTE", "")
        if remote:
            try:
                result = subprocess.run(
                    ["rclone", "copy", str(zip_path), remote,
                     "--s3-no-check-bucket", "--retries", "3", "--retries-sleep", "10s"],
                    capture_output=True, timeout=900,
                )
                if result.returncode != 0:
                    log.warning("R2 offsite backup failed: %s", result.stderr.decode()[:500])
                else:
                    log.info("R2 offsite backup OK: %s", zip_path.name)
            except Exception as offsite_exc:
                log.warning("Offsite backup error: %s", offsite_exc)

        # Local retention
        retain_days = int(os.getenv("BACKUP_RETAIN_DAYS", "30"))
        cutoff = utcnow().timestamp() - retain_days * 86400
        for old in backup_dir.glob("themisiq-*.zip"):
            if old.stat().st_mtime < cutoff:
                old.unlink()
                log.info("Pruned old backup: %s", old.name)

        log.info("Backup OK: %s (%d KB)", zip_path.name, zip_path.stat().st_size // 1024)
    except Exception as exc:
        log.error("Backup error: %s", exc)


# ═════════════════════════════════════════════════════════════════════════
# Job 7: Response deadlines of non-conformances (daily 08:15 CAT)
# ═════════════════════════════════════════════════════════════════════════

def _nc_deadlines(db, org_id, today) -> int:
    """The assignee hears once when the response deadline is within 3 days, and once a week while it is overdue. A
    corrected deadline is a new threshold and may be told again."""
    rows = db.execute(
        "SELECT nc.id, nc.audit_id, nc.assigned_to, nc.response_deadline FROM grid_non_conformances nc "
        "WHERE nc.response_deadline IS NOT NULL AND nc.status != 'closed' "
        "AND COALESCE(nc.cap_status, '') NOT IN ('Closed', 'Verification') AND nc.assigned_to IS NOT NULL").fetchall()
    soon = (today + timedelta(days=3)).isoformat()
    asked = 0
    for nc in rows:
        due = templates.iso_or_none(nc["response_deadline"])
        if not due or due > soon:
            continue
        stage = "due" if due >= today.isoformat() else f"overdue:{_week(today)}"
        if outbox.enqueue_safely(
                db, "audit.deadline", recipient_user_id=nc["assigned_to"], org_id=org_id,
                route=f"/grid/?open=nc:{nc['id']}", fields={"reference": f"AU-{nc['audit_id']}", "due": due},
                source=("grid", "nc", nc["id"]), purpose="deadline", threshold=f"{due}|{stage}"):
            asked += 1
    return asked


def process_nc_deadline_reminders() -> None:
    """Remind assignees whose NC response deadline is within 3 days or past."""
    log.info("Running NC deadline reminders...")
    _in_each_organization("GRID NC deadline reminders", _nc_deadlines)


# ═════════════════════════════════════════════════════════════════════════
# Job 8: Escalations of overdue non-conformances (daily 09:15 CAT)
# ═════════════════════════════════════════════════════════════════════════

def _escalate_findings(db, org_id, today) -> int:
    """A major or critical finding that is a week past its due date is escalated once a week to the audit lead, or to
    the administrators of the organization when the audit has no lead."""
    cutoff = (today - timedelta(days=7)).isoformat()
    rows = db.execute(
        "SELECT nc.id, nc.audit_id, nc.assigned_to, nc.due_date FROM grid_non_conformances nc "
        "WHERE nc.due_date IS NOT NULL AND nc.due_date < %s AND nc.status != 'closed' "
        "AND COALESCE(nc.cap_status, '') NOT IN ('Closed', 'Verification') "
        "AND nc.severity IN ('major', 'critical') ORDER BY nc.due_date LIMIT 200", (cutoff,)).fetchall()
    asked = 0
    for nc in rows:
        due = templates.iso_or_none(nc["due_date"])
        for uid in _escalation_recipients(db, org_id, nc["audit_id"], nc["assigned_to"]):
            if outbox.enqueue_safely(
                    db, "audit.escalation", recipient_user_id=uid, org_id=org_id,
                    route=f"/grid/?open=nc:{nc['id']}", fields={"reference": f"AU-{nc['audit_id']}", "due": due},
                    source=("grid", "nc", nc["id"]), purpose="escalation", threshold=f"overdue:{_week(today)}"):
                asked += 1
    return asked


def process_nc_escalations() -> None:
    """Escalate overdue NCs (a week or more past their due date, not closed)."""
    log.info("Running NC CAP escalations...")
    _in_each_organization("GRID NC escalations", _escalate_findings)


# ═════════════════════════════════════════════════════════════════════════
# Job 9: Evidence Vault expiry (daily 08:45 CAT)
# ═════════════════════════════════════════════════════════════════════════

def process_vault_expiry_notifications() -> None:
    """The messages the Evidence scheduler also asks for, under the same key, so a person reached by both jobs is told
    once (06 section 2: the evidence and GRID paths overlapped)."""
    log.info("Running vault expiry notifications...")
    from modules.evidence.scheduler import enqueue_expiry_messages
    _in_each_organization("Vault expiry notifications", enqueue_expiry_messages)


# ═════════════════════════════════════════════════════════════════════════
# Job 10 — Evidence Vault: Integrity Audit (weekly Sunday 03:00 CAT)
# ═════════════════════════════════════════════════════════════════════════

def perform_integrity_audit() -> None:
    """Re-hash all evidence files and flag mismatches."""
    import hashlib
    log.info("Running evidence integrity audit...")
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, title, file_path, file_hash FROM evidence_items "
            "WHERE status != 'archived' AND file_hash IS NOT NULL AND file_path IS NOT NULL"
        ).fetchall()

        evidence_dir = Path(os.getenv("EVIDENCE_DIR", "data/evidence"))
        checked, mismatches = 0, 0
        for ev in rows:
            fp_str = ev["file_path"] or ""
            if fp_str.startswith("aria://") or fp_str.startswith("vault://"):
                continue  # Virtual references, no file on disk
            fp = (evidence_dir / fp_str).resolve()
            if not str(fp).startswith(str(evidence_dir.resolve())):
                continue  # Path traversal safety
            if not fp.exists():
                log.warning("Integrity: file missing for vault #%d: %s", ev["id"], fp_str)
                # Insert notification
                try:
                    db.execute(
                        "INSERT INTO notifications (user_id, module, title, message, link) "
                        "SELECT id, 'platform', %s, %s, '/evidence/' "
                        "FROM users u JOIN user_roles ur ON u.id=ur.user_id WHERE ur.role_key IN ('super_admin','admin') AND u.is_active=1",
                        (
                            f"Evidence File Missing: {ev['title']}",
                            f"Vault item #{ev['id']} file is missing from disk.",
                        ),
                    )
                except Exception:
                    swallowed("perform_integrity_audit (notifications)")
                mismatches += 1
                continue

            h = hashlib.sha256()
            with open(fp, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
            disk_hash = h.hexdigest()
            checked += 1

            if disk_hash != ev["file_hash"]:
                log.error("INTEGRITY FAILURE: vault #%d hash mismatch (stored=%s, disk=%s)",
                          ev["id"], ev["file_hash"][:12], disk_hash[:12])
                try:
                    db.execute(
                        "INSERT INTO notifications (user_id, module, title, message, link) "
                        "SELECT id, 'platform', %s, %s, '/evidence/' "
                        "FROM users u JOIN user_roles ur ON u.id=ur.user_id WHERE ur.role_key IN ('super_admin','admin') AND u.is_active=1",
                        (
                            f"INTEGRITY FAILURE: {ev['title']}",
                            f"Vault item #{ev['id']} hash mismatch — file may have been tampered with.",
                        ),
                    )
                except Exception:
                    swallowed("perform_integrity_audit (notifications)")
                mismatches += 1

        db.commit()
        log.info("Integrity audit done: %d checked, %d issues", checked, mismatches)
    except Exception as exc:
        log.error("Integrity audit error: %s", exc)
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════
# Job 11 — Evidence Vault: Retention Enforcement (daily 01:00 CAT)
# ═════════════════════════════════════════════════════════════════════════

def enforce_retention_policy() -> None:
    """Auto-archive evidence items past their expiry date."""
    log.info("Running retention enforcement...")
    db = get_db()
    try:
        result = db.execute(
            "UPDATE evidence_items SET status='archived', updated_at=CURRENT_TIMESTAMP "
            "WHERE status='current' AND expiry_date IS NOT NULL "
            f"AND expiry_date < {sql_current_date()}"
        )
        count = result.rowcount
        db.commit()
        if count:
            log.info("Retention enforcement: archived %d expired items", count)
        else:
            log.info("Retention enforcement: no expired items")
    except Exception as exc:
        log.error("Retention enforcement error: %s", exc)
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════
# Job 12 — Backup Verification (daily 03:00 CAT)
# ═════════════════════════════════════════════════════════════════════════

def backup_verify_check() -> None:
    """Verify the most recent backup is structurally sound. Alerts admins on failure."""
    import subprocess as _sub
    log.info("Running backup verification...")
    script = Path(__file__).parent.parent.parent / "scripts" / "verify_latest_backup.py"
    try:
        result = _sub.run(
            [sys.executable, str(script)],
            capture_output=True, timeout=120,
        )
        if result.returncode == 0:
            log.info("Backup verify: %s", result.stdout.decode().strip())
        else:
            msg = result.stderr.decode().strip() or result.stdout.decode().strip()
            log.error("Backup verify FAILED: %s", msg)
            # Alert admins via the existing notification system
            try:
                from core.event_handlers import _notify_admins
                db_notify = get_db()
                try:
                    _notify_admins(db_notify, "GRID",
                                   "Backup Verification Failed",
                                   f"The daily backup verification failed:\n\n{msg[:500]}")
                    db_notify.commit()
                finally:
                    db_notify.close()
            except Exception as notify_exc:
                log.error("Could not notify admins of backup failure: %s", notify_exc)
    except Exception as exc:
        log.error("Backup verify error: %s", exc)


# ═════════════════════════════════════════════════════════════════════════
# Job 13 — Weekly Restore Drill (Sunday 04:00 CAT)
# ═════════════════════════════════════════════════════════════════════════

def weekly_restore_drill() -> None:
    """Run the weekly restore drill as a subprocess so a Docker failure can't crash the app."""
    import subprocess as _sub
    log.info("Running weekly restore drill...")
    script = Path(__file__).parent.parent.parent / "scripts" / "weekly_restore_drill.py"
    try:
        result = _sub.run(
            [sys.executable, str(script)],
            capture_output=True, timeout=1800,
        )
        if result.returncode == 0:
            log.info("Restore drill: PASS")
        else:
            msg = result.stderr.decode().strip() or result.stdout.decode().strip()
            log.error("Restore drill FAILED: %s", msg)
            try:
                from core.event_handlers import _notify_admins
                db_notify = get_db()
                try:
                    _notify_admins(db_notify, "GRID",
                                   "Weekly Restore Drill Failed",
                                   f"The weekly restore drill failed:\n\n{msg[:500]}")
                    db_notify.commit()
                finally:
                    db_notify.close()
            except Exception as notify_exc:
                log.error("Could not notify admins of drill failure: %s", notify_exc)
    except Exception as exc:
        log.error("Restore drill error: %s", exc)


# ═════════════════════════════════════════════════════════════════════════
# Scheduler lifecycle
# ═════════════════════════════════════════════════════════════════════════

def start_scheduler() -> BackgroundScheduler:
    """Register all cron jobs and start the background scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        log.warning("Scheduler already running")
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True)

    _scheduler.add_job(process_reminders, CronTrigger(hour=8, minute=0, timezone=TZ),
                       id="grid_reminders", replace_existing=True)
    _scheduler.add_job(process_expiry_alerts, CronTrigger(hour=8, minute=30, timezone=TZ),
                       id="grid_expiry_alerts", replace_existing=True)
    _scheduler.add_job(process_escalations, CronTrigger(hour=9, minute=0, timezone=TZ),
                       id="grid_escalations", replace_existing=True)
    _scheduler.add_job(send_weekly_digest, CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=TZ),
                       id="grid_weekly_digest", replace_existing=True)
    _scheduler.add_job(snapshot_scores, CronTrigger(hour=0, minute=0, timezone=TZ),
                       id="grid_score_snapshot", replace_existing=True)
    _scheduler.add_job(process_nc_deadline_reminders, CronTrigger(hour=8, minute=15, timezone=TZ),
                       id="grid_nc_deadlines", replace_existing=True)
    _scheduler.add_job(process_nc_escalations, CronTrigger(hour=9, minute=15, timezone=TZ),
                       id="grid_nc_escalations", replace_existing=True)
    _scheduler.add_job(process_vault_expiry_notifications, CronTrigger(hour=8, minute=45, timezone=TZ),
                       id="vault_expiry_notifications", replace_existing=True)
    _scheduler.add_job(perform_integrity_audit, CronTrigger(day_of_week="sun", hour=3, minute=0, timezone=TZ),
                       id="vault_integrity_audit", replace_existing=True)
    _scheduler.add_job(enforce_retention_policy, CronTrigger(hour=1, minute=0, timezone=TZ),
                       id="vault_retention_enforcement", replace_existing=True)
    backup_jobs_enabled = os.getenv(
        "GRID_BACKUP_JOBS_ENABLED", "true"
    ).lower() in ("1", "true", "yes", "on")
    if backup_jobs_enabled:
        _scheduler.add_job(perform_backup, CronTrigger(hour=2, minute=0, timezone=TZ),
                           id="grid_backup", replace_existing=True)
        _scheduler.add_job(backup_verify_check, CronTrigger(hour=3, minute=0, timezone=TZ),
                           id="backup_verify_check", replace_existing=True)
        _scheduler.add_job(weekly_restore_drill, CronTrigger(day_of_week="sun", hour=4, minute=0, timezone=TZ),
                           id="weekly_restore_drill", replace_existing=True)
    else:
        log.info(
            "GRID application backup jobs disabled; host backup service is authoritative"
        )

    _scheduler.start()
    log.info(
        "GRID scheduler started (Africa/Harare timezone) — %d jobs registered",
        len(_scheduler.get_jobs()),
    )
    return _scheduler


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("GRID scheduler stopped")
    _scheduler = None


def get_scheduler_status() -> dict:
    """P02: read-only, side-effect-free liveness check -- whether this
    process's APScheduler is running and each registered job's next
    scheduled fire time. This is liveness, not an audit trail: APScheduler
    itself does not retain a history of past run outcomes, so "last
    successful run" is deliberately not claimed here -- reporting a fake
    one would be worse than reporting none."""
    if _scheduler is None or not _scheduler.running:
        return {"running": False, "jobs": []}
    jobs = [
        {"id": job.id, "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None}
        for job in _scheduler.get_jobs()
    ]
    return {"running": True, "jobs": jobs}


def get_scheduler_status() -> dict:
    """Return current scheduler status and next run times."""
    if not _scheduler or not _scheduler.running:
        return {"running": False, "jobs": []}
    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    return {"running": True, "jobs": jobs}
