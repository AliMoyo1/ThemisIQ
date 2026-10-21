"""
PLAN-36 T08 ("Add download checks for expected content type, disposition,
non-empty file, and authorization"). Plain httpx against live_app, same
reasoning as test_action_registry_http_contracts.py: this is about the HTTP
contract, not rendered DOM.

Two representative CSV export routes (ERM risk register, BCM incidents) --
chosen because they need no filesystem/upload fixture (StreamingResponse over
a DB query), unlike evidence's file-backed download
(modules/evidence/routes.py's api_evidence_download). That one is left for a
follow-up once this suite has a real uploaded-file fixture; see progress.md.
"""
import httpx
import pytest


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


# (id, path, persona holding the required capability, expected content-type
# prefix, expected filename in Content-Disposition)
_DOWNLOADS = [
    ("erm_risk_register_csv", "/erm/api/export/csv", "risk_owner",
     "text/csv", "erm_risk_register.csv"),
    ("bcm_incidents_csv", "/bcm/api/export/csv", "bcm_manager",
     "text/csv", "bcm_incidents_export.csv"),
    ("orm_events_csv", "/orm/api/export/csv", "risk_owner",
     "text/csv", "orm_events.csv"),
]


@pytest.mark.parametrize(
    "name,path,persona,content_type,filename", _DOWNLOADS, ids=[d[0] for d in _DOWNLOADS]
)
def test_unauthenticated_download_is_redirected(live_app, name, path, persona, content_type, filename):
    client = httpx.Client(base_url=live_app, follow_redirects=False, timeout=10)
    resp = client.get(path)
    assert resp.status_code in (301, 302, 303, 307, 308, 401), (
        f"{name}: unauthenticated download returned {resp.status_code}, expected a redirect or 401"
    )
    if resp.status_code in (301, 302, 303, 307, 308):
        assert "/login" in resp.headers.get("location", ""), (
            f"{name}: unauthenticated redirect went to {resp.headers.get('location')!r}, not /login"
        )


@pytest.mark.parametrize(
    "name,path,persona,content_type,filename", _DOWNLOADS, ids=[d[0] for d in _DOWNLOADS]
)
def test_download_contract(live_app, synthetic_tenant, name, path, persona, content_type, filename):
    creds = synthetic_tenant["users"][persona]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get(path)
        assert resp.status_code == 200, f"{name}: {resp.status_code} {resp.text[:200]}"
        assert resp.headers.get("content-type", "").startswith(content_type), (
            f"{name}: content-type was {resp.headers.get('content-type')!r}, expected to start with {content_type!r}"
        )
        disposition = resp.headers.get("content-disposition", "")
        assert "attachment" in disposition, f"{name}: not served as an attachment: {disposition!r}"
        assert filename in disposition, f"{name}: filename missing from Content-Disposition: {disposition!r}"
        assert len(resp.content) > 0, f"{name}: empty download body"
    finally:
        client.close()


@pytest.mark.parametrize(
    "name,path,persona,content_type,filename", _DOWNLOADS, ids=[d[0] for d in _DOWNLOADS]
)
def test_download_rejects_persona_without_module_access(
    live_app, synthetic_tenant, name, path, persona, content_type, filename
):
    # "viewer" (EXTERNAL_AUDITOR) holds neither module.bcm.access nor
    # erm.risk.view (core/rbac.py's CAPABILITIES table) -- "employee" was
    # tried first and rejected: EMPLOYEE is deliberately included in
    # module.bcm.access (business-continuity duties reach every staff
    # member), so it isn't a valid "denied" persona for that download.
    denied_persona = "viewer"
    assert denied_persona != persona, f"{name}: fixture bug, denied persona equals the allowed one"
    creds = synthetic_tenant["users"][denied_persona]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get(path)
        assert resp.status_code == 403, (
            f"{name}: {denied_persona} (no module access) got {resp.status_code}, expected 403"
        )
    finally:
        client.close()
