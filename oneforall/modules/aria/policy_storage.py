"""
PLAN-35 T05: private artifact storage and DOCX validation for the ARIA
policy authoring workflow.

Layout (section 7.3), relative to ARIA_UPLOAD_DIR (routes.py's existing
`data/aria_uploads` default, never a new/separate root):

    policy_workflow/
      org_<org_id>/
        staging/<build_uuid>/
        artifacts/<build_uuid>/
          source.docx
          branded.docx
          preview.pdf
          template.docx
        trash/<cleanup_uuid>/

Paths stored in the database are always relative to ARIA_UPLOAD_DIR; the
browser never sees a filesystem path. Every path this module returns is
verified to actually resolve inside the workflow root before being
trusted, via Path.resolve() + is_relative_to(), not a string prefix check
(a string check can be fooled by a sibling directory sharing a prefix,
e.g. "policy_workflow_evil" vs "policy_workflow").
"""
from __future__ import annotations

import hashlib
import os
import stat
import time
import uuid
from pathlib import Path

from modules.aria.routes import ARIA_UPLOAD_DIR
from modules.aria.policy_docx_validation import (
    DocxValidationError, MAX_DOCX_ENTRIES, MAX_DOCX_EXPANSION_RATIO,
    MAX_DOCX_TOTAL_UNCOMPRESSED, validate_docx_stream,
)

WORKFLOW_ROOT = ARIA_UPLOAD_DIR / "policy_workflow"

class PathContainmentError(Exception):
    """Raised when a resolved path would escape the workflow root."""


def _org_root(org_id: int) -> Path:
    return WORKFLOW_ROOT / f"org_{int(org_id)}"


def _verify_contained(path: Path, root: Path) -> Path:
    """Resolve path and prove it is actually inside root. Rejects
    traversal, absolute-path escapes, and symlinks/reparse points that
    point outside root -- resolve() follows symlinks, so a link escaping
    the tree is caught by the is_relative_to check just like a literal
    ../ escape would be."""
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise PathContainmentError(f"{path} resolves outside {root}")
    return resolved_path


def new_staging_dir(org_id: int) -> tuple[str, Path]:
    """Returns (build_uuid, absolute staging path). Caller writes build
    outputs here; call attach_build() to atomically promote to artifacts/."""
    build_id = uuid.uuid4().hex
    staging = _org_root(org_id) / "staging" / build_id
    staging.mkdir(parents=True, exist_ok=True)
    _verify_contained(staging, WORKFLOW_ROOT)
    return build_id, staging


def attach_build(org_id: int, build_id: str) -> Path:
    """Atomically rename staging/<build_id> to artifacts/<build_id> on the
    same volume (os.rename is atomic within one filesystem). Paths become
    immutable once here -- never overwrite an existing artifacts dir in
    place; callers must use a fresh build_id per attempt."""
    staging = _verify_contained(_org_root(org_id) / "staging" / build_id, WORKFLOW_ROOT)
    artifacts = _org_root(org_id) / "artifacts" / build_id
    artifacts.parent.mkdir(parents=True, exist_ok=True)
    if artifacts.exists():
        raise FileExistsError(f"Artifact build {build_id} already attached; use a new build id.")

    # Windows only: a just-created directory can transiently fail to
    # rename with WinError 5 (Access is denied) if antivirus/indexing has
    # it open for scanning for a moment -- observed directly in this
    # project's own test runs (intermittent, same directory succeeds on
    # retry seconds later). Not applicable to this project's actual Linux
    # production target, but retrying briefly costs nothing there either
    # (POSIX rename doesn't hit this error class, so the loop exits on
    # the first attempt).
    last_exc = None
    for attempt in range(5):
        try:
            os.rename(str(staging), str(artifacts))
            last_exc = None
            break
        except PermissionError as exc:
            last_exc = exc
            time.sleep(0.1 * (attempt + 1))
    if last_exc is not None:
        raise last_exc

    return _verify_contained(artifacts, WORKFLOW_ROOT)


def relative_path(absolute: Path) -> str:
    """The exact string stored in the database: relative to ARIA_UPLOAD_DIR,
    forward slashes, never an absolute filesystem path."""
    resolved = _verify_contained(absolute, ARIA_UPLOAD_DIR)
    return resolved.relative_to(ARIA_UPLOAD_DIR.resolve()).as_posix()


