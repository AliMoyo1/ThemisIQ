# PLAN-03: Bridge Alignment (make the skeleton work against the real ThemisIQ)

PREREQUISITE: PLAN-01 merged and deployed (the bridge calls those endpoints). Proactive alerts additionally need PLAN-02.

## Goal

The bridge in `themisiq_wa_bridge\` is a good skeleton wired to an imaginary API and carrying three real bugs. Make it actually work:

1. Fix `themis_client.py`: real auth header (`X-API-Key`), real endpoint paths (`/api/v1/...`).
2. Fix Meta signature verification: Meta signs with the APP SECRET, not the verify token. Add `WA_APP_SECRET` config and enforce verification outside offline mode.
3. Fix the invalid default model id and response handling.
4. Implement the ThemisIQ webhook fan-out (proactive alerts to subscribed WhatsApp users) which is currently a stub.
5. Persist the first-interaction privacy-notice marker and dedupe Meta's redelivered messages.
6. Update tests and example config files to match.

## Files to touch

- `themisiq_wa_bridge\app\themis_client.py`
- `themisiq_wa_bridge\app\config.py`
- `themisiq_wa_bridge\app\main.py`
- `themisiq_wa_bridge\app\intent.py` (help text only)
- `themisiq_wa_bridge\tenant_map.json.example`
- `themisiq_wa_bridge\tests\test_smoke.py`, `themisiq_wa_bridge\tests\tenant_map.test.json`
- `themisiq_wa_bridge\.env.example`
- `themisiq_wa_bridge\README.md` (endpoint + env var updates)

## Steps in order

### Step 1: Fix themis_client.py

Replace the `ENDPOINTS` dict with the real paths from PLAN-01:

```python
ENDPOINTS = {
    "open_dpias":      "/api/v1/dpias?status=open",
    "open_dsars":      "/api/v1/dsrs?status=open",
    "open_breaches":   "/api/v1/breaches?status=open",
    "risk_score":      "/api/v1/risk-summary",
    "kri_status":      "/api/v1/kris",
    "document":        "/api/v1/documents/{doc_id}",
    "command_centre":  "/api/v1/overview",
}
```

Replace `_headers` with:

```python
    def _headers(self) -> dict[str, str]:
        # ThemisIQ API v1 authenticates with X-API-Key; the tenant is derived
        # server-side from the key's organisation. No tenant header exists.
        return {"X-API-Key": self.api_key}
```

Remove the docstring's Bearer claim. Keep everything else (timeout, raise_for_status) unchanged.

### Step 2: Fix Meta signature verification

In `config.py`, in the WhatsApp section of `Settings`, add:

```python
    wa_app_secret: str = Field(default="", description="Meta APP SECRET used for X-Hub-Signature-256 verification")
```

In `main.py`, in `wa_inbound`, replace the verification block:

```python
    sig = request.headers.get("X-Hub-Signature-256")
    if settings.offline_mode:
        pass  # local smoke tests carry no signature
    elif not settings.wa_app_secret:
        audit.log_event(actor="unknown", tenant_id=None, action="wa_verify",
                        detail="wa_app_secret not configured", ok=False)
        raise HTTPException(status_code=503, detail="Bridge not configured")
    elif not verify_meta_signature(raw, sig, settings.wa_app_secret):
        audit.log_event(actor="unknown", tenant_id=None, action="wa_verify", ok=False)
        raise HTTPException(status_code=401, detail="Bad signature")
