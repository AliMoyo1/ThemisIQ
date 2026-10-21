# 10. Completion record (plan 05)

**2026-10-21 source correction:** Pull request 11 merged `claude/plan-04-platform-truth` into `master` at `790ce1cd`; pull request 14 merged the AI Governance follow-up at `3bee4106`. Statements below saying that branch is unmerged, or that learner routes are kept, describe the 2026-10-15 snapshot. The follow-up removed AI literacy application surfaces while retaining historical rows, and labels bounded decision and monitoring counts as partial when needed. The specialist pilot, phase-owner sign-off, live tenant migration and production release still have no evidence in this record. Neither this note nor a code merge records operational acceptance.

**Status:** Written 2026-10-15 on the branch `claude/plan-04-platform-truth` and brought up to date the same day for follow-ups
11 to 13. It is the record that
[05](05-delivery-and-acceptance.md) section 12 asks for: for each slice, what was decided and built, how it was checked and
where, and what is still open. It does not repeat the build detail, which is in [07](07-implementation-ledger.md) under the
heading named in each row.

**How to read the status words.** Used exactly as 05 section 12 separates them. *Built*: on the branch `claude/plan-04-platform-truth` (commits `cbf9372` to the latest, pushed to GitHub), not merged to `master`. *Verified
locally*: the focused checks named passed on SQLite, on a disposable PostgreSQL 18 where the row says so, and in a browser
where the row says so. *Pilot live* and *generally released*: nothing here is either. No source owner has signed any phase
off, a pilot walkthrough with Ali Moyo and Vivian Tsongorera has not happened, and nothing from this branch is merged to `master` or deployed.

## 1. Decision register (05 section 1)

Each default below was applied because the plan recommends it and no owner had said otherwise. None is signed off. Product
copy was written not to describe an unresolved decision as implemented. The rows marked *confirmed* were confirmed by the
owner in chat on 2026-10-15 ("Go with your recommendations but explain them in the ledger"); the reasons are in the ledger
under "Decisions taken". A confirmed default is still not a phase sign-off.

| Decision | Default applied | Owner (per 05) | Affected schema and routes | Migration need | Open risk |
| --- | --- | --- | --- | --- | --- |
| AI Governance user group | Specialists are full users; external requesters stay outside the platform | Product owner, customer governance lead | `ai_use_intake_requests.requester` (a fact, not an account); `/ai-governance/*` | none | A customer with no specialist user cannot use the import |
| Initial request entry | Versioned Forms export, specialist preview and import; no direct Forms integration | Customer administrator, product owner | `ai_import_batches`, seven columns on `ai_use_intake_requests`; `/ai-governance/import`, `/ai-governance/api/import/*` | additive | Column headers were written from the tools' documented behaviour, not from a customer file |
| Future invitation form | Deferred: not built | Security, product owner | none | none | None until it is built |
| Literacy transition | Out of the specialist navigation; courses, versions, completions and routes kept | Product owner | no schema change | none | Consumers of the learner pages were inventoried in 1A, not asked |
| Evidence semantics | A live link, current proof and reviewer-accepted are three measures | Assurance owner | nine additive columns (ledger 2A and 2B); `/evidence/api/coverage*`; capability `evidence.link.review` | additive | Target-specific acceptance rules were not approved; self acceptance is refused with no switch for a one specialist tenant |
| Report audience and retention | A frozen scoped run for the person it was made for; recipient-bound packs already exist for external sharing | Information owner | `report_runs.snapshot_hash`, `previous_run_id`, `report_run_notes`; `/api/reports/*` | additive; old runs are labelled legacy | Retention, expiry and deletion of runs are not built |
| Jurisdiction rules | Not built. A fixed breach clock says it is indicative | Privacy and legal owner | `sentinel_breaches.notify_deadline` follows the recorded date and regulation | none | One breach still has one regulation and one clock |
| Risk acceptance | Not built | Risk governance owner | none | none | The delegated-authority matrix is an owner decision |
| Temporary Gmail sender | The path is built and safe; no mailbox was chosen or configured | Security, operations | `core/email.py`, `email_outbox`, `email_reminders` columns, `/api/admin/email-*` | additive | Seven owner questions are open in [09](09-email-inventory.md) |
| Team in My Work (*confirmed*) | The units a person heads, inside the head's own scope; heading never widens scope | Product owner | `business_units.head_user_id`; `GET /api/my-work/team` | none | A matrix organization is not described; a head outside the unit sees no team |
| Work counted against a person (*confirmed*) | Only assigned work; shared queues and notifications are not charged to anyone | Product owner | `my_work_service.get_team_work` | none | A shared item with nobody named is on nobody's line |
| Summaries, quiet hours and tenant override (*confirmed*) | Per person, opt in, platform wide, fixed UTC offset; a tenant cannot override | Product owner, security | `user_preferences` keys `email.*`; `/api/my-email-preferences` | none | A zone with daylight saving needs the offset changed twice a year |
| Named reviewer, decider and incident commander (*confirmed*) | Optional; nobody named stays in the app only; a commander is a user and the label stays | Product owner, module owners | three nullable columns; `/ai-governance/api/.../assign`, `/bcm/api/people` | additive | A named person who does nothing is not chased |
| Outbox retention, send limit, group task mail (*confirmed*) | 180 days for ended deliveries; 20 ordinary messages a minute across organizations; one message for a group of tasks | Security, operations, product owner | none new; `core/email_outbox.py` constants `RETENTION_DAYS`, `PER_MINUTE` | none | Retention and processor terms are still the owner's to confirm |
| BCM acknowledgement windows and alternate (*confirmed*) | 15, 30 and 60 minutes for critical, high and medium; the BCM manager who can open the incident is the first alternate; once | Incident owner, product owner | four nullable columns on `bcm_incidents`; `POST /bcm/api/incidents/{id}/acknowledge` | additive | One level only; a manager with no unit is not told about a unit's incident |
| Predictive trace and disputes (*confirmed*) | Frozen with the prediction; a dispute is a note | Risk governance owner | `ai_risk_prediction_notes`; `/api/predictive-risk/trace` | additive | Earlier predictions have no trace |

