# PLAN-02: Patch dependency vulnerabilities and pin floating deps

## Goal

GitHub reports 2 moderate vulnerabilities on the default branch. The most
likely culprits: `fastapi==0.111.0` pins `starlette 0.37.x`, which is
vulnerable to CVE-2024-47874 (multipart DoS, fixed in starlette 0.40.0)
and CVE-2025-54121 (event-loop blocking on large multipart uploads, fixed
in starlette 0.47.2). Additionally `sentry-sdk[fastapi]` and `posthog` are
unpinned in `requirements.txt`, so production installs are
non-reproducible.

Outcome: fastapi/starlette upgraded past both CVEs, all deps pinned, full
test suite green, upload endpoints (multipart) manually verified.

## Exact files to touch

1. `oneforall/requirements.txt`
2. Nothing else unless the upgrade breaks tests (see Step 5).

## Step-by-step order

### Step 1 — Confirm the actual alerts

Open https://github.com/AliMoyo1/ThemisIQ/security/dependabot in a browser
(the API returned an empty list — the alerts may be visible only in the
web UI). Note the package names and "fixed in" versions. If the alerts
name different packages than starlette, patch THOSE versions instead and
apply the same verification steps below.

### Step 2 — Update the pins

In `oneforall/requirements.txt` change:

```
fastapi==0.111.0
uvicorn==0.29.0
```

to:

```
fastapi==0.115.14
uvicorn==0.30.6
starlette>=0.47.2
```

and change the last two lines:

```
sentry-sdk[fastapi]
posthog
```

to exact pins. Determine the currently-installed versions first:

```
python -m pip show sentry-sdk
```

```
python -m pip show posthog
```

and pin exactly those, e.g. `sentry-sdk[fastapi]==2.x.y` and
`posthog==3.x.y`. Do NOT guess versions — read them from pip show output.

### Step 3 — Install and freeze-check locally

```
python -m pip install -r oneforall/requirements.txt --upgrade
```

Then verify the resolved starlette:

```
python -m pip show starlette
```

Version must be >= 0.47.2.

### Step 4 — Audit

```
python -m pip install pip-audit
```

```
python -m pip audit -r oneforall/requirements.txt
```

Record any remaining findings. If pip-audit flags a package with a
patched version available, bump the pin and re-run Steps 3-4. Stop and
report (do not upgrade) if the only fix is a major-version jump of
`anthropic`, `psycopg2-binary`, or `apscheduler` — those need human
review.

### Step 5 — Run the test suite

```
cd oneforall
```

```
python -m pytest tests/ -x --tb=short
```

All tests must pass. Known break-risk areas for fastapi 0.111 → 0.115:

- Custom middleware ordering (`app.middleware("http")` registrations in
  `main.py:51-56`) — behavior unchanged in 0.115, but confirm startup logs
  show no middleware errors.
- `TemplateResponse(request, "x.html", {...})` call signature — already the
  new-style order in this codebase, no change needed.
- If a test fails referencing `starlette.formparsers`, the multipart API
  changed: check `python-multipart` is still `0.0.32` (it is compatible)
  and re-read the failing endpoint before patching.

### Step 6 — Live multipart smoke test

Start the app locally and exercise ONE real file upload (evidence upload
is the most representative):

1. `python -m uvicorn main:app --port 8080` (from `oneforall/`)
2. Log in, open Evidence Vault, upload any small PDF.
3. Confirm the file appears in the list and downloads back.

This specifically exercises the starlette multipart parser that changed
between the vulnerable and patched versions.

### Step 7 — Commit

Single commit, message:
`Patch starlette CVEs via fastapi 0.115 upgrade, pin all floating deps`.
Include only `oneforall/requirements.txt`.

### Step 8 — Deploy note for the VPS

After the user pulls on the VPS they must run (one command per step, no
pipes, no && — the user types these manually into a console):

```
cd /opt/themisiq
```

```
sudo git pull origin master
```

```
sudo python3 -m pip install -r oneforall/requirements.txt --upgrade
```

```
sudo systemctl restart themisiq-app.service
```

```
sudo systemctl status themisiq-app.service
```

Include these steps verbatim in your final report to the user.

## Edge cases a weaker model would miss

- **Do not add `starlette` as a direct import anywhere** — the explicit
  `starlette>=0.47.2` line in requirements.txt only constrains the
  resolver; the app must keep importing via fastapi.
- **fastapi 0.115 requires Python >= 3.8; the prod box runs Python 3.x
  from Ubuntu and dev runs 3.14** — both fine, but `pip-audit` may emit
  warnings about the unpinned transitive `anyio`; ignore unless it is an
  actual vulnerability finding.
- **`sentry-sdk` extras syntax must keep the `[fastapi]` extra** when
  pinning: `sentry-sdk[fastapi]==<ver>`, not `sentry-sdk==<ver>`.
- **Do not run `pip freeze > requirements.txt`.** That would dump every
  transitive dep and dev tool into the manifest and break the curated
  file.
- **The 429/nginx work is unrelated** — if uploads fail with 429 during
  smoke testing locally there is no nginx in the loop; that means you
  broke the app-level rate limiter, investigate before proceeding.
- **If the Dependabot page shows the alerts are for the `landing_page/`
  npm packages instead**, the fix target changes entirely: run
  `npm audit fix` inside `landing_page/` and do NOT touch
  requirements.txt except the floating pins (Step 2 second half still
  applies).

## Acceptance criteria

1. `python -m pip show starlette` reports >= 0.47.2 (or the exact fixed
   versions the Dependabot page names).
2. `python -m pip audit -r oneforall/requirements.txt` reports no known
   vulnerabilities (or only ones with no released fix, documented in the
   commit message).
3. `requirements.txt` contains zero unpinned lines (every line has `==`
   except the intentional `starlette>=` resolver constraint).
4. Full pytest suite passes.
5. Evidence upload round-trip works in a live browser session.
6. After VPS deploy, the Dependabot alerts on GitHub auto-close within a
   day (they re-scan on push).