```

This changes the security posture from fail-open (no token means no verification) to fail-closed.

Twilio note: if `wa_provider=twilio`, Twilio signs with `X-Twilio-Signature` using a different scheme. Phase 1 targets Meta; if Twilio is used, verification must be added before production (leave a `TODO` comment plus a hard refusal: if provider is twilio and not offline, return 503 "Twilio signature verification not implemented").

### Step 3: Fix the model default and reply formatting

In `config.py`, change `ai_model` default from `"claude-sonnet-4"` (not a valid id) to `"claude-opus-4-8"`.

In `main.py` `_execute`, adjust the two actions whose response shapes are now known:

```python
    if i.action == "risk_score":
        d = client.risk_score()
        top = "\n".join(f"• {t['title']} (score {t['score']})" for t in d.get("top_risks", []))
        return (f"Enterprise risk summary:\n"
                f"Open risks: {d.get('open', 0)}\n"
                f"Average open score: {d.get('average_open_score', 'n/a')}\n"
                f"Top risks:\n{top or '• none'}")
    if i.action == "kri_status":
        d = client.kri_status()
        rows = d.get("data", [])
        if not rows:
            return "No active KRIs."
        icon = {"critical": "🔴", "warning": "🟠", "ok": "🟢"}
        lines = [f"{icon.get(k.get('breach_level'), '⚪')} {k['name']}: "
                 f"{k.get('current_value')} {k.get('unit') or ''} "
                 f"(warn {k.get('threshold_warn')}, crit {k.get('threshold_crit')})"
                 for k in rows[:10]]
        return "KRI status:\n" + "\n".join(lines)
```

The list actions (`open_dpias`, `open_dsars`, `open_breaches`) already work because `_summarise` reads the `data` key, and rows have `title` or `ref_number`; extend `_summarise`'s label fallback chain to include `ref_number`:

```python
                label = (it.get("title") or it.get("name") or it.get("ref_number")
                         or it.get("id") or "item")
```

### Step 4: Implement proactive alert fan-out

In `tenant_map.json.example`, extend each entry with alert subscriptions:

```json
{
  "263783047375": {
    "tenant_id": "org_abc",
    "org_slug": "acme",
    "api_key": "REPLACE_WITH_READONLY_SCOPED_KEY",
    "role": "compliance_manager",
    "modules": ["sentinel", "erm", "command_centre"],
    "alerts": ["sentinel.breach.confirmed", "sentinel.dsr.overdue", "erm.appetite.breached"]
  }
}
```

In `config.py`, add a reverse lookup:

```python
def users_for_org(org_slug: str) -> list[tuple[str, dict]]:
    """All (wa_user_id, entry) pairs bound to an organisation slug."""
    return [(uid, t) for uid, t in _TENANT_MAP.items()
            if t.get("org_slug") == org_slug]
```

In `main.py`, replace the stubbed body of `themis_inbound` AFTER the signature check with:

```python
    payload = json.loads(raw or b"{}")
    event_type = payload.get("event_type", "")
    org_slug = payload.get("organisation") or payload.get("organisation_id") or ""
    detail = payload.get("payload") or {}

    templates = {
        "sentinel.breach.confirmed": "🚨 Breach confirmed: {title}. Open ThemisIQ Sentinel for details.",
        "sentinel.dsr.overdue": "⏰ A data subject request is OVERDUE: {title}. Statutory deadline passed.",
        "erm.appetite.breached": "📈 Risk appetite breached in category {category}.",
        "bcm.incident.declared": "🔔 BCM incident declared: {title}.",
        "kri.threshold.breached": "📊 KRI threshold breached: {title}.",
        "webhook.test": "✅ ThemisIQ test event received by the WhatsApp bridge.",
    }
    tmpl = templates.get(event_type)
    if not tmpl:
        return Response(status_code=200)  # unsubscribed event type, ack

    class _SafeDict(dict):
        def __missing__(self, key):
            return "n/a"
    msg = tmpl.format_map(_SafeDict(
        title=detail.get("title") or detail.get("name") or detail.get("ref_number") or "(no title)",
        category=detail.get("category") or "n/a"))

    sent = 0
    for wa_user_id, entry in users_for_org(str(org_slug)):
        if event_type in entry.get("alerts", []) or event_type == "webhook.test":
            await _send_reply(wa_user_id, msg + "\n(AI-free automated alert)")
            audit.log_event(actor="themisiq", tenant_id=entry["tenant_id"],
                            action="proactive_alert", target=event_type, ok=True)
            sent += 1
    log.info("event %s for org %s fanned out to %d users", event_type, org_slug, sent)
    return Response(status_code=200)