## 2. Baseline and contracts (Phase 0 outputs)

| Output named in 05 section 2 | Where it is | State |
| --- | --- | --- |
| Baseline matrix: built, proposed, deferred | The slice table and the Baseline table of the ledger | Built; the deployed state of any tenant is not known from the source |
| Route and schema inventory | `oneforall/docs/generated/capability_inventory.*` (1100 routes, `--check` passes) and the platform inventory [08](08-platform-functions-inventory.md) | Built from source |
| Source-of-truth contract and relationship vocabulary | The README map, `modules/governance/entity_scope.py` (`_KINDS`), the relationship service states recorded, suggested, disputed | Built |
| Metric definitions | `core/metric_registry.py` and the page `/metrics` | Built; readiness counts are not registered yet |
| Import field guide and sample mapping | Published by `/ai-governance/api/import/guide` and shown on the import page; a CSV template at `/ai-governance/api/import/template.csv` for the form administrator | Built; not checked against a customer export |
| Access matrix | The capability inventory and `core/rbac.py` | Built from source |
| Migration impact notes | Section 4 below | Built |
| Current-state screenshots | Not produced | Not done |
| Email inventory (E0) | [09](09-email-inventory.md) | Built from source; no server was read |

## 3. Phase gates against the evidence

The sentence is the plan's acceptance gate, shortened. "Verified locally" names the checks; anything that was not exercised
says so.

