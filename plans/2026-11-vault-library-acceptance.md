# Evidence Vault library acceptance (Phase 1b gate), 2026-11-09

Branch `claude/vault-library-acceptance`, from `master` 53fe8351 (PR 48 merge). The owner asked in chat on 2026-11-09 to "build 1": finish the Evidence Vault library checks. This is chat confirmation, not sign-off.

## Starting point (checked in code before building)

The Phase 1b deliverables in `design/evidence-vault/PLAN.md` section 9 are already built: list-first view, a work bar with smart views (All, Needs filing, Waiting for review, Review due, Requests, Recently updated), a closed Insights panel, filter chips with Clear filters, saved views, a "Showing X to Y of N" pager, a detail drawer, and Find evidence. Existing browser tests cover the work view counts, phone width, stat cards as buttons, detail tabs, Escape and bulk selection by keyboard.

The two open gate items are:
1. Keyboard and zoom review (200% zoom has not been checked).
2. Every metric drills into its filtered list.

## Findings

| # | Finding | Status |
| --- | --- | --- |
| F1 | An Insights card (Total, Expiring 30d, Needs filing, a module) kept any search, module, type, state, owner, folder or filing scope already in place, so the list it opened could be shorter than the number on the card. A module card also kept the current work view. | fixed: a card clears every other filter first (`evClearFilters`), and a module card opens All for that module |
| F2 | The work view counts (All, Needs filing, Review due and the others) count the whole library, but a search or filter narrows the list each tab opens, so "Needs filing 3" could open a list of 1. | fixed: the counts are hidden while a filter narrows the list; the pager gives the list's own total. Requests is a link to another page and keeps its count |
| F3 | At 200% zoom (and on any narrow window) the page bar kept its fixed height while its nine buttons wrapped, so buttons spilled over the title and under the page below. | fixed: the Vault's page bar grows and wraps (`.ev-topbar`), title and buttons share the first row when they fit |
| F4 | The breadcrumb said "Command Centre" on the Vault and the browser tab said "Evidence Repository". | fixed: both say Evidence Vault |
| F5 | "Clear filters" left a company view (By reviewed company) and a status filter in place, and neither had a chip, so a list could stay narrowed with nothing on screen saying why. | fixed: both have a chip and both are cleared |
| F6 | Keyboard: every control on the page is reachable by Tab with a visible 3px focus ring, a "Skip to main content" link comes first, and the detail panel closes on Escape (existing test). | no change needed |

## Decisions (chat confirmation, not sign-off)

| Decision | Why | Cost | How to change |
| --- | --- | --- | --- |
| Work view counts are hidden while a filter is on, rather than recounted for the filter. | A count must be the length of the list it opens. Recounting every view for every filter adds five counting queries to each list load. | While filtering, a person sees the total of the open list only (in the pager), not how the filter splits across views. | Return per-view counts for the current filters from `/evidence/api/items` (reuse `_library_page`'s filter clauses) and stop toggling `ev-narrowed` in `evActiveChips`. |
| The "Links" figure in Insights stays a plain number with no list. | It counts links, not files; there is no list of links to open. | It is the one Insights figure that does not open a list. | Turn it into a button that opens a list of linked files if one is wanted. |
| The coverage figures (records with a live link, current proof, accepted) stay plain numbers. | They count records in other modules, not Vault files; the Command Centre "without proof" card is where those records are listed. | No drill-down from the coverage panel. | Link each module row to that module's records filtered by proof state once those modules offer such a filter. |
| Only the Vault's page bar grows and wraps. | 11 other module templates use the same fixed-height bar; changing the shared rule touches every module and needs its own browser pass. | Other module pages with many buttons may still overflow at 200% zoom. | Move the `.ev-topbar` rule to `.topbar` in `templates/base_shell.html` after checking each module. |

## Evidence

| Check | Result |
| --- | --- |
| New browser test: an Insights number opens its whole list while a search is on (Needs filing and a module card), and the work counts hide while filtered | passed |
| New browser test: at 640 by 400 (200% zoom of 1280 by 800) every page bar button sits inside the bar, no sideways scroll, title and breadcrumb say Evidence Vault | passed |
| Screenshots at 200% zoom in light and dark, and at 1280 wide | checked |
| All Vault browser tests (`tests/ui -k "evidence or vault"`) | 73 passed |
| Backend Vault and CSP tests (`tests -k "evidence or vault or csp"`, browser excluded) | 259 passed, 6 skipped |
| `node --check`, `git diff --check` | clean |

## Change log

- 2026-11-09: branch created; plan written after reading the Vault page, its stats endpoint and the list filters.
- 2026-11-09: keyboard, 200% zoom and drill-down pass run in a real browser; F1 to F5 fixed in `modules/evidence/templates/evidence_index.html` and `static/js/evidence_vault.js`; two browser tests added to `tests/ui/test_evidence_library_ui.py`.
