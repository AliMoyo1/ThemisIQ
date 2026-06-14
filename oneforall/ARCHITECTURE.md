# ThemisIQ / One For All — Architecture

A single-binary, multi-module GRC (Governance, Risk, Compliance) platform. One
SQLite database, one FastAPI app, eight functional modules, a cross-module
event bus, and a canonical-entity layer that lets the modules share identities
without giving up their domain-specific schemas.

## Tech stack

| Layer | Choice |
|---|---|
| Web | FastAPI + Uvicorn |
| Templates | Jinja2 (server-rendered, with embedded fetch-based SPAs per module) |
| DB | SQLite (WAL, parametrised queries, runtime migrations) |
| Auth | bcrypt (cost 12), session cookies (HttpOnly, SameSite=Strict), CSRF token + origin check, per-IP login throttle |
| AI | Multi-provider abstraction (Anthropic, OpenAI, Gemini, DeepSeek, Ollama) |
| Scheduling | APScheduler (background jobs per module) |
| Email | SMTP / Microsoft Graph / console |

## Repo layout

```
oneforall/
├── main.py                # FastAPI app, startup/shutdown, /health, /ready
├── config.py              # Env-driven Settings (single source of truth)
├── database.py            # Schema, migrations, get_db(), get_db_background()
├── core/
│   ├── auth.py            # Sessions, bcrypt
│   ├── middleware.py      # require_auth, CSRF, rate-limit, security headers
│   ├── rbac.py            # Capability map, has_capability(), user_modules()
│   ├── events.py          # Pub/sub bus + event-name constants
│   ├── event_handlers.py  # Registered cross-module handlers
│   ├── links.py           # cross_module_links read/write
│   ├── vendor_link.py     # Canonical vendor identity + directory
│   ├── framework_service.py  # Unified frameworks/controls
│   ├── predictive_risk.py # Multi-domain risk score
│   ├── timeutils.py       # utcnow() helper (replaces deprecated datetime.utcnow)
│   ├── email.py
│   ├── reminder_scheduler.py
│   └── shell_context.py
├── modules/
│   ├── launcher/   # Command Centre, dashboards, admin, vendor directory
│   ├── aria/       # Governance — frameworks, controls, policies
│   ├── grid/       # Audit — audits, findings, controls, vendor assessments
│   ├── bcm/        # Resilience — BIA, plans, incidents, exercises, vendors
│   ├── sentinel/   # Privacy — RoPA, DPIA, breaches, DSR, vendors, consent
│   ├── erm/        # Enterprise risk — risks, appetite, obligations
│   ├── orm/        # Operational risk — events, KRIs, RCSA
│   └── evidence/   # Cross-module evidence vault
├── seeds/          # Initial frameworks, controls, mappings
├── templates/      # Cross-cutting shells (base_shell, command_centre)
├── static/         # JS, CSS, images
├── tests/          # pytest suite
└── data/           # SQLite DB at runtime
```

## Modules at a glance

Each module is a self-contained vertical: its own `routes.py`, `data_service.py`,
optional `scheduler.py`, `ai_service.py`, and Jinja templates. Modules import
from `core/` but never from each other directly — they coordinate via the
event bus.

| Module | Purpose | Owns tables prefixed | Mounts on |
|---|---|---|---|
| launcher | Cross-module shell, dashboards, admin, platform vendor directory | (none — uses shared tables) | `/`, `/admin/*`, `/vendors`, `/tasks`, `/workflows` |
| aria | Governance & compliance frameworks | `aria_*` | `/aria/*` |
| grid | Audit management | `grid_*` | `/grid/*` |
| bcm | Business continuity management | `bcm_*` | `/bcm/*` |
| sentinel | Privacy & data protection | `sentinel_*` | `/sentinel/*` |
| erm | Enterprise risk | `erm_*`, `risk_register` (shared view) | `/erm/*` |
| orm | Operational risk | `orm_*` | `/orm/*` |
| evidence | Evidence vault | `evidence_items` | `/evidence/*` |

## Cross-cutting data layers

Three small tables hold the platform together:

### 1. `canonical_vendors` — shared vendor identity

Each module has its own vendor table (`sentinel_vendors`, `grid_vendors`,
`bcm_vendors`) keyed to a row in `canonical_vendors` via `canonical_id`. This
lets the Privacy team store DPA fields, GRID store assessment scores, and BCM
store criticality/SLA — without losing the link between them.

