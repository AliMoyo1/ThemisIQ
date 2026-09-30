"""
PLAN-36 T08 ("Add HTTP integration coverage for authentication ... capability
denial ... on critical routes" / "Drive every action-registry entry").

Plain httpx against the real ASGI app (live_app), not Playwright -- these
checks are about the HTTP contract itself (status codes, redirects), not
rendered DOM, so a browser buys nothing and only slows the suite down
(same reasoning test_request_id_middleware.py already documents for this
directory).

Every mutation action in action_registry.json is checked generically for
the one property every one of them shares regardless of what the route
actually does: an unauthenticated request must never reach the mutation
logic, only the auth redirect (require_auth/require_capability both
return this before touching any path parameter or resource lookup, so a
placeholder ID in a route like /aria/documents/update/{doc_id} is safe
to call directly). Actions whose required_capability is a single simple
string (not the more complex "X OR (Y AND is_own)" ownership expressions
some ARIA routes use) are additionally checked for the second shared
property: a real, authenticated session that lacks the capability must
get 403, not a silent 200 or a leaked resource.
"""
import json
from pathlib import Path

import httpx
import pytest

_REGISTRY = json.loads(
    (Path(__file__).parent / "action_registry.json").read_text(encoding="utf-8")
)
_MUTATIONS = [a for a in _REGISTRY["actions"] if a["classification"] == "mutation"]


def _fill_path_params(path: str) -> str:
    """Replace any {param} placeholder with a nonexistent-but-well-formed
    id -- safe because require_auth/require_capability run before any
    resource lookup (confirmed by reading core/middleware.py directly)."""
    import re
    return re.sub(r"\{[^}]+\}", "999999999", path)


def _login(base_url: str, username: str, password: str) -> httpx.Client:
    """A real login through the actual /login form -- GET for the CSRF
    cookie, POST the credentials back with it, matching exactly what a
    browser does (core/middleware.py's validate_csrf falls back to the
    double-submit cookie since there's no session yet to HMAC against)."""
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


@pytest.fixture(scope="module")
def persona_client(live_app, synthetic_tenant):
    """persona_client('risk_owner') -> a logged-in httpx.Client for that
    synthetic user. Cached per persona per module so the 11-persona
    parametrized tests below don't each pay for a fresh login."""
    cache = {}

    def _get(persona: str) -> httpx.Client:
        if persona not in cache:
            creds = synthetic_tenant["users"][persona]
            cache[persona] = _login(live_app, creds["username"], creds["password"])
        return cache[persona]

    yield _get
    for client in cache.values():
        client.close()


# A JSON body is the right default probe for most of these routes, but a
# few expect multipart/form-data (FastAPI validates that shape at the
# framework level, before @require_auth ever runs, so sending the wrong
# shape gets a 422 regardless of auth state and would falsely look like a
# missing auth check either way).
_MULTIPART_ACTIONS = {"evidence.upload_evidence.submit": {"file": ("t.txt", b"x", "text/plain")}}


@pytest.mark.parametrize("action", _MUTATIONS, ids=[a["id"] for a in _MUTATIONS])
def test_unauthenticated_mutation_is_redirected_not_executed(live_app, action):
    if action["personas"] == ["anonymous"]:
        pytest.skip(f"{action['id']} is intentionally reachable while logged out")
    method = action["backend"]["method"]
    path = _fill_path_params(action["backend"]["path"])
    client = httpx.Client(base_url=live_app, follow_redirects=False, timeout=10)
    if action["id"] in _MULTIPART_ACTIONS:
        resp = client.request(method, path, files=_MULTIPART_ACTIONS[action["id"]])
    else:
        resp = client.request(method, path, json={})
    assert resp.status_code in (301, 302, 303, 307, 308, 401), (
        f"{action['id']}: unauthenticated {method} {path} returned "
        f"{resp.status_code}, expected a redirect or 401 -- the mutation "
        f"must never be reachable without a session"
    )
    if resp.status_code in (301, 302, 303, 307, 308):
        assert "/login" in resp.headers.get("location", ""), (
            f"{action['id']}: unauthenticated redirect went to "
            f"{resp.headers.get('location')!r}, not /login"
        )


# Only actions gated by one simple capability string (not ARIA's "X OR (Y
# AND is_own)" ownership expressions, which need a real owned/not-owned
# document to exercise meaningfully and are covered by
# test_aria_managed_edit.py instead).
_SIMPLE_CAPABILITY_MUTATIONS = [
    a for a in _MUTATIONS
    if a.get("required_capability") and " OR " not in a["required_capability"]
]


@pytest.mark.parametrize(
    "action", _SIMPLE_CAPABILITY_MUTATIONS, ids=[a["id"] for a in _SIMPLE_CAPABILITY_MUTATIONS]
)
def test_persona_without_capability_is_forbidden(live_app, persona_client, action):
    denied_persona = next(
        (p for p in ["employee", "viewer", "risk_owner"] if p not in action["personas"]),
        None,
    )
    assert denied_persona, f"{action['id']}: no test persona available outside its own allowed list"
    client = persona_client(denied_persona)
    method = action["backend"]["method"]
    path = _fill_path_params(action["backend"]["path"])
    resp = client.request(method, path, json={})
    assert resp.status_code == 403, (
        f"{action['id']}: {denied_persona} (lacking {action['required_capability']}) "
        f"got {resp.status_code} calling {method} {path}, expected 403"
    )
