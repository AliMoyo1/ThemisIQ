# ThemisIQ — Feature Roadmap and Progress Tracker

Original baseline: 2026-06-17. Selected statuses reconciled to the 2026-10-02 checkout. This document remains a historical roadmap; use [the generated route inventory](oneforall/docs/generated/capability_inventory.md) and [PLAN-36 progress](plans/PLAN-36-themisiq-stabilization-and-product-improvements/progress.md) for current, verified scope. The old summary and remaining work order below are historical, not a current deployment decision.

---

## Summary

| Status | Count |
|--------|-------|
| Done   | 8 (June 2026 baseline) |
| Pending | 8 (June 2026 baseline) |

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

**Status: IMPLEMENTED IN SOURCE; VISUAL ACCEPTANCE SEPARATE**
Shared oneforall/static/css/responsive.css exists and is loaded from base_shell.html.
Follow-up: finish pixel-level responsive acceptance across modules; the shared stylesheet and shell include already exist.

---

## Item 3: ERM to Sentinel Cross-Module Link (Bug Fix)

**Status: DONE** (commit 01cefba)
@on("erm.risk.identified") handler added to core/event_handlers.py.
When ERM risk category is data_breach or privacy, auto-creates a Sentinel breach and cross_module_links record.
Idempotency guard prevents duplicate records.

---

## Item 4: Multi-Tenancy (Schema-per-Tenant)

**Status: IMPLEMENTED IN SOURCE; PRODUCTION STATE REQUIRES SEPARATE VERIFICATION**
Source evidence: database.py defines public organizations/licenses, tenant schemas and set_tenant(); tenant middleware and super-admin routes exist. VPS deployment state is not established by this checkout.

---

## Item 5: AI Guardrails

**Status: DONE** (commit 01cefba)
_GRC_GUARDRAIL system prompt prepended to every AI call in core/ai_client.py.
Restricts scope to GRC domain, requires verifiable standard citations with clause numbers, blocks off-topic requests.

---

## Item 6: Two-Factor Authentication (TOTP)

**Status: IMPLEMENTED IN SOURCE**
Source evidence: user_mfa table and /mfa/setup, /mfa/enable, /mfa/verify routes and templates exist. Policy options are off/admins/all.

---

## Item 7: APIs and Connectors

### 7a. Slack notifications
**Status: IMPLEMENTED IN SOURCE; DELIVERY DEPENDS ON CONFIGURATION**
Source evidence: send_slack() and connector configuration/test routes exist. Event coverage and live delivery need separate verification.

### 7b. Microsoft Teams notifications
**Status: IMPLEMENTED IN SOURCE; DELIVERY DEPENDS ON CONFIGURATION**
Source evidence: send_teams() and connector configuration/test routes exist. Event coverage and live delivery need separate verification.

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

## Current work order

The June 2026 priority table is retired because several listed features now exist in source. PLAN-36's task plan and progress ledger carry the current stabilization and product work order. Deployment state, live connector delivery, and browser acceptance still require separate verification.

---

## PostgreSQL Migration Status

The codebase is fully migrated at the code level:
- database.py supports dual-mode (SQLite local dev, PostgreSQL production)
- All ? placeholders replaced with %s
- INSERT OR IGNORE replaced with ON CONFLICT DO NOTHING
- TIMESTAMPTZ comparisons fixed (commits d894c1d, 73db4d9)
- Transaction abort handling fixed (commit d894c1d)

Remaining steps: see PostgreSQL section in the project README or ask for the next steps.
