# ERM — Enterprise Risk Management

The strategic risk layer. Holds the enterprise risk register, risk appetite
thresholds, the risk library, and regulatory obligations.

## Mounts

- `/erm/` — dashboard.
- `/erm/risks`, `/erm/appetite`, `/erm/library`, `/erm/obligations`,
  `/erm/assessments`.
- `/erm/api/*` — JSON CRUD.

## Tables

`erm_*` prefix. Notable: `erm_enterprise_risks`, `erm_risk_appetite`,
`erm_risk_library`, `erm_regulatory_obligations`, `erm_assessments`.

Also reads the shared `risk_register` table (cross-module view).

## Events

Emits:
- `erm.risk.identified`, `erm.risk.escalated`, `erm.risk.mitigated`,
  `erm.risk.closed`
- `erm.appetite.breached`
- `erm.scenario.created`, `erm.scenario.updated`, `erm.scenario.published`
  (a board pack was published)

Handles:
- `sentinel.breach.confirmed` → creates jurisdiction-aware obligation row(s)
  in `erm_regulatory_obligations` and elevates to ERM risk register.
- `bcm.risk.escalated`, `aria.risk.escalated` → enterprise risk row.
- `orm.event.elevated` → enterprise risk row.

## Files

| File | Role |
|---|---|
| `routes.py` | HTTP + JSON routes |
| `data_service.py` | DB CRUD |
| `templates/index.html` | SPA |

## Notes

- `erm_regulatory_obligations.regulator` and `.regulation_name` are TEXT;
  they store whatever authority + regulation name the source event provided.
  Jurisdiction-aware breach handlers in `core.event_handlers` populate these
  from `sentinel.jurisdictions.JURISDICTION_RULES`.

## Scenario Studio

`/erm/scenario-studio`. What-if analysis: define a scenario, pick the affected risks, controls, indicators, objectives
and external context, set what changes, read the effect against today, brief the board with a frozen pack.

- `scenarios.py` is the calculation (pure, reproducible) and board packs. `scenario_support.py` is everything around it:
  the headline sentence, the unit scoped candidate picker, read only context from ORM, tasks, the BCM hand off and
  modelling a scenario on an incident. `scenario_ai.py` holds the five AI proposals. `scenario_templates.py` is the
  starter data. See `plans/2026-10-scenario-studio/plan.md`.
- AI never changes a number: each proposal is validated (ids must have been offered, scores pass the engine's own
  validation, citations must exist in the result) and accepted item by item. Accepted shocks carry `source` and
  `reason` inside the delta. Features: `erm.scenario_draft`, `_shocks`, `_gaps`, `_explain`, `_challenge`.
- A scenario is a related record (`("erm", "scenario")` in `governance/entity_scope.py`): Related Items, Evidence Vault
  links (`/evidence/?attach=erm:scenario:ID`), global search and My Work (owner review).
- Literal paths under `/erm/api/scenarios/` (`candidates`, `seed`, `ai/draft`) are registered before
  `/api/scenarios/{scenario_id}`.
