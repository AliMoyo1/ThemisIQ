"""Regression tests for the production systemd deployment tooling."""

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "deploy.py"
SPEC = importlib.util.spec_from_file_location("themisiq_production_deploy", SCRIPT)
deploy = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(deploy)


def test_configured_environment_prefers_live_values_and_forces_safe_rollout():
    selected = deploy.configured_environment(
        running={
            "DATABASE_URL": "postgresql://live@127.0.0.1:5434/themisiq",
            "SECRET_KEY": "live-secret",
            "ARIA_POLICY_AUTHORING_ENABLED": "true",
            "ARIA_POLICY_AUTHORING_ORG_IDS": "12",
            "PATH": "/untrusted",
        },
        legacy_sources=[{
            "DATABASE_URL": "postgresql://stale@127.0.0.1:5432/themisiq",
            "SECRET_KEY": "stale-secret",
            "DEEPSEEK_API_KEY": "provider-secret",
            "PATH": "/also-untrusted",
        }],
        unit_keys={"DATABASE_URL", "SECRET_KEY"},
    )
    assert selected["DATABASE_URL"].endswith(":5434/themisiq")
    assert selected["SECRET_KEY"] == "live-secret"
    assert selected["DEEPSEEK_API_KEY"] == "provider-secret"
    assert selected["ARIA_POLICY_AUTHORING_ENABLED"] == "false"
    assert selected["ARIA_POLICY_AUTHORING_ORG_IDS"] == ""
    assert selected["GRID_BACKUP_JOBS_ENABLED"] == "false"
    assert selected["HOST"] == "127.0.0.1"
    assert "PATH" not in selected


def test_validate_environment_fails_closed_for_authoring_and_non_postgres():
    values = dict(deploy.FORCED_SAFE_VALUES)
    values.update({
        "DATABASE_URL": "sqlite:///data/oneforall.db",
        "SECRET_KEY": "present",
        "ARIA_POLICY_AUTHORING_ENABLED": "true",
        "ARIA_POLICY_AUTHORING_ORG_IDS": "7",
    })
    errors = deploy.validate_environment(values)
    assert any("PostgreSQL" in error for error in errors)
    assert any("AUTHORING_ENABLED" in error for error in errors)
    assert any("ORG_IDS" in error for error in errors)


def test_environment_serialization_quotes_values_without_printable_newlines():
    text = deploy.serialize_environment({
        "DATABASE_URL": "postgresql://user:p@ss@127.0.0.1:5434/themisiq",
        "SECRET_KEY": 'a value with "quotes" and \\slashes',
    })
    assert 'DATABASE_URL="postgresql://user:p@ss@127.0.0.1:5434/themisiq"' in text
    assert 'SECRET_KEY="a value with \\"quotes\\" and \\\\slashes"' in text


def test_atomic_private_write_uses_mode_0600(tmp_path):
    target = tmp_path / "etc" / "themisiq.env"
    deploy.atomic_write_private(target, 'SECRET_KEY="value"\n')
    assert target.read_text(encoding="utf-8") == 'SECRET_KEY="value"\n'
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700


def test_private_write_does_not_rechmod_existing_parent(tmp_path):
    parent = tmp_path / "project"
    parent.mkdir()
    if os.name != "nt":
        parent.chmod(0o755)

    deploy.atomic_write_private(parent / ".env", 'SECRET_KEY="value"\n')

    if os.name != "nt":
        assert stat.S_IMODE(parent.stat().st_mode) == 0o755


def test_restore_unit_removes_new_install_when_no_previous_unit(tmp_path):
    unit = tmp_path / "themisiq-app.service"
    unit.write_text("new unit\n", encoding="utf-8")
    dropin = tmp_path / "themisiq-app.service.d"
    dropin.mkdir()
    (dropin / "override.conf").write_text("new drop-in\n", encoding="utf-8")

    deploy.restore_unit(unit, None, None)

    assert not unit.exists()
    assert not dropin.exists()


def test_scrub_legacy_file_removes_secrets_but_preserves_flags(tmp_path):
    legacy = tmp_path / ".env"
    legacy.write_text(
        "DEBUG=false\nSECRET_KEY=secret\n"
        "DATABASE_URL=postgresql://user:pass@localhost/db\n"
        "SLACK_WEBHOOK_URL=https://hooks.example.invalid/secret\n"
        "ARIA_POLICY_AUTHORING_ENABLED=false\n",
        encoding="utf-8",
    )
    removed = deploy.scrub_legacy_file(legacy)
    assert set(removed) == {"SECRET_KEY", "DATABASE_URL", "SLACK_WEBHOOK_URL"}
    remaining = legacy.read_text(encoding="utf-8")
    assert "DEBUG=false" in remaining
    assert "ARIA_POLICY_AUTHORING_ENABLED=false" in remaining
    assert "secret" not in remaining
    if os.name != "nt":
        assert stat.S_IMODE(legacy.stat().st_mode) == 0o600


def test_systemd_unit_is_non_root_loopback_only_and_sandboxed():
    unit = (Path(__file__).parents[1] / "scripts" / "systemd" / "themisiq-app.service").read_text(encoding="utf-8")
    required = (
        "User=themisiq", "Group=themisiq",
        "EnvironmentFile=/etc/themisiq/themisiq.env",
        "--host 127.0.0.1", "--workers 1", "NoNewPrivileges=true",
        "PrivateTmp=true", "ProtectSystem=strict",
        "ProtectHome=true", "UMask=0077",
    )
    for marker in required:
        assert marker in unit
    assert "Environment=SECRET_KEY=" not in unit
    assert "--host 0.0.0.0" not in unit
    assert "--workers 2" not in unit


def test_backup_jobs_use_the_service_virtualenv_interpreter():
    scheduler = (Path(__file__).parents[1] / "modules" / "grid" / "scheduler.py").read_text(encoding="utf-8")
    assert '["python", str(script)]' not in scheduler
    assert scheduler.count("[sys.executable, str(script)]") == 2
    assert '"GRID_BACKUP_JOBS_ENABLED", "true"' in scheduler


def test_production_backup_is_private_atomic_and_restore_verified():
    script = (
        Path(__file__).parents[1] / "scripts" / "production_backup.sh"
    ).read_text(encoding="utf-8")

    assert "set -Eeuo pipefail" in script
    assert "umask 077" in script
    assert "--format=custom" in script
    assert "--list \"${staging_path}\"" in script
    assert "--exit-on-error" in script
    assert "themisiq_backup_verify_" in script
    assert "install -o root -g root -m 0600" in script
    assert "mv -- \"${partial_path}\" \"${final_path}\"" in script
    assert "sha256sum \"${final_path}\"" in script
    assert "invalid_indexes" in script
    assert "/usr/bin/docker" not in script.lower()
    assert "\ndocker " not in script.lower()
