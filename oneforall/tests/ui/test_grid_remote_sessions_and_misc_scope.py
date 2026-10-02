"""
PLAN-36 F19 final sweep: HTTP regression coverage for the GRID endpoints
named in findings.md as the explicit remainder after the mappings/
reminders/saved-reports/policy-requests/approvals/share-links slice --
`GET /api/reports/list`, `grid_timeline`, `grid_compliance_scores`, and the
full `grid_remote_sessions`/`grid_remote_findings`/notes/participants
family.

Same pattern as the two prior GRID scope test files: seed a resource under
the synthetic tenant's own business unit and a second BU, confirm a
second-BU Audit Lead is denied (404) with no row created/changed, and
confirm the owning BU's Audit Lead succeeds.
"""

import database
import httpx
import pytest

from core.auth import hash_password
from core.rbac import AUDIT_LEAD
from modules.governance.data_service import assign_user_business_unit

_PASSWORD = "Synthetic-Test-Pass-Grid-Scope-3!"


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
            "INSERT INTO business_units (name, is_active) VALUES ('UI Harness GRID Scope3 Other SBU', 1)"
        )
        db.commit()
        bu_id = db.execute(
            "SELECT id FROM business_units WHERE name=%s",
            ("UI Harness GRID Scope3 Other SBU",),
        ).fetchone()["id"]

        username = "uiharness_grid_scope3_other_sbu_lead"
        db.execute(
            "INSERT INTO users "
            "(username, email, full_name, password_hash, org_id, is_super_admin, must_change_password) "
            "VALUES (%s, %s, %s, %s, %s, 0, 0)",
            (username, f"{username}@example.test", "GRID Scope3 Other SBU Lead",
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
def owned_audit(live_app, synthetic_tenant):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO grid_audits (name, business_unit_id) VALUES (%s, %s)",
            ("F19 Scope3 Owned Audit", synthetic_tenant["business_unit_id"]),
        )
        db.commit()
        return db.execute("SELECT id FROM grid_audits WHERE name='F19 Scope3 Owned Audit'").fetchone()["id"]
    finally:
        db.close()


@pytest.fixture
def other_bu_audit(second_bu_audit_lead):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO grid_audits (name, business_unit_id) VALUES (%s, %s)",
            ("F19 Scope3 Other Audit", second_bu_audit_lead["business_unit_id"]),
        )
        db.commit()
        return db.execute("SELECT id FROM grid_audits WHERE name='F19 Scope3 Other Audit'").fetchone()["id"]
    finally:
        db.close()


@pytest.fixture
def other_bu_remote_session(other_bu_audit):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO grid_remote_sessions (audit_id, title) VALUES (%s, 'F19 Scope3 Other Session')",
            (other_bu_audit,),
        )
        db.commit()
        return db.execute(
            "SELECT id FROM grid_remote_sessions WHERE title='F19 Scope3 Other Session'"
        ).fetchone()["id"]
    finally:
        db.close()


def _clients(live_app, synthetic_tenant, second_bu_audit_lead):
    owner_creds = synthetic_tenant["users"]["audit_lead"]
    owner = _login(live_app, owner_creds["username"], owner_creds["password"])
    other = _login(live_app, second_bu_audit_lead["username"], second_bu_audit_lead["password"])
    return owner, other


# ── Reports list ─────────────────────────────────────────────────────────────

