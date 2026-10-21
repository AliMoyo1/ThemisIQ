"""Regression tests for the production systemd deployment tooling."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import time
from pathlib import Path

import pytest


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
            "PYTHON_DOTENV_DISABLED": "0",
        },
        legacy_sources=[{
            "DATABASE_URL": "postgresql://stale@127.0.0.1:5432/themisiq",
            "SECRET_KEY": "stale-secret",
            "DEEPSEEK_API_KEY": "provider-secret",
            "OPENROUTER_API_KEY": "openrouter-secret",
            "PATH": "/also-untrusted",
        }],
        unit_keys={"DATABASE_URL", "SECRET_KEY"},
    )
    assert selected["DATABASE_URL"].endswith(":5434/themisiq")
    assert selected["SECRET_KEY"] == "live-secret"
    assert selected["DEEPSEEK_API_KEY"] == "provider-secret"
    assert selected["OPENROUTER_API_KEY"] == "openrouter-secret"
    assert selected["ARIA_POLICY_AUTHORING_ENABLED"] == "false"
    assert selected["ARIA_POLICY_AUTHORING_ORG_IDS"] == ""
    assert selected["GRID_BACKUP_JOBS_ENABLED"] == "false"
    assert selected["HOST"] == "127.0.0.1"
    assert "PATH" not in selected
    assert "PYTHON_DOTENV_DISABLED" not in selected


def _production_values(**overrides):
    values = dict(deploy.FORCED_SAFE_VALUES)
    values.update({
        "DATABASE_URL": "postgresql://user@127.0.0.1:5434/themisiq",
        "SECRET_KEY": "present",
    })
    values.update(overrides)
    return values


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
    assert any(deploy.ARIA_AUTHORIZATION_OPTION in error for error in errors)
    assert any(deploy.ARIA_ACCEPTANCE_OPTION in error for error in errors)


def test_validate_environment_accepts_exact_explicit_aria_pilot_authorization():
    values = _production_values(
        ARIA_POLICY_AUTHORING_ENABLED="true",
        ARIA_POLICY_AUTHORING_ORG_IDS="12,7",
    )

    errors = deploy.validate_environment(
        values,
        authorized_aria_org_ids=(7, 12),
        accept_aria_known_limitations=True,
    )

    assert errors == []


def test_validate_environment_rejects_mismatched_aria_pilot_authorization():
    values = _production_values(
        ARIA_POLICY_AUTHORING_ENABLED="true",
        ARIA_POLICY_AUTHORING_ORG_IDS="7",
    )

    errors = deploy.validate_environment(
        values,
        authorized_aria_org_ids=(8,),
        accept_aria_known_limitations=True,
    )

    assert any("exactly match" in error for error in errors)


@pytest.mark.parametrize("raw", ["7,abc", "0", "7,7", "7,,8", "*"])
def test_parse_org_id_allowlist_rejects_malformed_or_ambiguous_values(raw):
    with pytest.raises(ValueError):
        deploy.parse_org_id_allowlist(raw, field_name="test allowlist")


def test_validate_environment_rejects_stale_allowlist_while_disabled():
    values = _production_values(
        ARIA_POLICY_AUTHORING_ENABLED="false",
        ARIA_POLICY_AUTHORING_ORG_IDS="7",
    )

    errors = deploy.validate_environment(values)

    assert any("must be empty when authoring is disabled" in error for error in errors)


def test_cli_requires_both_aria_pilot_acknowledgements(capsys):
    rc = deploy.main([deploy.ARIA_AUTHORIZATION_OPTION, "7"])

    assert rc == 2
    assert "requires both" in capsys.readouterr().err


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
        "OPENROUTER_API_KEY=sk-or-v1-test-only\n"
        "SLACK_WEBHOOK_URL=https://hooks.example.invalid/secret\n"
        "ARIA_POLICY_AUTHORING_ENABLED=false\n",
        encoding="utf-8",
    )
    removed = deploy.scrub_legacy_file(legacy)
    assert set(removed) == {
        "SECRET_KEY", "DATABASE_URL", "OPENROUTER_API_KEY", "SLACK_WEBHOOK_URL"
    }
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
        "Environment=PYTHON_DOTENV_DISABLED=1",
        "--host 127.0.0.1", "--workers 1", "NoNewPrivileges=true",
        "PrivateTmp=true", "ProtectSystem=strict",
        "ProtectHome=true", "UMask=0077",
    )
    for marker in required:
        assert marker in unit
    assert "Environment=SECRET_KEY=" not in unit
    assert "--host 0.0.0.0" not in unit
    assert "--workers 2" not in unit


def test_aria_preview_companion_matches_service_account_and_is_isolated():
    compose = (
        Path(__file__).parents[2] / "deploy" / "aria-preview" / "compose.vps.yml"
    ).read_text(encoding="utf-8")

    assert "ARIA_PREVIEW_UID" in compose
    assert "ARIA_PREVIEW_GID" in compose
    assert 'user: "${ARIA_PREVIEW_UID:' in compose
    assert "uid=1001" not in compose
    assert "gid=1001" not in compose
    assert "network_mode: none" in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert "memswap_limit: 1g" in compose
    assert "ports:" not in compose


def _healthy_preview_inspection(spool: Path, *, env=None):
    return [{
        "Config": {
            "Image": "ghcr.io/alimoyo1/themisiq-aria-preview@sha256:" + "a" * 64,
            "User": "1234:5678",
            "Env": env or ["HOME=/home/ariaworker", "PATH=/usr/bin:/bin"],
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "PortBindings": {},
            "RestartPolicy": {"Name": "unless-stopped"},
            "Memory": 1024 * 1024 * 1024,
            "MemorySwap": 1024 * 1024 * 1024,
            "NanoCpus": 1_500_000_000,
            "PidsLimit": 128,
            "Tmpfs": {
                "/tmp": "rw,noexec,nosuid,nodev,size=536870912,uid=1234,gid=5678",
                "/home/ariaworker": (
                    "rw,noexec,nosuid,nodev,size=33554432,uid=1234,gid=5678"
                ),
            },
        },
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "NetworkSettings": {"Ports": {}},
        "Mounts": [
            {"Type": "bind", "Source": str(spool), "Destination": "/spool"},
            {"Type": "tmpfs", "Source": "", "Destination": "/tmp"},
            {"Type": "tmpfs", "Source": "", "Destination": "/home/ariaworker"},
        ],
    }]


def test_aria_preview_runtime_readiness_accepts_hardened_worker(tmp_path, monkeypatch):
    spool = tmp_path.resolve()
    monkeypatch.setattr(
        deploy,
        "verify_aria_preview_spool",
        lambda values, **kwargs: spool,
    )

    def fake_run(args, **kwargs):
        output = "container-id\n" if args[1] == "ps" else json.dumps(
            _healthy_preview_inspection(spool)
        )
        return deploy.subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(deploy, "_run", fake_run)

    deploy.verify_aria_preview_container({}, 1234, 5678)


def test_aria_preview_runtime_readiness_rejects_secret_environment(tmp_path, monkeypatch):
    spool = tmp_path.resolve()
    monkeypatch.setattr(
        deploy,
        "verify_aria_preview_spool",
        lambda values, **kwargs: spool,
    )
    inspection = _healthy_preview_inspection(
        spool,
        env=["HOME=/home/ariaworker", "SECRET_KEY=must-not-be-present"],
    )

    def fake_run(args, **kwargs):
        output = "container-id\n" if args[1] == "ps" else json.dumps(inspection)
        return deploy.subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(deploy, "_run", fake_run)

    with pytest.raises(RuntimeError, match="must not receive secret-bearing"):
        deploy.verify_aria_preview_container({}, 1234, 5678)


def test_aria_preview_runtime_readiness_rejects_untrusted_digest(tmp_path, monkeypatch):
    spool = tmp_path.resolve()
    monkeypatch.setattr(
        deploy,
        "verify_aria_preview_spool",
        lambda values, **kwargs: spool,
    )
    inspection = _healthy_preview_inspection(spool)
    inspection[0]["Config"]["Image"] = "ghcr.io/other/image@sha256:" + "b" * 64

    def fake_run(args, **kwargs):
        output = "container-id\n" if args[1] == "ps" else json.dumps(inspection)
        return deploy.subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(deploy, "_run", fake_run)

    with pytest.raises(RuntimeError, match="tested ThemisIQ GHCR image"):
        deploy.verify_aria_preview_container({}, 1234, 5678)


@pytest.mark.parametrize("missing", ["/tmp", "/home/ariaworker"])
def test_aria_preview_runtime_readiness_requires_both_tmpfs_mounts(
    tmp_path, monkeypatch, missing
):
    spool = tmp_path.resolve()
    monkeypatch.setattr(
        deploy,
        "verify_aria_preview_spool",
        lambda values, **kwargs: spool,
    )
    inspection = _healthy_preview_inspection(spool)
    inspection[0]["HostConfig"]["Tmpfs"].pop(missing)

    def fake_run(args, **kwargs):
        output = "container-id\n" if args[1] == "ps" else json.dumps(inspection)
        return deploy.subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(deploy, "_run", fake_run)

    with pytest.raises(RuntimeError, match="required /tmp"):
        deploy.verify_aria_preview_container({}, 1234, 5678)


def test_aria_preview_runtime_readiness_rejects_swap_above_memory(
    tmp_path, monkeypatch
):
    spool = tmp_path.resolve()
    monkeypatch.setattr(
        deploy,
        "verify_aria_preview_spool",
        lambda values, **kwargs: spool,
    )
    inspection = _healthy_preview_inspection(spool)
    inspection[0]["HostConfig"]["MemorySwap"] = 2 * 1024 * 1024 * 1024

    def fake_run(args, **kwargs):
        output = "container-id\n" if args[1] == "ps" else json.dumps(inspection)
        return deploy.subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(deploy, "_run", fake_run)

    with pytest.raises(RuntimeError, match="swap limit"):
        deploy.verify_aria_preview_container({}, 1234, 5678)


def test_aria_preview_spool_requires_fresh_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setitem(
        deploy.FORCED_SAFE_VALUES,
        "ARIA_POLICY_PREVIEW_SPOOL_DIR",
        str(tmp_path),
    )
    values = {"ARIA_POLICY_PREVIEW_SPOOL_DIR": str(tmp_path)}
    (tmp_path / ".worker.heartbeat").write_text(str(time.time()), encoding="ascii")

    assert deploy.verify_aria_preview_spool(values) == tmp_path

    (tmp_path / ".worker.heartbeat").write_text(
        str(time.time() - deploy.ARIA_PREVIEW_HEARTBEAT_MAX_AGE_SECONDS - 1),
        encoding="ascii",
    )
    with pytest.raises(RuntimeError, match="heartbeat is stale"):
        deploy.verify_aria_preview_spool(values)


def test_aria_preview_spool_rejects_non_file_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setitem(
        deploy.FORCED_SAFE_VALUES,
        "ARIA_POLICY_PREVIEW_SPOOL_DIR",
        str(tmp_path),
    )
    values = {"ARIA_POLICY_PREVIEW_SPOOL_DIR": str(tmp_path)}
    (tmp_path / ".worker.heartbeat").mkdir()

    with pytest.raises(RuntimeError, match="must be a regular file"):
        deploy.verify_aria_preview_spool(values)


def test_aria_preview_release_workflow_tests_before_publishing_digest():
    workflow = (
        Path(__file__).parents[2] / ".github" / "workflows" / "aria-preview-image.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "packages: write" in workflow
    assert "--network none" in workflow
    assert "--cap-drop ALL" in workflow
    assert "--read-only" in workflow
    assert "--once" in workflow and "--healthcheck" in workflow
    assert "real_conversion=PASS" in workflow
    assert workflow.index("real_conversion=PASS") < workflow.index("docker push")
    assert "ARIA_PREVIEW_IMAGE=${image}" in workflow
    assert "OPENROUTER_API_KEY" not in workflow
    assert "DATABASE_URL" not in workflow


def test_dependency_probe_matches_the_non_root_production_runtime(tmp_path, monkeypatch):
    python = tmp_path / "oneforall" / ".venv" / "bin" / "python3"
    python.parent.mkdir(parents=True)
    python.touch()
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return deploy.subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(deploy.subprocess, "run", fake_run)

    deploy.verify_dependencies(
        tmp_path,
        {"SECRET_KEY": "present", "DEBUG": "false"},
        uid=1234,
        gid=5678,
    )

    assert captured["user"] == 1234
    assert captured["group"] == 5678
    assert captured["extra_groups"] == []
    assert captured["umask"] == 0o077
    assert captured["env"]["PYTHON_DOTENV_DISABLED"] == "1"
    assert captured["env"]["HOME"] == "/var/lib/themisiq"
    assert "from config import settings" in captured["args"][-1]


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
