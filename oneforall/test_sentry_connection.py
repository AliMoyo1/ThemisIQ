"""Run once on the VPS to confirm Sentry receives events. Delete after use."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

lines = open("/project/.env").readlines()
dsn = next(
    (l.split("=", 1)[1].strip() for l in lines if l.startswith("SENTRY_DSN=")), ""
)

if not dsn:
    print("ERROR: SENTRY_DSN not found in /project/.env")
    sys.exit(1)

import sentry_sdk

sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0)
sentry_sdk.capture_message("ThemisIQ VPS connectivity test", level="info")
sentry_sdk.flush(timeout=5)
print("Test event sent. Check Sentry dashboard in a few seconds.")
