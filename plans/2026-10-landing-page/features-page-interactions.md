# Features page: interaction design

Companion to [PLAN-features-page.md](PLAN-features-page.md), [features-page-content.md](features-page-content.md) and
[features-page-copy.md](features-page-copy.md). Date: 2026-10-21. Owner request: the features page must be interactive,
reusing the click interactions of the landing page so the content is appealing to click through.

## 1. What the landing page already does (read from `landing_page/*.js` on `master`)

| Pattern | Where on the landing page | Code | Behaviour |
| --- | --- | --- | --- |
| **P1 Module switcher** | Hero and Modules | `app.js` `selectModule`, `moduleTabs` keydown, `reset-view` | Tabs swap a product screenshot and the accent colour; arrow keys move between tabs; a reset returns to the Command Centre |
| **P2 Story tabs** | Platform in motion, Intelligence | `features.js` `selectFeature`; `intelligence.js` `selectIntel` | A tab list with one scene per tab, roving keyboard focus |
| **P3 Stepper with replay** | How it connects | `intelligence.js` `showFlowNode`, `replayFlow` | Click a stage or let it play; a readout names the stage; plays once when scrolled into view; respects reduced motion |
| **P4 Choice chips** | Draft types, Ask ARIA questions, horizon themes, risk scenarios | `intelligence.js` `selectDraft`, `[data-ask]`, `[data-context]`, `[data-risk]` | Pressed-state buttons that change a panel from a small data table; risk chips highlight the contributing signals |
| **P5 Live countdown** | Privacy jurisdiction picker | `features.js` `privacyRules`, `updatePrivacyClock` | Chips change the authority and rule; an illustrative clock ticks |
| **P6 Event route replay** | Connected response | `features.js` `replayResponse` | One event fans out to follow-up records, replayable |
| **P7 Linked-record selector** | Evidence Vault | `features.js` `evidenceLinks` | Select a linked record; a detail panel explains the use |
| **P8 Arrange and hide cards** | Command Centre | `features.js` `animateCardLayout`, `move-audit`, `toggle-briefing` | Cards reorder or hide with a smooth layout animation |
| **P9 Framework ribbon** | Hero | `features.js` `framework-track` | A moving list of standards, duplicate set hidden from assistive technology |
| **P10 Reveal on scroll, theme switch** | Whole page | `features.js` reveal targets; `app.js` `applyTheme` | Sections ease in once; Sage and Dusk themes |

## 2. Principles

1. **Reuse, do not reinvent.** Every interaction on `/features` is one of P1 to P10, extracted into one shared script
   (`landing_page/interactions.js`) that both pages load. The landing page keeps working unchanged in behaviour.
2. **One main interaction per section.** The interactive study sits at the top of a section; the capability lists below
   stay plain text, so search, filters and search engines can read everything.
3. **Every interaction teaches a real capability.** Each one demonstrates a line in the capability sheet; nothing is
   decoration.
4. **Illustrative, always labelled.** Example data only, with the same "Illustrative example" footnotes as today.
5. **Works without script.** With JavaScript off, every scene's content is visible in order; the controls simply do
   nothing.
6. **Accessible.** Tabs use `role="tablist"` with arrow keys; chips use `aria-pressed`; changing readouts use
   `aria-live="polite"`; replays never autoplay when reduced motion is set; focus is always visible; both themes are
   checked for contrast.
7. **Light.** No framework, no new libraries, each section's script starts only when it scrolls near the viewport.

## 3. Interaction for each section

