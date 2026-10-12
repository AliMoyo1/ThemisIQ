# 08. G5 build plan: monitoring, evaluation records, regulatory impact, explanations

**Status:** Build plan written 2026-10-11 before code, from [03](03-delivery-and-acceptance.md) slice G5, [02 journeys 6, 7 and 9](02-feature-journeys.md) and the briefs [VerifyWise 04](../verifywise-features/04-evaluations-monitoring.md), [05](../verifywise-features/05-regulatory-impact.md) and [08](../verifywise-features/08-contextual-ai-advisor.md). Evidence of what was built goes in the [execution ledger](05-execution-ledger.md).

## 1. What is built here and what is not

The slice names four things that can be done from a laptop and a handful that cannot. Built:

| Part | What a person gets | Source of truth |
| --- | --- | --- |
| **Monitoring signals** | The Monitoring tab shows, for the use, what is measured: its decision and next review, open incidents linked to it, AI controls that are implemented without current proof, proof that expires soon, the last evaluation and whether it passed, and regulatory changes confirmed for it. A source that reports nothing says "not measured", never "fine". | The owning modules, read through the viewer's scope |
| **Evaluation records** | A reviewer records an evaluation run against a use: test set and version, rubric version, the version of what was evaluated, who or what evaluated it, thresholds, scores by dimension, cases and failures, retention choice, and an optional Vault item as the artifact. Passing is computed from the scores and the thresholds on the server. A run that failed, was cancelled, or errored is never shown as passed; a run older than the last material change or than 180 days reads as stale. Two runs can be compared. A failed run proposes a task and a decision re-review; it does not mark a control failed. | `ai_evaluation_runs` |
| **Regulatory impact** | A change posted to the Regulatory Inbox is matched, by fixed rules, to AI uses whose intended jurisdictions it concerns. A reviewer confirms or dismisses each candidate with a reason; a confirmed one becomes one owned action and a note on the use; a dismissed one does not come back without a material change to the source. | `ai_regulatory_impacts` over `regulatory_updates` |
| **Explain** | On a use, "Explain this status" gives a short account of why it is in the state it is in, each sentence tied to a fact the viewer may see. The account is built from the rules; when the organization's AI policy allows it, a model may rephrase it, and any sentence whose citation does not resolve to a fact is dropped. Without AI the rule based account is shown. | `explain.py` over the same service reads |

Not built, and said plainly:

- **Running evaluations.** ThemisIQ does not execute a customer's AI system or a test set against it: there is no job runner, no provider call, no budget or timeout machinery for evaluations. Runs are recorded by a person or by an integration the organization controls. The brief's slice B (bounded asynchronous execution, cancel) and slice C (customer use pilot with component targets) are not claimed.
- **The Ask ARIA baseline run.** Its deterministic scope and citation checks already exist as the Ask ARIA test suite (`tests/test_aria_ask_scoping.py`). They are not a scheduled job; nothing here displays a "last evaluated" for Ask ARIA.
- **Regulatory sources.** The inbox is manual: a person posts a change with its source link and effective date. Nothing fetches regulation text, so "current primary source" is the person's responsibility and the screen says so.
- **Find, Prepare and Suggest.** Only Explain is built. Retrieval over several modules, drafting and link suggestions need the shared scoped retrieval and the evaluation set the brief asks for before release, which do not exist.

## 2. Data

| Table | Holds |
| --- | --- |
| `ai_evaluation_runs` | One row per recorded run: application, name, test set name and version, rubric version, subject version, evaluator kind (`deterministic`, `human`, `model_graded`), status, started and finished, thresholds and scores (JSON), cases total and failed, retention, artifact (Vault item id), notes, who recorded it, review outcome and reviewer, `version`. |
| `ai_regulatory_impacts` | One row per (update, application): status `candidate`, `confirmed`, `dismissed`; the rule that matched and why; reviewer, time and reason; the task made on confirmation; the update's fingerprint when the row was last reviewed (so a changed update reopens a dismissed one). Unique on (update, application). |

Both carry the system's business unit for queues. Neither stores prompt or response text.

## 3. Rules enforced on the server

1. A run is recorded by `ai_use.review` holders for a system they may open. Scores are numbers in range and every threshold names a score; status is one of the four; a `completed` run with a score below its threshold is `passed = false`. (Runs against a platform feature key instead of an application are not built: the table's `application_id` is not null. See [09](09-g6-build-plan.md) section 5.3.)
2. Staleness and drift are derived from the rows and the profile's last material change, never stored.
3. A failed run raises one event; its handler notifies the owner and the deciders (once per run) and the decision state gains the reason "an evaluation failed after it was signed".
4. A regulatory candidate is proposed only for an active use with a profile in the update's scope, by the matching rules of `regulation.py`; reviewing needs `ai_use.review` and the system in the reviewer's scope. Confirming makes at most one task per (update, system).
5. Explain reads only through the viewer's own scope, adds no fact the checklist, decision or monitoring reads did not return, and goes through the AI wrapper like every other model call.
6. A hidden system answers like a missing one on every call.

## 4. Build order (test first)

1. Rules (pure): run outcome and staleness, comparison of two runs, jurisdiction matching, citation validation.
2. Schema, services and SQLite tests: evaluations, monitoring signals, decision reopening on a failed run, regulatory impact.
3. Routes and HTTP matrix; events, notifications and My Work.
4. Monitoring tab, evaluation form, regulatory queue and Explain panel; browser tests.
5. Real PostgreSQL tests; capability inventory; ledger and honest limits.
