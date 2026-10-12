# 06. The AI impact assessment moves into AI Governance

**Status:** Planned 2026-10-11 on the owner's instruction: "move AIIA to the AI governance module". This amends who owns the AI impact assessment (AIIA) in the [programme index](README.md), the [domain contract](01-domain-and-integrations.md), [feature journey 3](02-feature-journeys.md) and [slice G3](03-delivery-and-acceptance.md). Everything else in those documents stands. What was built and verified is recorded in the [execution ledger](05-execution-ledger.md) under slice G3b; nothing below is built until the ledger says so.

## 1. Decision

The AI impact assessment becomes an AI Governance record. A person assesses an AI use from the AI system's own place in the product: the assessment list, the form, the impact dimensions and the status live under `/ai-governance`, and the Privacy (Sentinel) module no longer has an AIIA screen of its own.

DPIA and RoPA stay in Sentinel: they are privacy-law instruments and an AIIA links to them. The AI management assessment (AIMS) stays in Operations risk. The programme rule "linked, never copied" is unchanged. Only the writer of the AIIA changes.

The move also removes two items the earlier plan carried: a deep link into the Sentinel single page application to "start an assessment from this system", and a separate reviewer queue for linking old assessments to systems (section 6 replaces it with a list filter).

## 2. What exists today (read from the code, 2026-10-11)

| Part | Where | Notes |
| --- | --- | --- |
| Tables | `sentinel_aiia`, `sentinel_aiia_impacts` (one row per dimension, cascade delete), `sentinel_aiia_dimensions` (seeded with eight) | `application_id`, `ropa_id`, `dpia_id`, `business_unit_id` are plain integers, no foreign keys. Reference numbers `AIIA-yyyymmdd-xxxxx` |
| API | `GET/POST /sentinel/api/aiias`, `GET/PUT/DELETE /sentinel/api/aiias/{id}`, `GET/PUT /sentinel/api/aiia-dimensions` | Read needs `module.sentinel.access`; write needs `sentinel.dpia.manage`; unit scope on read and, since G1a, on update and delete |
| Service | `modules/sentinel/data_service.py`: `create_aiia`, `update_aiia`, `get_aiia`, `delete_aiia`, `list_aiias`, `list_aiia_dimensions`, `save_aiia_dimensions` | Opens its own connection and commits; classification comes from ERM `get_active_framework_matrix` and `resolve_band` |
| Screens | Sentinel single page view `aiia`: list with search and status chips, a four section drawer (Basics, Impacts, Mitigation, Review), a dimensions dialog | About 340 lines of script and 50 lines of markup in `modules/sentinel/templates/index.html` |
| Shared | `entity_scope._KINDS[("sentinel", "aiia")]`, relationship rule `assesses` (AIIA to application), application delete guard in `governance/data_service.py`, event constant `SENTINEL_AIIA_COMPLETED` (never emitted) | |
| AI Governance | `guidance.py` (`_aiia` adapter, `_OPEN["aiia"]`, `aiia_prefill`), `workspace.py` Assessments tab, `checklist.py` step `aiia` | Today these send the person out to `/sentinel/?new=aiia&application_id=` and `/sentinel/?open=aiia:{id}` |

**Gaps in the current implementation (observed in the code; each gets a failing test before it is fixed in G3b).**

1. A new assessment is filed with no business unit unless the writer chose one, and a NULL unit means "organization wide", so an assessment created from the form without a unit is visible to everyone who may read AIIAs.
2. `ropa_id` and `dpia_id` are not checked against the writer's scope, and the read returns the linked RoPA's processing name and the DPIA's title to anyone who may open the AIIA, whatever their access to Privacy records.
3. Update has no version check: two people editing the same assessment overwrite each other silently.
4. Create, update and delete write no audit entry.
5. `status` accepts any string, and a non numeric likelihood or impact reaches `int()` and fails with a server error instead of a field message.
6. An approved assessment can be deleted, which would remove the basis of a later decision.

