# PLAN-17: First impressions - active tracking (2026-07-22)

## Status: COMPLETE

## Goal
See plans/PLAN-17-first-impressions-refresh.md for full spec. HARD
CONSTRAINT: zero aesthetic changes. Two additions: (1) a personalized
greeting + attention summary above the Command Centre's module tiles,
(2) functional-only login polish (dark-mode bootstrap, autofocus,
autocomplete, disabled-submit state, bfcache reset).

## Changes log

### Step 1: Command Centre greeting markup (templates/command_centre.html)
- [x] Inserted the greeting row right after the section-header (title +
      Export/Board Report buttons) and before the "Your Modules" tiles
      grid -- not literally "directly above the first stats-row" as the
      plan's words suggest, since the real page has a module-tiles grid
      between section-header and the first stats-row; placing it here
      instead satisfies the plan's actual intent ("the first screen...
      opens cold" / greeting should be immediately visible) better than
      burying it below the module tiles
- [x] `id="ccGreeting"` / `id="ccAttention"` / `id="ccToday"`, using only
      existing tokens (--text, --muted, --text-mid, --mono), matching the
      plan's exact markup
- [x] Used the existing `animate-fade-up` class (no anim-N suffix) so it
      animates in together with the section-header, not delayed --
      confirmed `.animate-fade-up` alone carries no delay and `.anim-1/2/3`
      are opt-in per-element, so there was no inherited-stagger risk to
      guard against

### Step 2: Greeting JS (daypart + date)
- [x] IIFE placed immediately before `populateStats(d)`'s definition in
      the same script block; client-side daypart computation (server is
      UTC) exactly per the plan's snippet

### Step 3: Attention summary
- [x] Read `populateStats(d)`: the function receives the full data
      object `d` directly as its parameter, so the attention logic reads
      `d.erm_critical_high` / `d.overdue_count` straight from that
      parameter rather than parsing back from DOM text (the plan's own
      fallback for when direct variables aren't available -- they were
      available here, so used them directly, a more robust binding)
- [x] Bound to the SAME 2 signals as the plan's own worked example
      ("2 critical risks, 1 overdue audit"): `erm_critical_high` and
      `overdue_count`. Did not add a 3rd/4th signal (sentinel breaches,
      bcm incidents, etc.) despite them being available in the same `d`
      object -- those already have their own dedicated banners elsewhere
      on this page; scope stayed at the 2 the plan itself demonstrated
- [x] Verb pluralization ("need" vs "needs") keyed off the true combined
      count (critHigh + overdue === 1), not off attBits.length, so e.g.
      "1 critical/high risk and 1 overdue item" (2 total) correctly gets
      the plural "need"

### Step 4: Login functional polish (modules/launcher/templates/login.html)
- [x] Read the full file first. Found autofocus, autocomplete="username"/
      "current-password", and a submit-disable-with-visual-feedback state
      (spinner swap via `.loading` class, not literal "Signing in…" text)
      ALL ALREADY PRESENT -- no changes needed for those 3 items; the
      existing spinner mechanism already satisfies the functional intent
      of "disabled state on submit" and the HARD CONSTRAINT says no
      layout/copy changes, so replacing a working spinner with plain text
      would have been an unrequested change, not a fix
- [x] Dark-mode bootstrap: ADDED (was genuinely missing) -- exact same
      snippet as base_shell.html's own restore logic
      (`localStorage.getItem('ofa-theme')`, set `data-theme` before the
      `<style>` block). DISCOVERY: login.html has ZERO `[data-theme="dark"]`
      CSS rules anywhere -- it's a fully custom, light-only "glass card"
      design, unlike base_shell.html which has extensive dark overrides.
      Live-confirmed setting `data-theme="dark"` produces NO visible
      change on this page (screenshotted). This means the "white flash"
      scenario the plan's acceptance criteria describes cannot currently
      occur on this page (nothing to flash between) -- the bootstrap is
      added for correctness/forward-compatibility (matches the plan's
      literal ask, zero visual risk) but does not fix a presently-visible
      bug, since there wasn't one to begin with. Did NOT add new dark-mode
      CSS to actually theme this page, since that would be a real visual/
      design change forbidden by the HARD CONSTRAINT.
- [x] bfcache reset: ADDED a `pageshow` listener that unconditionally
      clears `.loading` and `disabled` -- genuinely missing before, and a
      real (if narrow) gap: the existing 8000ms setTimeout re-enable
      would not reliably fire if the page were frozen in bfcache for that
      whole window. `pageshow` fires on every page display (fresh load or
      bfcache restore), so this is harmless on a fresh load too.
- [x] Nothing else touched -- no layout, color, or copy changes anywhere
      in this file

### Step 5: Verify + commit
- [x] Jinja parses cleanly for both command_centre.html and login.html
- [x] Extracted and syntax-checked both files' <script> blocks with
      `node --check` after stripping Jinja {{ }}/{% %} -- clean
- [x] Full pytest: 176/176 passing (no Python touched by this plan)
- [x] Live browser pass (temp super_admin account "_p17_verify", full
      name "Jordan Alex Rivera" to exercise the multi-word-name path,
      deleted afterward along with its user_roles/audit_log/sessions rows):
      - "Good morning, Jordan" rendered correctly (multi-word name, first
        word only)
      - Date rendered "Wed, Jul 22, 2026" -- matches actual current date
      - Attention line "7 overdue items need your attention" cross-checked
        directly against `ccOverdueCount` DOM value (both "7") and
        `ccErmCritHigh` (0, correctly excluded from the sentence) --
        proves the binding is accurate, not just plausible-looking
      - Autofocus confirmed (`document.activeElement.id === 'username'`
        immediately after page load)
      - Dark-mode bootstrap confirmed applying `data-theme="dark"` from
        localStorage with zero visual change (screenshotted)
      - Wrong-password path: server re-renders fresh, submit button
        correctly NOT disabled/loading afterward (confirmed live)
      - Single-word-name and NULL-full_name cases NOT separately live
        tested (would need yet more temp accounts for a code path that's
        trivially the same `.split(' ')[0]` logic, or a guarded no-op) --
        verified by direct code inspection instead: the `{% if user and
        (user.full_name or user.username) %}` guard keeps `.split()`
        unreachable on a falsy value, and a single-word string's
        `.split(' ')[0]` is just itself, no special case exists to break
      - "Back after successful login restores from bfcache with button
        still disabled" was NOT cleanly reproduced live -- this session's
        browsing history across many prior test accounts made a clean
        repro impractical; relying instead on the `pageshow` event's
        documented browser guarantee (fires on both fresh loads and
        bfcache restores) plus direct code review, rather than overclaiming
        a live repro that didn't actually happen
- [x] All temp verification data cleaned up (user row, user_roles,
      audit_log, sessions all removed; DB back to the original 4 seed users)

## Deviation notes
See Step 1 (greeting placement) and Step 4 (dark-mode bootstrap being a
currently-invisible no-op, spinner-vs-text for submit state) above --
folded inline rather than repeated here since each is tightly scoped to
its own step.
