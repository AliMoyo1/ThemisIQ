"""Cover-only PDF rendition with independent, presentation-only review."""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import uuid
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.aria import policy_intake as intake
from modules.aria import policy_storage as storage
from modules.aria.policy_access import document_edit_ok, document_read_ok


def _pages_hash(reader, first_body_page: int) -> str:
    digest = hashlib.sha256()
    for page in reader.pages[first_body_page:]:
        stream = page.get_contents()
        content = stream.get_data() if stream else b""
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        # A page's content stream can refer to an image object outside that
        # stream. Compare those bytes too; otherwise an unchanged stream could
        # disguise a missing or substituted diagram in a presentation copy.
        for item in sorted(page.images, key=lambda image: image.name):
            digest.update(item.name.encode("utf-8", errors="replace"))
            digest.update(hashlib.sha256(item.data).digest())
        digest.update(str(tuple(page.mediabox)).encode())
    return digest.hexdigest()


def _source(db, actor, import_id):
    row = intake.get_import(db, actor, import_id)
    if row["state"] != "registered" or row["mime_type"] != intake.MIME[".pdf"]:
        raise intake.IntakeError(409, "Register a PDF original first.")
    if intake.detail(db, actor, import_id)["pending_replacement"]:
        raise intake.IntakeError(409, "Verify the replacement before creating a presentation copy.")
    doc = db.execute("SELECT * FROM aria_documents WHERE id=%s AND org_id=%s",
                     (row["document_id"], row["org_id"])).fetchone()
    if not doc or not document_read_ok(actor, dict(doc)):
        raise intake.IntakeError(404, "Import not found.")
    source = intake._source_path(row)
    if not source.is_file() or storage.sha256_file(source) != row["file_hash"]:
        raise intake.IntakeError(409, "The original changed or is missing.")
    return row, dict(doc), source


def page_count(db, actor, import_id):
    row, _, source = _source(db, actor, import_id)
    try:
        reader = PdfReader(source, strict=True)
        count = len(reader.pages)
    except Exception as exc:
        raise intake.IntakeError(422, "The PDF could not be safely read.") from exc
    if not 1 <= count <= intake.MAX_PAGES:
        raise intake.IntakeError(422, "PDF page count is outside the supported range.")
    return {"pages": count, "source_sha256": row["file_hash"]}


def create(db, actor, import_id, first_body_page):
    row, doc, source = _source(db, actor, import_id)
    if not document_edit_ok(actor, doc):
        raise intake.IntakeError(403, "Policy edit permission required.")
    if not isinstance(first_body_page, int) or isinstance(first_body_page, bool):
        raise intake.IntakeError(422, "Choose the first page of the retained body.")
    reader = PdfReader(source, strict=True)
    if not 1 <= first_body_page < len(reader.pages) <= intake.MAX_PAGES:
        raise intake.IntakeError(422, "Choose a body page after the cover and before the last page.")
    metadata = json.loads(row["reviewed_json"] or "{}")
    if not metadata:
        raise intake.IntakeError(409, "Review the document metadata first.")
    cover = io.BytesIO()
    pdf = canvas.Canvas(cover, pagesize=(612, 792))
    pdf.setTitle(metadata["title"])
    pdf.setFont("Helvetica-Bold", 23)
    title = metadata["title"][:100]
    pdf.drawString(54, 660, title[:48])
    if len(title) > 48:
        pdf.drawString(54, 625, title[48:96])
    pdf.setFont("Helvetica", 12)
    pdf.drawString(54, 565, f"Version: {metadata['version']}")
    pdf.drawString(54, 545, f"Effective date: {metadata.get('effective_date') or 'Pending approval'}")
    pdf.drawString(54, 100, "Presentation copy. Verify against the retained original and approval record.")
    pdf.showPage(); pdf.save(); cover.seek(0)
    writer = PdfWriter()
    writer.add_page(PdfReader(cover).pages[0])
    for page in reader.pages[first_body_page:]:
        writer.add_page(page)
    writer.add_metadata({"/Title": metadata["title"][:180]})
    output = io.BytesIO(); writer.write(output)
    result = PdfReader(io.BytesIO(output.getvalue()), strict=True)
    expected = _pages_hash(reader, first_body_page)
    if _pages_hash(result, 1) != expected:
        raise intake.IntakeError(422, "Retained PDF pages changed during cover replacement.")
    rendition_id = uuid.uuid4().hex
    target = storage._org_root(row["org_id"]) / "renditions" / f"{rendition_id}.pdf"
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
            handle.write(output.getvalue())
        digest = storage.sha256_file(target)
        db.execute("INSERT INTO aria_policy_renditions "
                   "(id,org_id,business_unit_id,import_id,source_version_id,output_path,output_sha256,"
                   "retained_pages_sha256,first_body_page,prepared_by,created_at) "
                   "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                   (rendition_id, row["org_id"], row["business_unit_id"], import_id,
                    row["policy_version_id"], storage.relative_path(target), digest, expected,
                    first_body_page, actor["id"], utcnow().isoformat()))
        db.commit()
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    return {"rendition_id": rendition_id, "state": "pending_review", "pages_retained": len(result.pages) - 1,
            "output_sha256": digest}


