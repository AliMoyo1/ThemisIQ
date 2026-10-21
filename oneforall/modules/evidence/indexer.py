"""Small, tenant-scoped batches of searchable evidence text.

Files are immutable versions. An index row is searchable only when its stored
hash still equals the evidence row's hash. No document text is sent to a model.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from core.timeutils import utcnow
from database import get_db_background
from modules.evidence.extract_worker import MAX_SOURCE_BYTES, MAX_TEXT_CHARS, SUPPORTED


log = logging.getLogger("evidence.indexer")
INDEXER_VERSION = "1"
EVIDENCE_DIR = Path(os.getenv("EVIDENCE_DIR", "data/evidence"))
_CHILD_TIMEOUT = 20
_MAX_CHILD_OUTPUT = 1_000_000
_STATUSES = frozenset({"indexed", "empty", "unsupported", "failed"})


def indexing_enabled() -> bool:
    """Require both operator opt-in and an available Linux process sandbox."""
    requested = os.getenv("EVIDENCE_TEXT_INDEX_ENABLED", "").strip().lower() in {"1", "true"}
    return requested and sys.platform.startswith("linux") and shutil.which("bwrap") is not None


def _result(status: str, code: str | None = None) -> dict:
    return {"status": status, "error_code": code, "text": "", "segments": []}


def _child(path: Path) -> dict:
    # The child sees only the interpreter, its packages, its own code and this
    # frozen input file. It has no app tree, database URL, network or shell.
    sandbox = shutil.which("bwrap") if sys.platform.startswith("linux") else None
    if not sandbox:
        return _result("failed", "sandbox_unavailable")
    roots = []
    for raw in ("/usr", "/lib", "/lib64", "/bin", sys.base_prefix, sys.prefix):
        root = Path(raw).resolve()
        if root.is_dir() and not any(root == parent or root.is_relative_to(parent) for parent in roots):
            roots.append(root)
    worker = Path(__file__).with_name("extract_worker.py").resolve()
    input_name = "/input" + path.suffix.lower()
    command = [sandbox, "--unshare-all", "--die-with-parent", "--new-session", "--tmpfs", "/tmp",
               "--dev", "/dev", "--proc", "/proc"]
    for root in roots:
        command += ["--ro-bind", str(root), str(root)]
    command += ["--ro-bind", str(worker), "/worker.py", "--ro-bind", str(path), input_name,
                "--chdir", "/", "--setenv", "HOME", "/tmp", "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
                sys.executable, "/worker.py", input_name]
    env = {key: value for key, value in os.environ.items()
           if key.upper() == "PATH"}
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        with tempfile.TemporaryFile() as output:
            completed = subprocess.run(
                command, cwd="/", env=env,
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                timeout=_CHILD_TIMEOUT,
            )
            output.seek(0)
            payload = output.read(_MAX_CHILD_OUTPUT + 1)
    except subprocess.TimeoutExpired:
        return _result("failed", "index_timeout")
    if completed.returncode or len(payload) > _MAX_CHILD_OUTPUT:
        return _result("failed", "index_worker_failed")
    try:
        got = json.loads(payload)
        if got["status"] not in _STATUSES or not isinstance(got["text"], str):
            raise ValueError("invalid extraction result")
        if len(got["text"]) > MAX_TEXT_CHARS or not isinstance(got["segments"], list):
            raise ValueError("oversize extraction result")
        if len(got["segments"]) > 100 or any(
               not isinstance(segment, dict) or not isinstance(segment.get("label"), str)
               or len(segment["label"]) > 100
               or not isinstance(segment.get("start"), int) or not isinstance(segment.get("end"), int)
               or segment["start"] < 0 or segment["end"] > len(got["text"])
               for segment in got["segments"]):
            raise ValueError("invalid extraction segments")
        return got
    except (ValueError, KeyError, TypeError):
        return _result("failed", "index_worker_failed")


def _extract(item: dict) -> dict:
    stored_path = item.get("file_path")
    expected_hash = item.get("file_hash")
    if not stored_path or not expected_hash:
        return _result("unsupported", "file_or_hash_missing")
    root = EVIDENCE_DIR.resolve()
    path = (root / stored_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return _result("failed", "file_missing_or_outside_vault")
    if path.suffix.lower() not in SUPPORTED:
        return _result("unsupported", "format_not_supported")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        return _result("unsupported", "file_too_large")
    # Freeze exactly the bytes whose hash is checked. A changed source cannot
    # turn into different text between the integrity check and parsing.
    with tempfile.TemporaryDirectory(prefix="themisiq-evidence-index-") as work:
        frozen = Path(work) / ("source" + path.suffix.lower())
        digest = hashlib.sha256()
        copied = 0
        with path.open("rb") as source, frozen.open("xb") as target:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                copied += len(block)
                if copied > MAX_SOURCE_BYTES:
                    return _result("unsupported", "file_too_large")
                digest.update(block)
                target.write(block)
        if digest.hexdigest() != expected_hash:
            return _result("failed", "integrity_mismatch")
        return _child(frozen)


def index_batch(org_id: int | None, *, limit: int = 12) -> int:
    """Process at most `limit` rows in the current tenant, without holding a DB connection during parsing."""
    if not indexing_enabled():
        return 0
    db = get_db_background()
    try:
        org_clause = "" if org_id is None else "AND e.org_id = %s "
        params = [] if org_id is None else [org_id]
        rows = db.execute(
            "SELECT e.id,e.org_id,e.business_unit_id,e.file_path,e.file_hash "
            "FROM evidence_items e LEFT JOIN evidence_text_index ti ON ti.evidence_id=e.id "
            "WHERE e.file_path IS NOT NULL AND e.file_path != '' " + org_clause +
            "AND (ti.evidence_id IS NULL OR ti.file_hash != COALESCE(e.file_hash, '') "
            "OR COALESCE(ti.org_id,-1) != COALESCE(e.org_id,-1) "
            "OR COALESCE(ti.business_unit_id,-1) != COALESCE(e.business_unit_id,-1) "
            "OR ti.indexer_version != %s OR (ti.status = 'failed' AND ti.retry_after <= %s)) "
            "ORDER BY e.id LIMIT %s",
            [*params, INDEXER_VERSION, utcnow().isoformat(), min(max(int(limit), 0), 12)],
        ).fetchall()
    finally:
        db.close()
    processed = 0
    for row in rows:
        item = dict(row)
        try:
            result = _extract(item)
        except (OSError, ValueError):
            result = _result("failed", "file_read_failed")
        retry_after = ((utcnow() + timedelta(days=1)).isoformat()
                       if result["status"] == "failed" else None)
        db = get_db_background()
        try:
            latest = db.execute(
                "SELECT org_id,business_unit_id,file_path,file_hash FROM evidence_items WHERE id=%s",
                (item["id"],),
            ).fetchone()
            if not latest or any(latest[key] != item[key] for key in
                                 ("org_id", "business_unit_id", "file_path", "file_hash")):
                continue
            db.execute(
                "INSERT INTO evidence_text_index "
                "(evidence_id,org_id,business_unit_id,file_hash,indexer_version,status,content_text,"
                "segments_json,error_code,retry_after,indexed_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(evidence_id) DO UPDATE SET org_id=excluded.org_id, "
                "business_unit_id=excluded.business_unit_id,file_hash=excluded.file_hash, "
                "indexer_version=excluded.indexer_version,status=excluded.status, "
                "content_text=excluded.content_text,segments_json=excluded.segments_json, "
                "error_code=excluded.error_code,retry_after=excluded.retry_after,indexed_at=excluded.indexed_at",
                (item["id"], item["org_id"], item["business_unit_id"], item["file_hash"] or "",
                 INDEXER_VERSION, result["status"], result["text"], json.dumps(result["segments"]),
                 result.get("error_code"), retry_after, utcnow().isoformat()),
            )
            db.commit()
            processed += 1
        finally:
            db.close()
    return processed


def snippets_for_page(db, rows: list, terms: list[str]) -> dict[int, dict]:
    """Get short passages only for already-scoped list rows; never return full index text."""
    terms = [term.strip()[:200].casefold() for term in terms if term and term.strip()]
    if not rows or not terms:
        return {}
    by_id = {row["id"]: row for row in rows}
    marks = ",".join(["%s"] * len(by_id))
    found = db.execute(
        "SELECT evidence_id,org_id,business_unit_id,file_hash,content_text,segments_json FROM evidence_text_index "
        f"WHERE status='indexed' AND evidence_id IN ({marks})", list(by_id),
    ).fetchall()
    snippets = {}
    for indexed in found:
        item = by_id[indexed["evidence_id"]]
        if (indexed["file_hash"] != item["file_hash"] or indexed["org_id"] != item["org_id"]
                or indexed["business_unit_id"] != item["business_unit_id"]):
            continue
        content = indexed["content_text"]
        folded = content.casefold()
        offsets = [folded.find(term) for term in terms]
        position = next((offset for offset in offsets if offset >= 0), -1)
        if position < 0:
            continue
        try:
            segments = json.loads(indexed["segments_json"])
        except (ValueError, TypeError):
            segments = []
        label = next((s["label"] for s in segments if s["start"] <= position < s["end"]), "Document")
        start = max(0, position - 65)
        end = min(len(content), position + max(len(term) for term in terms) + 95)
        snippets[indexed["evidence_id"]] = {
            "label": label, "text": ("…" if start else "") + content[start:end] + ("…" if end < len(content) else "")}
    return snippets
