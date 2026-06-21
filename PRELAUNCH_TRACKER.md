# ThemisIQ Pre-Launch Tracker

**Last updated:** 2026-06-20
**Target URL:** https://themisiq.net / https://app.themisiq.net
**Stack:** FastAPI, PostgreSQL, Nginx, Cloudflare, Hetzner VPS

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

### Remaining
- [ ] Log rotation: configure logrotate for app logs and backup logs
- [ ] Uptime monitoring: set up external ping (UptimeRobot or similar)
- [ ] Email delivery verification: confirm SMTP credentials and test flow
- [ ] Nginx hardening: add rate limiting at proxy level
- [ ] Firewall rules: verify only ports 80, 443 exposed

---

## 6. Cloudflare Coverage

Cloudflare provides the following protections at the edge:

- [x] SSL/TLS termination (Full Strict mode)
- [x] DDoS mitigation (automatic, always-on)
- [x] HSTS enforcement (6 months, includeSubDomains)
- [x] CDN caching for static assets
- [x] Bot management (basic)
- [ ] WAF rules: review and enable OWASP Core Rule Set
- [ ] Page rules: configure caching rules for API vs static
- [ ] Rate limiting rules: configure at edge for login/API endpoints

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
- [ ] Alert rules: configure notifications for new errors
- [ ] Release tracking: tag deploys with git commit hash

---

## 9. Landing Page

- [x] Tailwind CSS: replaced CDN (3MB JS) with compiled purged CSS (25KB)
- [x] Three.js deduplication: removed eager-loaded duplicate
- [x] WebGL zero-dimension guard added to Spline 3D canvas
- [x] Console errors reduced from 260+ to 0 (6 unavoidable Spline warnings remain)
- [ ] Image optimization: compress hero images, add WebP fallbacks
- [ ] SEO meta tags: verify Open Graph, Twitter Card, description

---

## 10. Bug Fixes (Completed)

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

---

## 11. Feature Development (Completed)

- [x] Multi-tenancy with org isolation
- [x] Super admin SaaS-grade tenant management
- [x] Public REST API v1 with X-API-Key authentication
- [x] Slack and Teams notification connectors
- [x] TOTP two-factor authentication
- [x] Per-tenant licence enforcement with renewal banner
- [x] User management: org grouping, robust CSRF, polished UX
- [x] Luminous GRC glassmorphism aesthetic redesign

---

## 12. Pre-Launch Checklist (Critical)

- [x] All 16 pentest findings remediated (F-01 through F-16)
- [x] ZAP scan: 0 High/Critical findings
- [x] Session cookies hardened
- [x] HSTS enabled
- [x] Database backups automated
- [x] Sentry error tracking active
- [x] PostHog analytics active
- [x] Deploy latest code to VPS (cookie hardening commit, pulled 2026-06-20)
- [ ] Run full test suite on production after deploy
- [ ] Verify email delivery works end-to-end
- [ ] Configure Sentry alert rules
- [ ] Set up uptime monitoring
- [ ] Review Cloudflare WAF rules

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
