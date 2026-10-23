# Themis work assistant

Status: slices A-E implemented on the `codex/themis-grounded-assistant` branch, pending validation and integration. This work starts from `claude/onboarding-agent-plan` at `0626a370`; that branch is not yet merged into master. The existing guide and tours remain the navigation source. This plan extends the same Themis panel with permission-checked, read-only case answers and local draft previews.

## Product contract

Themis answers four questions for a specialist: what is happening, why it matters, what the next authorized action is, and which current record supports each claim. It may navigate, explain and prepare a draft. It never decides, approves, sends, publishes, changes a source record, or treats an AI suggestion as a completed control.

The owning module remains the source of truth. The assistant does not create a second knowledge store of statuses, deadlines or permissions. A missing, stale, inaccessible or failed source is shown as such, never filled with an invented answer.

## Release slices

| Slice | User journey | Source | Exit condition |
| --- | --- | --- | --- |
| A. Guided AI onboarding | “I want to onboard a new AI model” starts with the systems catalogue, then offers registration or form import according to the viewer's capabilities. | Platform guide, AI Governance routes and RBAC | No BCM BIA answer; every action opens an authorized route; unavailable roles see no restricted action. |
| B. Selected request | On an AI request, “what is outstanding?” explains draft completeness, recorded review notes, open questions and possible existing systems. | `service.get_intake`, `rules.missing_for_submit`, `questions.list_questions`, `service.find_duplicates` | Same-org/unit or author only; no inaccessible request or duplicate identity; links return to authorized records. |
| C. Selected AI system | On a system workspace, “why is this blocked?” shows the decision state and top outstanding items with reasons and source actions. | `decisions.get_decisions`, `outstanding.get_outstanding`, existing scope adapters | No claim that a checklist is approval; inaccessible or failed linked sources never become “complete.” |
| D. Cross-module cases | Add an adapter per audit, incident, risk, DPIA, control and Vault artifact. | Each owning module's scoped read service | The viewer can open every cited version; changed rights or deleted evidence invalidate answers. |
| E. Assisted preparation | Draft follow-up questions, an assessment note and an external reply from verified facts. | Same fact packets, organization AI policy | Preview and human approval before any source write or external response. |

The implementation is limited to exact selected-record contexts and conservative recorded facts. It does not search arbitrary cross-module free text or send case data to an AI provider.

## Build status in this branch

Slices A-E are implemented in `core/themis_work.py`, the trainer endpoint and the existing Themis panel. The selected-system answer reads the module's connected outstanding-work service, which already checks the linked assessments, control proof, continuity, oversight, evaluation, regulatory work and decision through the viewer's scope. It shows the first actionable items and links back to their sources. The selected-request answer reads current intake state, open questions and scoped possible duplicates. The local guide replaces the provider call for general how-to questions; its reserved policy registration remains so stored organization policies continue to parse, and operator oversight displays that feature as paused.

D reads exact selected audit, GRID control, BCM incident, Sentinel breach or DPIA, ERM risk, and Vault item IDs. Each fact query repeats the shared entity scope after the source descriptor gate. These answers report recorded state and limited dates or risk fields, plus a source link. The GRID control link now opens the control drawer. Drawer selection is a browser hint only; the server checks access again on every question. No arbitrary title search, document text retrieval or AI-generated cross-module synthesis is enabled.

E prepares local, deterministic follow-up questions and assessment-note previews from those current scoped answers. An external reply preview is available only for an AI use request and includes a safe status explanation and missing field labels, never a reviewer note or internal link. The specialist must review and copy the draft; Themis has no save, approve or send action. These local previews do not depend on an organization provider policy and incur no provider calls. Richer provider-assisted drafting requires a separate privacy and citation review.

This branch has not been merged or deployed. The existing guide assertions were adjusted for the local behavior. Automated tests and a browser walk-through have not been run in this build pass.

## Read and answer boundary

1. The signed-in person and organization come from request context. A client-supplied page path identifies only a candidate record. The owning service rechecks capability, organization, business-unit scope and record visibility. A hidden ID and a nonexistent ID produce the same outward answer.
2. A fact packet is assembled from scoped service results, not a prompt, search-index row or page DOM. It carries the source path, source version or update time where available, and a freshness state. The UI links only to same-origin paths returned by the server.
3. Deterministic rules calculate request completeness, decision state and outstanding work. The model may rephrase a fact packet only after organization policy allows its declared data categories. It cannot create a fact or source citation.
4. Initial case and platform-guide answers stay local. The prior guide sent a lightly masked free-text question to an external provider; that route is disabled in this slice because a person can type personal, evidence or secret content into the question. Later provider use needs a privacy review, bounded fact packet and accurate feature declaration.
5. Case answers are not cached across users. Any later cache must bind organization, viewer rights, source IDs and versions, and expiry. Do not log questions, record text or model output in routine request logs.
6. Source text, external form answers and uploaded evidence are data, never instructions. A future drafting call uses bounded, minimized excerpts, citation validation, token budgets and a manual fallback.

## UI

Keep one Themis panel. Present a short answer, at most three next-action links, and a small “From these records” area. Distinguish **recorded state**, **suggested next step**, and **unavailable information**. A user can open the cited source but cannot trigger a write from the assistant. On an AI system workspace, offer “Explain this use” and “What remains?” suggestions.

## Evaluation and release gates

- The screenshot query routes to AI Governance for an authorized specialist, including when no provider is configured.
- A request/system page answer is identical in scope to its owning module page. Wrong-unit, wrong-org, deleted and nonexistent IDs reveal no name, count, linked title or existence signal.
- All displayed record links open under the caller's current permission; a permission change before the click is enforced by the source route.
- Source outages produce an explicit unavailable state. No checklist item is counted complete from a stale index or missing source.
- No case data appears in AI provider traffic or routine logs in A-C. Answers remain available when organization AI is disabled.
- Before release, D/E need a question set, citation and abstention checks, role/unit/tenant matrix, prompt-injection cases and a specialist browser review. Provider cost and latency are not applicable to these local drafts.

## Integration notes

The Claude Level 2 guide is not a record assistant. Its platform KB and guided tours are retained. The first case adapters use AI Governance's scoped request, connected outstanding-work and decision services. Ask ARIA's live-document recheck and citation binding are the pattern for later evidence retrieval. The `launcher.api_trainer_ask` AI feature declaration remains in the catalogue for historical compatibility, but the endpoint does not make a provider call in this slice. Review that declaration before enabling any record-aware provider call.
