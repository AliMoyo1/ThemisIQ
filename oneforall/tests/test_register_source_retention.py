"""Confirmed document register workbooks follow the customer's own retention choice and legal holds.

No period is assumed: until the customer chooses one, workbooks are kept. A due workbook loses its file only; the Vault
record, hash and register claims stay. A hold always stops removal.
"""
from datetime import timedelta

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from config import settings
from core.auth import create_session
from core.timeutils import utcnow
from modules.aria import document_register_intake as intake
from modules.aria import register_source_retention as retention
from tests.test_document_register_intake import USER, _book


@pytest.fixture(autouse=True)
def _actor(test_db):
    test_db.execute("INSERT INTO organizations (id,name,slug) VALUES (1,'Test','test')")
    test_db.execute("INSERT INTO users (id,username,email,full_name,password_hash,org_id) "
                    "VALUES (1,'admin','admin@example.invalid','Admin','test',1)")
    test_db.commit()


def _confirm(test_db):
    preview = intake.preview(test_db, USER, _book(), "register.xlsx", org_wide=True)
    result = intake.confirm(test_db, USER, preview["batch_id"], 1,
                            [f"{w['code']}:{w.get('ref','')}" for w in preview["warnings"]])
    test_db.commit()
    return result


def test_without_a_chosen_period_a_confirmed_workbook_is_kept(test_db, tmp_path, monkeypatch):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
    result = _confirm(test_db)
    shown = retention.get(test_db, result["source_evidence_id"])
    assert shown["delete_after"] is None and shown["hold_reason"] is None
    assert retention.purge_due(1) == 0
    assert result["_created_source_path"].exists()


def test_a_due_workbook_loses_its_file_but_keeps_record_hash_and_claims(test_db, tmp_path, monkeypatch):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
    retention.save_policy(test_db, 30)
    test_db.commit()
    result = _confirm(test_db)
    source = result["source_evidence_id"]
    assert retention.get(test_db, source)["delete_after"] == (utcnow().date() + timedelta(days=30)).isoformat()
    assert retention.purge_due(1) == 0, "not due yet"

    test_db.execute("UPDATE register_source_retention SET delete_after='2020-01-01' WHERE evidence_id=%s", (source,))
    test_db.commit()
    file_hash = test_db.execute("SELECT file_hash FROM evidence_items WHERE id=%s", (source,)).fetchone()["file_hash"]
    assert retention.purge_due(1) == 1
    assert not result["_created_source_path"].exists()
    item = test_db.execute("SELECT file_path,status,file_hash FROM evidence_items WHERE id=%s", (source,)).fetchone()
    assert item["file_path"] is None and item["status"] == "archived" and item["file_hash"] == file_hash
    shown = retention.get(test_db, source)
    assert shown["purged_at"] and shown["purged_hash"] == file_hash
    assert {c["source_evidence_id"] for c in intake.claims(test_db, USER)} == {source}
    assert retention.purge_due(1) == 0, "a purge happens once"
    with pytest.raises(ValueError, match="already removed"):
        retention.set_retention(test_db, source, 1, None, None)


def test_a_legal_hold_stops_removal_until_it_is_lifted(test_db, tmp_path, monkeypatch):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
    result = _confirm(test_db)
    source = result["source_evidence_id"]
    retention.set_retention(test_db, source, 1, None, "Litigation hold on supplier dispute")
    test_db.execute("UPDATE register_source_retention SET delete_after='2020-01-01' WHERE evidence_id=%s", (source,))
    test_db.commit()
    assert retention.purge_due(1) == 0
    assert result["_created_source_path"].exists()
    test_db.execute("UPDATE register_source_retention SET hold_reason=NULL WHERE evidence_id=%s", (source,))
    test_db.commit()
    assert retention.purge_due(1) == 1


def test_another_organization_s_due_workbook_is_not_touched(test_db, tmp_path, monkeypatch):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
    result = _confirm(test_db)
    test_db.execute("UPDATE register_source_retention SET delete_after='2020-01-01' WHERE evidence_id=%s",
                    (result["source_evidence_id"],))
    test_db.commit()
    assert retention.purge_due(2) == 0
    assert result["_created_source_path"].exists()


