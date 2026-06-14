// Seed a demo tenant with realistic data. Idempotent: safe to re-run.
require('dotenv').config();
const bcrypt = require('bcryptjs');
const db = require('../models/db');
const rag = require('../services/rag');

const DEMO_EMAIL = 'demo@acme.test';
const DEMO_PASSWORD = 'demo12345';

function upsertTenant() {
  let tenant = db.prepare('SELECT * FROM tenants WHERE slug = ?').get('acme-demo');
  if (!tenant) {
    const info = db.prepare(`INSERT INTO tenants (name, slug, industry, ai_provider) VALUES (?, ?, ?, ?)`)
      .run('Acme Global', 'acme-demo', 'Manufacturing', process.env.AI_DEFAULT_PROVIDER || 'openai');
    tenant = db.prepare('SELECT * FROM tenants WHERE id = ?').get(info.lastInsertRowid);
  }
  return tenant;
}

function upsertUser(tenantId) {
  let user = db.prepare('SELECT * FROM users WHERE email = ?').get(DEMO_EMAIL);
  if (!user) {
    db.prepare(`INSERT INTO users (tenant_id, name, email, password_hash, role) VALUES (?, ?, ?, ?, 'admin')`)
      .run(tenantId, 'Demo Admin', DEMO_EMAIL, bcrypt.hashSync(DEMO_PASSWORD, 10));
    user = db.prepare('SELECT * FROM users WHERE email = ?').get(DEMO_EMAIL);
  }
  return user;
}