## 3. What moves and what stays

| Item | Before | After |
| --- | --- | --- |
| Screens (list, form with four sections, dimensions dialog) | Sentinel single page view | `/ai-governance/assessments`, `/ai-governance/assessments/new`, `/ai-governance/assessments/{id}` |
| API | `/sentinel/api/aiias*`, `/sentinel/api/aiia-dimensions` | `/ai-governance/api/assessments*`, `/ai-governance/api/assessment-dimensions` |
| Service | `modules/sentinel/data_service.py` (own connection, commits) | `modules/ai_governance/assessments.py` (service layer: takes `db` and `user`, checks capability and scope, never commits, returns audit and events) |
| Tables | `sentinel_aiia*` | **Unchanged** (section 4, decision D1) |
| Relationship kind | `("sentinel", "aiia")` | **Unchanged identity**; capability and deep link change |
| Capabilities | `module.sentinel.access`, `sentinel.dpia.manage` | `ai_assessment.view`, `ai_assessment.manage`, `ai_assessment.configure` |
| Licence gate | Needs the Sentinel module | None: AI Governance has no module licence |
| Privacy navigation | "AI Impact (AIIA)" opens the single page view | The same label stays as a plain link to the new list |
| Old addresses | `/sentinel/aiia`, `/sentinel/?open=aiia:{id}` | Redirects (302) to the new pages; the old `/sentinel/api/aiia*` routes are removed |
| DPIA, RoPA, vendors, breaches | Sentinel | Sentinel (unchanged) |

## 4. Decisions adopted (change any of these before G3b starts; after that each is a change request)

| # | Decision | Adopted default and why |
| --- | --- | --- |
| D1 | Stored identity | Keep the three tables, the `("sentinel", "aiia")` kind, reference numbers and the event constant. They are keys inside saved links, evidence references and audit rows; renaming them is a production data migration with no user-visible value. A rename is a separate, optional step (section 9, step 11) that needs a verified backup and a PostgreSQL rehearsal. |
| D2 | Who may read and write | `ai_assessment.view` and `ai_assessment.manage` go to the union of today's Privacy holders and the AI reviewers: super administrator, DPO, privacy analyst, compliance manager, GRC officer, risk owner, organization admin. `ai_assessment.configure` (the dimensions list, which changes how every assessment is scored) stays with today's holders plus organization admin: super administrator, DPO, privacy analyst, organization admin. **This widens write access** for compliance manager, GRC officer, risk owner and organization admin, who could read or review but not write an AIIA. Reason: the people who review AI uses should be able to complete the assessment that review waits for. |
| D3 | Licence | AIIA no longer requires the Sentinel module. An organization without Privacy can use it. The RoPA and DPIA pickers appear only for people who may open those kinds. |
| D4 | Delete | Allowed for `ai_assessment.manage` inside the person's unit scope, audited, and refused when the assessment is approved or, from G4, referenced by a decision. The reason is shown. |
| D5 | Business unit | A new assessment takes the linked system's unit, otherwise the author's own unit. NULL (organization wide) only by explicit choice, and only for a person with no unit. Same rule as intake requests. |
| D6 | Status values | `draft`, `in_progress`, `completed`, `approved`, validated on the server. Approval stays with any `ai_assessment.manage` holder, as today; the audit records who. Separation of duties belongs to the G4 decision, not to this status. |
| D7 | Dimensions | One list per organization, as today. Renaming a dimension still carries its scored history. |
| D8 | Concurrency | Optimistic version on update (`version` column, 409 with the current version), like profiles and requests. No idempotency key on create; the button disables while saving. |

## 5. Target design

**Pages** (built from text nodes with the AI Governance helpers, accessible, keyboard operable; one page per task instead of a drawer):

