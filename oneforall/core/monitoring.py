"""
Monitoring integration — Sentry (error tracking) and PostHog (analytics).

Both are optional: functions are no-ops when env vars are not configured.
"""
import logging

_log = logging.getLogger("oneforall.monitoring")
_posthog = None


def init_monitoring(settings) -> None:
    """Initialise Sentry and PostHog from settings. Call once at startup."""
    global _posthog

    if settings.SENTRY_DSN:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.starlette import StarletteIntegration
            sentry_sdk.init(
                dsn=settings.SENTRY_DSN,
                integrations=[StarletteIntegration(), FastApiIntegration()],
                traces_sample_rate=0.05,
                environment=settings.SENTRY_ENVIRONMENT,
                send_default_pii=False,
            )
            _log.info("Sentry enabled (environment=%s)", settings.SENTRY_ENVIRONMENT)
        except Exception as exc:
            _log.warning("Sentry init failed (non-fatal): %s", exc)

    if settings.POSTHOG_API_KEY:
        try:
            import posthog as _ph
            _ph.api_key = settings.POSTHOG_API_KEY
            _ph.host = settings.POSTHOG_HOST
            _ph.on_error = lambda status, msg: _log.warning(
                "PostHog error %s: %s", status, msg
            )
            _posthog = _ph
            _log.info("PostHog enabled (host=%s)", settings.POSTHOG_HOST)
        except Exception as exc:
            _log.warning("PostHog init failed (non-fatal): %s", exc)


def ph_capture(distinct_id: str, event: str, properties: dict | None = None) -> None:
    """Capture a server-side PostHog event. No-op if PostHog is not configured."""
    if _posthog is None:
        return
    try:
        _posthog.capture(distinct_id, event, properties or {})
    except Exception as exc:
        _log.debug("PostHog capture failed: %s", exc)


def ph_identify(distinct_id: str, properties: dict | None = None) -> None:
    """Identify a user in PostHog. No-op if PostHog is not configured."""
    if _posthog is None:
        return
    try:
        _posthog.identify(distinct_id, properties or {})
    except Exception as exc:
        _log.debug("PostHog identify failed: %s", exc)