Dedup is enforced by a UNIQUE index on `lower(trim(name))`. The flow:

1. Module's `create_vendor()` calls `core.vendor_link.ensure_canonical(db, name)`.
2. `ensure_canonical` returns an existing id or creates a new one; if it loses
   an INSERT race it catches the IntegrityError and re-SELECTs.
3. The module stores the returned id in its own `canonical_id` column.
4. `get_vendor_directory()` joins all three module tables on `canonical_id`
   to build the platform-wide vendor view (Command Centre → Vendor Directory).

### 2. `cross_module_links` — generic relationships

Whenever one module raises an artifact in another (breach → ERM risk, audit
finding → ARIA policy, BCM incident → ORM event), the relationship is recorded
in `cross_module_links` so both ends can show "linked items".

Schema: `(source_module, source_type, source_id, target_module, target_type,
target_id, relationship)`. A UNIQUE index on that tuple makes
`create_cross_module_link()` idempotent via `INSERT OR IGNORE`.

Valid `source_module` / `target_module` values: `aria`, `grid`, `bcm`,
`sentinel`, `platform`, `evidence`, `erm`, `orm`.

Valid `relationship` values: `related`, `triggers`, `evidence_for`,
`implements`, `mitigates`, `escalated_to`, `derived_from`, `audits`,
`elevated_to`.

### 3. `events` — audit log of cross-module signals

Every `emit()` writes a row to `events` for replay/observability. Synchronous
handlers fire inline; failures are logged but don't block the source operation.

## Event catalog

Defined in `core/events.py`, handled in `core/event_handlers.py`. Payload is
always a dict and varies per event; see the handler for the contract.

| Event | Emitted when | Notable cross-module effects |
|---|---|---|
| `aria.policy.published` | ARIA policy goes live | GRID may flag audits for re-review |
| `aria.policy.updated` | Policy version bump | Notifies relevant audit/control owners |
| `aria.risk.created` | New risk in ARIA register | May surface in ERM register |
| `aria.risk.escalated` | Risk severity bumped | ERM risk row created/updated |
| `aria.control.updated` | Control status change | GRID audit findings revalidated |
| `grid.audit.completed` | Audit closed | ARIA control statuses refreshed |
| `grid.finding.created` | New finding | ARIA control flagged, task created |
| `grid.non_conformance.raised` | NC raised | Escalates to ERM if critical |
| `grid.policy.requested` | Audit needs missing policy | ARIA notified |
| `bcm.incident.declared` | BCM incident started | ORM event created |
| `bcm.incident.resolved` | Incident closed | Linked ORM event resolved |
| `bcm.risk.escalated` | BCM risk severity bumped | ERM risk row |
| `bcm.plan.approved` / `activated` / `deactivated` | Plan lifecycle | Audit + notifications |
| `sentinel.breach.confirmed` | Privacy breach confirmed | **Jurisdiction-aware** ERM obligation rows, ERM risk row, ORM event, GRID post-incident audit. Payload includes `regulation` and `active_jurisdictions` so handlers can reference the right authority + deadline. |
| `sentinel.breach.resolved` | Status → closed/resolved/contained | Linked ERM/ORM artifacts close |
| `sentinel.dpia.completed` | DPIA approved | Updates related controls |
| `sentinel.dsr.overdue` | DSR past deadline | ORM event, admin notification |
| `erm.risk.identified` | New ERM risk | Cross-module link to source |
| `erm.risk.escalated` | Severity bumped | Notifies owners |
| `erm.risk.mitigated` / `closed` | Risk lifecycle | Linked artifacts updated |
| `erm.appetite.breached` | KRI/threshold crossed | Admin notification |
| `orm.event.logged` | New op-risk event | KRI auto-increment if matching `auto_update_event_type` |
| `orm.event.elevated` | Event severity bumped | ERM risk row |
| `orm.event.resolved` | Event closed | Linked artifacts updated |

## Jurisdiction-aware privacy flow

Sentinel has a per-org `sentinel_jurisdiction_config` table that holds active
jurisdictions with `is_primary` flags. The registry of legal rules
(`modules/sentinel/jurisdictions.py`) maps each jurisdiction key to its
authority name, breach deadline hours, DSR deadline days, and notification
language.

