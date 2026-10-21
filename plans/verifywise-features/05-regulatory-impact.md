# 05 · Regulatory watchlist and impact review

**Inspiration:** VerifyWise [Regulations Tracker](https://verifywise.ai/user-guide/regulations-tracker), including jurisdiction watchlists, a dated changelog, effective-date deadlines, and impact review. **Priority:** after relationship service. **Size:** M.

## Existing ThemisIQ anchor

Governance has a Regulatory Inbox and deterministic drift work ([PLAN-13](../PLAN-13-drift-detection-regulatory-inbox.md)); ERM has an External Context inbox. Sentinel handles jurisdiction-specific privacy work. Extend these owners and their review paths rather than adding a second regulatory feed or letting external content directly rewrite controls.

## User journey

An administrator chooses relevant jurisdictions, regulations, topics, and business units. A new sourced change appears once in a **Review impact** queue with publication date, effective date, source URL, change summary, confidence, and review owner. The reviewer sees candidate affected frameworks, controls, applications, AI uses, data processing activities, and risks. They confirm or dismiss each link, assign work, and retain a dated decision trail. The Command Centre shows only owned, due, or high-impact items.

## Build slices

- **A (watchlist and source contract):** use approved primary or authoritative sources; capture jurisdiction, issuer, source version, retrieval time, effective date, amendment state, and provenance. Deduplicate updates and distinguish proposal, adopted rule, guidance, and effective obligation. Do not infer legal applicability from a jurisdiction label alone.
- **B (impact queue):** extend Regulatory Inbox review states and ERM External Context linkage. Deterministic matches propose affected framework/control/application records; AI may summarize the change and reasons with source citations. A reviewer accepts mappings and named actions before My Work receives tasks. Notifications link to the reviewed change and avoid repeats.
- **C (deadlines and history):** calendar of confirmed effective dates, review reminders, superseded versions, and a filterable “what changed since my last review” view. For Sentinel, route applicable privacy changes to the appropriate jurisdiction owner and record; do not hard-code one global breach deadline.

## Acceptance gates

- Every displayed change has a resolvable source, issuer, date, and review status. An unavailable source is marked stale, not silently treated as current.
- No external page text can issue workflow instructions or alter controls without a permitted human decision. Incorrect candidate matches can be dismissed with a reason and will not recur as new tasks without a material source change.
- A reviewer can trace one accepted change to affected records, assigned actions, and the exact source version; wrong-org/BU records never appear in counts or notifications.

**Out of scope for first slice:** legal advice, automatic obligation adoption, and indiscriminate web crawling across every jurisdiction.