| Section | Interaction | Pattern | What the visitor does and sees | Capability it proves |
| --- | --- | --- | --- | --- |
| Header | Search and role filter | P4, plus a text filter | Type or press a role chip; capability lines that do not match fold away, section headings stay; a "Clear" chip resets | Breadth, findable |
| What sets ThemisIQ apart | Tile jump | P2 opener | Click a tile; the page scrolls to the section and opens the matching study on the right step | The five strengths |
| AI across the platform | Assistant switcher and policy card | P2 + P4 | Tabs by module swap one assistant card (sample request, answer, source line, "Human review required"). A small "Your AI policy" card has chips for data kinds; switch "Personal data" off and the sample request shows "Refused by your AI policy, nothing was sent" | Assistants per module; policy refusal before sending |
| ARIA: policy authoring studio | Five step stepper with replay, and document type chips | P3 + P4 | Steps Generate, Edit, Preview, Approve, Publish; chips pick Policy, Procedure, Standard, Guideline or Framework and an "Integrated document" toggle; the Approve step shows the author greyed out in the approver list; Publish shows the version landing in the Vault and on an audit control | Generation, workbench, branded preview, separation of duties, publication |
| ARIA: one set of controls | Multi-select standard chips | P4 (multi-select) | Select two or more standards; the Integrated, Partly matched and Unique columns update; a proposed match card shows "Awaiting a different reviewer"; "Audit these together" jumps to GRID with the same selection | IMS matching and review |
| GRID: integrated audit | Stepper continuing the selection | P3 | Steps Create, Checklist (badges per control), Finding, Corrective action, Sign-off, Share; the share step shows an expiring link | Integrated audit, findings to closure, auditor link |
| Sentinel: one breach, several duties | Jurisdiction chips that add obligations, each with a live clock | P5 extended + P4 region filter | Region chips filter the rule cards; each card shows Draft, Approved or Indicative. Add jurisdictions to a sample breach: each adds an obligation row with its own ticking clock, or "As soon as reasonably possible"; a row's "Decide" button toggles Notify or Not notifying, with a reason field | Rule cards, approval, per jurisdiction obligations and decisions |
| BCM: escalation | Replay strip | P6 | Press "Play": incident raised, owner alerted, timer runs out for its severity, alert moves to the alternate; severity chips change the window | Escalation by severity |
| ERM: scenarios and predictive risk | Scenario chips and signal highlight | P4 (the landing page's risk chips) | Chips Baseline, Exercise overdue, Control gaps; the affected risks and the contributing signals light up; a link opens the landing page's full version | Scenario Studio, predictive signals |
| ORM: from event to learning | Event selector | P7 | Pick a sample event; the panel shows its linked self assessment control, indicator movement and the continuity link | Events, RCSA, KRIs, links |
| AI Governance: life of one AI use | Six step stepper with replay | P3 | Register, Review, Assess, Decide, Watch, Prove; the Decide step shows the requester blocked from deciding; the Assess step shows the checklist ticking as assessments complete | Inventory to decision to monitoring |
| Evidence Vault | Linked-record selector with expiry chips | P7 + P4 | Pick a linked record (control, audit, incident); expiry chips 30, 7 and 1 days show the reminder that would go out; a "Campaign" tab shows a request moving from Sent to Reviewed | One proof, many uses; renewal; campaigns |
| Work and reporting | Arrange and hide cards, then a report sign-off toggle | P8 + P4 | Reorder or hide Command Centre cards; a sample report flips from Draft to "Signed off by an independent reviewer" with a share link that shows its expiry | Personal Command Centre; reports |
| Connected governance | Vendor map with a change signal replay | P6 + P7 | Pick a vendor; links light up to a continuity process, a processing activity, an audit assessment and a risk. Press "Raise the vendor's risk level"; each connected owner shows "Asked to take another look", with Confirm and Dismiss | Connected view, change signals |
| Integration and administration | Static, with a copyable API example | None | A short sample request and response block | API |
| Frameworks and jurisdictions | Ribbon and filter chips | P9 + P4 | The ribbon as on the landing page; family chips filter the standards table; region chips filter the jurisdictions table | Catalogue and coverage |
| Call to action | The landing page form | Existing | As today | |

## 4. Build approach

- **Shared helpers in `landing_page/interactions.js`:** `tabs(listEl)` (roving focus and panels), `chipGroup(el,
  {multi})` (pressed state, change callback), `stepper(el, {autoplayOnView})` (steps, readout, replay, reduced motion),
  `onView(el, start)` (start a section's script when it nears the viewport), and `countdown(el, from, hours)`. The
  landing page scripts move onto these helpers one pattern at a time, with a visual check after each move.
- **Data beside the markup:** each study's example data sits in a small object in `features-interactions.js`,
  mirroring how `features.js` and `intelligence.js` hold `privacyRules`, `draftTypes` and `riskExamples` today.
- **Styles:** reuse `styles.css` and `site-extras.css` tokens and the existing scene, chip and tab classes; add only
  what the new studies need, in `features-page.css`.
- **No new dependency**, no build step beyond the existing Tailwind file.

## 5. Checks before it ships

- Every interaction with mouse, keyboard only and a touch screen.
- Reduced motion on: nothing autoplays, every step is still reachable.
- JavaScript off: all content readable.
- Sage and Dusk themes, phone width and desktop, no horizontal scroll.
- An accessibility scan with no serious issues; no console errors.
- Every study's words match the copy file and every claim matches the capability sheet.

## 6. Effort

About four to five days on top of the page build in the plan: two for the shared helpers and moving the landing page
onto them, two to three for the new studies (Sentinel obligations, IMS selection, policy studio and the AI policy card
are the largest), and half a day of checks.
