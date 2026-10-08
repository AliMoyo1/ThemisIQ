# 06. Scoped external questionnaire invitations

**Status:** Conditional discovery proposal, 2026-10-08. **Owner:** GRID for audit/vendor answers, with Evidence Vault owning uploaded proof. **Entry point:** a named external respondent invited to one frozen, bounded questionnaire. This is an original ThemisIQ capability proposed by the supplied attachment, distinct from CISO Assistant's authenticated [respondent assignments](https://github.com/intuitem/ciso-assistant-community/blob/main/product-docs/features/assignments.md) and read-only [public trust centers](https://github.com/intuitem/ciso-assistant-community/blob/main/product-docs/features/portals.md).

## Validate demand and ownership

Observe at least two vendor/auditor workflows and record who owns the request, what the external party must see, whether an existing limited account is acceptable, expected document sensitivity, retention period and reviewer workload. Compare an invitation with the signed-in [internal assignment](03-respondent-assignments.md), GRID remote sessions, Vault campaigns and the [auditor sharing](../verifywise-features/06-auditor-sharing-trust.md) plan. Choose one owning record and one review queue. If an authenticated limited account meets the job, use that path first.

## Proposed one-journey pilot

1. A permitted GRID owner selects one audit/vendor scope, a small question set, due date and named recipient. The invitation captures a frozen question and framework edition, permitted response fields, retention date, reviewer and explicit evidence limits. Preview the exact external view before issuing it.
2. Deliver a revocable, short-lived opaque invitation whose verifier is stored hashed. Bind it to a named recipient with a second verification factor if the questionnaire reveals sensitive information; never place source record IDs, organization secrets or document content in the URL. Limit attempts and reissue on compromise. Decide separately whether delegation is permitted.
3. The external page shows only its own questions, attachments and draft answers. It offers save/resume and accessible validation, but no platform navigation, search, other respondent names, internal audit scores, file browsing or cross-tenant lookup. Each read, write and download checks the same invitation scope and current state.
4. Uploads enter a quarantined intake with file type/size checks, malware handling, provenance, safe filenames and retention policy. Vault creates a canonical evidence item/version only after validation and authorized reviewer triage; a submitted file does not become accepted proof or an automatically shared document.
5. Submission locks the response version and places it in a GRID review queue. The reviewer can accept, return specific questions, or reject the submission with recorded reasons. Existing audit status and ERM risk state change only through their owning module's approved workflow. My Work receives one deduplicated review action; events publish identifiers and permitted metadata only after the source transaction commits.
6. Revocation, expiry and deletion have visible semantics. An expired or withdrawn link stops reads/downloads immediately; historic reviewer decisions retain an auditable source manifest according to the retention policy. Reissued invitations do not expose old draft data to a new recipient.

## Architecture and threat-model decisions before build

- Decide if outside users can be represented as scoped guest identities, or if an invitation capability is required. Do not create a blanket sessionless `/p/<token>` route with reusable upload rights as the default design.
- Resolve organization, BU, audit/vendor relationship and object access server-side on every action. Audit all admin issuance and external activity without logging token values, answer text or document contents.
- Specify CSRF/session behavior, single or multiple use, email verification, rate limits, replay/concurrency rules, content scanning, tenant quotas, incident response, support recovery and retention. An HMAC signature alone is insufficient for revocation and recipient binding.
- Keep public trust publication a separate read-only workflow. An invitation may expose private questions to one recipient; it must never make internal evidence public.

## Pilot acceptance conditions

- A respondent can answer only the exact frozen questions issued to them; direct IDs, search, filenames, exports and stale links reveal nothing else.
- A reviewer can return one answer without losing accepted answers, source version or prior comments. Revoked and expired invitations cannot read or upload, including via previously copied download links.
- Invalid, oversized or unscanned uploads never appear as accepted Vault evidence. A retry cannot produce duplicate evidence items or duplicate downstream actions.
- The owner can see invite status, recipient, expiry, submission and review outcome without confusing draft answers with approved audit findings.
- The pilot measures completion time, reviewer rework, support requests and security events before expanding to generic quick forms or a public portal.

**Sequencing:** after PLAN-37 scope and event gates, Vault intake behavior and the signed-in assignment pilot. This plan does not approve a schema, route, deadline or public launch.
