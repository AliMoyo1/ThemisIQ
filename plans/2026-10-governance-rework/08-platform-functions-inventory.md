# 08. Platform functions inventory

**Status:** Built from source on the branch `claude/plan-04-platform-truth`, 2026-10-14. It answers plan 04 section 8: for each
platform function, who reads and writes what, under which gate, what was found, and what is still unverified. It is a
journey review, not a security audit of every endpoint.

**Method.** Routes and gates come from `docs/generated/capability_inventory.json` (regenerated 2026-10-14: 1080 routes). The
generator now sees a capability through a `require_auth` wrapper: seven routes that it used to list as "sign-in only" are
capability gated (`manage_frameworks`). Tables come from the SQL in each route file. "Verified" means the route source was
read. Anything else is marked "not verified". A "sign-in" gate is the weakest declared gate; most such routes check ownership
or scope inside the handler through a helper, which the inventory generator cannot see.

## Summary

| Function | Routes | Gate as declared | Reads | Writes | State |
| --- | --- | --- | --- | --- | --- |
| Compliance projects and framework catalogue | 15 | 5 capability (`manage_frameworks`), 10 sign-in | `frameworks`, `controls` | `frameworks`, `controls` | Verified gates; project to report path not walked |
| Readiness | 6 | 6 capability | readiness findings | findings | Not verified beyond gates |
| Workflows and SLA definitions | 28 | 28 sign-in | `workflow_*`, `sla_*`, `comm_templates` | same, `notifications` | Organization scope verified; authoring needs no capability (finding) |
| Task board | 9 | 9 sign-in | `task_board` | `task_board`, `notifications` | Assignee and owner checks verified in the handlers |
| Calendar and reminders | 9 | 8 sign-in, 1 capability | `calendar_events`, `email_reminders` | same | Owner checks in the handlers; delivery status is plan 06 |
| Saved views and analytics | 8 | 8 sign-in | `saved_views`, `analytics_snapshots` | same | Saved views keep the person's own filters; snapshot capture is capability checked inside |
| Evidence campaigns | 12 | 5 capability, 7 sign-in | campaign and request tables | same | Reviewer and assignee checks inside; not walked end to end |
| Bulk import and export | 2 | 2 sign-in, capability checked inside | `controls`, `risk_register`, `evidence_items`, `sentinel_ropa` | same | One defect fixed (below) |
| User and role administration | 13 | 13 capability | `users`, `user_roles`, `business_units` | same | Gates verified |
| API keys and webhooks | 11 | 11 capability | `api_keys`, `webhooks`, `webhook_logs` | same | Gates verified; token and payload review not done |
| Audit log | 1 | capability (`platform.view_audit_log`) | `audit_log` | none | Read only |
| Trainer | 1 | sign-in | none | none | AI help assistant, public data class |
| Reports (new in plan 04) | 12 | 12 sign-in; scope read through the person's own access | `report_*`, source tables | `report_definitions`, `report_runs` | Built and tested in slice 4B |
| My Work, search, related items | 8 | sign-in; every read goes through the person's scope | module tables | `cross_module_links` | Built and tested in slices 4C and 4D |

## Per function

### Compliance projects and framework catalogue
- **Readers:** `/projects`, `/api/frameworks*`. **Writers:** activate and deactivate a framework, add controls, bulk add,
  AI generate (all `manage_frameworks`); the admin routes create, toggle and seed frameworks.
- **Found:** the generator listed the five mutation routes as sign-in only because `require_auth` wraps
  `require_capability`. They are capability gated. Fixed in the generator, not in the routes.
- **Open:** a previous report keeps its earlier edition only because a run is now frozen (4B). The framework edition and
  provenance are not stored on the project; "can a lead walk from a project to the live control, review, evidence and report"
  was not walked.

### Readiness
- **Readers and writers:** `/readiness*`, six routes, all capability gated (`platform.view_readiness`, `platform.manage_readiness`).
- **Open:** denominators and exclusions of the readiness counts are not declared in the metric registry. They should be
  registered (`cc.*` style) before readiness is shown on a board view.

### Workflows and SLA definitions
- **Readers and writers:** 28 routes. `_owned_definition` and `_owned_sla_instance` apply organization and ownership rules
  inside the handlers (verified for definition update, instance respond and resolve).
- **Found:** the ownership helpers (`_owned_definition`, `_owned_comm_template`, `_owned_sla_instance`) scope by the
  creator's **organization**, not by person. Creating or changing a workflow definition or a communication template needs
  only a sign-in, while deleting one and creating or changing an SLA definition need `platform.manage_users`. So an
  employee in the organization can rewrite the steps of an approval workflow but not delete it. The rule should be one
  capability for authoring (decision needed: which role may author workflows); it was not changed here because it changes
  who can use the Workflows page today.
- **Open:** the plan asks that a workflow step cannot bypass its source module's approval rule. That is a property of each
  source module's own approve action and was not tested here.

### Task board, calendar and reminders
- **Verified:** task create, update, delete and bulk update check the assignee and the owner. A task assigned to a person
  who may not see the record it is about is refused by `validate_task_assignee`.
- **Found (4C):** an unread notification about a task was listed beside the task as a second action. It is now one line.
- **Open:** one overdue review counted once across My Work, the calendar and the task board needs the canonical action
  identity of plan 06 section 3; My Work now dedupes by link and by `(module, type, id, action)`.

