# Landing page and features page: release readiness

Branch `claude/landing-hero-connected`. Owner, 2026-10-21: "start the official build of the features page and other
redesigns of the landing page we did and be ready for deployment".

**Ready for deployment** means a pull request that is checked and mergeable, plus deployment steps the owner can run.
Deploying is the owner's step: the live site at themisiq.net changes only when `setup_nginx.py` runs on the VPS.

## What ships

- **Landing page:**
  - The connected-line 3D hero.
  - The labels font, with no dots.
  - "Every discipline" copy.
  - A seventh module tab (AI Governance) with its screenshot.
  - The "AI use summary" drafting tab.
  - The pricing section.
  - A Pricing link in the navigation.
- **Features page:** the module switcher, guardrails, the connected section, frameworks and the capability index.
- **Demo request:** sends the chosen package.

## Findings before release (2026-10-21)

1. **Nothing new is live yet.** `https://themisiq.net/features.html` answers 404, and the live index is dated
   2026-10-07.
2. **No security headers on the site.** Cloudflare sits in front and adds HSTS. The origin nginx block in
   `setup_nginx.py` sends no `X-Content-Type-Options`, `Referrer-Policy`, framing protection or content security
   policy.
3. **Cloudflare injects scripts** into the live page: an inline bot-management script and its email-protection script.
   A content security policy that restricts scripts would break them, or need Cloudflare settings changed. Decision:
   - The policy sets `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'` and `form-action 'self'`.
   - It also adds `nosniff`, a referrer policy and a permissions policy.
   - It does not restrict scripts. The site is static, with no user content and no sign-in, so the risk is low.
   - How to tighten later: turn off Cloudflare's email obfuscation and bot script injection, then add
     `script-src 'self'` with a hash for the import map.
4. **Prices are proposals.** The pricing section shows a "Proposed" badge. Publishing prices needs the owner's yes, and
   the badge goes when they are confirmed.

## Steps

1. Commit the work in progress (pricing, landing fixes, AI Governance screenshot).
2. Merge `origin/master` into the branch. It was stacked on an old head of PR 13.
3. Add the security headers to the landing server block in `setup_nginx.py`.
4. Audit:
   - Every internal link and asset on both pages resolves.
   - No console errors.
   - Sage and Dusk; desktop, pane width and phone width; no horizontal overflow.
   - No em dashes, no counts outside pricing, no pink, no coloured top borders.
   - The sitemap lists `features.html`.
   - Claims are checked against the capability sheet.
5. Push and open the pull request.
6. Write the owner's deployment steps: one command per step, no pipes.

## Deployment steps (owner, after PR 13 and PR 18 are merged)

Run these one at a time in the Hetzner console:

1. `cd /project`
2. `git pull origin master`
3. `sudo python3 /project/setup_nginx.py`
4. In Cloudflare, purge the cache for themisiq.net. Stylesheets and scripts can otherwise be served stale; the changed
   ones carry new version numbers, but `styles.css` does not.
5. Open `https://themisiq.net/features.html` and `https://themisiq.net/#pricing` and check both pages load.

**To roll back:**

1. `cd /project`
2. `git checkout <previous commit> -- landing_page setup_nginx.py`
3. Run step 3 again.

The app at `app.themisiq.net` is not affected by any of these steps.

## Log

- 2026-10-21: plan written; findings 1 to 4 recorded.
- 2026-10-21: steps 1 to 4 done.
  - Work committed as `b87bb9e`. PR 13's branch and `origin/master` (PR 17) are merged in; both merged cleanly
    because PR 13's branch already carried the reconciled AI Governance tests.
  - Security headers added to the landing server block in `setup_nginx.py`. `nginx -t` runs before any restart, so a
    bad config cannot take the site down.
  - Audit results:
    - A script check finds every local link, asset and anchor resolves on index, features, privacy and terms.
    - The sitemap lists `features.html`.
    - No em dashes.
    - The claims checker against `origin/master` finds 145 lines and none missing; the regenerated sheet only
      refreshes test counts. The pricing FAQ and the AI use summary are backed by sheet lines 13, 56, 64, 128 and
      150.
    - Browser: both pages in Sage and Dusk at 1024 px and 375 px. No console errors and no horizontal scroll. The
      hero's view buttons scroll sideways on a phone by design.
  - Fixed during the audit: the last pink, the Dusk ERM token in `features.css` (`#f19ab4` to `#f87171`).
- 2026-10-21: step 5 done: PR 18 opened (https://github.com/AliMoyo1/ThemisIQ/pull/18), auto-fix on. Step 6: deployment steps written above.
