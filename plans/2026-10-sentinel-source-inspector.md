# Sentinel source-watch workspace

## Problem and goal

Manual checks currently refresh the source list and clear the review panel. The check result and proof appear below a potentially long list, so a specialist cannot see what happened next to the source they checked. Keep source selection, check outcome, proof and review together without changing the legal approval workflow.

## User journey

1. Jurisdiction Manager opens with a compact source list and a selected-source inspector. Pending captures and failed checks have distinct badges and filters. Search by source or jurisdiction and filter by status. Keep cadence and capture-retention settings in a disclosure above the workspace.
2. Selecting a source updates the inspector. On a phone it opens as a dismissible sheet; the list remains behind it. The inspector identifies the pinned authority, last check, capture/review state and when the next manual check is available.
3. Check now immediately shows progress in the inspector. Use the existing check response (`result`, optional `capture_id`, optional `error`) to show unchanged, first baseline, changed text or failed extraction. Refresh the selected source without losing its selection or jumping down the page. A 429 appears beside the action with the next available time. An error never means unchanged.
4. If a capture exists, show the stored-byte integrity result, pinned source, capture time, diff, complete captured text on demand, scoped connected-record preview, version history, legal hold and review actions in the inspector. A newer pending capture must not replace a previously approved retrieval version.
5. Approval/rejection remains restricted to a DPO, requires a reason and applies only to the newest pending capture with verified stored bytes. A source check never changes an operational rule or deadline.

## Implementation and guardrails

- Keep the current tenant-scoped APIs and capabilities. Build the workspace in the existing Sentinel page and external JavaScript; no legal-content inference or provider call is added.
- Render source and captured text with DOM text nodes. Validate external links as HTTPS. Prevent stale asynchronous detail responses from replacing a newly selected source. Preserve selection across refreshes within the page.
- Desktop: responsive two-column list and sticky inspector. Mobile: accessible closeable sheet with focus return and Escape support. Respect reduced motion, provide visible status and touch targets, and avoid horizontal overflow.
- Keep the source check frequency server-enforced. Client timing is an aid, not an authority. Show 429 errors without disabling unrelated sources.

## Acceptance

- A check launched from the first source displays its result in the adjacent inspector, with no vertical search; unchanged, pending, failure and rate-limit states are distinct.
- Selecting another source during a slow check does not swap its inspector contents when the earlier request finishes.
- DPO proof and review actions remain available; other readers cannot gain write actions through the new layout.
- Desktop, 390 px mobile, keyboard navigation and existing Sentinel living-law tests pass. Captured text remains inert and outside HTML string interpolation.

## Local build status

The two-pane workspace, compact source list, status/search filters, immediate check outcome, versioned proof, DPO actions and mobile inspector sheet are implemented on the `codex/sentinel-card-polish-2026-10-25` worktree. The source-check and capture APIs were reused without changing their approval or tenant boundaries. Local isolated checks: 11 living-law backend tests and six targeted browser tests passed. The browser cases cover pending, unchanged and failed/rate-limited checks, DPO review, delayed capture responses, and phone close/focus behavior. The broader test suite and a live deployment are outside this local build check.