| Gate | Evidence | State |
| --- | --- | --- |
| P1: a failed source cannot render a sample value | `test_no_dashboard_template_carries_sample_data_or_a_fallback_object`, `test_2_no_dashboard_template_carries_sample_data`, `test_a_source_that_fails_is_unavailable_and_a_sum_that_lost_one_is_partial` | Verified locally |
| P1: a report button proves a persisted run and opens its output; a later change does not alter a saved run | `test_a_saved_run_shows_the_figures_it_was_generated_with`, `test_3_no_report_button_ends_in_a_timer_and_every_type_it_asks_for_is_registered`, `tests/ui/test_reports_and_search_ui.py` | Verified locally |
| P1: counts, list rows and exports have matching scopes | `test_1_a_card_a_list_an_export_and_the_same_numbers_later`, `test_the_export_is_the_frozen_run_and_text_that_looks_like_a_formula_is_written_as_text` | Verified locally for the Command Centre and reports; module lists were not all reconciled |
| P1: release notes name a deliberate metric definition change | The legacy keys `compliance_pct`, `sla.pct`, `module_health[].pct` are `null` when nothing is recorded (ledger 4A) | No release note exists in this repository; the owner writes it |
| P2: the same current artifact can be found and linked from GRID, an AI use or a BCM plan in a bounded number of steps | AI use: yes. GRID and BCM keep their own file stores | **Not met** for GRID and BCM files (ledger Not done 2A and 2B) |
| P2: a replaced artifact keeps historical decisions and flags dependent claims; wrong unit searches leak nothing | `tests/test_evidence_proof.py`, `tests/test_evidence_inspector_find.py`, `tests/test_evidence_search_is_scoped.py` | Verified locally (SQLite, real PostgreSQL) |
| P3: the same response imported twice creates one case; a corrected one is a revision with a diff; an unknown owner stays unresolved | `tests/test_ai_governance_imports.py`, `_import_rules.py`, `_import_routes.py`; a PostgreSQL case in `tests/test_postgres_init.py` | Verified locally |
| P3: a specialist completes review and exports a response without a requester login; the approver cannot approve their own request | `tests/test_ai_governance_external_responses.py`, the decision separation tests of the G series | Verified locally |
| P3: with AI disabled the manual path is complete | `test_6_with_ai_off_a_specialist_can_find_review_and_report`, `tests/test_ai_governance_imports.py` | Verified locally |
| P4: a vendor change identifies affected cases and creates one review per owning module without changing signed decisions | `tests/test_change_signals.py` | Verified locally (SQLite, real PostgreSQL) |
| P4: an audit finding appears as GRID work and an ERM signal, and closing one does not close the other | The event handlers exist (`finding_elevates_to_erm`); closing independence was not tested in this programme | **Not verified** |
| P4: a source module stays usable when the relationship service is unavailable and the view says it is partial | `tests/ui/test_governance_connected_ui.py`; a section that could not be read says so | Verified locally |
| P5: a saved board report is stable; a data-poor report states its missing inputs; each number traces to authorized records | `test_the_board_report_has_no_record_lists_and_states_what_it_cannot_say`, `test_5_a_figure_is_traced_to_its_rows_and_disputed_beside_it`; the predictive number: `tests/test_predictive_trace.py` (19), `tests/ui/test_predictive_trace_ui.py` (2), the PostgreSQL case | Verified locally. A prediction made before the trace was kept says it cannot be traced and shows its figures only |
| P5: external context cannot silently create a risk | `core/predictive_risk.py` now writes to the ERM emerging-risk inbox (ledger 4E) | Verified locally |
| P5: a policy answer cites the exact permitted version | Policy Q&A was not part of this build | **Not built** |
| E1: a console fallback, a missing address or a failed provider is not recorded as delivered | `tests/test_email_transport.py`, `test_email_producers.py` (reminders) | Verified locally |
| E2: a second delivery of an event does not duplicate mail; a transfer stops mail to the prior owner; a wrong-unit user receives nothing | `tests/test_email_outbox.py`, `test_email_producers.py` | Verified locally |
| E2: a received message has aligned sender authentication and a working HTTPS link | A real mailbox and sending domain are needed | **Not verified** |

## 4. Migration inventory (05 section 9)

Everything this programme added to the schema is additive, created idempotently with the platform tables for every tenant
schema at start (`_migrate_all_tenant_schemas`). No row of an existing table was rewritten, except by one backfill (below).

| Existing data | What was done | Reversal and audit constraint |
| --- | --- | --- |
| AI requests, profiles, decisions, evaluations, oversight | Kept. Seven nullable or defaulted columns and `ai_import_batches`, `ai_precedent_verdicts`, `ai_request_questions`, `ai_external_responses` added | Older code ignores them. A decided request is never edited by an import |
| AI literacy | Untouched; only the specialist navigation changed | No data removed |
| Vault items, versions, links | Nine additive columns; the owner of a file that had none is set to its uploader once per schema; a new version proposes links and never inherits a verdict | The bytes and the earlier link decisions are untouched |
| GRID and BCM files | Not converged | None needed |
| Reports | `snapshot_hash`, `previous_run_id`, `report_run_notes`. A run with no hash is a legacy run and is labelled so; it is never recomputed | A legacy run is never relabelled as frozen |
| Change signals | Two tables, one capability, no backfill | None |
| Email | `email_outbox`; three columns on `email_reminders`. Old secrets in `settings` are still read and can be cleared by an administrator | Clearing is explicit and confirmed |
| Follow-up 11 | Nullable columns `bcm_incidents.commander_user_id`, `ai_use_intake_requests.assigned_reviewer_id`, `ai_use_decisions.assigned_decider_id`; a table `ai_risk_prediction_notes`; the telemetry JSON of a new prediction gains a `trace` key | Older code ignores the columns and the key. A prediction made earlier has no trace and says so. Preferences are rows of the existing `user_preferences` table |

