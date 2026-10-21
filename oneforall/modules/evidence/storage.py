"""Vault file preparation shared by module upload adapters.

The database row is created by the caller in the same transaction as its
module reference. This module only validates and writes one immutable file.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path


BLOCKED_EXTENSIONS = frozenset({
    ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".wsh", ".msi", ".scr", ".com", ".pif", ".hta", ".cpl",
    ".inf", ".reg", ".dll", ".sys", ".drv", ".lnk", ".html", ".htm",
    ".svg", ".xhtml",
})
ALLOWED_MIMES = frozenset({
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-excel", "application/vnd.ms-powerpoint",
    "text/plain", "text/csv", "text/xml", "application/json", "application/xml",
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "application/zip", "application/x-zip-compressed", "application/octet-stream",
})
MAGIC = {
    ".pdf": ((b"%PDF", 0),),
    ".png": ((b"\x89PNG\r\n\x1a\n", 0),),
    ".jpg": ((b"\xff\xd8\xff", 0),), ".jpeg": ((b"\xff\xd8\xff", 0),),
    ".gif": ((b"GIF87a", 0), (b"GIF89a", 0)),
    ".webp": ((b"RIFF", 0),),
    ".docx": ((b"PK\x03\x04", 0), (b"PK\x05\x06", 0)),
    ".xlsx": ((b"PK\x03\x04", 0), (b"PK\x05\x06", 0)),
    ".pptx": ((b"PK\x03\x04", 0), (b"PK\x05\x06", 0)),
    ".zip": ((b"PK\x03\x04", 0), (b"PK\x05\x06", 0), (b"PK\x07\x08", 0)),
    ".doc": ((b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0),),
    ".xls": ((b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0),),
    ".ppt": ((b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0),),
}


def describe(content: bytes, filename: str, mime_type: str | None, *, max_bytes: int) -> dict:
    if not content:
        raise ValueError("Choose a nonempty file")
    if len(content) > max_bytes:
        raise ValueError(f"File too large (max {max_bytes // 1024 // 1024}MB)")
    original = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not original or len(original) > 255 or any(ord(char) < 32 for char in original):
        raise ValueError("Use a file name of at most 255 printable characters")
    extension = Path(original).suffix.lower()
    if extension in BLOCKED_EXTENSIONS:
        raise ValueError("This file type is not permitted")
    mime = (mime_type or "application/octet-stream").lower()
    if mime not in ALLOWED_MIMES:
        raise ValueError("This MIME type is not permitted")
    signatures = MAGIC.get(extension)
    if signatures and not any(content[offset:offset + len(signature)] == signature
                              for signature, offset in signatures):
        raise ValueError("File content does not match its declared type")
    return {"original_name": original, "extension": extension, "mime_type": mime,
            "file_size": len(content), "file_hash": hashlib.sha256(content).hexdigest()}


def write(content: bytes, extension: str) -> tuple[str, Path]:
    root = Path(os.getenv("EVIDENCE_DIR", "data/evidence")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{extension}"
    destination = root / name
    with open(destination, "xb") as output:
        output.write(content)
    return name, destination
