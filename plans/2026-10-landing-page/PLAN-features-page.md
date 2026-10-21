# Plan: show how complete ThemisIQ is (landing page and a features page)

Date: 2026-10-20. Status: proposal for the owner, nothing built. Source read: `landing_page/index.html` on `master`
(`790ce1c`), the platform functions inventory (`plans/2026-10-governance-rework/08`), the AI Governance and Evidence
Vault modules, and the security assessment of the same day.

## 1. Recommendation in one paragraph

Yes, build a separate features page, and change the landing page only a little. The landing page already tells a good
story (one connected picture, six disciplines, a signal travelling between modules, evidence, the Command Centre and
four AI stories). What it cannot show is breadth: whole modules and platform functions built since it was written
appear nowhere. Adding them to the landing page would turn a calm story into a long list. So: keep the landing page
as the story, add one compact "what's inside" band that proves breadth at a glance and links out, and put the full
catalogue on `/features`, where a buyer who wants detail can scan, filter and deep link.

## 2. What the landing page shows today

| Section | Content |
| --- | --- |
| Hero | "Every signal. One clear view." Six module previews, a 16 framework ribbon |
| The system | Shared context, clear ownership, traceable action |
| How it connects | ORM event to BCM response to evidence to a decision |
| Platform in motion | Privacy across five jurisdictions, one event routed to ERM, ORM and GRID, the Evidence Vault, a personal Command Centre |
| Intelligence | Assisted drafting, Ask ARIA with sources, ERM horizon scan, predictive risk |
| Modules | ARIA, GRID, BCM, Sentinel, ERM, ORM with screenshots |
| Approach | Shared evidence, assisted intelligence, Scenario Studio |
| Contact | Demo request |

## 3. What is built but not shown

Grouped the way a buyer thinks, not the way the code is organised.

| Area | Built in the platform | On the landing page today |
| --- | --- | --- |
| **AI Governance** (a seventh workspace) | AI system inventory and intake, AI impact assessments, decisions signed on a frozen brief with separation of duties, monitoring and evaluations, human oversight arrangements, regulatory change tracking, review packs for auditors, AI literacy courses with renewal, bulk import, register of the platform's own AI features | Not mentioned; ISO 42001 only appears in the ribbon |
| **Evidence Vault** | Library with expiry and renewal, proof per control, find across content, evidence campaigns (request evidence from owners and review it), shown in each module | One story card |
| **Work management** | My Work, task board, calendar and reminders, workflows with SLAs, team view for managers, related items between modules, global search | Not mentioned |
| **Reporting** | Report builder with frozen snapshots, sign-off by an independent reviewer, named expiring shares, retention; saved views; analytics | Not mentioned |
| **Notifications** | In-app notifications, email outbox with templates, quiet hours, daily or weekly summaries, BCM incident escalation to alternates by severity | Not mentioned |
| **Readiness** | Readiness findings across the platform | Not mentioned |
| **Security and trust** | Organisation isolation, business-unit scoping, role-based access with specialist roles, MFA, audit log, encrypted transport, AI policy per organisation with provider, data category and budget controls, AI usage log | Not mentioned |
| **Integration** | REST API with keys, outbound webhooks, Slack and Teams connectors, bulk import and export | Not mentioned |
| **Administration** | Users, roles, business units and transfers, people directory, licences per module | Not mentioned |

## 4. Proposed structure

### 4.1 Landing page: small, targeted changes

1. **Hero**: keep. Change the sub line from "six disciplines" to name AI Governance too, or say "governance, audit,
   resilience, privacy, risk and AI".
2. **New "What's inside" band** after the modules section: a grid of 8 to 10 tiles (the areas in section 3), each with
   one sentence and a "See all features" link to the matching anchor on `/features`. One honest number line above it,
   for example "7 workspaces, 16 frameworks, one evidence vault". Numbers must be counted from the product before
   publishing, not estimated.
3. **Modules section**: add AI Governance as a seventh tab with its own screenshot.
4. **Nav**: add "Features" pointing to `/features`; keep "Modules" for the in-page section.
5. **Trust strip** above the contact form: three short claims a security reviewer looks for (data isolated per
   organisation, role and unit scoped access, AI controlled by your policy) with a link to a security section on
   `/features`.

Everything else stays. The page gets about one screen longer, not ten.

### 4.2 New `/features` page