**Not done before a production migration** (05 section 9): a verified restorable backup, an inventory of tenant schemas and
non-empty legacy tables, a rehearsal on a representative copy, and a check of row security for the application role. These
are the owner's steps on the server. The PostgreSQL lane proves the additive DDL on a fresh and on an existing schema.

## 5. Security checks per slice (05 section 9)

"Reviewed" means the code was read for it and a test pins it. No independent security review of any slice has been done.

| Slice | Isolation at query, aggregate, search and export | Capability enforced in the API | Links grant no rights; AI gets the minimum | Audit and safe retry |
| --- | --- | --- | --- | --- |
| 1A to 1C | Every read through the viewer's unit scope; a hidden use answers 404 like a missing one | Review and decision capabilities; the response approver is not its drafter | The response carries no internal id or score; no model sets a state or a match | Compare-and-set on a version; the import is idempotent |
| 2A to 2C | A duplicate in an unreachable unit is refused without naming it; claims shown are only those the viewer may open | `evidence.link.review`; the attacher cannot review; only a current, unexpired version can be accepted | The finder sends the question and a vocabulary, no file content | Each verdict audited; compare-and-set |
| 3A to 3D | A signal is visible only when both ends are openable; no title is stored | `governance.change.review` or the owner; compare-and-set on open | A link or a similar name informs nobody until it is confirmed | One signal per change and day, enforced by a unique index |
| 4A to 4G | One scope helper reads cards, lists, exports and narratives; a module the viewer may not open is not announced | A run opens only for the person it was made for | AI declarations name what each feature reads and leaves out | A refusal on opening a run is audited; a changed run is refused |
| 6 (E1 and E2) | A recipient who may not open the record is suppressed; a platform operator is not staff | `platform.manage_users` for the sender, queue and secrets | A message carries a reference, a date and a link: no title, name or token | Admin actions audited; one delivery per action and threshold; the queue shows no recipient |
| 11 (follow-up) | The trace names only records the viewer may open and counts the rest; the team view reads each person's work through the viewer's own unit scope and does not name a title from a module the viewer may not open; a named reviewer or decider must hold the capability and be able to open the use | The trace and its disputes are for super administrators like the panel; assignment needs the review or decision capability and refuses the requester | A dispute is a note beside the number and edits nothing; a link is a link | A dispute is audited; an assignment is audited |

Not reviewed: payload signing and replay identification for webhooks, an effective-capability preview before a role is
assigned (listed in [08](08-platform-functions-inventory.md)), the upload path of the Forms import under hostile files beyond
the size and type limits, and retention of delivery metadata.

## 6. Verification strategy results (05 section 10)

| Scenario or case | Covered by | State |
| --- | --- | --- |
| Importer, specialist reviewer, independent decider | 1B and 1C tests; the decision separation tests | Verified locally |
| Module owner decides a change signal | `tests/test_change_signals.py` | Verified locally |
| Board reader | `test_the_board_report_*` | Verified locally |
| Wrong business unit employee | A "cannot see" assertion with a positive twin in every new test file | Verified locally |
| Platform operator | Excluded from the people a mail job addresses (`organization_people`) | Verified locally |
| External recipient | The audit share binds the emailed recipient (`test_share_link_requires_login_and_binds_emailed_recipient`); the response is a file for the specialist to send | Verified locally |
| Empty tenant and not measured | `test_nothing_to_measure_is_not_measured_and_never_a_good_looking_hundred` | Verified locally |
| 500 or more artifacts | The library is paginated; it was not run against a seeded 500 file tenant | **Not run** |
| Duplicate and corrected import | 1B | Verified locally |
| Expired proof | 2B | Verified locally |
| Unavailable source, revoked recipient | 4A, 4B | Verified locally |
| Stale cache | No cache was added | Not applicable |
| AI disabled | `test_6_with_ai_off_a_specialist_can_find_review_and_report` | Verified locally |
| Concurrent decision or version update | Compare-and-set tests in 1C, 2B, 3A | Verified locally |
| A specialist walkthrough on pilot data | | **Not done** |
| The full browser suite in one session | About 3.8 hours; focused files only (see the ledger stage tables) | **Not run as one session** |

