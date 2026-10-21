"""
PLAN-35 T05: private artifact storage and DOCX validation tests.

Covers path traversal / containment, a real malicious ZIP corpus (bad
signature, path-traversal entry names, disallowed macro/OLE content,
encrypted entries, an actual zip-bomb expansion ratio, entry-count and
size limits), atomicity of the staging-to-artifacts promotion, and hash
correctness.
"""
import io
import os
import zipfile

import pytest
from docx import Document as DocxDocument

from modules.aria import policy_storage as storage


@pytest.fixture(autouse=True)
def _isolated_workflow_root(tmp_path, monkeypatch):
    """Every test gets its own workflow root under tmp_path, never the
    real ARIA_UPLOAD_DIR."""
    root = tmp_path / "aria_uploads"
    monkeypatch.setattr(storage, "ARIA_UPLOAD_DIR", root)
    monkeypatch.setattr(storage, "WORKFLOW_ROOT", root / "policy_workflow")
    yield root


def _real_docx_bytes() -> bytes:
    doc = DocxDocument()
    doc.add_heading("Test Policy", level=1)
    doc.add_paragraph("Body text.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────
# Path containment
# ─────────────────────────────────────────────────────────────────────────

def test_new_staging_dir_is_contained_under_workflow_root():
    build_id, staging = storage.new_staging_dir(org_id=1)
    resolved_root = storage.WORKFLOW_ROOT.resolve()
    assert staging.resolve().is_relative_to(resolved_root)
    assert build_id in str(staging)


def test_relative_path_rejects_a_path_outside_upload_dir(tmp_path):
    outside = tmp_path / "outside_the_tree.txt"
    outside.write_text("x")
    with pytest.raises(storage.PathContainmentError):
        storage.relative_path(outside)


def test_resolve_stored_path_rejects_absolute_path():
    with pytest.raises(storage.PathContainmentError):
        storage.resolve_stored_path("/etc/passwd")


def test_resolve_stored_path_rejects_traversal():
    with pytest.raises(storage.PathContainmentError):
        storage.resolve_stored_path("policy_workflow/../../../etc/passwd")


def test_relative_path_and_resolve_stored_path_round_trip():
    build_id, staging = storage.new_staging_dir(org_id=1)
    f = staging / "source.docx"
    f.write_bytes(b"data")
    rel = storage.relative_path(f)
    assert not os.path.isabs(rel)
    assert ".." not in rel
    resolved = storage.resolve_stored_path(rel)
    assert resolved.resolve() == f.resolve()


# ─────────────────────────────────────────────────────────────────────────
# Atomic staging -> artifacts promotion
# ─────────────────────────────────────────────────────────────────────────

def test_attach_build_moves_staging_to_artifacts():
    build_id, staging = storage.new_staging_dir(org_id=1)
    (staging / "source.docx").write_bytes(b"content")
    artifacts = storage.attach_build(org_id=1, build_id=build_id)
    assert (artifacts / "source.docx").exists()
    assert not staging.exists()


def test_attach_build_retries_past_a_transient_permission_error(monkeypatch):
    """Proves the Windows-transient-lock retry actually retries and
    succeeds, rather than trusting the loop by inspection alone."""
    build_id, staging = storage.new_staging_dir(org_id=1)
    (staging / "source.docx").write_bytes(b"content")

    real_rename = os.rename
    state = {"calls": 0}

    def flaky_rename(src, dst):
        state["calls"] += 1
        if state["calls"] < 3:
            raise PermissionError("simulated transient Windows lock")
        return real_rename(src, dst)

    monkeypatch.setattr(storage.os, "rename", flaky_rename)
    monkeypatch.setattr(storage.time, "sleep", lambda *_: None)  # don't actually wait in tests

    artifacts = storage.attach_build(org_id=1, build_id=build_id)
    assert state["calls"] == 3
    assert (artifacts / "source.docx").exists()


def test_attach_build_gives_up_after_persistent_permission_errors(monkeypatch):
    build_id, staging = storage.new_staging_dir(org_id=1)
    (staging / "source.docx").write_bytes(b"content")

    def always_fails(src, dst):
        raise PermissionError("simulated persistent lock")

    monkeypatch.setattr(storage.os, "rename", always_fails)
    monkeypatch.setattr(storage.time, "sleep", lambda *_: None)

    with pytest.raises(PermissionError):
        storage.attach_build(org_id=1, build_id=build_id)


def test_attach_build_refuses_to_overwrite_an_existing_attachment():
    build_id, staging = storage.new_staging_dir(org_id=1)
    (staging / "source.docx").write_bytes(b"content")
    storage.attach_build(org_id=1, build_id=build_id)

    # Recreate a staging dir with the SAME build_id (simulating a caller bug)
    (storage.WORKFLOW_ROOT / "org_1" / "staging" / build_id).mkdir(parents=True)
    with pytest.raises(FileExistsError):
        storage.attach_build(org_id=1, build_id=build_id)


# ─────────────────────────────────────────────────────────────────────────
# Hashing
# ─────────────────────────────────────────────────────────────────────────

def test_sha256_file_matches_known_hash(tmp_path):
    import hashlib
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello world")
    assert storage.sha256_file(f) == hashlib.sha256(b"hello world").hexdigest()


# ─────────────────────────────────────────────────────────────────────────
# DOCX validation: the real corpus
# ─────────────────────────────────────────────────────────────────────────

def test_valid_docx_passes(tmp_path):
    f = tmp_path / "valid.docx"
    f.write_bytes(_real_docx_bytes())
    storage.validate_docx(f)  # must not raise


def test_wrong_extension_rejected(tmp_path):
    f = tmp_path / "valid.txt"
    f.write_bytes(_real_docx_bytes())
    with pytest.raises(storage.DocxValidationError) as exc_info:
        storage.validate_docx(f)
    assert exc_info.value.code == "INVALID_TEMPLATE"


def test_not_a_zip_rejected(tmp_path):
    f = tmp_path / "fake.docx"
    f.write_bytes(b"This is not a zip file at all, just plain text padding.")
    with pytest.raises(storage.DocxValidationError):
        storage.validate_docx(f)


def test_missing_required_ooxml_members_rejected(tmp_path):
    f = tmp_path / "empty.docx"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("hello.txt", "not a real word document")
    with pytest.raises(storage.DocxValidationError) as exc_info:
        storage.validate_docx(f)
    assert exc_info.value.code == "INVALID_TEMPLATE"


def test_path_traversal_entry_rejected(tmp_path):
    f = tmp_path / "evil.docx"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<document/>")
        zf.writestr("../../../etc/passwd", "pwned")
    with pytest.raises(storage.DocxValidationError):
        storage.validate_docx(f)


def test_absolute_path_entry_rejected(tmp_path):
    f = tmp_path / "evil2.docx"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<document/>")
        zf.writestr("/etc/passwd", "pwned")
    with pytest.raises(storage.DocxValidationError):
        storage.validate_docx(f)


def test_macro_content_rejected(tmp_path):
    f = tmp_path / "macro.docx"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<document/>")
        zf.writestr("word/vbaProject.bin", b"\x00\x01macro-bytes")
    with pytest.raises(storage.DocxValidationError) as exc_info:
        storage.validate_docx(f)
    assert "macro" in exc_info.value.message.lower()


def test_ole_embedding_rejected(tmp_path):
    f = tmp_path / "ole.docx"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<document/>")
        zf.writestr("word/embeddings/oleObject1.bin", b"\x00\x01ole-bytes")
    with pytest.raises(storage.DocxValidationError):
        storage.validate_docx(f)


def test_encrypted_entry_rejected(tmp_path):
    f = tmp_path / "encrypted.docx"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<document/>")
    # Retroactively flip the encryption bit on one entry to simulate an
    # encrypted archive without needing a real crypto-capable zip writer.
    with zipfile.ZipFile(f, "a") as zf:
        pass
    _flip_encryption_bit(f, "word/document.xml")
    with pytest.raises(storage.DocxValidationError) as exc_info:
        storage.validate_docx(f)
    assert exc_info.value.code == "INVALID_TEMPLATE"


def _flip_encryption_bit(path, member_name):
    """Rewrite the local/central-directory flag bits for one entry to set
    the encryption bit, entirely within the zip container -- no external
    crypto library needed just to prove the check works."""
    import struct
    data = bytearray(path.read_bytes())
    # Central directory entries start with signature PK\x01\x02; flag bits
    # are a 2-byte field at offset 8 within each central directory record.
    idx = data.find(b"PK\x01\x02")
    while idx != -1:
        name_len = struct.unpack_from("<H", data, idx + 28)[0]
        name = bytes(data[idx + 46: idx + 46 + name_len])
        if name.decode("utf-8", "replace") == member_name:
            flags = struct.unpack_from("<H", data, idx + 8)[0]
            struct.pack_into("<H", data, idx + 8, flags | 0x1)
            break
        idx = data.find(b"PK\x01\x02", idx + 4)
    path.write_bytes(bytes(data))


def test_too_many_entries_rejected(tmp_path):
    f = tmp_path / "many.docx"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<document/>")
        for i in range(storage.MAX_DOCX_ENTRIES + 1):
            zf.writestr(f"junk/file{i}.txt", "x")
    with pytest.raises(storage.DocxValidationError) as exc_info:
        storage.validate_docx(f)
    assert exc_info.value.code == "ARCHIVE_TOO_LARGE"


def test_zip_bomb_expansion_ratio_rejected(tmp_path):
    f = tmp_path / "bomb.docx"
    huge_compressible = b"0" * (5 * 1024 * 1024)  # 5 MiB of one repeated byte
    with zipfile.ZipFile(f, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<document/>")
        zf.writestr("word/bomb.bin", huge_compressible)
    with pytest.raises(storage.DocxValidationError) as exc_info:
        storage.validate_docx(f)
    assert exc_info.value.code == "ARCHIVE_TOO_LARGE"


# ─────────────────────────────────────────────────────────────────────────
# Cleanup dry-run
# ─────────────────────────────────────────────────────────────────────────

def test_cleanup_dry_run_lists_unreferenced_artifacts_only():
    build_id_a, staging_a = storage.new_staging_dir(org_id=1)
    (staging_a / "source.docx").write_bytes(b"a")
    artifacts_a = storage.attach_build(org_id=1, build_id=build_id_a)
    referenced_rel = storage.relative_path(artifacts_a / "source.docx")

    build_id_b, staging_b = storage.new_staging_dir(org_id=1)
    (staging_b / "source.docx").write_bytes(b"b")
    orphan_artifacts = storage.attach_build(org_id=1, build_id=build_id_b)

    report = storage.cleanup_dry_run(org_id=1, referenced_relative_paths={referenced_rel})
    assert report["org_id"] == 1
    orphan_path_parts = {part for path in report["orphans"] for part in path.split("/")}
    assert build_id_b in orphan_path_parts
    assert build_id_a not in orphan_path_parts
