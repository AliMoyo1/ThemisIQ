/**
 * Shared fetch wrapper for /api/* calls (PLAN-36 T06, findings.md F08).
 *
 * One place that turns every response or transport failure into either the
 * parsed success value or a typed ApiError -- so a proxy HTML page, a
 * malformed JSON body, a 401, or a dropped connection can no longer surface
 * as a silent no-op or an uncaught secondary error. Never retries a mutation
 * automatically (the caller decides; a user re-clicking a button already is
 * the retry mechanism used throughout this app).
 *
 * Usage:
 *   try {
 *     const data = await ApiClient.request('/api/admin/webhooks', {
 *       method: 'POST', body: { name, url, events }, actionId: 'webhooks.create',
 *     });
 *   } catch (err) {
 *     if (err instanceof ApiClient.ApiError) showToast(err.detail, 'error');
 *   }
 *
 *   await ApiClient.withButtonState(btn, { pendingLabel: 'Saving...', fn: () => ApiClient.request(...) });
 *
 * request(url, options):
 *   method, body (object -> JSON, FormData, or string), headers,
 *   expect: 'json'|'text'|'blob'|'none' (default 'json'; 'blob' returns
 *   {blob, filename} for a file download, filename read from
 *   Content-Disposition when present), timeoutMs (default 20000),
 *   idempotencyKey (sent as the Idempotency-Key header when given; no route
 *   currently deduplicates on it server-side, so this only prepares the wire
 *   format -- the client itself never auto-retries regardless), signal (an
 *   AbortSignal the caller controls, e.g. from a component teardown),
 *   actionId (a short string used only for the telemetry event below, never
 *   logged with form content or personal data).
 *
 * ApiError fields: status (0 for network/timeout/abort), detail (short,
 * always safe to render directly -- never a raw response body, stack trace,
 * or SQL error), retryable (boolean), requestId (from the X-Request-ID
 * response header, or null), kind: 'network'|'timeout'|'abort'|'auth'|
 * 'forbidden'|'validation'|'conflict'|'rate_limit'|'server'|'parse'|'unknown',
 * retryAfterSeconds (parsed from a 429's Retry-After header, or null).
 */
