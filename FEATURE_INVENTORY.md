# One For All — Complete Feature Inventory & Status

> Last updated: 2026-05-30 | Auto-generated from codebase analysis + feature tracker spreadsheet + design documents

---

## Platform Core (Launcher)

| ID | Feature | Status | Notes |
|---|---|---|---|
| CORE-01 | Session-based authentication | ✅ Done | bcrypt passwords, 24hr expiry |
| CORE-02 | RBAC with 15 roles | ✅ Done | 50+ capabilities, user_roles table |
| CORE-03 | Secure cookies (HttpOnly) | ✅ Done | CSRF protection on forms |
| CORE-04 | Audit logging | ✅ Done | audit_log table, all actions |
| CORE-05 | Rate limiting on login | ✅ Done | IP-based restrictions |
| CORE-06 | Security headers middleware | ✅ Done | X-Frame-Options, CSP, etc. |
| CORE-07 | Unified shell UI | ✅ Done | base_shell.html template |
| CORE-08 | Dark/light theme toggle | ❌ Missing | CSS variable mismatch across modules |
| CORE-09 | Command centre dashboard | ✅ Done | Launcher module |
| CORE-10 | User management | ✅ Done | Admin panel CRUD |
| CORE-11 | Settings management | ✅ Done | settings table |
| CORE-12 | Email notifications | ✅ Done | SMTP configured, GRID sends emails |
| CORE-13 | API keys for integration | ✅ Done | api_keys table |
| CORE-14 | Webhooks | ✅ Done | webhooks + webhook_logs tables |
| CORE-15 | Activity timeline | ✅ Done | audit_log UI view |
| CORE-16 | Two-factor authentication (2FA) | ❌ Missing | TOTP-based for admin accounts |
| CORE-17 | Session management UI | ❌ Missing | View/revoke active sessions |
| CORE-18 | Password policy enforcement | ❌ Missing | Complexity, expiry, history |
| CORE-19 | Account lockout after failures | ❌ Missing | 5 failures = 15 min lockout |
| CORE-20 | Login audit dashboard | ❌ Missing | Map of failed login attempts |
| CORE-21 | User activity reports | ❌ Missing | Who did what, when, exportable |
| CORE-22 | Bulk user import/export | ❌ Missing | CSV for HR integration |
| CORE-23 | LDAP/Active Directory integration | ❌ Missing | Corporate login |
| CORE-24 | Password reset flow | ❌ Missing | Secure token-based reset |
| CORE-25 | Email template editor | ❌ Missing | Customize notification emails |
| CORE-EV1 | Cross-module evidence vault | ✅ Done | Upload, tag, search, link, version, verify |
| CORE-EV2 | Evidence vault UI overhaul | ✅ Done | Module tabs, detail panel, link-to, coverage |
| CORE-EV3 | Evidence integrity verification | ✅ Done | SHA-256 hash + weekly audit job |
| CORE-EV4 | Evidence expiry notifications | ✅ Done | Scheduler job, 30-day alerts |
| CORE-EV5 | Evidence retention enforcement | ✅ Done | Auto-archive past expiry date |
| CORE-EV6 | Evidence coverage dashboard | ✅ Done | Per-module entity coverage API |
| CORE-XM1 | Cross-module event bus | ✅ Done | 14+ event types, handlers across modules |
| CORE-XM2 | Cross-module risk register | ✅ Done | Centralized risk tracking |
| CORE-XM3 | Cross-module task board | ✅ Done | Kanban-style, auto-created tasks |
| CORE-XM4 | Notification system | ✅ Done | Bell icon, mark-as-read |
| CORE-XM5 | Global search | ✅ Done | Full-text across modules |
| CORE-XM6 | Platform Trainer AI | ✅ Done | AI assistant bubble, tooltip mode |

---

## Module 1: ARIA (Governance, Risk & Compliance)