function seedDomain(tenantId) {
  const existing = db.prepare('SELECT COUNT(*) AS c FROM bia_records WHERE tenant_id = ?').get(tenantId).c;
  if (existing > 0) return;

  // BIA
  const biaRows = [
    ['Online order processing', 'E-commerce', 'Priya Shah', 'Primary revenue channel.', 2, 4, 85000, 5, 4, 3, 'Critical', 'Payments gateway, inventory, fulfillment'],
    ['Payroll processing', 'HR', 'Marcus Lee', 'Biweekly staff payroll.', 48, 24, 12000, 3, 4, 5, 'High', 'Bank API, HRIS'],
    ['Customer support phone lines', 'Support', 'Andrea McBean', 'SLA-backed phone support.', 4, 2, 8000, 4, 3, 2, 'High', 'Telephony, CRM'],
    ['Email communications', 'IT', 'Peter Jacobs', 'Transactional + internal email.', 2, 1, 4000, 3, 2, 2, 'Medium', 'Mail relay, DNS'],
    ['Warehouse management system', 'Operations', 'Mary Billins', 'Pick-pack-ship orchestration.', 8, 4, 22000, 5, 3, 3, 'Critical', 'ERP, scanners'],
  ];
  const biaStmt = db.prepare(`INSERT INTO bia_records
    (tenant_id, process_name, department, owner, description, rto_hours, rpo_hours, financial_impact_per_day, operational_impact, reputational_impact, regulatory_impact, criticality, dependencies)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);
  biaRows.forEach(r => biaStmt.run(tenantId, ...r));

  // Risks
  const riskRows = [
    ['Ransomware attack on production network', 'Cyber', 'Mass encryption of file shares and servers.', 3, 5, 15, 'Mitigate', 'EDR + immutable backups + tabletop drills quarterly.', 'CISO', 'in_progress', '2026-06-30'],
    ['Single-supplier dependency for raw materials', 'Supplier', 'Supplier X provides 85% of component Y.', 3, 4, 12, 'Mitigate', 'Onboard alternate supplier by Q3.', 'Procurement', 'open', '2026-09-01'],
    ['Extended cloud region outage', 'Operational', 'Primary region unreachable.', 2, 5, 10, 'Mitigate', 'Configure active-passive failover to secondary region.', 'Platform Eng', 'open', '2026-05-20'],
    ['Key person dependency on payroll system', 'People', 'Only one engineer knows the payroll integration.', 4, 3, 12, 'Mitigate', 'Document + cross-train another engineer.', 'HR Eng', 'in_progress', '2026-05-15'],
    ['GDPR data breach through vendor', 'Regulatory', 'Sub-processor data incident.', 2, 4, 8, 'Transfer', 'Strengthen DPAs and require breach notification SLAs.', 'DPO', 'open', '2026-07-01'],
    ['Office flooding (London HQ)', 'Facility', 'Seasonal flood risk within basement IT room.', 2, 3, 6, 'Mitigate', 'Relocate racks to upper floor + sensors.', 'Facilities', 'in_progress', '2026-04-30'],
  ];
  const riskStmt = db.prepare(`INSERT INTO risks
    (tenant_id, title, category, description, likelihood, impact, score, treatment, mitigation, owner, status, due_date)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);
  riskRows.forEach(r => riskStmt.run(tenantId, ...r));

  // BCP plans
  const planRows = [
    ['Enterprise IT Disaster Recovery Plan', 'All production IT systems', 'Peter Jacobs', '1.3', 'approved',
`## Purpose
Restore critical IT services within defined RTO/RPO targets.

## Scope
All production systems including payments, WMS, CRM, email.

## Activation Criteria
- Primary region outage > 30 minutes
- Confirmed cyber incident with SEV2+ impact
- Facility loss affecting primary data center

## Roles
- Incident Commander: On-call platform lead
- Comms: VP Comms
- Recovery Lead: Infrastructure manager

## Procedures
1. Declare incident in Continuity OS
2. Execute failover runbook
3. Notify executive sponsor within 15 minutes
4. Validate service health checks
5. Communicate status every 30 minutes

## Communications
Internal: #incidents Slack + status page.
External: status.acmeglobal.com + email to enterprise customers.

## Review
Reviewed quarterly. Last DR test: 2026-01.`,
     '2026-01-15', '2026-07-15'],
    ['Ransomware Response Playbook', 'Cyber incidents', 'CISO', '2.0', 'approved',
`## Immediate Actions
1. Isolate affected hosts.
2. Preserve evidence — snapshot memory where possible.
3. Activate Cyber Incident Response Team.

## Notifications
- CEO, CISO, Legal, Cyber insurance carrier.
- Do not pay ransom without legal + law-enforcement counsel.

## Recovery
- Restore from immutable backups.
- Full forensic sweep before reconnection.

## Post-incident
- PIR within 7 days.
- Update IOCs and detection rules.`,
     '2026-02-01', '2026-05-01'],
    ['Supply Chain Continuity Plan', 'Procurement + Operations', 'Procurement Director', '1.1', 'draft',
`## Purpose
Maintain production if key suppliers fail.

## Key Suppliers
- Supplier X (components) — 85% dependency, contingency: Supplier Y.
- Supplier Z (logistics) — 60% dependency.

## Triggers
Any Tier 1 supplier with >7 day disruption.

## Response
Switch to approved alternates; ramp inventory buffer to 45 days.`,
     null, '2026-04-30'],
    ['Office Evacuation & Safety Plan', 'All offices', 'Facilities', '1.0', 'approved',
`## Purpose
Protect staff during facility-threatening events.

## Triggers
Fire alarm, flood, gas leak, armed threat, earthquake.

## Procedures
1. Activate alarm + PA system.
2. Evacuate via nearest exit to muster point.
3. Wardens conduct roll call.
4. Await emergency services.`,
     '2026-03-01', '2027-03-01'],
  ];
  const planStmt = db.prepare(`INSERT INTO bcp_plans
    (tenant_id, title, scope, owner, version, status, content, last_reviewed, next_review)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`);
  planRows.forEach(r => planStmt.run(tenantId, ...r));

  // Incidents
  const incRows = [
    ['Checkout latency spike on EU region', 'P95 latency exceeded 4s for 12 minutes on EU cluster.', 'SEV2', 'mitigated', 'Peter Jacobs', 'Payments service, EU load balancer'],
    ['Supplier X delivery delay (5 days)', 'Component Y shipment delayed due to port congestion.', 'SEV3', 'investigating', 'Procurement Director', 'Production line B'],
  ];
  const incStmt = db.prepare(`INSERT INTO incidents
    (tenant_id, title, description, severity, status, commander, affected_systems)
    VALUES (?, ?, ?, ?, ?, ?, ?)`);
  incRows.forEach(r => incStmt.run(tenantId, ...r));

  // ======================= Phase 2 demo data =======================

  // Vendors
  const vendorRows = [
    ['AWS - Primary Region (eu-west-1)', 'Cloud / Hosting', 'Hosts production services.', 'Peter Jacobs',
      'Alex Rivera', 'alex@aws.example', '+44 20 7946 0001',
      'Critical', 1, 'Restricted / Regulated', '99.99% uptime / 15m RPO', '2027-03-31',
      20, 4, 5, 3, 5, 'active', 'Multi-AZ active-passive, failover drill Q1 2026.', '2026-01-10', '2026-07-10'],
    ['Stripe', 'Financial', 'Payment processing for e-commerce.', 'Marcus Lee',
      'Jordan Finch', 'jordan@stripe.example', '+1 415 555 0123',
      'High', 2, 'Restricted / Regulated', '99.95% / 4h incident response', '2026-12-31',
      15, 4, 4, 4, 3, 'active', 'Backup processor: Adyen (manual cut-over).', '2025-11-30', '2026-05-31'],
    ['Supplier X (components)', 'Manufacturing', 'Sole-source component Y supplier.', 'Procurement Director',
      'Wei Chen', 'wei@supplierx.example', '+86 21 5555 0011',
      'Critical', 1, 'Internal', '10 business days lead time', '2026-07-15',
      20, 4, 5, 2, 5, 'active', 'Concentration risk high. Alternate onboarding in progress.', '2026-02-01', '2026-05-01'],
    ['Zendesk', 'SaaS', 'Customer support platform.', 'Andrea McBean',
      'Sam Patel', 'sam@zendesk.example', null,
      'Medium', 3, 'Internal', '99.9% / standard support', '2026-10-01',
      6, 2, 3, 2, 2, 'active', null, '2025-10-15', '2026-10-15'],
    ['Rackspace DNS (secondary)', 'Telecom', 'Secondary DNS provider.', 'Peter Jacobs',
      null, null, null,
      'Low', 4, 'Public', '99.99% anycast', '2026-09-01',
      3, 1, 2, 1, 1, 'active', null, '2025-09-01', '2026-09-01']
  ];
  const vendorStmt = db.prepare(`INSERT INTO vendors
    (tenant_id, name, category, service_provided, owner, contact_name, contact_email, contact_phone,
     criticality, tier, data_sensitivity, sla, contract_renewal,
     risk_score, financial_score, operational_score, compliance_score, concentration_risk,
     status, notes, last_reviewed, next_review)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);
  vendorRows.forEach(v => vendorStmt.run(tenantId, ...v));

  // Exercises
  const exerciseRows = [
    ['Ransomware tabletop - Q1 2026', 'tabletop', 'Simulated ransomware on production file servers.',
      null, '2026-03-12', 120, 'CISO',
      'CISO, CIO, Platform lead, Comms, Legal, External IR consultant',
      'Validate isolation, backup restore time, and executive comms.',
      'completed', 'partial',
      'Detection and isolation within SLA. Comms draft needed more work.',
      'Fast EDR response. Clear chain of command.',
      'Executive comms draft took 30+ min. Backup restore manifest unclear.',
      'Owner: CISO. Pre-draft exec comms templates and refresh backup runbook by 2026-05-15.'],
    ['Supplier X disruption walkthrough', 'walkthrough', 'Supplier X 10-day outage scenario.',
      null, '2026-05-06', 90, 'Procurement Director',
      'Procurement, Operations, Finance, Sales',
      'Confirm trigger points and alternate supplier activation.',
      'planned', null, null, null, null, null],
    ['Full-scale DR failover simulation', 'simulation', 'eu-west-1 full region loss.',
      null, '2026-06-24', 240, 'Peter Jacobs',
      'Platform, SRE, App owners, Customer Success',
      'Achieve RTO < 2h and verify service parity on secondary region.',
      'planned', null, null, null, null, null]
  ];
  const exStmt = db.prepare(`INSERT INTO exercises
    (tenant_id, title, type, scenario, plan_id, scheduled_date, duration_minutes, facilitator,
     participants, objectives, status, outcome, aar_summary, aar_strengths, aar_gaps, aar_actions)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);
  exerciseRows.forEach(e => exStmt.run(tenantId, ...e));

  // Compliance controls - seed ISO 22301 baseline if none exist
  const { FRAMEWORKS } = require('../services/frameworks');
  const catalog = FRAMEWORKS['ISO 22301'];
  const existingCtrl = db.prepare(`SELECT COUNT(*) AS c FROM compliance_controls WHERE tenant_id = ? AND framework = ?`)
    .get(tenantId, 'ISO 22301').c;
  if (existingCtrl === 0) {
    const ctrlIns = db.prepare(`INSERT INTO compliance_controls
      (tenant_id, framework, clause, title, description, status, owner, last_reviewed, next_review)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`);
    // Pre-fill some with varied statuses for a realistic dashboard
    const preset = {
      '4.1': 'implemented', '4.2': 'implemented', '4.3': 'implemented', '4.4': 'in_progress',
      '5.1': 'verified',    '5.2': 'implemented', '5.3': 'implemented',
      '6.1': 'in_progress', '6.2': 'implemented', '6.3': 'in_progress',
      '7.1': 'implemented', '7.2': 'in_progress', '7.3': 'in_progress', '7.4': 'implemented', '7.5': 'in_progress',
      '8.1': 'in_progress', '8.2': 'implemented', '8.3': 'implemented', '8.4': 'implemented', '8.5': 'in_progress',
      '8.6': 'not_started',
      '9.1': 'not_started', '9.2': 'not_started', '9.3': 'in_progress',
      '10.1': 'not_started', '10.2': 'not_started'
    };
    catalog.forEach(c => {
      ctrlIns.run(tenantId, 'ISO 22301', c.clause, c.title, c.description,
        preset[c.clause] || 'not_started',
        'BCM Lead', '2026-01-10', '2026-07-10');
    });
  }

  // ======================= Phase 3 demo data =======================

  // Training modules
  const trainingRows = [
    [
      'BCM 101 — Why Business Continuity Matters',
      'A 15-minute primer on business continuity, ISO 22301, and your role during a disruption.',
      'BCM fundamentals',
      null, // required_roles (null = all users)
      15, 'BCM Lead', 12, 90, 'active',
`## Learning objectives
- Understand what BCM is and why it matters
- Recognize our critical processes and their RTO targets
- Know how to declare an incident and who to contact

## What is business continuity?
Business Continuity Management (BCM) is the discipline of preparing for, responding to, and
recovering from disruptions. We follow ISO 22301 — an international standard that centers on
the Plan-Do-Check-Act cycle.

## Your role
When a disruption strikes, every staff member is expected to:
1. Follow the evacuation plan for physical emergencies
2. Notify the incident commander through the approved channel
3. Use the declared alternate procedures (manual workarounds) until systems are restored
4. Document actions taken for the post-incident review

## Critical processes
Our Business Impact Analysis identified five Tier-1 processes: online orders, payroll,
customer phone support, email, and the warehouse management system. RTO targets range from
2 to 48 hours depending on the process.`
    ],
    [
      'Incident Response — First 30 Minutes',
      'Step-by-step actions for the first 30 minutes of a declared incident.',
      'Incident response',
      'admin,manager,responder', // required roles
      20, 'CISO', 12, 85, 'active',
`## Immediate response checklist

1. **Confirm** the incident is real and safety is not at risk
2. **Declare** the incident in BCM Sentinel with the correct severity
3. **Activate** the incident commander and response team
4. **Communicate** initial status to leadership within 15 minutes
5. **Document** every action, timestamp, and decision

## Severity guidance
- **SEV1** — critical customer impact, exec notification within 5 minutes
- **SEV2** — major impact, exec notification within 15 minutes
- **SEV3** — moderate impact, standard channels
- **SEV4** — minor, tracking only

## Escalation
If the incident involves cyber, data, or safety — notify Legal immediately.`
    ],
    [
      'Crisis Communications Essentials',
      'How to draft a clear, calm, and truthful update under pressure.',
      'Crisis communications',
      'admin,manager', 10, 'VP Comms', 12, 80, 'active',
`## The 3C rule
**Clear.** One sentence of what happened. No jargon.
**Calm.** Neutral tone. Avoid speculation.
**Consistent.** All channels say the same thing.

## Audiences
- Staff — facts + what you need from them
- Customers — impact + ETA
- Regulators — what, when, how we're responding
- Media — statement via VP Comms only

## Review checklist
Did you include: what happened, when, who is affected, what we're doing, when we'll update again?`
    ],
    [
      'Ransomware Awareness',
      'How to spot, report, and avoid enabling ransomware attacks.',
      'Cyber resilience',
      null, 12, 'CISO', 12, 80, 'active',
`## Spot the signs
- Unexpected file renames or extensions
- Files becoming unreadable
- Ransom notes or unfamiliar pop-ups
- Sluggish machines with unusual network activity

## What to do
1. Disconnect from the network (pull cable / disable Wi-Fi)
2. Do NOT turn off the machine (evidence preservation)
3. Report to the SOC immediately
4. Wait for IR team guidance

## Prevention basics
- Never enable macros from email attachments
- Never click unknown links or unfamiliar MFA prompts
- Keep your OS and browser up to date
- Use the corporate password manager and MFA on everything`
    ]
  ];
  const trainingStmt = db.prepare(`INSERT INTO training_modules
    (tenant_id, title, description, category, required_roles, duration_minutes, owner, renewal_months, passing_score, status, content)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);
  const moduleIds = trainingRows.map(r => trainingStmt.run(tenantId, ...r).lastInsertRowid);

  // Pre-signed attestation for the demo user on the BCM 101 module
  const demoUser = db.prepare('SELECT id, name, email FROM users WHERE tenant_id = ? LIMIT 1').get(tenantId);
  if (demoUser && moduleIds.length) {
    db.prepare(`INSERT INTO training_attestations
      (tenant_id, module_id, user_id, user_name, user_email, signature, score, ip, user_agent, expires_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, date('now','+12 months'))`)
      .run(tenantId, moduleIds[0], demoUser.id, demoUser.name, demoUser.email, demoUser.name, 95, '127.0.0.1', 'seed');
  }

  // Documents + RAG index
  const plans = db.prepare('SELECT id, title, content FROM bcp_plans WHERE tenant_id = ?').all(tenantId);
  const docStmt = db.prepare(`INSERT INTO documents
    (tenant_id, title, source_kind, filename, mime, bytes, uploaded_by, tags, content, linked_plan_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);
  plans.forEach(p => {
    const info = docStmt.run(
      tenantId, p.title, 'plan', null, 'text/markdown',
      Buffer.byteLength(p.content || '', 'utf8'),
      'Demo Admin', 'seed', p.content || '', p.id
    );
    rag.indexDocument(tenantId, info.lastInsertRowid, p.content || '');
  });
  // Add a standalone policy
  const policyText = `# Acme Global — Access Control Policy

## Purpose
Govern how we grant, review, and revoke access to production systems and sensitive data
in line with ISO 27001 and our ISO 22301 business continuity program.

## Scope
All employees, contractors, and third parties with access to Acme Global information assets.

## Principles
- Least privilege — users receive the minimum access necessary.
- Segregation of duties — no single person can both request and approve privileged access.
- Just-in-time — privileged access is time-bound and re-verified quarterly.

## Access review
Access reviews run every 90 days. Owners must certify all entitlements for their team or
flag them for removal within 10 business days of the review open date.

## Joiner-mover-leaver
- **Joiner** — access provisioned within 2 business days of start date; MFA enrolled day 1.
- **Mover** — access reset to role defaults within 5 business days of role change.
- **Leaver** — access revoked within 2 hours of termination notification; physical access
  revoked same day.

## Privileged accounts
Privileged (admin / root) access requires a documented business justification, owner approval,
and quarterly recertification. Break-glass accounts are logged to the SIEM and reviewed weekly.

## Incidents
Suspected account compromise must be reported within 1 hour. Containment targets:
- Disable the account within 15 minutes of confirmation
- Rotate all secrets the account had access to within 4 hours
- Post-incident review within 5 business days
`;
  const polInfo = docStmt.run(
    tenantId, 'Access Control Policy', 'policy', 'access-control.md', 'text/markdown',
    Buffer.byteLength(policyText, 'utf8'), 'Demo Admin', 'seed, security', policyText, null
  );
  rag.indexDocument(tenantId, polInfo.lastInsertRowid, policyText);

  // Dependency graph — nodes and edges
  const nodeStmt = db.prepare(`INSERT INTO dependency_nodes
    (tenant_id, node_type, name, description, criticality, ref_table, ref_id)
    VALUES (?, ?, ?, ?, ?, ?, ?)`);
  const N = (type, name, desc, crit, refTbl = null, refId = null) =>
    nodeStmt.run(tenantId, type, name, desc, crit, refTbl, refId).lastInsertRowid;

  const nOrders = N('process', 'Online order processing', 'Primary revenue channel', 'Critical', 'bia_records', null);
  const nPayroll = N('process', 'Payroll processing', 'Biweekly staff payroll', 'High', 'bia_records', null);
  const nWMS = N('process', 'Warehouse management', 'Pick-pack-ship orchestration', 'Critical', 'bia_records', null);
  const nCRM = N('system', 'CRM', 'Customer relationship management platform', 'High');
  const nERP = N('system', 'ERP', 'Enterprise resource planning system', 'High');
  const nStripe = N('vendor', 'Stripe', 'Payments processor', 'High', 'vendors', null);
  const nAWS = N('vendor', 'AWS eu-west-1', 'Primary hosting region', 'Critical', 'vendors', null);
  const nSupplier = N('vendor', 'Supplier X', 'Sole-source raw materials supplier', 'Critical', 'vendors', null);
  const nLondon = N('site', 'London HQ', 'Head office and primary DC', 'High');
  const nSec = N('site', 'Dublin secondary', 'Secondary data center', 'Medium');
  const nSRE = N('team', 'SRE / Platform', 'On-call engineering team', 'High');
  const nCustData = N('data', 'Customer PII', 'Names, emails, order history', 'Critical');

  const edgeStmt = db.prepare(`INSERT INTO dependency_edges
    (tenant_id, source_id, target_id, label, strength, notes) VALUES (?, ?, ?, ?, ?, ?)`);
  const E = (src, tgt, label = 'depends_on', strength = 4, note = null) =>
    edgeStmt.run(tenantId, src, tgt, label, strength, note);

  E(nOrders, nCRM);
  E(nOrders, nStripe, 'depends_on', 5, 'Payment gateway');
  E(nOrders, nAWS, 'hosts', 5);
  E(nOrders, nCustData, 'feeds', 4);
  E(nWMS, nERP);
  E(nWMS, nSupplier, 'depends_on', 5, 'Inbound component Y');
  E(nWMS, nAWS, 'hosts', 4);
  E(nCRM, nAWS, 'hosts', 4);
  E(nERP, nAWS, 'hosts', 4);
  E(nPayroll, nERP, 'depends_on', 3);
  E(nAWS, nLondon, 'fails_over_to', 3, 'Manual cut-over to London DC');
  E(nAWS, nSec, 'fails_over_to', 4);
  E(nSRE, nAWS, 'supports', 5);
}

function main() {
  const tenant = upsertTenant();
  const user = upsertUser(tenant.id);
  seedDomain(tenant.id);
  console.log('\nDemo workspace ready:');
  console.log('  Workspace : ' + tenant.name + ' (' + tenant.slug + ')');
  console.log('  Email     : ' + DEMO_EMAIL);
  console.log('  Password  : ' + DEMO_PASSWORD);
  console.log('');
  process.exit(0);
}

main();
