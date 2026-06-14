const Database = require('better-sqlite3');
const path = require('path');

const DB_PATH = path.join(__dirname, '..', 'auditsphere.db');
const db = new Database(DB_PATH);

db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

db.exec(`
  CREATE TABLE IF NOT EXISTS frameworks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    color TEXT DEFAULT '#4f8ef7',
    type TEXT DEFAULT 'Security',
    created_at TEXT DEFAULT (datetime('now')),
    is_active INTEGER DEFAULT 1
  );

  CREATE TABLE IF NOT EXISTS audits (
    id TEXT PRIMARY KEY,
    framework_id TEXT NOT NULL,
    name TEXT NOT NULL,
    audit_type TEXT DEFAULT 'External',
    auditor TEXT,
    audit_lead TEXT,
    start_date TEXT,
    audit_date TEXT,
    status TEXT DEFAULT 'In Progress',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (framework_id) REFERENCES frameworks(id)
  );

  CREATE TABLE IF NOT EXISTS controls (
    id TEXT PRIMARY KEY,
    audit_id TEXT NOT NULL,
    framework_id TEXT NOT NULL,
    control_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    risk_level TEXT DEFAULT 'Medium',
    assigned_to TEXT,
    assigned_email TEXT,
    due_date TEXT,
    status TEXT DEFAULT 'Not Started',
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (audit_id) REFERENCES audits(id),
    FOREIGN KEY (framework_id) REFERENCES frameworks(id)
  );

  CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    control_id TEXT NOT NULL,
    audit_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    filename TEXT,
    original_name TEXT,
    file_type TEXT,
    file_size INTEGER,
    status TEXT DEFAULT 'Pending',
    uploaded_by TEXT,
    uploaded_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT,
    notes TEXT,
    FOREIGN KEY (control_id) REFERENCES controls(id),
    FOREIGN KEY (audit_id) REFERENCES audits(id)
  );

  CREATE TABLE IF NOT EXISTS evidence_requirements (
    id TEXT PRIMARY KEY,
    control_id TEXT NOT NULL,
    description TEXT NOT NULL,
    is_satisfied INTEGER DEFAULT 0,
    evidence_id TEXT,
    FOREIGN KEY (control_id) REFERENCES controls(id)
  );

  CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    control_id TEXT NOT NULL,
    audit_id TEXT NOT NULL,
    email TEXT NOT NULL,
    frequency TEXT DEFAULT 'weekly',
    last_sent TEXT,
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY (control_id) REFERENCES controls(id)
  );

  CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    entity_type TEXT,
    entity_id TEXT,
    action TEXT,
    details TEXT,
    user_name TEXT DEFAULT 'System',
    created_at TEXT DEFAULT (datetime('now'))
  );

  CREATE TABLE IF NOT EXISTS ai_analyses (
    id TEXT PRIMARY KEY,
    audit_id TEXT,
    control_id TEXT,
    analysis_type TEXT,
    result TEXT,
    created_at TEXT DEFAULT (datetime('now'))
  );
`);

// Seed default frameworks
const existing = db.prepare('SELECT COUNT(*) as c FROM frameworks').get();
if (existing.c === 0) {
  const { v4: uuidv4 } = require('uuid');
  const insert = db.prepare(`INSERT INTO frameworks (id, name, description, color, type) VALUES (?, ?, ?, ?, ?)`);
  const frameworks = [
    [uuidv4(), 'ISO 27001', 'Information Security Management', '#4f8ef7', 'Security'],
    [uuidv4(), 'ISO 42001', 'AI Management Systems', '#b06ef5', 'AI Governance'],
    [uuidv4(), 'SOC 2 Type II', 'Service Organization Controls', '#3ecf84', 'Security'],
    [uuidv4(), 'PCI DSS', 'Payment Card Industry Data Security', '#f5a623', 'Financial'],
    [uuidv4(), 'GDPR', 'General Data Protection Regulation', '#2dcdc8', 'Privacy'],
    [uuidv4(), 'Zimbabwe CDPA', 'Cyber and Data Protection Act', '#3ecf84', 'Privacy'],
    [uuidv4(), 'HIPAA', 'Health Insurance Portability Act', '#f25c5c', 'Healthcare'],
  ];
  const insertAll = db.transaction((fws) => fws.forEach(fw => insert.run(...fw)));
  insertAll(frameworks);
  console.log('Frameworks seeded');
}

module.exports = db;
