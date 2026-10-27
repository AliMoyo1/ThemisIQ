# ThemisIQ login video refresh

Status: implemented and locally previewed in the isolated `login-video-fonts-build` worktree. The preview is not a production release.

## Goal and current state

Make sign-in feel current with a full-viewport version of the supplied abstract network video and a readable, semi-translucent frosted card. Preserve the existing authentication flow and make the login page fast and usable on phones, low-bandwidth connections, and devices that cannot play the video.

The current `oneforall/modules/launcher/templates/login.html` already has a translucent card, but it also has animated blobs, beams, tilt and shimmer. The page locks overflow and hard-codes four small module pills. The authenticated main sidebar currently names seven modules: Governance, Audit, Resilience, Privacy, Enterprise Risk, Operations Risk, and AI Governance. The public sign-in page must describe platform capabilities, not promise that every module is licensed or available to a particular account.

The supplied source is `12778048_3840_2160_30fps.mp4` at the repository root. It is an approximately 20-second, silent, 3840 x 2160 H.264 clip, roughly 31.8 MB. Its pale grey network imagery has bright highlights, so contrast must be checked over the entire loop. A trial 1080p/24 fps H.264 rendition was about 2.4 MB and a 1920 px WebP poster about 19 KB. Those are feasibility measurements, not final visual approval.

The application and login already load self-hosted WOFF2 fonts from `oneforall/static/fonts/`; the app does not need a Google Fonts conversion. At the build baseline, the landing and features pages loaded Instrument Sans and Newsreader from Google, while the privacy and terms pages loaded Inter from Google. The marketing site and app have different origins, so font files for the marketing site must be served from its own origin.

## Proposed experience

```text
Full-screen network video (or still poster)
  subtle legibility overlay
    centered glass sign-in card
      ThemisIQ mark + short welcome line
      Username label and input
      Password label, input and show/hide control
      Remember me / Forgot password?
      Sign in / inline authentication error
      Connected modules: seven names, lower visual priority
    Pause / Play background control
```

1. Keep the sign-in form as the focus. Use a 440–480 px maximum card width on desktop, generous internal spacing, navy text, gold accents and a quiet shadow. Start with a white glass surface around 80–88% opacity and 18–24 px blur, then tune against frames at the beginning, middle and end of the clip. Add a solid near-white fallback where `backdrop-filter` is unavailable or transparency harms legibility. Do not use transparent input fields against moving imagery.
2. Remove the existing decorative blob, beam and card-tilt animations from the login composition. The video provides the movement. Retain only functional feedback such as the submit spinner. Keep the page vertically scrollable when viewport height, zoom, keyboard or translated text requires it.
3. Show all seven module names in a restrained two-row or wrapping group headed **Connected modules** below the form. On narrow screens use a two-column/wrapping arrangement or a compact text line; never shrink labels to the current tiny pill type. Do not render an entitlement badge or live tenant-specific module state before authentication. Remove the hard-coded `v1.0` footer in favor of a timeless footer or an actual build value if needed.
4. Add persistent visible labels above Username and Password rather than relying on placeholders. Keep existing input names, CSRF field, password-manager autocomplete, Remember me, Forgot password and post-login redirect behavior. Make the show-password control reachable by keyboard and announce its current action. Keep errors adjacent to the form and expose them to assistive technology.
5. Place a visible Pause background / Play background control away from the submit button, with a clear focus style and accessible state. The background has no audio and no meaning needed to sign in. Do not let its controls enter the form submission path.

## Media loading and fallback

- Keep the raw 4K file as design source. Do not serve or commit that 31.8 MB file as the login background. Produce a visually checked, self-hosted H.264 MP4 under `oneforall/static/media/login/` and a small WebP or JPEG poster. Keep final filenames fingerprinted or otherwise cache-safe. Confirm the asset's provenance and web/public-display rights before release.
- Paint the poster first in CSS. For motion-eligible desktop users, load the video after the form and poster render, use `autoplay muted loop playsinline`, `object-fit: cover`, and keep the form above it in stacking order. A failed download, unsupported codec or rejected `play()` promise leaves the poster visible and the form working.
- Default to the static poster on small/mobile viewports and when `prefers-reduced-motion: reduce` is set. Do not fetch the video in these cases. Optionally offer a clearly labelled Play control on mobile after the form is ready. Treat `navigator.connection.saveData` as an additional hint only, since browser support varies. Pause when the tab becomes hidden; do not interrupt typing when motion resumes.
- Target a final video around 2–3 MB at 1080p and a poster below 100 KB, subject to actual quality and performance testing. Measure first form usability before video completion, cumulative layout shift and the effect on slow mobile connections. Do not preload the whole video or make video success a prerequisite for rendering the form.
- Validate `Content-Type`, caching and byte-range behavior on the nginx/Cloudflare path. Serve only from ThemisIQ's own origin. Retain no-store on the login HTML and keep credentials, analytics and tenant data out of media URLs. Make `media-src 'self'` explicit in the login CSP if the site policy requires it; avoid broadening script permissions.

## Implementation boundaries

