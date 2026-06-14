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
