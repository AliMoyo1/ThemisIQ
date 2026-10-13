# 07. G4 build plan: decisions on an AI use

**Status:** Build plan written 2026-10-11 before code, from [03](03-delivery-and-acceptance.md) slice G4, [02 journey 5](02-feature-journeys.md), the [domain contract](01-domain-and-integrations.md) section 1 and 2, and the [approval gates brief](../verifywise-features/03-approval-gates.md). Evidence of what was built goes in the [execution ledger](05-execution-ledger.md).

## 1. What a person can do when it is built

- **Ask for a decision.** The owner of an AI use, or a reviewer, asks for a decision from the system's Decisions tab. One open request per system; asking twice returns the same request.
- **See the brief.** A decider sees what is proposed, which required steps are done, which are not, the assessments and their status, the AI controls with the proof held for them, the quality checks that are open, and what changed since the last decision.
- **Decide.** A decider approves, approves with named conditions and an expiry date, returns it with a note, or rejects it with a reason. Approving with a required step unresolved needs an explicit override reason, which is recorded.
- **See the standing decision.** The workspace shows the latest decision, who made it, why, its conditions and expiry, and the history. When a covered fact changes, or the approval expires, or proof it relied on expires, the state reads "Needs re-review" and the earlier decision is untouched.
- **Get the work where they look.** A decider sees the request in My Work and a notification; an owner sees a return or a decision, a due condition, or a re-review in My Work and a notification. One entry per event, never a second one for a retry.

## 2. Boundaries

- A decision never edits an AIIA, a risk, a policy or a control. It records a judgement about the use and what it was based on.
- ERM risk acceptance stays a separate signed exposure decision. The decision brief links to it and does not stand in for it.
- No model output sets a state. Nothing here calls an AI provider.
- Not built here: auditor packs of a decision (G6), monitoring-driven reopening from evaluations and incidents (G5; this slice reopens on a profile change, a tier change, an expired approval and expired proof in the manifest), an editable approval chain per organization (a single decider stage with separation of duties).

## 3. Data (additive, nullable where a fact may be unknown)

| Table | Holds |
| --- | --- |
| `ai_use_decisions` | One row per request, append only in meaning: the request (who, when, note, the system's unit), then one final outcome set once (status, decider, rationale, expiry, the frozen manifest and its hash, the profile version, fingerprint and tier it covers, rule versions, any override reason), and a revocation set once. `version` for optimistic concurrency. A partial unique index allows one `proposed` row per application. |
| `ai_use_decision_conditions` | The named conditions of an approval: text, due date, open or met, who and when. The decision row keeps the text as signed; this table tracks whether it was met. |

`business_unit_id` on the decision carries the system's unit when asked, so queues and My Work can be scoped without reading the application each time. It is added to the unit reference guard.

## 4. State

`status` on the row: `proposed`, then exactly one of `approved`, `approved_with_conditions`, `rejected`, `returned`, or `withdrawn` (the requester takes it back). A revoked approval keeps its status and carries `revoked_at`.

The workspace state is derived, never stored: **No decision**; **Waiting for a decision** (an open request); **Approved** or **Approved with conditions** (the latest final decision is an approval, not revoked, not past its expiry, and the profile fingerprint and the effective tier equal the ones it covered and no proof item in its manifest has since expired); **Needs re-review** (the same approval, with the reason named: a covered fact changed, the tier changed, the approval expired, proof expired); **Not approved** (latest final decision is a rejection or a return); **Revoked**.

## 5. Rules enforced on the server

1. A request needs an AI profile, the system to be active, and no open request already. The requester is the system's owner or holds `ai_use.review`.
2. The decider holds `ai_use.decide` and may open the system. With separation on (the default), the decider is neither the person who asked nor the system's owner. An organization may turn separation off (a single person may be the whole function); the choice is stored, audited and shown on the decision.
3. The brief is built under the decider's own scope. The decision carries the hash of the brief the decider saw; if the facts moved before they signed, it is refused with "reload" and nothing is stored.
4. Approval is refused while a required step is unresolved unless `override_reason` is given (3 to 1000 characters). The override is stored on the decision and audited.
5. Conditions need text; an expiry must be a later date. A rejection and a return need a reason.
6. Every transition is a compare-and-set on the row's version and status, so two deciders cannot both win and a retry of the same request is a no-op that returns the existing result.
7. A hidden system answers exactly like a missing one on every call. A record named in a brief or a notification is shown to a viewer only when they may open it.

## 6. API and pages

`GET /ai-governance/api/systems/{id}/decisions` (state, latest, history, open request, what the viewer may do), `GET .../decision-brief` (deciders and requesters), `POST .../decisions` (ask), `POST /api/decisions/{id}/decide`, `POST /api/decisions/{id}/withdraw`, `POST /api/decisions/{id}/revoke`, `PUT /api/decision-conditions/{id}`, `GET /api/decisions` (the queue of open requests and re-reviews in the viewer's scope). Pages: the Decisions tab of the workspace (the action surface) and `/ai-governance/decisions` (the queue). Separation is set on the AI Policy page.

## 7. Events, notifications, My Work

New events `ai_use.decision_requested`, `ai_use.decision_made`, `ai_use.decision_revoked`. Handlers notify through the existing one-per-person-per-event path; the existing `ai_use.material_change` event also notifies the owner and the deciders. My Work gets an `ai_governance` adapter: requests to decide, requests returned to their author, intake requests waiting for a reviewer, conditions due, and re-reviews, each keyed so one source event is one entry.

## 8. Build order (test first)

1. Pure rules: state derivation, hash of a brief, separation and override checks (`tests/test_ai_governance_decisions_rules.py`).
2. Schema, service and service tests (SQLite): request, brief, decide each outcome, return, reject, withdraw, revoke, conditions, concurrency, separation, override, stale brief, hidden systems.
3. Routes and HTTP tests: the permission matrix, hidden equals missing, body checks.
4. Events, handlers, My Work adapter and their tests.
5. Workspace Decisions tab and the queue page; browser tests with accessibility and keyboard.
6. Real PostgreSQL tests: the unique open request under two requesters at once, compare-and-set under two deciders, the queue SQL.
7. Capability inventory, ledger, honest limits.

## 9. Acceptance (from the gates)

- An approval cannot complete with a mandatory step unresolved without a recorded override; two deciders cannot overwrite each other; a retry does not repeat.
- A change after approval makes the workspace read "Needs re-review" and leaves the earlier snapshot exactly as signed.
- A decider reaches the source records from the brief and comes back to the decision; a record the viewer may not open is never named in a brief, a queue, a notification or My Work.
- No model output decides or signs.
