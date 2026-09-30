"""
PLAN-36 P02: individual read-only diagnostic probes. Each mirrors a real,
already-existing mechanism rather than inventing a second copy of it:
core/backup_status.py reads the exact file/env conventions
scripts/verify_latest_backup.py and modules/grid/scheduler.py's
perform_backup() already use; modules/aria/policy_preview.py's
get_worker_heartbeat_state() reads the exact heartbeat file
scripts/aria_policy_preview_worker.py's own healthcheck() already reads.
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.capability_state import AVAILABLE, DEGRADED, NOT_CONFIGURED


def test_backup_freshness_reports_not_configured_when_host_managed(monkeypatch):
    monkeypatch.setenv("GRID_BACKUP_JOBS_ENABLED", "false")
    from core.backup_status import get_backup_freshness
    state = get_backup_freshness()
    assert state.state == NOT_CONFIGURED
    assert state.reason_code == "backup_host_managed"


def test_backup_freshness_reports_not_configured_when_no_file(monkeypatch, tmp_path):
    monkeypatch.setenv("GRID_BACKUP_JOBS_ENABLED", "true")
    monkeypatch.setenv("BACKUP_PATH", str(tmp_path / "empty"))
    from core.backup_status import get_backup_freshness
    state = get_backup_freshness()
    assert state.state == NOT_CONFIGURED
    assert state.reason_code == "no_backup_found"


def test_backup_freshness_reports_available_for_a_fresh_file(monkeypatch, tmp_path):
    monkeypatch.setenv("GRID_BACKUP_JOBS_ENABLED", "true")
    monkeypatch.setenv("BACKUP_PATH", str(tmp_path))
    monkeypatch.setenv("BACKUP_MAX_AGE_HOURS", "26")
    (tmp_path / "themisiq-20260930.zip").write_bytes(b"x" * 1024)
    from core.backup_status import get_backup_freshness
    state = get_backup_freshness()
    assert state.state == AVAILABLE
    assert state.reason_code == "backup_fresh"


def test_backup_freshness_reports_degraded_for_a_stale_file(monkeypatch, tmp_path):
    """Red proof (temporarily widening _MAX_AGE_HOURS to something absurd):
    this assertion fails because a stale file would then read as fresh."""
    monkeypatch.setenv("GRID_BACKUP_JOBS_ENABLED", "true")
    monkeypatch.setenv("BACKUP_PATH", str(tmp_path))
    monkeypatch.setenv("BACKUP_MAX_AGE_HOURS", "1")
    stale = tmp_path / "themisiq-old.zip"
    stale.write_bytes(b"x" * 1024)
    old_time = time.time() - 3 * 3600  # 3h old, past the 1h max
    os.utime(stale, (old_time, old_time))

    from core.backup_status import get_backup_freshness
    state = get_backup_freshness()
    assert state.state == DEGRADED
    assert state.reason_code == "backup_stale"
    assert state.retryable is True


def test_worker_heartbeat_reports_not_configured_when_missing(monkeypatch, tmp_path):
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_PREVIEW_SPOOL_DIR", str(tmp_path / "no-spool"))
    from modules.aria.policy_preview import get_worker_heartbeat_state
    state = get_worker_heartbeat_state()
    assert state.state == NOT_CONFIGURED
    assert state.reason_code == "preview_worker_heartbeat_missing"


def test_worker_heartbeat_reports_available_when_fresh(monkeypatch, tmp_path):
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_PREVIEW_SPOOL_DIR", str(tmp_path))
    monkeypatch.setenv("ARIA_POLICY_PREVIEW_HEARTBEAT_MAX_AGE_SECONDS", "90")
    (tmp_path / ".worker.heartbeat").write_text(str(time.time()), encoding="ascii")

    from modules.aria.policy_preview import get_worker_heartbeat_state
    state = get_worker_heartbeat_state()
    assert state.state == AVAILABLE


def test_worker_heartbeat_reports_degraded_when_stale(monkeypatch, tmp_path):
    """Red proof (temporarily widening the max-age env var to something
    absurd): this assertion fails because a stale heartbeat would then
    read as alive."""
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_PREVIEW_SPOOL_DIR", str(tmp_path))
    monkeypatch.setenv("ARIA_POLICY_PREVIEW_HEARTBEAT_MAX_AGE_SECONDS", "5")
    (tmp_path / ".worker.heartbeat").write_text(str(time.time() - 60), encoding="ascii")

    from modules.aria.policy_preview import get_worker_heartbeat_state
    state = get_worker_heartbeat_state()
    assert state.state == DEGRADED
    assert state.retryable is True


def test_scheduler_status_reports_not_running_when_never_started():
    from modules.grid import scheduler as sched
    sched._scheduler = None
    status = sched.get_scheduler_status()
    assert status == {"running": False, "jobs": []}


def test_get_diagnostics_never_leaks_the_configured_smtp_host(monkeypatch):
    """Redaction regression (task_plan.md P02 acceptance: 'redaction tests
    cover every response field'). email state must be a boolean-derived
    judgement only -- the configured host/credentials must never appear
    anywhere in the serialized response."""
    import json
    from config import settings

    secret_host = "smtp.internal-secret-host.example.com"
    # _email_configured_state reads core.email._get_setting("smtp_host") first
    # (a real settings-table row, if any, takes precedence over settings.SMTP_HOST)
    # -- patch that primary path directly rather than the env fallback so the
    # test exercises the actual precedence order, not a path it never takes.
    import core.email
    monkeypatch.setattr(core.email, "_get_setting", lambda key, default="": secret_host if key == "smtp_host" else default)
    monkeypatch.setattr(settings, "SMTP_HOST", secret_host, raising=False)

    from modules.launcher.diagnostics_service import get_diagnostics
    result = get_diagnostics({"org_id": 1, "is_super_admin": True, "licensed_modules": []})

    serialized = json.dumps(result)
    assert secret_host not in serialized
    assert result["email"]["state"] == AVAILABLE
