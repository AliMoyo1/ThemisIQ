# Security assessment and code review, 2026-10-20

Scope: the whole ThemisIQ application in `oneforall/` (about 100,000 lines of Python, 1134 routes, 89 browser test files),
the deployment files in the repository, and a line review of branch `claude/specialist-fixtures-grid-contrast`. Method:
reading the security core in full (config, middleware, auth, MFA, sanitising, outbound HTTP, AI client and policy,
RLS), targeted sweeps across all modules, and proving the main findings in a real browser against the test harness.
Nothing was changed while assessing. No finding below has been fixed yet.

Severity: **High** means exploitable now with real impact; **Medium** means a real weakness with limited reach or
needing another condition; **Low** means hygiene or defence in depth.

## Summary

| # | Severity | Finding | Proven |
| --- | --- | --- | --- |
| H1 | High | Stored XSS in the ARIA documents list | Yes, in a browser |
| H2 | High | Organisation MFA policy is read from the wrong schema at login | By code |
| H3 | High | A required MFA policy locks unenrolled users out for good | Yes, in a browser |
| M1 | Medium | Changing or resetting a password does not end other sessions | By code |
| M2 | Medium | AI task prioritisation sends every open task in the organisation to the AI and back to any user | By code |
| M3 | Medium | Prompt injection: the user-input wrapper can be closed from inside, and several prompts do not use it | By code |
| M4 | Medium | AI policy allows everything until an organisation saves one; jobs with no organisation skip it | By code |
| M5 | Medium | AI rate limit missing on several AI endpoints | By code |
| M6 | Medium | `monitor.themisiq.net` serves the whole app over plain HTTP, around Cloudflare | By config file |
| M7 | Medium | CSP allows inline script, so any XSS runs | By code |
| M8 | Medium | TOTP codes can be replayed inside their window; TOTP secrets stored in clear | By code |
| L1 to L12 | Low | Hygiene and defence in depth, listed below | |

## High

### H1. Stored XSS in the ARIA documents list

`modules/aria/templates/documents.html:173` renders
`onclick='openEditModal({{ doc | tojson }})'`. ARIA replaces Jinja's safe `tojson` with its own
(`modules/aria/routes.py:54`), a plain `json.dumps` marked safe, which does not escape `'`, `<`, `>` or `&`. A single
quote in any document field closes the attribute. The input sanitiser strips tags but keeps quotes.

Proof: a document titled `Policy' onmouseover='window.__pwn=1//` gave the Edit button a real `onmouseover` attribute,
and hovering it ran the script (`window.__pwn` became 1). Anyone who can save an ARIA document can run script in the
session of every colleague, approver or super admin who opens the list. The CSP does not stop it (M7).

