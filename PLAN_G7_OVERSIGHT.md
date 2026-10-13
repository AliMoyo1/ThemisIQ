# G7 oversight foundation

Starting point: commit `4384c79`. Keep EU legal content disabled pending recorded approval.

1. Add two content-neutral tracks per AI use: design controls and day-to-day operation. Each track names a responsible person and records how people observe, intervene, stop and escalate. Save creates a new immutable content version; a second reviewer may mark that version reviewed.
2. Bind every version to its AI profile version. A later profile edit or arrangement revision requires another review. Keep historical versions visible to scoped viewers.
3. Connect the arrangements to the AI Governance workspace, Monitoring, Decisions and My Work. Decisions show a live status link without changing the signed brief or its digest. Existing assessments, incidents and evidence remain in their source modules.
4. Keep EU AI Act rule text, effective dates, classifications and obligations disabled until a legal/content owner records the approved rule version.

## Acceptance notes

- A hidden AI use gives the same response as a missing one; all writes check scope and capability in the service.
- A stale browser cannot overwrite a newer version. Reviewers cannot approve their own draft.
- A reviewed version retains its content and reviewer history. A subsequent edit creates a new draft.
- The workspace explains that recording an arrangement is not a legal conformity decision.
- The release gate for any EU rule pack remains closed pending owner approval.

## Change log

- 2026-10-12: Started after the G6 milestone was committed and pushed.
- 2026-10-12: Scoped the first slice to content-neutral oversight records and an explicit legal-content gate.
- 2026-10-12: Added versioned design and operation records, optimistic revision checks, separate reviewers, profile staleness, permission-scoped person search and a workspace tab. Review remains pending; no tests were run for this slice.
- 2026-10-13: Connected live status to Monitoring and Decisions, and actionable current versions to scoped My Work. Focused service, HTTP, browser and disposable PostgreSQL checks passed. The full suite remains deferred until the larger stage. EU rule content remains disabled pending recorded legal approval.
