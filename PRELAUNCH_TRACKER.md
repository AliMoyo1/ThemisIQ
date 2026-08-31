# ThemisIQ Pre-Launch Tracker

**Last updated:** 2026-08-07 (reconciled against 168 commits made between 2026-06-25 and now — this doc had not been touched since v1.0.2 despite that entire body of work)
**Target URL:** https://themisiq.net / https://app.themisiq.net
**Stack:** FastAPI, PostgreSQL, Nginx, Cloudflare, Hetzner VPS

**Reframing note:** Commits `PLAN-31` (9 commits) show a full "Econet consolidation" applied directly to production ("PLAN-31 Phase 2 COMPLETE: Econet consolidation applied on production"), plus an active WhatsApp bridge and recurring production-crash fixes (semicolons breaking PG executescript, missing columns on `sentinel_breaches`, missing `workflow_actions` columns) that were fixed *in* production. This reads as an app already carrying live tenant traffic, not a system still waiting to launch. Confirm with Ali whether "pre-launch" is still the right frame, or whether this doc should become an ops/hardening backlog for an already-live product.

**What could not be verified from the repo alone** (ops/dashboard-side state, not code): current deployed commit on the VPS, whether API keys were regenerated after the PBKDF2 hashing upgrade (`3ad2671`). **Resolved 2026-08-19:** VPS confirmed running `4524f5b` (includes the PBKDF2 fix; 4 commits behind current `master`), and `api_keys` has 0 rows in production, so there was nothing to regenerate. See Sections 1 and 12.

**Cross-checked against `ThemisIQ_PreLaunch_Tracker.xlsx` (2026-08-07):** the xlsx mirror turned out to be carrying newer information than this file for several ops items — its "Pre-Launch Checklist" sheet already marks log rotation, uptime monitoring, email delivery (tested end-to-end), nginx rate limiting, firewall rules, and Sentry alert rules as **Done**, and Cloudflare WAF as **N/A — Free plan, Free Managed Ruleset active**. That's relayed below, but it's Ali's own prior record, not something re-verified from code this session — flag it if any of it has since drifted. The xlsx also had one genuine internal contradiction (its own "Post-Launch" sheet still showed image optimization and WAF as Pending) which has now been fixed in the xlsx to match the Checklist sheet and this doc's code-verified findings.

---

## 1. Security Hardening (7-Phase Programme)

### Phase 1: Reconnaissance and Code Audit
- [x] Manual code review of all modules
- [x] Configuration file review
- [x] Environment variable handling audit
- [x] Secret exposure analysis
- [x] API key management review
- [x] Dependency mapping

### Phase 2: Critical Vulnerability Remediation
- [x] F-01 CRITICAL: API key removed from git history, revoked
- [x] F-02 HIGH: Email credentials removed from .env.example
- [x] F-03 HIGH: Gemini API key moved from URL param to HTTP header
- [x] F-04 HIGH: SSRF protection added to webhook URL validation
- [x] F-05 HIGH: Stored XSS fixed in email template variables (html.escape)
- [x] F-06 HIGH: Secure flag added to session and CSRF cookies

### Phase 3: Authentication Hardening
- [x] F-07 MEDIUM: Rate limiting extended to MFA verify endpoint
- [x] F-08 MEDIUM: Seed passwords randomised with must_change_password=1
- [x] F-09 MEDIUM: PostgreSQL TLS enforced (PGSSLMODE=require)
- [x] Rate limiting extended to password-change endpoint

### Phase 4: Audit Trail and Information Disclosure
- [x] F-10 MEDIUM: Failed login attempts now logged with IP and username
- [x] F-11 MEDIUM: Deletion audit events include human-readable identifiers
- [x] F-12 MEDIUM: Email password sentinel replaced with '__unchanged__'
- [x] F-13 MEDIUM: Bulk import rewritten with atomic transaction

### Phase 5: Security Headers
- [x] F-14 LOW: COOP and CORP headers added
- [x] F-15 LOW: CSP font-src restricted to 'self' (fonts self-hosted)
- [x] Content-Security-Policy tightened for script, style, connect sources
- [x] Permissions-Policy: camera, microphone, geolocation blocked
- [x] Referrer-Policy: strict-origin-when-cross-origin