Fix: delete the override at `modules/aria/routes.py:54` so Jinja's built-in `tojson` (which escapes `<`, `>`, `&`, `'`)
is used, and move the object out of the attribute (a `data-doc-id` and a lookup in the `_allDocsById` map the page
already builds). Add a browser test with a quote and `</script>` in a title. The same override also feeds
`{{ docs | tojson }}` inside a `<script>` block on the same page, where a stored `</script>` from a path that skips the
JSON tag stripper (file imports, form posts) would break out; the same fix covers it.

### H2. Organisation MFA policy is read from the wrong schema at login

The policy is stored with `set_setting("security.require_mfa", ...)` in the `settings` table, which is per tenant
(`_PLATFORM_TABLES`, created in every `tenant_<slug>` schema). At `POST /login` there is no session yet, so
`get_db()` has no tenant and reads `public.settings` (`modules/launcher/routes_auth.py:131`). Result on PostgreSQL:

- an organisation with its own schema that turns MFA on is never asked for MFA at login;
- every organisation gets the default organisation's policy instead.

`/mfa/setup` and the admin page read inside the session, so they show the policy as on while login ignores it.

Fix: after `authenticate_user`, look up the user's organisation slug and read the setting inside that tenant
(`database.tenant_context(slug)` or `set_current_tenant` then `get_db`), and add a PostgreSQL test with two
organisations and different policies.

### H3. A required MFA policy locks unenrolled users out

When the policy requires MFA and the person has not enrolled, login creates an `mfa_pending` session and sends them to
`/mfa/setup`. `require_auth` then redirects every `mfa_pending` session that is not on `/mfa/verify` back to
`/mfa/verify` (`core/middleware.py:33`, `_MFA_PENDING_EXEMPT`), and `/mfa/verify` cannot pass because nothing is enrolled.

Proof: with the policy set to `all`, a fresh user landed on `/mfa/verify`; `/mfa/setup` and `/` both bounced back
there. They can never sign in. Combined with H2, a policy set on the default organisation would lock every unenrolled
user in every organisation out.

Fix: allow an `mfa_pending` session to reach `/mfa/setup` and `/mfa/enable` only when the person has no enabled MFA,
then promote the session after `confirm_enrollment`. Only the browser-free policy function is tested today
(`tests/test_mfa_policy.py`); add an end-to-end test.

## Medium

### M1. Sessions survive a password change, an admin reset and MFA changes

`change_password_submit` (`routes_auth.py:394`), `admin_reset_password` (`routes_admin.py:532`), `mfa_enable` and
`mfa_disable` never delete the user's other sessions. Someone who stole a session keeps it for up to 24 hours after the
owner or an administrator reacts. Fix: `DELETE FROM sessions WHERE user_id = %s AND token <> %s` on self change, and all
sessions on admin reset, MFA enable and MFA disable.

### M2. AI task prioritisation is not scoped

`POST /api/tasks/ai-prioritize` (`modules/launcher/routes_platform.py:951`) only needs a signed-in user, selects the 30
latest open tasks of the whole organisation with no user, unit or capability filter, sends their titles and
descriptions to the AI provider, and returns the ranking with a rationale per task id. Every other task endpoint is
limited to tasks the person created or was assigned. Tenant schemas keep this inside one organisation. Fix: use the
same `created_by = %s OR assigned_to = %s` filter, and add `check_ai_rate_limit`.

### M3. Prompt injection

`wrap_user_input` (`core/ai_client.py:884`) puts text inside `<user_input>` tags but does not neutralise a
`</user_input>` inside the text, so a document, finding or imported row can close the tag and speak as the
instructions. The JSON tag stripper removes it from JSON bodies, but not from file content, imports or form posts.
These prompts interpolate stored text without the wrapper at all: evidence link suggestions
(`modules/evidence/routes.py:1701`), task prioritisation (`routes_platform.py:985`), report narratives
(`routes_reports.py:934`), the governance drift check (`governance/data_service.py:1309`, the one feature that writes
without review), the advisor (`core/advisor.py:280`), control generation (`core/ai_controls.py:59`) and the ERM board
pack (`erm/scenarios.py:990`).

Good already: evidence link suggestions are checked against what the person may see before they are returned, and
ARIA renders model output through escaping or DOMPurify.

Fix: escape `<` and `>` inside the wrapper (or use a per-call random delimiter), wrap stored text in the seven call
sites, and keep validating model output against scope everywhere it names records.

### M4. AI policy defaults to allow everything

`ai_policy.authorize` returns a ticket with no checks when an organisation has never saved a policy ("compatibility
mode": every feature, data category and provider, no token budget), and when there is no organisation in context
(scheduled jobs). Fix: ship a default policy (sensitive categories off, a monthly budget) or require a saved policy
before AI turns on for an organisation, and bind the organisation in scheduled AI jobs.

### M5. AI rate limit missing on several endpoints

`check_ai_rate_limit` (60 calls an hour a person) is used by AI Governance, ARIA, BCM, ERM and Sentinel, but not by the
GRID and ORM AI services, task prioritisation, report narratives, evidence AI or the advisor. A person can run up
provider cost there limited only by nginx's 30 requests a second. Fix: call it in each of those routes.

### M6. Plain HTTP origin exposed

`scripts/nginx/themisiq` serves `app.themisiq.net` and `monitor.themisiq.net` from the same server block on port 80.
The monitor name is not proxied by Cloudflare, so the whole app (login form included) answers in clear text and
without Cloudflare's protection. Login itself fails there (the CORS guard rejects that origin) but the password has
already crossed the network. Fix: give `monitor.themisiq.net` its own block that serves only `/health`, and firewall
port 80 to Cloudflare's ranges. Verify on the VPS.

### M7. CSP allows inline script

`script-src 'self' 'unsafe-inline' ...` (`core/middleware.py:431`) means any injected handler or script runs. It is a
known, tracked refactor; H1 shows why it matters. Interim: add a nonce for the inline blocks that remain.

### M8. TOTP replay and plaintext secrets

`mfa.verify_code` accepts the same TOTP code again until its 90 second window ends, and `user_mfa.totp_secret` is
stored in clear. Fix: store the last accepted time step and refuse equal or older; encrypt the secret with a key from
the environment. Rate limits on MFA attempts are per IP, not per account.

## Low

- **L1.** `/openapi.json` is public (Swagger is off, the schema is not): set `openapi_url=None` in production.
- **L2.** `/api/demo-request` has no app-level limit or challenge, so it can flood the admin inbox and the table.
- **L3.** Login rate limits are per IP only (app 5 per 5 minutes, nginx 20 a minute) with no per-account lockout, and
  the database check fails open on error.
- **L4.** Password policy: 8 characters minimum and no breached-password check. Suggest 12 and a check.
- **L5.** Evidence uploads use an extension denylist, not an allowlist. Downloads are attachments with `nosniff`, so
  the risk is low.
- **L6.** `defusedxml` protects spreadsheet uploads from XML bombs and is installed locally, but is not pinned in
  `requirements.txt`.
- **L7.** `data/oneforall.db` (seed users with password hashes, one session) is committed. The seed passwords are random
  per install, so it is hygiene, not a leak. Remove it from git.
- **L8.** API v1 keys ignore business-unit scope and API writes leave no audit entry; `routes_api_v1.py` falls back to
  a fixed salt string if `SECRET_KEY` is unset (the app refuses to start without it, so only scripts are exposed).
- **L9.** An inactive account answers faster than a wrong password (no dummy hash), which reveals that it exists.
- **L10.** `cleanup_expired_sessions` is never scheduled; sessions have a 24 hour absolute life and no idle timeout.
- **L11.** `X-XSS-Protection: 1; mode=block` is obsolete; set it to `0`.
- **L12.** People directory and inventory reads are organisation wide, not unit scoped (an intra-organisation choice to
  confirm, not a leak across organisations: each organisation has its own copy of these tables).

## Checked and sound

- `SECRET_KEY` is required in production; the app refuses to start without it.
- Sessions: 48 byte random tokens stored as SHA-256; `HttpOnly`, `SameSite=Strict`, `Secure` in production; a
  suspended organisation or expired licence ends access at once; roles are re-read on every request.
- Passwords: bcrypt cost 12; logout is POST only; CSRF tokens on forms, origin check plus `SameSite=Strict` on JSON.
- MFA backup codes are hashed and spent with a compare-and-set.
- Admin routes refuse to grant `super_admin` unless the caller is one.
- SQL: the 126 f-string queries build placeholder lists, scope fragments or allowlisted column names; values are always
  parameters. The public API's update takes its keys from a Pydantic model.
- Outbound webhooks and connectors: HTTPS only, every resolved address must be public, no redirects, bounded reads.
- Files: stored under random names, paths confined with `is_relative_to`, magic-byte checks, served as attachments.
- No `eval`, `exec`, `pickle`, unsafe YAML or `shell=True`; subprocess calls pass argument lists.
- Errors return generic messages; exception detail goes only to the log.
- Tenant isolation: per-tenant schemas plus RLS on the shared tables, policies forced, startup refuses on failure.
- nginx takes the real client IP from `CF-Connecting-IP`, and uvicorn only trusts the local proxy.
- AI: a domain guardrail on every prompt, an organisation policy check before any provider call, usage logged, all 54
  AI features registered and declared, only one writes without review, ZDR and no data collection on OpenRouter,
  model output escaped or DOMPurified where it is rendered as markup.

## Branch review: `claude/specialist-fixtures-grid-contrast`

No blocking issue. Notes:

- `decisions._hash_as_asked` only relaxes the comparison for steps that were `no_access` in the frozen request, which
  is server-written and integrity-checked by `_proposal_intact`; the decider's own fresh digest is still required, and
  the reverse case stays refused by `_proposal_access_gap`. It assumes the stored manifest has a well-formed checklist,
  which the server always writes.
- The employee lockout is enforced by capability, guarded by a test that scans every AI Governance route gate, and the
  inventory diff shows only `employee` leaving 11 routes.
- `literacy._assigned` now excludes anyone whose only roles are employee or external auditor, including as an AI use
  owner; such uses keep their owner-literacy signal until a specialist owner is named (recorded in plan 16).
- The module home link colour change is CSS only.

## How the assessment was done

Run from the worktree on branch `claude/specialist-fixtures-grid-contrast` (based on `master` `790ce1c`), with the
repository `.venv` Python, from `oneforall/`. Read only: nothing in the product was changed. Throwaway probe tests were
written under `tests/ui/`, run once and deleted.

### 1. Branch review

`git diff -- oneforall/modules oneforall/core oneforall/static`, read line by line for logic, authorisation and data
handling. Verified by the lanes already run on the branch: backend 2672 passed and 0 failed; AI Governance, AI policy
and module home browser files 90 passed and 0 failed.

### 2. Security core, read in full

`config.py`, `core/middleware.py` (auth decorators, CSRF, rate limits, headers, CORS, tenant context, JSON tag stripper,
body limit, audit), `core/auth.py`, `core/security.py`, `core/sanitize.py`, `core/mfa.py`,
`modules/launcher/routes_auth.py`, `core/outbound_http.py`, `core/rls.py`, `core/ai_client.py`, `core/ai_policy.py`, and
the public parts of `main.py` (health, readiness, demo request, catch-all routes, error handlers).

### 3. Deployment files

`oneforall/entrypoint.sh`, `oneforall/scripts/systemd/themisiq-app.service`, `oneforall/scripts/nginx/themisiq`,
`oneforall/scripts/nginx/themisiq-zones.conf` and `setup_nginx.py`: how the client IP reaches the app, which host names
are served, rate limits at the proxy.

### 4. Sweeps across the code (patterns, then each hit read in context)

| Area | What was searched | How hits were judged |
| --- | --- | --- |
| Public routes | `docs/generated/capability_inventory.md`, rows whose gate is `public` or `unknown` | Each handler read; catch-alls traced to their gated module handler |
| SQL injection | `execute(f"...")` (126 hits) and string-built SQL | Interpolations classified as placeholder lists, scope fragments, fixed tables or allowlisted columns; dynamic `UPDATE ... SET` key sources read |
| Dangerous calls | `eval(`, `exec(`, `pickle.`, `yaml.load(`, `shell=True`, `os.system(`, `subprocess.` | Arguments traced |
| Template XSS | `\| safe`, `Markup(`, `autoescape`, `tojson` in templates | Each use read; attribute and script contexts checked |
| Client XSS | `innerHTML` (905 uses) with unescaped `${...}` or `+ x.title +` style concatenation | Hits read; most were constant form definitions or `confirm()` text |
| Model output rendering | `marked`, `DOMPurify`, `mdToHtml` | Renderers read for escape-first or sanitiser use |
| Uploads and downloads | `UploadFile`, `FileResponse`, `StreamingResponse` | Size limits, type checks, stored names, path confinement, disposition |
| SSRF | `requests.`, `httpx.`, `urlopen` outside `outbound_http.py` | Who controls each URL |
| Sessions | `set_cookie(`, `DELETE FROM sessions`, rate limit call sites | Flags, revocation points, limit keys |
| Tokens and passwords | `token_urlsafe`, `random.`, `uuid4()`, temp password and reset code | Generator strength and purpose |
| Tenant scope | Table definition blocks in `database.py` (`_SHARED_TABLES` vs `_PLATFORM_TABLES`), `_apply_tenant_schema_ddl`, `get_db` | Whether a table is per tenant or shared; spot checks of id-only queries |
| AI | Every `create_message*` call site against `wrap_user_input` and `check_ai_rate_limit` users; `ai_declarations` and `ai_policy.FEATURES` compared with every `feature="..."` in the code | Unwrapped stored text, missing limits, unregistered features, writes without review, output validation |
| Secrets | `git ls-files` for `.env`, `.db`, key files; `git grep` for API key and private key formats | Committed database opened read only to see what it holds |
| Dependencies | `requirements.txt`; `python -m pip_audit` (blocked, see limits); offline check that `defusedxml` protects `openpyxl` | Version judgement |

### 5. Proofs in a real browser

Each probe used the browser harness (`tests/ui/conftest.py`: a live app on a throwaway SQLite file and a synthetic
organisation with one user per role), ran once with `pytest -s`, and was deleted.

- **H1 (XSS):** stored an ARIA document titled `Policy' onmouseover='window.__pwn=1//`, signed in as the compliance
  manager, opened `/aria/documents`, read the Edit button's attribute names and hovered it. Result: an `onmouseover`
  attribute was present and `window.__pwn` became 1.
- **H3 (MFA lockout):** set `security.require_mfa` to `all`, signed in as an unenrolled user, then opened `/mfa/setup`
  and `/`. Result: every page ended on `/mfa/verify`, with no way to enroll. The setting was removed afterwards.
- **Decision bug (fixed on this branch, found while fixing the fixtures):** compared the decision brief the DPO and the
  super admin each received from `/ai-governance/api/systems/{id}/decision-brief`; only the AIMS step differed.

H2 and the Medium findings are proven from the code paths cited, not by a running exploit.

### 6. Write-up

Each finding was checked against the code a second time (for example, `people_directory` and `task_board` looked
shared across organisations at first, but each organisation has its own copy, so those were downgraded) and ranked by
reach and impact.

## Limits of this assessment

- `pip-audit` could not reach PyPI (the network's TLS inspection presents a self-signed certificate) and certificate
  checks were not disabled, so dependencies were judged by version only. Run `pip-audit` on the VPS.
- Not every one of the 1134 routes was read for object-level access; previous rounds closed most scope findings and
  this pass sampled the generic ones. The 905 `innerHTML` uses were swept by pattern, not read one by one.
- VPS facts not in the repository were not verified: firewall, the PostgreSQL role being `NOSUPERUSER NOBYPASSRLS`,
  which organisations use their own schema, and the WhatsApp bridge behind `/webhook/`.
