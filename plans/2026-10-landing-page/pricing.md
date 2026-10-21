# Pricing: proposal and landing page calculator

Branch `claude/landing-hero-connected`. Owner request, 2026-10-21:

- Add a pricing area to the landing page, adapted from a supplied React component ("usage slider pricing table"), with
  the same visual elements in our colours.
- Advise on pricing, which is not set yet: modular, per package. Look at other vendors, and include AI Governance.

## Status

**Proposal only. None of these prices is approved.**

- The section is built so the owner can see it working.
- Every number lives in one object at the top of `landing_page/pricing.js`, so changing a price is a one-line edit.
- Do not deploy the landing page with this section until the owner confirms the prices.
- This also overrides the earlier "no numbers on the site" hold for this one section, so it needs an explicit yes.

## What the market charges (October 2026)

Few vendors publish list prices. The figures below are third-party estimates (deal data and reviews), not quotes.

| Vendor | Shape | Typical annual cost (USD) |
| --- | --- | --- |
| Vanta | Tiers by headcount and framework | Core about 10k; Plus 15k to 30k; enterprise 80k and up |
| Drata | Tiers, framework add-ons | Median deal about 25k; range about 10k to 60k; enterprise to 100k and up |
| Secureframe | Tiers, some services included | 7.5k to 20k entry; 20k to 45k mid |
| OneTrust GRC and privacy | Per module | About 8k to 13k per module (GRC); privacy suite from about 44k |
| AuditBoard | Per module, by controls and audits | About 30k to 42k per module |
| LogicGate | Per application, plus power users | 15k to 45k per application |
| Archer | Per module, customised | 55k to 150k and up |
| MetricStream, ServiceNow IRM | Per user per module | 2.4k to 8k per user per year; six figures typical |
| Fusion (continuity) | Platform | Average about 93k |
| AI governance (Credo AI, Holistic AI, OneTrust AI) | Custom quotes | Budget guides suggest 25k to 200k and up |

### Patterns worth copying

- **Platform plus modules.** OneTrust, AuditBoard, LogicGate and Archer all sell the platform and charge per module.
- **Packages for the common case.** Vanta, Drata and Secureframe sell three tiers, so buyers do not have to design their
  own bundle.
- **Pay for working users, not readers.** ServiceNow charges "fulfillers" and LogicGate charges "power users". Viewers
  cost little or nothing.
- **Annual contracts, shown monthly.** List prices are annual. Monthly figures appear only as a way of showing them.
- **Metered AI.** AI usage is usually included up to an allowance, then charged.

### What buyers dislike

- Opaque quotes.
- Renewal jumps of 10% to 50%.
- Paying again for each framework.
- Implementation fees that are not disclosed up front.

## Recommended model for ThemisIQ

Three packages. Each one includes:

- The shared platform: Evidence Vault, Command Centre, My Work, reports, connected records, the API, every framework in
  the catalogue and every privacy jurisdiction.
- A number of modules.
- A number of named specialist users.
- The AI assistants, included under fair use.

**Revision 3** (owner, 2026-10-21): "revise prices down to undercut competition"; Essentials and Professional can be
billed monthly or annually; Enterprise is quote only. The first two versions are in this file's git history.

Prices are USD. Annual billing is 10 months of the monthly price (two months free).

| | Essentials | Professional | Enterprise |
| --- | --- | --- | --- |
| Modules | 2 of your choice | 4 of your choice | All 7, including AI Governance |
| Monthly billing | 720 a month | 1,800 a month | Quote |
| Annual billing | 7,200 a year | 18,000 a year | Quote (internal reference: 36,000 a year) |
| Named users included | 10 | 25 | From 50 |
| Each extra user | 20 a month (200 a year) | 15 a month (150 a year) | Volume pricing (reference 10 a month) |
| User limit | 50 | 250 | None |
| AI assistants | Included | Included | Included |
| Fair use guide (not published) | 1,500 a month plus 75 per user | 5,000 plus 120 per user | 12,000 plus 150 per user |
| Support | Email, next business day | Priority, named contact | Dedicated manager, uptime commitment |
| Onboarding, one time | 1,500 | 4,000 | Quoted |

Add-ons:

- **Extra core module** on Essentials or Professional: 500 a month (5,000 a year).
- **AI Governance:** a premium module.
  - As an add-on: 800 a month (8,000 a year).
  - Included in Enterprise.
  - On its own: AI Governance Starter, 1,000 a month (10,000 a year), up to 10 specialists.

