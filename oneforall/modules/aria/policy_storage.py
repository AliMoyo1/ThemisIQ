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
import uuid
import zipfile
from pathlib import Path

from modules.aria.routes import ARIA_UPLOAD_DIR

WORKFLOW_ROOT = ARIA_UPLOAD_DIR / "policy_workflow"

# section 7.2 limits
MAX_DOCX_TOTAL_UNCOMPRESSED = 100 * 1024 * 1024  # 100 MiB
MAX_DOCX_ENTRIES = 2000
MAX_DOCX_EXPANSION_RATIO = 200  # uncompressed / compressed; flags a zip bomb

# The minimum set of members every valid OOXML .docx package must have.
_REQUIRED_OOXML_MEMBERS = {"[Content_Types].xml", "word/document.xml"}

# Presence of any of these is treated as untrusted content this workflow
# must refuse, even though the extension claims .docx.
_DISALLOWED_MEMBER_PREFIXES = (
    "word/vbaProject",       # macro-enabled content (should be .docm, not .docx)
    "word/embeddings/",      # embedded OLE objects
    "word/activeX/",         # embedded ActiveX controls
)


class DocxValidationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


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
    os.rename(str(staging), str(artifacts))
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
    """Raises DocxValidationError on anything untrustworthy. Never raises
    for a legitimately generated or previously-accepted document; this is
    meant to catch a malicious or corrupt upload, not to be a general DOCX
    linter.
    """
    if path.suffix.lower() != ".docx":
        raise DocxValidationError("INVALID_TEMPLATE", "File must have a .docx extension.")

    with open(path, "rb") as f:
        magic = f.read(4)
    if magic != b"PK\x03\x04" and magic != b"PK\x05\x06":  # normal or empty-zip signature
        raise DocxValidationError("INVALID_TEMPLATE", "File is not a valid ZIP/OOXML package.")

    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise DocxValidationError("INVALID_TEMPLATE", "File is not a valid ZIP archive.") from exc

    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_DOCX_ENTRIES:
            raise DocxValidationError(
                "ARCHIVE_TOO_LARGE", f"Archive has {len(infos)} entries, maximum {MAX_DOCX_ENTRIES}."
            )

        total_uncompressed = 0
        names = set()
        for info in infos:
            # Reject encrypted entries outright: general purpose bit 0 set.
            if info.flag_bits & 0x1:
                raise DocxValidationError("INVALID_TEMPLATE", "Encrypted archive entries are not allowed.")

            name = info.filename
            names.add(name)
            # Path traversal / absolute-path entries inside the archive.
            if name.startswith("/") or name.startswith("\\") or ".." in Path(name).parts:
                raise DocxValidationError("INVALID_TEMPLATE", f"Unsafe archive entry path: {name!r}")

            total_uncompressed += info.file_size
            if total_uncompressed > MAX_DOCX_TOTAL_UNCOMPRESSED:
                raise DocxValidationError(
                    "ARCHIVE_TOO_LARGE",
                    f"Uncompressed content exceeds {MAX_DOCX_TOTAL_UNCOMPRESSED} bytes.",
                )
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > MAX_DOCX_EXPANSION_RATIO:
                    raise DocxValidationError(
                        "ARCHIVE_TOO_LARGE",
                        f"Entry {name!r} has a suspicious {ratio:.0f}x expansion ratio.",
                    )

            for bad_prefix in _DISALLOWED_MEMBER_PREFIXES:
                if name.startswith(bad_prefix):
                    raise DocxValidationError(
                        "INVALID_TEMPLATE",
                        f"Disallowed content found ({name!r}): macros, OLE objects and "
                        "ActiveX controls are not accepted.",
                    )

        missing = _REQUIRED_OOXML_MEMBERS - names
        if missing:
            raise DocxValidationError(
                "INVALID_TEMPLATE", f"Not a valid Word document (missing {sorted(missing)})."
            )


def cleanup_dry_run(org_id: int, referenced_relative_paths: set[str]) -> dict:
    """List (never delete) staging/artifacts entries under this org that
    are not referenced by any live record, for the retention job's dry-run
    mode (section 7.5). Returns counts and paths only, no file contents."""
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
                    orphans.append(rel)
    return {"org_id": org_id, "orphan_count": len(orphans), "orphans": orphans}
