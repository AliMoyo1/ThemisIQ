#!/usr/bin/env python3
"""Install and verify the hardened ThemisIQ systemd service.

The workflow is deliberately staged:

* ``--capture-running-env`` copies configured application variables from the
  healthy running service into a root-only environment file. Values are never
  printed and PLAN-35 authoring is forced off.
* ``--apply`` installs the non-root service. With ``--restart`` it checks both
  health probes and restores the previous unit automatically on failure.
* ``--scrub-legacy-secrets`` removes duplicate secrets from legacy env files
  only after the hardened service is verified.

Without an action the command is read-only. It never installs packages,
changes PostgreSQL, runs migrations directly, or edits the policy-authoring
flags. An already-configured pilot is accepted only when the operator repeats
the exact organization allow-list and explicitly accepts the documented pilot
limitations on both preflight and apply.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_PROJECT_ROOT = Path("/project")
DEFAULT_ENV_FILE = Path("/etc/themisiq/themisiq.env")
DEFAULT_UNIT_FILE = Path("/etc/systemd/system/themisiq-app.service")
SERVICE_NAME = "themisiq-app.service"
SERVICE_USER = "themisiq"
SERVICE_GROUP = "themisiq"

KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
UNIT_ENV_KEY_RE = re.compile(
    r'^\s*Environment\s*=\s*["\']?([A-Z_][A-Z0-9_]*)='
)
DANGEROUS_ENV_KEYS = {
    "BASH_ENV", "ENV", "LD_LIBRARY_PATH", "LD_PRELOAD", "PATH",
    "PYTHONHOME", "PYTHONPATH", "PYTHON_DOTENV_DISABLED",
}
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}
ARIA_AUTHORIZATION_OPTION = "--authorize-aria-policy-authoring-org-ids"
ARIA_ACCEPTANCE_OPTION = "--accept-aria-policy-authoring-known-limitations"
ARIA_PREVIEW_COMPONENT_LABEL = "com.themisiq.component=aria-policy-preview"
ARIA_PREVIEW_IMAGE_PREFIX = "ghcr.io/alimoyo1/themisiq-aria-preview@sha256:"
ARIA_PREVIEW_HEARTBEAT_MAX_AGE_SECONDS = 90
FORCED_SAFE_VALUES = {
    "DEBUG": "false",
    "HOST": "127.0.0.1",
    "PORT": "8080",
    "GRID_BACKUP_JOBS_ENABLED": "false",
    "ARIA_POLICY_AUTHORING_ENABLED": "false",
    "ARIA_POLICY_AUTHORING_ORG_IDS": "",
    "ARIA_UPLOAD_DIR": "/project/oneforall/data/aria_uploads",
    "ARIA_TEMPLATE_DIR": "/project/oneforall/data/aria_templates",
    "ARIA_POLICY_PREVIEW_SPOOL_DIR": "/var/lib/themisiq/preview-spool",
    "EVIDENCE_DIR": "/project/oneforall/data/evidence",
    "GRID_UPLOAD_DIR": "/project/oneforall/data/grid_uploads",
    "REPORTS_DIR": "/project/oneforall/data/reports",
    "BACKUP_PATH": "/project/oneforall/data/backups",
}


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a command without a shell so environment values cannot execute."""
    return subprocess.run(args, check=check, capture_output=True, text=True)


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse the plain KEY=VALUE subset used by the deployment files."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not KEY_RE.fullmatch(key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            parsed = shlex.split(value, posix=True)
            value = parsed[0] if parsed else ""
        values[key] = value
    return values


