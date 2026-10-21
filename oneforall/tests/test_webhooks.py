"""Tests for core.webhooks — signing, delivery, retry, logging.

Run: .venv/Scripts/python -m pytest tests/test_webhooks.py -q
"""
import hashlib
import hmac
import json

import pytest

from core import webhooks as wh
from core.outbound_http import OutboundResult


def _valid_sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_sign_format():
    body = b'{"event_type":"x"}'
    sig = wh._sign("s3cr3t", body)
    assert sig.startswith("sha256=")
    assert sig == _valid_sig("s3cr3t", body)


def test_build_payload_shape():
    p = wh._build_payload("erm.risk.escalated", "erm", "risk", 7,
                          {"score": 9}, 42, 99)
    assert p["event_type"] == "erm.risk.escalated"
    assert p["source_module"] == "erm"
    assert p["source_entity_id"] == 7
    assert p["organisation_id"] == 99
    assert p["triggered_by_user"] == 42
    assert "timestamp" in p and p["data"] == {"score": 9}


def _fake_result(status_code=200, text="ok"):
    return OutboundResult(status_code=status_code, text=text, elapsed_ms=0.0)


def test_deliver_success(monkeypatch):
    captured = {}

    def fake_send_outbound(url, *, content=None, headers=None, **kw):
        captured["url"] = url
        captured["sig"] = headers["X-ThemisIQ-Signature"]
        captured["body"] = content
        return _fake_result(200, "received")

    monkeypatch.setattr(wh, "send_outbound", fake_send_outbound)
    ok = wh.deliver(1, "https://example.com/hook", "s3cr3t",
                    {"event_type": "x", "data": {}})
    assert ok is True
    # signature must verify against the secret + body
    assert captured["sig"] == _valid_sig("s3cr3t", captured["body"])


def test_deliver_retries_then_fails(monkeypatch):
    calls = {"n": 0}

    def fake_send_outbound(url, *, content=None, headers=None, **kw):
        calls["n"] += 1
        raise ConnectionError("conn refused")  # network error -> retryable

    monkeypatch.setattr(wh, "send_outbound", fake_send_outbound)
    ok = wh.deliver(2, "https://example.com/hook", "s3cr3t", {"event_type": "x"})
    assert ok is False
    assert calls["n"] == wh._MAX_RETRIES  # tried max times


def test_deliver_4xx_no_retry(monkeypatch):
    calls = {"n": 0}

    def fake_send_outbound(url, *, content=None, headers=None, **kw):
        calls["n"] += 1
        return _fake_result(404, "not found")  # client error -> don't retry

    monkeypatch.setattr(wh, "send_outbound", fake_send_outbound)
    ok = wh.deliver(3, "https://example.com/hook", "s3cr3t", {"event_type": "x"})
    assert ok is False
    assert calls["n"] == 1  # single attempt, no retry on 4xx


def test_deliver_blocked_by_outbound_policy_does_not_retry_as_network_error(monkeypatch):
    """PLAN-36 T05: a URL rejected by outbound policy (e.g. re-resolves to a
    private address between save and send) must be logged as a real failure,
    not silently retried forever as if it were a transient network blip."""
    calls = {"n": 0}

    def fake_send_outbound(url, *, content=None, headers=None, **kw):
        calls["n"] += 1
        raise wh.OutboundURLError("URL resolves to a blocked (non-public) address")

    monkeypatch.setattr(wh, "send_outbound", fake_send_outbound)
    ok = wh.deliver(4, "https://rebinding.example/hook", "s3cr3t", {"event_type": "x"})
    assert ok is False
    assert calls["n"] == wh._MAX_RETRIES, \
        "still goes through the normal retry budget (code=0 is retryable), just never succeeds"


def test_dispatch_matches_subscribers(monkeypatch):
    """dispatch_event only delivers to webhooks subscribed to the event."""
    delivered = []

    def fake_deliver(wid, url, secret, payload):
        delivered.append((wid, payload["event_type"]))
        return True

    monkeypatch.setattr(wh, "deliver", fake_deliver)

    # fake DB returning two webhooks: one subscribed, one not
    class Row(dict):
        pass

    sub = Row(id=10, url="u", secret="s", org_id=5, events="erm.risk.escalated,erm.risk.closed")
    other = Row(id=11, url="u2", secret="s", org_id=5, events="grid.audit.completed")

    class FakeRows(list):
        def fetchall(self):
            return list(self)

    class FakeDB:
        def execute(self, *a, **k):
            return FakeRows([sub, other])

        def close(self):
            pass

    monkeypatch.setattr(wh, "get_db", lambda: FakeDB())

    wh.dispatch_event("erm.risk.escalated", "erm", "risk", 1, {"a": 1},
                      user_id=2, org_id=None)
    # only the subscribed webhook (id 10) should receive it
    assert delivered == [(10, "erm.risk.escalated")]