def test_reports_list_excludes_other_bu_audits(
    live_app, synthetic_tenant, second_bu_audit_lead, owned_audit, other_bu_audit,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        listed = owner.get("/grid/api/reports/list")
        assert listed.status_code == 200
        ids = [a["id"] for a in listed.json()]
        assert owned_audit in ids
        assert other_bu_audit not in ids
    finally:
        owner.close()
        other.close()


# ── Timeline ─────────────────────────────────────────────────────────────────

def test_timeline_update_rejects_cross_bu(
    live_app, synthetic_tenant, second_bu_audit_lead, other_bu_audit,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        db = database.get_db()
        try:
            db.execute(
                "INSERT INTO grid_timeline (audit_id, title, date) VALUES (%s, 'F19 Scope3 Milestone', '2026-01-01')",
                (other_bu_audit,),
            )
            db.commit()
            tid = db.execute(
                "SELECT id FROM grid_timeline WHERE title='F19 Scope3 Milestone'"
            ).fetchone()["id"]
        finally:
            db.close()

        denied = owner.put(f"/grid/api/timeline/{tid}", json={"status": "Complete"})
        assert denied.status_code == 404, denied.text

        db = database.get_db()
        try:
            row = db.execute("SELECT status FROM grid_timeline WHERE id=%s", (tid,)).fetchone()
        finally:
            db.close()
        assert row["status"] != "Complete", "cross-BU update changed timeline status despite denial"

        allowed = other.put(f"/grid/api/timeline/{tid}", json={"status": "Complete"})
        assert allowed.status_code == 200
    finally:
        owner.close()
        other.close()


# ── Compliance scores ────────────────────────────────────────────────────────

def test_compliance_scores_reject_cross_bu(
    live_app, synthetic_tenant, second_bu_audit_lead, other_bu_audit,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        denied_create = owner.post(f"/grid/api/scores/{other_bu_audit}", json={"score": 90})
        assert denied_create.status_code == 404, denied_create.text

        db = database.get_db()
        try:
            leaked = db.execute(
                "SELECT 1 FROM grid_compliance_scores WHERE audit_id=%s", (other_bu_audit,)
            ).fetchone()
        finally:
            db.close()
        assert leaked is None

        denied_list = owner.get(f"/grid/api/scores/{other_bu_audit}")
        assert denied_list.status_code == 404

        allowed_create = other.post(f"/grid/api/scores/{other_bu_audit}", json={"score": 90})
        assert allowed_create.status_code == 201, allowed_create.text
        allowed_list = other.get(f"/grid/api/scores/{other_bu_audit}")
        assert allowed_list.status_code == 200
    finally:
        owner.close()
        other.close()


# ── Remote sessions ──────────────────────────────────────────────────────────

def test_remote_session_create_rejects_cross_bu_audit(
    live_app, synthetic_tenant, second_bu_audit_lead, other_bu_audit,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        denied = owner.post("/grid/api/remote-sessions", json={
            "audit_id": other_bu_audit, "title": "Cross-BU session",
        })
        assert denied.status_code == 404, denied.text

        db = database.get_db()
        try:
            leaked = db.execute(
                "SELECT 1 FROM grid_remote_sessions WHERE title='Cross-BU session'"
            ).fetchone()
        finally:
            db.close()
        assert leaked is None
    finally:
        owner.close()
        other.close()


def test_remote_session_list_excludes_other_bu(
    live_app, synthetic_tenant, second_bu_audit_lead, owned_audit, other_bu_remote_session, other_bu_audit,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        unfiltered = owner.get("/grid/api/remote-sessions")
        assert unfiltered.status_code == 200
        assert all(s["id"] != other_bu_remote_session for s in unfiltered.json())

        filtered_denied = owner.get(f"/grid/api/remote-sessions?audit_id={other_bu_audit}")
        assert filtered_denied.status_code == 404
    finally:
        owner.close()
        other.close()


def test_remote_session_get_update_start_end_reject_cross_bu(
    live_app, synthetic_tenant, second_bu_audit_lead, other_bu_remote_session,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        assert owner.get(f"/grid/api/remote-sessions/{other_bu_remote_session}").status_code == 404
        assert owner.put(f"/grid/api/remote-sessions/{other_bu_remote_session}", json={"title": "Hijacked"}).status_code == 404
        assert owner.post(f"/grid/api/remote-sessions/{other_bu_remote_session}/start").status_code == 404
        assert owner.post(f"/grid/api/remote-sessions/{other_bu_remote_session}/end").status_code == 404

        db = database.get_db()
        try:
            row = db.execute(
                "SELECT title, status FROM grid_remote_sessions WHERE id=%s", (other_bu_remote_session,)
            ).fetchone()
        finally:
            db.close()
        assert row["title"] == "F19 Scope3 Other Session"
        assert row["status"] != "in_progress" and row["status"] != "completed"

        assert other.get(f"/grid/api/remote-sessions/{other_bu_remote_session}").status_code == 200
        assert other.post(f"/grid/api/remote-sessions/{other_bu_remote_session}/start").status_code == 200
    finally:
        owner.close()
        other.close()


def test_remote_finding_create_update_reject_cross_bu(
    live_app, synthetic_tenant, second_bu_audit_lead, other_bu_remote_session, other_bu_audit,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        denied_create = owner.post(f"/grid/api/remote-sessions/{other_bu_remote_session}/findings", json={
            "title": "Cross-BU finding",
        })
        assert denied_create.status_code == 404, denied_create.text

        created = other.post(f"/grid/api/remote-sessions/{other_bu_remote_session}/findings", json={
            "title": "Owned finding",
        })
        assert created.status_code == 201, created.text
        fid = created.json()["id"]

        denied_update = owner.put(f"/grid/api/remote-findings/{fid}", json={"status": "closed"})
        assert denied_update.status_code == 404, denied_update.text

        db = database.get_db()
        try:
            row = db.execute("SELECT status FROM grid_remote_findings WHERE id=%s", (fid,)).fetchone()
        finally:
            db.close()
        assert row["status"] != "closed"

        allowed_update = other.put(f"/grid/api/remote-findings/{fid}", json={"status": "closed"})
        assert allowed_update.status_code == 200
    finally:
        owner.close()
        other.close()


def test_remote_finding_create_rejects_cross_bu_control(
    live_app, synthetic_tenant, second_bu_audit_lead, owned_audit,
):
    """A session owned by the caller's own BU, but referencing a control
    from a different BU's audit, must still be rejected on the control id."""
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        db = database.get_db()
        try:
            db.execute(
                "INSERT INTO grid_audits (name, business_unit_id) VALUES ('F19 Scope3 Control Audit', %s)",
                (second_bu_audit_lead["business_unit_id"],),
            )
            db.commit()
            other_audit_id = db.execute(
                "SELECT id FROM grid_audits WHERE name='F19 Scope3 Control Audit'"
            ).fetchone()["id"]
            db.execute(
                "INSERT INTO grid_controls (audit_id, name) VALUES (%s, 'F19 Scope3 Other Control')",
                (other_audit_id,),
            )
            db.commit()
            other_control_id = db.execute(
                "SELECT id FROM grid_controls WHERE name='F19 Scope3 Other Control'"
            ).fetchone()["id"]

            db.execute(
                "INSERT INTO grid_remote_sessions (audit_id, title) VALUES (%s, 'F19 Scope3 Owned Session')",
                (owned_audit,),
            )
            db.commit()
            owned_session_id = db.execute(
                "SELECT id FROM grid_remote_sessions WHERE title='F19 Scope3 Owned Session'"
            ).fetchone()["id"]
        finally:
            db.close()

        denied = owner.post(f"/grid/api/remote-sessions/{owned_session_id}/findings", json={
            "title": "Cross-BU control reference", "control_id": other_control_id,
        })
        assert denied.status_code == 404, denied.text
    finally:
        owner.close()
        other.close()


def test_remote_note_and_participant_reject_cross_bu(
    live_app, synthetic_tenant, second_bu_audit_lead, other_bu_remote_session,
):
    owner, other = _clients(live_app, synthetic_tenant, second_bu_audit_lead)
    try:
        denied_note = owner.post(f"/grid/api/remote-sessions/{other_bu_remote_session}/notes", json={
            "content": "Cross-BU note",
        })
        assert denied_note.status_code == 404, denied_note.text

        denied_participant = owner.post(f"/grid/api/remote-sessions/{other_bu_remote_session}/participants", json={
            "name": "Cross-BU participant",
        })
        assert denied_participant.status_code == 404, denied_participant.text

        db = database.get_db()
        try:
            leaked_note = db.execute(
                "SELECT 1 FROM grid_remote_notes WHERE session_id=%s", (other_bu_remote_session,)
            ).fetchone()
            leaked_participant = db.execute(
                "SELECT 1 FROM grid_remote_participants WHERE session_id=%s AND external_name='Cross-BU participant'",
                (other_bu_remote_session,),
            ).fetchone()
        finally:
            db.close()
        assert leaked_note is None
        assert leaked_participant is None

        allowed_note = other.post(f"/grid/api/remote-sessions/{other_bu_remote_session}/notes", json={
            "content": "Owned note",
        })
        assert allowed_note.status_code == 201, allowed_note.text
    finally:
        owner.close()
        other.close()