def parse_proc_environ(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for entry in path.read_bytes().split(b"\0"):
        if not entry or b"=" not in entry:
            continue
        key_raw, value_raw = entry.split(b"=", 1)
        key = key_raw.decode("utf-8", errors="strict")
        if KEY_RE.fullmatch(key):
            values[key] = value_raw.decode("utf-8", errors="strict")
    return values


def parse_unit_environment_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    if not path.is_file():
        return keys
    for line in path.read_text(encoding="utf-8").splitlines():
        match = UNIT_ENV_KEY_RE.match(line)
        if match:
            keys.add(match.group(1))
    return keys


def configured_environment(
    running: dict[str, str],
    legacy_sources: list[dict[str, str]],
    unit_keys: set[str],
) -> dict[str, str]:
    """Select configured app keys, preferring live process values."""
    configured_keys = set(unit_keys)
    legacy_merged: dict[str, str] = {}
    for source in legacy_sources:
        legacy_merged.update(source)
        configured_keys.update(source)
    configured_keys.difference_update(DANGEROUS_ENV_KEYS)

    selected: dict[str, str] = {}
    for key in sorted(configured_keys):
        if key in running:
            selected[key] = running[key]
        elif key in legacy_merged:
            selected[key] = legacy_merged[key]
    selected.update(FORCED_SAFE_VALUES)
    return selected


def parse_org_id_allowlist(raw: str, *, field_name: str) -> tuple[int, ...]:
    """Return a canonical, duplicate-free tuple of positive organization IDs."""
    if not raw.strip():
        return ()

    parsed: list[int] = []
    seen: set[int] = set()
    for item in raw.split(","):
        token = item.strip()
        if not token or not token.isascii() or not token.isdigit():
            raise ValueError(
                f"{field_name} must be a comma-separated list of positive "
                "integer organization IDs"
            )
        value = int(token)
        if value <= 0:
            raise ValueError(f"{field_name} organization IDs must be greater than zero")
        if value in seen:
            raise ValueError(f"{field_name} must not contain duplicate organization IDs")
        seen.add(value)
        parsed.append(value)
    return tuple(sorted(parsed))


def quote_environment_value(value: str) -> str:
    if "\n" in value or "\r" in value or "\0" in value:
        raise ValueError("environment values must not contain newlines or NUL bytes")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def serialize_environment(values: dict[str, str]) -> str:
    lines = [f"{key}={quote_environment_value(values[key])}" for key in sorted(values)]
    return "\n".join(lines) + "\n"


def validate_environment(
    values: dict[str, str],
    *,
    authorized_aria_org_ids: tuple[int, ...] | None = None,
    accept_aria_known_limitations: bool = False,
) -> list[str]:
    errors: list[str] = []
    for key in ("DATABASE_URL", "SECRET_KEY"):
        if not values.get(key):
            errors.append(f"missing required key: {key}")

    database_url = values.get("DATABASE_URL", "")
    if database_url:
        parsed = urllib.parse.urlsplit(database_url)
        if parsed.scheme not in {"postgresql", "postgres"}:
            errors.append("DATABASE_URL must use PostgreSQL in production")
        if not parsed.hostname:
            errors.append("DATABASE_URL must include a database host")
    if values.get("DEBUG", "").lower() not in FALSE_VALUES:
        errors.append("DEBUG must be false in production")

    authoring_raw = values.get("ARIA_POLICY_AUTHORING_ENABLED", "").strip().lower()
    authoring_value_is_valid = authoring_raw in TRUE_VALUES | FALSE_VALUES
    if not authoring_value_is_valid:
        errors.append(
            "ARIA_POLICY_AUTHORING_ENABLED must be an explicit true or false value"
        )
    authoring_enabled = authoring_raw in TRUE_VALUES
    try:
        configured_aria_org_ids = parse_org_id_allowlist(
            values.get("ARIA_POLICY_AUTHORING_ORG_IDS", ""),
            field_name="ARIA_POLICY_AUTHORING_ORG_IDS",
        )
    except ValueError as exc:
        errors.append(str(exc))
        configured_aria_org_ids = ()

    if authoring_value_is_valid and authoring_enabled:
        if not configured_aria_org_ids:
            errors.append(
                "ARIA_POLICY_AUTHORING_ORG_IDS must contain at least one organization "
                "when authoring is enabled"
            )
        if authorized_aria_org_ids is None:
            errors.append(
                "enabled ARIA policy authoring requires explicit "
                f"{ARIA_AUTHORIZATION_OPTION} authorization"
            )
        elif configured_aria_org_ids != authorized_aria_org_ids:
            errors.append(
                "ARIA_POLICY_AUTHORING_ORG_IDS must exactly match the IDs supplied to "
                f"{ARIA_AUTHORIZATION_OPTION}"
            )
        if not accept_aria_known_limitations:
            errors.append(
                "enabled ARIA policy authoring requires explicit "
                f"{ARIA_ACCEPTANCE_OPTION} acknowledgement"
            )
    elif authoring_value_is_valid:
        if configured_aria_org_ids:
            errors.append(
                "ARIA_POLICY_AUTHORING_ORG_IDS must be empty when authoring is disabled"
            )
        if authorized_aria_org_ids is not None or accept_aria_known_limitations:
            errors.append(
                "ARIA policy-authoring authorization was supplied but the secure "
                "environment has authoring disabled"
            )
    if values.get("HOST") != "127.0.0.1":
        errors.append("HOST must be 127.0.0.1 behind the reverse proxy")
    if values.get("PORT") != "8080":
        errors.append("PORT must be 8080 for the configured reverse proxy")
    dangerous = sorted(set(values).intersection(DANGEROUS_ENV_KEYS))
    if dangerous:
        errors.append("dangerous process-control keys are not allowed: " + ", ".join(dangerous))
    return errors


def is_sensitive_key(key: str) -> bool:
    return (
        key in {"DATABASE_URL", "PGPASSWORD"}
        or key.endswith(("_DSN", "_KEY", "_TOKEN", "_PASSWORD", "_PASS", "_SECRET", "_WEBHOOK_URL"))
        or "SECRET" in key
    )


def atomic_write_private(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp.{os.getpid()}")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        if temp.exists():
            temp.unlink()


def require_root() -> None:
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise RuntimeError("this action must run as root on the VPS")


def service_main_pid() -> int:
    result = _run(["systemctl", "show", SERVICE_NAME, "-p", "MainPID", "--value"])
    try:
        pid = int(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("could not determine the running service PID") from exc
    if pid <= 0:
        raise RuntimeError(f"{SERVICE_NAME} is not running")
    return pid


def capture_running_environment(project_root: Path, target: Path, unit_file: Path) -> dict[str, str]:
    require_root()
    pid = service_main_pid()
    running = parse_proc_environ(Path(f"/proc/{pid}/environ"))
    legacy_paths = [project_root / ".env", project_root / "oneforall" / ".env"]
    legacy = [parse_env_file(path) for path in legacy_paths]
    values = configured_environment(running, legacy, parse_unit_environment_keys(unit_file))
    errors = validate_environment(values)
    if errors:
        raise RuntimeError("environment capture refused:\n- " + "\n- ".join(errors))
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    atomic_write_private(target, serialize_environment(values))
    print(f"Captured {len(values)} configured keys in {target} (mode 0600).")
    print("Captured key names: " + ", ".join(sorted(values)))
    return values


def verify_private_file(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"required environment file does not exist: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise RuntimeError(f"{path} must have mode 0600, found {mode:04o}")


def _aria_authoring_enabled(values: dict[str, str]) -> bool:
    return values.get("ARIA_POLICY_AUTHORING_ENABLED", "").strip().lower() in TRUE_VALUES


def existing_service_account() -> tuple[int, int]:
    """Return the existing service UID/GID without mutating a preflight host."""
    import grp
    import pwd

    try:
        account = pwd.getpwnam(SERVICE_USER)
        group = grp.getgrnam(SERVICE_GROUP)
    except KeyError as exc:
        raise RuntimeError(
            f"{SERVICE_USER} service account must exist before ARIA pilot preflight"
        ) from exc
    return account.pw_uid, group.gr_gid


def ensure_service_account() -> tuple[int, int]:
    import grp
    import pwd

    try:
        account = pwd.getpwnam(SERVICE_USER)
    except KeyError:
        _run([
            "useradd", "--system", "--user-group",
            "--home-dir", "/var/lib/themisiq", "--create-home",
            "--shell", "/usr/sbin/nologin", SERVICE_USER,
        ])
        account = pwd.getpwnam(SERVICE_USER)
    group = grp.getgrnam(SERVICE_GROUP)
    return account.pw_uid, group.gr_gid


def verify_aria_preview_spool(
    values: dict[str, str],
    *,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
) -> Path:
    """Require the private production spool and a fresh worker heartbeat."""
    configured = Path(values.get("ARIA_POLICY_PREVIEW_SPOOL_DIR", ""))
    expected = Path(FORCED_SAFE_VALUES["ARIA_POLICY_PREVIEW_SPOOL_DIR"])
    if not configured.is_absolute() or configured != expected:
        raise RuntimeError(
            "ARIA_POLICY_PREVIEW_SPOOL_DIR must use the hardened production path "
            f"{expected}"
        )
    if configured.is_symlink():
        raise RuntimeError("ARIA preview spool must not be a symlink")
    if not configured.is_dir():
        raise RuntimeError(f"ARIA preview spool does not exist: {configured}")
    if os.name == "posix":
        spool_stat = configured.stat()
        mode = stat.S_IMODE(spool_stat.st_mode)
        if mode & 0o007:
            raise RuntimeError(
                f"ARIA preview spool must not grant access to other users (mode {mode:04o})"
            )
        if (
            expected_uid is not None
            and expected_gid is not None
            and (spool_stat.st_uid, spool_stat.st_gid) != (expected_uid, expected_gid)
        ):
            raise RuntimeError(
                "ARIA preview spool ownership does not match the app service UID/GID"
            )

    heartbeat = configured / ".worker.heartbeat"
    if heartbeat.is_symlink() or not heartbeat.is_file():
        raise RuntimeError("ARIA preview worker heartbeat must be a regular file")
    if os.name == "posix" and expected_uid is not None and expected_gid is not None:
        heartbeat_stat = heartbeat.stat()
        if (heartbeat_stat.st_uid, heartbeat_stat.st_gid) != (
            expected_uid,
            expected_gid,
        ):
            raise RuntimeError(
                "ARIA preview worker heartbeat ownership does not match the app "
                "service UID/GID"
            )
    try:
        heartbeat_age = time.time() - float(heartbeat.read_text(encoding="ascii"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("ARIA preview worker heartbeat is missing or invalid") from exc
    if heartbeat_age < 0 or heartbeat_age > ARIA_PREVIEW_HEARTBEAT_MAX_AGE_SECONDS:
        raise RuntimeError(
            f"ARIA preview worker heartbeat is stale ({heartbeat_age:.0f}s old)"
        )
    return configured


def verify_aria_preview_container(
    values: dict[str, str],
    uid: int,
    gid: int,
) -> None:
    """Inspect the one running converter and enforce its isolation contract."""
    spool = verify_aria_preview_spool(
        values,
        expected_uid=uid,
        expected_gid=gid,
    ).resolve()
    result = _run([
        "docker", "ps",
        "--filter", f"label={ARIA_PREVIEW_COMPONENT_LABEL}",
        "--format", "{{.ID}}",
    ])
    container_ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(container_ids) != 1:
        raise RuntimeError(
            "exactly one running ARIA preview worker is required; "
            f"found {len(container_ids)}"
        )

    inspect_result = _run(["docker", "inspect", container_ids[0]])
    try:
        documents = json.loads(inspect_result.stdout)
        inspection = documents[0]
    except (json.JSONDecodeError, IndexError, TypeError, KeyError) as exc:
        raise RuntimeError("could not inspect the ARIA preview worker") from exc

    config = inspection.get("Config") or {}
    host = inspection.get("HostConfig") or {}
    state = inspection.get("State") or {}
    network = inspection.get("NetworkSettings") or {}

    image = str(config.get("Image") or "")
    if not re.fullmatch(
        re.escape(ARIA_PREVIEW_IMAGE_PREFIX) + r"[0-9a-f]{64}", image
    ):
        raise RuntimeError(
            "ARIA preview worker must use the tested ThemisIQ GHCR image by digest"
        )
    if str(config.get("User") or "") != f"{uid}:{gid}":
        raise RuntimeError("ARIA preview worker UID/GID does not match the app service")
    if not state.get("Running") or (state.get("Health") or {}).get("Status") != "healthy":
        raise RuntimeError("ARIA preview worker is not running and healthy")
    if host.get("NetworkMode") != "none":
        raise RuntimeError("ARIA preview worker network mode must be none")
    if not host.get("ReadonlyRootfs"):
        raise RuntimeError("ARIA preview worker root filesystem must be read-only")
    if host.get("Privileged"):
        raise RuntimeError("ARIA preview worker must not be privileged")
    if host.get("Devices") or host.get("DeviceRequests"):
        raise RuntimeError("ARIA preview worker must not receive host devices")
    if "ALL" not in {str(item).upper() for item in (host.get("CapDrop") or [])}:
        raise RuntimeError("ARIA preview worker must drop all Linux capabilities")
    if not any(
        str(item).startswith("no-new-privileges")
        for item in (host.get("SecurityOpt") or [])
    ):
        raise RuntimeError("ARIA preview worker must enforce no-new-privileges")
    if host.get("PortBindings") or network.get("Ports"):
        raise RuntimeError("ARIA preview worker must not publish network ports")
    if (host.get("RestartPolicy") or {}).get("Name") != "unless-stopped":
        raise RuntimeError("ARIA preview worker restart policy must be unless-stopped")

    limits = (
        ("memory", int(host.get("Memory") or 0), 1024 * 1024 * 1024),
        ("CPU", int(host.get("NanoCpus") or 0), 1_500_000_000),
        ("PID", int(host.get("PidsLimit") or 0), 128),
    )
    for label, configured, maximum in limits:
        if configured <= 0 or configured > maximum:
            raise RuntimeError(
                f"ARIA preview worker {label} limit must be set and no greater than {maximum}"
            )
    memory_swap = int(host.get("MemorySwap") or 0)
    memory_limit = int(host.get("Memory") or 0)
    if memory_swap <= 0 or memory_swap > memory_limit:
        raise RuntimeError(
            "ARIA preview worker swap limit must be set and no greater than its "
            "memory limit"
        )

    mounts = inspection.get("Mounts") or []
    allowed_destinations = {"/spool", "/tmp", "/home/ariaworker"}
    destinations = {str(mount.get("Destination") or "") for mount in mounts}
    if not destinations or not destinations.issubset(allowed_destinations):
        raise RuntimeError("ARIA preview worker has an unexpected filesystem mount")
    spool_mounts = [mount for mount in mounts if mount.get("Destination") == "/spool"]
    if len(spool_mounts) != 1 or spool_mounts[0].get("Type") != "bind":
        raise RuntimeError("ARIA preview worker must have one bind-mounted /spool")
    try:
        mounted_source = Path(str(spool_mounts[0].get("Source") or "")).resolve()
    except (OSError, RuntimeError) as exc:
        raise RuntimeError("ARIA preview worker spool source is invalid") from exc
    if mounted_source != spool:
        raise RuntimeError("ARIA preview worker is mounted to the wrong spool directory")

    required_tmpfs = {"/tmp", "/home/ariaworker"}
    tmpfs = host.get("Tmpfs") or {}
    if not isinstance(tmpfs, dict) or set(tmpfs) != required_tmpfs:
        raise RuntimeError(
            "ARIA preview worker must have only the required /tmp and "
            "/home/ariaworker tmpfs mounts"
        )
    required_tmpfs_options = {
        "rw", "noexec", "nosuid", "nodev", f"uid={uid}", f"gid={gid}"
    }
    for destination, raw_options in tmpfs.items():
        options = {item.strip() for item in str(raw_options).split(",") if item.strip()}
        if not required_tmpfs_options.issubset(options):
            raise RuntimeError(
                f"ARIA preview worker tmpfs {destination} is missing required "
                "security or ownership options"
            )

    for item in config.get("Env") or []:
        key = str(item).split("=", 1)[0]
        if is_sensitive_key(key):
            raise RuntimeError(
                f"ARIA preview worker must not receive secret-bearing variable {key}"
            )


def chown_tree(path: Path, uid: int, gid: int) -> None:
    if path.is_symlink():
        raise RuntimeError(f"refusing to change ownership through symlink: {path}")
    path.mkdir(mode=0o750, parents=True, exist_ok=True)
    for root, directories, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        os.chown(root_path, uid, gid, follow_symlinks=False)
        for name in directories:
            child = root_path / name
            if not child.is_symlink():
                os.chown(child, uid, gid, follow_symlinks=False)
        for name in files:
            child = root_path / name
            if not child.is_symlink():
                os.chown(child, uid, gid, follow_symlinks=False)


def service_template_path(project_root: Path) -> Path:
    return project_root / "oneforall" / "scripts" / "systemd" / SERVICE_NAME


def verify_dependencies(
    project_root: Path,
    values: dict[str, str],
    uid: int,
    gid: int,
) -> None:
    """Import production dependencies and configuration as the service user."""
    python = project_root / "oneforall" / ".venv" / "bin" / "python3"
    if not python.is_file():
        raise RuntimeError(f"production virtualenv Python is missing: {python}")
    probe_code = (
        "import fastapi, uvicorn, psycopg2, dotenv, jinja2, multipart, bcrypt, "
        "docx, apscheduler, alembic, itsdangerous, httpx, aiofiles, openpyxl, reportlab; "
        "from config import settings"
    )
    environment = {
        **values,
        "HOME": "/var/lib/themisiq",
        "LANG": "C.UTF-8",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHON_DOTENV_DISABLED": "1",
    }
    result = subprocess.run(
        [str(python), "-c", probe_code],
        cwd=project_root / "oneforall",
        env=environment,
        capture_output=True,
        text=True,
        user=uid,
        group=gid,
        extra_groups=[],
        umask=0o077,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "production service-user dependency/configuration check failed"
        )


def _lock_down_tree(path: Path) -> None:
    os.chmod(path, 0o700)
    for root, directories, files in os.walk(path, followlinks=False):
        for name in directories:
            os.chmod(Path(root) / name, 0o700, follow_symlinks=False)
        for name in files:
            os.chmod(Path(root) / name, 0o600, follow_symlinks=False)


def install_unit(project_root: Path, unit_file: Path) -> tuple[Path | None, Path | None]:
    template = service_template_path(project_root)
    if not template.is_file():
        raise RuntimeError(f"service template is missing: {template}")
    _run(["systemd-analyze", "verify", str(template)])

    rollback_dir = Path("/root/themisiq-rollbacks")
    rollback_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(rollback_dir, 0o700)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup: Path | None = None
    if unit_file.exists():
        backup = rollback_dir / f"{SERVICE_NAME}.{stamp}"
        shutil.copy2(unit_file, backup)
        os.chmod(backup, 0o600)

    dropin_dir = unit_file.parent / f"{unit_file.name}.d"
    dropin_backup: Path | None = None
    if dropin_dir.is_dir():
        dropin_backup = rollback_dir / f"{SERVICE_NAME}.d.{stamp}"
        shutil.copytree(dropin_dir, dropin_backup)
        _lock_down_tree(dropin_backup)

    temp = unit_file.with_name(unit_file.name + ".new")
    try:
        shutil.copyfile(template, temp)
        os.chmod(temp, 0o644)
        os.replace(temp, unit_file)
        if dropin_dir.is_dir():
            shutil.rmtree(dropin_dir)
    except Exception:
        temp.unlink(missing_ok=True)
        restore_unit(unit_file, backup, dropin_backup)
        raise
    return backup, dropin_backup


def restore_unit(
    unit_file: Path,
    backup: Path | None,
    dropin_backup: Path | None,
) -> None:
    if backup and backup.exists():
        shutil.copy2(backup, unit_file)
    else:
        unit_file.unlink(missing_ok=True)
    dropin_dir = unit_file.parent / f"{unit_file.name}.d"
    if dropin_dir.exists():
        shutil.rmtree(dropin_dir)
    if dropin_backup and dropin_backup.is_dir():
        shutil.copytree(dropin_backup, dropin_dir)


def probe(url: str, expected: bytes, attempts: int = 20) -> None:
    last_error = "no response"
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                body = response.read()
                if response.status == 200 and expected in body:
                    return
                last_error = f"HTTP {response.status}: {body[:120]!r}"
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"probe failed for {url}: {last_error}")


def verify_runtime() -> None:
    active = _run(["systemctl", "is-active", SERVICE_NAME], check=False)
    if active.stdout.strip() != "active":
        raise RuntimeError(f"{SERVICE_NAME} is not active")
    user = _run(["systemctl", "show", SERVICE_NAME, "-p", "User", "--value"])
    if user.stdout.strip() != SERVICE_USER:
        raise RuntimeError(f"{SERVICE_NAME} is not running as {SERVICE_USER}")
    probe("http://127.0.0.1:8080/health", b'"status":"ok"')
    probe("http://127.0.0.1:8080/ready", b'"status":"ready"')


def apply_service(
    project_root: Path,
    env_file: Path,
    unit_file: Path,
    restart: bool,
    *,
    authorized_aria_org_ids: tuple[int, ...] | None = None,
    accept_aria_known_limitations: bool = False,
) -> None:
    require_root()
    verify_private_file(env_file)
    values = parse_env_file(env_file)
    errors = validate_environment(
        values,
        authorized_aria_org_ids=authorized_aria_org_ids,
        accept_aria_known_limitations=accept_aria_known_limitations,
    )
    if errors:
        raise RuntimeError("deployment refused:\n- " + "\n- ".join(errors))

    uid, gid = ensure_service_account()
    verify_dependencies(project_root, values, uid, gid)
    data_dir = project_root / "oneforall" / "data"
    state_dir = Path("/var/lib/themisiq")
    chown_tree(data_dir, uid, gid)
    chown_tree(state_dir, uid, gid)
    for directory in (
        data_dir / "aria_uploads",
        data_dir / "aria_templates",
        data_dir / "aria_preview_spool",
        data_dir / "backups",
        data_dir / "evidence",
        data_dir / "grid_uploads",
        data_dir / "reports",
        state_dir / "preview-spool",
    ):
        directory.mkdir(mode=0o750, parents=True, exist_ok=True)
        os.chown(directory, uid, gid)

    if _aria_authoring_enabled(values):
        verify_aria_preview_container(values, uid, gid)

    backup, dropin_backup = install_unit(project_root, unit_file)
    _run(["systemctl", "daemon-reload"])
    try:
        _run(["systemctl", "restart", SERVICE_NAME])
        verify_runtime()
    except Exception:
        restore_unit(unit_file, backup, dropin_backup)
        _run(["systemctl", "daemon-reload"], check=False)
        _run(["systemctl", "restart", SERVICE_NAME], check=False)
        raise

    print(f"{SERVICE_NAME} passed /health and /ready as user {SERVICE_USER}.")
    if backup:
        print(f"Rollback unit retained at {backup} (mode 0600).")
    if dropin_backup:
        print(f"Rollback drop-ins retained at {dropin_backup} (root-only).")


def scrub_legacy_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    kept: list[str] = []
    removed: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if KEY_RE.fullmatch(key) and is_sensitive_key(key):
                removed.append(key)
                continue
        kept.append(raw_line)
    content = "\n".join(kept)
    if content:
        content += "\n"
    atomic_write_private(path, content)
    return removed


def scrub_legacy_secrets(project_root: Path, env_file: Path) -> None:
    require_root()
    verify_private_file(env_file)
    verify_runtime()
    for path in (project_root / ".env", project_root / "oneforall" / ".env"):
        removed = scrub_legacy_file(path)
        if removed:
            print(f"Removed secret-bearing keys from {path}: {', '.join(sorted(removed))}")
        else:
            print(f"No secret-bearing keys found in {path}.")


def preflight(
    project_root: Path,
    env_file: Path,
    unit_file: Path,
    *,
    authorized_aria_org_ids: tuple[int, ...] | None = None,
    accept_aria_known_limitations: bool = False,
) -> None:
    print(f"Project root: {project_root}")
    print(f"Secure environment: {env_file}")
    print(f"Service unit: {unit_file}")
    if env_file.exists():
        mode = stat.S_IMODE(env_file.stat().st_mode)
        values = parse_env_file(env_file)
        print(f"Environment mode: {mode:04o}; configured keys: {len(values)}")
        errors = validate_environment(
            values,
            authorized_aria_org_ids=authorized_aria_org_ids,
            accept_aria_known_limitations=accept_aria_known_limitations,
        )
        if errors:
            raise RuntimeError("preflight failed:\n- " + "\n- ".join(errors))
        if _aria_authoring_enabled(values):
            uid, gid = existing_service_account()
            verify_aria_preview_container(values, uid, gid)
            print("ARIA preview worker readiness: PASS")
    else:
        print("Secure environment has not been captured yet.")
    template = service_template_path(project_root)
    if not template.is_file():
        raise RuntimeError(f"service template is missing: {template}")
    print("Preflight completed without modifying the host.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--unit-file", type=Path, default=DEFAULT_UNIT_FILE)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--capture-running-env", action="store_true")
    actions.add_argument("--apply", action="store_true")
    actions.add_argument("--scrub-legacy-secrets", action="store_true")
    parser.add_argument(
        "--restart", action="store_true",
        help="with --apply, restart and verify; otherwise install without restart",
    )
    parser.add_argument(
        ARIA_AUTHORIZATION_OPTION,
        metavar="ORG_ID[,ORG_ID...]",
        help=(
            "authorize the exact non-empty organization allow-list already present "
            "in the secure environment; does not edit the environment"
        ),
    )
    parser.add_argument(
        ARIA_ACCEPTANCE_OPTION,
        action="store_true",
        help=(
            "acknowledge the documented unresolved ARIA pilot limitations; required "
            "with --authorize-aria-policy-authoring-org-ids"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.restart and not args.apply:
        print("ERROR: --restart requires --apply", file=sys.stderr)
        return 2
    if args.apply and not args.restart:
        print("ERROR: --apply requires explicit --restart", file=sys.stderr)
        return 2
    authorization_raw = args.authorize_aria_policy_authoring_org_ids
    authorization_is_incomplete = (
        authorization_raw is None
        and args.accept_aria_policy_authoring_known_limitations
    ) or (
        authorization_raw is not None
        and not args.accept_aria_policy_authoring_known_limitations
    )
    if authorization_is_incomplete:
        print(
            "ERROR: ARIA pilot authorization requires both "
            f"{ARIA_AUTHORIZATION_OPTION} and {ARIA_ACCEPTANCE_OPTION}",
            file=sys.stderr,
        )
        return 2
    if authorization_raw is not None and (
        args.capture_running_env or args.scrub_legacy_secrets
    ):
        print(
            "ERROR: ARIA pilot authorization is valid only for preflight or --apply",
            file=sys.stderr,
        )
        return 2
    project_root = args.project_root.resolve()
    env_file = args.env_file.resolve()
    unit_file = args.unit_file.resolve()
    try:
        authorized_aria_org_ids = None
        if authorization_raw is not None:
            authorized_aria_org_ids = parse_org_id_allowlist(
                authorization_raw,
                field_name=ARIA_AUTHORIZATION_OPTION,
            )
            if not authorized_aria_org_ids:
                raise ValueError(
                    f"{ARIA_AUTHORIZATION_OPTION} requires at least one organization ID"
                )
        if args.capture_running_env:
            capture_running_environment(project_root, env_file, unit_file)
        elif args.apply:
            apply_service(
                project_root,
                env_file,
                unit_file,
                args.restart,
                authorized_aria_org_ids=authorized_aria_org_ids,
                accept_aria_known_limitations=(
                    args.accept_aria_policy_authoring_known_limitations
                ),
            )
        elif args.scrub_legacy_secrets:
            scrub_legacy_secrets(project_root, env_file)
        else:
            preflight(
                project_root,
                env_file,
                unit_file,
                authorized_aria_org_ids=authorized_aria_org_ids,
                accept_aria_known_limitations=(
                    args.accept_aria_policy_authoring_known_limitations
                ),
            )
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