@pytest.mark.parametrize("body,message", [
    ({"delete_after": "2020-01-01", "reason": "Customer schedule applied"}, "after today"),
    ({"delete_after": "2030-02-30", "reason": "Customer schedule applied"}, "real date"),
    ({"hold_reason": "short", "reason": "Customer schedule applied"}, "10 to 500"),
    ({"delete_after": None}, "Record why"),
])
def test_a_change_is_validated_before_it_is_stored(body, message):
    with pytest.raises(ValueError, match=message):
        retention.parse_change(body)


@pytest.fixture
def client(test_db):
    from modules.evidence.routes import router as evidence_router
    from modules.launcher.routes import router as launcher_router
    app = FastAPI()
    app.include_router(evidence_router)
    app.include_router(launcher_router)
    return TestClient(app, base_url="http://testserver", follow_redirects=False)


def _cookie(test_db, username, role):
    test_db.execute("INSERT INTO users (username,email,full_name,password_hash,org_id,is_active) "
                    "VALUES (%s,%s,%s,'x',1,1)", (username, username + "@example.test", username))
    uid = test_db.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()["id"]
    test_db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s,%s)", (uid, role))
    test_db.commit()
    return {"Cookie": f"{settings.SESSION_COOKIE_NAME}={create_session(uid, ip='203.0.113.7', user_agent='T/1')}"}


def test_http_policy_and_per_workbook_retention_need_the_retention_capability(test_db, tmp_path, monkeypatch, client):
    monkeypatch.setenv("EVIDENCE_DIR", str(tmp_path))
    result = _confirm(test_db)
    source = result["source_evidence_id"]
    manager = _cookie(test_db, "retention_manager", "org_admin")
    staff = _cookie(test_db, "plain_staff", "employee")

    assert client.get("/api/registers/source-retention-policy", headers=staff).status_code == 403
    assert client.get("/api/registers/source-retention-policy", headers=manager).json()["days"] is None
    assert client.post("/api/registers/source-retention-policy", headers=manager,
                       json={"days": 10, "reason": "Customer schedule"}).status_code == 400
    saved = client.post("/api/registers/source-retention-policy", headers=manager,
                        json={"days": 365, "reason": "Customer schedule agreed by the DPO"})
    assert saved.status_code == 200 and saved.json()["days"] == 365
    cleared = client.post("/api/registers/source-retention-policy", headers=manager,
                          json={"days": None, "reason": "Keep workbooks until legal confirms"})
    assert cleared.status_code == 200 and client.get("/api/registers/source-retention-policy",
                                                     headers=manager).json()["days"] is None

    path = f"/evidence/api/items/{source}/source-retention"
    change = {"delete_after": (utcnow().date() + timedelta(days=90)).isoformat(),
              "hold_reason": "Regulator inquiry open until closure", "reason": "Regulator asked us to keep it"}
    assert client.post(path, headers=staff, json=change).status_code == 403
    response = client.post(path, headers=manager, json=change)
    assert response.status_code == 200, response.text
    assert response.json()["source_retention"]["hold_reason"] == "Regulator inquiry open until closure"
    detail = client.get(f"/evidence/api/items/{source}", headers=manager).json()
    assert detail["source_retention"]["delete_after"] == change["delete_after"]
    assert detail["can_manage_source_retention"] is True

    test_db.execute("INSERT INTO evidence_items (title,file_path,file_name,file_size,file_hash,mime_type,category,"
                    "status,uploaded_by,org_id) VALUES ('Plain file','x.txt','x.txt',1,'h','text/plain','general',"
                    "'current',1,1)")
    test_db.commit()
    plain = test_db.execute("SELECT id FROM evidence_items WHERE title='Plain file'").fetchone()["id"]
    assert client.post(f"/evidence/api/items/{plain}/source-retention", headers=manager,
                       json=change).status_code == 409
    assert "source_retention" not in client.get(f"/evidence/api/items/{plain}", headers=manager).json()
