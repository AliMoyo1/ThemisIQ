const Database = require('better-sqlite3');
const path = require('path');
require('dotenv').config();

const dbPath = process.env.DB_PATH || './data/auditsphere.db';
const db = new Database(path.resolve(dbPath));

db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'viewer', -- admin, auditor, owner, viewer
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS frameworks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    color TEXT DEFAULT '#4f8ef7',
    type TEXT DEFAULT 'Security',
    active INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    framework_id INTEGER NOT NULL,
    audit_type TEXT DEFAULT 'External',
    auditor TEXT,
    lead_id INTEGER,
    start_date TEXT,
    audit_date TEXT,
    status TEXT DEFAULT 'Planning', -- Planning, Active, Review, Complete
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (framework_id) REFERENCES frameworks(id),
    FOREIGN KEY (lead_id) REFERENCES users(id)
  );

  CREATE TABLE IF NOT EXISTS controls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id INTEGER NOT NULL,
    framework_id INTEGER NOT NULL,
    control_id TEXT,
    name TEXT NOT NULL,
    description TEXT,
    risk_level TEXT DEFAULT 'Medium', -- Critical, High, Medium, Low
    status TEXT DEFAULT 'Not Started', -- Not Started, In Progress, Complete
    assignee_id INTEGER,
    due_date TEXT,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (audit_id) REFERENCES audits(id),
    FOREIGN KEY (framework_id) REFERENCES frameworks(id),
    FOREIGN KEY (assignee_id) REFERENCES users(id)
  );

  CREATE TABLE IF NOT EXISTS evidence_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    control_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    required INTEGER DEFAULT 1,
    FOREIGN KEY (control_id) REFERENCES controls(id)
  );

  CREATE TABLE IF NOT EXISTS evidence_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_item_id INTEGER,
    control_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    mime_type TEXT,
    uploaded_by INTEGER,
    status TEXT DEFAULT 'Uploaded', -- Uploaded, Approved, Rejected
    approved_by INTEGER,
    approved_at DATETIME,
    version INTEGER DEFAULT 1,
    expires_at TEXT,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (evidence_item_id) REFERENCES evidence_items(id),
    FOREIGN KEY (control_id) REFERENCES controls(id),
    FOREIGN KEY (uploaded_by) REFERENCES users(id)
  );

  CREATE TABLE IF NOT EXISTS audit_timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    date TEXT NOT NULL,
    status TEXT DEFAULT 'Pending', -- Pending, Done, Overdue
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (audit_id) REFERENCES audits(id)
  );

  CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    control_id INTEGER,
    audit_id INTEGER,
    user_id INTEGER NOT NULL,
    frequency TEXT DEFAULT 'weekly', -- daily, weekly, none
    last_sent DATETIME,
    active INTEGER DEFAULT 1,
    FOREIGN KEY (control_id) REFERENCES controls(id),
    FOREIGN KEY (audit_id) REFERENCES audits(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
  );

  CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    details TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS ai_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    control_id INTEGER,
    audit_id INTEGER,
    suggestion_type TEXT,
    content TEXT,
    status TEXT DEFAULT 'Pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );
`);

// Seed default data if empty
const fwCount = db.prepare('SELECT COUNT(*) as c FROM frameworks').get();
if (fwCount.c === 0) {
  const insertFw = db.prepare('INSERT INTO frameworks (name, description, color, type) VALUES (?, ?, ?, ?)');
  [
    ['ISO 27001', 'Information security management standard', '#4f8ef7', 'Security'],
    ['ISO 42001', 'AI management system standard', '#b06ef5', 'AI Governance'],
    ['SOC 2 Type II', 'Service organization controls', '#3ecf84', 'Security'],
    ['PCI DSS', 'Payment card industry data security standard', '#f5a623', 'Financial'],
    ['GDPR', 'General data protection regulation', '#2dcdc8', 'Privacy'],
    ['Zimbabwe CDPA', 'Cyber and Data Protection Act', '#3ecf84', 'Privacy'],
    ['HIPAA', 'Health insurance portability act', '#f25c5c', 'Healthcare'],
  ].forEach(fw => insertFw.run(...fw));

  // Seed a default admin user (password: admin123)
  const bcrypt = require('bcryptjs');
  const hash = bcrypt.hashSync('admin123', 10);
  db.prepare('INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)').run('Admin User', 'admin@auditsphere.local', hash, 'admin');
  db.prepare('INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)').run('T. Moyo', 'tmoyo@auditsphere.local', hash, 'owner');
  db.prepare('INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)').run('S. Khumalo', 'skhumalo@auditsphere.local', hash, 'owner');
}

module.exports = db;