(function (global) {
  'use strict';

  var _TIMEOUT_REASON = '__api_client_timeout__';
  var RETRYABLE_KINDS = { network: 1, timeout: 1, server: 1, rate_limit: 1 };

  class ApiError extends Error {
    constructor(message, fields) {
      super(message);
      this.name = 'ApiError';
      this.status = fields.status;
      this.detail = fields.detail;
      this.retryable = fields.retryable;
      this.requestId = fields.requestId || null;
      this.kind = fields.kind;
      this.retryAfterSeconds = fields.retryAfterSeconds || null;
      this.body = fields.body || null; // the parsed JSON error body, when there is one -- for
                                        // a caller that needs more than the safe .detail string
    }
  }

  function classify(status) {
    if (status === 401) return 'auth';
    if (status === 403) return 'forbidden';
    if (status === 409) return 'conflict';
    if (status === 429) return 'rate_limit';
    if (status === 400 || status === 422) return 'validation';
    if (status >= 500) return 'server';
    return 'unknown';
  }

  function defaultDetailFor(status) {
    if (status === 401) return 'Your session has expired. Please sign in again.';
    if (status === 403) return 'You do not have permission to do that.';
    if (status === 404) return 'Not found.';
    if (status === 409) return 'This was changed by someone else. Please refresh and try again.';
    if (status === 429) return 'Too many requests. Please wait a moment and try again.';
    if (status >= 500) return 'Something went wrong on our end. Please try again.';
    return 'The request could not be completed.';
  }

  function reportTelemetry(actionId, status, durationMs, requestId) {
    try {
      if (global.posthog && typeof global.posthog.capture === 'function') {
        global.posthog.capture('api_request', {
          action_id: actionId || null,
          status_class: status ? Math.floor(status / 100) + 'xx' : 'network',
          duration_ms: Math.round(durationMs),
          request_id: requestId || null,
        });
      }
    } catch (err) { /* telemetry must never break the caller */ }
  }

  async function request(url, options) {
    options = options || {};
    var method = options.method || 'GET';
    var expect = options.expect || 'json';
    var timeoutMs = options.timeoutMs || 20000;
    var actionId = options.actionId || null;
    var start = (global.performance || Date).now();

    var controller = new AbortController();
    var timedOut = false;
    var timer = setTimeout(function () {
      timedOut = true;
      controller.abort(_TIMEOUT_REASON);
    }, timeoutMs);
    var externalSignal = options.signal;
    if (externalSignal) {
      if (externalSignal.aborted) controller.abort(externalSignal.reason);
      else externalSignal.addEventListener('abort', function () { controller.abort(externalSignal.reason); });
    }

    var headers = Object.assign({}, options.headers || {});
    var body = options.body;
    var sendBody = null;
    if (body !== undefined && body !== null) {
      if (body instanceof FormData || typeof body === 'string') {
        sendBody = body;
      } else {
        if (!headers['Content-Type']) headers['Content-Type'] = 'application/json';
        sendBody = JSON.stringify(body);
      }
    }
    if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey;

    var response;
    try {
      response = await fetch(url, {
        method: method,
        headers: headers,
        credentials: 'same-origin', // JSON /api/* routes rely on the Origin-check
        body: sendBody,             // + SameSite cookie middleware, not a form CSRF token
        signal: controller.signal,
      });
    } catch (err) {
      clearTimeout(timer);
      var kind = timedOut ? 'timeout' : (controller.signal.reason && controller.signal.reason !== _TIMEOUT_REASON ? 'abort' : 'network');
      var msg = kind === 'timeout' ? 'Request timed out.'
        : kind === 'abort' ? 'Request cancelled.'
        : 'Network error. Check your connection.';
      reportTelemetry(actionId, 0, (global.performance || Date).now() - start, null);
      throw new ApiError(msg, { status: 0, detail: msg, retryable: kind !== 'abort', requestId: null, kind: kind });
    }
    clearTimeout(timer);

    var requestId = response.headers.get('X-Request-ID');
    var contentType = response.headers.get('Content-Type') || '';
    var durationMs = (global.performance || Date).now() - start;

    // Check authentication redirects before handling ANY success response
    // mode. In particular, report downloads use expect:'blob': if this check
    // runs after the blob branch, an expired session saves the /login HTML as
    // report.pdf/report.docx and the caller displays a false success toast.
    // The same ordering protects text and none callers.
    var loginRedirect = response.redirected
      && /\/login(?:[/?#]|$)/.test(new URL(response.url).pathname);
    if (loginRedirect) {
      var sessionMsg = 'Your session has expired. Please sign in again.';
      reportTelemetry(actionId, 401, durationMs, requestId);
      throw new ApiError(sessionMsg, {
        status: 401,
        detail: sessionMsg,
        retryable: false,
        requestId: requestId,
        kind: 'auth',
      });
    }

    if (response.ok) {
      reportTelemetry(actionId, response.status, durationMs, requestId);
      if (expect === 'none' || response.status === 204) return null;
      if (expect === 'text') return await response.text();
      if (expect === 'blob') {
        var blob = await response.blob();
        var cd = response.headers.get('Content-Disposition') || '';
        var fnMatch = cd.match(/filename="?([^";\n]+)"?/);
        return { blob: blob, filename: fnMatch ? fnMatch[1] : null };
      }
      if (contentType.indexOf('application/json') !== -1) {
        try {
          return await response.json();
        } catch (err) {
          throw new ApiError('Server returned an invalid response.', {
            status: response.status, detail: 'Server returned an invalid response.',
            retryable: false, requestId: requestId, kind: 'parse',
          });
        }
      }
      // expect defaults to 'json' and none of the branches above matched,
      // so the caller asked for (or implicitly expects) JSON but got a
      // non-JSON 200. This is not a legitimate success case: the most
      // common real cause is a session that expired mid-request -- the
      // auth middleware redirects to /login, fetch's default
      // redirect:'follow' silently follows it, and /login itself answers
      // 200 with an HTML page. Returning that HTML (or any other non-JSON
      // body) as if it were the successful payload let every caller's
      // success path fire -- "Saved"/"Delivered" toasts -- for a mutation
      // that never actually ran. The login-redirect case is handled before
      // all response-mode branches above; any other non-JSON 200 still throws
      // rather than silently degrading to raw truncated text.
      var unexpectedMsg = 'Server returned an unexpected response.';
      throw new ApiError(unexpectedMsg, {
        status: response.status,
        detail: unexpectedMsg,
        retryable: false,
        requestId: requestId,
        kind: 'parse',
      });
    }

    reportTelemetry(actionId, response.status, durationMs, requestId);
    var detail = '';
    if (contentType.indexOf('application/json') !== -1) {
      try {
        var data = await response.json();
        detail = (data && (data.detail || data.error)) || '';
      } catch (err) { /* body wasn't valid JSON despite its content-type; fall through */ }
    }
    var errKind = classify(response.status);
    var safeDetail = (typeof detail === 'string' && detail.length && detail.length < 500)
      ? detail : defaultDetailFor(response.status);
    var retryAfterHeader = response.headers.get('Retry-After');
    var retryAfterSeconds = retryAfterHeader && /^\d+$/.test(retryAfterHeader) ? parseInt(retryAfterHeader, 10) : null;

    throw new ApiError(safeDetail, {
      status: response.status,
      detail: safeDetail,
      retryable: !!RETRYABLE_KINDS[errKind],
      requestId: requestId,
      kind: errKind,
      retryAfterSeconds: retryAfterSeconds,
      body: (typeof data !== 'undefined' && data) || null,
    });
  }

  /** Disable `button`, swap its label to `pendingLabel`, run `fn`, and
   * always restore the original disabled/label state -- the exact pattern
   * hand-rolled in admin_webhooks.html's Test button (PLAN-36 T05), lifted
   * here so it also suppresses double-clicks for every other caller. */
  async function withButtonState(button, opts) {
    opts = opts || {};
    if (!button || button.disabled) return undefined;
    var original = button.textContent;
    button.disabled = true;
    if (opts.pendingLabel) button.textContent = opts.pendingLabel;
    try {
      return await opts.fn();
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  global.ApiClient = { request: request, ApiError: ApiError, withButtonState: withButtonState };
})(window);