def get_rendition(db, actor, import_id, rendition_id):
    row, doc, _ = _source(db, actor, import_id)
    rendition = db.execute("SELECT * FROM aria_policy_renditions WHERE id=%s AND import_id=%s AND org_id=%s",
                           (rendition_id, import_id, row["org_id"])).fetchone()
    if not rendition:
        raise intake.IntakeError(404, "Rendition not found.")
    rendition = dict(rendition)
    if (rendition["state"] != "approved" and actor["id"] != rendition["prepared_by"]
            and not has_capability(actor, "aria.policy.approve")):
        raise intake.IntakeError(404, "Rendition not found.")
    path = storage.resolve_stored_path(rendition["output_path"])
    if not path.is_file() or storage.sha256_file(path) != rendition["output_sha256"]:
        raise intake.IntakeError(409, "Rendition changed or is missing.")
    return rendition, path, doc


def latest(db, actor, import_id):
    row, _, _ = _source(db, actor, import_id)
    matches = db.execute("SELECT id FROM aria_policy_renditions WHERE import_id=%s AND org_id=%s "
                         "ORDER BY created_at DESC LIMIT 10", (import_id, row["org_id"])).fetchall()
    for match in matches:
        try:
            rendition, _, _ = get_rendition(db, actor, import_id, match["id"])
            return {"id": rendition["id"], "state": rendition["state"],
                    "first_body_page": rendition["first_body_page"],
                    "can_decide": rendition["state"] == "pending_review" and
                    actor["id"] != rendition["prepared_by"] and has_capability(actor, "aria.policy.approve")}
        except intake.IntakeError:
            continue
    return None


def decide(db, actor, import_id, rendition_id, approve: bool, note: str):
    rendition, path, doc = get_rendition(db, actor, import_id, rendition_id)
    if rendition["state"] != "pending_review":
        raise intake.IntakeError(409, "Rendition has already been reviewed.")
    if not has_capability(actor, "aria.policy.approve") or actor["id"] == rendition["prepared_by"]:
        raise intake.IntakeError(403, "An independent policy approver must review this rendition.")
    note = note.strip()
    if not note or len(note) > 500:
        raise intake.IntakeError(422, "Enter a concise comparison note.")
    row, _, source = _source(db, actor, import_id)
    original = PdfReader(source, strict=True)
    result = PdfReader(path, strict=True)
    if _pages_hash(original, rendition["first_body_page"]) != rendition["retained_pages_sha256"] or (
            _pages_hash(result, 1) != rendition["retained_pages_sha256"]):
        raise intake.IntakeError(409, "Retained PDF pages no longer match the source.")
    now = utcnow().isoformat()
    copied = None
    if approve:
        from modules.evidence.routes import EVIDENCE_DIR
        EVIDENCE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.pdf"
        copied = EVIDENCE_DIR / name
        try:
            with path.open("rb") as source_file, os.fdopen(
                    os.open(copied, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
                shutil.copyfileobj(source_file, out)
            evidence_id = insert_returning_id(db, "INSERT INTO evidence_items "
                "(title,description,file_path,file_name,file_size,file_hash,mime_type,category,tags,status,"
                "uploaded_by,org_id,business_unit_id,parent_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'policy',%s,'current',%s,%s,%s,%s)",
                (doc["title"], "Reviewed presentation rendition; retained PDF pages match imported original.",
                 name, f"{doc['doc_id']}-presentation.pdf", path.stat().st_size,
                 rendition["output_sha256"], intake.MIME[".pdf"],
                 f"aria,policy,aria_doc_id={doc['id']},rendition={rendition_id}",
                 actor["id"], row["org_id"], row["business_unit_id"], row["evidence_id"]))
            db.execute("INSERT INTO evidence_links (evidence_id,module,entity_type,entity_id,linked_by) "
                       "VALUES (%s,'aria','document',%s,%s)", (evidence_id, doc["id"], actor["id"]))
        except Exception:
            db.rollback()
            copied.unlink(missing_ok=True)
            raise
    else:
        evidence_id = None
    try:
        changed = db.execute("UPDATE aria_policy_renditions SET state=%s,reviewed_by=%s,reviewed_at=%s,"
                             "review_note=%s,evidence_id=%s WHERE id=%s AND state='pending_review'",
                             ("approved" if approve else "rejected", actor["id"], now, note, evidence_id, rendition_id))
        if getattr(changed, "rowcount", 1) != 1:
            raise intake.IntakeError(409, "Rendition has already been reviewed.")
        db.commit()
    except Exception:
        db.rollback()
        if copied is not None:
            copied.unlink(missing_ok=True)
        raise
    return {"state": "approved" if approve else "rejected", "evidence_id": evidence_id}
