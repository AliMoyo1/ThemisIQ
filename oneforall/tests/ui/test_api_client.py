"""
PLAN-36 T06: static/js/api_client.js's own response/error classification,
real browser. Every response shape is deterministic via page.route()
interception (Playwright's ASGI-app-agnostic mocking) rather than needing a
real backend route per scenario -- covers exactly the list task_plan.md's
T06 names: 200 JSON, 204, text response, malformed JSON, 400 detail,
401/403, 409, 429 with retry hint, 500 HTML, network failure, timeout, and
abort.

A real authenticated page is used only so base_shell.html loads the script
under test; the fetch target itself is always the intercepted fake
/api/test-endpoint, never a real route.
"""
import re

_CALL = """
async ({url, options}) => {
  try {
    const data = await ApiClient.request(url, options || {});
    return {ok: true, data};
  } catch (err) {
    return {
      ok: false, status: err.status, detail: err.detail, retryable: err.retryable,
      kind: err.kind, requestId: err.requestId, retryAfterSeconds: err.retryAfterSeconds,
      body: err.body, isApiError: err instanceof ApiClient.ApiError,
    };
  }
}
"""


def _call(page, url, options=None):
    return page.evaluate(_CALL, {"url": url, "options": options or {}})


def _goto(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/admin/webhooks")
    page.wait_for_selector("#webhooksBody")
    return page


def test_200_json_returns_parsed_data(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.fulfill(
        status=200, content_type="application/json", body='{"ok": true, "n": 3}'))
    result = _call(page, "/api/test-endpoint")
    assert result == {"ok": True, "data": {"ok": True, "n": 3}}


def test_204_returns_none(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.fulfill(status=204))
    result = _call(page, "/api/test-endpoint")
    assert result == {"ok": True, "data": None}


def test_text_response_returned_as_text(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.fulfill(
        status=200, content_type="text/plain", body="plain body"))
    result = _call(page, "/api/test-endpoint", {"expect": "text"})
    assert result == {"ok": True, "data": "plain body"}


def test_login_redirect_throws_session_expired_not_fake_success(login_as, live_app):
    """Red proof for this test (temporarily restoring the old fallback,
    `return (await response.text()).slice(0, 2000);`, in place of the
    throw): `result["ok"]` becomes True with the real /login page's HTML
    as `data` -- exactly the false-mutation-success bug this closes.
    Restored, the session-expiry request rejects instead.

    Session expiry is simulated by clearing cookies after logging in,
    not just redirecting /api/test-endpoint to /login directly -- an
    *authenticated* browser hitting /login gets bounced onward to /,
    which would make the redirect chain end at / instead of /login and
    miss the exact case this fix targets (a truly unauthenticated
    request landing ON /login and staying there, 200, HTML)."""
    page = _goto(login_as, live_app)
    page.context.clear_cookies()
    page.route("**/api/test-endpoint", lambda r: r.fulfill(
        status=302, headers={"Location": "/login"}))
    result = _call(page, "/api/test-endpoint")
    assert result["ok"] is False
    assert result["kind"] == "auth"
    assert result["status"] == 401
    assert "session has expired" in result["detail"].lower()


def test_non_json_200_without_redirect_throws_parse_error(login_as, live_app):
    """A non-JSON 200 that ISN'T a login redirect (e.g. some other proxy
    or misconfigured route) must still reject rather than hand the caller
    a raw HTML/text blob as if it were the requested JSON payload."""
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.fulfill(
        status=200, content_type="text/html", body="<html>not json</html>"))
    result = _call(page, "/api/test-endpoint")
    assert result["ok"] is False
    assert result["kind"] == "parse"
    assert result["status"] == 200


def test_blob_response_returns_blob_and_filename(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.fulfill(
        status=200, content_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="audit-report.pdf"'},
        body="%PDF-1.4 fake report bytes"))
    result = page.evaluate("""
        async () => {
          const data = await ApiClient.request('/api/test-endpoint', {expect: 'blob'});
          return {filename: data.filename, size: data.blob.size, text: await data.blob.text()};
        }
    """)
    assert result["filename"] == "audit-report.pdf"
    assert result["size"] > 0
    assert "fake report bytes" in result["text"]


