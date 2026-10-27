"""Workbook rows are review claims, never approved policies or control mappings."""
from io import BytesIO

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


def test_document_register_requires_acknowledged_conflicts_and_keeps_source_claims_unapproved(test_db):
    test_db.execute("INSERT INTO aria_documents (doc_id,framework,title,version,org_id,policy_workflow_managed) "
                    "VALUES ('IMS-OMNI-P001','ISO 27001','Information Security Policy','2.0',1,1)")
    preview = intake.preview(test_db, USER, _book(), "IMS-OMNI-R029 v4.1.xlsx", org_wide=True)
    assert len(preview["rows"]) == 2
    assert [r["outcome"] for r in preview["rows"]] == ["matched", "needs_source_file"]
    assert preview["source_versions"] == {"filename": "4.1", "banner": "3.9", "revision_history": "3.7"}
    assert {w["code"] for w in preview["warnings"]} == {"version_conflict", "not_current"}
    assert test_db.execute("SELECT COUNT(*) FROM aria_document_register_claims").fetchone()[0] == 0
    with pytest.raises(intake.RegisterError, match="acknowledge"):
        intake.confirm(test_db, USER, preview["batch_id"], 1, [])
    result = intake.confirm(test_db, USER, preview["batch_id"], 1,
                            [f"{w['code']}:{w.get('ref','')}" for w in preview["warnings"]])
    assert result == {"claims": 2, "matched": 1}
    claims = intake.claims(test_db, USER)
    assert len(claims) == 2 and {r["state"] for r in claims} == {"pending_review"}
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
