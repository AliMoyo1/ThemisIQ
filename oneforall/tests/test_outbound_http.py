"""
PLAN-36 T05 (findings.md F07): centralized outbound URL policy.

DNS-dependent cases (loopback/private/link-local/reserved/mixed answers,
the over-broad 172.x prefix) are tested by monkeypatching socket.getaddrinfo
to return controlled fake answers for a fixed hostname -- no real network or
DNS dependency. Transport-level behavior (redirect not followed, response
byte cap, connect timeout) is tested against a real local HTTP server this
file starts itself, which is the "controlled local fixture" the plan's own
T05 test list asks for; validate_outbound_url's HTTPS-only check is
bypassed for just those tests via monkeypatch, since they're proving
transport mechanics, not URL policy (which has its own tests below).
"""
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from core import outbound_http as oh


def _fake_getaddrinfo(answers):
    """answers: list of ip strings. Returns a socket.getaddrinfo-shaped fixture."""
    def _fn(host, port, *args, **kwargs):
        out = []
        for ip in answers:
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            sockaddr = (ip, port or 0, 0, 0) if family == socket.AF_INET6 else (ip, port or 0)
            out.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
        return out
    return _fn


# ─────────────────────────────────────────────────────────────────────────
# validate_outbound_url: scheme / credentials / hostname
# ─────────────────────────────────────────────────────────────────────────

def test_rejects_non_https_scheme():
    with pytest.raises(oh.OutboundURLError, match="HTTPS"):
        oh.validate_outbound_url("http://example.com/hook")


def test_rejects_credentials_in_url(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(["93.184.216.34"]))
    with pytest.raises(oh.OutboundURLError, match="credentials"):
        oh.validate_outbound_url("https://user:pass@example.com/hook")


def test_rejects_malformed_host():
    with pytest.raises(oh.OutboundURLError, match="hostname"):
        oh.validate_outbound_url("https:///no-host-here")


def test_rejects_unresolvable_host(monkeypatch):
    def _raise(*a, **k):
        raise socket.gaierror("Name or service not known")
    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    with pytest.raises(oh.OutboundURLError, match="resolve"):
        oh.validate_outbound_url("https://this-does-not-exist.invalid/hook")


# ─────────────────────────────────────────────────────────────────────────
# validate_outbound_url: DNS-resolved address classification (ipaddress,
# not string prefixes)
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ip,label", [
    ("127.0.0.1", "loopback"),
    ("10.1.2.3", "private RFC1918"),
    ("192.168.1.1", "private RFC1918"),
    ("169.254.1.1", "link-local (cloud metadata range)"),
    ("169.254.169.254", "the literal cloud metadata address"),
    ("0.0.0.0", "unspecified"),
    ("::1", "IPv6 loopback"),
    ("fe80::1", "IPv6 link-local"),
    ("fc00::1", "IPv6 unique local (private)"),
    ("172.16.0.1", "private 172.16.0.0/12"),
    ("172.31.255.255", "private 172.16.0.0/12 upper bound"),
    ("100.64.0.1", "carrier-grade NAT / IPv4 Shared Address Space (RFC 6598)"),
    ("100.100.100.1", "carrier-grade NAT upper range"),
])
def test_rejects_non_global_dns_answer(monkeypatch, ip, label):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo([ip]))
    with pytest.raises(oh.OutboundURLError, match="blocked"):
        oh.validate_outbound_url("https://attacker-controlled.example/hook")


@pytest.mark.parametrize("ip", ["8.8.8.8", "172.15.255.255", "172.32.0.1", "1.1.1.1"])
def test_allows_public_dns_answer_including_public_172_range(monkeypatch, ip):
    """The old string-prefix check blocked ALL 172.x; only 172.16.0.0/12 is
    actually private. 172.15.x and 172.32.x are public and must be allowed."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo([ip]))
    assert oh.validate_outbound_url("https://example.com/hook") == "https://example.com/hook"


def test_rejects_if_any_one_of_multiple_dns_answers_is_non_global(monkeypatch):
    """A hostname resolving to both a public and a private address must be
    rejected outright -- an attacker only needs one usable answer."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(["8.8.8.8", "127.0.0.1"]))
    with pytest.raises(oh.OutboundURLError, match="blocked"):
        oh.validate_outbound_url("https://mixed-answers.example/hook")


# ─────────────────────────────────────────────────────────────────────────
# send_outbound: transport-level behavior against a real local HTTP server
# ─────────────────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # keep test output quiet

    def do_POST(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "https://attacker.invalid/should-not-be-followed")
            self.end_headers()
        elif self.path == "/big":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"x" * (oh.MAX_RESPONSE_BYTES * 2))
        elif self.path == "/slow":
            time.sleep(2)
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')


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
def _bypass_url_policy_for_local_fixture(monkeypatch, request):
    """Only applied to the send_outbound tests below (they opt in via the
    local_server fixture); validate_outbound_url's own HTTPS/DNS rules are
    tested in full above and must stay real everywhere else."""
    if "local_server" in request.fixturenames:
        monkeypatch.setattr(oh, "validate_outbound_url", lambda url: url)


def test_send_outbound_does_not_follow_redirects(local_server):
    result = oh.send_outbound(f"{local_server}/redirect")
    assert result.status_code == 302, "a redirect must be returned as-is, never followed"


def test_send_outbound_caps_response_body_size(local_server):
    result = oh.send_outbound(f"{local_server}/big")
    assert len(result.text.encode("utf-8")) == oh.MAX_RESPONSE_BYTES, \
        "response body must be truncated at exactly the cap, not just stopped-after-exceeding-it"


def test_send_outbound_enforces_read_timeout(local_server, monkeypatch):
    monkeypatch.setattr(oh, "READ_TIMEOUT", 0.3)
    with pytest.raises(httpx.TimeoutException):
        oh.send_outbound(f"{local_server}/slow")


def test_send_outbound_returns_truthful_success(local_server):
    result = oh.send_outbound(f"{local_server}/ok")
    assert result.status_code == 200
    assert "ok" in result.text
