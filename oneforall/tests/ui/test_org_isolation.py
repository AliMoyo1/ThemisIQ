"""
PLAN-36 T08 ("Add HTTP integration coverage for ... organization/SBU
isolation ... on critical routes"). Plain httpx against live_app -- an
HTTP-level proof that a real authenticated request from one organization
cannot read/write another organization's resource through a real route,
complementing the existing service/data-layer isolation tests (e.g.
tests/test_erm_library_tenancy.py, tests/test_audit_org_isolation.py) which
call data_service functions directly rather than through the ASGI app.

ERM's risk library is the concrete route chosen: `erm.library.manage` is
held by RISK_OWNER (an org-scoped role, not a platform-wide one like
super_admin -- confirmed via core/rbac.py's CAPABILITIES table), and
modules/erm/data_service.py's `_library_can_manage` is explicit that a
non-super-admin actor may only manage a row belonging to their own org_id.
`synthetic_tenant` (tests/ui/conftest.py) only builds one organization, so
this file adds its own second, disposable org + risk_owner user the same way
test_modal_contract.py's `test_link_evidence_modal_from_an_existing_item`
seeds its own row: directly via `database.get_db()`, inside the same
per-session SQLite file `live_app` already booted.
"""
import database
import httpx
import pytest

from core.auth import hash_password
from core.rbac import RISK_OWNER

_PASSWORD = "Synthetic-Test-Pass-2!"


@pytest.fixture(scope="module")
def second_org_risk_owner(live_app):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO organizations (name, slug, plan, status) "
            "VALUES ('UI Harness Org B', 'ui-harness-org-b', 'enterprise', 'active')"
        )
        db.commit()
        org_id = db.execute(
            "SELECT id FROM organizations WHERE slug='ui-harness-org-b'"
        ).fetchone()["id"]
        username = "uiharness_org_b_risk_owner"
        db.execute(
            "INSERT INTO users (username, email, full_name, password_hash, org_id, "
            "is_super_admin, must_change_password) VALUES (%s, %s, %s, %s, %s, 0, 0)",
            (username, f"{username}@example.test", "Org B Risk Owner",
             hash_password(_PASSWORD), org_id),
        )
        db.commit()
        user_id = db.execute(
            "SELECT id FROM users WHERE username=%s", (username,)
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)",
            (user_id, RISK_OWNER),
        )
        db.commit()
        return {"username": username, "password": _PASSWORD, "org_id": org_id, "user_id": user_id}
    finally:
        db.close()


def _login(base_url: str, username: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=10)
    get_resp = client.get("/login")
    csrf = get_resp.cookies.get("csrf_token")
    resp = client.post("/login", data={
        "username": username, "password": password, "csrf_token": csrf,
    })
    assert resp.status_code in (302, 303), f"login POST did not redirect: {resp.status_code}"
    assert resp.headers.get("location") != "/login", "login rejected the credentials"
    return client


