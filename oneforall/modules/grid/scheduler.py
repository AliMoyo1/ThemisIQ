"""
GRID module — Background scheduler.

Runs periodic compliance tasks on cron schedules (Africa/Harare = CAT = UTC+2).
Ported from the original AuditSphere scheduler.js.

IMPORTANT: Jobs only run on schedule, never on startup.
All email calls have timeouts built into email_service.py (10 s per request).
"""
from __future__ import annotations

import logging
import math
import os
import shutil
import subprocess
import urllib.parse
import zipfile
from datetime import date, datetime
from core.timeutils import utcnow, to_dt
from pathlib import Path

from config import settings

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import get_db_background as get_db, sql_now_offset, sql_date_offset, sql_current_date  # scheduler: fail-fast, never block UI
from modules.grid.email_service import (
    send_email,
    reminder_email_html,
    weekly_digest_html,
    escalation_html,
    expiry_alert_html,
    nc_deadline_reminder_html,
    nc_cap_escalation_html,
)

log = logging.getLogger("grid.scheduler")
TZ = "Africa/Harare"

_scheduler: BackgroundScheduler | None = None


# ═════════════════════════════════════════════════════════════════════════
# Job 1 — Reminders (daily 08:00 CAT)
# ═════════════════════════════════════════════════════════════════════════

def process_reminders() -> None:
    log.info("Running reminders...")
    db = get_db()
    try:
        rows = db.execute(f"""
            SELECT r.id, r.frequency, r.last_sent,
                   c.control_id AS ctrl_id, c.name AS control_name,
                   c.due_date, c.status AS control_status,
                   a.name AS audit_name,
                   u.full_name AS user_name, u.email AS user_email
            FROM grid_reminders r
            JOIN grid_controls c  ON r.control_id = c.id
            JOIN grid_audits   a  ON c.audit_id   = a.id
            LEFT JOIN users    u  ON u.id          = r.user_id
            WHERE r.active = 1 AND c.status != 'Complete'
            AND (
              (r.frequency = 'daily')
              OR (r.frequency = 'weekly'  AND (r.last_sent IS NULL OR r.last_sent < {sql_now_offset('-6 days')}))
              OR (r.frequency = 'monthly' AND (r.last_sent IS NULL OR r.last_sent < {sql_now_offset('-28 days')}))
            )
        """).fetchall()

        sent = 0
        for r in rows:
            email = r["user_email"]
            if not email:
                continue
            send_email(
                to=email,
                subject=f"[G.R.I.D AI] Reminder: {r['control_name']}",
                body_html=reminder_email_html(
                    control_name=r["control_name"],
                    control_id=r["ctrl_id"] or "",
                    due_date=r["due_date"] or "",
                    audit_name=r["audit_name"] or "",
                    recipient_name=r["user_name"] or "",
                    frequency=r["frequency"] or "weekly",
                ),
            )
            db.execute("UPDATE grid_reminders SET last_sent=%s WHERE id=%s",
                        (utcnow().isoformat(), r["id"]))
            sent += 1
        db.commit()
        log.info("Reminders done: %d sent", sent)
    except Exception as exc:
        log.error("Reminders error: %s", exc)
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════
# Job 2 — Expiry Alerts (daily 08:30 CAT)
# ═════════════════════════════════════════════════════════════════════════

