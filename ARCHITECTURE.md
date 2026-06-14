# One For All — Unified Compliance Platform

## Architecture Plan

### Overview

One For All merges four standalone compliance tools into a single FastAPI monolith with a unified SQLite database, capability-based RBAC, cross-module event propagation, and per-module themed frontends.

### Source Tools

| Module | Internal Name | Original Stack | Purpose |
|--------|--------------|----------------|---------|
| ARIA | `aria` | Python/FastAPI | GRC — policies, controls, 7 frameworks, cross-mapping |
| GRID | `grid` | Node/Express | Audit management, AI checklist parsing, evidence, gap analysis |
| BCM | `bcm` | Node/Express | Business continuity, BIA, risk, incidents, exercises |
| Sentinel | `sentinel` | Python/Flask | Data protection, RoPA, DPIA, breaches, DSR, consent |

### Tech Stack (Unified)

- **Backend:** Python 3.10+ / FastAPI
- **Database:** SQLite (single file, WAL mode)
- **Templates:** Jinja2 (each module keeps its own theme)
- **AI:** Anthropic Claude API (shared service layer)
- **Auth:** bcrypt password hashing, secure session tokens (httponly cookies)
- **Exports:** python-docx, openpyxl, reportlab (PDF)
- **Email:** SMTP via aiosmtplib
- **Deployment:** Windows laptop, single `START.bat`

---

## Project Structure

```
oneforall/
├── main.py                    # FastAPI app entry point, mounts all routers
├── config.py                  # Environment config (.env loading)
├── database.py                # Unified DB init, connection helpers
├── START.bat                  # Windows launcher
├── requirements.txt
├── .env.example
│
├── core/                      # Shared infrastructure
│   ├── auth.py                # Login, logout, session management
│   ├── rbac.py                # Unified RBAC: roles, capabilities, checks
│   ├── events.py              # Cross-module event bus
│   ├── ai_service.py          # Shared Anthropic Claude integration
│   ├── email_service.py       # SMTP email
│   ├── export_docx.py         # Word export helpers
│   ├── export_xlsx.py         # Excel export helpers
│   ├── export_pdf.py          # PDF export helpers
│   └── middleware.py          # Security headers, CSRF, rate limiting
│
├── models/                    # SQLAlchemy-style table definitions
│   ├── base.py                # Shared tables (users, roles, audit_log, events)
│   ├── aria.py                # ARIA tables (frameworks, controls, documents, risks, evidence)
│   ├── grid.py                # GRID tables (audits, controls, evidence, timeline, reminders)
│   ├── bcm.py                 # BCM tables (bia, risks, plans, incidents, exercises, vendors)
│   └── sentinel.py            # Sentinel tables (ropa, dpia, breaches, dsr, consent, vendors)
│
├── modules/
│   ├── launcher/              # Gateway/launcher (post-login module picker)
│   │   ├── routes.py
│   │   └── templates/
│   │       └── launcher.html
│   │
│   ├── aria/                  # ARIA module
│   │   ├── routes.py          # All ARIA endpoints under /aria/
│   │   ├── services.py        # Business logic
│   │   └── templates/         # Jinja2 templates (cream/olive theme)
│   │       ├── base.html
│   │       ├── dashboard.html
│   │       ├── framework.html
│   │       ├── documents.html
│   │       ├── risks.html
│   │       ├── mapping.html
│   │       ├── ai_generator.html
│   │       ├── ask.html
│   │       └── audit_log.html
│   │
│   ├── grid/                  # GRID (AuditSphere) module
│   │   ├── routes.py
│   │   ├── services.py
│   │   └── templates/         # (green/white theme)
│   │       ├── base.html
│   │       ├── dashboard.html
│   │       ├── audit_detail.html
│   │       ├── controls.html
│   │       ├── evidence.html
│   │       └── gap_analysis.html
│   │
│   ├── bcm/                   # BCM Sentinel module
│   │   ├── routes.py
│   │   ├── services.py
│   │   └── templates/         # (cream/olive dark-sidebar theme)
│   │       ├── base.html
│   │       ├── dashboard.html
│   │       ├── bia.html
│   │       ├── risks.html
│   │       ├── plans.html
│   │       ├── incidents.html
│   │       ├── exercises.html
│   │       └── vendors.html
│   │
│   └── sentinel/              # Data Protection Sentinel module
│       ├── routes.py
│       ├── services.py
│       └── templates/         # (dark cyberpunk/navy theme)
│           ├── base.html
│           ├── dashboard.html
│           ├── ropa.html
│           ├── dpia.html
│           ├── breaches.html
│           ├── dsr.html
│           ├── consent.html
│           └── vendors.html
│
├── static/                    # Shared static assets
│   ├── css/
│   │   ├── shared.css         # Reset, typography, shared components
│   │   ├── launcher.css       # Launcher theme
│   │   ├── aria.css           # ARIA cream/olive theme
│   │   ├── grid.css           # GRID green/white theme
│   │   ├── bcm.css            # BCM cream/dark-sidebar theme
│   │   └── sentinel.css       # Sentinel dark/cyber theme
│   ├── js/
│   │   ├── shared.js          # Common utilities
│   │   └── charts.js          # Chart.js helpers
│   └── img/
│       └── logo.svg
│
├── data/                      # Database file location
│   └── oneforall.db
│
└── seeds/                     # Seed data scripts
    └── seed.py                # Create default admin, frameworks, demo data
```

