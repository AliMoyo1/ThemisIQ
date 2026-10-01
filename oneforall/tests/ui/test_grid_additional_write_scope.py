"""
PLAN-36 F19 follow-up: HTTP regression coverage for the GRID endpoints named
as still-needing-review in findings.md's F19 entry -- cross-mappings,
reminders, saved reports, and policy requests -- plus two adjacent gaps of
the identical class found while reviewing those (evidence approvals, and
audit share links, the latter notably granting an *external* auditor access
to an audit's data via a mailed link).

Each category follows the same pattern test_grid_nc_write_scope.py already
established: seed a resource under the synthetic tenant's own business unit,
confirm a second-BU Audit Lead is denied (404/403, no row created/changed),
and confirm the owning BU's Audit Lead succeeds.
"""

import database
import httpx
import pytest

from core.auth import hash_password
from core.rbac import AUDIT_LEAD
from modules.governance.data_service import assign_user_business_unit

_PASSWORD = "Synthetic-Test-Pass-Grid-Scope-2!"


def _login(base_url: str, username: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=10)
    login_page = client.get("/login")
    csrf = login_page.cookies.get("csrf_token")
    response = client.post(
        "/login", data={"username": username, "password": password, "csrf_token": csrf},
    )
    assert response.status_code in (302, 303), response.text
    assert response.headers.get("location") != "/login"
    return client


@pytest.fixture(scope="module")
def second_bu_audit_lead(live_app, synthetic_tenant):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO business_units (name, is_active) VALUES ('UI Harness GRID Scope2 Other SBU', 1)"
        )
        db.commit()
        bu_id = db.execute(
            "SELECT id FROM business_units WHERE name=%s",
            ("UI Harness GRID Scope2 Other SBU",),
        ).fetchone()["id"]

        username = "uiharness_grid_scope2_other_sbu_lead"
        db.execute(
            "INSERT INTO users "
            "(username, email, full_name, password_hash, org_id, is_super_admin, must_change_password) "
            "VALUES (%s, %s, %s, %s, %s, 0, 0)",
            (username, f"{username}@example.test", "GRID Scope2 Other SBU Lead",
             hash_password(_PASSWORD), synthetic_tenant["org_id"]),
        )
        db.commit()
        user_id = db.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()["id"]
        db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)", (user_id, AUDIT_LEAD))
        db.commit()
        assign_user_business_unit(user_id, bu_id)
        return {"username": username, "password": _PASSWORD, "business_unit_id": bu_id}
    finally:
        db.close()


@pytest.fixture
def owned_audit_and_control(live_app, synthetic_tenant):
    """One audit + one control, owned by the synthetic tenant's own BU."""
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO grid_audits (name, business_unit_id) VALUES (%s, %s)",
            ("F19 Scope2 Owned Audit", synthetic_tenant["business_unit_id"]),
        )
        db.commit()
        audit_id = db.execute(
            "SELECT id FROM grid_audits WHERE name='F19 Scope2 Owned Audit'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO grid_controls (audit_id, name) VALUES (%s, 'F19 Scope2 Owned Control')",
            (audit_id,),
        )
        db.commit()
        control_id = db.execute(
            "SELECT id FROM grid_controls WHERE name='F19 Scope2 Owned Control'"
        ).fetchone()["id"]
        return {"audit_id": audit_id, "control_id": control_id}
    finally:
        db.close()


@pytest.fixture
def other_bu_audit_and_control(second_bu_audit_lead):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO grid_audits (name, business_unit_id) VALUES (%s, %s)",
            ("F19 Scope2 Other Audit", second_bu_audit_lead["business_unit_id"]),
        )
        db.commit()
        audit_id = db.execute(
            "SELECT id FROM grid_audits WHERE name='F19 Scope2 Other Audit'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO grid_controls (audit_id, name) VALUES (%s, 'F19 Scope2 Other Control')",
            (audit_id,),
        )
        db.commit()
        control_id = db.execute(
            "SELECT id FROM grid_controls WHERE name='F19 Scope2 Other Control'"
        ).fetchone()["id"]
        return {"audit_id": audit_id, "control_id": control_id}
    finally:
        db.close()