| ID | Feature | Status | Notes |
|---|---|---|---|
| ARIA-01 | Multi-framework support (15) | ✅ Done | frameworks table, seed data |
| ARIA-02 | Framework activation toggle | ✅ Done | Admin toggle API |
| ARIA-03 | Control tracking per framework | ✅ Done | aria_controls table |
| ARIA-04 | Control status updates | ✅ Done | Inline editing |
| ARIA-05 | Document library | ✅ Done | aria_documents table |
| ARIA-06 | Document upload | ✅ Done | File upload + revision system |
| ARIA-07 | Risk register | ✅ Done | aria_risks table |
| ARIA-08 | Cross-framework control mapping | ✅ Done | Visual mapping table |
| ARIA-09 | Excel export | ✅ Done | GET /aria/export/excel |
| ARIA-10 | AI policy generator | ✅ Done | POST /aria/api/generate-policy |
| ARIA-11 | AI gap analysis | ✅ Done | Framework-level gap analysis |
| ARIA-12 | Ask ARIA chatbot (RAG) | ✅ Done | POST /aria/api/ask |
| ARIA-13 | Framework dashboard with charts | ✅ Done | Overview UI |
| ARIA-14 | Framework detail page | ✅ Done | Controls table with inline edit |
| ARIA-15 | Pre-populated control sets | ❌ Missing | Seed scripts needed |
| ARIA-16 | AI auto-creation of controls | ❌ Missing | Auto-generate on framework activation |
| ARIA-17 | Control testing schedule | ❌ Missing | Calendar tracking |
| ARIA-18 | Control evidence requirements | ❌ Missing | Evidence validation mapping |
| ARIA-19 | Control maturity scoring | ❌ Missing | 0-5 capability scale |
| ARIA-20 | Automated control reminders | ❌ Missing | Email review due tracking |
| ARIA-21 | Control owner assignment | ❌ Missing | Responsible team mapping |
| ARIA-22 | Control history/change log | ❌ Missing | Track status changes over time |
| ARIA-23 | Framework comparison view | ❌ Missing | Side-by-side control mapping |
| ARIA-24 | Compliance score trends | ❌ Missing | Historical progress charts |
| ARIA-25 | Gap analysis report export | ❌ Missing | Formal management PDF |
| ARIA-26 | Policy template library | ❌ Missing | Pre-written baseline policies |
| ARIA-NEW1 | Document template management | ✅ Done | Upload .docx branding templates |
| ARIA-NEW2 | Document upload-and-replace workflow | ✅ Done | Replace AI draft with edited version |
| ARIA-NEW3 | Branding engine | ✅ Done | Apply company template to documents |
| ARIA-NEW4 | Document revision history | ✅ Done | aria_doc_revisions table |
| ARIA-NEW5 | Document review workflow | ✅ Done | AI Draft → Under Review → Approved |
| ARIA-NEW6 | Controls show vault evidence count | ✅ Done | Evidence badge on framework detail |
| ARIA-NEW7 | GRID↔ARIA policy request flow | ✅ Done | Cross-module event + notification |
| ARIA-NEW8 | ARIA policies sync to vault | ✅ Done | Auto-sync on approval |

---

## Module 2: GRID (Audit Management)

