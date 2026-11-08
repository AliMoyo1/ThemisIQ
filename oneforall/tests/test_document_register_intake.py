"""Workbook rows are review claims, never approved policies or control mappings."""
from io import BytesIO
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from modules.aria import document_register_intake as intake


USER = {"id": 1, "org_id": 1, "roles": ["super_admin"], "is_super_admin": True,
        "username": "admin", "full_name": "Admin"}


def _book(*, formula=False):
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Document Register"
    sheet.append(["IMS-OMNI-R029 | Document Register"])
    sheet.append(["Integrated Register · Version 3.9"])
    sheet.append(list(intake.HEADINGS))
    sheet.append(["SECTION: POLICIES"])
    sheet.append([1, "IMS-OMNI-P001", "Information Security Policy", "Policy", "2.0", "2026-01-01",
                  "2026-01-01", "2027-01-01", "Current", "Owner", "A.5.1", "", "Approved"])
    sheet.append([2, "IMS-OMNI-P002", "Old Policy", "Policy", "1.0", "", "", "", "Superseded",
                  "Owner", "A.5.2", "=1+1" if formula else "", "Withdrawn"])
    control = wb.create_sheet("Document Control")
    control.append(["Revision History"])
    control.append(["Version"])
    control.append(["Version 3.7"])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


@pytest.fixture(autouse=True)
def _actor(test_db):
    test_db.execute("INSERT INTO organizations (id,name,slug) VALUES (1,'Test','test')")
    test_db.execute("INSERT INTO users (id,username,email,full_name,password_hash,org_id) "
                    "VALUES (1,'admin','admin@example.invalid','Admin','test',1)")
    test_db.commit()


def test_document_register_requires_acknowledged_conflicts_and_keeps_source_claims_unapproved(test_db, tmp_path, monkeypatch):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
    test_db.execute("INSERT INTO aria_documents (doc_id,framework,title,version,org_id,policy_workflow_managed) "
                    "VALUES ('IMS-OMNI-P001','ISO 27001','Information Security Policy','2.0',1,1)")
    original = _book()
    preview = intake.preview(test_db, USER, original, "IMS-OMNI-R029 v4.1.xlsx", org_wide=True)
    assert len(preview["rows"]) == 2
    assert [r["outcome"] for r in preview["rows"]] == ["matched", "needs_source_file"]
    assert preview["source_versions"] == {"filename": "4.1", "banner": "3.9", "revision_history": "3.7"}
    assert {w["code"] for w in preview["warnings"]} == {"version_conflict", "not_current"}
    assert test_db.execute("SELECT COUNT(*) FROM aria_document_register_claims").fetchone()[0] == 0
    with pytest.raises(intake.RegisterError, match="acknowledge"):
        intake.confirm(test_db, USER, preview["batch_id"], 1, [])
    result = intake.confirm(test_db, USER, preview["batch_id"], 1,
                            [f"{w['code']}:{w.get('ref','')}" for w in preview["warnings"]])
    assert result["claims"] == 2 and result["matched"] == 1
    assert result["source_evidence_id"] > 0
    assert result["_created_source_path"].read_bytes() == original
    stored = test_db.execute("SELECT file_hash,org_id,business_unit_id,category FROM evidence_items WHERE id=%s",
                             (result["source_evidence_id"],)).fetchone()
    assert stored["org_id"] == 1 and stored["business_unit_id"] is None and stored["category"] == "report"
    assert stored["file_hash"] == preview["file_sha256"]
    assert test_db.execute("SELECT source_bytes FROM aria_document_register_batches WHERE id=%s", (preview["batch_id"],)).fetchone()[0] is None
    claims = intake.claims(test_db, USER)
    assert len(claims) == 2 and {r["state"] for r in claims} == {"pending_review"}
    assert {r["source_evidence_id"] for r in claims} == {result["source_evidence_id"]}
    with pytest.raises(intake.RegisterError, match="different reviewer"):
        intake.review_claim(test_db, USER, claims[0]["id"], 1, "needs_source_file")
    test_db.execute("INSERT INTO users (id,username,email,full_name,password_hash,org_id) "
                    "VALUES (2,'reviewer','reviewer@example.invalid','Reviewer','test',1)")
    reviewer = {**USER, "id": 2, "username": "reviewer"}
    matched = next(c for c in claims if c["matched_document_id"])
    reviewed = intake.review_claim(test_db, reviewer, matched["id"], 1, "exact_match")
    assert reviewed["state"] == "matched_for_review"
    assert test_db.execute("SELECT status FROM aria_documents WHERE id=%s", (matched["matched_document_id"],)).fetchone()[0] == "Draft"
    assert test_db.execute("SELECT COUNT(*) FROM aria_policy_clause_links").fetchone()[0] == 0
    with pytest.raises(intake.RegisterError, match="no longer current"):
        intake.confirm(test_db, USER, preview["batch_id"], 1, [])


