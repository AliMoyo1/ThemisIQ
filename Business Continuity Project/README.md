# BCM Sentinel — By Ali Moyo

A multi-tenant Business Continuity Management SaaS platform with an AI copilot, Business Impact Analysis, Risk Register, Continuity Plans, Incident Management, Vendor & Third-Party Risk, Tabletop Exercises with After-Action Reports, ISO 22301 compliance mapping with an evidence repository, a SOC 2-grade audit log, and email reminders.

## Stack

- Node.js 22+ (uses the built-in `node:sqlite` module — no native compilation)
- Express + EJS with a custom cream/olive + dark-sidebar theme
- SQLite single-file database, created automatically at first run
- Nodemailer for SMTP email
- node-cron for scheduled reminder sweeps
- OpenAI and/or Anthropic for the AI copilot (configurable per tenant)

## Quick start

On Windows, the simplest path is to double-click `start.bat` — it installs dependencies, seeds the demo workspace on first run, and starts the server.

Otherwise:

```bash
# 1. Install dependencies
npm install

# 2. Configure environment
cp .env.example .env
# Edit .env and fill in SMTP + AI keys (optional — the app works without them)

# 3. Seed a demo tenant (optional but recommended)
npm run seed

# 4. Run the server
npm start
# or for auto-reload:
npm run dev
```

Open http://localhost:3000.

If you ran the seed:
- Email: `demo@acme.test`
- Password: `demo12345`

## What's included (Phase 1 MVP)

### Multi-tenant SaaS foundations
- Sign up as an organization, which creates a tenant
- Users scoped to a tenant with roles: `admin`, `manager`, `responder`, `viewer`
- Invite teammates from Settings → Team
- Every domain query is scoped by `tenant_id`

### Core BCM modules
- **Business Impact Analysis** — processes, RTO/RPO, financial/operational/reputational/regulatory impact, auto-computed criticality
- **Risk Register** — likelihood × impact scoring, treatment, owner, due date, mitigation
- **Continuity Plans (BCP/DRP)** — versioned plans with status, scope, owner, last/next review, Markdown content
- **Incidents** — declare with severity (SEV1–4), status workflow (open → investigating → mitigated → resolved → closed), timeline of updates, auto-notifies admins via email on declaration

### Dashboard
- KPI tiles: BIA records, open risks, active plans, open incidents
- Recent activity across modules
- Continuity Pulse — aggregate readiness score (plan coverage, risk posture, incident health, review freshness, BIA coverage, readiness)
- Upcoming plan reviews
- Overdue risk mitigations
- Quick actions

### AI copilot
- **Chatbot** — persistent conversation history per user, answers BCM questions, cites standards
- **AI Plan Generator** — describe scope and scenario → receive a full Markdown BCP draft → one-click save into the BCP library
- **Provider abstraction** — OpenAI or Anthropic, selectable per tenant in Settings. If no key is configured, returns a helpful stub answer so the UI keeps working during development.

### Phase 2: Resilience modules
- **Vendors / Third-Party Risk** — categorised register with tiers (1–5), four risk dimensions (financial, operational, compliance, concentration), auto-computed criticality and risk score, SLA and contract renewal tracking, assessment snapshots, and a review cadence that surfaces on the dashboard.
- **Exercises** — tabletops, walkthroughs, simulations, and full-scale tests with linked continuity plans, scheduled date, duration, facilitator, participants, objectives, outcome, and an after-action report (strengths, gaps, follow-up actions).
- **Compliance (ISO 22301)** — pre-seeded clause catalog (clauses 4.1 through 10.2), four-state status (not started → in progress → implemented → verified), owner assignment, review cadence, per-clause evidence repository with URL + notes, and an overall maturity %.
- **Audit log** — tenant-scoped, tamper-evident trail of CREATE / UPDATE / DELETE / LOGIN / LOGOUT / EXPORT events. Filterable by action, entity, user, and date range. Admins and managers can export to CSV for SOC 2 evidence.