def _clients(live_app, synthetic_tenant, second_bu_audit_lead):
    owner_creds = synthetic_tenant["users"]["audit_lead"]
    owner = _login(live_app, owner_creds["username"], owner_creds["password"])
    other = _login(live_app, second_bu_audit_lead["username"], second_bu_audit_lead["password"])
    return owner, other


# ── Cross-mappings ───────────────────────────────────────────────────────────

def test_mapping_create_rejects_cross_bu_controls(
    live_app, synthetic_tenant, second_bu_audit_lead, owned_audit_and_control, other_bu_audit_and_control,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        denied = owner.post("/grid/api/mappings", json={
            "source_control_id": owned_audit_and_control["control_id"],
            "target_control_id": other_bu_audit_and_control["control_id"],
        })
        assert denied.status_code == 404, denied.text

        db = database.get_db()
        try:
            leaked = db.execute(
                "SELECT 1 FROM grid_control_mappings WHERE source_control_id=%s AND target_control_id=%s",
                (owned_audit_and_control["control_id"], other_bu_audit_and_control["control_id"]),
            ).fetchone()
        finally:
            db.close()
        assert leaked is None, "cross-BU mapping was inserted despite denial"

        denied_list = other.get(f"/grid/api/mappings/{owned_audit_and_control['audit_id']}")
        assert denied_list.status_code == 404

        denied_delete = other.delete("/grid/api/mappings/999999")
        assert denied_delete.status_code == 404
    finally:
        owner.close()
        other.close()


def test_mapping_create_and_list_succeed_within_same_bu(
    live_app, synthetic_tenant, second_bu_audit_lead, owned_audit_and_control,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        db = database.get_db()
        try:
            db.execute(
                "INSERT INTO grid_controls (audit_id, name) VALUES (%s, 'F19 Scope2 Owned Control 2')",
                (owned_audit_and_control["audit_id"],),
            )
            db.commit()
            control2_id = db.execute(
                "SELECT id FROM grid_controls WHERE name='F19 Scope2 Owned Control 2'"
            ).fetchone()["id"]
        finally:
            db.close()

        created = owner.post("/grid/api/mappings", json={
            "source_control_id": owned_audit_and_control["control_id"],
            "target_control_id": control2_id,
        })
        assert created.status_code == 201, created.text
        mapping_id = created.json()["id"]

        listed = owner.get(f"/grid/api/mappings/{owned_audit_and_control['audit_id']}")
        assert listed.status_code == 200
        assert any(m["id"] == mapping_id for m in listed.json())

        assert other.get(f"/grid/api/mappings/{owned_audit_and_control['audit_id']}").status_code == 404
        assert other.delete(f"/grid/api/mappings/{mapping_id}").status_code == 404

        deleted = owner.delete(f"/grid/api/mappings/{mapping_id}")
        assert deleted.status_code == 200
    finally:
        owner.close()
        other.close()


def test_mapping_bulk_rejects_any_out_of_scope_control(
    live_app, synthetic_tenant, second_bu_audit_lead, owned_audit_and_control, other_bu_audit_and_control,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        resp = owner.post("/grid/api/mappings/bulk", json={"mappings": [{
            "source_control_id": owned_audit_and_control["control_id"],
            "target_control_id": other_bu_audit_and_control["control_id"],
        }]})
        assert resp.status_code == 404, resp.text
    finally:
        owner.close()
        other.close()


# ── Reminders ────────────────────────────────────────────────────────────────

def test_reminder_create_and_pending_reject_cross_bu(
    live_app, synthetic_tenant, second_bu_audit_lead, other_bu_audit_and_control,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        denied_create = owner.post("/grid/api/reminders", json={
            "audit_id": other_bu_audit_and_control["audit_id"], "frequency": "weekly",
        })
        assert denied_create.status_code == 404, denied_create.text

        db = database.get_db()
        try:
            leaked = db.execute(
                "SELECT 1 FROM grid_reminders WHERE audit_id=%s", (other_bu_audit_and_control["audit_id"],)
            ).fetchone()
        finally:
            db.close()
        assert leaked is None

        # other_bu_audit_and_control belongs to second_bu_audit_lead's own BU,
        # so "other" seeing its pending reminders is the expected same-BU
        # positive control; "owner" (the opposite, actually-cross-BU, side)
        # must be denied.
        assert other.get(f"/grid/api/reminders/{other_bu_audit_and_control['audit_id']}/pending").status_code == 200
        assert owner.get(f"/grid/api/reminders/{other_bu_audit_and_control['audit_id']}/pending").status_code == 404
    finally:
        owner.close()
        other.close()


def test_reminder_create_succeeds_within_same_bu(
    live_app, synthetic_tenant, second_bu_audit_lead, owned_audit_and_control,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        created = owner.post("/grid/api/reminders", json={
            "audit_id": owned_audit_and_control["audit_id"],
            "control_id": owned_audit_and_control["control_id"],
            "frequency": "weekly",
        })
        assert created.status_code == 201, created.text
    finally:
        owner.close()
        other.close()


# ── Saved reports ────────────────────────────────────────────────────────────

def test_saved_report_create_rejects_cross_bu_audit(
    live_app, synthetic_tenant, second_bu_audit_lead, other_bu_audit_and_control,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        denied = owner.post("/grid/api/reports/saved", json={
            "audit_id": other_bu_audit_and_control["audit_id"],
            "filename": "x.pdf", "file_path": "missing-test-file.pdf",
        })
        assert denied.status_code == 404, denied.text
    finally:
        owner.close()
        other.close()


def test_saved_report_detail_download_delete_reject_cross_bu(
    live_app, synthetic_tenant, second_bu_audit_lead, other_bu_audit_and_control,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        created = other.post("/grid/api/reports/saved", json={
            "audit_id": other_bu_audit_and_control["audit_id"],
            "filename": "other.pdf", "file_path": "missing-test-file-2.pdf",
        })
        assert created.status_code == 201, created.text
        rid = created.json()["id"]

        assert all(r["id"] != rid for r in owner.get("/grid/api/reports/saved").json())
        assert owner.get(f"/grid/api/reports/saved/{rid}").status_code == 404
        assert owner.get(f"/grid/api/reports/saved/{rid}/download").status_code == 404
        assert owner.delete(f"/grid/api/reports/saved/{rid}").status_code == 404

        db = database.get_db()
        try:
            still_there = db.execute("SELECT 1 FROM grid_reports WHERE id=%s", (rid,)).fetchone()
        finally:
            db.close()
        assert still_there is not None, "cross-BU delete attempt removed the report despite denial"

        assert other.get(f"/grid/api/reports/saved/{rid}").status_code == 200
    finally:
        owner.close()
        other.close()


# ── Policy requests ──────────────────────────────────────────────────────────

def test_policy_request_create_and_list_reject_cross_bu(
    live_app, synthetic_tenant, second_bu_audit_lead, owned_audit_and_control, other_bu_audit_and_control,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        denied_create = owner.post("/grid/api/policy-requests", json={
            "audit_id": other_bu_audit_and_control["audit_id"], "title": "Cross-BU policy",
        })
        assert denied_create.status_code == 404, denied_create.text

        denied_control_link = owner.post("/grid/api/policy-requests", json={
            "audit_id": owned_audit_and_control["audit_id"],
            "control_id": other_bu_audit_and_control["control_id"],
            "title": "Cross-BU control link",
        })
        assert denied_control_link.status_code == 404, denied_control_link.text

        denied_list = owner.get(f"/grid/api/policy-requests?audit_id={other_bu_audit_and_control['audit_id']}")
        assert denied_list.status_code == 404
    finally:
        owner.close()
        other.close()


def test_policy_request_create_succeeds_within_same_bu(
    live_app, synthetic_tenant, second_bu_audit_lead, owned_audit_and_control,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        created = owner.post("/grid/api/policy-requests", json={
            "audit_id": owned_audit_and_control["audit_id"], "title": "Owned policy request",
        })
        assert created.status_code == 201, created.text
    finally:
        owner.close()
        other.close()


# ── Evidence approvals ───────────────────────────────────────────────────────

def test_approval_routes_reject_cross_bu(
    live_app, synthetic_tenant, second_bu_audit_lead, other_bu_audit_and_control,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        db = database.get_db()
        try:
            db.execute(
                "INSERT INTO grid_evidence_files (control_id, filename, original_name, file_path) "
                "VALUES (%s, 'e.txt', 'Other BU evidence', 'missing-test-file-3')",
                (other_bu_audit_and_control["control_id"],),
            )
            db.commit()
            evidence_id = db.execute(
                "SELECT id FROM grid_evidence_files WHERE original_name='Other BU evidence'"
            ).fetchone()["id"]
        finally:
            db.close()

        assert owner.get(f"/grid/api/approvals/{evidence_id}").status_code == 404
        denied_request = owner.post(f"/grid/api/approvals/{evidence_id}", json={})
        assert denied_request.status_code == 404, denied_request.text

        created = other.post(f"/grid/api/approvals/{evidence_id}", json={})
        assert created.status_code == 201, created.text
        approval_id = created.json()["id"]

        denied_decide = owner.put(f"/grid/api/approvals/{approval_id}/decide", json={"status": "approved"})
        assert denied_decide.status_code == 404, denied_decide.text

        db = database.get_db()
        try:
            row = db.execute("SELECT status FROM grid_approvals WHERE id=%s", (approval_id,)).fetchone()
        finally:
            db.close()
        assert row["status"] != "approved", "cross-BU decide call changed approval status despite denial"
    finally:
        owner.close()
        other.close()


# ── Share links ──────────────────────────────────────────────────────────────

def test_share_link_create_list_revoke_reject_cross_bu(
    live_app, synthetic_tenant, second_bu_audit_lead, other_bu_audit_and_control,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        denied_create = owner.post("/grid/api/share-links", json={
            "audit_id": other_bu_audit_and_control["audit_id"],
        })
        assert denied_create.status_code == 404, denied_create.text

        db = database.get_db()
        try:
            leaked = db.execute(
                "SELECT 1 FROM grid_share_links WHERE audit_id=%s", (other_bu_audit_and_control["audit_id"],)
            ).fetchone()
        finally:
            db.close()
        assert leaked is None, "cross-BU share link was created despite denial (external data exposure risk)"

        created = other.post("/grid/api/share-links", json={
            "audit_id": other_bu_audit_and_control["audit_id"],
        })
        assert created.status_code == 201, created.text
        sid = created.json()["id"]
        token = created.json()["token"]

        assert owner.get(f"/grid/api/share-links/{other_bu_audit_and_control['audit_id']}").status_code == 404
        denied_revoke = owner.put(f"/grid/api/share-links/{sid}/revoke")
        assert denied_revoke.status_code == 404, denied_revoke.text

        db = database.get_db()
        try:
            row = db.execute("SELECT active FROM grid_share_links WHERE id=%s", (sid,)).fetchone()
        finally:
            db.close()
        assert row["active"] == 1, "cross-BU revoke call deactivated another BU's share link despite denial"

        # Token validation is deliberately unscoped -- the token itself is the
        # credential, meant for an external holder with no GRID BU of their own.
        validated = owner.get(f"/grid/api/share-links/validate/{token}")
        assert validated.status_code == 200
    finally:
        owner.close()
        other.close()
