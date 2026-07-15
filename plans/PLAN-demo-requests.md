# PLAN: Demo Request System

## Status: IN PROGRESS

## Scope

Build a proper demo request pipeline: persist every submission to the DB,
show a clear on-screen confirmation to the submitter, and give the super admin
a dashboard to view and manage all requests with analytics.

## Phase 1 — NOW (this session)

### 1. `demo_requests` table in `database.py` (`_SHARED_TABLES`)

```sql
CREATE TABLE IF NOT EXISTS demo_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    email        TEXT NOT NULL,
    company      TEXT,
    plan         TEXT,
    ip_address   TEXT,
    contacted    INTEGER DEFAULT 0,
    contacted_at TEXT,
    notes        TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_demo_requests_email   ON demo_requests(email);
CREATE INDEX IF NOT EXISTS idx_demo_requests_created ON demo_requests(created_at);
```

Added to `_SHARED_TABLES` (public schema, not per-tenant). Runs on both
SQLite (`init_db`) and Postgres (`init_db` + `provision_tenant_schema`
does NOT include this block - shared only).

### 2. `main.py` - persist before email

In `/api/demo-request`:
- Capture `ip_address = request.client.host`
- `INSERT INTO demo_requests (name, email, company, plan, ip_address) VALUES (...)`
- Commit
- Then try email (best-effort, never blocks the 200 response)

The DB write is the source of truth. Email delivery failure no longer loses the lead.

### 3. Super admin endpoints in `routes_super_admin.py`

- `GET /super-admin/api/demo-requests` - all requests, newest first
- `POST /super-admin/api/demo-requests/{id}/contacted` - mark contacted + timestamp
- `DELETE /super-admin/api/demo-requests/{id}` - delete spam/test submissions

### 4. Super admin UI in `super_admin.html`

New section below the Orgs table, with:

**Stat cards (4):**
- Total Requests (all time)
- This Week
- Pending (not yet contacted)
- Contacted

**Requests per day chart:**
- Simple SVG bar chart, last 14 days
- Bars coloured by contacted vs pending ratio

**Requests table:**
- Columns: Name, Email, Company, Plan, Date, Status badge, Actions
- Status badge: green Contacted / amber Pending
- Actions: Mark Contacted button, Delete (spam)
- Search/filter by status

### 5. Landing page `index.html` - proper success state

On submit success: hide the form, replace the section content with a full
confirmation card:
- Check circle icon (green)
- "Request received!" heading
- "We'll be in touch at [email] within 24 hours."
- "Back to site" link (scrolls to hero)

The tiny green text under the button is not enough for a prospect who just
submitted their details.

## Phase 2 — FUTURE (plan only, not built yet)

### Rate limiting

Two-layer approach:
1. Email cooldown: if `demo_requests` already has a row with the same email
   created in the last 24 hours, return 429 with message "We already have
   your request - we'll reach out soon." No new insert.
2. IP cooldown: max 5 submissions from the same IP in any 1-hour window
   (catches bots that rotate emails). Check count, return 429 if exceeded.
   Store IP in the existing `ip_address` column - no new table needed.

Both checks happen server-side only (no JS-visible signal for bots to probe).

### Auto-reply email to the submitter

Once domain email (e.g., hello@themisiq.net via Google Workspace / Postmark)
is configured:
- Send a branded "We got your request" email to the submitter
- Content: confirmation, what to expect, link to book a slot (Calendly / Cal.com)
- Use the existing `core/email.send_email()` - just add a second call with
  `to=email` (submitter) after the existing admin notify call
- Gated on `settings.SMTP_USER` being a domain address (not a personal Gmail)
  to avoid sending from alimoyo58@gmail.com which looks unprofessional

### Job title + message fields

Add to the form (and DB):
- `job_title TEXT` - single highest-signal field for prioritising leads
  (CISO vs IT Admin vs Developer changes the conversation entirely)
- `message TEXT` - optional "what's your biggest compliance challenge"
  (short textarea, not required)

DB: add via `_COLUMN_MIGRATIONS` (idempotent ALTER TABLE) rather than
touching `_SHARED_TABLES`, since the table already exists by then.

### CSV export from admin

"Export CSV" button in the demo requests section downloads all requests
as a CSV (name, email, company, job_title, plan, date, status). Mirrors
the existing ERM CSV export pattern.

### Admin notification email improvements

Current email body is plain. Improve to:
- Clear subject line with plan highlighted if set
- Quick "Reply to this email" button linking to `mailto:{submitter_email}`
- Estimated lead score (job_title CISO/VP/Head = hot, else warm)

## Files changed

| File | Change |
|---|---|
| `database.py` | Add `demo_requests` table + 2 indexes to `_SHARED_TABLES` |
| `main.py` | Persist to DB + capture IP in `/api/demo-request` |
| `modules/launcher/routes_super_admin.py` | 3 new endpoints |
| `modules/launcher/templates/super_admin.html` | Demo Requests section + analytics |
| `landing_page/index.html` | Full success card on form submission |

## Change log

- [ ] Add `demo_requests` table to `_SHARED_TABLES` in database.py
- [ ] Update `/api/demo-request` in main.py to persist to DB
- [ ] Add 3 super admin endpoints to routes_super_admin.py
- [ ] Add Demo Requests section to super_admin.html
- [ ] Replace landing page inline success text with full confirmation card
- [ ] py_compile clean on all touched Python files
- [ ] Manual smoke test: submit form, verify DB row, verify super admin shows it
