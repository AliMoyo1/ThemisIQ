"""ThemisIQ WhatsApp Assistant Bridge.

A thin, read-only, multi-tenant bridge between WhatsApp Business Platform and
ThemisIQ's REST API + AI providers. See ThemisIQ_WhatsApp_Assistant_Plan.md
(Part A architecture, Part B DPIA).

Security posture (inherited from ThemisIQ's own hardening findings):
  - Never put secrets in URLs or git (F-01/F-08).
  - HMAC-verify every inbound payload (Meta webhook + ThemisIQ webhook).
  - Per-tenant API keys; bridge never crosses tenant boundaries.
  - Append-only audit log; rate limiting on inbound.
"""

__version__ = "0.1.0"
