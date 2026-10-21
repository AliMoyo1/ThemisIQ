# PLAN-02: Outbound Webhook Dispatcher (make the webhooks feature real)

## Goal

ThemisIQ has a webhooks admin UI, a `webhooks` table, and a `webhook_logs` table, but nothing ever delivers a webhook. Build the dispatcher:

1. When `core/events.py` `emit()` fires an event, matching active webhooks for the current tenant receive an HTTPS POST.
2. Payloads are HMAC-SHA256 signed (`X-ThemisIQ-Signature: sha256=<hex>`), as the Platform Manual promises.
3. Up to 3 delivery attempts with backoff; every attempt logged to `webhook_logs`.
4. Delivery is fully non-blocking and can never break or slow the user operation that emitted the event.
5. A "Send test event" admin endpoint + button so delivery can be verified without triggering real events.

This is what enables proactive WhatsApp alerts (PLAN-03), and it benefits every customer integration.

## Files to touch

- `oneforall\core\webhook_dispatcher.py` (NEW)
- `oneforall\core\events.py` (one hook call in `emit`)
- `oneforall\modules\launcher\routes_admin.py` (test endpoint)
- `oneforall\modules\launcher\templates\admin_webhooks.html` (test button)
- `oneforall\tests\test_webhook_dispatcher.py` (new file)

## Steps in order

### Step 1: Create `oneforall\core\webhook_dispatcher.py`

```python
"""
Outbound webhook delivery.

Called from core.events.emit() after handlers run. Delivery happens on a
daemon worker thread so the emitting request never waits on network I/O.
Payloads are HMAC-SHA256 signed with each webhook's secret:
    X-ThemisIQ-Signature: sha256=<hex hmac of the raw request body>
Every attempt is recorded in webhook_logs. 3 attempts, backoff 2s / 10s.
"""
import hashlib
import hmac
import ipaddress
import json
import logging
import queue
import socket
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

log = logging.getLogger("oneforall.webhooks")

_QUEUE: "queue.Queue[dict]" = queue.Queue(maxsize=1000)
_WORKER_STARTED = False
_START_LOCK = threading.Lock()

_ATTEMPTS = 3
_BACKOFF_SECONDS = (0, 2, 10)
_TIMEOUT = 10.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _url_is_safe(url: str) -> bool:
    """Block non-HTTPS and private/loopback targets (SSRF guard).
    Mirrors the create-time validation in routes_admin, re-checked at send
    time because DNS can change between creation and delivery."""
    try:
        p = urlparse(url)
        if p.scheme != "https" or not p.hostname:
            return False
        infos = socket.getaddrinfo(p.hostname, p.port or 443)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True
    except Exception:
        return False


def _event_matches(subscribed_csv: str, event_type: str) -> bool:
    """events column is CSV. '*' matches all. 'sentinel.*' matches prefix."""
    for token in (subscribed_csv or "").split(","):
        token = token.strip()
        if not token:
            continue
        if token == "*" or token == event_type:
            return True
        if token.endswith(".*") and event_type.startswith(token[:-1]):
            return True
    return False


def dispatch(event_type: str, source_module: str, entity_type: str,
             entity_id: int, payload: dict, tenant_slug: str | None) -> None:
    """Fan an event out to this tenant's webhooks. Non-blocking, never raises."""
    try:
        _ensure_worker()
        _QUEUE.put_nowait({
            "event_type": event_type,
            "source_module": source_module,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload": payload or {},
            "tenant_slug": tenant_slug,
            "queued_at": _now_iso(),
        })
    except queue.Full:
        log.warning("webhook queue full; dropping event %s", event_type)
    except Exception:
        log.exception("webhook dispatch enqueue failed")


def _ensure_worker() -> None:
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    with _START_LOCK:
        if _WORKER_STARTED:
            return
        t = threading.Thread(target=_worker, name="webhook-dispatcher", daemon=True)
        t.start()
        _WORKER_STARTED = True


def _worker() -> None:
    while True:
        job = _QUEUE.get()
        try:
            _process(job)
        except Exception:
            log.exception("webhook job failed")
        finally:
            _QUEUE.task_done()


def _process(job: dict) -> None:
    # Imported here (not module top) to avoid circular imports at startup,
    # and because this runs on the worker thread.
    from database import get_db, set_current_tenant

    slug = job.get("tenant_slug")
    # Contextvars do NOT cross threads: re-establish tenant context here.
    set_current_tenant(slug or "public")

    db = get_db()
    try:
        hooks = db.execute(
            "SELECT id, url, secret, events FROM webhooks WHERE is_active=1"
        ).fetchall()
    finally:
        db.close()

    matching = [dict(h) for h in hooks
                if _event_matches(h["events"], job["event_type"])]
    if not matching:
        return

    body_obj = {
        "event_type": job["event_type"],
        "source_module": job["source_module"],
        "entity_type": job["entity_type"],
        "entity_id": job["entity_id"],
        "payload": job["payload"],
        "organisation": slug,
        "timestamp": job["queued_at"],
    }
    raw = json.dumps(body_obj, ensure_ascii=False, default=str).encode("utf-8")

    for hook in matching:
        _deliver_one(slug, hook, job["event_type"], raw)


def _deliver_one(slug: str | None, hook: dict, event_type: str, raw: bytes) -> None:
    import httpx
    from database import get_db, set_current_tenant

    if not _url_is_safe(hook["url"]):
        _log_attempt(slug, hook["id"], event_type, raw, None, "blocked: unsafe URL", False)
        return

    headers = {"Content-Type": "application/json",
               "User-Agent": "ThemisIQ-Webhook/1.0"}
    if hook.get("secret"):
        sig = hmac.new(hook["secret"].encode(), raw, hashlib.sha256).hexdigest()
        headers["X-ThemisIQ-Signature"] = "sha256=" + sig

    for attempt in range(_ATTEMPTS):
        time.sleep(_BACKOFF_SECONDS[attempt])
        code, resp_body, ok = None, "", False
        try:
            r = httpx.post(hook["url"], content=raw, headers=headers,
                           timeout=_TIMEOUT, follow_redirects=False)
            code, resp_body = r.status_code, r.text[:500]
            ok = 200 <= r.status_code < 300
        except Exception as exc:
            resp_body = str(exc)[:500]
        _log_attempt(slug, hook["id"], event_type, raw, code, resp_body, ok)
        if ok:
            return


def _log_attempt(slug, webhook_id, event_type, raw, code, resp_body, ok) -> None:
    from database import get_db, set_current_tenant
    try:
        set_current_tenant(slug or "public")
        db = get_db()
        try:
            db.execute(
                "INSERT INTO webhook_logs (webhook_id, event, payload_json,"
                " response_code, response_body, success, attempted_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (webhook_id, event_type, raw.decode("utf-8")[:4000],
                 code, resp_body, 1 if ok else 0, _now_iso()),
            )
            db.commit()
        finally:
            db.close()
    except Exception:
        log.exception("webhook log write failed")
```

