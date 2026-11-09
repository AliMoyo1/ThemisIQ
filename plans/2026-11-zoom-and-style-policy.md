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

## Part 4: every other module (branch `claude/style-attrs-all-modules`)

The owner said in chat on 2026-11-09, after PR 50 merged: "do all modules".

### What is left (survey on master 577e1578)

| Kind | Places | How it is converted |
| --- | --- | --- |
| Fixed value in a template | 2,181 | generated rule, element gets `data-s` |
| Fixed value written by a script | 3,001 | generated rule, element gets `data-s` |
| Value filled in by Jinja (`{{ }}` or `{% if %}`) | 37 | `data-sv`, applied as below |
| Value filled in by a script at run time | 262 | `data-sv`, applied as below |
| `setAttribute('style', ...)` in two small DOM helpers | 2 | `style.cssText` |
| `static/architecture-showcase.html` | 126 | same as templates |

Hand slicing at the pace of slice 1 would take weeks for about 5,400 places. Part 4 converts them with a script, then checks the result three ways instead of by eye.

### Decisions (chat confirmation, not sign-off)

| # | Decision | Why | Cost | How to change it |
| --- | --- | --- | --- | --- |
| D4.1 | A fixed style becomes an attribute token, `data-s="s1a2b3c4"`, named by a hash of its declarations. The generated rules live in one stylesheet, `static/css/style-tokens.css`. | Scripts build markup where the `class` attribute is often half filled in by code; a second attribute needs no merging, so the conversion can be mechanical. One token per distinct declaration list keeps the file small (about 2,500 rules). | Token names say nothing about intent. New code must not add tokens by hand: it writes ordinary classes (the guard test refuses new `style=`). | Rename tokens to classes module by module later; the browser test below still holds. |
| D4.2 | Each rule's selector is `:is([data-s~="..."],#_#_#_)`. | An inline style beat every normal rule. The `:is()` list counts as three IDs, so the token beats the page's own rules the same way; `!important` rules (responsive.css) still win, as they did; and a script's `element.style` still wins, as it did. Slice 1 used `!important` instead, which would stop scripts from changing a value later (progress bars, colours). | Needs a browser from 2021 or later (`:is()`). | Use `!important` (slice 1 style) where a script never sets the same property. |
| D4.3 | `display` never goes into a token. It becomes `data-sd`, and a small script in the head, `static/js/style_tokens.js`, sets it with `element.style.display` as each element is added, then drops the attribute. The stylesheet also hides `[data-sd=none]` until then, so nothing flashes. | 49 places show an element by clearing `element.style.display = ''`, and four read it back. A token would keep those elements hidden. Setting it through CSSOM (which the policy allows) leaves every one of those scripts working unchanged. | One small script on every page, watching for added elements. | Replace with `hidden` and explicit classes per module, script by script. |
| D4.4 | A value filled in at run time (Jinja or script) becomes `data-sv="..."`, applied by the same script through `element.style.setProperty`, after checks: a fixed list of properties, no `url(`, `image-set(`, `expression`, `attr(`, backslash, `@`, `<`, `>`, braces, and no `position:fixed` or `sticky`. | These are mostly colours and bar widths, some taken from stored records. Today a stored colour such as `red;position:fixed;...` would apply as written; through the checks it cannot place an overlay or load a URL. | The checks are a list to maintain; a property not on it is dropped (and the test suite shows the gap). Limit: markup injected through some other bug could still reuse existing classes and tokens (a dialog's full-page backdrop, for one), as on any page styled by classes; the policy stops free-form styles and loaded URLs, not that. | Move a value to a token, or to `element.style` in its script, and remove it from the list. |
| D4.5 | When every page is clean, `style-src-attr 'none'` applies to every page under the strict script policy; `STRICT_STYLE_PREFIXES` goes away. | That was the owner's goal: no CSP exception for styles. | A page that still writes `style=` loses that style in the browser. The guard test and the full browser suite (which fails on any console error) catch it before release. | Put a prefix list back in `core/middleware.py`. |
| D4.6 | Emails (`core/email_templates.py`, the test email in `routes_admin.py`) and the Word and Excel writers keep their inline styles. | Emails need inline styles and are not served under the page policy. | none | none |

### Checks

1. Corpus check: a browser page holds, for every generated token, one element with the original `style` and one with the token; their computed styles must match.
2. Fingerprint: the computed styles of every element on 141 pages (org administrator at 1440 and 640 pixels wide, super administrator at 1440), recorded on master and again after the change, compared element by element.
3. The full browser suite with `style-src-attr 'none'` everywhere: it fails on any console error, and a refused style is one.

### What was built

| File | What changed |
| --- | --- |
| 61 templates, `static/architecture-showcase.html`, 46 scripts | 2,310 template and 3,001 script attributes into `data-s` tokens (2,113 distinct) and `data-sd`; 37 Jinja and 262 script run-time values into `data-sv` |
| `static/css/style-tokens.css` (new, generated once) | the token rules, and the `data-sd` holding rules |
| `static/js/style_tokens.js` (new) | applies `data-sd` and the checked `data-sv` values through `element.style` as elements are parsed or inserted |
| 10 page heads (`base_shell.html`, `error.html`, login, MFA, launcher, the three module dashboards, the shared audit page, the showcase) | load the two files first |
| `static/css/responsive.css`, `static/css/premium_theme.css` | their `[style*=...]` selectors (mobile grid columns, reduced motion) also name the matching tokens, and the `prop: value` spelling that `element.style` writes |
| `admin_ai_policy.js`, `command_centre.js` (two helpers), `metrics_definitions.js` | element helpers send `style` to `style.cssText` instead of `setAttribute` |
| `bcm_index.js`, `erm_index.js` | two lookups that found an element by its inline style (`[style*=...]`) now test the computed style |
| `core/report_kit/render_html.py`, `charts.py` | the print view's page break and chart margin are classes; a chart's natural width is its SVG `width`, capped by the stylesheet |
| `core/middleware.py` | `style-src-attr 'none'` on every page; `STRICT_STYLE_PREFIXES` removed |
| `tests/test_csp_report_only.py` | no page, script or browser-facing Python writes a style attribute; helpers given `style:` use `cssText`; every page head loads the tokens before its own styles; every token used has its rule |
| `tests/ui/test_style_policy_browser.py` | 83 pages as super administrator, organisation administrator and DPO with no refusal and nothing left unapplied; `data-sd` and `data-sv` behave as described, a fixed position and a URL are refused |

| # | Found on the way | Status |
| --- | --- | --- |
| S3 | The ERM risk import result and the Sentinel training import result each had two `style` attributes on one tag. Browsers use only the first, so the card's `padding:16px` and bottom margin never applied. | now both apply, so the result card shows the padding its markup asked for (the only visible change the fingerprint found) |
| S4 | Two small element helpers (the Command Centre's "Why this number" panel and the metrics definitions page) copied every key with `setAttribute`, including `style`, so the guard test could not see those styles. The metrics page lost its link spacing under the strict rule; the fingerprint found it. | fixed in both; a guard test now requires `style.cssText` in any script that passes `style:` to a helper |
| S5 | A stored colour reaches some `style` attributes (framework colours, project colours). With the old attribute a value such as `red;position:fixed;...` would have applied as written. | `data-sv` checks each value (D4.4) |
| S6 | Not a style issue, found by the new page test: the ARIA AI Generator page failed with a server error (500) once the organisation held a policy document saved without a framework or control reference (an imported policy, for one). The page joined the two values as text, and a missing value broke the join. | fixed in `modules/aria/routes.py`: such documents are left out of the "controls that have documents" list, as the count above it already did |

### Evidence

| Check | Result |
| --- | --- |
| Corpus check: 2,284 original styles against their tokens, every computed property | 0 differences; the browser kept all 2,121 generated rules (so the `:is()` selector is understood) |
| Fingerprint: 139 pages x 3 (org administrator at 1440 and 640 pixels, super administrator at 1440), every element, 69 computed properties, master against this branch | 206 of 417 identical; the rest differ only in timestamps (text widths) and animations caught mid-frame, apart from S3 and S4 (S4 since fixed), and one ORM element whose `display:-webkit-box` now comes from its token (same computed style) |
| Full browser suite with `style-src-attr 'none'` on every page | 822 passed, 5 skipped, 4 failed: two tests that listed a button's attributes (`style` is now `data-s`), my own test's choice of persona, and S6; all four fixed and passed on rerun (37 passed) |
| `tests/test_csp_report_only.py`, `tests/test_report_kit.py` | passed |
| Backend suite | 3,496 passed, 102 skipped |

## Change log

- 2026-11-09: branch created; zoom probe over 33 pages; Z1 to Z3 fixed in `templates/base_shell.html` and `modules/evidence/templates/evidence_index.html` (the Vault-only rule removed, now shared); zoom test extended.
- 2026-11-09: style survey and research; decisions above.
- 2026-11-09: nonce policy for `<style>` built and checked in a real browser; S1 found by the new browser test and fixed.
- 2026-11-09: owner chose to start removing style attributes with the smallest module; slice 1 (AI Governance and the shell) built, S2 found and fixed, AI Governance switched to `style-src-attr 'none'`.
- 2026-11-09: PR 50 merged (577e1578). Owner said "do all modules": part 4 planned (D4.1 to D4.6), master fingerprinted, every remaining attribute converted by script, `style-src-attr 'none'` made global; S3 to S6 found, S4 and S6 fixed; corpus check, fingerprint and full browser suite run.
