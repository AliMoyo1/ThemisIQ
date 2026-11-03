"""Durable staging for the batch queue (plan 22, C10).

A file chosen in the batch queue is sent here first. It is checked the same way an upload is (size, blocked extension,
MIME allowlist, file signature) and, if it passes, kept on the server outside the Vault's own directory under a random
name until the person who staged it files it, discards it, or it expires after seven days. A reload or a lost
connection loses nothing. A file that fails a check is quarantined: the reason and its hash are kept so the person can
see what happened, and its bytes are not. Filing goes through the ordinary upload route, which checks everything
again; nothing here puts a file in the Vault. Only the person who staged a file sees it.
"""
import hashlib
import os
import uuid
from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException

from config import settings
from core.timeutils import utcnow
from database import insert_returning_id

STAGING_DIR = Path(os.getenv("EVIDENCE_STAGING_DIR", "data/evidence_staging"))
KEEP_DAYS = 7
MAX_STAGED = 50
MAX_FILE_SIZE = 100 * 1024 * 1024

# Shared with the upload route, so a staged file and an uploaded one pass exactly the same gates.
# Dangerous executable extensions, including HTML and SVG, which can carry script.
BLOCKED_EXTENSIONS = frozenset({
    ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".msi", ".scr", ".com", ".pif",
    ".hta", ".cpl", ".inf", ".reg", ".dll", ".sys", ".drv", ".lnk", ".html", ".htm", ".svg", ".xhtml",
})
ALLOWED_MIMES = frozenset({
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-excel", "application/vnd.ms-powerpoint",
    "text/plain", "text/csv", "text/xml",
    "application/json", "application/xml",
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "application/zip", "application/x-zip-compressed",
    "application/octet-stream",  # fallback for unknown: the extension check is the primary gate
})


def _table() -> str:
    return "public.evidence_staging" if settings.is_postgres() else "evidence_staging"


def _check(file_name: str, mime: str, content: bytes) -> str:
    """'' when the file may be staged, otherwise why it is quarantined. The same checks as an upload."""
    from modules.evidence.routes import _MAGIC
    ext = Path(file_name).suffix.lower()
    if len(content) > MAX_FILE_SIZE:
        return "The file is larger than 100 MB."
    if ext in BLOCKED_EXTENSIONS:
        return f"File type '{ext}' is not allowed for security reasons."
    if mime not in ALLOWED_MIMES:
        return f"MIME type '{mime}' is not permitted."
    sigs = _MAGIC.get(ext)
    if sigs and not any(content[off: off + len(sig)] == sig for sig, off in sigs):
        return "File content does not match its declared type."
    return ""


def stage(db, user: dict, file_name, mime, content: bytes, filing_scope: str) -> dict:
    """Keep one file for later filing, or quarantine it. The filing scope is checked before any byte is kept."""
    from modules.evidence import company_views
    if not user.get("org_id"):
        raise HTTPException(403, "Your account has no organization to stage evidence for")
    if not isinstance(filing_scope, str) or not filing_scope.strip():
        raise HTTPException(422, "Choose an authorized filing scope.")
    company_views.selected_unit(db, user, filing_scope.strip(), for_filing=True)
    open_count = db.execute(f"SELECT COUNT(*) FROM {_table()} WHERE org_id=%s AND user_id=%s AND status='staged'",
                            (user["org_id"], user["id"])).fetchone()[0]
    if open_count >= MAX_STAGED:
        raise HTTPException(409, f"File or discard staged files first: at most {MAX_STAGED} wait at a time.")
    name = Path(str(file_name or "file")).name[:255] or "file"
    mime = str(mime or "application/octet-stream").lower()[:120]
    reason = _check(name, mime, content)
    stored = None
    if not reason:
        stored = f"{uuid.uuid4().hex}.bin"
        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        (STAGING_DIR / stored).write_bytes(content)
    now = utcnow()
    staged_id = insert_returning_id(
        db, f"INSERT INTO {_table()} (org_id,user_id,filing_scope,file_name,mime_type,file_size,file_hash,stored_name,"
        "status,reason,created_at,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (user["org_id"], user["id"], filing_scope.strip(), name, mime, len(content),
         hashlib.sha256(content).hexdigest(), stored, "quarantined" if reason else "staged", reason or None,
         now.isoformat(), (now + timedelta(days=KEEP_DAYS)).isoformat()))
    return _public(db.execute(f"SELECT * FROM {_table()} WHERE id=%s", (staged_id,)).fetchone())


