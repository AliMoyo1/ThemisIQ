"""
PLAN-36 T05 (findings.md F07): Slack/Teams/WhatsApp connectors share the
same outbound policy as generic webhooks.

Unit level: core.notifications._send() (the shared chokepoint behind
send_slack/send_teams/send_whatsapp) never fakes success and never bypasses
core.outbound_http. HTTP level: the /api/admin/connectors/test-* routes make
a real delivery against a controlled local server and are rate-limited per
actor+connector, mirroring test_webhook_test_endpoint.py's pattern.
"""
import asyncio
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import core.middleware as middleware
import core.notifications as notif
import modules.launcher.routes_admin as routes_admin
from core.outbound_http import OutboundResult, OutboundURLError


def _run(coro):
    return asyncio.run(coro)


def _fake_result(status_code=200, text="ok"):
    return OutboundResult(status_code=status_code, text=text, elapsed_ms=0.0)


# ── Unit level: _send() is the shared chokepoint for all three connectors ──

@pytest.mark.parametrize("send_fn,url_key", [
    (notif.send_slack, "slack_webhook_url"),
    (notif.send_teams, "teams_webhook_url"),
    (notif.send_whatsapp, "whatsapp_webhook_url"),
])
def test_connector_not_configured_returns_false_without_sending(monkeypatch, send_fn, url_key):
    monkeypatch.setattr(notif, "_get_setting", lambda key, default="": default)
    called = {"n": 0}
    monkeypatch.setattr(notif, "send_outbound", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    assert send_fn("hello") is False
    assert called["n"] == 0


@pytest.mark.parametrize("send_fn,url_key", [
    (notif.send_slack, "slack_webhook_url"),
    (notif.send_teams, "teams_webhook_url"),
    (notif.send_whatsapp, "whatsapp_webhook_url"),
])
def test_connector_never_fakes_success_when_outbound_policy_blocks_it(monkeypatch, send_fn, url_key):
    monkeypatch.setattr(notif, "_get_setting", lambda key, default="": "https://blocked.example/hook" if key == url_key else default)

    def _raise(*a, **k):
        raise OutboundURLError("URL resolves to a blocked (non-public) address")

    monkeypatch.setattr(notif, "send_outbound", _raise)
    assert send_fn("hello") is False


@pytest.mark.parametrize("send_fn,url_key", [
    (notif.send_slack, "slack_webhook_url"),
    (notif.send_teams, "teams_webhook_url"),
    (notif.send_whatsapp, "whatsapp_webhook_url"),
])
def test_connector_success_goes_through_send_outbound(monkeypatch, send_fn, url_key):
    monkeypatch.setattr(notif, "_get_setting", lambda key, default="": "https://hooks.example/x" if key == url_key else default)
    captured = {}

    def fake_send_outbound(url, *, json=None, **k):
        captured["url"] = url
        captured["json"] = json
        return _fake_result(200)

    monkeypatch.setattr(notif, "send_outbound", fake_send_outbound)
    assert send_fn("hello") is True
    assert captured["url"] == "https://hooks.example/x"


def test_connector_failure_status_returns_false(monkeypatch):
    monkeypatch.setattr(notif, "_get_setting", lambda key, default="": "https://hooks.example/x" if key == "slack_webhook_url" else default)
    monkeypatch.setattr(notif, "send_outbound", lambda *a, **k: _fake_result(500, "error"))
    assert notif.send_slack("hello") is False


# ── HTTP level: /api/admin/connectors/test-slack makes a real, rate-limited send ──

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
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
def _mock_auth(monkeypatch):
    state = {"actor": None}

    async def fake_get_current_user(request):
        return state["actor"]

    monkeypatch.setattr(middleware, "get_current_user", fake_get_current_user)
    middleware._login_attempts.clear()
    return state


@pytest.fixture(autouse=True)
def _allow_http_for_local_fixture(monkeypatch, request):
    if "local_server" in request.fixturenames:
        import core.outbound_http as oh
        monkeypatch.setattr(oh, "validate_outbound_url", lambda url: url.strip())


def _request_as(auth_state, actor):
    auth_state["actor"] = actor
    return types.SimpleNamespace(state=types.SimpleNamespace(user=actor),
                                  url=types.SimpleNamespace(path="/admin/test"))


def _admin(db, uid):
    db.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (1,'org1','org1')"
    )
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, org_id) "
        "VALUES (%s,%s,%s,%s,'x',1)",
        (uid, f"admin{uid}", f"admin{uid}@example.com", f"Admin {uid}"),
    )
    db.commit()
    return {"id": uid, "username": f"admin{uid}", "org_id": 1,
            "is_super_admin": 0, "roles": ["super_admin"]}


def test_connector_test_endpoint_makes_a_real_send_and_is_rate_limited(test_db, _mock_auth, local_server, monkeypatch):
    test_db.execute("INSERT INTO settings (key, value) VALUES ('slack_webhook_url', %s)", (f"{local_server}/ok",))
    test_db.commit()
    admin = _admin(test_db, 10)
    request = _request_as(_mock_auth, admin)

    monkeypatch.setattr(middleware, "_MAX_LOGIN_ATTEMPTS", 2)
    for _ in range(2):
        result = _run(routes_admin.api_connectors_test_slack(request))
        assert result.status_code == 200

    blocked = _run(routes_admin.api_connectors_test_slack(request))
    assert blocked.status_code == 429