The price ladder still holds. These were checked in the calculator at 20 users, monthly billing:

| Modules chosen | Essentials | Professional | Enterprise | Best fit |
| --- | --- | --- | --- | --- |
| 2 or 3 | lowest | | | Essentials |
| 4 | 1,920 | 1,800 | | Professional |
| 5 | 2,420 | 2,300 | | Professional |
| All 7 | 3,720 | 3,600 | 3,600 reference | Enterprise |

Enterprise is also the fit:

- Past 250 users.
- Whenever its internal reference costs less than the other packages.

"Request quote" then sends the plan `enterprise` with the demo request.

### Why these numbers

1. **Below every entry point we could find.**
   - Essentials costs 7,200 a year, against Drata and Secureframe at about 7.5k, Vanta Core at about 10k and StandardFusion
     at about 9k to 18k.
   - Those buy one discipline (security compliance). Essentials buys any two modules.
2. **Professional at 18,000 a year is under Drata's median deal (about 25k)** and works out at 4.5k per module. That is
   about half OneTrust's per-module figure (8k to 13k) and a sixth of AuditBoard's (30k to 42k).
3. **Enterprise as a quote.**
   - Large buyers expect to negotiate, and a published number would anchor them.
   - The internal reference (36k a year for all seven modules and 50 users) is still far below buying seven modules
     elsewhere (60k to 300k). It is the floor for the conversation.
4. **Two months free on annual billing** is the most common SaaS pattern. It rewards commitment without a separate
   discount table.
5. **AI stays included.**
   - The fair use guide is scaled down with the lower prices.
   - Essentials' guide costs us about 50 to 70 USD a month at average usage, under 10% of the price.
   - The AI policy budget caps the worst case.
6. **AI Governance stays premium but cheap for its market.**
   - 8,000 a year as an add-on, or 10,000 on its own, against 25k to 200k for dedicated tools.
7. **Margin check.** Hosting on the shared VPS is small per tenant, and AI is the main variable cost. Watch:
   - Onboarding effort at these prices. It is why onboarding remains a separate one-time fee.
   - Support load on Essentials.

### Commercial terms to decide

- **Currency and regions.** List in USD. Consider a regional price list (for example 20% to 30% lower) for Southern
  Africa, billed in local currency where exchange controls make USD difficult.
- **Discounts.** 10% for a three-year term, and a price lock on renewal. A cap on renewal increases (for example 7%)
  answers a common complaint.
- **Public sector and non-profit.** A published discount, or quote only.
- **Hosting.** Prices assume our hosted service. A dedicated or in-country deployment is quoted separately.

## The landing page calculator

The supplied component is React, Tailwind and TypeScript, built for a shadcn project. The landing page is static HTML,
CSS and JavaScript served by nginx, with no build step. Adding React, Tailwind and shadcn for one section would add a
toolchain to a page that has none. The component is therefore ported to plain JavaScript and CSS with the same parts:

- The "Usage calculator" header.
- Two sliders, each with a tooltip that follows the thumb, a filled track and minimum and maximum labels.
- A recommendation bar.
- A comparison table with a highlight that slides behind the best-fit plan.
- Rolling price digits and counting figures.
- "Choose" buttons.
- A one-pass guided tour that stops when the visitor touches anything, with a Replay button.

Its pricing maths (`quoteUsagePlan`, including graduated user tiers and overage rounded up to the next 1,000) is kept
exactly.

The axes are adapted:

- "Seats" becomes **named users**.
- "Requests" becomes **AI requests per month**.

Two visual details are changed to respect standing owner rules:

- The highlight's coloured top strip is removed (no coloured top borders).
- The dot before "Best fit" is removed (no bullet dots on the landing page).

"Choose" fills the plan into the existing demo request form, whose API already stores a `plan` value. The value sent is
a fixed plan id from the page, never free text.

## Steps

1. Write this plan.
2. Build `pricing.css` and `pricing.js`, add a pricing section to `index.html`, and link it from the navigation.
3. Make "Choose" set the plan on the demo form (`site.js`).
4. Check in the browser at desktop, pane width and phone width, in Sage and Dusk: sliders, keyboard, tour, replay,
   Choose, reduced motion and no overflow.
5. Log here.