- `/ai-governance/assessments`: list with search, status, classification, system, and "not linked to a system" filters; server side paging; "New assessment" and, for configurers, "Impact dimensions".
- `/ai-governance/assessments/new?application_id=`: the form. Opened from a system, it is prefilled from the AI profile through the existing `GET /ai-governance/api/systems/{id}/aiia-prefill`, and says where each answer came from and when. A saved assessment keeps its own values (it is a snapshot); a later profile edit never rewrites it.
- `/ai-governance/assessments/{id}`: the same form for an existing assessment, with a header (reference, system, status, classification chip) and a link back to the system's Assessments tab.

**Form sections** are the four that exist today (Basics, Impacts, Mitigation, Review), with the same fields and vocabularies: no field is dropped and none is invented. Likelihood and impact stay 1 to 5; the overall classification is still computed from the active ERM rating framework (`unrated` when none is active, nothing when no row is scored).

**API** (all under `/ai-governance/api`): `GET/POST /assessments`, `GET/PUT/DELETE /assessments/{id}`, `GET/PUT /assessment-dimensions`, `GET /assessments/link-options?kind=ropa or dpia&q=`. Linking or unlinking a system is a `PUT` of `application_id`, not a separate call. Lists answer `{items, total, page, page_size, pages, can}` and reject unknown filters with 400, like the inventory.

**Schema** (additive only): `sentinel_aiia.version INTEGER NOT NULL DEFAULT 1`, and an index on `sentinel_aiia(application_id)` (added to both the SQLite and PostgreSQL index lists). Nothing is backfilled.

**Audit and events**: `ai_assessment_created`, `ai_assessment_updated`, `ai_assessment_status_changed`, `ai_assessment_linked`, `ai_assessment_deleted`, `ai_dimensions_changed`. One event, `ai_assessment.completed`, when the status first becomes `completed` or `approved`; G4 consumes it for decision readiness and notifications. The constant `SENTINEL_AIIA_COMPLETED` is replaced, not duplicated.

## 6. Linking, scope and references

- `application_id` must be a system the writer may open (same check the Sentinel route has had since G1a); `business_unit_id` must be in the writer's scope; `ropa_id` and `dpia_id` must be records the writer may open under the registry rule. Anything else is a 400 with a sentence, never a silent drop.
- Reads go through `entity_scope_sql(("sentinel", "aiia"), user)`. A record outside the viewer's scope is a 404 identical to a missing one. The linked RoPA name and DPIA title are returned only when the viewer may open those records; otherwise the field says "a privacy record you cannot open".
- **Unlinked assessments** (the old reviewer queue) become the list filter "not linked to a system" plus an inline action "Link to a system" for people with `ai_assessment.manage` who may open the chosen system. Nothing is matched by name automatically.
- The system workspace's Assessments tab, the checklist step and the quality checks read the same table through the same registry, so one assessment is never counted twice.

## 7. Other modules and code touched

| Where | Change |
| --- | --- |
| `core/rbac.py` | Three capabilities with the role sets of D2 |
| `modules/governance/entity_scope.py` | The `("sentinel", "aiia")` kind: capability `ai_assessment.view`, no licence module, deep link `/ai-governance/assessments/{id}` |
| `modules/ai_governance/guidance.py`, `checklist.py`, `workspace.py` | `_OPEN["aiia"]` becomes `/ai-governance/assessments/new?application_id={id}`; record URLs point at the new pages; `aiia_prefill` is called by the form |
| `modules/sentinel/` | Remove the view, drawer, dimensions dialog, the seven routes and the service functions; `/sentinel/aiia` and `?open=aiia:{id}` redirect; the Privacy navigation entry becomes a plain link |
| `database.py` | `version` column and index; dimensions seed stays |
| `core/events.py` | `AI_ASSESSMENT_COMPLETED` replaces the unused Sentinel constant |
| Templates | AI Governance sidebar gains "Impact assessments"; the system workspace links to the list filtered by system |
| Docs | `SYSTEMS_TEST.md`, `docs/manual-keyboard-test-script.md`, regenerated `docs/generated/capability_inventory.*` |
| Unchanged | `governance/data_service.py` application delete guard, relationship rule `assesses`, evidence links, ERM classification code |