```

Import `users_for_org` in main.py's config import line.

### Step 5: Persist the privacy-notice marker and dedupe redeliveries

In `main.py`, replace `_SEEN_INTRO: set[str] = set()` with a small persisted set:

```python
_SEEN_INTRO_PATH = Path("seen_intro.json")
def _load_seen() -> set[str]:
    try:
        return set(json.loads(_SEEN_INTRO_PATH.read_text(encoding="utf-8")))
    except Exception:
        return set()
_SEEN_INTRO: set[str] = _load_seen()
def _mark_seen(uid: str) -> None:
    _SEEN_INTRO.add(uid)
    try:
        _SEEN_INTRO_PATH.write_text(json.dumps(sorted(_SEEN_INTRO)), encoding="utf-8")
    except Exception:
        pass
```

(add `from pathlib import Path` to imports). In `_handle_user_message`, replace `_SEEN_INTRO.add(wa_user_id)` with `_mark_seen(wa_user_id)`.

Message dedupe: Meta retries webhook delivery on slow/failed acks, which would double-process a message. In `_extract_wa_message`, also return the message id (`msg.get("id", "")`) so it becomes a 3-tuple, and in `wa_inbound` keep a bounded in-memory set:

```python
_SEEN_MSG_IDS: "collections.OrderedDict[str, None]" = collections.OrderedDict()

    wa_user_id, text, msg_id = _extract_wa_message(payload)
    if msg_id:
        if msg_id in _SEEN_MSG_IDS:
            return Response(status_code=200)
        _SEEN_MSG_IDS[msg_id] = None
        while len(_SEEN_MSG_IDS) > 500:
            _SEEN_MSG_IDS.popitem(last=False)
```

(add `import collections`).

### Step 6: Async WhatsApp sends

`_send_reply` currently calls blocking `httpx.post` inside an async handler, freezing the event loop during sends. Convert to the async client:

```python
async def _send_reply(wa_user_id: str, text: str) -> None:
    if settings.offline_mode:
        log.info("[offline] would send to %s: %s", wa_user_id, text[:80])
        return
    import httpx
    async with httpx.AsyncClient(timeout=10) as c:
        if settings.wa_provider == "twilio":
            url = (f"https://api.twilio.com/2010-04-01/Accounts/"
                   f"{settings.twilio_account_sid}/Messages.json")
            data = {"From": f"whatsapp:{settings.twilio_from_number}",
                    "To": f"whatsapp:{wa_user_id}", "Body": text[:1600]}
            await c.post(url, data=data, auth=(settings.twilio_account_sid,
                                               settings.twilio_auth_token))
        else:
            url = (f"https://graph.facebook.com/{settings.wa_api_version}/"
                   f"{settings.wa_phone_number_id}/messages")
            body = {"messaging_product": "whatsapp", "to": wa_user_id,
                    "type": "text", "text": {"body": text[:4096]}}
            await c.post(url, json=body,
                         headers={"Authorization": f"Bearer {settings.wa_token}"})