def _public(row) -> dict:
    return {"id": row["id"], "file_name": row["file_name"], "mime_type": row["mime_type"], "file_size": row["file_size"],
            "file_hash": row["file_hash"], "filing_scope": row["filing_scope"], "status": row["status"],
            "reason": row["reason"], "created_at": row["created_at"], "expires_at": row["expires_at"]}


def listing(db, user: dict) -> "list[dict]":
    """The caller's own staged and quarantined files that have not expired."""
    rows = db.execute(f"SELECT * FROM {_table()} WHERE org_id=%s AND user_id=%s AND status IN ('staged','quarantined') "
                      "AND expires_at>%s ORDER BY id", (user.get("org_id"), user.get("id"), utcnow().isoformat())).fetchall()
    return [_public(r) for r in rows]


def _own(db, user: dict, staged_id: int):
    row = db.execute(f"SELECT * FROM {_table()} WHERE id=%s AND org_id=%s AND user_id=%s",
                     (staged_id, user.get("org_id"), user.get("id"))).fetchone()
    if not row:
        raise HTTPException(404, "Staged file not found")
    return row


def take(db, user: dict, staged_id: int) -> "tuple[dict, bytes]":
    """The caller's own staged file, for the upload route to file. Its hash is checked again."""
    row = _own(db, user, staged_id)
    if row["status"] != "staged" or row["expires_at"] <= utcnow().isoformat() or not row["stored_name"]:
        raise HTTPException(404, "Staged file not found")
    path = (STAGING_DIR / row["stored_name"]).resolve()
    if not path.is_relative_to(STAGING_DIR.resolve()) or not path.is_file():
        raise HTTPException(404, "Staged file not found")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != row["file_hash"]:
        raise HTTPException(409, "The staged file changed on the server; stage it again.")
    return dict(row), content


def mark_filed(db, user: dict, staged_id: int, evidence_id: int) -> None:
    changed = db.execute(f"UPDATE {_table()} SET status='filed',evidence_id=%s WHERE id=%s AND org_id=%s AND user_id=%s "
                         "AND status='staged'", (evidence_id, staged_id, user["org_id"], user["id"])).rowcount
    if changed != 1:
        raise HTTPException(409, "This staged file was already filed or discarded.")


def remove_bytes(stored_name) -> None:
    if stored_name:
        (STAGING_DIR / stored_name).unlink(missing_ok=True)


def discard(db, user: dict, staged_id: int) -> None:
    row = _own(db, user, staged_id)
    if row["status"] not in ("staged", "quarantined"):
        raise HTTPException(404, "Staged file not found")
    db.execute(f"UPDATE {_table()} SET status='discarded' WHERE id=%s AND org_id=%s AND user_id=%s",
               (staged_id, user["org_id"], user["id"]))
    remove_bytes(row["stored_name"])


def sweep(db) -> int:
    """Expire staged files older than the keep period and delete their bytes. For the daily job."""
    rows = db.execute(f"SELECT id, stored_name FROM {_table()} WHERE status IN ('staged','quarantined') AND expires_at<=%s",
                      (utcnow().isoformat(),)).fetchall()
    for row in rows:
        db.execute(f"UPDATE {_table()} SET status='expired' WHERE id=%s", (row["id"],))
        remove_bytes(row["stored_name"])
    return len(rows)
