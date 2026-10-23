# Replace every emoji in the application with SVG icons

Owner, 2026-10-23: remove all emoji like the ones on the DPIA tabs (clipboard, folder, shield, tick) from the whole
application and replace them with quality SVG icons. Check the whole system and do it thoroughly.

Branch `claude/svg-icons`, worktree `.claude/worktrees/svg-icons`, from master `fda87389`. Codex's integration branch is
editing some of the same templates (reports, DPIA form, AIMS). Keep each template edit small and mechanical so the merge
stays easy.

## 1. The survey (before any change)

A script (`oneforall/` as root, tests and generated docs excluded) found, in templates, scripts and Python strings:

- 432 emoji in 28 files, 98 distinct.
- Written three ways: 279 literal characters, 152 HTML entities (`&#128202;`, used by the BCM and Operations Risk
  screens), 1 `\u` escape. A plain search would have missed the entities.
- The biggest files are the Operations Risk, BCM, Privacy, Enterprise Risk, Evidence and Audit pages. Also the Command
  Centre, vendor directory, the Operations Risk template and KRI library scripts, and the jurisdiction registry (country
  flags).

How they are used:

| Use | Example | Replacement |
| --- | --- | --- |
| Icon beside a label, in a button or tab | tab "📋 Basics" | icon then the label |
| Icon alone in a button | AI button "🧠" | icon, with an accessible name |
| Loading state | `btn.innerHTML='⏳'` | spinner icon |
| Status dot | 🔴 🟡 🟢 🟠 | coloured dot icon, never colour alone: keep the text |
| Warning marker | ⚠ | triangle-alert |
| Country flag | 🇿🇼 | country code chip (below) |
| Inside plain text that cannot hold markup | a toast that says "click 🧠" | reworded, no icon |
| Returned by the server | severity `🔴` from the dashboard | server returns a code, the page draws the icon |

## 2. Decisions (chat confirmation, 2026-10-23, not a sign-off)

1. **Lucide icons** (ISC licence, which allows commercial use and needs only the licence text kept with them).
   - Why: the app's own hand-drawn icons (the Themis bubble, the rail) are already 24 px, 2 px stroke, rounded line
     icons. Lucide is the same family, so the new icons look native. They are consistent, accessible and free.
   - Cost: one small attribution file in the repo.
   - How to change: swap the symbols in the sprite; nothing else depends on the choice.
2. **One SVG sprite**, `static/icons/sprite.svg`, with one `<symbol>` per icon, and one stylesheet, `static/css/icons.css`.
   - Why: there is no build step and many icons are written inside JavaScript strings. A reference such as
     `<use href=/static/icons/sprite.svg#ic-brain>` is short, works in templates and in JavaScript strings, is cached
     once, and takes its colour and size from the surrounding text (`currentColor`, `1em`).
   - The markup is written with unquoted attribute values so the same text is safe inside single-quoted,
     double-quoted and template-literal strings.
3. **Decorative icons are hidden from screen readers** (`aria-hidden=true`). An icon on its own in a button keeps the
   button's existing `title` or `aria-label`; where there is none, one is added.
4. **Country flags become country code chips** (a neutral rounded badge with the two letter ISO code).
   - Why: flags are emoji. Real flags would need 21 or more national flag drawings, including coats of arms, and some of
     them are politically sensitive in a compliance product. A code chip is clear, accessible and consistent.
   - Cost: less decoration. How to change: add a flag set later behind the same `flag` field.
5. **Typographic symbols stay.** Arrows (→ ← ↑ ↓ ↗), the middle dot, the ellipsis, the multiplication sign, the plain check
   mark and cross used as text are letters, not pictures. This work covers pictographs and emoji-style symbols, including
   ⚠ ⚙ ✅ ❌ ⏰ ⏳ ⚡ ✨ ✎ ✦ ✶ ➤ ☰.
6. **A regression test** fails the build if an emoji appears again in a template, script or user-facing Python string.

## 3. Steps

1. Build the sprite from real Lucide files and add its licence.
2. Add `icons.css` and load it from the shared shell (and from any page that does not extend the shell).
3. Replace the emoji file by file with a script and a reviewed mapping. Each change is reviewed in the diff. Cases the
   script cannot do are done by hand: attribute values, toasts, `<option>` text, server-returned emoji, flags.
4. Check seeded data and Python strings that reach the screen (`seeds/`, dashboard severities, jurisdiction flags).
5. Add the regression test.
6. Verify in a browser, as several roles, on every module and the main platform pages, in light and dark themes: no
   emoji, no broken or missing icon, no layout shift, no console errors, and the loading and status states work.
7. Run the browser and backend tests that touch these templates.
8. Log, commit, open a PR.

## 4. Log

- 2026-10-23: survey done (432 emoji, 28 files); plan and decisions written.

## Log: verification and finish (2026-10-23)
- Replaced every emoji in templates, scripts and Python strings with sprite icons; flags became ISO code chips.
- Layout audit of 25 pages (flex rows with an icon beside text): one regression, `.stat-label` on the Command Centre used `space-between` and split icon from label. Fixed in base_shell.html (flex-start, gap 6px).
- Landing page theme toggle glyphs replaced with inline sun and moon SVGs (app.js, features-page.js, index.html, features.html); ribbon star bullet became a CSS dot.
- tests/test_icons.py and tests/ui/test_icons_ui.py: 34 passing.
- Throwaway demo server, database and credentials deleted; launch entry removed.
- Not done: commit and PR (waiting for go-ahead).

## Log: merge with master and finish (2026-10-23)
- Merged origin/master (Scenario Studio, PR 24). One conflict: the ERM sidebar moved into `_erm_sidebar.html`; took master's include and put the "Ask ERM AI" card icon change in the partial. No other emoji arrived with master (test_icons passes).
- Added `/erm/scenario-studio` to the browser icon audit. 42 icon, studio, BCM incident and Vault link browser tests pass.
