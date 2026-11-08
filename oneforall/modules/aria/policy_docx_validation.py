"""Dependency-free OOXML guard shared by policy storage and the isolated parser."""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import BinaryIO


MAX_DOCX_TOTAL_UNCOMPRESSED = 100 * 1024 * 1024
MAX_DOCX_ENTRIES = 2000
MAX_DOCX_EXPANSION_RATIO = 200
_REQUIRED_OOXML_MEMBERS = {"[Content_Types].xml", "word/document.xml"}
_DISALLOWED_MEMBER_PREFIXES = ("word/vbaProject", "word/embeddings/", "word/activeX/")


class DocxValidationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def validate_docx_stream(source: BinaryIO, filename: str) -> None:
    """Reject untrusted OOXML packages before any document library opens them.

    The caller controls where this code executes. The intake path calls it
    only inside the isolated worker, before parsing document content.
    """
    if Path(filename).suffix.lower() != ".docx":
        raise DocxValidationError("INVALID_TEMPLATE", "File must have a .docx extension.")
    if source.read(4) not in (b"PK\x03\x04", b"PK\x05\x06"):
        raise DocxValidationError("INVALID_TEMPLATE", "File is not a valid ZIP/OOXML package.")
    source.seek(0)
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise DocxValidationError("INVALID_TEMPLATE", "File is not a valid ZIP archive.") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_DOCX_ENTRIES:
            raise DocxValidationError("ARCHIVE_TOO_LARGE", f"Archive has {len(infos)} entries, maximum {MAX_DOCX_ENTRIES}.")
        total_uncompressed = 0
        names = set()
        for info in infos:
            if info.flag_bits & 0x1:
                raise DocxValidationError("INVALID_TEMPLATE", "Encrypted archive entries are not allowed.")
            name = info.filename
            names.add(name)
            if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                raise DocxValidationError("INVALID_TEMPLATE", f"Unsafe archive entry path: {name!r}")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_DOCX_TOTAL_UNCOMPRESSED:
                raise DocxValidationError("ARCHIVE_TOO_LARGE", f"Uncompressed content exceeds {MAX_DOCX_TOTAL_UNCOMPRESSED} bytes.")
            if info.compress_size > 0 and info.file_size / info.compress_size > MAX_DOCX_EXPANSION_RATIO:
                ratio = info.file_size / info.compress_size
                raise DocxValidationError("ARCHIVE_TOO_LARGE", f"Entry {name!r} has a suspicious {ratio:.0f}x expansion ratio.")
            for prefix in _DISALLOWED_MEMBER_PREFIXES:
                if name.startswith(prefix):
                    raise DocxValidationError("INVALID_TEMPLATE", f"Disallowed content found ({name!r}): macros, OLE objects and ActiveX controls are not accepted.")
        missing = _REQUIRED_OOXML_MEMBERS - names
        if missing:
            raise DocxValidationError("INVALID_TEMPLATE", f"Not a valid Word document (missing {sorted(missing)}).")
