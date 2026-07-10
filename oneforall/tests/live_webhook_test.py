"""Live integration test for core.webhooks against the running ThemisIQ app.

Starts a tiny local HTTP receiver, registers a webhook in the app's DB
pointing at it, emits an event via core.events.emit(), and asserts the
signed payload arrives with a valid X-ThemisIQ-Signature.

Run while the app is booted (DEBUG, port 8090) with this DB:
  python tests/live_webhook_test.py
"""
import hashlib
import hmac
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import get_db
from core.events import emit, ERM_RISK_ESCALATED


RECEIVER_PORT = 9123
RECEIVER_URL = f"http://127.0.0.1:{RECEIVER_PORT}/hook"
SECRET = "integration-test-secret"


class _Handler(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        sig = self.headers.get("X-ThemisIQ-Signature", "")
        _Handler.received.append({
            "body": body,
            "signature": sig,
            "content_type": self.headers.get("Content-Type"),
        })
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")
        self.close_connection = True

    def log_message(self, *a):
        pass


def _start_receiver():
    srv = HTTPServer(("127.0.0.1", RECEIVER_PORT), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def main():
    srv = _start_receiver()
    time.sleep(0.5)

    # Register a webhook in the app DB subscribed to the event we'll emit.
    db = get_db()
    try:
        db.execute(
            "INSERT INTO webhooks (name, url, secret, events, is_active, created_by) "
            "VALUES (%s, %s, %s, %s, 1, 1)",
            ("integration-test", RECEIVER_URL, SECRET, ERM_RISK_ESCALATED),
        )
        db.commit()
    finally:
        db.close()

    # Emit the event — dispatch_event should fan it out to our receiver.
    emit(ERM_RISK_ESCALATED, "erm", "risk", 123,
         {"score": 9, "level": "critical"}, user_id=1)

    # Give the delivery a moment.
    time.sleep(2.0)

    assert _Handler.received, "No webhook delivery received!"
    rec = _Handler.received[0]
    body = rec["body"]
    sig = rec["signature"]

    # Verify HMAC signature matches secret + body.
    expected = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(sig, expected), f"Bad signature: {sig} != {expected}"

    payload = __import__("json").loads(body)
    assert payload["event_type"] == ERM_RISK_ESCALATED
    assert payload["source_module"] == "erm"
    assert payload["source_entity_id"] == 123
    assert payload["data"]["level"] == "critical"
    assert "timestamp" in payload

    # Confirm it was logged.
    db = get_db()
    try:
        log_row = db.execute(
            "SELECT COUNT(*) AS c FROM webhook_logs WHERE event=%s AND success=1",
            (ERM_RISK_ESCALATED,),
        ).fetchone()
        assert log_row["c"] >= 1, "webhook_logs missing success row"
    finally:
        db.close()

    print("LIVE WEBHOOK INTEGRATION TEST PASSED")
    print(f"  -> delivered 1 signed POST, signature valid, logged to webhook_logs")
    srv.shutdown()


if __name__ == "__main__":
    main()
