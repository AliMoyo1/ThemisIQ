# 🛡️ ComplianceOS

**A multi-framework GRC (Governance, Risk & Compliance) web platform**

Tracks policies and procedures across 7 major compliance frameworks in a single, unified web application.

## Frameworks Covered
| Framework | Controls |
|---|---|
| ISO 27001:2022 | 47 controls |
| ISO 42001 (AI) | 28 controls |
| SOC 2 Type II | 40 controls |
| PCI DSS v4.0 | 39 controls |
| GDPR | 26 controls |
| Zimbabwe CDPA | 27 controls |
| HIPAA | 32 controls |
| **Total** | **239 controls** |

## Features
- 📊 **Live Dashboard** — real-time compliance scores and charts
- 🔗 **Cross-Framework Mapping** — see which controls satisfy multiple frameworks
- ⚠️ **Risk Register** — log and score compliance risks
- 📁 **Document Register** — track all policies and procedures
- 📋 **Audit Trail** — every change logged with user and timestamp
- ⬇️ **Excel Export** — export all data to formatted Excel workbook
- 🔐 **Role-based Access** — Admin, Auditor, Viewer roles

## Quick Start (Windows)

1. Install Python 3.9+ from [python.org](https://python.org)
2. Double-click `START.bat`
3. Open browser to `http://localhost:8000`

## Manual Start

```bash
pip install -r requirements.txt
python database.py
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Default Credentials
| Role | Username | Password |
|---|---|---|
| Admin | admin | Admin@123! |
| Auditor | auditor | Audit@123! |
| Viewer | viewer | View@123! |

## Tech Stack
- **Backend**: Python + FastAPI
- **Database**: SQLite
- **Frontend**: HTML + CSS + Chart.js
- **Templates**: Jinja2

## Project Structure
```
complianceos/
├── main.py          # FastAPI application & routes
├── database.py      # DB models, seed data, all framework controls
├── templates/       # HTML templates
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── framework.html
│   ├── mapping.html
│   ├── risks.html
│   ├── documents.html
│   └── audit_log.html
├── static/          # CSS, JS, images
├── requirements.txt
└── START.bat        # Windows launcher
```

## Roadmap
- [ ] Phase 2: AI Policy Generator (Claude API integration)
- [ ] Phase 2: Audit Readiness Score engine
- [ ] Phase 3: Email reminders for review dates
- [ ] Phase 3: Evidence file upload
- [ ] Phase 3: Docker deployment package

---
*Built as a portfolio project demonstrating GRC domain knowledge + Python web development*
