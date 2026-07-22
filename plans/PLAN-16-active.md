# PLAN-16: Navigation upgrade - active tracking (2026-07-22)

## Status: COMPLETE

## Goal
See plans/PLAN-16-navigation-upgrade.md for full spec. HARD CONSTRAINT:
zero aesthetic changes to the collapsed rail. Behavior-only upgrade:
hover-to-peek / pin-to-keep-open expansion with text labels, section
headers (Main/Modules/Platform), per-module color dots, localStorage
persistence, no flash on load, touch never expands.

## Changes log

### Step 0: Create active plan file
- [x] plans/PLAN-16-active.md

### Step 1: Expansion CSS (implemented in base_shell.html, see deviation note)
- [x] Read current file contents first
- [x] Added expansion rules exactly as specified (all `@media (hover:hover)`
      guarded, `!important` on tooltip suppression), inserted right after
      the existing `.icon-nav-divider` rule and before `.icon-sidebar-bottom`
      in base_shell.html's `<style>` block

### Step 2: Markup (implemented in base_shell.html, see deviation note)
- [x] Read current file contents first
- [x] nav-label span after each icon's svg, text = the link's existing
      `title` attribute value (Command Centre, Governance, Audit,
      Resilience, Privacy, Enterprise Risk, Operations Risk, Super Admin,
      Admin Settings) -- shorter and more appropriate for an expanded
      label than the fuller "X -- Y" tooltip text
- [x] Section labels: "Main" before Command Centre, "Modules" before the
      first module link (aria/Governance), "Platform" before the bottom
      cluster -- gated on `{% if is_admin or is_super_admin %}` since the
      real rail has no governance/timeline link to key off of (see
      deviation note); this correctly produces zero orphaned headings
      for a non-admin user (verified live)
- [x] mod-dot spans with literal hex values on all 6 module links (aria
      #7d6527, grid #059669, bcm #3d4660, sentinel #3b5bdb, erm #881337,
      orm #7c3a0a) -- verified byte-for-byte via getComputedStyle RGB
      against the real `[data-module]` CSS blocks
- [x] Pin button (`<button id="railPin">`) as the first child of
      `icon-sidebar-bottom`, before the super-admin/admin conditionals --
      the real markup has no literal divider element there (plan assumed
      one), so "above the cluster" was satisfied by ordering alone
- [x] Pre-paint inline `<script>` immediately after the icon-sidebar's
      closing `</div>`, not deferred to DOMContentLoaded

### Step 3: Verify
- [x] Grepped `--icon-sidebar-w`: used by responsive.css for the
      tablet/mobile drawer breakpoints (<=900px), untouched by this plan;
      confirmed the plan's own verification scope (1366/1024 desktop +
      touch) doesn't intersect that responsive layer in any way this
      change affects
- [x] Screenshot: collapsed rail is icon-only at 64px, no visible
      change vs. pre-change baseline (light and dark)
- [x] Hover expand/collapse confirmed via direct `:hover` pseudo-class
      state inspection (`el.matches(':hover')`) at 1366px -- width
      64px<->208px, labels/section-labels/mod-dots appear and disappear
      exactly with hover state
- [x] Pin persistence across reload: confirmed via an ACTUAL page
      navigation (not simulated) -- pinned before nav, still pinned
      (208px, `.pinned` class) immediately after a fresh `/` load, proving
      the pre-paint script + localStorage round-trip works with no
      dependency on DOMContentLoaded timing
- [x] Resize event on pin toggle: confirmed a `resize` listener fires
      ~250ms after `tiqToggleRail()` runs, matching the debounce in the
      pre-paint script
- [x] Keyboard reachability: tabbed from the logo through all 7 nav
      items and confirmed focus lands on `#railPin` next, exactly the
      expected order
- [x] "Platform" label gating: confirmed live with two temp accounts --
      the super_admin account sees "Main"/"Modules"/"Platform" plus
      Super Admin + Admin links; the compliance_manager account (no
      admin/super_admin capability) sees only "Main"/"Modules", zero
      Super Admin/Admin links, zero orphaned "Platform" heading