def resolve_stored_path(relative: str) -> Path:
    """The inverse of relative_path: turn a stored relative path back into
    an absolute one, refusing anything that isn't actually contained under
    ARIA_UPLOAD_DIR (an absolute path or a ../ escape stored by mistake, or
    tampered with, must never be served)."""
    if os.path.isabs(relative) or ".." in Path(relative).parts:
        raise PathContainmentError(f"Rejected stored path: {relative!r}")
    candidate = ARIA_UPLOAD_DIR / relative
    return _verify_contained(candidate, ARIA_UPLOAD_DIR)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_docx(path: Path) -> None:
    """Validate a stored DOCX. Intake itself validates inside its worker."""
    with path.open("rb") as source:
        validate_docx_stream(source, path.name)


def _list_orphans(org_id: int, referenced_relative_paths: set[str]) -> list[tuple[str, Path]]:
    """Shared by cleanup_dry_run and move_orphans_to_trash: (relative_path,
    absolute_path) for every staging/artifacts entry not referenced by any
    live record."""
    org_root = _org_root(org_id)
    orphans = []
    if org_root.exists():
        for subdir in ("staging", "artifacts"):
            base = org_root / subdir
            if not base.exists():
                continue
            for entry in base.iterdir():
                try:
                    rel = relative_path(entry)
                except PathContainmentError:
                    continue
                if rel not in referenced_relative_paths and not any(
                    ref.startswith(rel + "/") for ref in referenced_relative_paths
                ):
                    orphans.append((rel, entry))
    return orphans


def cleanup_dry_run(org_id: int, referenced_relative_paths: set[str]) -> dict:
    """List (never delete) staging/artifacts entries under this org that
    are not referenced by any live record, for the retention job's dry-run
    mode (section 7.5). Returns counts and paths only, no file contents."""
    orphans = [rel for rel, _ in _list_orphans(org_id, referenced_relative_paths)]
    return {"org_id": org_id, "orphan_count": len(orphans), "orphans": orphans}


def move_orphans_to_trash(org_id: int, referenced_relative_paths: set[str],
                           grace_hours: int) -> list[str]:
    """Moves each orphaned staging/artifacts entry older than grace_hours
    into trash/<same-name>, stamped with a .trashed_at sidecar recording
    when it arrived (section 7.5's 24-hour default grace period before an
    unreferenced directory is even touched, guarding against a build still
    in flight -- a candidate an in-progress request has staged but not yet
    attached). Returns the relative trash paths actually moved."""
    now = time.time()
    cutoff = now - grace_hours * 3600
    moved = []
    for rel, abs_path in _list_orphans(org_id, referenced_relative_paths):
        try:
            mtime = abs_path.stat().st_mtime
        except OSError:
            continue
        if mtime > cutoff:
            continue  # not old enough yet -- may still be an in-progress build

        entry_name = abs_path.name
        trash_dir = _org_root(org_id) / "trash"
        trash_dir.mkdir(parents=True, exist_ok=True)
        dest = trash_dir / entry_name
        if dest.exists():
            dest = trash_dir / f"{entry_name}_{uuid.uuid4().hex[:8]}"
        try:
            os.rename(str(abs_path), str(dest))
        except OSError as exc:
            continue
        try:
            (dest / ".trashed_at").write_text(str(now), encoding="utf-8")
        except OSError:
            pass
        moved.append(relative_path(dest))
    return moved


def purge_expired_trash(org_id: int, retention_days: int) -> list[str]:
    """Permanently deletes trash/<entry> whose .trashed_at sidecar shows it
    has sat longer than retention_days (section 7.5's 7-day default). A
    trash entry with no readable sidecar (should not normally happen) is
    left alone rather than guessed at."""
    import shutil
    trash_dir = _org_root(org_id) / "trash"
    if not trash_dir.exists():
        return []
    now = time.time()
    cutoff = now - retention_days * 86400
    purged = []
    for entry in trash_dir.iterdir():
        sidecar = entry / ".trashed_at"
        try:
            trashed_at = float(sidecar.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        if trashed_at > cutoff:
            continue
        try:
            rel = relative_path(entry)
            shutil.rmtree(entry)
            purged.append(rel)
        except OSError:
            continue
    return purged