| ID | Feature | Status | Notes |
|---|---|---|---|
| GRID-01 | SPA shell | ✅ Done | Single index.html, client-side routing |
| GRID-02 | Dashboard API | ✅ Done | GET /grid/api/dashboard |
| GRID-03 | Audit CRUD | ✅ Done | Full lifecycle |
| GRID-04 | Audit control checklists | ✅ Done | Controls linked to audits |
| GRID-05 | Evidence collection | ✅ Done | Upload, approval, versioning, expiry |
| GRID-06 | Non-conformance tracking | ✅ Done | Full CAP lifecycle (7 stages) |
| GRID-07 | Vendor management | ✅ Done | grid_vendors table |
| GRID-08 | Vendor assessments | ✅ Done | Assessment records |
| GRID-09 | Remote audit sessions | ✅ Done | Sessions + participants + findings |
| GRID-10 | AI gap analysis for audit | ✅ Done | Per-audit gap analysis |
| GRID-11 | AI risk scoring (batch) | ✅ Done | Batch risk scoring |
| GRID-12 | AI checklist parsing | ✅ Done | Excel/CSV upload + AI extraction |
| GRID-13 | AI report narrative generation | ✅ Done | Executive summary generation |
| GRID-14 | AI compliance chat | ✅ Done | ask_compliance_ai |
| GRID-15 | Control mappings | ✅ Done | grid_control_mappings table |
| GRID-16 | Approval workflows | ✅ Done | grid_approvals table |
| GRID-17 | Share links for audits | ✅ Done | Token-based external access |
| GRID-18 | Control comments | ✅ Done | grid_control_comments |
| GRID-19 | Compliance scores | ✅ Done | Nightly snapshots |
| GRID-20 | Timeline tracking | ✅ Partial | grid_timeline exists, auto-generated milestones, minimal UI |
| GRID-21 | Audit checklist templates | ✅ Partial | Framework auto-population + checklist import covers use case |
| GRID-22 | Audit scheduling calendar | ❌ Missing | No visual calendar component |
| GRID-23 | Audit team assignment | ✅ Partial | Controls have assignee_id, NCs have assigned_to |
| GRID-24 | Evidence request workflow | ❌ Missing | No trackable request pipeline |
| GRID-25 | Automated audit score calculation | ✅ Done | Nightly snapshot + dashboard |
| GRID-26 | Finding remediation tracking | ✅ Done | 7-stage CAP lifecycle + mgmt response |
| GRID-27 | Audit report generator | ✅ Done | PDF + DOCX with NCs, evidence, sign-offs |
| GRID-NEW1 | Evidence versioning | ✅ Done | Replace with version chain |
| GRID-NEW2 | Evidence expiry tracking | ✅ Done | 30-day alerts via scheduler |
| GRID-NEW3 | Evidence approval workflow | ✅ Done | Approve/reject with bulk operations |
| GRID-NEW4 | Evidence completeness dashboard | ✅ Done | Per-control coverage |
| GRID-NEW5 | CAP lifecycle stepper | ✅ Done | 7-stage visual stepper |
| GRID-NEW6 | Management response workflow | ✅ Done | Approve/reject gates |
| GRID-NEW7 | NC email notifications | ✅ Done | Assignment, deadline, escalation |
| GRID-NEW8 | NC-evidence linking | ✅ Done | Corrective action proof |
| GRID-NEW9 | Report persistence + history | ✅ Done | grid_reports table, download history |
| GRID-NEW10 | Follow-up audit linking | ✅ Done | parent_audit_id, NC carry-forward |
| GRID-NEW11 | Cross-cycle NC comparison | ✅ Done | Carried/new/resolved view |
| GRID-NEW12 | Audit conclusion + sign-off | ✅ Done | Lead → Reviewer → Lock workflow |
| GRID-NEW13 | Audit locking | ✅ Done | Mutation enforcement (HTTP 423) |
| GRID-NEW14 | Program dashboard | ✅ Done | Multi-audit compliance posture |
| GRID-NEW15 | Attach ARIA policy as evidence | ✅ Done | Browse + attach approved policies |
| GRID-NEW16 | Policy request to ARIA | ✅ Done | Cross-module event flow |
| GRID-NEW17 | Browse Evidence Vault | ✅ Done | Vault picker in control detail |
| GRID-NEW18 | GRID evidence syncs to vault | ✅ Done | Auto-sync on upload |

---

## Module 3: BCM (Business Continuity Management)

| ID | Feature | Status | Notes |
|---|---|---|---|
| BCM-01 | SPA shell | ✅ Done | Single index.html, tab navigation |
| BCM-02 | Dashboard stats | ✅ Done | GET /bcm/api/dashboard |
| BCM-03 | BIA (Business Impact Analysis) | ✅ Done | RTO/RPO/MTPD fields, criticality |
| BCM-04 | BCM risk register | ✅ Done | Likelihood × impact scoring |
| BCM-05 | Recovery plans | ✅ Done | CRUD + plan reviews + AI generation |
| BCM-06 | Incident management | ✅ Done | Full lifecycle |
| BCM-07 | Incident updates tracking | ✅ Done | Timeline of updates |
| BCM-08 | AI incident suggestions | ✅ Done | POST /bcm/api/incidents/{id}/ai-suggest |
| BCM-09 | Exercise planning | ✅ Done | bcm_exercises CRUD |
| BCM-10 | Vendor dependency register | ✅ Done | bcm_vendors + assessments |
| BCM-11 | Dependency graph | ✅ Done | Nodes + edges + impact analysis |
| BCM-12 | Automated BIA calculation | ❌ Missing | RTO/RPO algorithm engine |
| BCM-13 | Maximum Tolerable Downtime (MTD) | ❌ Missing | Calculated MTD boundaries |
| BCM-14 | Crisis communication templates | ❌ Missing | Pre-written response alerts |
| BCM-15 | Emergency contact tree | ❌ Missing | Call trees with escalation |
| BCM-16 | Exercise scenario library | ❌ Missing | Pre-built disaster injects |
| BCM-17 | Plan activation workflow | ❌ Missing | One-click emergency launch |
| BCM-18 | Dependency impact analysis (auto) | ❌ Missing | Automated failure cascade tracing |
| BCM-IMPL1 | Incident action items | ✅ Done | bcm_incident_actions CRUD |
| BCM-IMPL2 | Incident decisions log | ✅ Done | bcm_incident_decisions CRUD |
| BCM-IMPL3 | Incident stakeholders | ✅ Done | Notification management |
| BCM-IMPL4 | Incident plan links | ✅ Done | Link incidents to plans |
| BCM-IMPL5 | Compliance controls | ✅ Done | bcm_compliance_controls + evidence |
| BCM-IMPL6 | Training management | ✅ Done | Modules + attestation tracking |
| BCM-IMPL7 | Document management + RAG | ✅ Done | Upload, reindex, AI Q&A |
| BCM-IMPL8 | Coverage analysis | ✅ Done | BIA↔plan gap detection |
| BCM-IMPL9 | AI plan generator | ✅ Done | Claude generates full BCPs |
| BCM-IMPL10 | AI plan review | ✅ Done | AI critique with scoring |
| BCM-IMPL11 | Board report generator | ✅ Done | AI executive summary |
| BCM-IMPL12 | AI chat | ✅ Done | Conversational assistant |
| BCM-IMPL13 | Evidence from vault | ✅ Done | Plans/incidents show vault evidence |