def process_expiry_alerts() -> None:
    log.info("Running expiry alerts...")
    db = get_db()
    try:
        rows = db.execute(f"""
            SELECT ef.id, ef.original_name AS evidence_name, ef.expires_at,
                   c.name AS control_name,
                   u.full_name AS owner_name, u.email AS owner_email
            FROM grid_evidence_files ef
            JOIN grid_controls c ON ef.control_id = c.id
            LEFT JOIN users    u ON c.assignee_id = u.id
            WHERE ef.expires_at IS NOT NULL
              AND ef.expires_at > CURRENT_DATE
              AND ef.expires_at <= {sql_date_offset('+30 days')}
              AND ef.expiry_notified = 0
              AND ef.status != 'Rejected'
        """).fetchall()

        sent = 0
        for ev in rows:
            if not ev["owner_email"]:
                continue
            days_left = math.ceil(
                (to_dt(ev["expires_at"]) - utcnow()).total_seconds() / 86400
            )
            send_email(
                to=ev["owner_email"],
                subject=f"[G.R.I.D AI] Evidence expiring in {days_left} days: {ev['evidence_name']}",
                body_html=expiry_alert_html(
                    recipient_name=ev["owner_name"] or "",
                    evidence_name=ev["evidence_name"] or "",
                    control_name=ev["control_name"] or "",
                    expiry_date=ev["expires_at"] or "",
                    days_until_expiry=days_left,
                ),
            )
            db.execute("UPDATE grid_evidence_files SET expiry_notified=1 WHERE id=%s", (ev["id"],))
            sent += 1
        db.commit()
        log.info("Expiry alerts done: %d sent", sent)
    except Exception as exc:
        log.error("Expiry alerts error: %s", exc)
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════
# Job 3 — Escalations (daily 09:00 CAT)
# ═════════════════════════════════════════════════════════════════════════

def process_escalations() -> None:
    log.info("Running escalations...")
    db = get_db()
    try:
        rows = db.execute(f"""
            SELECT c.id, c.control_id AS ctrl_id, c.name, c.due_date,
                   c.risk_level, a.name AS audit_name,
                   u.full_name AS owner_name, u.email AS owner_email,
                   m.full_name AS manager_name, m.email AS manager_email
            FROM grid_controls c
            JOIN grid_audits a ON c.audit_id = a.id
            LEFT JOIN users  u ON c.assignee_id = u.id
            LEFT JOIN users m ON m.id IN (SELECT user_id FROM user_roles WHERE role_key IN ('super_admin','admin'))
            WHERE c.due_date < {sql_date_offset('-7 days')}
              AND c.status != 'Complete'
              AND c.assignee_id IS NOT NULL
              AND c.risk_level IN ('Critical', 'High')
            LIMIT 20
        """).fetchall()

        seen: set[int] = set()
        for ctrl in rows:
            if not ctrl["manager_email"] or ctrl["id"] in seen:
                continue
            seen.add(ctrl["id"])
            days_overdue = math.floor(
                (utcnow() - to_dt(ctrl["due_date"])).total_seconds() / 86400
            )
            send_email(
                to=ctrl["manager_email"],
                subject=f"[G.R.I.D AI] ESCALATION: {ctrl['name']} — {days_overdue} days overdue",
                body_html=escalation_html(
                    manager_name=ctrl["manager_name"] or "",
                    owner_name=ctrl["owner_name"] or "Unassigned",
                    control_name=ctrl["name"] or "",
                    control_id=ctrl["ctrl_id"] or str(ctrl["id"])[:8],
                    days_overdue=days_overdue,
                    audit_name=ctrl["audit_name"] or "",
                ),
            )
        log.info("Escalations done: %d sent", len(seen))
    except Exception as exc:
        log.error("Escalations error: %s", exc)
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════
# Job 4 — Weekly Digest (Mondays 07:00 CAT)
# ═════════════════════════════════════════════════════════════════════════