### Phase 6: Dependency CVE Patching
- [x] F-16 LOW: jinja2 upgraded (CVE patched)
- [x] python-multipart upgraded (CVE patched)
- [x] python-dotenv upgraded (CVE patched)
- [x] requirements.txt versions pinned

### Phase 7: Verification and Regression Testing
- [x] 53-test security regression suite created (pytest)
- [x] OWASP ZAP baseline scan 1 executed: 0 High, 59 Pass, 8 Warn
- [x] HSTS enabled via Cloudflare (6 months, includeSubDomains)
- [x] OWASP ZAP baseline scan 2 executed: HSTS warnings reduced from 3 to 1

### Phase 8: CodeQL Static Analysis Remediation (2026-06-24)
- [x] SQL injection: tenant schema DDL uses psycopg2.sql.Identifier (database.py)
- [x] Path traversal: report file serving validates paths within REPORTS_DIR (grid/routes.py)
- [x] Weak hashing: API key hash upgraded from SHA-256 to HMAC-SHA256 (routes_api_v1.py)
- [x] Incomplete JS string escaping: added backslash escape in 11 onclick handlers
- [x] DOM XSS: notification link validated as internal path (base_shell.html)
- [x] DOM XSS: server error messages escaped before innerHTML (documents.html)
- [x] ReDoS: email validation regex tightened (routes_admin.py)
- [x] Clear-text logging: DATABASE_URL redacted in startup output (start_app.py)
- [x] Information exposure: 10+ API error responses replaced str(exc) with generic messages
- [x] Legacy code removal: 10auditsphere, complianceos, BCM, Sentinel folders removed from repo

### Phase 9: Post-v1.0.2 Hardening (2026-06-25 to present, previously undocumented)
- [x] API key hashing upgraded from HMAC-SHA256 to PBKDF2-SHA256, 100k iterations (`3ad2671`)
- [x] PostgreSQL Row Level Security enabled on shared public tables (`ca82af2`, fixed startup crash in `71d54d7`/`d3c5ee7`)
- [x] Second CodeQL sweep: DOM XSS (documents.html, BCM doc viewer, analytics.html, notification handler — 6 separate fixes), path traversal/injection in report/grid endpoints (4 fixes), ReDoS in tag-stripping regex, clear-text secret storage in `.env`, SECRET_KEY logging removed
- [x] Login CSRF loop fixed: csrf_token cookie now set on error responses (`0190833`)
- [x] Audit log org isolation hardened: strict filtering for non-super-admins (`27f8446`)
- [x] AI prompt-injection protection + AI-endpoint rate limiting (`4ab948a`)
- [x] All user inputs sanitized at request boundaries (`6d00661`)
- [x] Upload magic-byte validation added (PLAN-18 B/C, `c14108b`)
- [x] `sanitize_json_middleware` ASGI `receive()` contract bug fixed — was the root cause of intermittent 500s (`1dec2fe`)
- [x] nginx rate-limiting fixed to key off real client IP behind Cloudflare, not the shared CF edge IP (`94459ee`) — the config lives at `oneforall/scripts/nginx/themisiq-zones.conf`, confirmed present
- [x] **Confirmed 2026-08-19:** `api_keys` table has 0 rows in production (verified via read-only query against the live DB) — no keys existed before or after the PBKDF2 rehash in `3ad2671`, so nothing needed regenerating.

**Verify this section stays current:** run `git log v1.0.2..HEAD --oneline --grep=-i security` periodically — this list was hand-assembled from 168 commits and may miss something.

---

## 2. Penetration Test Results

**Date:** 19 June 2026
**Tool:** OWASP ZAP 2.x Baseline Passive Scan (unauthenticated)
**Report:** ThemisIQ_Pentest_Report_2026-06-19.docx

| Metric | Scan 1 | Scan 2 |
|--------|--------|--------|
| FAIL (High/Critical) | 0 | 0 |
| PASS | 59 | 59 |
| WARN | 8 | 8 |
| Overall | PASS | PASS |

