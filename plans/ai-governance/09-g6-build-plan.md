# 09. G6 build plan: review packs, AI literacy, the platform's own AI features

**Status:** Build plan written 2026-10-11 before code, from [03](03-delivery-and-acceptance.md) slice G6, [02 journeys 8, 10, 11 and 12](02-feature-journeys.md) and the briefs [VerifyWise 06](../verifywise-features/06-auditor-sharing-trust.md) and [07](../verifywise-features/07-ai-literacy-training.md). Evidence of what was built goes in the [execution ledger](05-execution-ledger.md).

**Implementation update, 2026-10-12:** G6a review packs are built and passed focused service, HTTP, browser and real
PostgreSQL checks. G6b AI literacy and G6c platform feature oversight are built in the working tree. Eight focused
service/HTTP cases, two browser journeys and one real PostgreSQL case pass. A read-only production query found no old
tenant copies of `platform_ai_features`. Section 5 below is the original handoff
snapshot; use the execution ledger for current state. The G6 milestone lanes then passed: 2079 backend, 66 guarded
PostgreSQL and 481 browser tests, with the documented skips and two repaired browser regressions.

## 1. What is built here and what is not

| Part | What a person gets | Source of truth |
| --- | --- | --- |
| **G6a. AI review pack** | A reviewer picks one AI use, previews exactly what a pack would hold (profile, decision and conditions, assessments, controls with proof, evaluations, regulatory changes, gaps and dismissed findings), chooses whether people's names and free text go in, names one signed-in recipient, an expiry and whether they may download, and issues it. The recipient sees a frozen, read-only account with an index, the date it was generated and a stated hash. The owner sees who opened it, can revoke it at any time, and is told what has changed since it was generated. | `ai_review_packs` (frozen manifest), `ai_review_pack_events` (access log) |
| **G6b. AI literacy** | An administrator defines a course with versioned content and an optional knowledge check, and who it applies to (roles, a business unit, owners of AI uses). A person sees one assignment in My Work, reads, answers or acknowledges, and sees when it renews. A reviewer sees coverage with its denominator, by course, and who is overdue or expired. A use whose owner has no current completion carries one quality check. | `ai_literacy_courses`, `ai_literacy_versions`, `ai_literacy_completions` |
| **G6c. The platform's own AI features** | A platform operator sees every first party model call site from the registry in `core/ai_policy.py` with the categories of data it sends, how often it was used, and what the operator recorded: owner, provider and model note, known limitations, incident path, deployment decision, review due. A review that is overdue says so. No customer prompt or evidence is stored. | `core/ai_policy.FEATURES` (code) and `platform_ai_features` (operator notes) |

Not built, and said plainly:

- **Shadow AI discovery (journey 11).** The plan allows it only after a named, authorized feed exists with documented fields, retention, residency and an owner. None does. There is no scraper, agent, gateway or manual import in this slice, and the product does not claim coverage of unregistered AI. Declaring "I do not know whether a vendor embeds AI" (slice G1) remains the only discovery path.
- **Model component lineage.** The plan says "if needed". Nothing in the pilot evidence asks for it; a use records its vendor and its models in the profile.
- **Public trust page, anonymous evidence links, certified or readiness percentages.** Out of scope by the plan. A pack never says a use is compliant, certified or ready; it says what is recorded and what is missing.
- **GRID audit packs with exact Vault versions.** The existing GRID share flow is unchanged. The review pack is a new object for AI uses and does not widen what a GRID share link reaches.
- **Reminders by email and a schedule.** The assignment shows in My Work and the person is told once when a course is assigned to them; there is no daily reminder job.
- **Reconciling BCM and Sentinel training.** BCM modules and attestations and Sentinel training sessions stay in their modules. BCM has no course version and Sentinel keeps an aggregate rate, so neither can be counted as an individual completion of an AI course. The coverage screen says so. A migration needs real data shapes, which are not available from a laptop.
- **Export of literacy results.** Coverage is on screen with drill down; no download is added until someone defines the audience and fields.

## 2. Data

| Table | Holds |
| --- | --- |
| `ai_review_packs` | application and its name at the time, business unit, name, purpose, status (`issued` or `revoked`; a preview is never stored, so there is no draft), recipient, `allow_download`, `include_people`, `include_notes`, expiry, the frozen manifest (JSON) and its hash, generated, issued and revoked by and when, reason, `version`. |
| `ai_review_pack_events` | pack, person, `viewed`, `downloaded` or `denied`, time. A denial stores a reason code only. |
| `ai_literacy_courses` | title, summary, the working copy (body, questions, pass mark), audience (roles, unit, `ai_use_owners`), renewal months, days to complete, status (`draft`, `active`, `retired`), current version, the lowest version whose completion still counts (`retake_from`), `version`. |
| `ai_literacy_versions` | course, version number, the body, the questions (JSON), pass mark, who published and when, `retake`. Published rows are never edited. |
| `ai_literacy_completions` | course, course version, person, business unit at the time, outcome (`passed` or `acknowledged`), score, completed and expires. A renewal or a retake adds a row and keeps the earlier ones; the person counts once because only the latest unexpired completion at or above `retake_from` is read as current. There is no unique constraint: a second submit while a completion is current returns it instead of adding a row. |
| `platform_ai_features` | feature key, owner, provider note, known limitations, incident path, deployment (`in_service`, `paused`, `retired`), review due, last reviewed and by, `version`. Platform schema only. |

