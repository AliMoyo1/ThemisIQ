# Email queue fairness and AI literacy navigation

## Scope

- Give each active organization a chance to send ordinary email during a worker pass while retaining the shared 20-message limit and the critical-message exception.
- Remove AI literacy from AI Governance navigation. Preserve existing course routes, completion history and My Work course links until a separate staff learning destination is ready.
- Correct progress records that still describe BCM escalation as unbuilt.

## Change log

- 2026-10-15: Read the current branch, mail worker, tenant iteration, sidebar, My Work course links and implementation records. The queue always starts with the first organization; the literacy link remains in the specialist sidebar and the main module rail.
- 2026-10-15: Added a first share of the ordinary-mail allowance for each organization, reuse of unused capacity, and a rotating start when the allowance is smaller than the tenant count. Critical messages remain outside the allowance.
- 2026-10-15: Removed AI literacy links from the AI Governance sidebar and removed literacy-only access from the module rail. Existing routes, APIs, course data and assigned-course links in My Work remain intact pending the separate staff learning destination.
- 2026-10-15: Corrected the stale BCM escalation status in the implementation ledger and email inventory. Historical test claims in those records are unchanged.
- 2026-10-15: Static review found that the existing 200-message daily limit is per tenant. A shared Gmail sender needs a provider-wide daily limit before a live mail pilot. This correction addresses fairness within one worker pass, not that separate release gate.
- 2026-10-15: AI Governance visibility is still broader than the specialist-only product direction because `ai_use.view` covers most internal roles. Changing that capability needs a separate access and historical-workflow review; this edit changes navigation only.
- Static diff review and whitespace check completed. No tests were added or run for this change. Release status remains open.