Purpose: let a buyer, a compliance lead or an assessor answer "does it do X?" in under a minute.

- **Top**: title, one sentence, a search box and filter chips (by area and by role: compliance, privacy, audit, risk,
  continuity, AI, IT and security).
- **Body**: one section per area from section 3, in this order: Governance and controls (ARIA), Audit (GRID),
  Resilience (BCM), Privacy (Sentinel), Enterprise risk (ERM), Operations risk (ORM), AI Governance, Evidence Vault,
  Work and notifications, Reporting, Security and trust, Integration and administration.
- **Each section**: a short intro, a screenshot, then a list of capabilities. Each capability is one line: what it does
  for the person, written from their side ("Get a reminder before evidence expires", not "expiry scheduler").
- **Frameworks**: the full catalogue as a table (standard, version, what the platform does with it: controls, mapping,
  audit checklists).
- **Footer call to action**: the same demo request as the landing page.
- **Anchors** for every section (`/features#ai-governance`) so sales can send a direct link and the landing tiles can
  jump there.

Build it as a plain static page beside `index.html` in `landing_page/`, reusing `styles.css`, `site-extras.css`, the
header, footer, theme switch and cookie banner, so it looks like the same site and needs no new tooling. The capability
list lives in the HTML (or one small JSON file read by `features.js` for search and filters); no framework.

### 4.3 Optional later

- One page per area (`/features/ai-governance`) if search traffic or sales need it. Not before the single page proves
  too long.
- A downloadable one page capability sheet (PDF) generated from the same list.

## 5. Rules for the copy (so it stays true)

- Claim only what is built and verified on `master`. Each capability line gets a source in a working sheet (module and
  route or test) before publishing. Section 3 is a starting list, not approved copy.
- Say what needs setup: AI features need a configured provider and are governed by each organisation's policy; email
  needs a sender identity; web search for ERM needs configuration; AI Governance is switched on per organisation.
- Do not advertise MFA enforcement by policy until findings H2 and H3 of the security assessment are fixed. Wait for
  the H1 fix before calling the platform "secure by design" anywhere.
- Keep the "illustrative" labels on example data, as the landing page does now.
- No em dashes, plain words, active voice, the person's point of view.
- Regulatory claims (notification windows, jurisdictions) keep the existing disclaimer that duties depend on the event
  and current law.

## 6. Steps

| Step | What | Who | Output |
| --- | --- | --- | --- |
| 1 | Agree the structure in section 4 and the open questions in section 8 | Owner | Decisions recorded here |
| 2 | Build the capability sheet: every line, its area, its role tags, its source in the code, verified on `master` | Build | `plans/2026-10-landing-page/capability-sheet.md` |
| 3 | Capture fresh screenshots: AI Governance overview and workspace, Evidence Vault library, My Work, a report, notifications | Build | `.webp` and `.png` pairs, same sizes as today |
| 4 | Write the copy for `/features` and the landing band from the sheet | Build, owner review | Draft in the sheet |
| 5 | Build `/features` (static, shared styles, search and filters, anchors) with the interactive studies in [features-page-interactions.md](features-page-interactions.md), reusing the landing page's interactions through a shared `interactions.js` | Build | `landing_page/features.html`, `interactions.js`, `features-interactions.js` |
| 6 | Landing changes: hero line, "What's inside" band, seventh module tab, nav link, trust strip | Build | `landing_page/index.html` |
| 7 | Checks: both themes, phone width, keyboard, contrast, no console errors, every link and anchor, `sitemap.xml` and page titles updated | Build | Notes in this plan |
| 8 | Deploy to `/var/www/themisiq` with the existing process | Owner | Live |

Estimate: steps 2 to 7 are about three to four working days for a static page, plus four to five days for the interactive studies (owner request, 2026-10-21; see the interaction design).

## 7. Risks

- **Overclaiming.** The biggest risk. Mitigated by the capability sheet with sources and the setup notes.
- **Stale page.** The features page will drift as the product grows. Add a line to the release checklist: update the
  capability sheet when a feature ships.
- **Clutter creeping back onto the landing page.** Hold the line: new things go to `/features`, the landing page gets a
  tile at most.

## 8. Decisions for the owner

1. Separate `/features` page (recommended) or a longer landing page?
2. Should AI Governance be presented as a seventh module, or as a capability across the platform?
3. Which numbers may we publish (workspaces, frameworks, AI features)? Any customer names or logos (for example
   Econet), or none?
