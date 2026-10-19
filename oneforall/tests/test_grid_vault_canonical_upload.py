"""GRID uploads keep one Vault file while GRID owns its approval verdict."""
from pathlib import Path

import pytest

from modules.grid import data_service as grid


def _id(db, table, **columns):
    result = db.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(['%s'] * len(columns))})",
        tuple(columns.values()),
    )
    db.commit()
    return result.lastrowid


def test_upload_and_replace_keep_one_file_per_vault_version(test_db, monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "vault"))
    org = _id(test_db, "organizations", name="Pilot", slug="pilot")
    uploader = _id(test_db, "users", username="uploader", email="up@example.test",
                   full_name="Uploader", password_hash="x", org_id=org)
    reviewer = _id(test_db, "users", username="reviewer", email="review@example.test",
                   full_name="Reviewer", password_hash="x", org_id=org)
    audit = _id(test_db, "grid_audits", name="Audit")
    control = _id(test_db, "grid_controls", audit_id=audit, name="Control")
    user = {"id": uploader, "org_id": org, "is_super_admin": True, "roles": ["super_admin"]}
    grid_id, first = grid.create_vault_backed_evidence_file(
        {"control_id": control, "original_name": "first.txt", "mime_type": "text/plain"},
        b"first", user)
    row = test_db.execute("SELECT file_path FROM grid_evidence_files WHERE id=%s", (grid_id,)).fetchone()
    assert row["file_path"] == f"vault://{first}"
    test_db.execute("UPDATE grid_evidence_files SET status='Approved', approved_by=%s, "
                    "approved_at=CURRENT_TIMESTAMP WHERE id=%s", (reviewer, grid_id))
    test_db.commit()

    same_grid_id, second = grid.create_vault_backed_evidence_file(
        {"replace_id": grid_id, "control_id": control,
         "original_name": "second.txt", "mime_type": "text/plain"}, b"second", user)
    assert same_grid_id == grid_id and second != first
    assert test_db.execute("SELECT status FROM evidence_items WHERE id=%s", (first,)).fetchone()[0] == "superseded"
    current = test_db.execute("SELECT parent_id,version,file_path FROM evidence_items WHERE id=%s", (second,)).fetchone()
    assert (current["parent_id"], current["version"]) == (first, 2)
    assert (Path(tmp_path / "vault" / current["file_path"])).read_bytes() == b"second"
    history = test_db.execute("SELECT status,approved_by FROM grid_evidence_versions "
                              "WHERE evidence_id=%s", (grid_id,)).fetchone()
    assert (history["status"], history["approved_by"]) == ("Approved", reviewer)
    version = grid.get_evidence_versions(grid_id, org)[0]
    assert version["vault_evidence_id"] == first
    assert version["storage_state"] == "vault" and "file_path" not in version
    current_grid = test_db.execute("SELECT status,approved_by,file_path FROM grid_evidence_files "
                                   "WHERE id=%s", (grid_id,)).fetchone()
    assert (current_grid["status"], current_grid["approved_by"], current_grid["file_path"]) == (
        "Uploaded", None, f"vault://{second}")
    assert len(list((tmp_path / "vault").iterdir())) == 2


def test_upload_rejects_foreign_checklist_and_bad_signature(test_db, monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "vault"))
    org = _id(test_db, "organizations", name="Pilot", slug="pilot")
    uploader = _id(test_db, "users", username="uploader", email="up@example.test",
                   full_name="Uploader", password_hash="x", org_id=org)
    audit = _id(test_db, "grid_audits", name="Audit")
    control = _id(test_db, "grid_controls", audit_id=audit, name="Control")
    other = _id(test_db, "grid_controls", audit_id=audit, name="Other")
    checklist = _id(test_db, "grid_evidence_items", control_id=other, name="Wrong control")
    user = {"id": uploader, "org_id": org, "is_super_admin": True, "roles": ["super_admin"]}
    with pytest.raises(LookupError):
        grid.create_vault_backed_evidence_file(
            {"control_id": control, "evidence_item_id": checklist,
             "original_name": "sample.txt", "mime_type": "text/plain"}, b"ok", user)
    with pytest.raises(ValueError, match="does not match"):
        grid.create_vault_backed_evidence_file(
            {"control_id": control, "original_name": "fake.pdf",
             "mime_type": "application/pdf"}, b"not a pdf", user)
    assert not (tmp_path / "vault").exists()