### Step 2: Hook into the event bus

In `oneforall\core\events.py`, inside `emit(...)`, AFTER the handler loop (`for handler in handlers: ...` block) and before the function ends, add:

```python
    # Outbound webhooks (non-blocking; never breaks the emitting operation)
    try:
        from database import get_current_tenant
        from core.webhook_dispatcher import dispatch
        dispatch(event_type, source_module, entity_type, entity_id,
                 payload or {}, get_current_tenant())
    except Exception:
        log.exception("webhook dispatch failed for %s", event_type)
```

Capture the tenant HERE (on the request thread) and pass it in. Do not read it inside the worker thread.

### Step 3: Admin test endpoint

In `routes_admin.py`, after the webhook delete endpoint (anchor: `async def api_webhook_delete`), add:

```python
@router.post("/api/admin/webhooks/{wid}/test")
@require_admin_or_higher
async def api_webhook_test(request: Request, wid: int):
    """Fire a synthetic test event at one webhook."""
    user = request.state.user
    db = get_db()
    try:
        row = _get_webhook_for_admin(db, wid, user)
    finally:
        db.close()
    if not row:
        raise HTTPException(status_code=404, detail="Webhook not found")
    from database import get_current_tenant
    from core.webhook_dispatcher import dispatch
    dispatch("webhook.test", "platform", "webhook", wid,
             {"message": "Test delivery from ThemisIQ"}, get_current_tenant())
    return _JSONResp({"queued": True})
```

Copy the exact decorator used by the sibling webhook endpoints in this file (check whether they use `@require_admin_or_higher` or another guard, and match it). Note the test event type is `webhook.test`: a webhook must have `*` in its events list (or `webhook.test`) to receive it; return that hint in the UI text.

### Step 4: Test button in the UI

In `templates\admin_webhooks.html`, find where each webhook row's action buttons are rendered (near the delete button). Add a "Test" button that calls the new endpoint with the row id and then refreshes the delivery-logs view. Match the page's existing fetch pattern (including any CSRF header the other calls send; copy exactly what the delete call sends).

### Step 5: Document the event catalogue in the UI

In `admin_webhooks.html`, where the events input/help text is, list the real event types so users subscribe to strings that actually fire:

`sentinel.breach.confirmed, sentinel.breach.resolved, sentinel.dpia.completed, sentinel.dsr.overdue, erm.risk.identified, erm.risk.escalated, erm.risk.closed, erm.appetite.breached, bcm.incident.declared, bcm.incident.resolved, bcm.plan.activated, grid.audit.completed, grid.finding.created, grid.non_conformance.raised, aria.policy.published, framework.activated, vendor.created, webhook.test` plus wildcard forms `*` and `sentinel.*`.

### Step 6: Tests

Create `oneforall\tests\test_webhook_dispatcher.py`:

