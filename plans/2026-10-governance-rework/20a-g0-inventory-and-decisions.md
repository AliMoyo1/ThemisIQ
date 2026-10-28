# 20a. Group oversight G0: inventory and decisions

**Status:** G0 of [20 Group oversight across tenants](20-group-oversight-across-tenants.md), 2026-10-28. Read only: no behavior changed and no data touched. Part A (the code inventory) is complete. Part B (the live server inventory) is a ready script that the owner runs on the server; its results are not in this document yet. G0 is therefore **not signed off**.

## 1. How this was done

- **Part A, from the code.** Every `CREATE TABLE` in `database.py` (246 tables, 3,211 columns) plus the migration column list was scanned for column names that suggest personal data or free text, then each table was read by hand where it mattered. Names are only hints: a column called `name` is usually a record name, not a person. The classification below is a judgement from the schema, not from real rows.
- **Part B, from the server.** `oneforall/scripts/inventory_group_oversight.py` reads every tenant and reports counts and organization or business-unit names only. It never prints a person's name, email, title, file name or content. It runs in a read only transaction (verified on a throwaway PostgreSQL 18: a write is refused with `ReadOnlySqlTransaction`) and has tests that check its output contains no personal value.

## 2. Personal data classes

| Class | Meaning | Where it sits (tables and columns) | Crosses to the group? |
| --- | --- | --- | --- |
| **A. Data subjects** (people outside the workforce whose data the organization handles, plus case details) | The most sensitive class | `sentinel_dsr` (requester_name, requester_email, description, response_notes); `sentinel_consent` (subject_id, subject_name, subject_email, notes); `grid_remote_participants` (external_name, external_email); `grid_share_links` (auditor_email); `ai_use_intake_requests` and `ai_external_responses` (requester); `demo_requests` (name, email, ip_address; marketing leads in the public schema) | **Never** above level 1, except as a count and a deadline. Never in any snapshot. |
| **B. Workforce and business contacts** | Staff and supplier contact details | `users` (full_name, email, username); `people_directory` (full_name, email, phone); `sentinel_training` (staff_name, staff_email); `sentinel_controllers` (contact, controller and DPO names, emails, phones, address); `sentinel_vendors`, `bcm_vendors`, `grid_vendors`, `canonical_vendors` (contact_name, contact_email, contact_phone); `bcm_contact_nodes` (name, email, phone, mobile); `bcm_training_attestations` (user_name, user_email, signature, ip); `grid_digest_subscriptions` (email, name); `email_reminders` (recipient_email); `ai_risk_prediction_notes` and `report_run_notes` (author_name); `bcm_plan_reviews` (reviewer_name) | Owner and reviewer **display names and work emails** may appear in level 2 registers, with a visible notice. Personal mobile numbers, signatures, supplier contacts and training attestations do not. |
| **C. Technical identifiers** | Who did what, from where | `audit_log` (username, ip_address); `sessions` (ip_address); `aria_ask_log` (username) | Never in a snapshot. Group access is logged in both tenants by its own mechanism. |
| **D. Free text** | Anything a person typed, including names and case facts | See section 4 | Excluded from every group view. Only released item by item through the request pipeline. |
| **E. Secrets** | Credentials and tokens | `users.password_hash`; `sessions.token`; `grid_share_links.token`; `api_keys.key_hash`; `webhooks.secret`; `aria_policy_publication_jobs.lease_token`; `erm_emerging_scan_jobs.lease_token` | **Never**, by a hard rule in the code, not by configuration. |
| **F. Not personal** | Names of processes, frameworks, controls, risks, units, organizations | e.g. `business_units.name`, `aria_frameworks.name`, `erm_kris.name`, `organizations.name` | Allowed where the level allows the table. |

Findings that matter for the design:

1. **Level 1 can be built from numbers that already exist and contain no personal data.** The platform's metric registry (`core/metric_registry.py`) defines 30 metrics, all counts, shares or levels (list in section 3). Each is already defined once, with a denominator and a scope, so a snapshot can publish exactly those and nothing else.
2. **`demo_requests` is in the public schema and holds prospects' names, emails and IP addresses.** It belongs to the platform operator, not to any tenant. No group path may read it.
3. **Free text sits beside the safe fields in the same rows** (for example a breach has `severity` and `status`, which are safe, next to `description`, `cause`, `impact`, `containment` and `notes`, which are not). Level 2 must therefore be an allowlist of named columns per table, not "everything except".
4. **Sentinel carries the most class A data.** Because data subject requests and consent records hold names and emails, level 2 shows them only as a count and the nearest deadline.

## 3. Level 1 allowlist: the 30 registered metrics

All counts, shares or levels. No row, name or free text.

| Module | Metrics |
| --- | --- |
| ARIA | controls implemented; active frameworks |
| Platform | overdue actions; reviews due within 30 days; evidence files; evidence expiring within 30 days; service clocks resolved on time; active workflows; open risks by level; share of records in their good state; claims with a live link; claims with current proof; claims with accepted proof |
| ERM | critical and high risks; appetite breaches |
| ORM | open operational events |
| BCM | active incidents; analyses with a continuity plan; continuity plans; exercises completed; open continuity risks; continuity risks by level |
| GRID | audit controls not yet compliant |
| Sentinel | open breaches; processing records; business processes with a processing record; impact assessments in progress; data subject requests waiting |

(`cc.*` Command Centre keys and the module keys overlap in a few places, for example open breaches; the snapshot uses one key per meaning.) The overall compliance score, per module and per framework, is computed in the source tenant from the same rows and published with its method version.

## 4. Level 2: proposed named-field allowlist and the exclusions

Proposed, for the group DPO's issue register in the first release (other modules follow only after the privacy review in plan 20 section 8). Safe fields only; every other column is excluded by default.

