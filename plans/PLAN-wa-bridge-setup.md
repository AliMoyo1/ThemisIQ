# WA Bridge Setup Plan

## Status: IN PROGRESS

## What the bridge does

A separate FastAPI service (`themisiq_wa_bridge/`) that:
1. Receives WhatsApp messages from Meta Cloud API (or Twilio)
2. Parses intent, calls ThemisIQ REST API v1, returns a reply
3. Receives proactive alert webhooks from ThemisIQ, fans them out to subscribed WA numbers

Runs on port 8001. ThemisIQ runs on port 8080. Both on the same VPS.

## Bugs found and fixed

### Bug 1: Duplicate load_tenant_map in config.py
`config.py` defines `load_tenant_map` twice (lines 86-93 and 149-157). The first version
does NOT call `_rebuild_org_subs()`, making the org subscriber map stale.
Fix: remove the first definition, keep only the second (correct) one.

### Bug 2: Wrong auth header in themis_client.py
Bridge uses `Authorization: Bearer {api_key}` but ThemisIQ's API uses `X-API-Key: {api_key}`.
Confirmed in `routes_api_v1.py` line 40: `x_api_key: str = Header(None, alias="X-API-Key")`.
Fix: change header to `X-API-Key`.

### Bug 3: Non-existent API endpoints in themis_client.py
Bridge calls endpoints that do not exist in ThemisIQ's API v1:
- /api/sentinel/dpias, /api/sentinel/dsars, /api/erm/risk-score, /api/erm/kris,
  /api/aria/documents/{id}, /api/command-centre/overview

ThemisIQ API v1 actually has only 3 endpoints:
- GET /api/v1/risks (filter: status, category)
- GET /api/v1/audits (filter: status, audit_type)
- GET /api/v1/breaches (filter: status, severity, regulation)

Fix: Rewrite ThemisClient to use actual endpoints. Update intent.py and main.py accordingly.

### Bug 4: Wrong field used for Meta payload HMAC verification in main.py
`main.py` uses `wa_verify_token` as the HMAC secret for Meta payload signatures.
Meta uses the App Secret (not the verify token) for signing POST payloads.
Fix: add `wa_app_secret` field to Settings; use it for HMAC in main.py.

## Files modified

1. `themisiq_wa_bridge/app/config.py` - remove duplicate function, add wa_app_secret
2. `themisiq_wa_bridge/app/themis_client.py` - fix auth header + endpoints
3. `themisiq_wa_bridge/app/intent.py` - update actions to match available API
4. `themisiq_wa_bridge/app/main.py` - update _execute() + fix HMAC field

## Files created

5. `themisiq_wa_bridge/.env.example` - template for all env vars
6. `themisiq_wa_bridge/tenant_map.json.example` - template for tenant mapping
7. `themisiq_wa_bridge/systemd/themisiq-bridge.service` - systemd unit file
8. Updated `oneforall/scripts/nginx/themisiq` - added webhook proxy location blocks

## Architecture on VPS

- Bridge runs as `themisiq-bridge.service` on port 8001
- nginx proxies `/webhook/whatsapp` and `/webhook/themisiq` on `app.themisiq.net` to port 8001
- Meta webhook URL (for Meta dashboard): `https://app.themisiq.net/webhook/whatsapp`
- ThemisIQ connector URL (internal): `http://localhost:8001/webhook/themisiq`
- Bridge .env file: `/project/themisiq_wa_bridge/.env`
- tenant_map.json: `/project/themisiq_wa_bridge/tenant_map.json`

## What the user still needs to do externally

1. Set up Meta WhatsApp Business API or Twilio account
2. Fill in `.env` credentials
3. Create `tenant_map.json` with phone->tenant mappings
4. Register webhook URL with Meta: `https://app.themisiq.net/webhook/whatsapp`
5. Set ThemisIQ connector URL in admin: `http://localhost:8001/webhook/themisiq`

## Change log

- [x] Created this plan file
- [ ] Fix config.py (remove duplicate function, add wa_app_secret)
- [ ] Fix themis_client.py (auth header + endpoints)
- [ ] Fix intent.py (new actions)
- [ ] Fix main.py (_execute + HMAC)
- [ ] Create .env.example
- [ ] Create tenant_map.json.example
- [ ] Create systemd service file
- [ ] Update nginx config
- [ ] Commit + push
- [ ] Provide VPS deploy instructions