## 8. Compatibility, rollout and rollback

- **No data moves.** The same rows are read and written from a new place, so row counts before and after must be equal and a rollback loses nothing.
- Order inside a deploy: the new pages and API ship first and work beside the old ones; the old screen and API are removed in the same release, because two writers of one table would split behavior (version checks, scope, audit).
- Old bookmarks, notification links and emails keep working through the redirects; the redirect tests are part of acceptance.
- A browser tab left open on the old drawer fails with a clear message on save and is fixed by a reload; nothing is lost that was not yet saved.
- The AI Governance rollout switch (planned in G2/G3) hides the new navigation entry and pages for an organization where it is off. The Privacy link then falls back to showing nothing rather than a dead end, so the switch has to be on before the Sentinel screen is removed in production. Record that dependency in the ledger when the switch lands.
- Rollback is a revert of the release: the table is unchanged and `version` is ignored by the old code.

## 9. Build order (test first, one commit-sized step each)

1. Failing tests for the six gaps in section 2 against the current routes (kept as the regression tests of the new service).
2. Capabilities, the registry kind change, the `version` column and index; the capability inventory test.
3. `assessments.py` service with the seven moved operations plus list filters and paging; move the seven classification and dimension tests of `tests/test_aiia.py` onto it with the same assertions.
4. Routes and the redirects; HTTP tests for the permission matrix, hidden-equals-missing, references, concurrency.
5. Pages and scripts: list, form, dimensions dialog; browser tests with an accessibility scan and keyboard operation.
6. Wire the checklist, prefill, workspace tab and the "not linked" filter with inline link action.
7. Remove the Sentinel screen, routes and service functions; move `tests/test_aiia_application_link.py` and the AIIA parts of `tests/test_relationships.py` to the new home.
8. Real PostgreSQL tests for the list SQL, version CAS and scope; full backend, PostgreSQL and browser suites.
9. Regenerate the capability inventory; update the manual test script and `SYSTEMS_TEST.md`.
10. Ledger entry: evidence, counts before and after, skipped checks, decisions to confirm.
11. Optional, only on the owner's request: rename tables and re-key stored kinds, with a rehearsal on a copy of production data.

## 10. Acceptance

- Every operation the Sentinel screen offered works at the new address with equal or stricter scope; a person who could not read or write before, and is not in D2, cannot now.
- The permission matrix (anonymous, staff, privacy analyst, DPO, compliance manager, GRC officer, risk owner, organization admin, external auditor, platform administrator) against list, detail, create, update, delete, dimensions, link options, counts and search is tested for the same unit, another unit, a unit the person leads, a NULL unit record and a missing id. No unauthorized title, count or id appears.
- "Start the assessment" from a system opens the form prefilled with its source and time; saving links the assessment to that system and it appears on the Assessments tab and in the checklist as in progress or complete.
- `/sentinel/aiia` and `/sentinel/?open=aiia:{id}` land on the right page; `/sentinel/api/aiia*` no longer exist.
- Row counts of the three tables are equal before and after; the only schema change is `version` and one index.
- The suites named in step 8 pass on SQLite and real PostgreSQL; the browser tests include keyboard operation, a 200 percent zoom check and a true mobile viewport for the list and the form.

## 11. Not part of this move

No change to DPIA, RoPA, AIMS or the ERM rating framework; no new assessment types, templates or AI drafting; no decision workflow (G4); no table or kind rename (D1); no public or auditor view of an assessment.

## 12. To confirm with the owner

D2 (the wider write set and the new configure capability), D3 (no Sentinel licence needed), D4 (approved assessments cannot be deleted) and whether the Privacy navigation should keep its link (the default) or drop it. None of these blocks the build; each is recorded in the ledger as adopted by default.