@pytest.fixture(scope="module")
def org_a_client(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["risk_owner"]
    client = _login(live_app, creds["username"], creds["password"])
    yield client
    client.close()


@pytest.fixture(scope="module")
def org_b_client(live_app, second_org_risk_owner):
    client = _login(live_app, second_org_risk_owner["username"], second_org_risk_owner["password"])
    yield client
    client.close()


def test_risk_owner_cannot_update_another_orgs_library_item(org_a_client, org_b_client):
    create_resp = org_a_client.post("/erm/api/library", json={
        "title": "Org A Isolation Probe", "category": "operational",
        "default_likelihood": 3, "default_impact": 3,
    })
    assert create_resp.status_code == 201, create_resp.text
    item_id = create_resp.json()["id"]

    cross_org_resp = org_b_client.put(f"/erm/api/library/{item_id}", json={"title": "Hijacked"})
    assert cross_org_resp.status_code == 404, (
        f"org B's risk_owner updated org A's library item: "
        f"{cross_org_resp.status_code} {cross_org_resp.text}"
    )

    same_org_resp = org_a_client.put(
        f"/erm/api/library/{item_id}", json={"title": "Org A Isolation Probe (updated)"}
    )
    assert same_org_resp.status_code == 200, (
        "positive control failed: org A's own risk_owner could not update its own "
        f"item ({same_org_resp.status_code} {same_org_resp.text}) -- the 404 above "
        "may not mean isolation is working, only that writes are broken"
    )


def test_risk_owner_cannot_delete_another_orgs_library_item(org_a_client, org_b_client):
    create_resp = org_a_client.post("/erm/api/library", json={
        "title": "Org A Isolation Probe 2", "category": "operational",
        "default_likelihood": 2, "default_impact": 2,
    })
    assert create_resp.status_code == 201, create_resp.text
    item_id = create_resp.json()["id"]

    cross_org_resp = org_b_client.delete(f"/erm/api/library/{item_id}")
    assert cross_org_resp.status_code == 404, (
        f"org B's risk_owner deleted org A's library item: "
        f"{cross_org_resp.status_code} {cross_org_resp.text}"
    )

    db = database.get_db()
    try:
        row = db.execute(
            "SELECT is_active FROM erm_risk_library WHERE id=%s", (item_id,)
        ).fetchone()
    finally:
        db.close()
    assert row is not None and row["is_active"] == 1, "the item was soft-deleted despite the 404"


# ── Evidence (PLAN-36 T08 finding, 2026-09-30): evidence_items had no
# tenant-scoping column at all before this session -- see
# tests/test_evidence_org_isolation.py for the backend/migration-level
# proof and database.py's _backfill_evidence_org_id /
# modules/evidence/routes.py's _scoped_evidence_item for the fix itself.
# These three checks only need @require_auth (no extra capability), so the
# same risk_owner clients used for the library tests above are reused
# as-is; evidence.delete needs COMPLIANCE_MGR, so cross-org delete/restore
# is left to the unit-level _scoped_evidence_item proof instead of adding a
# third persona/fixture pair here just for that.

def _upload_evidence(client: httpx.Client, title: str) -> int:
    # Content must vary per call -- duplicate detection is (correctly, as of
    # this fix) scoped per org by file_hash, but repeating the exact same
    # bytes within the SAME org's client across these tests would collide
    # with an earlier probe's hash and 409 instead of creating a new item.
    content = f"isolation probe contents: {title}".encode()
    resp = client.post(
        "/evidence/api/items",
        data={"title": title, "category": "general"},
        files={"file": (f"{title}.txt", content, "text/plain")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_evidence_from_another_org_is_not_listed(org_a_client, org_b_client):
    eid = _upload_evidence(org_a_client, "Org A Evidence Isolation Probe")

    org_b_items = org_b_client.get("/evidence/api/items").json()
    assert all(item["id"] != eid for item in org_b_items), (
        "org B's list included an evidence item uploaded by org A"
    )

    org_a_items = org_a_client.get("/evidence/api/items").json()
    assert any(item["id"] == eid for item in org_a_items), (
        "positive control failed: org A can't see its own uploaded evidence"
    )


def test_evidence_from_another_org_cannot_be_fetched_or_downloaded(org_a_client, org_b_client):
    eid = _upload_evidence(org_a_client, "Org A Evidence Fetch Probe")

    assert org_b_client.get(f"/evidence/api/items/{eid}").status_code == 404
    assert org_b_client.get(f"/evidence/api/items/{eid}/download").status_code == 404

    assert org_a_client.get(f"/evidence/api/items/{eid}").status_code == 200
    assert org_a_client.get(f"/evidence/api/items/{eid}/download").status_code == 200


def test_evidence_from_another_org_cannot_be_updated(org_a_client, org_b_client):
    eid = _upload_evidence(org_a_client, "Org A Evidence Update Probe")

    cross_org_resp = org_b_client.put(f"/evidence/api/items/{eid}", json={"title": "Hijacked"})
    assert cross_org_resp.status_code == 404, (
        f"org B updated org A's evidence: {cross_org_resp.status_code} {cross_org_resp.text}"
    )

    db = database.get_db()
    try:
        row = db.execute("SELECT title FROM evidence_items WHERE id=%s", (eid,)).fetchone()
    finally:
        db.close()
    assert row["title"] == "Org A Evidence Update Probe", "the title changed despite the 404"

    same_org_resp = org_a_client.put(f"/evidence/api/items/{eid}", json={"title": "Renamed by owner"})
    assert same_org_resp.status_code == 200, (
        "positive control failed: org A could not update its own evidence "
        f"({same_org_resp.status_code} {same_org_resp.text})"
    )


def test_evidence_stats_does_not_leak_another_orgs_recent_titles(org_a_client, org_b_client):
    """/api/stats' 'recently_added' returns real title/category/file_name,
    not just a count -- the one field in this endpoint that would leak
    actual content, not just a number, if org scoping were missing."""
    title = "Org A Stats Leak Probe (should never appear in org B's stats)"
    _upload_evidence(org_a_client, title)

    org_b_stats = org_b_client.get("/evidence/api/stats").json()
    recent_titles = [r["title"] for r in org_b_stats["recently_added"]]
    assert title not in recent_titles, "org B's stats included org A's recently-added evidence title"

    org_a_stats = org_a_client.get("/evidence/api/stats").json()
    org_a_titles = [r["title"] for r in org_a_stats["recently_added"]]
    assert title in org_a_titles, "positive control failed: org A's own upload is missing from its own stats"