### Saved views and analytics
- **Verified:** a saved view stores filter parameters only, for its owner. `/api/analytics/snapshot` needs
  `platform.manage_users` inside the handler.
- **Open:** analytics snapshots read the whole schema (`SELECT COUNT(*) FROM controls` without a unit scope) because the
  capture is an administrator action. The stored trend therefore reflects the whole organization. It should say so on the page.

### Evidence campaigns
- **Gates:** create, close, cancel and review need a capability; submit and start-review are sign-in with an assignee check.
- **Open:** whether a requested artifact lands in the right claim and waits for the right reviewer was not walked.

### Bulk import and export
- **Verified:** import needs `platform.manage_users`. Validation runs before any write and a failure rolls the whole batch
  back (single transaction). Evidence rows carry the importer's organization; ROPA rows carry the importer's unit.
- **Found and fixed:** imported **risks** had no business unit, so every imported risk was organization wide and visible to
  every unit. They now take the importer's unit, as a risk created by hand does (`routes_platform.api_bulk_import`).
- **Open:** import of `controls` writes `aria_controls` without a unit. Export applies the caller's scope (not re-verified).

### User and role administration, API keys and webhooks, audit log
- **Gates:** all capability gated. **Not verified:** effective-capability preview before assignment, outbound payload
  signing and bounds, replay identification (plan 04 section 8 rows). Listed for the security review of plan 05.

### Trainer
- **Verified:** `POST /api/trainer/ask`, signed-in users, feature `launcher.api_trainer_ask` (public data class). It sends
  the question only. **Open:** inventory its callers and the data before moving AI literacy elsewhere (plan 01).

## Candidates for deprecation or repair

| Item | Why | Decision needed from |
| --- | --- | --- |
| `bcm.chat`, `erm.chat`, `orm.chat` canned replies | When the assistant is off they answer with a placeholder sentence that is saved in the chat history | Product owner: keep as labelled, or refuse |
| Board narratives of BCM, ERM and ORM | When the assistant is off they return a labelled placeholder that reads like a report section | Product owner |
| Auto-mapping of controls with AI | Writes mappings without a review step (`core.auto_map_controls`) | Assurance owner |
| Regulatory drift check | Writes a status and a summary on a regulatory update without a review step | Governance owner |
| Checklist import risk rating | Writes a risk level onto each new audit item, and Medium for all when the assistant fails | GRID owner |
| Workflow and template authoring open to every signed-in user of the organization | See above | Product owner: which role authors workflows |
| ERM and ORM dashboard statistics | `get_dashboard_stats` has no unit scope, so a unit manager's board narrative is written from whole organization figures (known, pending decision, see the ERM export unit scope note) | Risk governance owner |

## What this slice changed in the platform functions

1. Capability inventory: sees a capability through a `require_auth` wrapper. 1080 routes.
2. Bulk import of risks: takes the importer's business unit.
3. AI routes: see plan 04 section 6 below and `core/ai_declarations.py`.

## AI use cases (section 6)

`core/ai_declarations.py` declares, for each of the 54 places the platform calls a model: the task, what it reads, what it
leaves out, who starts it, what becomes of the answer, whether a person reviews it, and what happens when the assistant is
not available. The AI Governance platform features page shows it beside the oversight notes.

Defects found while writing it, and fixed:

- **A plan review that nobody made.** `POST /bcm/api/plans/{id}/reviews` returned a fixed score of 72 with canned strengths
  when the assistant was off or its answer was unreadable, and then failed to save it anyway (a list was bound to a text
  column), so the Run AI review button was broken in both modes. It now saves the review with its score and lists, names the
  provider that answered, checks the plan's business unit, and does not run when the assistant is off.
- **A risk score written over the owner's.** `POST /erm/api/ai/score-risk/{id}` wrote likelihood and impact onto the risk for
  anyone holding `erm.ai.use` (a compliance manager holds it, and does not hold `erm.risk.manage`), without a unit check, and
  wrote a canned 3 by 3 when the assistant was off. It now suggests a score, the page asks the person to confirm it, and the
  update goes through the ordinary risk update with its own capability and scope.
- **A fabricated risk.** `identify_risks_from_responses` returned "Risk identified from assessment" at 3 by 3 when the
  assistant was off. Now unavailable.
- **An event analysis nobody made.** `POST /orm/api/ai/analyze/{id}` wrote a canned root cause and actions into the event,
  without a unit check. It now fills only empty fields, only with a real answer, and only inside the person's unit.
- **A prediction that made a risk.** A critical predictive alert created an enterprise risk (likelihood 4, impact 4, visible
  to the board) with no person involved. It now goes to the ERM emerging-risk inbox for a person to review (plan 04
  acceptance: nothing external or predictive silently creates a risk).
- **Policy refusals were swallowed.** The module services caught every exception, so an organization that had switched a
  feature off by policy still received canned content. A refusal now reaches the person with its own sentence (403), and
  "the assistant is not available" is a 503 with the reason.
- **The deep link in search results lost its colon.** The topbar search removed every character outside a short allowed set,
  so `?open=control:12` became `?open=control12`. It now keeps any path on this site and refuses everything else.

Still declared as canned content when the assistant is off (labelled, not analysis): the three chats and the three board
narratives. Still writing without review: auto-mapping, the drift check and checklist import scoring. These are listed above
for decision rather than changed, because each changes a person's workflow.
