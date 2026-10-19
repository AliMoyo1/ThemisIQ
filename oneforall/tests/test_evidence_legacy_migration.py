"""Historical GRID files and BCM references get a reviewable Vault crosswalk."""
from pathlib import Path

import pytest

from modules.evidence import legacy_migration
from modules.grid.data_service import get_evidence_versions


def _id(db, table, **columns):
    result = db.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(['%s'] * len(columns))})",
        tuple(columns.values()))
    db.commit()
    return result.lastrowid


def _user(db):
    org = _id(db, "organizations", name="Pilot", slug="pilot")
    uid = _id(db, "users", username="reviewer", email="r@example.test",
              full_name="Reviewer", password_hash="x", org_id=org)
    return {"id": uid, "org_id": org, "is_super_admin": True, "roles": ["super_admin"]}


def test_grid_migration_is_idempotent_and_preserves_review(test_db, monkeypatch, tmp_path):
    user = _user(test_db)
    upload_root = tmp_path / "grid_uploads"
    upload_root.mkdir()
    source = upload_root / "old.txt"
    source.write_bytes(b"historic proof")
    monkeypatch.setenv("GRID_UPLOAD_DIR", str(upload_root))
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "vault"))
    audit = _id(test_db, "grid_audits", name="Audit")
    control = _id(test_db, "grid_controls", audit_id=audit, name="Control")
    fid = _id(test_db, "grid_evidence_files", control_id=control, filename="old.txt",
              original_name="old.txt", file_path=str(source), mime_type="text/plain",
              status="Approved", approved_by=user["id"])
    assert legacy_migration.grid_inventory(user)[0]["state"] == "safe_local_file"
    vault = legacy_migration.migrate_grid_file(fid, user)
    assert legacy_migration.migrate_grid_file(fid, user) == vault
    record = test_db.execute("SELECT status,approved_by,file_path FROM grid_evidence_files "
                             "WHERE id=%s", (fid,)).fetchone()
    assert (record["status"], record["approved_by"], record["file_path"]) == (
        "Approved", user["id"], f"vault://{vault}")
    crosswalk = test_db.execute("SELECT legacy_path FROM evidence_file_crosswalk "
                                "WHERE module='grid' AND source_id=%s", (fid,)).fetchone()
    assert crosswalk["legacy_path"] == str(source) and source.read_bytes() == b"historic proof"
    assert len(list((tmp_path / "vault").iterdir())) == 1


def test_grid_rejects_file_outside_approved_root(test_db, monkeypatch, tmp_path):
    user = _user(test_db)
    root = tmp_path / "grid_uploads"
    root.mkdir()
    monkeypatch.setenv("GRID_UPLOAD_DIR", str(root))
    outside = tmp_path / "secret.txt"
    outside.write_text("private")
    audit = _id(test_db, "grid_audits", name="Audit")
    control = _id(test_db, "grid_controls", audit_id=audit, name="Control")
    fid = _id(test_db, "grid_evidence_files", control_id=control, filename="secret.txt",
              original_name="secret.txt", file_path=str(outside))
    assert legacy_migration.grid_inventory(user)[0]["state"] == "manual_review"
    with pytest.raises(ValueError, match="manual review"):
        legacy_migration.migrate_grid_file(fid, user)


def test_grid_version_migration_keeps_review_and_hides_legacy_path(test_db, monkeypatch, tmp_path):
    user = _user(test_db)
    root = tmp_path / "grid_uploads"
    root.mkdir()
    source = root / "prior.pdf"
    source.write_bytes(b"%PDF-1.7 historical")
    monkeypatch.setenv("GRID_UPLOAD_DIR", str(root))
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path / "vault"))
    audit = _id(test_db, "grid_audits", name="History audit")
    control = _id(test_db, "grid_controls", audit_id=audit, name="History control")
    fid = _id(test_db, "grid_evidence_files", control_id=control, filename="current.pdf",
              original_name="current.pdf", file_path="vault://999")
    version = _id(test_db, "grid_evidence_versions", evidence_id=fid, version=1,
                  filename="prior.pdf", original_name="prior.pdf", file_path=str(source),
                  mime_type="application/pdf", status="Approved", approved_by=user["id"])
    public = get_evidence_versions(fid, user["org_id"])[0]
    assert "file_path" not in public and public["storage_state"] == "legacy_needs_migration"
    vault_id = legacy_migration.migrate_grid_version(version, user)
    assert legacy_migration.migrate_grid_version(version, user) == vault_id
    row = test_db.execute("SELECT status, approved_by, file_path FROM grid_evidence_versions "
                          "WHERE id=%s", (version,)).fetchone()
    assert (row["status"], row["approved_by"], row["file_path"]) == (
        "Approved", user["id"], f"vault://{vault_id}")
    artifact = test_db.execute("SELECT status,file_hash FROM evidence_items WHERE id=%s",
                               (vault_id,)).fetchone()
    assert artifact["status"] == "superseded"
    assert source.read_bytes() == b"%PDF-1.7 historical"
    assert len(list((tmp_path / "vault").iterdir())) == 1
    public = get_evidence_versions(fid, user["org_id"])[0]
    assert public["vault_evidence_id"] == vault_id and "file_path" not in public


def test_grid_file_response_uses_storage_state_not_internal_path():
    from modules.grid.routes import _public_grid_file

    legacy = _public_grid_file({"id": 1, "file_path": "C:/private/path.txt"})
    vault = _public_grid_file({"id": 2, "file_path": "vault://12"})
    assert legacy == {"id": 1, "storage_state": "legacy_needs_migration"}
    assert vault == {"id": 2, "storage_state": "vault"}


def test_grid_evidence_collection_is_scoped_to_audit_unit(test_db):
    from modules.grid.data_service import get_all_evidence

    owner = _user(test_db)
    own_unit = _id(test_db, "business_units", name="Own unit")
    other_unit = _id(test_db, "business_units", name="Other unit")
    user = {**owner, "is_super_admin": False, "roles": ["audit_lead"],
            "business_unit_id": own_unit}
    for unit, name in ((own_unit, "visible"), (other_unit, "hidden")):
        audit = _id(test_db, "grid_audits", name=name, business_unit_id=unit)
        control = _id(test_db, "grid_controls", audit_id=audit, name=name)
        _id(test_db, "grid_evidence_files", control_id=control, filename=f"{name}.txt",
            original_name=f"{name}.txt", file_path=f"/private/{name}.txt")
    rows = get_all_evidence(user=user)
    assert [row["original_name"] for row in rows] == ["visible.txt"]


def test_bcm_crosswalk_requires_explicit_visible_vault_item(test_db):
    user = _user(test_db)
    control = _id(test_db, "bcm_compliance_controls", framework="ISO 22301",
                  clause="8.4", title="Continuity proof")
    source = _id(test_db, "bcm_compliance_evidence", control_id=control,
                 title="Old reference", file_path="/client/supplied/path")
    vault = _id(test_db, "evidence_items", title="Reviewed file", org_id=user["org_id"], status="current")
    assert legacy_migration.bcm_inventory(user)[0]["state"] == "manual_review"
    assert legacy_migration.reconcile_bcm_file(source, vault, user) == vault
    assert legacy_migration.reconcile_bcm_file(source, vault, user) == vault
    assert test_db.execute("SELECT file_path FROM bcm_compliance_evidence WHERE id=%s", (source,)).fetchone()[0] == f"vault://{vault}"
    assert test_db.execute("SELECT COUNT(*) FROM evidence_links WHERE evidence_id=%s AND module='bcm'", (vault,)).fetchone()[0] == 1