def test_status_projection_failure_rolls_back_file_and_both_records(test_db, monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "vault"))
    org = _id(test_db, "organizations", name="Rollback pilot", slug="rollback-pilot")
    uploader = _id(test_db, "users", username="rollback-uploader", email="rollback@example.test",
                   full_name="Uploader", password_hash="x", org_id=org)
    audit = _id(test_db, "grid_audits", name="Rollback audit")
    control = _id(test_db, "grid_controls", audit_id=audit, name="Rollback control")
    user = {"id": uploader, "org_id": org, "is_super_admin": True, "roles": ["super_admin"]}

    def broken_status(*_args, **_kwargs):
        raise RuntimeError("status projection failed")

    monkeypatch.setattr(grid, "_auto_status_control", broken_status)
    with pytest.raises(RuntimeError, match="status projection failed"):
        grid.create_vault_backed_evidence_file(
            {"control_id": control, "original_name": "sample.txt", "mime_type": "text/plain"},
            b"proof", user)
    assert test_db.execute("SELECT COUNT(*) FROM grid_evidence_files").fetchone()[0] == 0
    assert test_db.execute("SELECT COUNT(*) FROM evidence_items WHERE org_id=%s", (org,)).fetchone()[0] == 0
    assert not list((tmp_path / "vault").iterdir())


def test_replacing_approved_file_reopens_completed_control(test_db, monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "vault"))
    org = _id(test_db, "organizations", name="Review pilot", slug="review-pilot")
    uploader = _id(test_db, "users", username="review-uploader", email="review-uploader@example.test",
                   full_name="Uploader", password_hash="x", org_id=org)
    audit = _id(test_db, "grid_audits", name="Review audit")
    control = _id(test_db, "grid_controls", audit_id=audit, name="Review control")
    user = {"id": uploader, "org_id": org, "is_super_admin": True, "roles": ["super_admin"]}
    grid_id, _first = grid.create_vault_backed_evidence_file(
        {"control_id": control, "original_name": "first.txt", "mime_type": "text/plain"},
        b"first", user)
    test_db.execute("UPDATE grid_evidence_files SET status='Approved' WHERE id=%s", (grid_id,))
    test_db.commit()
    grid._auto_status_control(test_db, control)
    assert test_db.execute("SELECT status FROM grid_controls WHERE id=%s", (control,)).fetchone()[0] == "Complete"

    grid.create_vault_backed_evidence_file(
        {"replace_id": grid_id, "control_id": control,
         "original_name": "second.txt", "mime_type": "text/plain"}, b"second", user)
    assert test_db.execute("SELECT status FROM grid_controls WHERE id=%s", (control,)).fetchone()[0] == "In Progress"


def test_failed_replacement_preserves_approved_version(test_db, monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "vault"))
    org = _id(test_db, "organizations", name="Preserve pilot", slug="preserve-pilot")
    uploader = _id(test_db, "users", username="preserve-uploader", email="preserve@example.test",
                   full_name="Uploader", password_hash="x", org_id=org)
    audit = _id(test_db, "grid_audits", name="Preserve audit")
    control = _id(test_db, "grid_controls", audit_id=audit, name="Preserve control")
    user = {"id": uploader, "org_id": org, "is_super_admin": True, "roles": ["super_admin"]}
    grid_id, first = grid.create_vault_backed_evidence_file(
        {"control_id": control, "original_name": "first.txt", "mime_type": "text/plain"},
        b"first", user)
    test_db.execute("UPDATE grid_evidence_files SET status='Approved' WHERE id=%s", (grid_id,))
    test_db.commit()
    before = {path.name for path in (tmp_path / "vault").iterdir()}

    def broken_status(*_args, **_kwargs):
        raise RuntimeError("status projection failed")

    monkeypatch.setattr(grid, "_auto_status_control", broken_status)
    with pytest.raises(RuntimeError, match="status projection failed"):
        grid.create_vault_backed_evidence_file(
            {"replace_id": grid_id, "control_id": control,
             "original_name": "second.txt", "mime_type": "text/plain"}, b"second", user)
    assert tuple(test_db.execute("SELECT status,file_path FROM grid_evidence_files WHERE id=%s", (grid_id,)).fetchone()) == (
        "Approved", f"vault://{first}")
    assert test_db.execute("SELECT status FROM evidence_items WHERE id=%s", (first,)).fetchone()[0] == "current"
    assert test_db.execute("SELECT COUNT(*) FROM grid_evidence_versions WHERE evidence_id=%s", (grid_id,)).fetchone()[0] == 0
    assert test_db.execute("SELECT COUNT(*) FROM evidence_items WHERE org_id=%s", (org,)).fetchone()[0] == 1
    assert {path.name for path in (tmp_path / "vault").iterdir()} == before
