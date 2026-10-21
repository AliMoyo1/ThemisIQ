"""
PLAN-36 T05: admin_webhooks.html Test button shows a truthful in-flight/
outcome state (Sending / Delivered / Failed) and suppresses double-clicks,
real browser end to end.
"""
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import database
import core.outbound_http as oh


class _Handler(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        _Handler.hits.append(self.path)
        time.sleep(0.3)  # reliable window for the test to observe "Sending..."
        if self.path == "/fail":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"nope")
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")


def _start_local_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{port}"


def _seed_webhook(org_id, url, name):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO webhooks (name, url, secret, events, org_id) "
            "VALUES (%s, %s, 's3cr3t', 'risk.created', %s)",
            (name, url, org_id),
        )
        db.commit()
        return db.execute(
            "SELECT id FROM webhooks WHERE name=%s AND org_id=%s", (name, org_id)
        ).fetchone()["id"]
    finally:
        db.close()


def test_test_button_shows_sending_then_delivered_and_suppresses_double_clicks(
    login_as, live_app, synthetic_tenant, monkeypatch,
):
    _Handler.hits = []
    server, thread, base_url = _start_local_server()
    try:
        # Real webhook destinations must be HTTPS and resolve to a public
        # address (core/outbound_http.py, F07); this in-process local
        # fixture bypasses just that check, the same way
        # tests/test_webhook_test_endpoint.py does, to prove the UI/transport
        # behavior without standing up real TLS/DNS. live_app runs the real
        # app in a background thread of this same process, so the patch
        # applies to the server thread too.
        monkeypatch.setattr(oh, "validate_outbound_url", lambda url: url.strip())

        wh_id = _seed_webhook(synthetic_tenant["org_id"], f"{base_url}/ok", "UI Harness Hook OK")

        page = login_as("super_admin")
        page.goto(f"{live_app}/admin/webhooks")
        page.wait_for_selector(f"#test-btn-{wh_id}", timeout=5000)

        # Fire two click events back to back at the DOM level (bypassing
        # Playwright's actionability retry, which would otherwise wait for
        # the button to re-enable and turn this into two real sends). The
        # second must be swallowed by the native disabled button: a
        # disabled element does not dispatch click listeners at all.
        page.evaluate(
            "(id) => { const b = document.getElementById('test-btn-' + id); b.click(); b.click(); }",
            wh_id,
        )

        page.wait_for_selector(f"#test-btn-{wh_id}[disabled]", timeout=1000)
        assert page.locator(f"#test-btn-{wh_id}").inner_text() == "Sending..."

        page.wait_for_selector(f"#test-btn-{wh_id}:has-text('Delivered')", timeout=5000)
        assert len(_Handler.hits) == 1, (
            f"double-click suppression failed: server received {len(_Handler.hits)} requests"
        )

        page.wait_for_selector(f"#test-btn-{wh_id}:not([disabled])", timeout=3000)
        assert page.locator(f"#test-btn-{wh_id}").inner_text() == "Test"

        assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_test_button_shows_failed_on_a_real_delivery_failure(
    login_as, live_app, synthetic_tenant, monkeypatch,
):
    server, thread, base_url = _start_local_server()
    try:
        monkeypatch.setattr(oh, "validate_outbound_url", lambda url: url.strip())
        wh_id = _seed_webhook(synthetic_tenant["org_id"], f"{base_url}/fail", "UI Harness Hook Fail")

        page = login_as("super_admin")
        page.goto(f"{live_app}/admin/webhooks")
        page.wait_for_selector(f"#test-btn-{wh_id}", timeout=5000)
        page.click(f"#test-btn-{wh_id}")

        page.wait_for_selector(f"#test-btn-{wh_id}:has-text('Failed')", timeout=5000)
        # A real 502 is the intended scenario here, and Chrome logs any
        # non-2xx fetch response as a "Failed to load resource" console
        # message on its own, independent of whether the page's JS handled
        # it gracefully -- so that one specific, expected message is
        # filtered out; any other console/page error still fails the test.
        real_errors = [e for e in page.console_errors if "Failed to load resource" not in e]
        assert not real_errors, f"unexpected console/page errors: {real_errors}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