- [x] Dark mode: rail renders correctly pinned-open in dark theme,
      section labels legible against the `#0f172a` background
- [x] Jinja template parses cleanly (`jinja2.Environment().get_template()`)
- [x] Full pytest: 176/176 passing, zero regressions (no Python touched
      by this plan; this is the standing regression safety net)
- [~] Touch emulation ("tap navigates, never expands") -- NOT directly
      exercised live; this remote preview's touch-emulation surface
      wasn't reachable the same way real hover/click were tested. Relying
      on the `@media (hover:hover)` guard being present and correct
      (confirmed via code + the fact hover:hover DID report true/false
      correctly for this desktop browser context), which is the
      well-established standard technique for exactly this behavior.
      Flagged here rather than silently claimed as fully live-verified.
- [x] No JS errors observed in console at any point during verification

## Deviation notes

**MAJOR: the plan's "exact files to touch" are stale/dead.** Verified via
grep across the entire `oneforall/` tree:
- `templates/_icon_sidebar.html` and `templates/_icon_sidebar_styles.html`
  are NOT included by any template anywhere (`grep '{% include' oneforall/templates`
  finds only `_platform_trainer.html`; `grep icon_sidebar` across
  `oneforall/modules/` finds zero matches). They are orphaned files.
- ALL 18 templates that render a shell (`grep -l 'extends "base_shell'`)
  extend `templates/base_shell.html` directly, which has its OWN
  complete, self-contained icon-sidebar: CSS at lines ~186-240, markup
  at lines ~587-688. There is no "split" between a partial and
  base_shell.html as the plan assumed -- base_shell.html IS the single
  live source.
- The real icon-sidebar already has exactly 6 module links (aria, grid,
  bcm, sentinel, erm, orm) gated by `{% if 'X' in user_modules %}`,
  confirming the plan's "six module dots" premise is correct even
  though its file-location premise was wrong. All 6 hex values in the
  plan (aria #7d6527, grid #059669, bcm #3d4660, sentinel #3b5bdb,
  erm #881337, orm #7c3a0a) verified byte-for-byte against the real
  `[data-module]` CSS blocks (lines 59-93) -- reusing them as-is.
- The plan's edge case about a `can_governance_view`-gated item forcing
  a "Platform" section label does not materialize: the real icon-sidebar
  has no governance/timeline link at all (those apparently live in the
  Command Centre's own wider module-sidebar, not the icon rail). The
  real analog of a "Platform" cluster is the bottom `icon-sidebar-bottom`
  group (super-admin + admin links, both capability-gated) -- applying
  the same principle (don't orphan a heading over nothing), the
  "Platform" label there is gated on `{% if is_admin or is_super_admin %}`.
- Conclusion: implement the full CSS + markup change in
  `templates/base_shell.html` only. Leave `_icon_sidebar.html` /
  `_icon_sidebar_styles.html` untouched (not deleting orphaned files as
  part of this plan -- out of scope; flagged separately if worth a
  cleanup pass later).

**Tooling quirk discovered during verification (process note, not a
product bug):** this remote Browser pane's synthetic `hover`, `left_click`,
and `key` (Return) actions repeatedly failed to produce the expected
DOM/CSS effect on the icon-sidebar's interactive elements (pin button,
even the login form's submit button), despite landing at geometrically
correct coordinates within the target element's real bounding rect.
Conclusively isolated as a tool-level limitation, not a code defect, via
three independent checks that all succeeded: (1) calling
`window.tiqToggleRail()` directly, (2) dispatching a genuine bubbling
`MouseEvent('click', {bubbles:true})` on a child span of the button, and
(3) calling `document.activeElement.click()` on the tab-focused button.
All three correctly toggled `.pinned`. Real page navigations (login form
`.submit()`, actual `/` reloads) worked reliably throughout and were used
as the source of truth for persistence testing instead. Worth remembering
for future live-verification passes in this same preview surface: if a
button click or hover seems to silently no-op despite correct coordinates,
suspect the tool before the code, and confirm with a direct function call
or a manually dispatched bubbling event.