---

## Unified RBAC System

### Platform Roles

Users are assigned one or more roles. Each role grants a set of capabilities.

| Role | Scope | Description |
|------|-------|-------------|
| `super_admin` | Platform | Full access to everything, user management |
| `compliance_manager` | ARIA | Manages policies, controls, risks across all frameworks |
| `policy_author` | ARIA | Drafts and edits policies |
| `policy_approver` | ARIA | Reviews and approves policies |
| `control_owner` | ARIA | Updates assigned controls |
| `risk_owner` | ARIA + BCM | Updates assigned risks |
| `audit_lead` | GRID | Creates and manages audits |
| `auditor` | GRID | Works on assigned audit controls and evidence |
| `bcm_manager` | BCM | Manages BIA, plans, exercises |
| `incident_commander` | BCM | Manages incident response |
| `bcm_responder` | BCM | Updates incidents, executes plans |
| `dpo` | Sentinel | Full data protection officer access |
| `privacy_analyst` | Sentinel | Manages RoPA, DPIA, DSR |
| `employee` | All | Read-only on approved content, can use AI assistants |
| `external_auditor` | ARIA + GRID | Read-only access to controls, evidence, audit logs |

### Module Access Matrix

| Role | ARIA | GRID | BCM | Sentinel | Launcher |
|------|------|------|-----|----------|----------|
| super_admin | Full | Full | Full | Full | Full |
| compliance_manager | Full | Read | Read | Read | Yes |
| policy_author | Write | — | — | — | Yes |
| policy_approver | Approve | — | — | — | Yes |
| control_owner | Own | — | — | — | Yes |
| risk_owner | Own | — | Own | — | Yes |
| audit_lead | Read | Full | — | — | Yes |
| auditor | Read | Write | — | — | Yes |
| bcm_manager | Read | — | Full | — | Yes |
| incident_commander | — | — | Incidents | — | Yes |
| bcm_responder | — | — | Write | — | Yes |
| dpo | Read | Read | — | Full | Yes |
| privacy_analyst | — | — | — | Write | Yes |
| employee | Read | — | Read | — | Yes |
| external_auditor | Read | Read | — | — | Yes |

### Capability System

Capabilities are atomic permissions. Roles map to sets of capabilities.

```
# Module access
module.aria.access, module.grid.access, module.bcm.access, module.sentinel.access

# ARIA capabilities
aria.policy.create, aria.policy.edit_own, aria.policy.edit_any, aria.policy.approve
aria.policy.delete, aria.policy.generate_ai
aria.control.update_own, aria.control.update_any
aria.risk.add, aria.risk.update_own, aria.risk.update_any
aria.framework.view, aria.documents.export, aria.audit_log.view
aria.ask_ai

# GRID capabilities
grid.audit.create, grid.audit.edit, grid.audit.delete
grid.control.assign, grid.control.update_own, grid.control.update_any
grid.evidence.upload, grid.evidence.approve, grid.evidence.delete
grid.ai.parse_checklist, grid.ai.gap_analysis, grid.ai.report
grid.reminder.manage

# BCM capabilities
bcm.bia.manage, bcm.risk.manage
bcm.plan.create, bcm.plan.edit, bcm.plan.approve
bcm.incident.declare, bcm.incident.manage, bcm.incident.update
bcm.exercise.manage, bcm.vendor.manage
bcm.report.generate, bcm.ai.chat

# Sentinel capabilities
sentinel.ropa.manage, sentinel.dpia.manage
sentinel.breach.manage, sentinel.dsr.manage
sentinel.consent.manage, sentinel.vendor.manage
sentinel.privacy_notice.manage, sentinel.controller.manage
sentinel.transfer.manage, sentinel.retention.manage
sentinel.ai.assess
```

---

## Cross-Module Event System

An internal event bus propagates changes between modules. Events are stored in an `events` table and processed synchronously (or via background worker).

### Event Flows