def test_malformed_json_on_200_raises_parse_error(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.fulfill(
        status=200, content_type="application/json", body="{not valid json"))
    result = _call(page, "/api/test-endpoint")
    assert result["ok"] is False
    assert result["isApiError"] is True
    assert result["kind"] == "parse"
    assert result["status"] == 200
    assert "invalid" in result["detail"].lower()


def test_400_surfaces_the_servers_detail_message(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.fulfill(
        status=400, content_type="application/json", body='{"detail": "Name is required."}'))
    result = _call(page, "/api/test-endpoint")
    assert result["ok"] is False
    assert result["kind"] == "validation"
    assert result["detail"] == "Name is required."
    assert result["retryable"] is False


def test_401_is_classified_as_auth_with_a_safe_default_detail(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.fulfill(status=401, body=""))
    result = _call(page, "/api/test-endpoint")
    assert result["kind"] == "auth"
    assert "sign in" in result["detail"].lower()


def test_403_is_classified_as_forbidden(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.fulfill(status=403, body=""))
    result = _call(page, "/api/test-endpoint")
    assert result["kind"] == "forbidden"
    assert "permission" in result["detail"].lower()


def test_409_is_classified_as_conflict(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.fulfill(status=409, body=""))
    result = _call(page, "/api/test-endpoint")
    assert result["kind"] == "conflict"


def test_429_is_retryable_and_carries_retry_after_seconds(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.fulfill(
        status=429, headers={"Retry-After": "30"}, body=""))
    result = _call(page, "/api/test-endpoint")
    assert result["kind"] == "rate_limit"
    assert result["retryable"] is True
    assert result["retryAfterSeconds"] == 30


def test_500_html_never_leaks_the_raw_body(login_as, live_app):
    """A proxy/error page returning HTML on a 500 must never reach the
    caller's detail string -- only the safe generic fallback."""
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.fulfill(
        status=500, content_type="text/html",
        body="<html><body>Internal Server Error<pre>traceback...</pre></body></html>"))
    result = _call(page, "/api/test-endpoint")
    assert result["kind"] == "server"
    assert result["retryable"] is True
    assert "<html>" not in result["detail"]
    assert "traceback" not in result["detail"]


def test_network_failure_is_classified_and_retryable(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.abort("failed"))
    result = _call(page, "/api/test-endpoint")
    assert result["ok"] is False
    assert result["kind"] == "network"
    assert result["status"] == 0
    assert result["retryable"] is True


def test_timeout_aborts_and_is_classified_as_timeout(login_as, live_app):
    page = _goto(login_as, live_app)
    # Handler never calls fulfill/continue/abort -- the request just hangs,
    # exactly like a slow/unresponsive server, until the client's own timer fires.
    page.route("**/api/test-endpoint", lambda r: None)
    result = _call(page, "/api/test-endpoint", {"timeoutMs": 200})
    assert result["ok"] is False
    assert result["kind"] == "timeout"
    assert result["status"] == 0
    assert result["retryable"] is True


def test_caller_abort_is_classified_as_abort_not_timeout_or_network(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: None)  # hangs; the abort should win first
    result = page.evaluate("""
        async () => {
          const controller = new AbortController();
          const p = ApiClient.request('/api/test-endpoint', {signal: controller.signal, timeoutMs: 5000});
          setTimeout(() => controller.abort(), 50);
          try {
            await p;
            return {ok: true};
          } catch (err) {
            return {ok: false, kind: err.kind, retryable: err.retryable};
          }
        }
    """)
    assert result["ok"] is False
    assert result["kind"] == "abort"
    assert result["retryable"] is False


def test_error_body_is_available_for_a_caller_that_needs_more_than_detail(login_as, live_app):
    """E.g. evidence_index.html's upload-duplicate (409) handler needs the
    existing item's id/title out of the body, not just a message string."""
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.fulfill(
        status=409, content_type="application/json",
        body='{"detail": "Duplicate file", "existing_id": 42, "existing_title": "Policy.pdf"}'))
    result = _call(page, "/api/test-endpoint")
    assert result["body"] == {"detail": "Duplicate file", "existing_id": 42, "existing_title": "Policy.pdf"}


def test_request_id_from_response_header_is_surfaced_on_error(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/test-endpoint", lambda r: r.fulfill(
        status=500, headers={"X-Request-ID": "abc123requestid"}, body=""))
    result = _call(page, "/api/test-endpoint")
    assert result["requestId"] == "abc123requestid"
