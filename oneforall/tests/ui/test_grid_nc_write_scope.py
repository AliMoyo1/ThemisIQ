"""HTTP regression coverage for GRID NC parent-audit SBU authorization."""

import database
import httpx
import pytest

from core.auth import hash_password
from core.rbac import AUDIT_LEAD
from modules.governance.data_service import assign_user_business_unit

_PASSWORD = "Synthetic-Test-Pass-Grid-Scope-1!"


def _login(base_url: str, username: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=10)
    login_page = client.get("/login")
    csrf = login_page.cookies.get("csrf_token")
    response = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": csrf},
    )
    assert response.status_code in (302, 303), response.text
    assert response.headers.get("location") != "/login"
    return client


@pytest.fixture(scope="module")
def second_bu_audit_lead(live_app, synthetic_tenant):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO business_units (name, is_active) "
            "VALUES ('UI Harness GRID Other SBU', 1)"
        )
        db.commit()
        bu_id = db.execute(
            "SELECT id FROM business_units WHERE name=%s",
            ("UI Harness GRID Other SBU",),
        ).fetchone()["id"]

        username = "uiharness_grid_other_sbu_lead"
        db.execute(
            "INSERT INTO users "
            "(username, email, full_name, password_hash, org_id, "
            "is_super_admin, must_change_password) "
            "VALUES (%s, %s, %s, %s, %s, 0, 0)",
            (
                username,
                f"{username}@example.test",
                "GRID Other SBU Audit Lead",
                hash_password(_PASSWORD),
                synthetic_tenant["org_id"],
            ),
        )
        db.commit()
        user_id = db.execute(
            "SELECT id FROM users WHERE username=%s", (username,)
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)",
            (user_id, AUDIT_LEAD),
        )
        db.commit()
        assign_user_business_unit(user_id, bu_id)
        return {
            "username": username,
            "password": _PASSWORD,
            "user_id": user_id,
            "business_unit_id": bu_id,
        }
    finally:
        db.close()


def test_nc_create_rejects_an_audit_from_another_business_unit(
    live_app, synthetic_tenant, second_bu_audit_lead
):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO grid_audits (name, business_unit_id) VALUES (%s, %s)",
            ("GRID NC Write Scope Audit", synthetic_tenant["business_unit_id"]),
        )
        db.commit()
        audit_id = db.execute(
            "SELECT id FROM grid_audits WHERE name=%s",
            ("GRID NC Write Scope Audit",),
        ).fetchone()["id"]
    finally:
        db.close()

    other_client = _login(
        live_app,
        second_bu_audit_lead["username"],
        second_bu_audit_lead["password"],
    )
    owner_creds = synthetic_tenant["users"]["audit_lead"]
    owner_client = _login(live_app, owner_creds["username"], owner_creds["password"])
    try:
        denied = other_client.post(
            "/grid/api/ncs",
            json={"audit_id": audit_id, "title": "Cross-SBU NC injection"},
        )
        assert denied.status_code == 404, denied.text

        db = database.get_db()
        try:
            leaked = db.execute(
                "SELECT id FROM grid_non_conformances WHERE title=%s",
                ("Cross-SBU NC injection",),
            ).fetchone()
        finally:
            db.close()
        assert leaked is None, "cross-SBU request inserted an NC despite denial"

        allowed = owner_client.post(
            "/grid/api/ncs",
            json={"audit_id": audit_id, "title": "Owning-SBU NC"},
        )
        assert allowed.status_code == 201, allowed.text
        nc_id = allowed.json()["id"]

        assert other_client.get(f"/grid/api/ncs/{nc_id}").status_code == 404
        assert all(
            item["id"] != nc_id for item in other_client.get("/grid/api/ncs").json()
        )
        assert owner_client.get(f"/grid/api/ncs/{nc_id}").status_code == 200
        assert other_client.put(f"/grid/api/ncs/{nc_id}/advance").status_code == 404
        assert owner_client.get(f"/grid/api/ncs/{nc_id}").json()["cap_status"] == "Open"
        assert other_client.get(f"/grid/api/ncs/{nc_id}/evidence").status_code == 404
        assert other_client.get(f"/grid/api/audits/{audit_id}/stats").status_code == 404

        created_control = owner_client.post(
            "/grid/api/controls", json={"audit_id": audit_id, "name": "Owned GRID control"}
        )
        assert created_control.status_code == 201, created_control.text
        control_id = created_control.json()["id"]
        db = database.get_db()
        try:
            db.execute(
                "INSERT INTO grid_evidence_files "
                "(control_id, filename, original_name, file_path) "
                "VALUES (%s, %s, %s, %s)",
                (control_id, "owned-evidence.txt", "Owned GRID evidence", "missing-test-file"),
            )
            db.commit()
            evidence_id = db.execute(
                "SELECT id FROM grid_evidence_files WHERE original_name=%s",
                ("Owned GRID evidence",),
            ).fetchone()["id"]
        finally:
            db.close()
        assert owner_client.get(f"/grid/api/evidence/file/{evidence_id}").status_code == 200
        assert other_client.get(f"/grid/api/evidence/file/{evidence_id}").status_code == 404
        assert other_client.get(
            f"/grid/api/evidence/file/{evidence_id}/download"
        ).status_code == 404
        assert all(
            item["id"] != evidence_id
            for item in other_client.get("/grid/api/evidence-all").json()
        )
        linked = owner_client.post(
            f"/grid/api/ncs/{nc_id}/evidence",
            json={"evidence_file_id": evidence_id},
        )
        assert linked.status_code == 200, linked.text
        other_audit = other_client.post(
            "/grid/api/audits", json={"name": "Other SBU evidence audit"}
        )
        assert other_audit.status_code == 201, other_audit.text
        other_control = other_client.post(
            "/grid/api/controls",
            json={"audit_id": other_audit.json()["id"], "name": "Other SBU control"},
        )
        assert other_control.status_code == 201, other_control.text
        denied_control_link = owner_client.post(
            "/grid/api/ncs",
            json={
                "audit_id": audit_id,
                "control_id": other_control.json()["id"],
                "title": "Cross-audit control NC",
            },
        )
        assert denied_control_link.status_code == 404, denied_control_link.text
        allowed_control_link = owner_client.post(
            "/grid/api/ncs",
            json={
                "audit_id": audit_id,
                "control_id": control_id,
                "title": "Same-audit control NC",
            },
        )
        assert allowed_control_link.status_code == 201, allowed_control_link.text
        db = database.get_db()
        try:
            db.execute(
                "INSERT INTO grid_evidence_files "
                "(control_id, filename, original_name, file_path) "
                "VALUES (%s, %s, %s, %s)",
                (other_control.json()["id"], "other-evidence.txt", "Other SBU evidence", "missing-test-file"),
            )
            db.commit()
            other_evidence_id = db.execute(
                "SELECT id FROM grid_evidence_files WHERE original_name=%s",
                ("Other SBU evidence",),
            ).fetchone()["id"]
        finally:
            db.close()
        denied_link = owner_client.post(
            f"/grid/api/ncs/{nc_id}/evidence",
            json={"evidence_file_id": other_evidence_id},
        )
        assert denied_link.status_code == 404, denied_link.text
        assert [
            row["evidence_id"] for row in owner_client.get(f"/grid/api/ncs/{nc_id}/evidence").json()
        ] == [evidence_id]
        assert other_client.get(f"/grid/api/controls/{control_id}").status_code == 404
        assert other_client.get(f"/grid/api/evidence/{control_id}").status_code == 404
        assert other_client.get(f"/grid/api/evidence-items/{control_id}").status_code == 404
        assert other_client.post(
            f"/grid/api/controls/{control_id}/comments",
            json={"content": "Cross-SBU comment"},
        ).status_code == 404
        assert all(
            item["id"] != control_id for item in other_client.get("/grid/api/controls").json()
        )
        assert other_client.post(
            "/grid/api/controls", json={"audit_id": audit_id, "name": "Cross-SBU control"}
        ).status_code == 404
    finally:
        other_client.close()
        owner_client.close()


