# GRID — Audit Management

Plan and run audits against frameworks: schedule, sample controls, capture
evidence, raise non-conformances, score compliance, generate branded PDF/DOCX
reports, manage auditees and vendors. Includes a background scheduler for
reminders, escalations, and backups.

## Mounts

- `/grid/` — dashboard.
- `/grid/audits`, `/grid/controls`, `/grid/evidence`, `/grid/findings`,
  `/grid/vendors`, `/grid/non-conformances`, `/grid/reports`, `/grid/approvals`.
- `/grid/api/*` — JSON CRUD.
- `/grid/api/vendors/{id}/cross-module` — cross-module vendor profile.

## Tables

`grid_*` prefix. Notable: `grid_audits`, `grid_controls`, `grid_evidence_items`,
`grid_findings`, `grid_non_conformances`, `grid_vendors`,
`grid_vendor_assessments`, `grid_compliance_scores`, `grid_share_links`,
`grid_approval_requests`.

## Events

Emits:
- `grid.audit.completed`, `grid.finding.created`, `grid.non_conformance.raised`,
  `grid.policy.requested`
- `vendor.created` (on vendor create — feeds canonical registry)

Handles:
- `sentinel.breach.confirmed` → creates post-incident audit (jurisdiction-aware name)

## Files

| File | Role |
|---|---|
| `routes.py` | HTTP + JSON routes (~2,100 lines — split candidate) |
| `data_service.py` | DB CRUD (~2,400 lines — split candidate) |
| `report_service.py` | ReportLab PDF + python-docx Word export |
| `scheduler.py` | Cron jobs: reminders, escalations, weekly backups |
| `ai_service.py` | AI-assisted finding write-up |
| `templates/index.html` | SPA |

## Notes

- Vendor create calls `core.vendor_link.ensure_canonical` and stores
  `canonical_id`. The same vendor across Privacy/Resilience/Audit refers to
  the same canonical row.
- Compliance scoring is cached in `grid_compliance_scores` and recomputed on
  audit completion.
