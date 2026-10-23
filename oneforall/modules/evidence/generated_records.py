"""File a generated record once per substantive content change.

Current and two preceding copies are prominent in the Vault. Older copies are
archived, never overwritten or silently deleted; a legal hold or later
retention decision can still recover them. A generated link starts pending and
is not automatically accepted as evidence of compliance.
"""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import uuid

from fastapi import HTTPException

from config import settings
from core.report_kit.identity import safe_filename
from database import get_current_org, get_db, insert_returning_id
from modules.governance.entity_scope import describe_record, record_unit


MIME = {"pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
MAX_FILE_SIZE = 100 * 1024 * 1024


def _semantic_hash(report):
    document = asdict(report)
    # A fresh timestamp or a different downloader is not new record content.
    for field in ("generated_at", "generated_by", "exported_at", "exported_by"):
        document["meta"].pop(field, None)
    content = json.dumps(document, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def file_record(user, module, kind, record_id, report, fmt, body, stem):
    """Return (state, Vault ID). The caller has already authorized the export.

    Rechecks the source here so a direct service call cannot file under a hidden
    record. The file is written before the DB commit and removed on failure.
    """
    if fmt not in MIME or not isinstance(body, bytes) or not body or len(body) > MAX_FILE_SIZE:
        raise HTTPException(413, "Generated document is too large or invalid for the Vault")
    db = get_db()
    dest = None
    try:
        key = (module, kind)
        if not describe_record(db, key, record_id, user):
            raise HTTPException(404, "Record not found")
        known, unit = record_unit(db, module, kind, record_id, user=user)
        if not known:
            raise HTTPException(404, "Record not found")
        if settings.is_postgres():
            identity = f"generated:{module}:{kind}:{record_id}:{fmt}".encode("utf-8")
            lock_id = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big", signed=True)
            db.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,)).fetchone()
        semantic = _semantic_hash(report)
        latest = db.execute(
            "SELECT d.sequence, d.evidence_id, d.semantic_hash, e.status "
            "FROM generated_record_documents d JOIN evidence_items e ON e.id=d.evidence_id "
            "WHERE d.source_module=%s AND d.source_type=%s AND d.source_id=%s AND d.file_format=%s "
            "ORDER BY d.sequence DESC LIMIT 1", (module, kind, record_id, fmt),
        ).fetchone()
        if latest and latest["semantic_hash"] == semantic and latest["status"] == "current":
            return "unchanged", latest["evidence_id"]
        sequence = latest["sequence"] + 1 if latest else 1
        root = Path(os.getenv("EVIDENCE_DIR", "data/evidence"))
        root.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}.{fmt}"
        dest = root / stored_name
        with dest.open("xb") as stream:
            stream.write(body)
        file_hash = hashlib.sha256(body).hexdigest()
        filename = safe_filename(stem, fmt, when=report.meta.generated_at)
        if latest and latest["status"] == "current":
            db.execute("UPDATE evidence_items SET status='superseded', updated_at=CURRENT_TIMESTAMP "
                       "WHERE id=%s AND status='current'", (latest["evidence_id"],))
        evidence_id = insert_returning_id(
            db, "INSERT INTO evidence_items "
            "(title, description, file_path, file_name, file_size, file_hash, mime_type, category, tags, "
            "version, parent_id, status, uploaded_by, org_id, owner_user_id, business_unit_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (report.meta.title, "Generated review copy; specialist approval is required before external filing.",
             stored_name, filename, len(body), file_hash, MIME[fmt], "generated_record", "generated,review-copy",
             sequence, latest["evidence_id"] if latest else None, "current", user["id"],
             get_current_org() or user.get("org_id"), user["id"], unit),
        )
        insert_returning_id(
            db, "INSERT INTO generated_record_documents "
            "(source_module, source_type, source_id, file_format, evidence_id, semantic_hash, sequence) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (module, kind, record_id, fmt, evidence_id, semantic, sequence),
        )
        insert_returning_id(
            db, "INSERT INTO evidence_links "
            "(evidence_id, module, entity_type, entity_id, linked_by, review_status) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (evidence_id, module, kind, record_id, user["id"], "pending"),
        )
        # Keep current + two preceding copies in the generated-history area.
        # Older copies retain bytes and audit history, but leave the active list.
        older = db.execute(
            "SELECT evidence_id FROM generated_record_documents "
            "WHERE source_module=%s AND source_type=%s AND source_id=%s AND file_format=%s "
            "AND sequence < %s", (module, kind, record_id, fmt, sequence - 2),
        ).fetchall()
        for row in older:
            db.execute("UPDATE evidence_items SET status='archived', updated_at=CURRENT_TIMESTAMP "
                       "WHERE id=%s AND status='superseded'", (row["evidence_id"],))
        db.commit()
        return "new_version" if latest else "created", evidence_id
    except Exception:
        db.rollback()
        if dest is not None:
            dest.unlink(missing_ok=True)
        raise
    finally:
        db.close()
