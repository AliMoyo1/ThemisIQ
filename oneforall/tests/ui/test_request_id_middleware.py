"""
PLAN-36 T06: X-Request-ID response header (core/middleware.py::request_id_middleware).

Needs a real ASGI app + middleware stack, which only the live_app fixture
provides (tests/ outside tests/ui never imports main.py directly -- see its
own conftest.py comment). No browser needed: plain httpx against the real
running server, so Playwright is never imported for this file.
"""
import httpx
import pytest

_REQUEST_ID_RE = __import__("re").compile(r"^[A-Za-z0-9_-]{8,64}$")


def test_response_always_carries_a_well_formed_request_id(live_app):
    resp = httpx.get(f"{live_app}/login", timeout=5)
    rid = resp.headers.get("X-Request-ID")
    assert rid, "X-Request-ID header missing"
    assert _REQUEST_ID_RE.match(rid), f"not well-formed: {rid!r}"


def test_two_requests_get_two_different_generated_ids(live_app):
    rid1 = httpx.get(f"{live_app}/login", timeout=5).headers.get("X-Request-ID")
    rid2 = httpx.get(f"{live_app}/login", timeout=5).headers.get("X-Request-ID")
    assert rid1 != rid2


def test_a_well_formed_incoming_request_id_is_echoed_back(live_app):
    mine = "client-supplied-id-12345"
    resp = httpx.get(f"{live_app}/login", headers={"X-Request-ID": mine}, timeout=5)
    assert resp.headers.get("X-Request-ID") == mine


@pytest.mark.parametrize("bad_id", [
    "",                    # empty
    "short",               # under the 8-char minimum
    "has a space",         # invalid character
    "semi;colon",          # invalid character
    "x" * 65,              # over the 64-char maximum
])
def test_a_malformed_incoming_request_id_is_replaced_not_echoed(live_app, bad_id):
    resp = httpx.get(f"{live_app}/login", headers={"X-Request-ID": bad_id}, timeout=5)
    got = resp.headers.get("X-Request-ID")
    assert got != bad_id
    assert _REQUEST_ID_RE.match(got), f"replacement id not well-formed: {got!r}"


def test_request_id_is_present_even_on_an_error_response(live_app):
    """The middleware is registered outermost specifically so the header
    survives a rejection from a later middleware/handler, not just the
    happy path."""
    resp = httpx.get(f"{live_app}/this-route-does-not-exist-404", timeout=5)
    assert resp.status_code == 404
    assert _REQUEST_ID_RE.match(resp.headers.get("X-Request-ID", ""))


def test_request_id_and_security_headers_survive_a_cors_rejection(live_app):
    """A 404 passes through every middleware layer fully before the
    router itself fails to match a route -- it can't distinguish
    "registered outermost" from "registered innermost", since every
    middleware's own call_next() still runs either way. A CORS rejection
    is different: cors_block_middleware returns a response directly,
    WITHOUT calling call_next(), for any disallowed cross-origin request.
    If request_id_middleware/security_headers_middleware are registered
    such that they end up INSIDE (more nested than) cors_block_middleware
    -- which is what main.py's registration order produced before this
    fix, since Starlette wraps middleware in the reverse of registration
    order -- their own code never runs for this request at all, because
    nothing inside cors_block_middleware's early return ever gets
    called. Code-review finding, 2026-09-28: confirmed directly this way
    before the fix -- a rejected cross-origin request came back 403 with
    neither header present."""
    resp = httpx.get(
        f"{live_app}/",
        headers={"Origin": "https://evil.example"},
        timeout=5,
    )
    assert resp.status_code == 403
    assert _REQUEST_ID_RE.match(resp.headers.get("X-Request-ID", "")), \
        "X-Request-ID missing on a CORS-rejected response"
    assert resp.headers.get("Content-Security-Policy"), \
        "security headers (CSP) missing on a CORS-rejected response"
