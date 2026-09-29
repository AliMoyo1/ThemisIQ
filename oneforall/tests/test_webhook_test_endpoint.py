"""
PLAN-36 T05 (findings.md F06 + F07): /api/admin/webhooks/{id}/test.

Covers: a real delivery attempt against a controlled local HTTP fixture
(never a synthetic success), truthful failure reporting, per-actor rate
limiting, and organization isolation. Same _mock_auth/_request_as pattern
as test_aria_policy_legacy.py (async @_require_cap route).
"""
import asyncio
import socket
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import core.middleware as middleware
import modules.launcher.routes_admin as routes_admin


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _mock_auth(monkeypatch):
    state = {"actor": None}

    async def fake_get_current_user(request):
        return state["actor"]

    monkeypatch.setattr(middleware, "get_current_user", fake_get_current_user)
    # The in-memory rate limiter (core.middleware._login_attempts) is a
    # process-global dict, not reset by the test_db fixture. Each test here
    # gets a fresh SQLite test_db whose webhook ids restart from 1, so
    # rate-limit keys ("webhook_test:{uid}:{wid}") can collide across
    # unrelated tests that reuse the same admin uid. Clear it so every test
    # starts with a clean rate-limit slate regardless of id reuse.
    middleware._login_attempts.clear()
    return state


def _request_as(auth_state, actor):
    auth_state["actor"] = actor
    return types.SimpleNamespace(state=types.SimpleNamespace(user=actor),
                                  url=types.SimpleNamespace(path="/admin/test"))


def _org(db, org_id):
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,%s,%s)",
               (org_id, f"org{org_id}", f"org{org_id}"))


def _admin(db, uid, org_id):
    """An org-scoped admin: holds the super_admin ROLE (grants the
    platform.manage_users capability the route requires) but not the
    separate is_super_admin COLUMN (which _get_webhook_for_admin uses for
    its own, independent cross-org bypass) -- realistic per the T00 finding
    that seed.py's admin user only sets the role. Every test below therefore
    exercises the org-scoped lookup branch, including organization isolation."""
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, org_id) "
        "VALUES (%s,%s,%s,%s,'x',%s)",
        (uid, f"admin{uid}", f"admin{uid}@example.com", f"Admin {uid}", org_id),
    )
    db.commit()
    return {"id": uid, "username": f"admin{uid}", "org_id": org_id,
            "is_super_admin": 0, "roles": ["super_admin"]}


def _webhook(db, org_id, url, name="Test Hook"):
    db.execute(
        "INSERT INTO webhooks (name, url, secret, events, org_id) VALUES (%s,%s,'s3cr3t','erm.risk.escalated',%s)",
        (name, url, org_id),
    )
    db.commit()
    return db.execute("SELECT id FROM webhooks WHERE name=%s AND org_id=%s", (name, org_id)).fetchone()["id"]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/fail":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"server error")
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")


@pytest.fixture(scope="module")
def local_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _allow_http_and_loopback_for_local_fixture(monkeypatch, request):
    """The webhook Test route validates through the real outbound policy
    (HTTPS-only, public-address-only) -- tests that use the local_server
    fixture point at a plain-HTTP loopback address on purpose, so
    validate_outbound_url is bypassed for them the same way
    test_outbound_http.py's own transport tests do it. Tests that don't
    request local_server (the rebind/blocked-destination test below) get
    the real policy, unpatched -- that test is specifically about proving
    the real policy still refuses to connect."""
    if "local_server" in request.fixturenames:
        import core.outbound_http as oh
        monkeypatch.setattr(oh, "validate_outbound_url", lambda url: url.strip())


def test_test_endpoint_makes_a_real_delivery_and_logs_it_truthfully(test_db, _mock_auth, local_server):
    _org(test_db, 1)
    admin = _admin(test_db, 10, org_id=1)
    wid = _webhook(test_db, org_id=1, url=f"{local_server}/ok")

    request = _request_as(_mock_auth, admin)
    result = _run(routes_admin.api_webhook_test(request, wid))

    assert result.status_code == 200
    log = test_db.execute(
        "SELECT response_code, success FROM webhook_logs WHERE webhook_id=%s ORDER BY id DESC LIMIT 1", (wid,)
    ).fetchone()
    assert log["response_code"] == 200
    assert log["success"] == 1


def test_test_endpoint_reports_real_failure_never_fake_success(test_db, _mock_auth, local_server):
    _org(test_db, 1)
    admin = _admin(test_db, 10, org_id=1)
    wid = _webhook(test_db, org_id=1, url=f"{local_server}/fail")

    request = _request_as(_mock_auth, admin)
    result = _run(routes_admin.api_webhook_test(request, wid))

    assert result.status_code != 200, "a genuine delivery failure must not report as HTTP 200"
    log = test_db.execute(
        "SELECT response_code, success FROM webhook_logs WHERE webhook_id=%s ORDER BY id DESC LIMIT 1", (wid,)
    ).fetchone()
    assert log["response_code"] == 500
    assert log["success"] == 0, "F06: the old endpoint always inserted success=1 regardless of what happened"


def test_test_endpoint_enforces_organization_isolation(test_db, _mock_auth, local_server):
    _org(test_db, 1)
    _org(test_db, 2)
    owner = _admin(test_db, 10, org_id=1)
    outsider = _admin(test_db, 20, org_id=2)
    wid = _webhook(test_db, org_id=1, url=f"{local_server}/ok")

    request = _request_as(_mock_auth, outsider)
    result = _run(routes_admin.api_webhook_test(request, wid))
    assert result.status_code == 404

    count = test_db.execute("SELECT COUNT(*) AS n FROM webhook_logs WHERE webhook_id=%s", (wid,)).fetchone()["n"]
    assert count == 0, "an out-of-scope test attempt must not even reach delivery"


def test_test_endpoint_is_rate_limited_per_actor_and_webhook(test_db, _mock_auth, local_server, monkeypatch):
    _org(test_db, 1)
    admin = _admin(test_db, 10, org_id=1)
    wid = _webhook(test_db, org_id=1, url=f"{local_server}/ok")
    request = _request_as(_mock_auth, admin)

    monkeypatch.setattr(middleware, "_MAX_LOGIN_ATTEMPTS", 2)
    for _ in range(2):
        result = _run(routes_admin.api_webhook_test(request, wid))
        assert result.status_code == 200

    blocked = _run(routes_admin.api_webhook_test(request, wid))
    assert blocked.status_code == 429


def test_test_endpoint_never_fakes_success_for_a_blocked_destination(test_db, _mock_auth, monkeypatch):
    """DNS resolves the saved host to a loopback address (simulating either
    a rebind or a URL that slipped past save-time validation) -- the real
    outbound policy must still refuse to connect, and the failure must be
    logged as a failure, not silently treated as delivered."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443)),
    ])

    _org(test_db, 1)
    admin = _admin(test_db, 10, org_id=1)
    wid = _webhook(test_db, org_id=1, url="https://rebind-target.example/hook")

    request = _request_as(_mock_auth, admin)
    result = _run(routes_admin.api_webhook_test(request, wid))

    assert result.status_code != 200
    log = test_db.execute(
        "SELECT success FROM webhook_logs WHERE webhook_id=%s ORDER BY id DESC LIMIT 1", (wid,)
    ).fetchone()
    assert log["success"] == 0
