"""Regression for PostgreSQL backup RLS isolation."""

import subprocess
import zipfile

import database
from modules.grid import scheduler


def test_postgres_backup_bypass_is_limited_to_dump_connection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BACKUP_PATH", str(tmp_path / "backups"))
    monkeypatch.delenv("BACKUP_OFFSITE_RCLONE_REMOTE", raising=False)
    monkeypatch.delenv("PGOPTIONS", raising=False)
    monkeypatch.setattr(scheduler.settings, "is_postgres", lambda: True)
    monkeypatch.setattr(
        scheduler.settings,
        "DATABASE_URL",
        "postgresql://backup_test:synthetic@127.0.0.1:5432/themisiq_test_backup",
    )
    monkeypatch.setattr(
        database,
        "get_db_bypass_rls",
        lambda: (_ for _ in ()).throw(AssertionError("must not alter a database role")),
    )

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, b"synthetic-dump", b"")

    monkeypatch.setattr(scheduler.subprocess, "run", fake_run)

    scheduler.perform_backup()

    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd[0] == "pg_dump"
    assert "--enable-row-security" in cmd
    assert kwargs["env"]["PGOPTIONS"] == "-c app.bypass_rls=true"
    archives = list((tmp_path / "backups").glob("themisiq-*.zip"))
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as archive:
        assert archive.read("themisiq.dump") == b"synthetic-dump"