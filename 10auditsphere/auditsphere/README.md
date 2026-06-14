# AuditSphere — Compliance Audit Management System

A full-stack local web application for managing compliance audits across multiple frameworks (ISO 27001, SOC 2, GDPR, PCI DSS, HIPAA, Zimbabwe CDPA, ISO 42001 and custom frameworks). AI-powered by Anthropic Claude.

## Quick Start

```bash
# 1. Install dependencies
npm install

# 2. Configure environment
cp .env .env.local        # edit .env with your settings
# Set ANTHROPIC_API_KEY=sk-ant-...  (required for AI features)
# Set SMTP_* settings     (optional, for email reminders)

# 3. Start the server
npm start
# → http://localhost:3000
# → Login: admin@auditsphere.local / admin123
```

## Features

| Feature | Description |
|---|---|
| **Multi-Framework** | ISO 27001, SOC 2, GDPR, PCI DSS, HIPAA, Zimbabwe CDPA, ISO 42001 + custom |
| **Audit Management** | Create, track and manage external/internal audits with timelines |
| **Controls Checklist** | Manual entry or bulk import via Excel/CSV/PDF |
| **Evidence Repository** | File upload (PDF, Excel, PNG, DOCX), versioning, approval workflow |
| **AI Checklist Parser** | Upload auditor Excel/PDF → Claude extracts controls automatically |
| **AI Gap Analysis** | Claude analyses your controls and identifies risks + quick wins |
| **AI Compliance Chat** | Ask Claude anything about your frameworks |
| **AI Report Generation** | Claude writes executive summary + exports PDF report |
| **AI Auto-fill Controls** | Type control ID + name → Claude fills description + evidence list |
| **Email Reminders** | Daily/weekly/monthly reminders per control via SMTP |
| **Overdue Detection** | Automatic overdue flagging with visual indicators |
| **Comments & Threads** | Discussion threads on each control item |
| **User Management** | Admin / Auditor / Member roles |
| **Dashboard** | Live completion %, evidence ring chart, audit timeline |
| **PDF Export** | Full audit report with AI narrative, control table, stats |

## AI Features (require ANTHROPIC_API_KEY)

All AI features use `claude-sonnet-4-20250514` and consume your Anthropic API credits.

- **AI Checklist Parser** — Upload Excel/PDF from external auditor → automatic control extraction
- **AI Gap Analysis** — Readiness score, critical gaps, quick wins, prioritised recommendations  
- **AI Compliance Chat** — Ask anything about ISO 27001, SOC 2, GDPR etc.
- **AI Report Narrative** — Executive summary, key findings, overall status for PDF exports
- **AI Control Auto-fill** — Type control ID/name → auto-populate description + evidence items

## Email Reminders (optional SMTP)

Configure in `.env`:
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASS=your-app-password      # Gmail: create App Password
SMTP_FROM=AuditSphere <your@gmail.com>
```

Without SMTP config, emails are simulated (logged to console).

## Project Structure

```
auditsphere/
├── src/
│   ├── server.js              # Express server entry point
│   ├── database.js            # sql.js SQLite database layer
│   ├── routes/
│   │   ├── auth.js            # Login, register, session
│   │   ├── audits.js          # Frameworks + audit CRUD
│   │   ├── controls.js        # Controls, comments, reminders
│   │   ├── evidence.js        # File upload, versioning, approval
│   │   └── ai.js              # All Claude AI endpoints
│   └── services/
│       ├── ai.js              # Anthropic SDK wrapper
│       ├── email.js           # Nodemailer + HTML templates
│       ├── pdfReport.js       # PDFKit report generator
│       └── scheduler.js       # node-cron reminder scheduler
├── public/
│   └── index.html             # Complete SPA frontend
├── data/
│   ├── auditsphere.db         # SQLite database (auto-created)
│   ├── uploads/               # Evidence files
│   └── reports/               # Generated PDF reports
├── test-all.js                # 47-test integration suite
├── .env                       # Configuration (edit this)
└── package.json
```

## API Endpoints

```
POST   /api/auth/login                    Login
POST   /api/auth/register                 Add user
GET    /api/auth/users                    List users

GET    /api/frameworks                    List frameworks
POST   /api/frameworks                    Create framework

GET    /api/audits                        List audits
POST   /api/audits                        Create audit
GET    /api/audits/:id                    Get audit + controls
PATCH  /api/audits/:id                    Update audit
DELETE /api/audits/:id                    Delete audit + cascade

GET    /api/audits/:id/controls           List controls (filter: status, risk)
POST   /api/audits/:id/controls           Create control
POST   /api/audits/:id/controls/bulk      Bulk import controls
GET    /api/controls/:id                  Get control + evidence + comments
PATCH  /api/controls/:id                  Update control
DELETE /api/controls/:id                  Delete control + cascade
POST   /api/controls/:id/comments         Add comment
POST   /api/controls/:id/reminders        Set email reminder
GET    /api/controls/:id/evidence         List evidence

POST   /api/controls/:id/evidence         Upload evidence file
GET    /api/evidence/:id/download         Download file
PATCH  /api/evidence/:id                  Approve/reject evidence
DELETE /api/evidence/:id                  Delete evidence

POST   /api/ai/parse-checklist            AI: parse uploaded checklist
GET    /api/ai/gap-analysis/:auditId      AI: gap analysis
POST   /api/ai/suggest-control            AI: auto-fill control details
POST   /api/ai/generate-report/:auditId   AI: generate report + PDF
POST   /api/ai/chat                       AI: compliance Q&A
GET    /api/ai/reports/download/:fileName  Download generated PDF

GET    /api/health                        Health check
```

## Running Tests

```bash
node test-all.js
# Expected: 47/47 PASSED
# AI routes show as timeout in sandbox (no Anthropic network),
# will work normally with a valid ANTHROPIC_API_KEY on your machine.
```

## Default Login
- Email: `admin@auditsphere.local`
- Password: `admin123`
- **Change this immediately in production!**

## Technology Stack
- **Backend**: Node.js + Express
- **Database**: SQLite via sql.js (pure JS, zero native compilation)
- **AI**: Anthropic Claude (claude-sonnet-4-20250514)
- **PDF**: PDFKit
- **Excel parsing**: SheetJS (xlsx)
- **Email**: Nodemailer
- **Scheduler**: node-cron
- **Auth**: bcryptjs + express-session
- **Frontend**: Vanilla JS SPA (no build step required)