4. Should the security and trust section wait for the H1 to H3 fixes, or go out with the claims that are already true?
5. Is the downloadable capability sheet wanted now or later?

## Owner decisions (chat confirmation, 2026-10-20, not a sign-off)

1. **AI Governance is the seventh module**, with its own tab, screenshot and features section. Why: it has its own
   workspace, roles and records, and buyers look for it by name. How to change: fold its section into "Intelligence".
2. **Numbers are on hold.** No counts of modules, frameworks, jurisdictions, record types or AI features anywhere on the
   site until the owner releases them. The "7 workspaces, 16 frameworks" line in 4.1 is dropped. Cost: breadth must be
   shown by the content itself, not by figures. How to change: add a number line once approved.
3. **Security is being handled separately.** The security and trust section is drafted but published only when the
   owner confirms the high findings are fixed; until then the trust strip in 4.1 is held too.

The section by section content is in [features-page-content.md](features-page-content.md).

4. **Every Sentinel jurisdiction is named** on the features page (owner: all will be ready when live). Why: breadth of
   jurisdictions is a selling point and the registry already covers them. Cost: each must be specialist confirmed and
   DPO approved before launch, and Canada's entry names a bill, so it is shown as proposed. How to change: filter the
   list to approved cards only.
5. **Predictive risk** (recommendation, owner asked me to decide): a compact static panel in the ERM section that names
   the signals it combines and links to the landing page's interactive version. Why: the features page is for scanning
   and proof, the landing page is for the experience; one interactive means one thing to maintain. Cost: visitors who
   land on `/features` first see a still image, one click from the live demo. How to change: move the interactive
   study onto `/features` and leave a link on the landing page.
6. **Industry framing stays general.** No sector names in headings or examples. How to change: add a sector line to the
   "What sets ThemisIQ apart" section.

## Log

- 2026-10-20: plan written from the landing page on `master` and the platform inventory. Nothing built.
- 2026-10-20: owner decisions 1 to 3 recorded; content breakdown written in features-page-content.md.
- 2026-10-20: owner decisions 4 to 6 recorded (all jurisdictions, predictive risk panel, general framing).
- 2026-10-20: added the policy authoring studio to ARIA, the "AI across the platform" section, and how ARIA connects to AIIAs, DPIAs and continuity plans. Found: the live landing page's assisted drafting panel lists AIIA, but no AI drafting exists for AIIAs; remove it from that panel or build it before launch.
- 2026-10-20: step 2 done as a generated sheet: `capability-sheet.md` from `build_capability_sheet.py` against `origin/master`.
  139 lines, all backed by code; 17 lines prove only that the module file exists (`.` pattern) and need a closer look
  when their copy is reviewed; 3 lines have no matching tests (input wrapping, ARIA gap analysis, ORM RCSA actions).
  The input wrapping line is held until security finding M3 is fixed.
- 2026-10-20: page copy drafted in features-page-copy.md from the capability sheet; brief corrected (no count in the header, AI tile points to 1a, integrated audit links and badges equivalents but does not copy results).
- 2026-10-21: owner asked for an interactive features page reusing the landing page's click interactions; interaction design written in features-page-interactions.md and step 5 updated.
- 2026-10-21: landing hero rebuilt as the connected line (eight stations, one incident, silos toggle), label font and dots changed across the landing page, deploy copy fixed for vendor/; full record in hero-connected-line.md.
- 2026-10-21: owner asked to start the features page build (step 5), high spec and premium, with full visibility in the browser.
- 2026-10-21: step 5 built: landing_page/features.html with features-page.css and features-page.js. Every section of the copy file, a sticky section bar that follows the reader, search and role filters with highlighted matches, and eleven interactive studies (AI assistants with the policy refusal, policy authoring studio, integrated controls, integrated audit, privacy rule cards with live obligation clocks, escalation, scenarios, events, the AI use journey, Evidence links and expiry, Command Centre cards and report sign-off, connected vendor change signal). Module colours are the app's; Dusk ERM uses #f87171 instead of the pink #f19ab4. The landing nav Features link now opens the page; sitemap updated. Checked in the browser at desktop, 1440 px and phone width, Sage and Dusk, every study driven by script, no horizontal overflow.
