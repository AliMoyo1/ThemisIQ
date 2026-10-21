# Features page redesign: less text, one way to explore

Branch `claude/landing-hero-connected`. Follows the first build of `landing_page/features.html` (log in
[PLAN-features-page.md](PLAN-features-page.md)).

## Why

Owner feedback, 2026-10-21: "a lot of text, also not interactive and cluttered". Research the same day on Vanta, Drata,
Hyperproof, Optro (AuditBoard) and Secureframe:

- Every one of them uses its homepage as a short hub and gives each product its own page.
- A feature block is roughly 20 to 50 words, paired with a visual. Vanta's product page has 11 such blocks.
- There is one main interactive pattern, not many. Hyperproof uses seven product tabs, each with about 30 words and an
  image.
- Proof (logos, quotes, outcomes) carries the persuasion. We hold numbers for now, so we cannot lean on this.
- Nobody lists every feature. The detail lives deeper, or in the demo.

Our first build had about 3,600 words and 204 list items on one page, 19 interactive panels spread between the lists,
and 2 images.

## Owner decision (chat confirmation, 2026-10-21, not a sign-off)

"Go with your recommendations, plan it first then build." Adopted:

1. **One module switcher is the centre of the page.** Seven tabs, one per module. Each tab has a headline, about 35
   words, three short benefits and that module's interactive study.
   - Why: one place to explore, the way Hyperproof does it.
   - Cost: a visitor sees one module at a time, not all seven on a scroll.
   - How to change: render the seven panels in sequence without the tab bar.
2. **Full capability lists move into a collapsed "Every capability" index**, opened per area, with search.
   - Why: the lists stay true and findable without filling the page. About 1,200 words are visible before anyone opens
     anything.
   - Cost: a scanner must open an area to see the detail.
   - How to change: add `open` to the `<details>` elements.
3. **The role filter is removed. Search stays, inside the index.**
   - Why: the filter existed because the page was too long to scan. Once the page is short, it is extra controls.
   - Cost: no one-click view of only, for example, privacy items; the privacy area of the index does that job.
   - How to change: bring back the `data-roles` attributes and the chip row from git history (commit before this change).
4. **Kept: eight studies.** These are AI assistants with the policy refusal, the policy authoring studio, integrated
   controls, privacy rule cards with clocks, escalation, scenarios, events, the AI use journey, and the connected vendor.
   **Dropped: three.** These are the integrated audit stepper, Evidence links and expiry, and Command Centre and report
   sign-off.
   - Why: the dropped three repeat ideas shown elsewhere (integration, linking, sign-off). They are replaced by short
     tiles and the index.
   - How to change: they are in git history.
5. **The three guardrail groups become one grid of six.** Each has a title and one line visible, and the detail behind a
   click.
   - Why: AI trust matters to buyers but should take one screen.
   - Every line of the old groups is still in the index.
6. **Screenshots are not used yet.** The existing `screenshot-*.webp` files show near-empty dashboards (1%, zeros, "No
   data subject requests found"), a real person's name and the old AIIA menu in Sentinel.
   - Why: an empty product undersells it more than a mock does.
   - Cost: the page still shows illustrations, not the real product.
   - How to change: capture fresh screenshots from a seeded demo organisation (step 7) and add one per module tab.
7. **Frameworks and jurisdictions become chip rows instead of two tables.** Same names, less reading.

Copy rules are unchanged: every claim comes from `capability-sheet.md`, there are no counts, no em dashes, no coloured top
borders and no pink. The security section is still held.

## New structure

1. Hero: title, one line, two buttons ("Explore the modules", "Request a demo"). No search or chips.
2. Why ThemisIQ: the five tiles, unchanged.
3. Modules: a tab bar with seven tabs. Each panel has a kicker, headline, summary, three benefits, "See every
   capability" and the study.
4. AI you can govern: the assistant study, then six guardrail cards.
5. Connected: the vendor study, then three tiles (Evidence Vault, Work and reports, Integration and administration).
6. Frameworks and jurisdictions: chip rows.
7. Every capability: search, then a `<details>` element per area, holding the existing lists.
8. Contact.

The section bar shrinks to Why, Modules, AI, Connected, Frameworks and Every capability.

## Steps

1. Rewrite `features.html` to the new structure, moving the existing lists into the index without changing their words.
2. JS: module tabs (arrow keys, `#governance`-style deep links open the tab), search opens matching areas and closes them
   again when cleared, remove the role filter and the three dropped studies.
3. CSS: the tab bar and panel, guardrail cards, platform tiles, chip rows, the index; remove the CSS of the dropped
   pieces.
4. Check in the browser: desktop, 1440 px and phone width, Sage and Dusk, every tab and study, search, deep links, no
   horizontal overflow, no console errors.
5. Count the visible words, aiming for about 1,200.
6. Log here and in PLAN-features-page.md.
7. Later, separate step: seed a demo organisation and capture one screenshot per module.

## Log

- 2026-10-21: plan written.
- 2026-10-21: steps 1 to 6 built in `features.html`, `features-page.css` and `features-page.js`.
  - Changed from the plan: the hero said "Seven modules", which is a count, and counts are on hold (owner decision 2 in
    PLAN-features-page.md). It now reads "Everything you govern. One connected system."
  - The dropped studies' CSS and JS are removed. The role filter is gone. Every capability line is in the index with its
    words unchanged.
  - Results: the page is about 8,900 px tall at desktop, down from about 20,500 px. About 920 words are visible before
    anything is opened, down from about 3,600.
  - Checked in the browser:
    - Every module tab, and arrow keys (with wrap-around).
    - `#privacy`-style deep links and the "What sets ThemisIQ apart" tiles open the right tab.
    - "See every capability" links open their index area.
    - Search opens matching areas, hides the rest, counts and highlights matches, shows "no results", and closes the
      areas it opened when cleared.
    - Sage and Dusk; desktop, pane width and 375 px phone width; no horizontal overflow; no console errors apart from
      the browser's own `favicon.ico` probe.
  - Fixed during the check:
    - The panel header stacks below 1180 px.
    - On a phone, the chosen tab scrolls into view in the tab strip.
  - Step 7 (fresh screenshots) is not started.
