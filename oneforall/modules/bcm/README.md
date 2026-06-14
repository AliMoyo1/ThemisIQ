# BCM — Business Continuity Management

Manage business impact analyses, continuity plans, incidents, exercises,
training, vendors, the dependency graph, and a chat-style incident console.

## Mounts

- `/bcm/` — dashboard.
- `/bcm/bia`, `/bcm/plans`, `/bcm/incidents`, `/bcm/exercises`, `/bcm/vendors`,
  `/bcm/training`, `/bcm/documents`, `/bcm/dependencies`.
- `/bcm/api/*` — JSON CRUD.
- `/bcm/api/vendors/{id}/cross-module` — cross-module vendor profile.

## Tables

`bcm_*` prefix. Notable: `bcm_bia`, `bcm_plans`, `bcm_incidents`,
`bcm_incident_chat`, `bcm_exercises`, `bcm_vendors`, `bcm_training`,
`bcm_documents`, `bcm_dependencies`, `bcm_plan_reviews`, `bcm_risks`.

## Events

Emits:
- `bcm.incident.declared`, `bcm.incident.resolved`, `bcm.risk.escalated`
- `bcm.plan.approved`, `bcm.plan.activated`, `bcm.plan.deactivated`
- `vendor.created`

Handles:
- `sentinel.breach.confirmed` → may mark related vendor as elevated risk

## Files

| File | Role |
|---|---|
| `routes.py` | HTTP + JSON routes |
| `data_service.py` | DB CRUD |
| `scheduler.py` | Plan-review cron, exercise alerts, training reminders |
| `ai_service.py` | Plan generation assistance |
| `templates/index.html` | SPA |

## Notes

- Incidents have a "command console" with live chat (`bcm_incident_chat`).
- Vendor `tier` and `criticality` drive cross-module risk flags in the unified
  vendor directory.
