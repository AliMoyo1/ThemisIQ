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

## Log

- 2026-10-21: plan written; findings 1 to 4 recorded.
