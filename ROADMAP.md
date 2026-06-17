# ThemisIQ — Feature Roadmap and Progress Tracker

Last updated: 2026-06-17

---

## Summary

| Status | Count |
|--------|-------|
| Done   | 8     |
| Pending | 8    |

---

## Item 1: Performance

### 1a. GZip compression
**Status: DONE** (commit 01cefba)
GZipMiddleware added to main.py. Compresses all text responses over 1 KB automatically.

### 1b. Static asset cache headers
**Status: DONE** (commit 01cefba)
Cache-Control: public, max-age=31536000, immutable applied to /static/ paths in security_headers_middleware.

### 1c. App images converted to WebP
**Status: DONE** (commit f951b69)
All 5 app PNGs in static/img/ converted to WebP (75-94% size reduction).
base_shell.html and login.html updated to use picture/source with WebP + PNG fallback.

### 1d. Self-host Google Fonts
**Status: PENDING**
fonts.googleapis.com is still loaded externally in 6 template files (base_shell.html, base.html, login.html, launcher.html, bcm/dashboard.html, grid/dashboard.html, sentinel/dashboard.html).
Action: download Inter and other referenced fonts, serve from /static/fonts/, remove external CDN links.

### 1e. Lazy-load below-fold images
**Status: DONE** (commit f951b69)
loading="lazy" added to below-fold images.

### 1f. Landing page images to WebP
**Status: DONE** (commits afe0acf, f951b69)
All 8 landing page screenshots renamed to URL-safe names and converted to WebP.

---

## Item 2: Mobile and Tablet Optimization

**Status: PENDING**
Shared responsive.css not yet created.
Action: create static/css/responsive.css with table overflow-x, full-screen modal pattern, stat card grid collapse. Include in base_shell.html.

---

## Item 3: ERM to Sentinel Cross-Module Link (Bug Fix)

**Status: DONE** (commit 01cefba)
@on("erm.risk.identified") handler added to core/event_handlers.py.
When ERM risk category is data_breach or privacy, auto-creates a Sentinel breach and cross_module_links record.
Idempotency guard prevents duplicate records.

---

## Item 4: Multi-Tenancy (Schema-per-Tenant)

**Status: PENDING (major feature, 1-2 weeks)**
Prerequisite: PostgreSQL must be confirmed running on VPS.
Architecture decision: schema-per-tenant in PostgreSQL. Each org gets tenant_{slug} schema.
Action: add organizations + licenses tables to public schema, add set_tenant() to _PgConnWrapper, add tenant middleware, build /super-admin/ routes.

---

## Item 5: AI Guardrails

**Status: DONE** (commit 01cefba)
_GRC_GUARDRAIL system prompt prepended to every AI call in core/ai_client.py.
Restricts scope to GRC domain, requires verifiable standard citations with clause numbers, blocks off-topic requests.

---

## Item 6: Two-Factor Authentication (TOTP)

**Status: PENDING (1 day)**
Action: add user_mfa table, install pyotp + qrcode[pil], add /mfa/setup + /mfa/enable + /mfa/verify routes in routes_auth.py, add mfa_setup.html + mfa_verify.html templates.

---

## Item 7: APIs and Connectors

### 7a. Slack notifications
**Status: PENDING**
Action: add send_slack() in core/notifications.py using Incoming Webhooks. Trigger on critical risk, breach confirmed, SLA breach, appetite exceeded.

### 7b. Microsoft Teams notifications
**Status: PENDING**
Action: same pattern as Slack using Teams Incoming Webhooks.

### 7c. Jira integration
**Status: PENDING**
Action: add Jira issue creation on GRID non-conformance, inbound webhook receiver at POST /api/webhooks/jira.

### 7d. REST API documentation and auth
**Status: PENDING**
Action: add X-API-Key middleware using api_keys table, expose read-only GET endpoints for risks, audits, breaches.

---

## Item 8: Legal and Marketing Pages

**Status: PENDING (4 hours)**
Action: create landing_page/privacy.html and landing_page/terms.html. Add footer links and About/Contact sections to index.html. Implement demo request modal (POST /api/demo-request, no auth). Add cookie consent banner (localStorage flag, Accept All / Necessary Only).

---

## Item 9: Email Services

**Status: DONE** (commit f951b69)
SendGrid added as 5th email provider in core/email.py.
Reads sendgrid_api_key_enc from settings table or SENDGRID_API_KEY env var.
Uses SendGrid REST API (POST to v3/mail/send).

---

## Remaining Work Order

| Priority | Item | Effort | Notes |
|----------|------|--------|-------|
| Next | Item 1d: Self-host Google Fonts | 1h | Eliminates external DNS roundtrip |
| Next | Item 8: Legal pages + demo modal | 4h | Needed before marketing push |
| P3 | Item 6: 2FA TOTP | 1 day | Security requirement |
| P3 | Item 2: Mobile CSS | 2 days | UX improvement |
| P3 | Item 7a-b: Slack + Teams | 1 day | Notification integrations |
| P4 | Item 7c-d: Jira + REST API | 2 days | Enterprise connectors |
| P5 | Item 4: Multi-tenancy | 1-2 weeks | Requires PG confirmed on VPS |

---

## PostgreSQL Migration Status

The codebase is fully migrated at the code level:
- database.py supports dual-mode (SQLite local dev, PostgreSQL production)
- All ? placeholders replaced with %s
- INSERT OR IGNORE replaced with ON CONFLICT DO NOTHING
- TIMESTAMPTZ comparisons fixed (commits d894c1d, 73db4d9)
- Transaction abort handling fixed (commit d894c1d)

Remaining steps: see PostgreSQL section in the project README or ask for the next steps.
