"""PLAN-36 P03: explicit, scoped comparison of retained policy versions."""
from __future__ import annotations

import difflib
import hashlib
import json
import unicodedata
from fastapi.encoders import jsonable_encoder

from modules.aria import policy_workflow_service as svc
from modules.aria.policy_access import document_read_ok

_METADATA_KEYS = (
    "title", "doc_type", "control_ref", "framework_label",
    "effective_date", "review_date",
)
_MAX_TEXT = 200_000
_MAX_DIFF_LINES = 1200


def _normalized_body(value):
    if not value:
        return None, False
    text = unicodedata.normalize("NFC", str(value).replace("\r\n", "\n").replace("\r", "\n"))
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text[:_MAX_TEXT], len(text) > _MAX_TEXT


def _metadata(value):
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return {key: parsed.get(key) for key in _METADATA_KEYS}


def _side(version, approvals):
    body, truncated = _normalized_body(version.get("body"))
    return {
        "version": jsonable_encoder(svc._version_to_public_dict(version)),
        "metadata": _metadata(version.get("metadata_json")),
        "normalized_text": body,
        "normalized_text_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest() if body is not None else None,
        "text_truncated": truncated,
        "approval_history": approvals,
    }


def compare_versions(db, actor, doc_id, left_id, right_id):
    doc_row = db.execute(
        "SELECT id,org_id,business_unit_id,policy_workflow_managed "
        "FROM aria_documents WHERE doc_id=%s", (doc_id,),
    ).fetchone()
    if not doc_row or not document_read_ok(actor, dict(doc_row)):
        raise svc.NotFoundError("Document not found.")
    doc = dict(doc_row)
    left = svc.get_version(db, actor, left_id)
    right = svc.get_version(db, actor, right_id)
    if left["document_id"] != doc["id"] or right["document_id"] != doc["id"]:
        raise svc.NotFoundError("Version not found for this document.")
    history = db.execute(
        "SELECT policy_version_id,round_number,approver_id,decision_by,"
        "status,requested_at,decided_at FROM aria_document_approvals "
        "WHERE document_id=%s AND org_id=%s AND policy_version_id IN (%s,%s) "
        "ORDER BY policy_version_id,round_number",
        (doc["id"], doc["org_id"], left_id, right_id),
    ).fetchall()
    left_history = [jsonable_encoder(dict(r)) for r in history if r["policy_version_id"] == left_id]
    right_history = [jsonable_encoder(dict(r)) for r in history if r["policy_version_id"] == right_id]
    a = _side(left, left_history)
    b = _side(right, right_history)
    if a["normalized_text"] is None or b["normalized_text"] is None:
        diff = None
        diff_truncated = False
    else:
        lines = difflib.unified_diff(
            a["normalized_text"].splitlines(), b["normalized_text"].splitlines(),
            fromfile=f"version {left['version']}", tofile=f"version {right['version']}",
            lineterm="",
        )
        diff = []
        for line in lines:
            if len(diff) >= _MAX_DIFF_LINES:
                break
            diff.append(line)
        # Text truncation is a separate provenance flag; the diff itself is
        # bounded for predictable API responses.
        diff_truncated = len(diff) >= _MAX_DIFF_LINES
    return {
        "document_id": doc["id"], "left": a, "right": b,
        "normalized_diff": diff,
        "diff_truncated": diff_truncated,
        "normalization": "Unicode NFC, LF line endings, trailing line whitespace removed",
    }