```

### Step 7: Update .env.example, tests, README

- `.env.example`: add `WA_APP_SECRET=`, change `AI_MODEL=claude-opus-4-8`, keep `OFFLINE_MODE=true` as the local default.
- `tests\tenant_map.test.json`: add `org_slug` and `alerts` keys to the test entry.
- `tests\test_smoke.py`: update for the 3-tuple `_extract_wa_message`; add tests: (a) `users_for_org` returns the test user; (b) posting a `webhook.test` themis event in offline mode returns 200 and logs a `proactive_alert` audit line; (c) duplicated `msg_id` is processed once (assert only one audit line for the action).
- `README.md`: correct the endpoint table text, add `WA_APP_SECRET` to the wiring section, and note the ThemisIQ webhook should subscribe to exactly the event types listed in Step 4's template dict.

## Edge cases a weaker model would miss

1. **Meta signs with the app secret, not the verify token.** The verify token is only for the GET handshake. Confusing the two (the current bug) means production signature checks always fail or, worse, are skipped. Keep them as two separate settings.
2. **Fail closed.** With no `wa_app_secret` configured outside offline mode, the endpoint must return 503, not process unsigned traffic. The original code silently skipped verification when the token was empty.
3. **The webhook payload's org field is the tenant SLUG** (PLAN-02 sends `"organisation": slug`). The tenant_map therefore needs `org_slug` per user; do not try to match on numeric ids.
4. **Ack fast, always 200.** Meta and the ThemisIQ dispatcher both retry non-2xx responses. Unknown event types, unbound users, and empty payloads must still return 200 or you cause retry storms (and duplicate WhatsApp messages).
5. **Message dedupe is required precisely because of those retries.** Without the `msg_id` set, a slow LLM answer (>10s) makes Meta redeliver and the user gets two answers and two audit lines.
6. **Blocking httpx in async handlers** stalls every concurrent request during network sends. The async client fix matters most for fan-out (N sends in a loop).
7. **Twilio body limit is 1600 chars** vs Meta's 4096. The truncation values differ deliberately.
8. **`format_map` with a `_SafeDict`** so a missing payload key renders `n/a` instead of throwing `KeyError` inside the webhook handler (which would turn into retries, see item 4).
9. **Do not log message text into the audit log.** The DPIA separates 90-day message logs from the 7-year audit log. The audit entries log actions and event types only; keep it that way (the `detail=str(exc)[:200]` on errors is acceptable, but never add `detail=text`).
10. **`seen_intro.json` and `tenant_map.json` live in the service working directory** and must be excluded from git (check `.gitignore`; add both).
11. **`X-ThemisIQ-Signature` verification uses the raw body bytes** already captured before JSON parsing; do not reorder the code to parse first.
12. **The bridge's API key per tenant must be created with module scopes matching the user's modules** (PLAN-01 checkboxes). The bridge's own RBAC gate (`intent._gate`) is defense in depth on top, not a replacement.

## Acceptance criteria (verify each)

1. `python tests/test_smoke.py` (or pytest) passes offline with no network and no secrets.
2. With `OFFLINE_MODE=false`, no `WA_APP_SECRET`, POST to `/webhook/whatsapp` returns 503.
3. With `WA_APP_SECRET=test`: a POST with a correctly computed `X-Hub-Signature-256` (HMAC-SHA256 of the exact raw body, prefixed `sha256=`) is accepted; a tampered body returns 401 and an audit line `wa_verify ok=false`.
4. Against a running ThemisIQ with a scoped key in `tenant_map.json`: sending `list open DSRs` from the bound WhatsApp number returns real DSR ref numbers within seconds; `KRI status` returns the emoji status lines; `what is my risk score?` returns the summary with top risks.
5. A user whose `modules` lacks `erm` gets the "Access denied" message for `KRI status`, and the audit log shows `rbac_denied`.
6. An unbound WhatsApp number gets the "not linked" message and an `unbound_user` audit line.
7. In ThemisIQ admin, create a webhook to `https://<bridge>/webhook/themisiq` with the shared secret and events `webhook.test,sentinel.breach.confirmed`. Click Test (PLAN-02): the bound WhatsApp user with `webhook.test`-eligible mapping receives the test message.
8. Confirm a breach in Sentinel: subscribed users receive the 🚨 alert; users of another org receive nothing; the bridge audit log shows one `proactive_alert` line per recipient.
9. Redeliver the same Meta payload twice (same message id): exactly one reply is sent.
10. Restart the bridge: a user who already received the privacy notice does not receive it again (seen_intro.json persisted).
11. `git status` in the bridge folder never shows `tenant_map.json`, `seen_intro.json`, `.env`, or `audit.log.jsonl` as tracked files.
