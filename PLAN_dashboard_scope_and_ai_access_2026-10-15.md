# Dashboard scope and AI Governance access

## Goal

Make the ERM and ORM dashboard facts and AI summaries obey the viewer's business-unit scope. Then reconcile AI Governance access with the specialist-only journey without breaking historical requests or assigned training.

## Findings

- The ERM and ORM dashboard data services count and return whole-organization rows. Their routes also pass those figures to AI board and chat prompts.
- ORM exposes recent event titles and departments from the same unscoped source.
- ERM uses a scoped posture filter only when a client supplies a business-unit id; a caller can ask for another unit. Other headline figures and the event feed are unscoped.
- `ai_use.view` and `ai_use.submit` still cover most staff. Narrowing either capability affects historical requests, My Work, routes, and the learner links, so it is a separate access migration.

## Work log

- 2026-10-15: Inspected the current branch, source queries and route consumers. Existing worktree edits were left intact. Starting with source-backed dashboard scoping and keeping the role change separate.
- 2026-10-15: Scoped ORM dashboard counts, sums, type chart, top impact, recent event titles, SLA count and department choices with the shared event rule. Applied the same rule to the ORM AI board and chat context. BCM and Sentinel banners now follow the viewer's corresponding record access. KRI alerts are explicitly labelled organization-wide, matching the Indicators page and its records without a unit owner.
- 2026-10-15: Scoped ERM risk counters, trend, watchlist, actions, posture, heat map, register, appetite comparisons and executive dashboard using the shared ERM and platform risk rules. The ERM AI board and chat now receive scoped figures. Linked obligations follow the linked risk; unlinked obligations and assessments remain organization-wide because they have no unit owner. The cross-module event feed is labelled unavailable for unit-scoped users because its payload has no trustworthy unit owner.
- 2026-10-15: Read the changed SQL and route callers, and ran a whitespace-only diff check. No automated or manual behavior check was run.
- 2026-10-15: Scoped the direct ERM trend and ageing report sources. Linked obligations now follow the linked risk's unit in the ERM list, record lookups, writes, search and Related Items; unlinked obligations remain organization-wide. Linked-risk input is validated before a write.
- 2026-10-15: Split historical author access from new specialist intake. `ai_use.submit` continues to permit an existing author to read their own requests. New manual requests, edits, submission, duplicate search and people lookup require `ai_use.intake_create`. The full AI Governance read capability is now limited to governance and privacy reviewers. Prior authors see a read-only request and a My Work link when a request was returned. The generated route and role inventory was refreshed.
- 2026-10-15: Removed the remaining staff dashboard branch for a specialist viewer. ERM pillar and objective writes now take the viewer's unit scope and reject assignments outside it. New risk creation by a unit risk owner inherits their unit; reassignment through the ordinary risk form is rejected.
- 2026-10-15: Added a distinct ERM risk-acceptance proposal and decision record, immutable source snapshot and history events, independent approver capability, expiry and change-derived state, risk drawer actions, a My Work projection, and a deletion guard for risks with formal acceptance history. This is a local build with no behavior checks yet.
- 2026-10-15: Kept legacy `accepted` risks in exposure and appetite queries, rather than silently treating an unverified legacy label as a current approval. The Command Centre fallback now counts mitigated risks, not a chosen acceptance strategy, as mitigated.
- 2026-10-15: A GRID attachment now checks the viewer's Vault scope, starts as unreviewed in GRID, and uses a Vault virtual path. GRID single download and ZIP download resolve that path through current Vault scope. Existing GRID and BCM mirrored rows still need an inventory and crosswalk before file storage can converge.
- 2026-10-15: GRID's mirror now records organization, audit business unit, hash and Vault family version on a separate Vault copy. An early-error cleanup bug was repaired. This still leaves a legacy GRID-owned file copy and is a transition, not final single-file storage.
- 2026-10-15: BCM compliance proof now attaches an existing, scoped Vault artifact rather than accepting a client-supplied file path and creating a second evidence row. The compliance control keeps a separate review and link history. The screen has search, attach, view and unlink actions. Legacy path-based entries show metadata with a migration label and no download path. A control with evidence history cannot be hard deleted.
- 2026-10-15: Risk acceptance now refuses duplicate current approvals and stale review or expiry dates at decision time. A syntax-only parse and whitespace check found no errors; no behavior tests were run.
- 2026-10-15: BCM incident Vault link list, attach and unlink now check incident scope and artifact organization and unit scope. Link attribution uses the actor's user ID. This closes a separate ID-based link bypass found while reviewing BCM proof.
- 2026-10-15: AI Governance form imports can save an organization-scoped mapping from a reviewed preview, apply it to the next export, and archive it. Each new file still runs through mapping validation, preview, row decisions and explicit confirmation. Earlier batches retain their own mapping snapshot. The generated route inventory was refreshed.
- 2026-10-15: Mounted Related Items in the ERM risk drawer. The component now offers Link item from an empty state, escapes record text, binds picker actions without inserting record values into JavaScript, and opens the permitted target route. Other module screens and browser behavior remain open.

## Remaining for this stage

- Reconcile the remaining ERM and ORM readers and writes, including risk scenarios, organization-wide KRIs, assessments, and event feeds. Their unowned records need an explicit ownership contract before a unit view can present a complete picture.
- Review the existing AI Governance cases written for employee intake and inventory access. They describe the former product behavior and need migration before the changed access model can be released. Confirm that old returned requests should be read-only for former staff authors.
- Complete the later programme slices: portfolio charts, final GRID file cutover and legacy crosswalk, BCM legacy path crosswalk, module homes, source versions in reports, and the shared-sender daily email cap. Jurisdiction-specific clocks need approved legal content.
- Before the BCM proof change can release, inventory legacy `bcm_compliance_evidence` rows and old Vault mirrors by organization, hash and link. Migrate only matched files with an audit trail; do not infer a path from a title. Check the additive `deleted_at` migration on both database engines.
- The owner approved separate risk proposer and approver roles and a single Vault artifact for GRID and BCM files. The first risk-acceptance slice uses those roles. A release still needs review of its schema migration, UI and API behavior, historical accepted labels, source change concurrency and report manifests.
- Exercise focused cross-unit and role cases on both database engines, followed by the larger stage check, before treating this local patch as verified or release-ready. No test was run for this change.

## Release state

Local work only. No tests, commit, push, merge, or deployment have been requested for this slice.
