# Security remediation handoff, 2026-10-20

This work follows `plans/security-assessment-independent-2026-10-20.md` and the earlier local assessment. The checkout already contained unrelated uncommitted changes; this handoff does not claim they were reviewed or released. No production change was made.

## Implemented in this checkout

- ARIA document rows no longer place database values in inline event handlers. The Jinja `tojson` override was removed, and document actions use stable data attributes and fixed listeners.
- ERM appetite category text no longer enters executable click handlers, including the remediation dialog.
- Credential login reads the MFA policy from the authenticated user's organization. Pending unenrolled sessions can reach only enrollment and confirmation, then receive a rotated full session. Failed confirmation keeps the pending secret for a retry.
- Password changes rotate the current token and revoke other sessions in the same database transaction. Admin resets revoke all target sessions. MFA enable and disable rotate sessions; direct disable is rejected when organization policy requires MFA.
- Accepted TOTP time steps are single use, including concurrent submissions. New TOTP secrets are stored as Fernet ciphertext. A dry-run-first migration script handles existing plaintext rows and key rotation. Deployment preflight requires a separate MFA key.
- AI task prioritization uses the board's tenant and business-unit visibility rule, sends fewer fields, runs provider I/O off the event loop, and only returns suggestions for authorized task IDs.
- Office-to-PDF preview runs in a bounded worker with input, output, concurrency, and time limits. Responses stream from a temporary PDF.
- The monitor nginx host serves only `/health`. The application host keeps its existing webhook routes. Nginx and application request-size headers now align with the Vault's 100 MB file limit for the exact upload endpoint.
- The ASGI request-size middleware counts received bytes as well as declared Content-Length, including chunked requests. Vault, ARIA and GRID document uploads, and the ERM workbook import have route-specific multipart allowances in both application code and the checked-in nginx configuration.
- Integration keys now need resource-specific scopes and a valid finite expiry at issuance and authentication. A malformed stored business-unit restriction fails authentication; a valid optional unit restriction applies to counts, reads, creates and updates. Risk status, owner and source references cannot be set through this API. Risk updates reject null values for required fields. Successful write audits share the mutation transaction. Existing broad `read` and `write` keys no longer authorize v1 resources.
- Hidden-unit Vault hashes no longer produce a distinctive duplicate response. The caller's upload proceeds as its own item. The existing assertion was updated without running it.
- Organization AI calls require an approved stored policy and an organization context. Prompt data escapes delimiter characters; the UI no longer promises that prompt wrapping prevents all influence.
- Legacy AI policy rows that lack an identified review are now treated as disabled. A policy manager must explicitly confirm and save a policy to enable AI. Read-only policy and API key inventory scripts support the release review.
- Shared AI calls now reserve a conservative token allowance under a tenant database row lock before provider dispatch. Failed or unmetered calls retain the charge. Organization and per-person monthly limits use completed and reserved usage; exact provider usage can exceed a pre-call estimate.
- Static click handlers in the shared shell have moved to event listeners, and its five executable blocks have moved to local JavaScript files. The wider module-template migration and removal of `script-src 'unsafe-inline'` remain open.
- Production OpenAPI schema exposure, obsolete X-XSS header, demo-request throttling, and expired session retention were addressed. The broad PostgreSQL dependency range was pinned to `psycopg2-binary==2.9.13`.
- Both tracked local SQLite files were removed from the Git index without deleting the local copies; root ignore rules now cover their runtime variants.

## Release gates and remaining work

1. Provision `MFA_ENCRYPTION_KEY` in the root-owned VPS environment. Back up the database, run the count-only and `--apply` migration from `oneforall/docs/mfa-secret-migration.md`, and confirm zero plaintext rows. Keep any previous key available during rotation.
2. Inventory existing API keys and issue replacement keys with explicit scopes, expiry and unit settings before release. The old broad grants are intentionally rejected. Review any integration that submitted owner, status, or source fields because those writes are no longer accepted.
3. Establish and save an AI policy for every organization that should use model features. Previously enabled policies without an identified fresh approval are also disabled. See `oneforall/docs/security-cutover-mfa-api-ai-2026-10.md` for the inventory and cutover order.
4. Review and verify the effective VPS nginx configuration, TLS/DNS/firewall exposure, reverse-proxy upload limit and service health. The checked-in nginx file alone does not prove what is live.
5. Run focused browser, SQLite and real PostgreSQL security checks before release, followed by a dependency advisory scan. This task did not run a test suite. Python syntax parsing and `git diff --check` were the only static checks.
6. Finish the CSP migration away from inline scripts and event handlers across remaining templates. The checked-in policy still uses `unsafe-inline` and cannot yet enforce a strict script policy.
7. Validate the new AI allowance reservation behavior under concurrent calls on SQLite and real PostgreSQL, including interrupted calls, provider usage above the estimate, policy edits and tenant isolation. No such validation was run in this continuation.
8. Decide whether to purge the historical SQLite blobs from Git history. Removing them from the current index does not remove earlier commits. Assess exposed seed data and rotate any real credentials found before a history rewrite.
9. Verify the request-size middleware on declared and chunked uploads through the installed proxy and directly to the app. The code now counts actual received bytes, but no request-flow check was run in this task.

These release gates are not claims that the changed code is already safe to deploy. In particular, missing MFA key configuration and unrotated integration keys create immediate compatibility failures.

## Continuation on the landing-page master, 2026-10-22

The security commit was brought onto an isolated branch based on the current landing-page master. No production change was made. The main checkout contains unrelated active work and was left untouched.

This continuation removes executable template text from AI Governance page bootstraps and enforces `script-src` without `unsafe-inline` on its HTML routes. Other modules still require inline-script migration. Stored names, framework labels, workflow text, AI-generated ERM objects, and BCM resource categories no longer enter the selected click handlers updated in this branch. Internal Evidence Vault links and Sentinel internal links now require this site's origin; external ERM source and Sentinel notice links require HTTPS. The shared shell's HTML escaping now encodes quotes in attributes.

This is a targeted security improvement, not a claim that all browser injection paths are closed. The wider CSP inventory remains open. The operator has confirmed ownership of production MFA key provisioning and existing API integrations, but neither step is complete in this checkout. Do not deploy this branch before the release gates above are met. The first code rollback after MFA migration must support encrypted authenticators, or the approved recovery path must restore the pre-migration database with its matching old code.

Static review in this continuation: `git diff --check`, Node syntax checks for the new AI Governance bootstrap and changed shared shell, and Python syntax parsing for the changed middleware passed. Focused browser, SQLite, PostgreSQL and concurrency checks were not run in this continuation; the release gate requiring them remains open.