### Phase 3: People & Knowledge modules
- **Training & Attestation** — publish Markdown training modules with categories, required roles, durations, renewal cadence (e.g. annual), and a passing score. Users sign attestations by typing their full name; each signing captures timestamp, score, IP, and user-agent for audits. Attestations have expiry dates so renewals surface automatically, and admins can view/export the full log.
- **Document Q&A (RAG)** — upload BCP plans, policies, runbooks, and contracts (paste text, or copy from the plan editor). The platform chunks the text into sentence-aware ~600-character windows with 80-char overlap, indexes each chunk, and answers questions using BM25-style retrieval plus the tenant's configured AI provider. Every answer comes back with `[Source N]` citations you can click through to the original chunk. Works without an AI key (stub replies with real citations) and upgrades to live answers when OpenAI or Anthropic is configured.
- **Dependency Graph** — map processes, systems, vendors, sites, teams, assets, and data as nodes connected by directed edges (depends_on / feeds / hosts / supports / fails_over_to). Rendered with vis-network from CDN — pan, zoom, click a node for its impact page. BFS over outgoing edges shows downstream blast radius; a reverse walk shows upstream dependencies.

### Email notifications (SMTP)
- Incident declared → admins emailed immediately with severity, title, description, and a deep link
- BCP review reminders → emailed 7 days before the `next_review` date and again on the due date
- Risk mitigation reminders → emailed on the risk's `due_date`
- Test-email button in Settings → Notifications
- Reminders live in a `reminders` table and are swept every minute by node-cron
- Nightly job re-scans all plans and risks to refresh upcoming reminders

### Theme
- Cream page background (`#b0ac8f` outer, `#f4f1e8` inner)
- Near-black sidebar with soft rounded active state
- Olive/sage accents, serif display font (Cormorant Garamond) for headings, Inter for UI
- Rounded 18px cards with subtle shadows
- Responsive down to mobile (sidebar collapses to icon rail)

## Folder layout

```
├── server.js                    # Express app + scheduler bootstrap
├── package.json
├── .env / .env.example          # SMTP + AI keys
├── models/
│   └── db.js                    # SQLite + schema migrations
├── middleware/
│   └── auth.js                  # requireAuth / requireRole
├── routes/
│   ├── auth.js                  # signup / login / logout
│   ├── dashboard.js
│   ├── bia.js / risks.js / bcp.js / incidents.js
│   ├── chatbot.js / plan_generator.js
│   └── settings.js
├── services/
│   ├── ai.js                    # OpenAI + Anthropic adapter
│   ├── mailer.js                # Nodemailer + HTML email templates
│   └── scheduler.js             # cron sweep + reminder seeders
├── views/                       # EJS templates + partials
├── public/
│   ├── css/theme.css
│   └── js/app.js
├── data/
│   └── bcm.db                   # SQLite file (auto-created)
└── scripts/
    └── seed.js                  # Demo tenant + realistic data
```

## Configuration

`.env` keys:

| Key | Purpose |
| --- | --- |
| `SESSION_SECRET` | Session signing secret. Use a long random string in production. |
| `PORT` | HTTP port (default 3000) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM` | Email reminder transport |
| `AI_DEFAULT_PROVIDER` | Fallback provider if a tenant hasn't chosen (`openai` or `anthropic`) |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | Global OpenAI credentials |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | Global Anthropic credentials |
| `APP_NAME` | Branded name shown in UI + emails |
| `APP_URL` | Used in email deep links |

Tenants can override AI keys per-workspace in Settings → AI.

## Security notes

- Passwords are stored as bcrypt hashes
- Session cookies expire after 7 days
- Every domain table carries a `tenant_id` column and all queries scope by the session's tenant
- Delete operations cascade via SQLite foreign keys
- **Rotate the Gmail app password** from the `.env` after first deploy, since it may have been shared during development
- For production: put the app behind HTTPS, set `cookie: { secure: true }` on the session, switch to a persistent session store (e.g. `connect-sqlite3`), and move secrets into a secrets manager

## Roadmap (Phase 2+)

Feature backlog that's ready to build on top of this foundation:

- Mass notification / SMS alerting via Twilio
- Mobile-responsive PWA for responders
- Stripe billing + plan tiers
- Public API + webhooks

## Commands

```bash
npm start      # Production run
npm run dev    # Auto-reload (Node 20+)
npm run seed   # Create demo tenant with realistic data
```
