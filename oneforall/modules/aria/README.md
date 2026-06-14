# ARIA — Governance, Risk & Compliance

Framework- and control-centric module: import a framework (ISO 27001, SOC 2,
GDPR, NIST CSF, …), manage its controls, attach policies and evidence, run
cross-mappings, generate AI-assisted policy text.

## Mounts

- `/aria/` — dashboard.
- `/aria/frameworks`, `/aria/controls`, `/aria/risks`, `/aria/documents` — main views.
- `/aria/ask` — RAG-style "Ask ARIA" against indexed policy + control text.
- `/aria/api/*` — JSON CRUD.

## Tables

`aria_*` prefix. Notable: `aria_frameworks` (legacy — migrating to shared
`frameworks`), `aria_controls`, `aria_control_mappings`, `aria_policies`,
`aria_risks`, `aria_documents`.

## Events

Emits:
- `aria.policy.published`, `aria.policy.updated`
- `aria.risk.created`, `aria.risk.escalated`
- `aria.control.updated`

Handles:
- GRID audit/finding events → re-evaluate affected controls.

## Files

| File | Role |
|---|---|
| `routes.py` | All HTTP routes (~2,000 lines — split candidate) |
| `data_service.py` | DB CRUD |
| `ai_service.py` / `ask_service.py` | Policy generation + RAG |
| `templates/index.html` | SPA |