## Log

- 2026-10-21: plan and pricing analysis written.
- 2026-10-21: steps 2 to 5 built.
  - New files: `landing_page/pricing.css` and `pricing.js`.
  - `index.html`: a pricing section before the contact section, and a Pricing link in the navigation. `features.html`
    has the same link.
  - `site.js` sends the chosen plan with the demo request.
  - A third slider (core modules) and an AI Governance switch were added to the component's two sliders, because the
    pricing is modular.
  - Checked in the browser:
    - Every price matches the formulas: 20, 60 and 300 users; six modules with AI Governance; 80k AI requests.
    - Essentials is disabled above 50 users. The highlight follows the best fit, and the digits roll without being
      rebuilt.
    - The tour runs once and stops on any touch, and Replay works. "Choose" sets the plan and scrolls to the form.
    - Sage and Dusk, pane width and 375 px. No horizontal overflow and no console errors.
  - Fixed during the check:
    - The add-on prices (see Add-ons).
    - The default AI requests are now 2,000, so a small team does not start with an overage.
    - Smaller prices and plan names on the narrowest width.
- 2026-10-21: **owner decision** (chat confirmation, not a sign-off): "click to select modules, not a slider", "AI
  token pricing incorporated into the pricing by default and explained in FAQ", "the slider should be for named
  users". Done:
  - **Modules** are now chips, with AI Governance marked premium. At least one module stays selected. Choosing only AI
    Governance points the visitor to AI Governance Starter.
  - **One slider**, for named users.
  - **AI usage is no longer metered on the page.** The table shows "AI assistants: Included". The fair use guide and
    the budget control are explained in a new pricing FAQ, which also replaces the "every package includes"
    paragraph.
  - Why: buyers dislike metered AI bills, and our AI policy budget already caps cost. Cost: heavy AI users are handled
    through a pre-agreed top-up instead of automatic overage. How to change: put the request fields back on the plans
    in `pricing.js` and restore the slider and rows from git history.
  - Checked in the browser: chip selection and prices (20 users with every module gives Enterprise, three modules gives
    Essentials at 2,450), the last-chip guard, the AI Governance only message, the rows, Dusk, and no console errors.
- 2026-10-21: **owner decision** (chat confirmation, not a sign-off). The owner asked what the "Monthly estimate" row was
  for, asked for a switch to show annual pricing for Essentials and Professional, wanted Enterprise as "request quote",
  and wanted prices revised down to undercut the competition. Done:
  - "Monthly estimate" was only the table's corner label; the prices beside it were what changed. It now reads "Your
    price, billed annually" or "billed monthly".
  - A Monthly / Annual switch sits in the calculator header. Annual is the default and gives two months free.
  - Enterprise shows "Custom" and "Request quote". Its figures stay in `pricing.js` as an unpublished reference that
    decides when it is the best fit.
  - Prices revised (revision 3 above). The FAQ is updated to match.
  - Packages a selection exceeds are dimmed.
  - Cost: Enterprise visitors see no number, so some may leave without asking. How to change: remove `quote: true` from
    the Enterprise plan in `pricing.js`.
  - Checked in the browser:
    - Annual and monthly prices at 15 users.
    - The four, five and all-module ladder at 20 users.
    - 300 users: only Enterprise is available.
    - The rows, the buttons and the corner label. No console errors.
- 2026-10-21: owner asked what the line under each price was for. It repeated the Modules and Users included rows. It now says who each package is for: "For one team getting started", "For a growing programme" and "For the whole organisation". Checked in the browser.
- 2026-10-21: owner noticed "Users included" (10) seemed to contradict the slider (15). The row is now "Your users" and follows the slider. For example, at 15 users it reads "10 included + 5 extra", "15, all included" and "From 50"; past a limit it reads "Up to 50 only". Checked at 5, 15, 40, 60 and 300 users.
- 2026-10-21: owner asked why Professional was cheaper than Essentials at 50 users with every module. Essentials includes only 2 modules and 10 users, so 4 extra modules, AI Governance and 40 extra users came to 4,320 a month, against 3,975 for Professional. The ladder works as designed but the table did not explain it. Now, when a bigger package costs less for the selection, the smaller one is dimmed and says "Professional costs less for this" or "Enterprise costs less for this". Checked at the start state, with four modules (Essentials flagged) and with every module at 50 users (both flagged).