```
ARIA Policy Published/Updated
  → GRID: Flag related audit controls for re-review
  → Sentinel: Flag affected DPIAs for re-assessment
  → BCM: Update linked BCP plan review status

ARIA Risk Created/Escalated
  → BCM: Create/update corresponding risk in BCM risk register
  → Sentinel: Notify if risk relates to data processing

BCM Incident Declared (SEV1/SEV2)
  → Sentinel: Auto-create breach assessment draft
  → ARIA: Flag related controls as potentially impacted

Sentinel Breach Confirmed
  → BCM: Create incident if not already linked
  → ARIA: Flag related framework controls for review
  → GRID: Create audit finding for breach response

Sentinel DPIA Completed
  → ARIA: Update related controls with DPIA reference

GRID Audit Finding (Non-conformance)
  → ARIA: Create corrective action on related control
  → BCM: Flag if finding impacts continuity plans

Any Module — Risk Register Change
  → Unified risk dashboard aggregates from all modules
```

### Event Table Schema

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,         -- e.g. 'aria.policy.published'
    source_module TEXT NOT NULL,      -- 'aria', 'grid', 'bcm', 'sentinel'
    source_entity_type TEXT,          -- 'policy', 'risk', 'incident', etc.
    source_entity_id INTEGER,
    payload TEXT,                     -- JSON blob with event details
    status TEXT DEFAULT 'pending',    -- 'pending', 'processed', 'failed'
    created_by INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT
);
```

---

## Database Schema (Unified)

Single SQLite file: `data/oneforall.db`

### Shared Tables

- `users` — unified user accounts
- `user_roles` — many-to-many user ↔ role mapping
- `sessions` — active login sessions
- `audit_log` — platform-wide audit trail
- `events` — cross-module event bus
- `notifications` — user notifications from events
- `settings` — platform configuration (AI keys, SMTP, etc.)

### Per-Module Tables (prefixed)

- **ARIA:** `aria_frameworks`, `aria_controls`, `aria_documents`, `aria_risks`, `aria_evidence`
- **GRID:** `grid_audits`, `grid_controls`, `grid_evidence_items`, `grid_evidence_files`, `grid_timeline`, `grid_reminders`, `grid_ai_suggestions`, `grid_non_conformances`
- **BCM:** `bcm_bia_records`, `bcm_risks`, `bcm_plans`, `bcm_incidents`, `bcm_incident_updates`, `bcm_exercises`, `bcm_vendors`, `bcm_vendor_assessments`, `bcm_compliance_controls`, `bcm_compliance_evidence`, `bcm_dependencies`
- **Sentinel:** `sentinel_ropa`, `sentinel_dpias`, `sentinel_breaches`, `sentinel_dsr`, `sentinel_vendors`, `sentinel_privacy_notices`, `sentinel_consent`, `sentinel_controllers`, `sentinel_transfers`, `sentinel_retention`, `sentinel_security_measures`

---

## Build Phases

### Phase 1 — Foundation (This Session)
- Project skeleton and folder structure
- Unified database with shared tables + all module tables
- RBAC system (roles, capabilities, middleware)
- Auth (login, logout, session management)
- Launcher/gateway UI (module picker based on user roles)
- Security middleware (CSRF, headers, rate limiting)
- START.bat for Windows

### Phase 2 — Port ARIA Module
- Migrate ARIA routes from FastAPI to new structure
- Adapt templates to work under /aria/ prefix
- Preserve cream/olive theme
- Wire up event emission for policy/control/risk changes

### Phase 3 — Port Sentinel Module
- Rewrite Flask routes as FastAPI
- Migrate templates (already Jinja2-compatible)
- Preserve dark cyberpunk theme
- Wire up breach/DPIA event handling

### Phase 4 — Port GRID Module
- Rewrite Node/Express routes as FastAPI
- Convert EJS-like templates to Jinja2
- Preserve green/white theme
- Wire up audit finding events

### Phase 5 — Port BCM Module
- Rewrite Node/Express routes as FastAPI
- Convert EJS templates to Jinja2
- Preserve cream/dark-sidebar theme
- Wire up incident/risk events

### Phase 6 — Full Mesh Integration
- Implement all cross-module event handlers
- Unified risk dashboard
- Unified search across modules
- Aggregated notifications
- Platform-wide reporting

---

## Security Considerations

- Passwords hashed with bcrypt (cost factor 12)
- Session tokens: cryptographically random, httponly, secure, samesite=strict
- CSRF protection on all state-changing endpoints
- Input sanitisation on all user inputs
- SQL parameterised queries only (no string interpolation)
- Rate limiting on login endpoint
- Security headers (X-Frame-Options, CSP, etc.)
- File upload validation (type, size, path traversal prevention)
- Audit logging of all sensitive actions
- No secrets in source code (.env file)
