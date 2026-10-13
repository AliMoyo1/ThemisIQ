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

## Pilot runbook

The live pilot needs an environment, organization, two or three existing AI uses, and named people for the use owner, oversight author or reviewer, and an independent decider. The owner will provide these details. Use ordinary business records already approved for that environment; do not copy sensitive procedures into the run log.

1. For each use, confirm the owner can open its AI profile and that a person from another business unit cannot see the use or its oversight route.
2. Have the author record both design and operation arrangements, including a responsible person, observation method, intervention, stop procedure, and escalation path. Confirm the person picker offers only eligible people who can open that use.
3. Have the independent decider review each complete draft. Confirm the author cannot review their own version and a stale browser revision cannot overwrite a newer one.
4. Confirm Monitoring, Decisions and My Work show the live status and open the correct use. Edit an AI profile, then confirm both tracks report that the profile changed and require a new reviewed version. The prior reviewed content must remain in history.
5. Record sanitized task completion, navigation difficulties, elapsed time and unexpected access or status behavior for each participant. Keep the audit event IDs and software revision with the pilot record. A failed access or stale-state check stops promotion until fixed and repeated.

This pilot validates usability and internal oversight workflow. It cannot approve EU rule content or establish legal conformity.

## Change log

- 2026-10-12: Started after the G6 milestone was committed and pushed.
- 2026-10-12: Scoped the first slice to content-neutral oversight records and an explicit legal-content gate.
- 2026-10-12: Added versioned design and operation records, optimistic revision checks, separate reviewers, profile staleness, permission-scoped person search and a workspace tab. Review remains pending; no tests were run for this slice.
- 2026-10-13: Connected live status to Monitoring and Decisions, and actionable current versions to scoped My Work. Focused service, HTTP, browser and disposable PostgreSQL checks passed. EU rule content remains disabled pending recorded legal approval.
- 2026-10-13: Opened draft PR #6 for code review. The full G7 acceptance lanes started, and the PostgreSQL test now covers a provisioned tenant's business unit scope. The pilot runbook is ready; live participants and environment are pending owner details.
- 2026-10-13: Full disposable PostgreSQL lane passed. The local full backend run had two ARIA policy failures outside G7; both passed on focused rerun. CI's Linux backend coverage run progressed to 80 percent without a reported test failure, then reached its 20 minute job limit. Increased that limit to 40 minutes for the same coverage gate. The full local browser lane is still running.