def send_weekly_digest() -> None:
    log.info("Sending weekly digest...")
    db = get_db()
    try:
        subs = db.execute("SELECT * FROM grid_digest_subscriptions WHERE active=1").fetchall()
        if not subs:
            log.info("No digest subscribers")
            return

        audits = [dict(r) for r in db.execute("""
            SELECT a.id, a.name, f.name AS framework_name, a.audit_type,
                   COUNT(c.id) AS total_controls,
                   SUM(CASE WHEN c.status='Complete' THEN 1 ELSE 0 END) AS complete_controls,
                   SUM(CASE WHEN c.due_date < CURRENT_DATE AND c.status!='Complete' THEN 1 ELSE 0 END) AS overdue_controls
            FROM grid_audits a
            JOIN grid_frameworks f ON a.framework_id = f.id
            LEFT JOIN grid_controls c ON c.audit_id = a.id
            GROUP BY a.id ORDER BY a.created_at DESC
        """).fetchall()]

        for a in audits:
            total = a.get("total_controls") or 0
            complete = a.get("complete_controls") or 0
            a["completion_pct"] = round(complete / total * 100) if total > 0 else 0

        for sub in subs:
            sub = dict(sub)
            audit_ids = sub.get("audit_ids", "all")
            if audit_ids == "all":
                filtered = audits
            else:
                id_set = {x.strip() for x in audit_ids.split(",")}
                filtered = [a for a in audits if str(a["id"]) in id_set]

            send_email(
                to=sub["email"],
                subject=f"[G.R.I.D AI] Weekly Compliance Digest — {date.today().strftime('%d/%m/%Y')}",
                body_html=weekly_digest_html(
                    recipient_name=sub.get("name", ""),
                    audits=filtered,
                ),
            )

        log.info("Weekly digest sent to %d subscriber(s)", len(subs))
    except Exception as exc:
        log.error("Weekly digest error: %s", exc)
    finally:
        db.close()


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
                pg_env = {
                    **os.environ,
                    "PGPASSWORD": os.getenv("PGPASSWORD", parsed.password or ""),
                    "PGSSLMODE": os.getenv("PGSSLMODE", "prefer"),
                }
                cmd = [
                    "pg_dump", "--no-owner", "--no-acl", "--format=custom",
                    "-h", parsed.hostname or "localhost",
                    "-p", str(parsed.port or 5432),
                    "-U", parsed.username or "themisiq",
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
# Job 7 — NC Response Deadline Reminders (daily 08:15 CAT)
# ═════════════════════════════════════════════════════════════════════════

def process_nc_deadline_reminders() -> None:
    """Email assignees whose NC response_deadline is within 3 days or past due."""
    log.info("Running NC deadline reminders...")
    db = get_db()
    try:
        rows = db.execute(f"""
            SELECT nc.id, nc.title, nc.severity, nc.response_deadline,
                   nc.cap_status, nc.status,
                   a.name AS audit_name,
                   u.full_name AS owner_name, u.email AS owner_email
            FROM grid_non_conformances nc
            JOIN grid_audits a ON nc.audit_id = a.id
            LEFT JOIN users  u ON nc.assigned_to = u.id
            WHERE nc.response_deadline IS NOT NULL
              AND nc.status != 'closed'
              AND nc.cap_status NOT IN ('Closed', 'Verification')
              AND nc.response_deadline <= {sql_date_offset('+3 days')}
              AND nc.assigned_to IS NOT NULL
        """).fetchall()

        sent = 0
        for nc in rows:
            if not nc["owner_email"]:
                continue
            days = math.floor(
                (to_dt(nc["response_deadline"]) - utcnow()).total_seconds() / 86400
            )
            send_email(
                to=nc["owner_email"],
                subject=f"[G.R.I.D AI] {'OVERDUE' if days < 0 else 'Deadline'}: {nc['title']}",
                body_html=nc_deadline_reminder_html(
                    owner_name=nc["owner_name"] or "",
                    nc_title=nc["title"] or "",
                    severity=nc["severity"] or "",
                    response_deadline=nc["response_deadline"] or "",
                    days_remaining=days,
                    cap_status=nc["cap_status"] or "",
                    audit_name=nc["audit_name"] or "",
                ),
            )
            sent += 1
        log.info("NC deadline reminders done: %d sent", sent)
    except Exception as exc:
        log.error("NC deadline reminders error: %s", exc)
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════
# Job 8 — NC CAP Escalations (daily 09:15 CAT)
# ═════════════════════════════════════════════════════════════════════════

def process_nc_escalations() -> None:
    """Escalate overdue NCs (due_date past 7+ days, not closed) to admins."""
    log.info("Running NC CAP escalations...")
    db = get_db()
    try:
        rows = db.execute(f"""
            SELECT nc.id, nc.title, nc.severity, nc.due_date,
                   nc.cap_status, a.name AS audit_name,
                   u.full_name AS owner_name,
                   m.full_name AS manager_name, m.email AS manager_email
            FROM grid_non_conformances nc
            JOIN grid_audits a ON nc.audit_id = a.id
            LEFT JOIN users  u ON nc.assigned_to = u.id
            LEFT JOIN users m ON m.id IN (SELECT user_id FROM user_roles WHERE role_key IN ('super_admin','admin'))
            WHERE nc.due_date IS NOT NULL
              AND nc.due_date < {sql_date_offset('-7 days')}
              AND nc.status != 'closed'
              AND nc.cap_status NOT IN ('Closed', 'Verification')
              AND nc.severity IN ('major', 'critical')
            LIMIT 30
        """).fetchall()

        seen: set[int] = set()
        for nc in rows:
            if not nc["manager_email"] or nc["id"] in seen:
                continue
            seen.add(nc["id"])
            days_overdue = math.floor(
                (utcnow() - datetime.fromisoformat(nc["due_date"])).total_seconds() / 86400
            )
            send_email(
                to=nc["manager_email"],
                subject=f"[G.R.I.D AI] ESCALATION: {nc['title']} — {days_overdue} days overdue",
                body_html=nc_cap_escalation_html(
                    manager_name=nc["manager_name"] or "",
                    owner_name=nc["owner_name"] or "Unassigned",
                    nc_title=nc["title"] or "",
                    severity=nc["severity"] or "",
                    cap_status=nc["cap_status"] or "",
                    days_overdue=days_overdue,
                    audit_name=nc["audit_name"] or "",
                    due_date=nc["due_date"] or "",
                ),
            )
        log.info("NC CAP escalations done: %d sent", len(seen))
    except Exception as exc:
        log.error("NC CAP escalations error: %s", exc)
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════
# Job 9 — Evidence Vault: Expiry Notifications (daily 08:45 CAT)
# ═════════════════════════════════════════════════════════════════════════

def process_vault_expiry_notifications() -> None:
    """Email admins about evidence items expiring within 30 days."""
    log.info("Running vault expiry notifications...")
    db = get_db()
    try:
        rows = db.execute(f"""
            SELECT e.id, e.title, e.category, e.expiry_date,
                   e.uploaded_by, u.full_name AS owner_name, u.email AS owner_email
            FROM evidence_items e
            LEFT JOIN users u ON e.uploaded_by = u.id
            WHERE e.status = 'current'
              AND e.expiry_date IS NOT NULL
              AND e.expiry_date > {sql_current_date()}
              AND e.expiry_date <= {sql_date_offset('+30 days')}
            LIMIT 50
        """).fetchall()

        sent = 0
        for ev in rows:
            days_left = math.ceil(
                (to_dt(ev["expiry_date"]) - utcnow()).total_seconds() / 86400
            )
            # Notify the uploader if they have an email
            email = ev["owner_email"]
            if not email:
                continue
            send_email(
                to=email,
                subject=f"[One For All] Evidence expiring in {days_left} days: {ev['title']}",
                body_html=expiry_alert_html(
                    recipient_name=ev["owner_name"] or "",
                    evidence_name=ev["title"] or "",
                    control_name=f"Vault item #{ev['id']} ({ev['category']})",
                    expiry_date=ev["expiry_date"] or "",
                    days_until_expiry=days_left,
                ),
            )
            sent += 1
        log.info("Vault expiry notifications done: %d sent", sent)
    except Exception as exc:
        log.error("Vault expiry notifications error: %s", exc)
    finally:
        db.close()


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
                    pass
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
                    pass
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
            ["python", str(script)],
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
            ["python", str(script)],
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
    _scheduler.add_job(perform_backup, CronTrigger(hour=2, minute=0, timezone=TZ),
                       id="grid_backup", replace_existing=True)
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
    _scheduler.add_job(backup_verify_check, CronTrigger(hour=3, minute=0, timezone=TZ),
                       id="backup_verify_check", replace_existing=True)
    _scheduler.add_job(weekly_restore_drill, CronTrigger(day_of_week="sun", hour=4, minute=0, timezone=TZ),
                       id="weekly_restore_drill", replace_existing=True)

    _scheduler.start()
    log.info("GRID scheduler started (Africa/Harare timezone) — 13 jobs registered")
    return _scheduler


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("GRID scheduler stopped")
    _scheduler = None


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