### BCM — Features from Design Doc Not Yet Built

| Feature | Priority | Notes |
|---|---|---|
| Automated BIA calculation engine | High | RTO/RPO/MTD auto-compute from dependencies |
| Crisis communication templates | High | Pre-approved holding statements |
| Emergency contact/call tree | High | Escalation chains with SMS/email |
| Exercise scenario library | Medium | Pre-built tabletop injects |
| Plan activation (one-click) | High | Emergency mode: activate plan, notify team |
| Predictive risk scoring | Low | AI + threat feeds |
| Scenario simulation ("what-if") | Medium | Model cascade failures |
| Real-time threat intelligence | Low | External feed ingestion |
| Post-incident auto-summary | Medium | Generate PIR from logs |
| Smart notification routing | Medium | Channel/recipient selection by incident type |
| Multi-language translation | Low | Global operations support |
| Mobile offline access | Low | PWA for field responders |

---

## Module 4: Sentinel (Data Protection)

| ID | Feature | Status | Notes |
|---|---|---|---|
| SENT-01 | SPA shell | ✅ Done | Single index.html, tab navigation |
| SENT-02 | ROPA CRUD | ✅ Done | sentinel_ropa table |
| SENT-03 | DPIA CRUD | ✅ Done | Create manually or spawn from ROPA |
| SENT-04 | Breach register | ✅ Done | Lifecycle management |
| SENT-05 | DSR (Data Subject Requests) | ✅ Done | Access/deletion/portability tracking |
| SENT-06 | Consent records | ✅ Done | Legal basis + lifecycle |
| SENT-07 | International transfers tracking | ✅ Done | SCCs, adequacy decisions |
| SENT-08 | Retention policies | ✅ Done | Retention schedules |
| SENT-09 | AI generate full DPIA | ✅ Done | Claude-powered |
| SENT-10 | AI score ROPA | ✅ Done | Compliance quality scoring |
| SENT-11 | AI assess breach | ✅ Done | Impact assessment |
| SENT-12 | Data mapping visualization | ❌ Missing | Visual personal data flows |
| SENT-13 | Data retention scheduler | ❌ Missing | Automated cleanup intervals |
| SENT-14 | Legitimate interest assessment | ❌ Missing | LIA workflow template |
| SENT-15 | Subject access request tracking | ❌ Missing | 30-day regulatory timer |
| SENT-16 | Breach notification timer | ❌ Missing | 72-hour regulatory countdown |
| SENT-IMPL1 | Vendor/Processor management | ✅ Done | AI vendor compliance checks |
| SENT-IMPL2 | Privacy notices | ✅ Done | AI-generated drafts |
| SENT-IMPL3 | Data controllers | ✅ Done | Registration management |
| SENT-IMPL4 | Security measures | ✅ Done | Technical/organisational docs |
| SENT-IMPL5 | Privacy policies | ✅ Done | Full CRUD |
| SENT-IMPL6 | Training management | ✅ Done | Excel analysis capability |
| SENT-IMPL7 | Data flow mapping | ✅ Done | sentinel_data_flows CRUD |
| SENT-IMPL8 | AI research assistant | ✅ Done | General data protection research |
| SENT-IMPL9 | AI risk generator | ✅ Done | Privacy risk assessment |
| SENT-IMPL10 | AI chat | ✅ Done | Conversational assistant |
| SENT-IMPL11 | AI gap analysis | ✅ Done | Framework-level gaps |
| SENT-IMPL12 | AI DSR response drafts | ✅ Done | Auto-drafted responses |
| SENT-IMPL13 | AI privacy notice generator | ✅ Done | Draft notices |
| SENT-IMPL14 | AI vendor compliance check | ✅ Done | Per-vendor assessment |
| SENT-IMPL15 | Compliance score | ✅ Done | Overall compliance indicator |
| SENT-IMPL16 | Legal basis reference | ✅ Done | Per-regulation lookup |
| SENT-IMPL17 | Audit trail + export | ✅ Done | CSV export |
| SENT-IMPL18 | Settings management | ✅ Done | Module settings |

