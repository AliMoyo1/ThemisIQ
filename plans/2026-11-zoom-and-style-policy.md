# Page bars at 200% zoom, and the style part of the security policy, 2026-11-09

Branch `claude/zoom-and-style-policy`, from `claude/vault-library-acceptance` 80542ac9 (PR 49, waiting on CI). The owner asked in chat on 2026-11-09 to "build 1 and 2" from the next-work list:

1. Check every module's page bar at 200% zoom and move the Vault's wrapping fix into the shared bar.
2. Remove inline styles so the security policy can drop its last exception (`style-src 'unsafe-inline'`).

Decisions here are chat confirmation, not sign-off.

## Part 1: page bars at 200% zoom

### What was checked

A browser probe opened 33 pages as a super administrator at 640 by 400 (a 1280 by 800 window at 200% zoom). For each one it looked for controls outside their page bar, containers whose content spills past their height, and sideways scroll.

### Findings

| # | Finding | Status |
| --- | --- | --- |
| Z1 | The Risk Register's page bar kept its fixed height, so "+ New Risk" sat below the bar, over the summary cards. No other page bar spilled. | fixed: the shared `.topbar` grows and wraps, `.topbar-actions` is a wrapping row (the Vault's rule from PR 49, now shared) |
| Z2 | 16 templates have no breadcrumb of their own, so the bar said "Command Centre" on Reports, Task Board, Risk Register, Profile, the admin pages, ARIA, Governance and others. This is the same fault the Vault had (PR 49, F4). | fixed: a page without its own breadcrumb is named by its title, before the product name ("Risk Register — ThemisIQ" gives "Risk Register") |
| Z3 | With wrapping on, the shell bar first put the breadcrumb on a row of its own at 640 wide. | fixed: the left group shrinks first (`flex:1 1 0; min-width:140px`), so the bar stays one row and only the breadcrumb wraps |
| Z4 | The icon rail is short at 400 high and its middle group scrolls; nothing overlaps. | no change |

### Evidence

| Check | Result |
| --- | --- |
| Screenshots of 37 pages at 1280 by 800 and 640 by 400, before and after, compared pixel by pixel (two baseline runs differ only in timestamps on 13 shots) | at 1280 the only change is the breadcrumb text; at 640 the Risk Register buttons move inside the bar and breadcrumbs change |
| `tests/ui/test_200_percent_zoom.py`: new test, every page bar holds its controls at 640 by 400 and no breadcrumb falls back to Command Centre (27 routes, 4 added) | 54 passed (both tests) |

## Part 2: the style part of the security policy

### What the code holds (survey 2026-11-09)

| Kind | Count |
| --- | --- |
| `style="..."` attributes in templates | 2,411 in 60 templates (1,060 distinct static values, 38 with template values) |
| `style="..."` built by scripts into HTML | about 3,400 in 43 scripts (ERM 668, GRID 548, ORM 411, BCM 389, Sentinel 260, Vault 229, Workflows 167, and others), nearly all with values filled in at run time |
| `<style>` elements | 36 in 34 templates, 1 in the report HTML, 2 created by scripts, 1 written into a print window |
| Third-party scripts that add styles | none |

The earlier estimate in chat (2,400 attributes, 14 scripts) missed the script-built attributes. The real size is about 5,800 places.

### Research (CLAUDE.md: research before building)