| Area | Intended change |
| --- | --- |
| Login template | Replace decorative background markup, add poster/video layer, glass form arrangement, seven-module summary and playback control. Preserve all auth form field names, action and CSRF behavior. |
| Login CSS and JS | Move presentation and playback code into dedicated files in `oneforall/static/css/` and `oneforall/static/js/` where practical, in line with the ongoing CSP migration. Keep all essential login functionality independent of video JS. |
| Module names | Establish a small public display list aligned with the seven product modules in `base_shell.html`, or reuse a verified existing public catalogue. Add a drift test. Avoid reading authenticated module access, licenses or organization data on `/login`. |
| Auth route | No intended change to credential checks, rate limiting, sessions, MFA, password reset, CSRF or redirects. Check template context only if a shared public module list is introduced. |
| Static deployment | Include optimized media in the same release as the template, and confirm nginx/Cloudflare can serve it. Keep the raw source outside the served directory. |

## Companion font-delivery cleanup

This is a small adjacent release item, not a blocker for the video design. Self-hosting the public site's remaining fonts removes its browser request to Google and the associated third-party font-service IP disclosure. It may reduce connection overhead, but a Lighthouse score gain must be measured rather than assumed. It also lets the site use the intended typography when Google Fonts is unavailable, provided ThemisIQ's own site is reachable; it does not make the application itself work offline.

1. Preserve the public site's typography by serving WOFF2 subsets of Instrument Sans and Newsreader (including its italic style), plus Inter for the privacy and terms pages, under `landing_page/fonts/`. Keep their redistribution licenses alongside the assets.
2. Replace the four public pages' Google Fonts `<link>` and `preconnect` tags with same-origin CSS `@font-face` declarations. Select only used weights/styles, keep a system-font fallback and suitable `font-display`, and avoid preloading every face. The legal pages now also use the existing local Tailwind stylesheet instead of its external runtime CDN.
3. Use stable cache/versioned filenames with the correct WOFF2 MIME type and long-lived cache headers. Audit the app's existing seven local families for unused faces and language coverage as a separate optimization; do not remove a font based only on this login redesign.
4. In a clean browser, verify that login, landing, privacy and terms make zero requests to `fonts.googleapis.com` or `fonts.gstatic.com`. Compare cold-cache and slow-connection text render, layout shift, font transfer bytes and Lighthouse results before and after. Test with Google domains blocked. Once these pages are clean, review their CSP `font-src` and `style-src` against actual network traffic.

## Verification and release gates

1. Review screenshots/video at 320, 375, 768 and 1440 px, in short-height landscape and at 200% zoom. The full form, errors, password toggle and all module names must remain reachable without horizontal scrolling. Test text contrast over several video frames, not only the poster. Aim for WCAG 2.2 AA contrast: 4.5:1 for normal text and 3:1 for large text.
2. Test keyboard-only and screen-reader form use, visible focus, named inputs, show/hide state, authentication error announcements, pause/play operation and `prefers-reduced-motion`. The pause control is required because this decorative motion loops for more than five seconds.
3. Run focused browser/auth tests for successful sign-in, invalid credentials, CSRF rejection, MFA redirect, Remember me, Forgot password, back/forward restoration and password-manager autofill. Test video unavailable, autoplay denied, media loading late and CSS blur unsupported; each must leave the login usable.
4. Check seven public module labels against the approved product module set and confirm the sign-in page does not claim user-specific access. Verify the media has no sound, no third-party request and no content that obstructs form readability.
5. Test locally, obtain visual sign-off, then release optimized assets and template together. Verify the deployed poster, video and login route from a clean browser on desktop and phone. Rollback must restore both code and static assets; authentication remains available via the static poster if video delivery fails.

## Build record and remaining release checks

- The local login uses the supplied clip encoded as a 2.4 MB, silent 1080p MP4 with a 19 KB WebP poster. It has a frosted card, seven module labels, a pause control, and static fallbacks for small screens, reduced motion and data saver. The same login action, field names, CSRF token, errors and password controls remain.
- The public landing, features, privacy and terms pages reference same-origin WOFF2 font files. The legal pages use the existing local Tailwind stylesheet. The app's own fonts were already local.
- A local browser preview confirmed the desktop video, narrow layout, seven labels, password toggle, pause control and invalid-credential feedback. `tests/test_security.py` passed 58 tests; the focused motion and narrow-screen Playwright file passed 5 tests; the existing sign-in/theme browser test and public font asset check also passed.
- Before a public release, verify the static asset copy to `/var/www/themisiq`, nginx/Cloudflare MIME and range behavior for the media, and the optimized clip's display rights. Check the final appearance on a physical phone and at 200% zoom.

## Original design decisions

- Confirm the source video's license/provenance for public website display.
- Mobile uses the poster only in this build.
- Review the saved desktop and narrow preview images before committing or releasing.

## Reference guidance

- [MDN video element and poster behavior](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/video)
- [MDN autoplay guidance](https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Autoplay)
- [MDN reduced-motion media query](https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Media_queries/Using_for_accessibility)
- [W3C WCAG 2.2 pause, stop, hide](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide)
- [W3C WCAG 2.2 contrast minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
- [web.dev guidance on self-hosted font delivery](https://web.dev/learn/performance/optimize-web-fonts)
- [UK ICO guidance on external font libraries and IP addresses](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guidance-on-the-use-of-storage-and-access-technologies/what-are-the-exceptions/)
