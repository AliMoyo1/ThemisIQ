# ThemisIQ WhatsApp Assistant: Implementation Plans (Index)

Master index for implementing `ThemisIQ_WhatsApp_Assistant_Plan.md` (Part A architecture + Part B DPIA) into the ThemisIQ platform.

## Current-state analysis (what is real vs assumed)

The planning document assumes ThemisIQ already exposes everything the bridge needs. The codebase says otherwise:

| Assumed by the plan/bridge | Reality in `oneforall/` today |
|---|---|
| REST API with per-module scoped keys | `modules/launcher/routes_api_v1.py` exists with ONLY 3 endpoints: `/api/v1/risks`, `/api/v1/audits`, `/api/v1/breaches`. Auth is `X-API-Key` header (PBKDF2 hash against `api_keys` table), single `read` scope, tenant derived from the key's org. No per-module scoping. |
| Endpoints for DPIAs, DSRs, KRIs, risk score, documents, overview | Do not exist. The bridge's `themis_client.py` paths (`/api/sentinel/dpias` etc.) are invented. |
| Outbound webhooks with HMAC `X-ThemisIQ-Signature`, retries, delivery logs | `webhooks` + `webhook_logs` tables and full admin CRUD exist (`routes_admin.py`), but NO dispatcher exists anywhere. Nothing ever sends a webhook. The UI is decorative today. |
| Bridge calls ThemisIQ with `Authorization: Bearer` + `X-Tenant-Id` | Real API wants `X-API-Key` and ignores/derives tenant itself. Bridge must change. |
| Meta payloads verified with app secret | Bridge verifies with `wa_verify_token` (wrong secret; Meta signs with the APP SECRET). Bug. |
| Working internal event bus | TRUE: `core/events.py` emits typed events (`sentinel.breach.confirmed`, `sentinel.dsr.overdue`, `erm.appetite.breached`, `bcm.incident.declared`, ...). The dispatcher can hook here. |

So the work splits into: expand the API (PLAN-01), build the webhook dispatcher (PLAN-02), fix and finish the bridge (PLAN-03), deploy (PLAN-04), and complete the DPIA governance gate (PLAN-05).

## Ranking by leverage

| Rank | Plan | Delivers | Why this leverage |
|------|------|----------|-------------------|
| 1 | PLAN-01 API v1 expansion + module scopes | 6 new read-only endpoints and least-privilege key scopes | Blocks the assistant entirely; also makes the public API genuinely useful to ANY future integration (Power BI, SIEM, customer scripts). Biggest product value per line of code. |
| 2 | PLAN-02 Outbound webhook dispatcher | Real HMAC-signed webhook delivery with retries + logs | Turns an advertised-but-fake feature into a real one. Needed for proactive WhatsApp alerts and valuable to every customer independent of WhatsApp. |
| 3 | PLAN-03 Bridge alignment + alert fan-out | A bridge that actually works against the real API and fans out alerts | The bridge skeleton is written but wired to an imaginary API and has 3 real bugs. This makes the feature exist end to end. |
| 4 | PLAN-04 VPS deployment | Bridge running as a hardened systemd service behind nginx/Cloudflare with Meta wired up | Required to ship, near-zero product leverage on its own. |
| 5 | PLAN-05 Governance and go-live gate | DPIA sign-off pack executed inside ThemisIQ (ROPA, AI risk register, privacy notice, approvals) | Mandatory launch gate per the DPIA (B.11), but no technical leverage. Also great dogfooding of ThemisIQ itself. |

## Recommended execution order

1. PLAN-01 (everything reads through it)
2. PLAN-02 (independent of 01, can also run in parallel)
3. PLAN-03 (needs 01 finished; alert fan-out needs 02)
4. PLAN-04 (needs 03)
5. PLAN-05 (can start anytime; MUST be complete before the Meta webhook goes live in production. Treat it as the release gate, not an afterthought.)

## Shared conventions (read before executing any plan)

- ThemisIQ core lives in `C:\Projects\One For All\One For All\oneforall\`. The bridge lives in `C:\Projects\One For All\One For All\themisiq_wa_bridge\`.
- ThemisIQ DB access: always `db = get_db()` then `try/finally: db.close()`. SQL placeholders are `%s` (the wrapper translates for SQLite/PostgreSQL). Tenant context comes from `set_current_tenant(slug)`; API v1 sets it inside `_require_read_key`.
- Production DB is PostgreSQL (service `themisiq-app.service`, `DATABASE_URL` set on the VPS). Local dev may be SQLite. Never write SQL that only works on one of them (no `datetime('now')` in new queries; pass ISO timestamps from Python).
- Do not use em dashes in any text, comments, or UI copy.
- Never commit secrets. `.env` and `tenant_map.json` stay out of git (this platform has prior findings F-01/F-08 about exposed secrets).
- Phase 1 is READ-ONLY. No plan here adds write endpoints to ThemisIQ. Do not "helpfully" add any.
- All new user-visible API responses follow the existing shape: `{"data": [...], "total": n, "limit": n, "offset": n}` for lists.
- Line numbers drift. Locate edit points by the anchor strings given in each plan, not line numbers.
- Verification for ThemisIQ core changes: run the app locally (`python main.py` from `oneforall/`, or the existing start script) and use `curl` against `http://localhost:8000`. Existing tests run with `pytest oneforall/tests`.
