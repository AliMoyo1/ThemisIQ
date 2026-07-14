# ThemisIQ WhatsApp Assistant Bridge

A thin, **read-only, multi-tenant** bridge that lets authorised ThemisIQ users
interact with the platform from WhatsApp (or receive proactive compliance
alerts). Built as a small FastAPI service that sits *between* the WhatsApp
Business Platform and ThemisIQ's existing REST API + AI providers.

> Paired planning doc: `ThemisIQ_WhatsApp_Assistant_Plan.md`
> (Part A architecture, Part B DPIA — GDPR / CDPA / ISO 42001).

## Design principles (from the DPIA)
- **Read-only MVP** — no writes to live ThemisIQ records in Phase 1.
- **Per-tenant isolation** — the bridge never crosses tenant boundaries; each
  WhatsApp user is bound to exactly one tenant + role (admin-managed map).
- **RBAC enforced before any call** — a user can only query modules their
  ThemisIQ role permits.
- **HMAC-verified both ways** — inbound WhatsApp payloads and ThemisIQ
  outbound webhooks are signature-checked.
- **Append-only audit log** + rate limiting on every inbound message.
- **No secrets in URLs/git** (learned from ThemisIQ's own F-01/F-08 findings).

## Layout
```
app/
  __init__.py
  config.py        # env + per-tenant map (+ org_id -> subscriber reverse index)
  auth.py          # signature / challenge verification
  audit.py         # append-only audit log
  ratelimit.py     # in-memory limiter
  themis_client.py # ThemisIQ REST API client (GET-only MVP)
  llm.py           # LLM orchestration (anthropic/deepseek/openai/gemini/ollama)
  intent.py        # message -> action + RBAC gate
  main.py          # FastAPI app (webhooks + reply)
tests/
  test_smoke.py    # offline smoke test
.env.example
tenant_map.json.example
requirements.txt
```

## Quick start (local, offline)
```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # set OFFLINE_MODE=true for local testing
cp tenant_map.json.example tenant_map.json
python -m app.main              # runs via uvicorn (see bottom of main.py note)
# or: uvicorn app.main:app --reload --port 8000
```

Smoke test (no credentials, no network — LLM + WhatsApp sends stubbed):
```bash
python tests/test_smoke.py      # or: pytest tests/test_smoke.py
```

## Wiring to the real world
1. **WhatsApp**: create a Meta (Cloud API) or Twilio WhatsApp sender; set the
   webhook URL to `https://<your-bridge>/webhook/whatsapp`; configure
   `WA_VERIFY_TOKEN` / `WA_TOKEN` / `WA_PHONE_NUMBER_ID` (or Twilio creds).
2. **ThemisIQ**: in Command Centre → Developer → API Keys, create a
   **read-only, scoped** key per tenant. Put it in `tenant_map.json` alongside
   each user's `wa_id`, `tenant_id`, `role`, and allowed `modules`.
3. **Proactive alerts (implemented)**: ThemisIQ signs outbound webhooks with
   HMAC-SHA256 (`X-ThemisIQ-Signature`). To receive them:
   - In ThemisIQ → Webhooks, register `https://<your-bridge>/webhook/themisiq`
     as a target and subscribe to event types (e.g. `breach.created`,
     `risk.threshold_breached`, `dsar.created`, `dpia.created`).
   - Set `THEMIS_WEBHOOK_SECRET` in the bridge `.env` to **the same secret**
     ThemisIQ uses to sign (mismatch → HTTP 401).
   - Map each `tenant_map.json` entry to its ThemisIQ `organisation_id` via the
     **`org_id`** field (integer), OR use a top-level `org_subscriptions` block
     (`"<org_id>": ["wa_user_id", ...]`). When an event arrives, the bridge
     resolves `organisation_id` → subscribed `wa_user_id`s and fans out the
     alert to each, **scoped to that user's `modules`** (a user only receives
     pings for modules they can see — same RBAC as inbound queries).
   - Alerts are formatted as concise WhatsApp messages and audit-logged per
     recipient. In `OFFLINE_MODE` the send is stubbed (logged, not delivered).
4. **LLM**: set `AI_PROVIDER` + the matching key. Prefer a **zero-retention /
   enterprise** tier (see DPIA M6/M9).

## How proactive alerts are scoped
| Event type | Required module | Delivered to |
|------------|---------------|--------------|
| `breach.created` / `breach.updated` | `sentinel` | users with `sentinel` |
| `dsar.created` | `sentinel` | users with `sentinel` |
| `dpia.created` / `dpia.submitted` | `aria` | users with `aria` |
| `risk.threshold_breached` / `kri.status_changed` | `erm` | users with `erm` |
| `audit.logged` | `command_centre` | users with `command_centre` |
| `control.effectiveness_changed` | `governance` | users with `governance` |
| (unknown event) | — | all subscribers |

This keeps outbound alerts inside each recipient's read scope.

## Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/webhook/whatsapp` | Meta/Twilio verification handshake |
| POST | `/webhook/whatsapp` | inbound WhatsApp message → reply (HMAC-verified) |
| POST | `/webhook/themisiq` | ThemisIQ outbound webhook — HMAC-verified, fanned out to subscribed WhatsApp users (RBAC-scoped) |
| GET  | `/health`           | liveness |

## What users can say (Phase 1)
`help` · `list open risks` · `list open breaches` · `list audits` ·
`draft breach notification for incident <id>` · *any compliance question*.

Backed by ThemisIQ API v1: `/api/v1/risks`, `/api/v1/breaches`, `/api/v1/audits`.
Auth uses `X-API-Key` header (generate keys in ThemisIQ admin).

## Before production (DPIA checklist)
- [ ] DPO + controller sign-off on the DPIA
- [ ] Legitimate Interests Assessment attached
- [ ] LLM vendor zero-retention + DPA confirmed
- [ ] ROPA updated with Meta/Twilio + LLM sub-processors
- [ ] Privacy notice shown on first interaction (implemented)
- [ ] Per-tenant read-only keys issued; `tenant_map.json` populated & secured