def test_document_register_rejects_formula_and_foreign_org_match(test_db):
    with pytest.raises(intake.RegisterError, match="formulas"):
        intake.preview(test_db, USER, _book(formula=True), "register.xlsx", org_wide=True)
    test_db.execute("INSERT INTO organizations (id,name,slug) VALUES (2,'Other','other')")
    test_db.execute("INSERT INTO aria_documents (doc_id,framework,title,version,org_id,policy_workflow_managed) "
                    "VALUES ('IMS-OMNI-P001','ISO 27001','Other org policy','2.0',2,1)")
    result = intake.preview(test_db, USER, _book(), "IMS-OMNI-R029 v4.1.xlsx", org_wide=True)
    assert result["rows"][0]["outcome"] == "needs_source_file"


def test_confirmed_workbook_reuses_only_same_scoped_source(test_db, tmp_path, monkeypatch):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
    original = _book()
    def file_one(org_wide=True, unit=None):
        preview = intake.preview(test_db, USER, original, "register.xlsx", business_unit_id=unit, org_wide=org_wide)
        result = intake.confirm(test_db, USER, preview["batch_id"], 1,
                                [f"{w['code']}:{w.get('ref','')}" for w in preview["warnings"]])
        test_db.commit()
        return result
    first = file_one()
    again = file_one()
    assert again["source_evidence_id"] == first["source_evidence_id"]
    assert again["_created_source_path"] is None
    test_db.execute("INSERT INTO business_units (id,name) VALUES (10,'Unit')")
    unit_user = {**USER, "business_unit_id": 10}
    preview = intake.preview(test_db, unit_user, original, "register.xlsx", business_unit_id=10)
    scoped = intake.confirm(test_db, unit_user, preview["batch_id"], 1,
                            [f"{w['code']}:{w.get('ref','')}" for w in preview["warnings"]])
    assert scoped["source_evidence_id"] != first["source_evidence_id"]


def test_missing_preview_bytes_fail_closed(test_db, tmp_path, monkeypatch):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
    preview = intake.preview(test_db, USER, _book(), "register.xlsx", org_wide=True)
    test_db.execute("UPDATE aria_document_register_batches SET source_bytes=NULL WHERE id=%s", (preview["batch_id"],))
    with pytest.raises(intake.RegisterError, match="source is missing"):
        intake.confirm(test_db, USER, preview["batch_id"], 1,
                       [f"{w['code']}:{w.get('ref','')}" for w in preview["warnings"]])
    assert test_db.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0] == 0


def test_preview_expiry_erases_workbook_bytes_without_filing(test_db, tmp_path, monkeypatch):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
    preview = intake.preview(test_db, USER, _book(), "register.xlsx", org_wide=True)
    test_db.execute("UPDATE aria_document_register_batches SET created_at='2020-01-01 00:00:00' WHERE id=%s",
                    (preview["batch_id"],))
    assert intake.expire_previews(1, db=test_db) == 1
    row = test_db.execute("SELECT status,source_bytes FROM aria_document_register_batches WHERE id=%s",
                          (preview["batch_id"],)).fetchone()
    assert row["status"] == "expired" and row["source_bytes"] is None
    assert not list(tmp_path.glob("*.xlsx"))
    with pytest.raises(intake.RegisterError, match="no longer current"):
        intake.confirm(test_db, USER, preview["batch_id"], 1, [])


def test_confirmed_source_cannot_be_permanently_deleted_with_open_claims(test_db, tmp_path, monkeypatch):
    from modules.evidence import routes

    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
    preview = intake.preview(test_db, USER, _book(), "register.xlsx", org_wide=True)
    result = intake.confirm(test_db, USER, preview["batch_id"], 1,
                            [f"{w['code']}:{w.get('ref','')}" for w in preview["warnings"]])
    test_db.execute("UPDATE evidence_items SET status='archived' WHERE id=%s", (result["source_evidence_id"],))

    class OpenDB:
        def execute(self, *args, **kwargs):
            return test_db.execute(*args, **kwargs)
        def close(self):
            pass

    monkeypatch.setattr(routes, "get_db", lambda: OpenDB())
    request = SimpleNamespace(state=SimpleNamespace(user=USER))
    operation = routes.api_evidence_permanent_delete.__wrapped__(request, result["source_evidence_id"])
    with pytest.raises(StopIteration) as finished:
        operation.send(None)
    response = finished.value.value
    assert response.status_code == 409
    assert test_db.execute("SELECT COUNT(*) FROM evidence_items WHERE id=%s", (result["source_evidence_id"],)).fetchone()[0] == 1
