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
changes PostgreSQL, runs migrations directly, or enables policy authoring.
"""

from __future__ import annotations

import argparse
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


def quote_environment_value(value: str) -> str:
    if "\n" in value or "\r" in value or "\0" in value:
        raise ValueError("environment values must not contain newlines or NUL bytes")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def serialize_environment(values: dict[str, str]) -> str:
    lines = [f"{key}={quote_environment_value(values[key])}" for key in sorted(values)]
    return "\n".join(lines) + "\n"


def validate_environment(values: dict[str, str]) -> list[str]:
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
    if values.get("DEBUG", "").lower() not in {"false", "0", "no", "off"}:
        errors.append("DEBUG must be false in production")
    if values.get("ARIA_POLICY_AUTHORING_ENABLED", "").lower() not in {
        "false", "0", "no", "off"
    }:
        errors.append("ARIA_POLICY_AUTHORING_ENABLED must be false for deployment")
    if values.get("ARIA_POLICY_AUTHORING_ORG_IDS", "").strip():
        errors.append("ARIA_POLICY_AUTHORING_ORG_IDS must be empty for deployment")
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


def apply_service(project_root: Path, env_file: Path, unit_file: Path, restart: bool) -> None:
    require_root()
    verify_private_file(env_file)
    values = parse_env_file(env_file)
    errors = validate_environment(values)
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


def preflight(project_root: Path, env_file: Path, unit_file: Path) -> None:
    print(f"Project root: {project_root}")
    print(f"Secure environment: {env_file}")
    print(f"Service unit: {unit_file}")
    if env_file.exists():
        mode = stat.S_IMODE(env_file.stat().st_mode)
        values = parse_env_file(env_file)
        print(f"Environment mode: {mode:04o}; configured keys: {len(values)}")
        errors = validate_environment(values)
        if errors:
            raise RuntimeError("preflight failed:\n- " + "\n- ".join(errors))
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.restart and not args.apply:
        print("ERROR: --restart requires --apply", file=sys.stderr)
        return 2
    if args.apply and not args.restart:
        print("ERROR: --apply requires explicit --restart", file=sys.stderr)
        return 2
    project_root = args.project_root.resolve()
    env_file = args.env_file.resolve()
    unit_file = args.unit_file.resolve()
    try:
        if args.capture_running_env:
            capture_running_environment(project_root, env_file, unit_file)
        elif args.apply:
            apply_service(project_root, env_file, unit_file, args.restart)
        elif args.scrub_legacy_secrets:
            scrub_legacy_secrets(project_root, env_file)
        else:
            preflight(project_root, env_file, unit_file)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