## 3. Rules enforced on the server

1. A pack is built through the author's own scope: every section is read with the author as the viewer, so a record the author may not open is absent and the section says it is not open to them. The stored manifest carries titles, refs, states and dates, never links or internal ids another person could try.
2. A pack is issued only to an active person of the same organization who holds `ai_pack.receive`, with an expiry from 1 to 90 days. People's names and free text are in the manifest only when the author chose so at preview time; the preview is the manifest.
3. Every open of a pack checks, in this order: the pack is issued, not revoked and not expired; the caller is the named recipient (or an author or manager who may open the use); the manifest still hashes to the stored value; the issuer still holds `ai_pack.manage` and may still open the use. Any failure answers 404 with the same body as a pack that does not exist, and is logged.
4. Download follows the same checks and is allowed to the recipient only when the author allowed it.
5. A course version is immutable once published. A completion belongs to one version and is never rewritten; a new version that needs a retake makes people due again without removing what they did.
6. The questions are held on the server; the learner receives the prompts and options, never the answers. The pass mark is applied on the server.
7. Training status never changes a decision or a tier. The only effect is one quality check on the use, and a notice on the course's coverage.
8. Coverage and lists are scoped by business unit like everything else, and individual results are visible only to holders of `ai_literacy.report` within scope and to the person themselves.
9. Platform feature notes need `ai_governance.platform.manage` (super administrators); nobody else sees the page and no tenant data enters the table.

## 4. Build order (test first)

1. Rules (pure): pack hashing and section assembly from given facts, expiry and hash checks; course version currency (retake rule), assignment and status of a person, grading; platform review due.
2. Schema, services and SQLite tests for each part; capabilities and events; the quality check and My Work items.
3. Routes and the HTTP matrix (signed out, outside auditor, wrong unit, wrong recipient, non-object body).
4. Pages and browser tests.
5. Real PostgreSQL tests, capability inventory, ledger and honest limits.

## 5. Where this stands (2026-10-12) and the design of what is not written

Progress is recorded in [05-execution-ledger.md](05-execution-ledger.md), section "Handoff". In short:

| Part | Written | Not written |
| --- | --- | --- |
| G6a review packs | `modules/ai_governance/review_packs.py` (pure rules and service), `tests/test_ai_governance_pack_rules.py` (33, passing), `tests/test_ai_governance_packs.py` (service tests, not run: need the wiring below) | schema, capabilities, event and handler (all in `handoff/patch_g6_core.py`, not applied); routes, pages and script; sidebar entry; shell flag for outside auditors; HTTP and browser tests; real-PG test |
| G6b literacy | the data model and rules in this document | `modules/ai_governance/literacy.py`, its tests, routes, pages, My Work item, the owner check in `quality.py`, PG test |
| G6c platform features | the data model and rules in this document | `modules/ai_governance/platform_features.py`, its tests, a super administrator page, PG test |

### 5.1 G6a wiring that remains

