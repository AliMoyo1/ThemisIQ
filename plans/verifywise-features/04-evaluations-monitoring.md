# 04 · AI evaluations and monitoring

**Inspiration:** VerifyWise [LLM evaluations](https://verifywise.ai/user-guide/llm-evals/llm-evals-overview). **Priority:** after inventory and decision contract; start with ThemisIQ's own ARIA. **Size:** L.

## Existing ThemisIQ anchor

ARIA already answers questions and drafts content; ORM has AI controls/AIMS assessment records. Evidence Vault can hold reviewed result artifacts. The first evaluation target should be Ask ARIA's scoped retrieval and citation behavior, before offering an evaluation service for customer AI systems.

## User journey

An AI owner picks an approved, versioned test set, model/assistant version, and evaluation profile. They run tests in an isolated job, then see pass/fail by dimension, example failures with minimal retained content, cost, and a comparison with the previous run. A reviewer accepts the evaluation report as evidence or opens a finding. The AI-use workspace shows **last evaluated**, scope, and drift; it never equates a passed test with legal compliance.

## Build slices

- **A (ARIA baseline):** create a small curated, non-sensitive test set for permitted citations, no-match responses, prompt injection resistance, cross-org/BU leakage, and task accuracy. Store dataset version, evaluator/rubric version, model version, run timestamp, score inputs, and reproducible artifact references. Use deterministic checks where possible; label subjective model-graded scores separately.
- **B (review and evidence):** add bounded async execution with timeout, budget, retry/idempotency, and cancel. A reviewed run can link to ORM AI controls, AIIA, and Vault evidence. Failed cases create proposed work, not automatic control failure or approval.
- **C (customer use pilot):** only with explicit provider/data permissions, add model-component targets, evaluation datasets, baseline thresholds, and periodic reruns. Keep raw prompts/responses minimized and scoped; avoid running customer AI through ThemisIQ without an agreed data path.

## Acceptance gates

- Every score links to its test cases, rubric, input/output retention choice, and model version; a failed or interrupted run is not reported as passed.
- A cross-tenant retrieval case has zero unauthorized titles/snippets/citations. Results remain permission-checked when opened or exported later.
- Reviewers can compare two versioned runs and identify what changed; evaluation limits protect the VPS and provider budget.

**Out of scope for first slice:** opaque “AI safety percentage”, broad live traffic capture, automated certification, and unreviewed synthetic evidence.