| Table | Allowed fields | Excluded |
| --- | --- | --- |
| `sentinel_breaches` | ref_number, breach_type, severity, status, discovery_date, reported_date, affected_count, notification_required, authority_notified, authority_notify_date, regulation, business unit | title, description, cause, impact, containment, root_cause, corrective_actions, lessons_learned, remediation, ai_analysis, ai_assessment, notes, authority_ref, data_types |
| `sentinel_dsr` | ref_number, request_type, regulation, received_date, deadline_date, status, business unit | requester_name, requester_email, description, response_notes, ai_draft |
| `sentinel_consent` | none (count and expiring count only) | everything |
| `sentinel_dpias` | reference, title, status, risk rating, due date, owner display name, business unit | description, notes, consult_notes, details |
| `sentinel_ropa` | reference, processing_name, status, risk level, review date, owner display name, legal basis, business unit | notes, ai_risk_notes, details, data_subjects, systems |

Free text columns that must never cross (counted by the live inventory so their volume is known): `sentinel_dsr.description`, `response_notes` and `ai_draft`; the free text columns of `sentinel_breaches` (description, cause, impact, containment, root_cause, corrective_actions, lessons_learned, remediation, ai_analysis, ai_assessment, notes); `sentinel_dpias.description`, `notes` and `consult_notes`; `sentinel_ropa.notes`; `sentinel_consent.notes`; `bcm_incidents.description` and `impact`; `bcm_plans.content` and `description`; the five free text columns of `grid_non_conformances`; `erm_enterprise_risks.description` and `risk_context`; the four of `orm_events`; `aria_documents.body`; `evidence_items.description`; `task_board.description`; `notifications.message`.

## 5. Evidence Vault facts that affect plans 19 and 20

- **Family model, confirmed in the code.** An item is one `evidence_items` row; versions are further `evidence_items` rows linked by `parent_id` and `version`. The family is the root item. There is no `evidence_versions` table for the Vault and no `artifact_family_id`.
- **Null means the whole organization.** `evidence_scope_sql` returns rows whose `business_unit_id` is null to every user of the organization. A document filed without a unit is therefore visible to every business unit of that tenant. The live inventory counts these and counts those whose title or file name mentions a unit or organization name, as narrowing candidates (plan 19 exposure finding). Counts only; titles are never printed.
- **Within one tenant this is an inside-the-tenant exposure.** The group question is separate: across tenants no null-unit row is ever visible to another tenant.

## 6. Tenants, licenses and the group module (from the code)

- An organization is a row in the shared `organizations` table with a `slug` and a `plan`. PostgreSQL gives each organization a schema `tenant_<slug>` plus row level security; the default organization lives in the public schema. A **license** row (`licenses`) holds `module_keys` (default `aria,bcm,erm,grid,orm,sentinel`), `seats`, `valid_from` and `valid_until`. Module access is the role's `module.<key>.access` capability **and** the license key (`user_modules` in `core/rbac.py`; super administrators skip the license).
- **There is no group module key and no parent link today.** Adding group oversight needs (a) a `group` module key in the license list, added to a parent's license automatically and to a subsidiary's as "receive group view", and (b) the relationship table of plan 20. `user_modules` only looks at the six module keys, so group access must be its own capability set and check, not another entry in that loop.
- **A gap to design for:** the Chief GRC Officer role has no `module.orm.access` (it has aria, bcm, erm, grid and sentinel), and the DPO has no bcm or orm access. A group view of ORM or BCM figures must therefore not be gated by the holder's `module.*` capability in the group tenant; it is gated by the new group capability and by what the subsidiary's snapshot contains.
- Capability counts for the roles chosen in plan 20: Chief GRC Officer 34, Compliance Manager 60, DPO 37, Audit Lead 33.

## 7. Part B: running the live inventory

Not done yet. It needs the code on the server (after this branch is merged and pulled) and root access, so it is the owner's step. On the server, from the project folder, one command:

`cd /project/oneforall`

then

`.venv/bin/python3 scripts/inventory_group_oversight.py`

It prints, for the shared registry: each organization, its status and plan, each license (modules, seats, dates) and active users per organization id; then for each schema: the business-unit tree (names and depth), row counts of the level 1 tables, how many rows hold a value in each personal data column and each free text column, how many Vault items have no unit, how many families and versions exist, and how many no-unit items mention an organization or unit name. The output contains no personal value and can be pasted back here. Please paste it, so this document can be completed with the real numbers.

What the live run settles:

1. Whether Econet, EcoCash and OmniContact already exist as three organizations (separate tenants and licenses) or still as business units inside one.
2. How large the "Ownership unconfirmed" queue would be in each tenant, and how many no-unit Vault items look subsidiary specific.
3. How much class A, B and free text data actually exists per tenant, so the privacy review is sized on facts.

## 8. G0 sign-off checklist

| Item | State |
| --- | --- |
| Personal data classes from the schema | Done (section 2) |
| Level 1 allowlist | Done (section 3) |
| Level 2 allowlist proposal for the issue register | Proposed (section 4), needs the privacy reviewer |
| Role mapping against the existing roles and capabilities | Done in plan 20; section 6 adds the module gap |
| Live inventory (tenants, licenses, counts) | **Script ready and tested; needs the owner to run it** |
| Snapshot cadence | Daily proposed; owner to confirm |
| Named privacy reviewer at Econet | **Open** |
| Whether a group case may show a subsidiary another subsidiary's released item | Recommendation: no; owner to confirm |

## 9. Log

- 2026-10-28: Part A written from the schema scan. Script and tests added (4 tests; the script was also run against a throwaway PostgreSQL 18 with two tenants and refused a write). The live run is waiting for the owner.
