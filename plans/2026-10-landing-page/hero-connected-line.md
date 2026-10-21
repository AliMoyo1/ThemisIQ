# Landing page hero: the connected line

Date: 2026-10-21. Branch `claude/landing-hero-connected` (stacked on `claude/specialist-fixtures-grid-contrast`).
Companion to [PLAN-features-page.md](PLAN-features-page.md). Every decision below is the owner's, given in chat; where
I chose something, the reason and how to change it are stated.

## What was built

An interactive 3D machine in the landing page hero that shows the removal of silos between modules: eight stations on
one plate, joined by a conveyor belt, with one incident travelling through all of them.

| Station | Machine reused from the factory component | What happens to the incident |
| --- | --- | --- |
| 01 Privacy | Cabinet | Breach confirmed |
| 02 Resilience | Admin | Incident opened |
| 03 Enterprise risk | Engine | Obligation tracked |
| 04 Operations risk | Cabinet | Event logged |
| 05 Audit | Admin | Audit review |
| 06 Governance | Engine | Controls rechecked (the printhead prints the policy revision) |
| 07 AI Governance | Cabinet | AI use re-review |
| 08 Reports | Storefront (a screen) | Cycle complete: the report ticks off every module and is signed off |

The order follows the platform's real cross-module event paths where they exist (a confirmed breach opens a BCM
incident, an ERM obligation, an ORM event and an audit review); the journey is labelled illustrative.

Views and controls (all kept from the original component, owner request): Assembled, Cutaway (shells cut at deck
height), Stations (spread with labels), One incident (the camera follows one incident), plus Show the silos (walls rise
between stations and the belt stops). Cameras Overview, Side, Top, Station, Flight; zoom buttons; play and pause;
hover tooltips; click a station to focus it; drag to rotate.

## Owner decisions, in order

1. Build it for the landing page hero, customised to ThemisIQ, matching the colour theme.
2. Keep the factory machine look; reuse the Engine, Admin and Cabinet machines as modules, with the incident moving on
   the belt through all seven modules.
3. The checkout is Reports, the complete cycle: use the Storefront machine because it is a screen.
4. Keep every view (Assembled, Cutaway, Stations, One order), with full zoom and rotation.
5. No pink: each station uses its module's colour as defined in the app; the silo walls use the landing page's main
   colour.
6. Remove the monospace font and the bullet dots from the whole landing page; use a more premium font.

## Choices made, why, and how to change them

- **Plain JavaScript, not React.** The landing page is static HTML with Tailwind; adding React, TypeScript and shadcn for
  one hero would add a build system. The component's scene was ported to `connected-line.js` (three.js modules) with
  `connected-line-ui.js` for the controls and `connected-line.css` for the styling. To change: port into a React app if
  the site ever moves to one.
- **three.js 0.170.0 self-hosted** in `landing_page/vendor/three` (MIT licence included), loaded through an import map;
  the package tarball's SHA-512 matched npm's published integrity before use. No CDN, so no third-party request.
- **Zoom only after a click into the scene** (a tap on phones), so the scroll wheel and the finger keep scrolling the
  page. Zoom buttons are always available. To change: set `engage(true)` at start in `connected-line.js`.
- **Colours** come from `oneforall/templates/base_shell.html`: each module's `--accent` for caps, glow strips, labels,
  documents and incident cards, and its `--accent-light` for text on the dark machine screens. Reports uses the
  platform colour. Silo walls use the landing `--accent` (Sage `#326e62`, Dusk `#9bc5fc`), lightened for the glass.
- **Label font:** the landing token `--mono` now points at Instrument Sans (the brand face) instead of IBM Plex Mono, so
  labels are tracked capitals in the brand face; figures are tabular so counters and clocks do not jitter. The page
  uses two families (Instrument Sans and Newsreader) and no longer loads Plex Mono. To try another face (for example
  Manrope or Plus Jakarta Sans), change `--mono` in `styles.css` and the Google Fonts link.
- **Dots removed** from labels everywhere: the nine dot elements are deleted from the markup and the remaining label
  dots are hidden in `site-extras.css` (cache version bumped to `labels-2`). Kept on purpose: the window-control dots
  of product screenshots and the decorative contact graphic.
- **Fallbacks:** reduced motion starts paused; no WebGL or no JavaScript shows the Command Centre screenshot.
- **Deploy:** `setup_nginx.py` now also copies `landing_page/vendor/` to the web root (it copied only top-level files,
  so the hero would have fallen back to the screenshot in production).

## Verified in the browser (local static server)

Sage and Dusk themes; every mode and camera; silo walls and message; zoom buttons; station focus; desktop two-column
layout at 1440 px; phone width 375 px with no horizontal scroll and single-row scrollable controls; no console errors;
no label dot displayed; Plex Mono not loaded. Not verified: real touch devices, low-end GPU performance, Safari.

## Still open before the landing page is complete

1. "The system" and the Modules label still say "six disciplines".
2. The Modules section has no AI Governance tab yet (needs a screenshot from the app).
3. The intelligence panel lists AIIA as AI drafted, which is not true yet (plan 17).
4. The nav "Features" link points to the in-page section until `/features` exists.
5. Existing counts on the page ("05 JURISDICTIONS", "01 / 04") predate the numbers-on-hold decision; review them.