- **Routes** in `modules/ai_governance/routes.py`. Pages: `GET /packs` (capability `ai_pack.manage` or `ai_pack.receive`) and `GET /packs/{id}`. JSON under `/api`: `GET /packs/mine` (register before the id route), `GET /pack-recipients?q=`, `GET /systems/{id}/packs`, `POST /systems/{id}/packs/preview`, `POST /systems/{id}/packs` (body carries `expected_hash`), `GET /packs/{id}` (opens, records `viewed`), `GET /packs/{id}/export` (records `downloaded`, sends `Content-Disposition: attachment`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`), `GET /packs/{id}/history`, `GET /packs/{id}/changes`, `POST /packs/{id}/revoke`.
- **Opening is the one write on a GET.** `review_packs.open_pack` returns `{"refused": code, "http": 404 or 403}` instead of raising so the route can commit the access record, including the denial, before it answers. Do not route it through `_read` (which does not commit) or `_transact` (which rolls back on a `ServiceError`): commit explicitly, then answer. A refusal answers with the same body as a pack that does not exist.
- **Outside auditors** hold none of `ai_use.view`, so the module's pages refuse them. The two pack pages are guarded by the two pack capabilities only, and the shell must show a link to `/ai-governance/packs` for a person who holds `ai_pack.receive` even when `can_ai_use` is false (`core/shell_context.py`). The notification handler already links to `/ai-governance/packs/{id}`.
- **Pages** use the module's own script style (no inline script, `textContent` only, `.aig-dialog` for dialogs). The manager's screen is a tab or section on the workspace plus `/packs`: build (name, purpose, who sees names, who sees notes, download, expiry, recipient search), preview (the manifest sections as a read-only list with the not-shown sections called out), issue, then the list with state, opens and last opened, history, "what changed since", revoke with a reason. The recipient's screen is the frozen account, its index, the generated date, the hash, the disclaimer, and a download button only when allowed.
- **Tests still to write:** HTTP matrix (signed out 303, outside caller 403, wrong unit 404 with the identical body to a missing pack, non-object body 400, `mine` is not shadowed by the id route, export headers, recipient cannot reach the manager's list), one browser test per screen with the accessibility scan, one real-PG test (issue, open, revoke, issuer loses the right, inside a tenant schema).

### 5.2 G6b literacy, design

- **Service** `modules/ai_governance/literacy.py`, same conventions as the other services. Manage: `create_course`, `update_course` (compare and set on `version`), `publish_course(id, retake, expected_version)`, `retire_course`, `list_courses`, `get_course`. Learner: `my_courses`, `get_for_learning` (current published version, answers removed), `complete(course_id, answers, acknowledged)`. Report: `coverage` and a per-course drill down. Helper for the handler: `assignees_of(db, course_id, org_id)` (the event handler in `patch_g6_core.py` already calls it).
- **Course lifecycle.** A new course is `draft`. Publishing needs a title, a body, a non-empty audience and valid questions; it copies the working copy into `ai_literacy_versions` as `current_version + 1`, sets `status = active`, and `retake_from` becomes this version when `retake` is true (the first version always is) and is otherwise left alone. Publishing with `retake` raises `AI_LITERACY_PUBLISHED` once; people are told once. Retiring stops new assignment and keeps every completion.
- **Audience.** A person is in a course's audience when they hold one of `audience_roles` (never `external_auditor`) or `audience_owners` is set and they own an active AI use, and, when the course has a unit, their own unit is that unit or below it (`bu_scope_ids({"business_unit_id": unit, "is_super_admin": False})` is the subtree). Assignment is derived at read time, never stored, so a person who changes role stops being assigned and nothing goes stale.
- **Status of one person for one course.** `not_assigned`; `completed` (a completion at or above `retake_from`, not expired); `expired` (had one, now lapsed); `overdue` (never completed and past due); `to_do`. Due is `max(published_at of the retake_from version, the person's account creation date) + due_days`. A renewal date is shown for `completed`. There is no "in progress": nothing records that a person opened a course, and the screen does not pretend otherwise.
- **Grading** is server side. Questions are `{prompt, options (2 to 6), correct}`, at most 20, and a course with questions needs a pass mark from 1 to 100; a course without questions is acknowledged by an explicit `acknowledged: true`. A failed attempt returns the score and the numbers of the questions that were wrong, never the correct options. Answers must be a list of the same length as the questions, of whole numbers inside each question's range.
- **Reports.** `coverage` returns per active course: the denominator (people in the audience inside the viewer's unit scope), completed, expired, overdue, to do, and a drill down of names with state, due and completed dates, 200 at most, sorted by name and never by outcome. Unit scope for people: the viewer's subtree only; people with no unit are visible to unrestricted viewers only. The screen says BCM attestations and Sentinel training sessions are separate records and are not counted.
- **Where it shows.** My Work: one entry per course that is `to_do`, `overdue` or `expired` for the person (state derived, so a retry never doubles it), added to `_ai_governance_work` in `modules/launcher/my_work_service.py`. Quality: one warning on a use whose owner has no current completion of an active owner-targeted course (`owner_literacy`, dismissible like the other findings; the fix link is `/ai-governance/literacy`). Training status never changes a decision, a tier or a checklist step.

### 5.3 G6c platform features, design

- **Service** `modules/ai_governance/platform_features.py`: `list_features(db, user)` joins `core/ai_policy.FEATURES` (label, data categories, in code order) with `platform_ai_features` and a count and last-used date per feature from `ai_usage_log` (counts only, no content); `save_notes(db, user, feature_key, raw, expected_version)` upserts the operator's notes and validates `feature_key` against the registry, `deployment` against its three values, `review_due` as a date, and text lengths; `mark_reviewed(db, user, feature_key)` sets `last_reviewed_at` and the reviewer. A feature with no note row is "not reviewed". A review whose due date has passed reads "overdue".
- **Capability** `ai_governance.platform.manage` (super administrators). Read and write both need it; nobody else sees the page. The table lives in the platform schema only, so the page runs outside any tenant and the usage count is across organizations (a count, never content).
- **Page** `/ai-governance/platform-features` (or inside the existing super administrator area, whichever the shell's navigation already groups platform pages under): one row per feature with its data categories, usage, deployment, owner, review due and a dialog for the notes. The page says it is an internal oversight record, not a customer inventory and not a certification.
- **Evaluation of a first party feature** (recording a run against a feature key instead of an application) is not built: `ai_evaluation_runs.application_id` is not null and the evaluation service is application level.