def test_nc_create_rejects_invalid_parent_ids(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["audit_lead"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        for invalid_id in (None, True, 0, -1, "invalid", "9" * 5000):
            response = client.post(
                "/grid/api/ncs",
                json={"audit_id": invalid_id, "title": "Invalid-parent NC"},
            )
            assert response.status_code == 422, (invalid_id, response.text)
    finally:
        client.close()


def test_audit_creation_and_followup_keep_the_owning_business_unit(
    live_app, synthetic_tenant, second_bu_audit_lead
):
    owner_creds = synthetic_tenant["users"]["audit_lead"]
    owner = _login(live_app, owner_creds["username"], owner_creds["password"])
    other = _login(
        live_app, second_bu_audit_lead["username"], second_bu_audit_lead["password"]
    )
    try:
        created = owner.post("/grid/api/audits", json={"name": "Owned GRID audit"})
        assert created.status_code == 201, created.text
        audit_id = created.json()["id"]
        audit = owner.get(f"/grid/api/audits/{audit_id}")
        assert audit.status_code == 200, audit.text
        assert audit.json()["business_unit_id"] == synthetic_tenant["business_unit_id"]

        assert other.get(f"/grid/api/audits/{audit_id}").status_code == 404
        assert all(row["id"] != audit_id for row in other.get("/grid/api/audits").json())
        denied_edit = other.put(
            f"/grid/api/audits/{audit_id}", json={"name": "Cross-SBU edit"}
        )
        assert denied_edit.status_code == 404, denied_edit.text
        denied_followup = other.post(
            f"/grid/api/audits/{audit_id}/followup",
            json={"name": "Cross-SBU followup"},
        )
        assert denied_followup.status_code == 404, denied_followup.text
        assert owner.get(f"/grid/api/audits/{audit_id}").json()["name"] == "Owned GRID audit"

        edited = owner.put(
            f"/grid/api/audits/{audit_id}", json={"name": "Owned GRID audit updated"}
        )
        assert edited.status_code == 200, edited.text
        followup = owner.post(
            f"/grid/api/audits/{audit_id}/followup",
            json={"name": "Owned GRID followup", "carry_forward_ncs": False},
        )
        assert followup.status_code == 201, followup.text
        followup_id = followup.json()["id"]
        followup_detail = owner.get(f"/grid/api/audits/{followup_id}")
        assert followup_detail.status_code == 200, followup_detail.text
        assert followup_detail.json()["business_unit_id"] == synthetic_tenant["business_unit_id"]
        assert other.get(f"/grid/api/audits/{followup_id}").status_code == 404
    finally:
        owner.close()
        other.close()