- [centralcsp.com: style-src-elem](https://centralcsp.com/directives/style-src-elem) and [style-src](https://centralcsp.com/directives/style-src): `style-src-elem` governs `<style>` elements and stylesheets, `style-src-attr` governs `style=` attributes, both fall back to `style-src`. A nonce or hash in a directive makes `'unsafe-inline'` in that directive ignored, which is why the fallback `style-src` must not carry the nonce.
- [DEV: inline style exfiltration](https://dev.to/kreshby/how-reactnextjs-developers-can-defend-against-inline-style-exfiltration-ise-1hlo): PortSwigger showed in 2025 that injected `style=` attributes alone can read attribute values with CSS `if()`, but the data still has to leave by a URL. Its advice is `style-src-attr 'none'` plus tight `img-src` and `connect-src`.
- [Django CSP nonce docs](https://django-csp.readthedocs.io/en/latest/nonce.html) and the [kida Starlette example](https://lbliii.github.io/kida/docs/advanced/csp): per-request nonce kept on the request and written into each `<style>`; Starlette has no built-in, so a few lines in the existing middleware, no new dependency.
- Not used: `'unsafe-hashes'` with one hash per attribute (about 1,000 static values plus run-time values would not fit a header), and a script that copies `data-style` into styles at load (it would apply injected markup the same way, so it removes the word from the header without removing the risk).

### Decisions (chat confirmation, not sign-off)

| Decision | Why | Cost | How to change |
| --- | --- | --- | --- |
| Lock `<style>` elements now: `style-src-elem 'self' 'nonce-<per request>'`. Every template `<style>` carries `nonce="{{ request.state.csp_nonce }}"`; the report page, the print window and the two script-made style elements use the same nonce; the static showcase page's styles move to a file. | An injected `<style>` is the strong CSS attack: selectors can read a page's attributes and `@import` can pull in a whole stylesheet. This closes it on every page with about 45 small edits. | None for users; a new `<style>` without the nonce is refused by the browser (the test catches it). | `security_headers_middleware` in `core/middleware.py`. |
| Keep `style="..."` attributes allowed for now, written out as `style-src-attr 'unsafe-inline'` with `style-src 'self' 'unsafe-inline'` as the fallback for browsers without the newer directives. | Converting about 5,800 places touches every page and nearly all of them are built at run time, so it is weeks of page-by-page work with regression risk. The attribute route to send data out is already closed: `img-src 'self' data:`, `font-src 'self'` and `connect-src` allow no outside host. | An injected `style=` attribute can still restyle or cover parts of a page, which needs an HTML injection bug first. | Convert module by module (templates to classes, script-built styles to classes or `element.style`), then set `style-src-attr 'none'`. |

### What was built

- `core/middleware.py`: a fresh `secrets.token_urlsafe(18)` nonce per response on `request.state.csp_nonce`; the header adds `style-src-elem 'self' 'nonce-...'` and `style-src-attr 'unsafe-inline'`, keeps `style-src 'self' 'unsafe-inline'` as the fallback. The debug-only `/docs` keeps its old line.
- 35 `<style>` tags in 33 templates carry `nonce="{{ request.state.csp_nonce }}"`.
- `core/report_kit/render_html.py` takes an optional `nonce` (escaped); the browser print route passes the response's nonce. PDF and file renders are unchanged.
- `static/js/module_home.js` and `static/js/thinking-trace.js` give the style element they create the page's nonce; `static/js/aria_ai_generator.js` writes it into the print window, which inherits the page's policy.
- `static/architecture-showcase.html` is served as a file and cannot carry a nonce, so its styles moved to `static/css/architecture-showcase.css`.

### Found on the way

| # | Finding | Status |
| --- | --- | --- |
| S1 | ARIA Policy Imports (`/aria/policy-imports`) crashed with a server error for a platform super administrator outside any organization: the page asked for register claims, which refuse a person with no organization. | fixed: such a person gets no claims; the page opens (`modules/aria/routes_policy_intake.py`) |

### Evidence

| Check | Result |
| --- | --- |
| `tests/test_csp_report_only.py`: a fresh nonce per response, the fallback names no nonce, every template `<style>` carries the nonce, static pages hold none, scripts and Python add none without it | passed (with the report kit tests, 60 passed) |
| `tests/test_report_kit.py`: the print view's style carries the given nonce, escaped | passed |
| `tests/ui/test_style_policy_browser.py`: 24 pages (shell, module pages with their own styles, the error page, both scripts that add a style) apply every `<style>` with no refusal in the console; an injected `<style>` without the nonce does not apply; a print window's style with the page's nonce applies | 25 passed |
| Screenshots of 37 pages at two sizes, before and after the policy | identical apart from the same timestamp noise as two baseline runs; no policy refusal in the console on any page |

## Part 3: removing style attributes, module by module

The owner said in chat on 2026-11-09: "yes, start with the smallest module".

### Order

Counted per module as its templates plus the scripts they load (`style="..."` written into markup; setting `element.style` from a script is allowed by the policy and is not counted):

| Module | Places |
| --- | --- |
| AI Governance | 1 (`registers.html`) |
| Data Readiness | 4 |
| Evidence campaigns | 9 |
| Governance | 40 |
| Shared shell (`base_shell.html`, `_platform_trainer.html`, `shell_core.js`, `related_items.js`, `platform_trainer.js`) | about 130 |
| Evidence Vault, Sentinel, BCM, ORM, ARIA, GRID, ERM, platform pages | 370 to 1,390 each |

Every module page sits inside the shared shell, so no page can run with `style-src-attr 'none'` until the shell is clean. Slice 1 is therefore AI Governance plus the shell, and then the stricter rule switched on for AI Governance pages only.

### Method

- A fixed style in a template becomes a named class in the page's own nonce'd `<style>` block, written for that element (no generated class names).
- A value a script fills in at run time is set on the element with `element.style` after the markup is inserted, which the policy allows, or becomes a class when it is one of a few fixed values.
- An element hidden at first (`display:none`) gets a hiding class; every script that shows these elements sets an explicit value (`flex`, `block`), which still wins over a class. Scripts that read `element.style.display` were checked for each one.
- Inline styles outrank every class, so a class can lose to an existing rule. Screenshots before and after catch that.
- The middleware lists the path prefixes that are clean; only those get `style-src-attr 'none'`. A browser test opens each listed page and its dialogs and fails on any refusal.

Checked first in Chromium under `style-src-attr 'none'`: `element.style.width = ...` and `element.style.cssText = ...` apply; `style="..."` in markup, `setAttribute('style', ...)` and `style` inside `innerHTML` are refused.

### Slice 1: AI Governance and the shell (built 2026-11-09)

| File | What changed |
| --- | --- |
| `templates/base_shell.html` | 53 attributes into 42 `sh-` classes; the subscription banner's two colour sets became `sh-license-critical` and `sh-license-warn`; classes for the markup the shell scripts build (`sh-notif-*`, `sh-search-*`, `sh-sc-*`, `ri-*`) |
| `templates/_platform_trainer.html` | 9 attributes into `tr-` classes |
| `static/js/shell_core.js` | notifications (read and unread are classes), search results (the module dot is a class per module), keyboard shortcuts panel |
| `static/js/related_items.js` | the Related Items panel and its link picker |
| `static/js/platform_trainer.js` | the "Thinking..." line |
| `modules/ai_governance/templates/registers.html` | its one attribute; see S2 |
| `core/middleware.py` | `STRICT_STYLE_PREFIXES = ("/ai-governance",)`: those pages get `style-src-attr 'none'` |

The shell's new rules sit above the page CSS slot (`{% block extra_styles %}`), which is inside the shell's own `<style>`.

| # | Found on the way | Status |
| --- | --- | --- |
| S2 | The AI Registers page opened a nested `<style>` inside that slot. The nested tag made the browser drop the page's first rule, `.reg-grid`, so the register cards stacked in one column with no gap; its end tag also closed the shell's block early, so the first draft of this slice showed the shell's new rules as page text. | fixed: the page puts plain rules in the slot; the cards now show in the grid the page defines. A test now refuses a `<style>` opened inside the slot before the shell's block is closed (the ARIA base closes it first on purpose, which works) |

| Check | Result |
| --- | --- |
| `tests/test_csp_report_only.py`: AI Governance gets `style-src-attr 'none'` with the same nonce and fallback; the shell, the AI Governance templates and every script they load write no style attribute; the CSS slot rule | passed |
| `tests/ui/test_style_policy_browser.py`: all 14 AI Governance pages as a super administrator and as a DPO, with no refusal and no CSS shown as text; notifications, search (none and hits), shortcuts, reminder, Themis and the Related Items panel open styled; an injected `style=` attribute does nothing | passed (with part 2's checks, 37 passed) |
| Screenshots of 14 AI Governance pages and 9 shell pop-ups, and of 37 pages at two sizes, before and after | unchanged apart from timestamps, except AI Registers (S2, now the intended grid) |

## Change log

- 2026-11-09: branch created; zoom probe over 33 pages; Z1 to Z3 fixed in `templates/base_shell.html` and `modules/evidence/templates/evidence_index.html` (the Vault-only rule removed, now shared); zoom test extended.
- 2026-11-09: style survey and research; decisions above.
- 2026-11-09: nonce policy for `<style>` built and checked in a real browser; S1 found by the new browser test and fixed.
- 2026-11-09: owner chose to start removing style attributes with the smallest module; slice 1 (AI Governance and the shell) built, S2 found and fixed, AI Governance switched to `style-src-attr 'none'`.
