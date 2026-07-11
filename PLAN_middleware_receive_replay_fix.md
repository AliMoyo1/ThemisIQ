# Fix: sanitize_json_middleware breaks ASGI receive() contract

**Bug:** Intermittent unhandled 500s on POST/PUT/DELETE (confirmed on POST /erm/api/appetite,
platform-wide since it's global middleware). Server log:
`RuntimeError: Unexpected message received: http.request`, raised via Starlette's
`BaseHTTPMiddleware` disconnect-listening machinery, propagating through
`tenant_context_middleware`.

**Root cause (confirmed by reading installed Starlette 0.37.2 source,
`site-packages/starlette/middleware/base.py` `_CachedRequest.wrapped_receive` +
`starlette/requests.py` `Request.stream`):**

`sanitize_json_middleware` (`oneforall/core/middleware.py:429`) reads the body, sanitizes it,
then does://
```python
async def receive():
    return {"type": "http.request", "body": sanitized_bytes}
request._receive = receive
```
This closure unconditionally replays the same `http.request` message on *every* call, with no
`more_body: False` and no passthrough to the real channel. Starlette's `_CachedRequest.wrapped_receive`
calls the *replaced* `_receive` a second time once its own cached-body handoff is consumed, expecting
only `http.disconnect` at that point — getting `http.request` again raises the RuntimeError. This
reproduces under keep-alive/rapid successive requests because that's when the disconnect-listener
loop (`starlette/responses.py: listen_for_disconnect`) actually gets to its second `receive()` call
before the connection naturally ends.

**Second bug found during investigation (same anti-pattern, more severe, silent):** Starlette's
`_CachedRequest.wrapped_receive` checks `self._body` *before* ever consulting `self._receive`
(see base.py lines 62-69). Since `sanitize_json_middleware` calls `await request.body()` (caching
the ORIGINAL bytes into `request._body`) *before* replacing `request._receive`, the `_receive`
replacement is dead code for the happy path too — downstream layers/handlers receive the cached
`request._body` (original, unsanitized) directly, never touching our closure. **The HTML-stripping
XSS sanitization this middleware exists to provide has not actually been applied to any downstream
request body, crash or no crash.** Fix must address both.

**Fix:** In `sanitize_json_middleware`:
1. Set `request._body = sanitized_bytes` directly — this is what `_CachedRequest`'s fast path
   actually forwards downstream, so this is what makes sanitization take effect for real.
2. Replace `request._receive` with a proper buffer-once-then-passthrough closure (returns the
   sanitized message with `more_body: False` exactly once, then delegates all subsequent calls to
   the original `_receive`) — defends the disconnect-listener path regardless of which internal
   Starlette code path ends up calling it, and keeps behavior correct if Starlette internals change.

**Files to touch:**
- `oneforall/core/middleware.py` (`sanitize_json_middleware`)

**Verification:**
- Script issuing rapid POST requests over a persistent `requests.Session()` (keep-alive) against
  POST /erm/api/appetite, confirm no "Unexpected message received" in logs and real status codes
  (not 500) on every request.
- Confirm sanitization actually strips tags now (previously silently broken) — POST a body containing
  `<script>` and check it's stripped in what the handler/DB actually receives.
- Run full pytest suite to check for regressions (global middleware, touches every JSON POST/PUT/PATCH).

## Change Log

- [done] `oneforall/core/middleware.py:429` (sanitize_json_middleware) - attempt 1:
  - Added `request._body = sanitized_bytes` (fixes sanitization actually reaching downstream).
  - PLUS replaced `receive()` with a buffer-once-then-passthrough closure.
  - Built a minimal repro harness (2 stacked BaseHTTPMiddleware layers, matching production's
    actual layering order) in scratchpad and confirmed via real uvicorn + rapid keep-alive
    requests.Session() POSTs that this attempt STILL crashed 60/60 with the exact reported
    RuntimeError. Root cause: Starlette's `_CachedRequest.wrapped_receive` delivers the buffered
    message via the `_body` fast path (bypassing our `receive()` closure entirely on that first
    delivery), then later calls the raw `_receive` a second time expecting ONLY a disconnect
    signal. Our closure's "already sent once" flag was never flipped by that first delivery, so
    it replayed the buffered message again on this second call, still tripping the same
    "Unexpected message received" crash. Confirmed this by testing "first_fix" mode explicitly
    (not just reasoning about it).
- [done] Corrected fix: removed the `receive()` replacement entirely. Only `request._body` is
  set; `request._receive` is left completely untouched (it's already a correctly-behaving ASGI
  channel; there was never a reason to wrap it once `_body` is set directly).
- [done] Syntax check (`python -m py_compile core/middleware.py`) passed.
- [done] Fixed an em dash I'd introduced in a new comment (project convention: no em dashes).
- [done] Verification via repro harness against the real, corrected `core/middleware.py`
  (imported directly, not reimplemented):
  - 60 rapid sequential POSTs on one keep-alive `requests.Session()`: 60/60 returned 200, zero
    crashes in server log.
  - Stress test: 8 concurrent keep-alive sessions x 40 requests = 320 total: 320/320 returned
    200, zero crashes.
  - Sanitization confirmed working: `<script>`/`<b>`/`<i>` tags stripped from the echoed body in
    every response (previously silently NOT stripped at all, a second bug found during
    investigation, now also fixed by the same one-line change).
  - Edge cases (non-JSON content-type, malformed JSON, empty JSON body) return 500 in the mini
    test harness, confirmed identical in "buggy" mode too, so this is the test route's own
    lack of a try/except around `request.json()`, unrelated to the middleware fix (production
    routes already guard this via `_json_body()`/Pydantic body parsing).
- [done] Full existing pytest suite: 77 passed, 0 failed (`oneforall/pytest.ini` config, run from
  `oneforall/`). Only pre-existing deprecation warnings (unrelated, from FastAPI/Python 3.14
  `asyncio.iscoroutinefunction`).

## Status: COMPLETE
