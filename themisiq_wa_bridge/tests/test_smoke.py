"""Smoke test for the bridge — no external credentials or network needed.

Run:  pytest tests/test_smoke.py
or:   python -m pytest tests/test_smoke.py

Exercises: health, intent parsing, RBAC denial, help, and the full inbound
webhook flow in OFFLINE_MODE (LLM + WhatsApp sends are stubbed).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

# Ensure the app package imports regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Force offline + a temp tenant map BEFORE importing the app.
os.environ["OFFLINE_MODE"] = "true"
os.environ["THEMIS_TENANT_MAP_PATH"] = str(
    Path(__file__).resolve().parent / "tenant_map.test.json")
os.environ["AUDIT_LOG_PATH"] = str(
    Path(__file__).resolve().parent / "audit.test.log.jsonl")
# Set a webhook secret so signature verification is actually exercised.
_TEST_SECRET = "test_webhook_secret_123"
os.environ["THEMIS_WEBHOOK_SECRET"] = _TEST_SECRET

from fastapi.testclient import TestClient  # type: ignore

from app import main
from app.config import load_tenant_map

load_tenant_map(os.environ["THEMIS_TENANT_MAP_PATH"])

client = TestClient(main.app)


def _wa_payload(wa_id: str, text: str) -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "contacts": [{"wa_id": wa_id}],
                    "messages": [{"text": {"body": text}}],
                }
            }]
        }]
    }


def _sign(payload: dict):
    """Return (headers, body_bytes) with a valid X-ThemisIQ-Signature.

    Signing must cover the EXACT bytes sent, so the caller POSTs `content=body`
    (not `json=`, which would re-serialise and break the signature).
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sig = "sha256=" + hmac.new(
        _TEST_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {"X-ThemisIQ-Signature": sig, "Content-Type": "application/json"}, body


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_intent_help():
    from app import intent as I
    i = I.parse("wa_user_263783047375", "help", {"sentinel", "erm"})
    assert i.action == "help"


def test_rbac_denies_unauthorised_module():
    from app import intent as I
    # user only has 'erm'; asking for DPIAs (sentinel) must be denied
    i = I.parse("wa_user_263783047375", "list open DPIAs", {"erm"})
    assert i.action == "denied"
    assert i.params["needed"] == "sentinel"


def test_inbound_qa_offline():
    body = _wa_payload("wa_user_263783047375", "What does CDPA require for breach notification?")
    r = client.post("/webhook/whatsapp", json=body)
    assert r.status_code == 200  # always ack


def test_inbound_unbound_user():
    body = _wa_payload("unknown_user", "help")
    r = client.post("/webhook/whatsapp", json=body)
    assert r.status_code == 200


def test_themis_webhook_bad_signature():
    # Wrong secret -> 401 (secret is now set, so verification is enforced).
    r = client.post("/webhook/themisiq", json={"event_type": "breach.created"},
                    headers={"X-ThemisIQ-Signature": "sha256=bad",
                              "Content-Type": "application/json"})
    assert r.status_code == 401


def test_themis_webhook_fanout_offline():
    # Signed breach event for org 1 -> full subscriber (wa_user_263...) gets it.
    payload = {
        "event_type": "breach.created",
        "source_module": "sentinel",
        "organisation_id": 1,
        "timestamp": "2026-07-10T18:00:00Z",
        "data": {"title": "Unauthorised access to HR dataset", "id": 42},
    }
    headers, body = _sign(payload)
    r = client.post("/webhook/themisiq", content=body, headers=headers)
    assert r.status_code == 200
    # Audit log should record a delivered alert for the full subscriber.
    log_path = Path(os.environ["AUDIT_LOG_PATH"])
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").splitlines()
    sent = [l for l in lines if '"themis_alert_sent"' in l and "breach.created" in l]
    assert sent, "expected a themis_alert_sent audit record for breach.created"
    rec = json.loads(sent[-1])
    assert rec["tenant_id"] == "org_test"


def test_themis_webhook_rbac_scope():
    # risk.threshold_breached -> module 'erm'. Both org-1 subscribers have erm
    # (full user) or only erm (restricted), so both should receive.
    payload = {
        "event_type": "risk.threshold_breached",
        "source_module": "erm",
        "organisation_id": 1,
        "timestamp": "2026-07-10T18:05:00Z",
        "data": {"score": 8.4, "summary": "Residual risk above tolerance"},
    }
    headers, body = _sign(payload)
    r = client.post("/webhook/themisiq", content=body, headers=headers)
    assert r.status_code == 200
    log_path = Path(os.environ["AUDIT_LOG_PATH"])
    lines = log_path.read_text(encoding="utf-8").splitlines()
    sent = [l for l in lines if '"themis_alert_sent"' in l and "risk.threshold_breached" in l]
    assert sent, "expected alert for risk.threshold_breached to subscribers"


def test_event_allowed_mapping():
    from app.main import _event_allowed_for_user
    assert _event_allowed_for_user("breach.created", ["sentinel"]) is True
    assert _event_allowed_for_user("breach.created", ["erm"]) is False
    assert _event_allowed_for_user("risk.threshold_breached", ["erm"]) is True
    assert _event_allowed_for_user("dpia.created", ["aria"]) is True
    assert _event_allowed_for_user("dpia.created", ["sentinel"]) is False
    # unknown event types deliver to everyone
    assert _event_allowed_for_user("something.new", []) is True
