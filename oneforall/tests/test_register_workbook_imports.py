"""A workbook is staged before a specialist creates draft source records."""
from io import BytesIO
import json

import pytest
from openpyxl import Workbook

from modules.ai_governance import register_imports as imports
from modules.ai_governance.service import ServiceError


USER = {"id": 1, "org_id": 1, "roles": ["super_admin"], "is_super_admin": True,
        "username": "admin", "full_name": "Admin"}


@pytest.fixture(autouse=True)
def _actor(test_db):
    test_db.execute("INSERT INTO organizations (id,name,slug) VALUES (1,'Test','test')")
    test_db.execute("INSERT INTO users (id,username,email,full_name,password_hash,org_id) "
                    "VALUES (1,'admin','admin@example.invalid','Admin','test',1)")
    test_db.commit()


def _book(kind, *, formula=False):
    wb = Workbook()
    cover = wb.active
    cover.title = "Cover"
    cover.append(["Version", "1.1"])
    if kind == "ai_systems":
        sheet = wb.create_sheet("AI Systems Inventory")
        sheet.append(["Version 1.2"])
        sheet.append(["System ID", "AI System Name", "Version", *[f"Field {i}" for i in range(13)]])
        row = ["SYS-1", "Example AI", "1", "Generator", "SaaS", "Provider", "Draft text", "Internal", "No",
               "Business", "MEDIUM", "Team", "Active", "Notes", "Tools", ""]
    else:
        sheet = wb.create_sheet("Risk Register")
        sheet.append(["Version 1.0"])
        sheet.append(["Risk ID", "System ID", "AI System", *[f"Field {i}" for i in range(20)]])
        row = ["AI-R001", "SYS-1", "Example", "Privacy", "Data", "Description", "Impact", "Assets", "Clause", 4, 4, 16,
               "CRITICAL", "Controls", "Partial", 3, 3, 9, "MEDIUM", "Mitigate", "Owner", "2026-12-31", "2027-01-01"]
        treatment = wb.create_sheet("Risk Treatment")
        treatment.append(["Version 1.0"])
        treatment.append(["Risk ID", "AI System", "Risk Level", "Treatment", "Treatment Action", "Owner",
                          "Priority", "Resources", "Est. Cost", "Target", "Completed", "Effectiveness Review", "Notes"])
        treatment.append(["AI-R001", "Example", "HIGH", "Mitigate", "Investigate", "Owner", "High", "", "", "2026-12-31"])
    if formula:
        row[-1] = "=HYPERLINK(\"https://evil.example\")"
    sheet.append(row)
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def test_systems_workbook_needs_conflict_review_then_creates_unapproved_profile(test_db):
    preview = imports.preview(test_db, USER, kind="ai_systems", data=_book("ai_systems"), filename="systems.xlsx")
    assert len(preview["rows"]) == 1
    assert {w["code"] for w in preview["warnings"]} == {"version_conflict"}
    with pytest.raises(ServiceError, match="acknowledge"):
        imports.confirm(test_db, USER, preview["batch_id"], version=1, acknowledged=[])
    result = imports.confirm(test_db, USER, preview["batch_id"], version=1,
                             acknowledged=["version_conflict:"])
    profile = test_db.execute("SELECT external_ref,adopted_tier,import_review_state,source_claims_json "
                              "FROM ai_use_profiles ").fetchone()
    assert profile["external_ref"] == "SYS-1" and profile["adopted_tier"] is None
    assert profile["import_review_state"] == "pending"
    assert json.loads(profile["source_claims_json"])["risk_label"] == "MEDIUM"
    assert len(result["created"]) == 1
    with pytest.raises(ServiceError, match="no longer current"):
        imports.confirm(test_db, USER, preview["batch_id"], version=1, acknowledged=["version_conflict:"])


def test_risk_workbook_retains_rubric_and_treatment_disagreement(test_db):
    assessment = test_db.execute("INSERT INTO aims_assessments (ref,title) VALUES ('A-1','AI risks')").lastrowid
    preview = imports.preview(test_db, USER, kind="ai_risks", data=_book("ai_risks"),
                              filename="risks.xlsx", assessment_id=assessment)
    codes = {w["code"] for w in preview["warnings"]}
    assert {"rubric_conflict", "treatment_level_conflict", "unknown_system"}.issubset(codes)
    assert test_db.execute("SELECT COUNT(*) FROM aims_risks").fetchone()[0] == 0
    ack = [f"{w['code']}:{w.get('ref','')}" for w in preview["warnings"]]
    imports.confirm(test_db, USER, preview["batch_id"], version=1, acknowledged=ack)
    risk = test_db.execute("SELECT likelihood,impact,status,source_claims_json FROM aims_risks").fetchone()
    assert risk["likelihood"] * risk["impact"] == 16 and risk["status"] == "draft"
    assert json.loads(risk["source_claims_json"])["inherent_level"] == "CRITICAL"
    assert test_db.execute("SELECT COUNT(*) FROM aims_risk_controls").fetchone()[0] == 1


def test_workbook_formula_and_hidden_sheet_are_refused(test_db):
    with pytest.raises(ServiceError, match="formulas"):
        imports.preview(test_db, USER, kind="ai_systems", data=_book("ai_systems", formula=True), filename="bad.xlsx")


def test_foreign_unit_reference_does_not_appear_in_preview(test_db):
    own = test_db.execute("INSERT INTO business_units (name,is_active) VALUES ('Own',1)").lastrowid
    other = test_db.execute("INSERT INTO business_units (name,is_active) VALUES ('Other',1)").lastrowid
    foreign_app = test_db.execute("INSERT INTO applications (name,business_unit_id) VALUES ('Hidden',%s)",
                                  (other,)).lastrowid
    test_db.execute("INSERT INTO ai_use_profiles (application_id,external_ref) VALUES (%s,'SYS-1')", (foreign_app,))
    actor = {**USER, "is_super_admin": False, "roles": ["compliance_manager"], "business_unit_id": own}
    preview = imports.preview(test_db, actor, kind="ai_systems", data=_book("ai_systems"),
                              filename="systems.xlsx", business_unit_id=own)
    assert preview["rows"][0]["outcome"] == "create"
    assert "existing_reference" not in {w["code"] for w in preview["warnings"]}
    with pytest.raises(ServiceError, match="cannot be imported"):
        imports.confirm(test_db, actor, preview["batch_id"], version=1,
                        acknowledged=["version_conflict:"])
