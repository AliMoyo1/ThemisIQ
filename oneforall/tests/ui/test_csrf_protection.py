"""
PLAN-36 T08 ("Add HTTP integration coverage for authentication, CSRF/origin
behavior, capability denial ... on critical routes"). Plain httpx against the
real ASGI app (live_app), same reasoning as
test_action_registry_http_contracts.py: this is about the HTTP contract, not
rendered DOM.

validate_csrf() (core/middleware.py) is not a blanket decorator/middleware --
it is called explicitly, as the first statement, inside individual classic
server-rendered form routes. Grepping every call site found exactly 9
`/admin/users/*` mutations (routes_admin.py) sharing one identical pattern --
`if not validate_csrf(request, csrf_token): return _render_admin_users(...,
{"type": "error", "message": "Invalid request. Please try again."})`, before
any database access -- plus `/login`, `/mfa/verify`, and `/mfa/setup/confirm`
(routes_auth.py). The much larger set of JSON `/api/*` mutation routes
covered by test_action_registry_http_contracts.py do not call validate_csrf
at all: they are reached only with a session cookie, and (being JSON-body
endpoints, not HTML form posts) are not forgeable by a plain cross-site HTML
form the way the classic form routes are. That split is intentional
architecture, not a gap this file invents a fix for.

Only /login and the 9 /admin/users/* actions are covered here -- /mfa/verify
and /mfa/setup/confirm need a mfa_pending session fixture this suite doesn't
build yet; see progress.md for that as an explicit, named gap.
"""
import database
import httpx
import pytest


def _login(base_url: str, username: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=10)
    get_resp = client.get("/login")
    csrf = get_resp.cookies.get("csrf_token")
    assert csrf, "GET /login must set a csrf_token cookie"
    resp = client.post("/login", data={
        "username": username, "password": password, "csrf_token": csrf,
    })
    assert resp.status_code in (302, 303), f"login POST did not redirect: {resp.status_code}"
    assert resp.headers.get("location") != "/login", "login rejected the credentials"
    return client


_INVALID_REQUEST_MSG = "Invalid request. Please try again."

# (id, path, extra form fields the route requires besides csrf_token) -- a
# placeholder uid (999999999) is safe because validate_csrf runs before any
# uid lookup in every one of these handlers (confirmed by reading
# modules/launcher/routes_admin.py directly, not assumed).
_ADMIN_USERS_CSRF_ACTIONS = [
    ("create", "/admin/users/create",
     {"username": "csrf_probe_user", "email": "csrf_probe@example.com", "full_name": "CSRF Probe"}),
    ("grant_role", "/admin/users/999999999/roles/grant", {"role_key": "x"}),
    ("revoke_role", "/admin/users/999999999/roles/revoke", {"role_key": "x"}),
    ("deactivate", "/admin/users/999999999/deactivate", {}),
    ("activate", "/admin/users/999999999/activate", {}),
    ("delete", "/admin/users/999999999/delete", {}),
    ("restore", "/admin/users/999999999/restore", {}),
    ("hard_delete", "/admin/users/999999999/hard-delete", {}),
    ("reset_password", "/admin/users/999999999/reset-password", {}),
]


@pytest.fixture(scope="module")
def admin_client(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["super_admin"]
    client = _login(live_app, creds["username"], creds["password"])
    yield client
    client.close()


@pytest.mark.parametrize(
    "name,path,fields", _ADMIN_USERS_CSRF_ACTIONS, ids=[a[0] for a in _ADMIN_USERS_CSRF_ACTIONS]
)
def test_admin_users_action_rejects_missing_csrf_token(admin_client, name, path, fields):
    resp = admin_client.post(path, data=fields)  # no csrf_token field at all
    assert resp.status_code == 200, f"{name}: expected the form to re-render with an error, got {resp.status_code}"
    assert _INVALID_REQUEST_MSG in resp.text, (
        f"{name}: missing csrf_token did not hit the CSRF gate (response did not "
        f"contain {_INVALID_REQUEST_MSG!r})"
    )


@pytest.mark.parametrize(
    "name,path,fields", _ADMIN_USERS_CSRF_ACTIONS, ids=[a[0] for a in _ADMIN_USERS_CSRF_ACTIONS]
)
def test_admin_users_action_rejects_wrong_csrf_token(admin_client, name, path, fields):
    """A present-but-wrong token is a different branch inside validate_csrf
    (secrets.compare_digest mismatch) than an empty one (`if not form_token`)
    -- both must be proven, not just the falsy-string case."""
    resp = admin_client.post(path, data={**fields, "csrf_token": "not-the-real-token-0000"})
    assert resp.status_code == 200
    assert _INVALID_REQUEST_MSG in resp.text, (
        f"{name}: a wrong (non-empty) csrf_token did not hit the CSRF gate"
    )


def test_admin_users_create_with_bad_csrf_does_not_create_the_user(admin_client):
    """Message-matching proves the code took the CSRF-rejection branch;
    this proves that branch's own `return` (source-verified to run before
    any db = get_db() call) actually means no row was written, not just
    that the same message could theoretically be reachable elsewhere."""
    admin_client.post("/admin/users/create", data={
        "username": "csrf_probe_user", "email": "csrf_probe@example.com",
        "full_name": "CSRF Probe",
    })  # no csrf_token
    db = database.get_db()
    try:
        row = db.execute(
            "SELECT id FROM users WHERE username=%s", ("csrf_probe_user",)
        ).fetchone()
    finally:
        db.close()
    assert row is None, "a CSRF-rejected create still inserted a user row"


def test_login_rejects_missing_csrf_token_and_does_not_authenticate(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["super_admin"]
    client = httpx.Client(base_url=live_app, follow_redirects=False, timeout=10)
    resp = client.post("/login", data={"username": creds["username"], "password": creds["password"]})
    assert resp.status_code == 200
    assert _INVALID_REQUEST_MSG in resp.text
    from config import settings
    assert settings.SESSION_COOKIE_NAME not in resp.cookies, (
        "a CSRF-rejected login must not establish a session, even with correct credentials"
    )
    client.close()


def test_login_rejects_wrong_csrf_token_and_does_not_authenticate(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["super_admin"]
    client = httpx.Client(base_url=live_app, follow_redirects=False, timeout=10)
    resp = client.post("/login", data={
        "username": creds["username"], "password": creds["password"],
        "csrf_token": "forged-token-does-not-match",
    })
    assert resp.status_code == 200
    assert _INVALID_REQUEST_MSG in resp.text
    from config import settings
    assert settings.SESSION_COOKIE_NAME not in resp.cookies
    client.close()