### ZAP Warnings Disposition
- [x] Cache-control on robots.txt: Accepted (static file, no sensitive content)
- [x] X-Content-Type-Options on robots.txt: Accepted (Nginx-served static file)
- [x] HSTS on main domain: Remediated via Cloudflare
- [x] HSTS on sitemap.xml: Remediated via Cloudflare
- [x] HSTS on robots.txt: Accepted (Nginx static, no security implication)
- [x] Non-storable content on 403s: Accepted (403s should not be cached)
- [x] CSP worker-src/manifest-src: Accepted (default-src 'self' covers per spec)
- [x] Timestamp disclosure in 403: Accepted (not exploitable)
- [x] Modern web application alert: Informational only
- [x] CORP on robots.txt: Accepted (Nginx-served static file)

---

## 3. Session and Cookie Security

- [x] Session cookie: HttpOnly, SameSite=Strict, Secure (prod), max_age set
- [x] CSRF cookie: HttpOnly, SameSite=Lax/Strict, Secure (prod), max_age=3600
- [x] CSRF token derived from session via HMAC (no separate cookie dependency)
- [x] Logout delete_cookie hardened with path, samesite, secure flags
- [x] POST-only logout (GET /logout redirects without destroying session)
- [x] CSRF origin-check middleware on all mutating requests
- [x] HSTS header in production (max-age=63072000, includeSubDomains, preload)

---

## 4. Authentication and Access Control

- [x] bcrypt password hashing (cost factor 12)
- [x] Password complexity: 8+ chars, upper, lower, digit, special
- [x] TOTP two-factor authentication (RFC 6238)
- [x] Session token SHA-256 hashed in database
- [x] Rate limiting: 5 attempts / 5 min per IP (login, MFA, password change)
- [x] Database-backed rate limiting for PostgreSQL deployments
- [x] Org isolation enforced across all admin user management routes
- [x] RBAC with capability-based access control
- [x] Licence enforcement per tenant module

---

## 5. Infrastructure and Operations

### Completed
- [x] PostgreSQL migration (from SQLite)
- [x] PostgreSQL TLS enforced via PGSSLMODE=require
- [x] Systemd service with environment isolation
- [x] Cloudflare CDN, DDoS protection, edge SSL termination
- [x] Nginx reverse proxy on port 8080
- [x] Automated database backups: pg_dump at 2 AM daily, 7-day retention
- [x] Backup script at /project/backup_db.sh, cron configured
- [x] Static asset caching (1 year, immutable for /static/)

### Version Control (2026-06-24)
- [x] Git tagging strategy implemented (semantic versioning)
- [x] v1.0.0: Pre-launch release (all modules, IMS, AI generator)
- [x] v1.0.1: Repo cleanup + Sentry bug fixes
- [x] v1.0.2: Security hardening (CodeQL alerts)
- [x] Production deploys via tagged versions (git checkout v1.0.2)
- [x] Rollback procedure documented (checkout previous tag, restart service)

### Remaining
- [x] Log rotation: config exists at `oneforall/scripts/logrotate.d/themisiq` (confirmed present in repo). The xlsx tracker's Checklist sheet separately marks this **Done** (installed on VPS), so treating as fully done.
- [x] Nginx hardening: rate limiting confirmed live at `oneforall/scripts/nginx/themisiq-zones.conf` (login/api/general zones), fixed for real-client-IP-behind-Cloudflare in `94459ee`. xlsx also marks this Done.
- [x] Uptime monitoring: xlsx Checklist sheet marks this **Done** (external ping service). Not independently re-verified this session — no evidence either way in-repo, since this is pure ops/dashboard state.
- [x] Email delivery verification: xlsx Checklist sheet marks this **Done** ("Verify SMTP credentials and test full flow"). `core/email.py` + `core/reminder_scheduler.py` also look complete in code. Not independently re-tested this session.
- [x] Firewall rules: xlsx Checklist sheet marks this **Done**. Server-side state, cannot check from repo; relaying Ali's own prior record.