1. `_event_matches`: exact match true; `*` true; `sentinel.*` matches `sentinel.breach.confirmed`; empty CSV false; `erm.*` does not match `sentinel.breach.confirmed`.
2. `_url_is_safe`: `http://example.com` false; `https://127.0.0.1/x` false; `https://10.0.0.5/x` false (use monkeypatched `socket.getaddrinfo` so tests are offline-deterministic).
3. Signature: build the HMAC the same way and assert a receiver-side verify function accepts it (reuse the bridge's `verify_themis_signature` logic inline).
4. `_process` with a monkeypatched `httpx.post` returning 200 writes one `webhook_logs` row with success=1; returning 500 three times writes 3 rows with success=0 (monkeypatch `time.sleep` to avoid real backoff waits).

## Edge cases a weaker model would miss

1. **Contextvars do not propagate to new threads.** `get_current_tenant()` inside the worker thread would return the default, so the dispatcher would read the WRONG tenant's webhooks. The tenant slug must be captured in `emit()` on the request thread and passed through the queue. This is the single most important line of the plan.
2. **Delivery must never block or break the emitting operation.** Everything in `emit()`'s hook is wrapped in try/except and the actual network I/O happens on the daemon worker. Do not `await` or `httpx.post` inline in `emit()`.
3. **`time.sleep` backoff is fine on the worker thread but would be catastrophic on the request thread.** Keep the sleeps inside `_worker`/`_deliver_one` only.
4. **Re-validate the URL at send time**, not only at creation: DNS for a stored hostname can be repointed to an internal IP later (SSRF via DNS rebinding). The `_url_is_safe` resolver check handles this.
5. **`follow_redirects=False`.** A 302 to an internal address would bypass the SSRF check. Treat any 3xx as failure.
6. **Sign the exact raw bytes you send** (`content=raw`), not a re-serialized dict. `json=` in httpx would re-serialize with different spacing and break receiver-side HMAC verification.
7. **`default=str` in `json.dumps`**: event payloads can contain datetimes or Decimals; without it the worker throws and the event silently disappears.
8. **Bounded queue with drop + warning** instead of unbounded growth if a target endpoint is down for hours.
9. **Daemon thread + lazy start.** Starting the thread at import time breaks test collection and multiple-worker setups; `_ensure_worker` starts it on first dispatch. Daemon=True so shutdown is not blocked.
10. **`webhook_logs.payload_json` truncation (4000 chars)** so a huge payload cannot bloat the table; `response_body` capped at 500 like the column intends.
11. **Events emitted with no tenant context** (seeders, migrations, schedulers): slug is None; the code falls back to `public` schema, which will simply find no webhooks. Do not raise.
12. **Circular imports:** `core.events` is imported by nearly everything, so `webhook_dispatcher` must import `database` lazily inside functions, and `events.py` must import the dispatcher inside `emit`, not at module top.
13. **Do not send webhooks for `webhook.test` recursively** or loop protection generally: if a customer points a webhook at a ThemisIQ endpoint that emits events, delivery could loop. The bounded queue and the fact that inbound API is read-only keeps this contained; do not add write endpoints that emit events from webhook receipt.
14. **Scheduler-emitted events** (e.g. `sentinel.dsr.overdue` from `modules/sentinel/scheduler.py`) run outside a request. Check how that scheduler establishes tenant context (it iterates tenants); the dispatch hook in `emit` picks up whatever `get_current_tenant()` returns at that moment, which is correct as long as the scheduler sets tenant per iteration (it must, to query tenant tables). Verify once manually.

## Acceptance criteria (verify each)

1. Create a webhook in Admin pointing at a request-inspection endpoint you control (for local testing run `python -m http.server` behind an https tunnel, or use a disposable webhook-inspection service for non-sensitive test payloads), events `*`.
2. Click the new Test button: within seconds the endpoint receives a POST with JSON body containing `"event_type": "webhook.test"`, header `X-ThemisIQ-Signature: sha256=...`, and `Content-Type: application/json`.
3. Recompute the HMAC-SHA256 of the received raw body with the webhook secret: it equals the header value after `sha256=`.
4. The Delivery Logs view for that webhook shows the attempt with response code and success=1.
5. Confirm a breach in Sentinel (status change that fires `sentinel.breach.confirmed`): the webhook receives it; a webhook subscribed only to `erm.*` does NOT receive it.
6. Point a webhook at an unreachable HTTPS URL and fire a test: exactly 3 log rows appear for it (success=0), spaced by the backoff, and the admin UI action that triggered the event returned instantly (no multi-second hang).
7. Create a webhook with URL `https://localhost/x` via direct DB edit (creation UI blocks it): delivery is refused and logged as `blocked: unsafe URL`.
8. With two tenants configured, fire an event in tenant A: tenant B's webhooks receive nothing (check both tenants' logs).
9. `pytest oneforall/tests/test_webhook_dispatcher.py` passes; existing tests still pass.
10. Restart the app: the worker starts lazily on the next event with no startup errors in logs.