## 7. Success criteria: how each can be measured, and that none has been

No baseline was taken, so no figure is claimed (05 section 11). What the build can now supply:

| Outcome | Data the product holds today | Baseline |
| --- | --- | --- |
| Triage effort | `ai_import_batches`, request `submitted_at`, `reviewed_at`; the specialist's active minutes are not recorded | Not taken |
| Review clarity | The outstanding items summary per use, from one function | Not taken |
| Evidence findability | The library and Find evidence; time and steps must be observed | Not taken |
| Proof quality | Linked, current and accepted counts per module from `/evidence/api/coverage` | Not taken |
| Response reliability | A frozen response with a hash and its source reference | Not taken |
| Reporting trust | The reconciliation tests; unexplained differences are failures | The tests pass; no pilot reconciliation |
| Cross-module work | `change_signals` creation and decision times | Not taken |
| AI usefulness | The AI usage log of `core/ai_policy.py` | Not taken |

## 8. Per slice completion record

For every slice the plan asks for ten things. Issue and design, and code and schema, are the ledger entry of the same name;
the other columns are here.

| Slice | Ledger entry | Checks and environment | Manual journey | Authorization review | Rollout cohort | Rollback | Unresolved |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1A, 1B, 1C | 1A, 1B, 1C | SQLite, browser, real PostgreSQL | Not done | Section 5 | None | Turn the routes off; data additive | Ledger: Not done 1A, 1B, 1C |
| 2A, 2B, 2C | 2A and 2B, 2C | SQLite, browser, real PostgreSQL | Not done | Section 5 | None | Older code ignores the columns | Ledger: Not done 2A and 2B, 2C |
| 3A to 3D | 3A to 3D | SQLite, browser, real PostgreSQL | Not done | Section 5 | None | Signals are additive; the hooks are decorators | Ledger: Not done 3 |
| 4A to 4G | 4A to 4G | SQLite, browser, see the stage tables | Not done | Section 5 | None | Old runs are kept; the registry is read only | Ledger: Not done 4 |
| 5 | This file | Documents only | Not applicable | Not applicable | None | Delete the file | None |
| 6 E0 to E2 | Plan 06 | SQLite, browser, see the stage tables | A real mailbox pilot not done | Section 5 | None | Set the provider to console: nothing is sent and the in-app path is unchanged | Ledger: Not done 6 |
| 13 | Follow-up 13 | SQLite, browser, real PostgreSQL, see the stage tables | Not done | Section 5 | None | Set `RETENTION_DAYS` high and `PER_MINUTE` high: nothing else depends on them | Ledger: Not done (follow-up 13) |
| 12 | Follow-up 12 | SQLite, browser, real PostgreSQL, see the stage tables | Not done | Section 5 | None | Set no window: the job finds nothing due; the columns are ignored by older code | Ledger: Not done (follow-up 12) |
| 11 (steps 1 to 6) | Follow-up 11 | SQLite, browser, real PostgreSQL, see the stage tables | Not done | Section 5 | None | Pause sending holds the queue; naming a person is optional and removable; the trace and the team view are read only | Ledger: Not done (4) and (6) |

## 9. Release order and responsibility

The order of 05 section 12 was kept: truth repairs (4A, 4B, E1) before anything depends on them, the Vault before the
module journeys, the journeys before reporting. Responsibility sits where 05 puts it: the product and governance lead for the
role model and acceptance, privacy and legal for the jurisdiction rules, module owners for the facts of their domains,
engineering for the shared contracts, security for external intake and file handling. **No owner has been asked to sign a
phase.** A phase is complete only when its source owner signs it off with the evidence above attached; until then every row
in this file reads *verified locally* at most.