---

## 6. Cloudflare Coverage

Cloudflare provides the following protections at the edge:

- [x] SSL/TLS termination (Full Strict mode)
- [x] DDoS mitigation (automatic, always-on)
- [x] HSTS enforcement (6 months, includeSubDomains)
- [x] CDN caching for static assets
- [x] Bot management (basic)
- [x] WAF rules: xlsx Checklist sheet says N/A — Free Cloudflare plan, Free Managed Ruleset active (the paid OWASP Core Rule Set isn't available on this plan). Not independently re-verified this session.
- [x] Page rules: xlsx Checklist sheet marks this Done (caching rules for API vs static configured)
- [x] Rate limiting rules: xlsx Checklist sheet marks this Done ("nginx layers + CF leaked-credential rule")

---

## 7. PostHog Analytics

- [x] PostHog JS snippet integrated in base_shell.html via meta tags
- [x] User identification: posthog.identify() with user ID, email, name, role
- [x] Autocapture enabled (pageviews, page leaves, clicks)
- [x] Login page: separate snippet with autocapture disabled
- [x] CSP updated: posthog domains in script-src and connect-src
- [x] No Jinja2 auto-escaping issues (data passed via meta tags, read from DOM)

---

## 8. Sentry Error Tracking

- [x] Sentry DSN configured in /project/.env on VPS
- [x] Sentry SDK integrated in application
- [x] CSP updated: sentry.io domains in connect-src
- [x] Test event verified in Sentry dashboard (19 June 2026)
- [x] Sentry PYTHON-FASTAPI-H fixed: closeconn AttributeError (pool.putconn)
- [x] Sentry PYTHON-FASTAPI-G fixed: SSL stale connection (_ensure_alive ping)
- [x] Sentry PYTHON-FASTAPI-F fixed: UndefinedColumn title in evidence resolvers
- [x] Sentry PYTHON-FASTAPI-C fixed: UndefinedColumn owner in sentinel retention
- [x] Alert rules: xlsx Checklist sheet marks this Done. Not independently re-verified this session.
- [x] Release tracking: git tags v1.0.0, v1.0.1, v1.0.2 pushed and deployed

---

## 9. Landing Page

**The whole landing page was rebuilt from scratch since this doc was last touched** — it now lives at `landing_page/index.html` (served statically by nginx from `/var/www/themisiq`, per `oneforall/scripts/nginx/themisiq`), not as a Jinja template. Spline 3D was removed entirely in favor of a cinematic hero video. Everything below this line replaces the old Tailwind/Spline-era checklist, which no longer describes the current page.

- [x] Full rebuild: dark liquid-glass design system, hero video with poster fallback, module cards, AI capability cards, feature deep-dive rows, pricing/FAQ/footer (confirmed current in `landing_page/index.html`)
- [x] Spline removed entirely — replaced with `hero-poster.webp` + video, eliminating the WebGL/Three.js issues the old checklist was tracking
- [x] Image optimization: every image on the page (logo, hero poster, all 7 module screenshots) is `.webp`, most with `loading="lazy" decoding="async"` — confirmed by direct grep
- [x] SEO meta tags: `description`, full Open Graph set (type/url/title/description/image/site_name), and Twitter Card (summary_large_image + title/description/image) all present and populated — confirmed by direct grep
- [x] Em dashes removed from terms/privacy pages (including ones hidden as `&mdash;` entities)
- [ ] **Not yet verified this session:** live console-error count on the current rebuild (the "0 errors, 6 Spline warnings" note is from the old page and no longer applies since Spline is gone)

---

## 10. Bug Fixes (Completed)

### Original batch (through v1.0.2)
- [x] GRID program-dashboard 500: PostgreSQL GROUP BY compliance
- [x] PostHog JS syntax error: Jinja2 auto-escaping producing '&amp;' in script blocks
- [x] MFA silently disabling on /mfa/setup visit
- [x] Forced password change CSRF: derive token from session, not cookie
- [x] Org deletion: null audit_log.org_id and delete api_keys before DROP
- [x] User deletion: clean up all FK-referenced rows before DELETE
- [x] CSRF failure on forced password change for new org users
- [x] Mobile sidebar drawer positioning
- [x] Super-admin TemplateResponse Starlette API change
- [x] New User modal CSS class name typo
- [x] Sentry PYTHON-FASTAPI-H: closeconn AttributeError on pooled connections
- [x] Sentry PYTHON-FASTAPI-G: SSL stale connection (added _ensure_alive ping)
- [x] Sentry PYTHON-FASTAPI-F: UndefinedColumn "title" in evidence resolvers
- [x] Sentry PYTHON-FASTAPI-C: UndefinedColumn "owner" in sentinel retention

### Bug Audit B1-B22 (all closed)
- [x] B15: N+1 queries, risk pagination, datetime filter, task board limit
- [x] B16: orphaned NC evidence/signoffs
- [x] B17: physical file leak on delete
- [x] B18/B19/B22: NC status validation, vault cleanup, workflow ordering
- [x] B20: deduplicated ERM appetite breach events
- [x] B21: `delete_enterprise_risk()` now cleans up linked rows

### Full 6-module QA deep-dive (this session's SYSTEMS_TEST.md sweep)
- [x] GRID: audit-log gap-fill (15 mutation endpoints missing `log_activity()`), finding-creation 500, false-positive breach cascade
- [x] Sentinel: 7 sub-page field mismatches (Security Measures, Retention, Transfers, Policies, Vendors, Consent, Notices), Reports page early-return bug, modal Add/Edit mislabeling
- [x] BCM: risk-creation crash, 4 sub-page dead fields, console modal z-index, Add-as-Action onclick, delete-button quote escaping
- [x] ORM: KRI auto-update fields never saved, missing fields on 3 entities, built the RCSA Controls/Actions UI that had no frontend at all
- [x] ARIA: 76 em dashes cleaned up; a table mis-flagged as orphaned in first pass was corrected, and the *real* bug (5 sites reading compliance stats from the wrong table) was fixed instead
- [x] Platform-wide: `fmtDate()` Invalid Date bug across 7 templates, GRID Link Evidence modal z-index collision, Themis AI widget z-index over modals, DSR deadline auto-calc

### Production incident fixes (found live, not in QA)
- [x] Semicolons inside SQL comments breaking PostgreSQL `executescript` on startup (hit twice: `76b04e5`, `a5d44d1`)
- [x] `workflow_actions` missing `due_at`/`acted_at` columns on PostgreSQL
- [x] `sentinel_breaches` missing columns causing a production breach-creation failure
- [x] Predictive risk engine: Sentinel breach signal was structurally always zero
- [x] 429 rate-limit incorrectly hitting the first login of the day
- [x] Tenant provisioning FK ordering hazard: `applications.vendor_id` referenced a table created later in the same script (hit and fixed twice — `9103e45`, `6daa517`)
- [x] Excel export crash on framework names containing colons
- [x] `NameError` crashes in Command Centre stats, My Dashboard, and `database.py` startup (`_logging` undefined)

---

## 11. Feature Development (Completed)

### Original batch (through v1.0.2)
- [x] Multi-tenancy with org isolation
- [x] Super admin SaaS-grade tenant management
- [x] Public REST API v1 with X-API-Key authentication
- [x] Slack and Teams notification connectors
- [x] TOTP two-factor authentication
- [x] Per-tenant licence enforcement with renewal banner
- [x] User management: org grouping, robust CSRF, polished UX
- [x] Luminous GRC glassmorphism aesthetic redesign
- [x] ARIA IMS: multi-framework integration, curated control mappings (22 framework pairs)
- [x] ARIA Document Register: multi-framework, review cycle, control dropdown
- [x] Control card actions, clear button, policy pre-fill
- [x] Enhanced frameworks page with integrable framework pairs

### The Governance Graph — Tier 1 (major architecture addition, not previously tracked)
- [x] T1.1: 5 new node-type tables (business_units, departments, business_processes, applications, data_assets) + `business_unit_id` scoping across ERM/ORM/ARIA/GRID/Sentinel/BCM
- [x] T1.2: unified canonical controls model (`canonical_controls` + `risk_controls` bridge table)
- [x] T1.3: Control Effectiveness Engine
- [x] T1.4: Residual Risk Engine — ERM and ORM now converge on one formula instead of disagreeing
- [x] Governance module UI: entity admin pages, Ctrl+K command palette, entity deep links, related-items panel
- [x] Multi-SBU federation: Org Admin role, tenant-scoped settings tiering, People-tab business-unit assignment
- [x] Governance Timeline + Evidence Confidence Score
- [x] Regulatory Inbox + deterministic compliance drift detection
- [x] A00: Proactive daily governance briefing (advisories engine)

### ERM Risk Rating Framework (3 slices, full lifecycle)
- [x] Slice 1: configurable rating engine seeded with the OmniContact template (9 impact dimensions, 5×5 matrix, taxonomy)
- [x] Slice 2: framework editor + import/export, so other orgs can bring their own rating system
- [x] Slice 3/4: taxonomy-driven category dropdown, multi-dimension impact scoring
- [x] Round 6 (ERM v2): CF/ICE scoring engine, assessment workspace, per-CF treatments, dashboard v2, objectives, external-context/emerging-risk scanning with AI web search
- [x] Excel risk register import: two-phase preview/commit flow with fuzzy column/category/owner matching

### Evidence Vault & document overhaul
- [x] Evidence Vault rewritten as a real file repository (was ARIA-fallback only), with working download, editing, PDF export, and cascade-safe archive/restore/permanent-delete
- [x] Word export overhaul: proper markdown-table/bold conversion, branding engine rewritten to preserve template structure, doc_id collision fix
- [x] ARIA documents auto-sync to Evidence Vault on upload (not just on approval), auto-attach to GRID

### Workflow engine
- [x] Role resolution, auth check, status handling, and task-delete bugs fixed
- [x] SLA auto-check scheduler, multi-role steps, auto-trigger, step deadlines, delegation
- [x] Concurrency-safe workflow and task-board updates (PLAN-03)

### Integrations
- [x] WhatsApp bridge added alongside Slack/Teams: signed webhook fan-out, RBAC-scoped delivery (several commits fixing real delivery bugs)
- [x] Demo request pipeline: DB persistence, success-state UI, super-admin dashboard view

### AI features
- [x] Ask ARIA: multi-turn conversation memory, greeting/small-talk handling, actionable error messages
- [x] AI Impact Assessment, AI controls catalogue, AIMS/ORAAT engine
- [x] BIA questionnaire engine (BCM)
- [x] AI score suggestions + multi-dimension impact scoring (ERM)
- [x] Migrated off the retired `claude-sonnet-4-20250514` model id to `claude-sonnet-5`

### UI / UX
- [x] Expanding nav rail (pin/hover/labels) — and, this session, redesigned again to a theme-aware glass rail
- [x] Command Centre greeting + login polish
- [x] Vanity metric tiles replaced with actionable GRC stats on Command Centre
- [x] Full landing page rebuild (see Section 9)

### Production/tenant operations (new category — this work didn't exist in the old tracker)
- [x] PLAN-31: Econet organisation consolidation — planned, dry-run tested, then **applied on production** (users + structure migration, BU reassignment, oversight roles, SBU rename)
- [x] PLAN-32: tenant-schema self-heal for migration drift on startup
- [x] PLAN-01/PLAN-18: audit-log tenant isolation, org-enforced MFA + Security UI

---

## 12. Pre-Launch Checklist (Critical)

- [x] All 16 pentest findings remediated (F-01 through F-16)
- [x] ZAP scan: 0 High/Critical findings
- [x] Session cookies hardened
- [x] HSTS enabled
- [x] Database backups automated
- [x] Sentry error tracking active
- [x] PostHog analytics active
- [x] CodeQL static analysis: all high/medium alerts remediated, twice (2026-06-24 and a second sweep post-v1.0.2, see Section 1 Phase 9)
- [x] Git version control: semantic versioning with tagged releases (v1.0.0 - v1.0.2)
- [x] Legacy code cleanup: removed 5 defunct project folders (9,750 files)
- [x] Sentry production errors: all 4 original active errors fixed, plus 8+ later production incidents fixed (Section 10)
- [x] Log rotation and nginx rate-limiting configs confirmed present in-repo (Section 5)
- [x] Landing page image optimization + SEO meta tags confirmed done (Section 9)
- [x] **Superseded by events, not literally done:** "Deploy v1.0.2 to VPS" — 168 commits and multiple confirmed production deploys (including the Econet consolidation) have happened since v1.0.2 was tagged, so the VPS is almost certainly running something far newer than v1.0.2. The checkbox as originally written no longer maps to reality; see the resolved item below instead.
- [x] **Confirmed 2026-08-19:** VPS is running `4524f5b` ("Add ERM update event, API-key write endpoints, and background webhook delivery") — 4 commits behind current `master` (missing the thinking-trace widget rollout and the working-tree cleanup, neither behavior-critical). Verified via `git rev-parse HEAD` on the VPS matched against local `git log`.
- [ ] Run full test suite on production after next deploy
- [x] Email delivery, Sentry alert rules, uptime monitoring, and Cloudflare WAF: all marked Done (WAF as N/A/free-plan) in the xlsx tracker's Checklist sheet — see the cross-check note at the top of this file. Not independently re-verified this session.
- [x] **Confirmed 2026-08-19:** `api_keys` table has 0 rows in production — nothing existed to regenerate.

---

## 13. Post-Launch Recommendations

- [ ] Authenticated ZAP scan (with valid session credentials)
- [ ] API rate limiting at application level (beyond login endpoints)
- [ ] CSP report-uri: collect and monitor CSP violation reports
- [ ] Dependency audit automation: scheduled pip-audit in CI
- [ ] CI/CD pipeline with automated test runs on push
- [ ] Log aggregation: centralized logging with rotation
- [ ] Database connection pooling review
- [ ] Backup restoration test: verify dump can be restored cleanly
- [ ] HSTS preload submission (after stable HSTS period)
- [ ] Security re-test: quarterly ZAP scans
- [ ] SOC 2 / ISO 27001 evidence collection (audit logs, access controls)

---

## 14. Release History

| Version | Date | Description |
|---------|------|-------------|
| v1.0.0 | 2026-06-21 | Pre-launch release: all modules, IMS, AI generator, Sentry bug fixes |
| v1.0.1 | 2026-06-21 | Repo cleanup: removed 5 legacy project folders (9,750 files) |
| v1.0.2 | 2026-06-25 | Security hardening: CodeQL alerts fixed (SQL injection, XSS, path traversal, info exposure) |
| *(untagged)* | 2026-06-25 → 2026-08-07 | **168 commits, no version tag cut.** Covers: Phase 9 security hardening (PBKDF2, PG row-level security, 2nd CodeQL sweep), the full Governance Graph Tier 1, the ERM Risk Rating Framework (3 slices + Excel import), an Evidence Vault rewrite, a workflow-engine overhaul, the WhatsApp integration, a complete landing-page rebuild, the Econet production consolidation, and a full 6-module QA sweep. See Sections 1, 9, 10, 11 for the breakdown. |

**VPS running:** confirmed 2026-08-19 as `4524f5b` (`git rev-parse HEAD` on the VPS) — 4 commits behind current `master` (missing the thinking-trace widget rollout: `5b650fb`, `4d3fb17`, `9ac4739`; and the working-tree cleanup: `3eb1007`). None of the gap is security- or data-relevant.

**Suggested next step:** cut a `v1.1.0` tag at current `HEAD` to give this entire block of work a version boundary to deploy and roll back against — ask before doing this, since tagging is a deliberate release action, not a doc edit.

**Note:** the PBKDF2 rehash in `3ad2671` (post-v1.0.2) would have invalidated API keys hashed under the old scheme. **Confirmed 2026-08-19:** `api_keys` has 0 rows in production, so this never affected a real key.