### Sentinel — Features from Design Doc Not Yet Built

| Feature | Priority | Notes |
|---|---|---|
| Data mapping visualization (visual) | High | Interactive flow diagram, not just CRUD |
| Data retention scheduler | High | Automated deletion/anonymization on schedule |
| Legitimate Interest Assessment (LIA) | Medium | Structured 3-part test workflow |
| DSR 30-day timer with alerts | High | Regulatory countdown + escalation |
| Breach 72-hour notification timer | Critical | GDPR Article 33 compliance |
| Cookie consent management | Medium | Banner configuration, preference center |
| Privacy by design checklist | Low | New project assessment |
| Data inventory auto-discovery | Low | Scan systems for PII |

---

## Module 5: Evidence Vault (Cross-Module)

| Feature | Status | Notes |
|---|---|---|
| Centralized evidence repository | ✅ Done | Upload, store, deduplicate |
| SHA-256 integrity verification | ✅ Done | Hash on upload + verify endpoint |
| Version chains | ✅ Done | parent_id linking |
| Category/tag filtering | ✅ Done | policy, certificate, screenshot, etc. |
| Cross-module linking API | ✅ Done | evidence_links to any entity |
| Entity name resolution | ✅ Done | Batch resolve across modules |
| Auto-evidence from events | ✅ Done | 14+ event handlers create records |
| Module filter tabs | ✅ Done | All/ARIA/GRID/BCM/Sentinel |
| Detail slide panel | ✅ Done | Metadata, links, versions, integrity |
| Expiring Soon view | ✅ Done | 30-day window filter |
| Unlinked evidence view | ✅ Done | Items with zero links |
| Link-to cross-module | ✅ Done | Modal with entity search |
| Per-module stats | ✅ Done | Count breakdown in stats bar |
| Evidence coverage API | ✅ Done | Entity-level coverage percentages |
| GRID evidence sync to vault | ✅ Done | Auto-sync on upload |
| ARIA policy sync to vault | ✅ Done | Auto-sync on approval |
| Vault browse from GRID | ✅ Done | Attach vault items to controls |
| Expiry notifications | ✅ Done | Scheduler job (daily) |
| Integrity audit | ✅ Done | Weekly re-hash + mismatch alerts |
| Retention enforcement | ✅ Done | Auto-archive past expiry |
| Blocked file extensions | ✅ Done | .exe, .bat, .ps1, etc. |
| MIME type validation | ✅ Done | Allowlist enforcement |
| Path traversal protection | ✅ Done | Resolved path checks on download |

---

## Summary

| Module | Implemented | Missing | Coverage |
|---|---|---|---|
| Core Platform | 22 | 10 | 69% |
| ARIA | 22 | 12 | 65% |
| GRID | 37 | 2 | 95% |
| BCM | 24 | 7 | 77% |
| Sentinel | 24 | 5 | 83% |
| Evidence Vault | 22 | 0 | 100% |
| **Total** | **151** | **36** | **81%** |

### Critical Missing Items (should build next)

1. **SENT-16**: Breach 72-hour notification timer — regulatory compliance requirement
2. **SENT-15**: DSR 30-day timer — regulatory compliance requirement
3. **BCM-17**: Plan activation workflow — core BCM functionality
4. **BCM-14**: Crisis communication templates — essential for incident response
5. **BCM-15**: Emergency contact tree — essential for incident response
6. **CORE-16**: Two-factor authentication — security baseline for enterprise
7. **CORE-19**: Account lockout — security baseline
8. **SENT-12**: Data mapping visualization — visual data flow diagram
