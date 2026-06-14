# ORM — Operational Risk Management

The operational layer: events, KRIs (key risk indicators), RCSA (risk and
control self-assessment), and SLA tracking. KRIs can auto-update when their
configured event type fires.

## Mounts

- `/orm/` — dashboard.
- `/orm/events`, `/orm/kris`, `/orm/rcsa`, `/orm/chat`.
- `/orm/api/*` — JSON CRUD.

## Tables

`orm_*` prefix. Notable: `orm_events`, `orm_kris`, `orm_kri_history`,
`orm_rcsa`, `orm_chat`.

`orm_kris` has `auto_update_event_type` + `auto_update_notes` columns that
let a KRI auto-increment when an event of the configured type fires.

## Events

Emits:
- `orm.event.logged`, `orm.event.elevated`, `orm.event.resolved`

Handles:
- `sentinel.breach.confirmed` → ORM event titled `[<regulation>] Data Breach: <title>`.
- `bcm.incident.declared` → ORM event.
- Auto-update: any matching event type bumps the linked KRI value via the
  `orm_event_logged_handler`.

## Files

| File | Role |
|---|---|
| `routes.py` | HTTP + JSON routes |
| `data_service.py` | DB CRUD, KRI history, workflow, SLA |
| `templates/index.html` | SPA |
