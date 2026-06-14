// Multi-tenant SQLite database using Node 22's built-in node:sqlite module.
// All domain tables carry a tenant_id column and all reads/writes must scope by it.

const { DatabaseSync } = require('node:sqlite');
const path = require('path');
const fs = require('fs');

// DATA_DIR can be overridden via env for deployments where the project folder
// is on a read-only or non-POSIX mount.
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, '..', 'data');
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

const db = new DatabaseSync(path.join(DATA_DIR, 'bcm.db'));
db.exec('PRAGMA foreign_keys = ON');
// Try to enable WAL for better concurrency, but gracefully fall back on filesystems
// that don't support memory-mapping (e.g. some network / FUSE mounts).
try { db.exec('PRAGMA journal_mode = WAL'); }
catch (e) { /* keep default DELETE journal mode */ }

function migrate() {
  db.exec(`
  CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    industry TEXT,
    ai_provider TEXT DEFAULT 'openai',
    ai_openai_key TEXT,
    ai_anthropic_key TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    avatar_color TEXT DEFAULT '#a3a380',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, email),
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS bia_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    process_name TEXT NOT NULL,
    department TEXT,
    owner TEXT,
    description TEXT,
    rto_hours INTEGER,
    rpo_hours INTEGER,
    financial_impact_per_day REAL,
    operational_impact INTEGER,
    reputational_impact INTEGER,
    regulatory_impact INTEGER,
    criticality TEXT,
    dependencies TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS risks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    category TEXT,
    description TEXT,
    likelihood INTEGER,
    impact INTEGER,
    score INTEGER,
    treatment TEXT,
    mitigation TEXT,
    owner TEXT,
    status TEXT DEFAULT 'open',
    due_date DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS bcp_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    scope TEXT,
    owner TEXT,
    version TEXT DEFAULT '1.0',
    status TEXT DEFAULT 'draft',
    content TEXT,
    last_reviewed DATE,
    next_review DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    severity TEXT,
    status TEXT DEFAULT 'open',
    commander TEXT,
    affected_systems TEXT,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS incident_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    incident_id INTEGER NOT NULL,
    author TEXT,
    note TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    provider TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    ref_table TEXT,
    ref_id INTEGER,
    send_to_email TEXT NOT NULL,
    subject TEXT,
    body TEXT,
    send_at DATETIME NOT NULL,
    sent_at DATETIME,
    status TEXT DEFAULT 'pending',
    error TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  -- ======================= Phase 2: Vendors =======================
  CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    service_provided TEXT,
    owner TEXT,
    contact_name TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    criticality TEXT,
    tier INTEGER DEFAULT 3,
    data_sensitivity TEXT,
    sla TEXT,
    contract_renewal DATE,
    risk_score INTEGER,
    financial_score INTEGER,
    operational_score INTEGER,
    compliance_score INTEGER,
    concentration_risk INTEGER,
    status TEXT DEFAULT 'active',
    notes TEXT,
    last_reviewed DATE,
    next_review DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS vendor_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    vendor_id INTEGER NOT NULL,
    assessed_on DATE DEFAULT CURRENT_DATE,
    assessor TEXT,
    score INTEGER,
    summary TEXT,
    findings TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(vendor_id) REFERENCES vendors(id) ON DELETE CASCADE,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  -- ======================= Phase 2: Exercises =======================
  CREATE TABLE IF NOT EXISTS exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    type TEXT,                    -- tabletop / walkthrough / simulation / full
    scenario TEXT,
    plan_id INTEGER,              -- optional link to bcp_plans
    scheduled_date DATE,
    duration_minutes INTEGER,
    facilitator TEXT,
    participants TEXT,
    objectives TEXT,
    status TEXT DEFAULT 'planned', -- planned / in_progress / completed / cancelled
    outcome TEXT,                 -- pass / partial / fail
    aar_summary TEXT,             -- after-action report summary
    aar_strengths TEXT,
    aar_gaps TEXT,
    aar_actions TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(plan_id) REFERENCES bcp_plans(id) ON DELETE SET NULL,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  -- ======================= Phase 2: Compliance (ISO 22301) =======================
  CREATE TABLE IF NOT EXISTS compliance_controls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    framework TEXT NOT NULL,      -- ISO 22301, SOC 2, NIST, etc.
    clause TEXT NOT NULL,         -- e.g. 4.1, 6.2, 8.4.2
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'not_started', -- not_started / in_progress / implemented / verified
    owner TEXT,
    evidence_notes TEXT,
    last_reviewed DATE,
    next_review DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS compliance_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    control_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    ref_url TEXT,
    notes TEXT,
    uploaded_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(control_id) REFERENCES compliance_controls(id) ON DELETE CASCADE,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  -- ======================= Phase 2: Audit log =======================
  CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER,
    user_id INTEGER,
    user_email TEXT,
    action TEXT NOT NULL,         -- CREATE / UPDATE / DELETE / LOGIN / LOGOUT / EXPORT / ...
    entity TEXT,                  -- vendors / risks / bcp_plans / users / ...
    entity_id INTEGER,
    summary TEXT,
    ip TEXT,
    user_agent TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );
  CREATE INDEX IF NOT EXISTS idx_audit_tenant_created ON audit_log(tenant_id, created_at DESC);
  CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity, entity_id);

  -- ======================= Phase 3: Training & attestation =======================
  CREATE TABLE IF NOT EXISTS training_modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,
    required_roles TEXT,           -- CSV: admin,manager,responder,viewer (blank = all)
    duration_minutes INTEGER,
    owner TEXT,
    content TEXT,                  -- Markdown body
    passing_score INTEGER DEFAULT 80,
    renewal_months INTEGER DEFAULT 12,  -- 0 = one-time
    status TEXT DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS training_attestations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    module_id INTEGER NOT NULL,
    user_id INTEGER,
    user_name TEXT,
    user_email TEXT,
    attested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    signature TEXT,                 -- typed full name as e-signature
    score INTEGER,
    ip TEXT,
    user_agent TEXT,
    expires_at DATE,
    FOREIGN KEY(module_id) REFERENCES training_modules(id) ON DELETE CASCADE,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );
  CREATE INDEX IF NOT EXISTS idx_attest_tenant_user ON training_attestations(tenant_id, user_id);
  CREATE INDEX IF NOT EXISTS idx_attest_module ON training_attestations(module_id);

  -- ======================= Phase 3: Documents + RAG =======================
  CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    source_kind TEXT,               -- plan / policy / runbook / contract / other
    filename TEXT,
    mime TEXT,
    bytes INTEGER,
    uploaded_by TEXT,
    tags TEXT,
    content TEXT,                   -- full extracted text
    chunk_count INTEGER DEFAULT 0,
    linked_plan_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(linked_plan_id) REFERENCES bcp_plans(id) ON DELETE SET NULL,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    document_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );
  CREATE INDEX IF NOT EXISTS idx_doc_chunks ON document_chunks(tenant_id, document_id);

  CREATE TABLE IF NOT EXISTS document_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    user_id INTEGER,
    question TEXT NOT NULL,
    answer TEXT,
    cited_chunk_ids TEXT,           -- CSV of chunk ids
    provider TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  -- ======================= Phase 3: Dependency graph =======================
  CREATE TABLE IF NOT EXISTS dependency_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    node_type TEXT NOT NULL,        -- process / system / vendor / site / team / asset / data
    name TEXT NOT NULL,
    description TEXT,
    criticality TEXT,               -- Critical / High / Medium / Low
    ref_table TEXT,                 -- optional back-link: bia_records / vendors / bcp_plans
    ref_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS dependency_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    label TEXT,                     -- depends_on / feeds / hosts / supports / fails_over_to
    strength INTEGER DEFAULT 3,     -- 1..5
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_id) REFERENCES dependency_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY(target_id) REFERENCES dependency_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );
  CREATE INDEX IF NOT EXISTS idx_dep_edges_src ON dependency_edges(source_id);
  CREATE INDEX IF NOT EXISTS idx_dep_edges_tgt ON dependency_edges(target_id);

  -- ======================= Phase 4: Incident command console =======================
  CREATE TABLE IF NOT EXISTS incident_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    incident_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    owner TEXT,
    status TEXT DEFAULT 'open',           -- open / in_progress / done / blocked
    priority TEXT DEFAULT 'normal',       -- low / normal / high / critical
    due_at DATETIME,
    completed_at DATETIME,
    notes TEXT,
    created_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE CASCADE,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );
  CREATE INDEX IF NOT EXISTS idx_incact_incident ON incident_actions(incident_id);

  CREATE TABLE IF NOT EXISTS incident_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    incident_id INTEGER NOT NULL,
    decision TEXT NOT NULL,
    rationale TEXT,
    decided_by TEXT,
    decided_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE CASCADE,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );
  CREATE INDEX IF NOT EXISTS idx_incdec_incident ON incident_decisions(incident_id);

  CREATE TABLE IF NOT EXISTS incident_stakeholders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    incident_id INTEGER NOT NULL,
    role TEXT NOT NULL,                   -- e.g. Executive sponsor, Legal, Comms, Customer success
    person TEXT,
    channel TEXT,                         -- phone / email / slack / in-person
    notified_at DATETIME,
    ack_at DATETIME,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE CASCADE,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );
  CREATE INDEX IF NOT EXISTS idx_incstake_incident ON incident_stakeholders(incident_id);

  CREATE TABLE IF NOT EXISTS incident_plan_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    incident_id INTEGER NOT NULL,
    plan_id INTEGER NOT NULL,
    linked_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(incident_id, plan_id),
    FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE CASCADE,
    FOREIGN KEY(plan_id) REFERENCES bcp_plans(id) ON DELETE CASCADE,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );

  -- ======================= Phase 4: AI plan reviewer =======================
  CREATE TABLE IF NOT EXISTS plan_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    plan_id INTEGER NOT NULL,
    reviewer_id INTEGER,
    reviewer_name TEXT,
    provider TEXT,
    overall_score INTEGER,               -- 0..100
    standards TEXT,                      -- CSV, e.g. "ISO 22301,NIST CSF"
    summary TEXT,
    strengths TEXT,
    gaps TEXT,
    recommendations TEXT,
    section_coverage TEXT,               -- JSON of detected/missing sections
    raw_response TEXT,                   -- full model output (audit trail)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(plan_id) REFERENCES bcp_plans(id) ON DELETE CASCADE,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );
  CREATE INDEX IF NOT EXISTS idx_planrev_plan ON plan_reviews(plan_id);

  -- ======================= Phase 4: BIA <-> BCP coverage links =======================
  -- Many-to-many link so one BIA process can be covered by multiple plans and
  -- one plan can cover multiple BIA processes. coverage_type lets us distinguish
  -- "this is THE plan for this process" (primary) from softer relationships
  -- (secondary / partial / referenced).
  CREATE TABLE IF NOT EXISTS bia_plan_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    bia_id INTEGER NOT NULL,
    plan_id INTEGER NOT NULL,
    coverage_type TEXT DEFAULT 'primary',  -- primary / secondary / partial / referenced
    notes TEXT,
    created_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bia_id, plan_id),
    FOREIGN KEY(bia_id) REFERENCES bia_records(id) ON DELETE CASCADE,
    FOREIGN KEY(plan_id) REFERENCES bcp_plans(id) ON DELETE CASCADE,
    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
  );
  CREATE INDEX IF NOT EXISTS idx_biaplan_bia ON bia_plan_links(bia_id);
  CREATE INDEX IF NOT EXISTS idx_biaplan_plan ON bia_plan_links(plan_id);
  `);
}

migrate();

// Convenience: run a function inside a transaction.
function transaction(fn) {
  return (...args) => {
    db.exec('BEGIN');
    try {
      const result = fn(...args);
      db.exec('COMMIT');
      return result;
    } catch (err) {
      db.exec('ROLLBACK');
      throw err;
    }
  };
}

db.transaction = transaction;

module.exports = db;
