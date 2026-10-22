# PLAN-34: module-sidebar left-offset drawer overlap fix

## Status: DONE (cascade-verified; layout-pixel verification blocked by tooling, see notes)

## Goal
Fix `.module-sidebar`'s hardcoded `left:var(--icon-sidebar-w)` (64px) in the
<=900px/<=600px drawer breakpoints (oneforall/static/css/responsive.css) so
it tracks `.icon-sidebar`'s actual rendered width when `.pinned` or hover-
expanded (208px), instead of always assuming the collapsed 64px width.
Today this causes ~144px of overlap where the module-sidebar drawer
(z-index 600) renders on top of the expanded icon-sidebar (z-index 200),
covering its labels. Desktop (>900px) is unaffected -- `.app{display:flex}`
reflows flex siblings automatically there; the bug only exists at the two
breakpoints where `.module-sidebar` switches to `position:fixed` with a
hardcoded `left`.

## Files
- oneforall/templates/base_shell.html (icon-sidebar pinned/hover width,
  currently hardcoded `208px` in two separate places)
- oneforall/static/css/responsive.css (module-sidebar left/width overrides
  at the tablet and mobile breakpoints)

## Approach
Pure CSS, no JS changes needed -- `#moduleSidebar` (`.module-sidebar`) is a
DOM sibling of `.icon-sidebar` (both direct children of `.app`, icon-sidebar
first), so a sibling combinator can react to `.icon-sidebar`'s live state:
- `.icon-sidebar.pinned ~ .module-sidebar`
- `.icon-sidebar:hover ~ .module-sidebar` (inside `@media(hover:hover)`)

Introduced one custom property (`--icon-sidebar-expanded-w`, 208px) in
base_shell.html so the "expanded" width is defined once and reused by both
the icon-sidebar's own pinned/hover rules AND the module-sidebar's new
override rules, instead of the same magic number living in multiple places
(duplicated magic numbers drifting apart is how this bug happened).

## Changes log

### Step 1: base_shell.html - add shared custom property
- [x] Add `--icon-sidebar-expanded-w:208px` to `:root`
- [x] `.icon-sidebar.pinned{width:208px}` -> `width:var(--icon-sidebar-expanded-w)`
- [x] `@media(hover:hover){.icon-sidebar:hover{width:208px}}` -> same var

### Step 2: responsive.css - tablet breakpoint (max-width:900px)
- [x] `.module-sidebar` gets a `--rail-w` custom prop defaulting to
      `var(--icon-sidebar-w)`, `left` reads `var(--rail-w)`
- [x] `.icon-sidebar.pinned ~ .module-sidebar{--rail-w:var(--icon-sidebar-expanded-w)}`
- [x] new unscoped `@media(hover:hover)` block (harmless outside the fixed-
      position breakpoints, so no need to also gate it by max-width):
      `.icon-sidebar:hover ~ .module-sidebar{--rail-w:var(--icon-sidebar-expanded-w)}`

### Step 3: responsive.css - mobile breakpoint (max-width:600px)
- [x] `.module-sidebar{left:var(--icon-sidebar-w)...}` -> reads
      `var(--rail-w, var(--icon-sidebar-w))` for both `left` and the
      `width:min(220px,calc(100vw - ... - 24px))` formula, so it doesn't
      overflow off-screen when the rail is pinned wide on a narrow viewport

### Step 4: verify
- [x] py-side: n/a (CSS-only change)
- [x] live browser cascade-level verification (see notes below) -- could
      NOT get final pixel/layout confirmation, environment-blocked, not
      code-blocked
- [x] update this file's Status to DONE

## Verification notes (live browser, 2026-08-05)

Started the AegisGRC dev server in this worktree (had to add `autoPort` to
.claude/launch.json since port 8080 was held by another session's server;
also had to run with `DEBUG=true` since this worktree has no `.env`/
`SECRET_KEY` -- both launch.json changes were reverted after verification,
see Cleanup). Logged in as the freshly-seeded admin user.

**Blocker hit:** the Browser pane never entered a "displayed"/compositing
state for the whole session (`document.hidden === true`, `visibilityState:
"hidden"` on every tab, including a freshly created one) -- confirmed this
is a real layout freeze, not a timing artifact, by setting
`icon.style.setProperty('width','999px','important')` (a maximum-
specificity override that must win in any spec-compliant cascade) and
observing `getComputedStyle` / `getBoundingClientRect` still report the
stale pre-existing value afterward. `requestAnimationFrame` never fired
either (standard background-tab throttling), consistent with a page that
is style-computed but never laid out/painted. screenshot explicitly
errored with "the Browser pane is not displayed, so the page is not
compositing frames." This blocks pixel-level (`left`/`width`) confirmation
for THIS fix the same way it would block it for literally any layout
change tested in this session -- not specific to this CSS.

**What WAS verified (style-cascade level, not layout-dependent, so
unaffected by the freeze above):**
- `.icon-sidebar.pinned` and `.icon-sidebar:hover` correctly match the
  live element (`icon.matches('.icon-sidebar.pinned')` -> true after
  toggling the real `pinned` class via the page's own `tiqToggleRail()`).
- `--icon-sidebar-expanded-w` resolves to `208px` everywhere referenced
  (root, icon-sidebar, a scratch element created purely to test var
  resolution in isolation).
- The critical, actually-new mechanism -- `--rail-w` on `#moduleSidebar`
  flipping value based on the preceding sibling's state -- confirmed
  directly via `getComputedStyle(mod).getPropertyValue('--rail-w')`
  (a style-cascade read, not layout-dependent):
  - rail unpinned: `--rail-w` = `64px`
  - rail pinned: `--rail-w` = `208px`
  This is the exact handoff the bug was missing; `left` and the mobile
  `width` calc both consume this same variable, so once it resolves
  correctly (confirmed) the pixel values it feeds into are a direct,
  mechanical function of it.
- Dumped the full matched-rule list from `document.styleSheets` for both
  `.icon-sidebar` and `.module-sidebar` and hand-checked specificity: the
  override rules are `(0,2,0)` vs the base rules' `(0,1,0)`, so they win
  regardless of source order; confirmed no other rule anywhere in the
  cascade also targets `.icon-sidebar`'s or `.module-sidebar`'s `width`/
  `left` that could out-rank them.
- Confirmed via `fetch()` of the live served HTML/CSS that the running
  server was actually serving the edited files (not a stale cached
  template/asset).
- Confirmed desktop (1280px) is a no-op as designed: `.module-sidebar` has
  `position:static; left:auto` there (flexbox layout, no fixed
  positioning, so the new rules -- which only set a custom property and
  `left` -- have nothing to override).

**Not verified:** actual on-screen pixel non-overlap at the tablet/mobile
breakpoints. The style-cascade evidence above makes the outcome close to
mechanical, but this is explicitly weaker than a real rendered screenshot
and should be spot-checked in a session where the Browser pane displays
normally, or manually by the user.

**Cleanup:** reverted `.claude/launch.json` back to its original content
(hardcoded port 8080, no autoPort, no DEBUG=true prefix) -- those were
verification-only scaffolding, not part of the fix. Deleted the scratch
`oneforall/data/oneforall.db` this session's server run created (fresh
SQLite seed db, gitignored, not present before this session). Stopped the
preview server.

Not committed -- per standing rule, commit only on explicit user
instruction.