When a breach is confirmed, the emitted event payload carries
`regulation` (the breach's own jurisdiction) and `active_jurisdictions` (every
org-active key). The handler in `event_handlers.py` groups those by deadline
hours and creates one `erm_regulatory_obligation` per group — same deadlines
combined with `|`, different deadlines split.

For records without an explicit regulation, `sentinel.data_service.
_primary_jurisdiction_key()` looks up the org's primary; if none is set,
fallback is `settings.DEFAULT_REGULATION` (env-configurable, defaults to
`GDPR`).

## Authentication & authorization

- Login is the only unauth POST endpoint. Sessions are random tokens stored
  as SHA-256 hashes in the `sessions` table; cookies are HttpOnly,
  SameSite=Strict, 24-hour max-age.
- `core.middleware.require_auth` — redirects to `/login` if no valid session.
  Also forces `/change-password` when `must_change_password=1`.
- `core.middleware.require_capability(*caps)` — gates by RBAC capability;
  401 → redirect, 403 → JSON if any capability matches.
- Capabilities live in `core/rbac.py` with role → capability mapping.
- CSRF: same-origin check on all POST/PUT/DELETE/PATCH **plus** a session
  CSRF token validated on form submissions.
- Rate limit: 5 failed logins / 5 minutes per IP (in-process).

## Deployment checklist

Before a production deploy, ensure:

1. `.env` is populated:
   - `SECRET_KEY` (required — app refuses to start without it unless `DEBUG=true`)
   - `DB_PATH` (defaults to `data/oneforall.db` next to source)
   - `ANTHROPIC_API_KEY` or alternative AI provider keys
   - SMTP / Microsoft Graph config for email delivery
   - `DEFAULT_REGULATION` if you want to override the GDPR fallback
   - `LOG_LEVEL` (defaults to INFO in production, DEBUG when DEBUG=true)
2. `DEBUG` is **not** set (or set to `false`).
3. SQLite file is on a fast local disk (not a network mount — WAL doesn't
   tolerate concurrent writers across hosts).
4. Behind HTTPS — the auth cookie does not set `Secure` automatically.
5. `python -m pytest` passes.
6. `/ready` returns 200 after migrations.
7. A canonical vendor de-dupe pass has been run if upgrading from a pre-UNIQUE
   schema (a startup warning identifies the duplicate names).

## Local development

```powershell
# 1. Install
python -m pip install -r requirements-dev.txt

# 2. Bootstrap env
copy .env.example .env  # then edit values
# At minimum: DEBUG=true (or set SECRET_KEY)

# 3. Run
python -m uvicorn main:app --reload --port 8000

# 4. Tests
python -m pytest
```

First-run startup auto-seeds an admin user and base frameworks via
`seeds/seed.py`.

## Performance notes

- `get_db()` returns a fresh connection per request with WAL, NORMAL sync,
  64 MB cache, and a 15-second busy timeout. Background jobs use
  `get_db_background()` with a 3-second timeout so they can never queue
  behind user writes.
- `get_vendor_directory()` does 4 queries regardless of vendor count
  (canonical + 3 batched per-module fetches indexed by `canonical_id`).
- Indexes cover `canonical_id` foreign keys, status/regulation filter
  columns, `audit_log(action, created_at)`, `task_board(assigned_to)`, and
  `email_reminders(remind_at, is_sent)`.

## Where things commonly go wrong

| Symptom | Likely cause | Where to look |
|---|---|---|
| Sessions reset every restart | Missing `SECRET_KEY` in `.env` | `config.py` `_resolve_secret_key` |
| Cross-module link duplicates | Old DB without the UNIQUE migration | startup logs for `Skipped index` warnings |
| Vendor directory shows two copies of same vendor | Duplicate `canonical_vendors` rows | run `SELECT lower(trim(name)), COUNT(*) FROM canonical_vendors GROUP BY 1 HAVING COUNT(*) > 1` |
| Breach notification cites the wrong authority | Missing or wrong `regulation` on the breach record | `sentinel.data_service._primary_jurisdiction_key`, or set `DEFAULT_REGULATION` |
| Sub-page sidebar missing items | Sidebar duplicated between `command_centre.html` and `platform_base.html` | both files have to be kept in sync — refactor target |
