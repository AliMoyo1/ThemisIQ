# Sentinel — Privacy & Data Protection

Ported from a standalone Data Protection Sentinel app. Covers RoPA, DPIA,
breaches, DSRs, consent, retention, vendors with DPAs, notices, transfers,
legitimate interest assessments, and security measures. Jurisdiction-aware
across 27 regulations.

## Mounts

- `/sentinel/` — SPA.
- `/sentinel/api/*` — JSON CRUD for all 14 entity types.
- `/sentinel/api/breaches`, `/sentinel/api/dsr`, etc.
- `/sentinel/api/vendors/{id}/cross-module` — cross-module vendor profile.

## Tables

`sentinel_*` prefix. Notable: `sentinel_ropa`, `sentinel_dpias`,
`sentinel_breaches`, `sentinel_dsr`, `sentinel_vendors`, `sentinel_consent`,
`sentinel_retention`, `sentinel_transfers`, `sentinel_security_measures`,
`sentinel_lias`, `sentinel_notices`, `sentinel_jurisdiction_config`.

## Jurisdictions

`jurisdictions.py` is the registry — 27 jurisdictions (GDPR, ZW CDPA, UK GDPR,
LGPD, CCPA, …) with `breach_hours`, `authority`, `authority_short`,
`breach_note`, `dsr_days`, and notification language. Per-org config lives
in `sentinel_jurisdiction_config` with `is_active` and `is_primary` flags.

`data_service._primary_jurisdiction_key()` returns the primary; defaults to
`settings.DEFAULT_REGULATION` when none is set.

## Events

Emits:
- `sentinel.breach.confirmed` — payload includes `regulation` and
  `active_jurisdictions`. Drives cross-module ERM obligation rows, ERM risk,
  ORM event, and GRID post-incident audit — all jurisdiction-aware.
- `sentinel.breach.resolved`, `sentinel.dpia.completed`, `sentinel.dsr.overdue`
- `vendor.created`

## Files

| File | Role |
|---|---|
| `routes.py` | HTTP + JSON routes (~1,500 lines) |
| `data_service.py` | DB CRUD for 14 entity types |
| `jurisdictions.py` | Per-jurisdiction rule table |
| `scheduler.py` | Breach 72h monitor, DSR deadlines, retention review |
| `ai_service.py` | AI-assisted DPIA / RoPA / breach analysis |
| `templates/index.html` | SPA (~3,200 lines) |

## Notes

- Every new entity defaults its `regulation` field to the primary jurisdiction
  if none is provided. See `data_service._primary_jurisdiction_key`.
- Breach modal pre-selects the primary jurisdiction in the dropdown.
