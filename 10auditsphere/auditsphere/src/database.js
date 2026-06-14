const path     = require('path');
const fs       = require('fs');
const initSqlJs = require('sql.js');

const DB_PATH = path.join(__dirname, '../data/auditsphere.db');
fs.mkdirSync(path.dirname(DB_PATH), { recursive: true });

let _db = null;

function persist() {
  if (!_db) return;
  fs.writeFileSync(DB_PATH, Buffer.from(_db.export()));
}

function all(sql, params = []) {
  const stmt = _db.prepare(sql);
  if (params.length) stmt.bind(params);
  const rows = [];
  while (stmt.step()) rows.push(stmt.getAsObject());
  stmt.free();
  return rows;
}
function get(sql, params = []) { return all(sql, params)[0]; }
function run(sql, params = []) { _db.run(sql, params); persist(); }
function exec(sql) { _db.run(sql); persist(); }
function prepare(sql) {
  return {
    run:(...a) => { run(sql, a.flat()); return { changes: _db.getRowsModified() }; },
    all:(...a) => all(sql, a.flat()),
    get:(...a)  => get(sql, a.flat()),
  };
}
function transaction(fn) {
  return function(...args) {
    _db.run('BEGIN');
    try { fn(...args); _db.run('COMMIT'); persist(); }
    catch(e) { _db.run('ROLLBACK'); throw e; }
  };
}

const SCHEMA = `
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
  password TEXT NOT NULL, role TEXT DEFAULT 'member',
  avatar_initials TEXT, department TEXT,
  last_login TEXT, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS frameworks (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
  color TEXT DEFAULT '#1a6b3a', type TEXT DEFAULT 'Security',
  is_custom INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS audits (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, framework_id TEXT NOT NULL,
  audit_type TEXT DEFAULT 'External', status TEXT DEFAULT 'planning',
  auditor TEXT, lead_id TEXT, start_date TEXT, audit_date TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS controls (
  id TEXT PRIMARY KEY, audit_id TEXT NOT NULL, control_id TEXT,
  name TEXT NOT NULL, description TEXT, risk_level TEXT DEFAULT 'Medium',
  status TEXT DEFAULT 'not_started', assigned_to TEXT, due_date TEXT,
  evidence_required INTEGER DEFAULT 1, notes TEXT,
  category TEXT, framework_ref TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY, control_id TEXT NOT NULL, audit_id TEXT NOT NULL,
  name TEXT NOT NULL, description TEXT, file_path TEXT, file_name TEXT,
  file_size INTEGER, file_type TEXT, status TEXT DEFAULT 'pending',
  uploaded_by TEXT, approved_by TEXT, approved_at TEXT,
  expiry_date TEXT, expiry_notified INTEGER DEFAULT 0,
  onedrive_id TEXT, onedrive_url TEXT,
  version INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS evidence_versions (
  id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL, file_path TEXT,
  file_name TEXT, version INTEGER, uploaded_by TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS comments (
  id TEXT PRIMARY KEY, control_id TEXT NOT NULL, user_id TEXT,
  user_name TEXT, content TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS reminders (
  id TEXT PRIMARY KEY, control_id TEXT NOT NULL, user_email TEXT NOT NULL,
  frequency TEXT DEFAULT 'weekly', last_sent TEXT, active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS activity_log (
  id TEXT PRIMARY KEY, action TEXT NOT NULL, entity_type TEXT,
  entity_id TEXT, entity_name TEXT, user_id TEXT, user_name TEXT,
  details TEXT, ip_address TEXT, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS approval_stages (
  id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  status TEXT DEFAULT 'pending',
  assigned_to TEXT, assigned_email TEXT,
  comment TEXT, acted_at TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS share_links (
  id TEXT PRIMARY KEY, audit_id TEXT NOT NULL,
  token TEXT UNIQUE NOT NULL, label TEXT,
  created_by TEXT, expires_at TEXT,
  last_accessed TEXT, access_count INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS non_conformances (
  id TEXT PRIMARY KEY, audit_id TEXT NOT NULL, control_id TEXT,
  title TEXT NOT NULL, description TEXT, severity TEXT DEFAULT 'Major',
  raised_by TEXT, owner_id TEXT, owner_email TEXT,
  root_cause TEXT, corrective_action TEXT,
  status TEXT DEFAULT 'open', due_date TEXT, closed_at TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS vendors (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, contact_name TEXT,
  contact_email TEXT, category TEXT, risk_level TEXT DEFAULT 'Medium',
  compliance_frameworks TEXT, last_assessed TEXT, next_assessment TEXT,
  certificate_expiry TEXT, status TEXT DEFAULT 'active', notes TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS vendor_assessments (
  id TEXT PRIMARY KEY, vendor_id TEXT NOT NULL, assessed_by TEXT,
  score INTEGER, findings TEXT, action_required TEXT,
  next_due TEXT, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS control_mappings (
  id TEXT PRIMARY KEY, control_id_a TEXT NOT NULL, control_id_b TEXT NOT NULL,
  mapping_type TEXT DEFAULT 'equivalent', notes TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS digest_subscriptions (
  id TEXT PRIMARY KEY, email TEXT NOT NULL, name TEXT,
  frequency TEXT DEFAULT 'weekly', day_of_week INTEGER DEFAULT 1,
  audit_ids TEXT DEFAULT 'all', active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS scheduled_reports (
  id TEXT PRIMARY KEY, audit_id TEXT NOT NULL, email TEXT NOT NULL,
  frequency TEXT DEFAULT 'monthly', format TEXT DEFAULT 'both',
  last_sent TEXT, active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS api_keys (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT UNIQUE NOT NULL,
  key_prefix TEXT NOT NULL, created_by TEXT, last_used TEXT,
  permissions TEXT DEFAULT 'read', active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS compliance_scores (
  id TEXT PRIMARY KEY, audit_id TEXT NOT NULL,
  score INTEGER, total_controls INTEGER, complete_controls INTEGER,
  recorded_at TEXT DEFAULT (datetime('now'))
);
`;

async function init() {
  const SQL = await initSqlJs();
  _db = fs.existsSync(DB_PATH)
    ? new SQL.Database(fs.readFileSync(DB_PATH))
    : new SQL.Database();

  SCHEMA.split(';').map(s => s.trim()).filter(Boolean).forEach(s => _db.run(s));
  persist();
  await seed();
  console.log('✅ Database ready');
}

async function seed() {
  const fwCount = get('SELECT COUNT(*) as c FROM frameworks').c;
  if (!fwCount) {
    const fws = [
      ['fw-iso27001','ISO 27001','Information security management systems','#1a6b3a','Security'],
      ['fw-iso42001','ISO 42001','AI management systems','#7c3aed','AI Governance'],
      ['fw-soc2','SOC 2 Type II','Service organization control','#2563eb','Security'],
      ['fw-pcidss','PCI DSS','Payment card security standard','#d97706','Financial'],
      ['fw-gdpr','GDPR','General data protection regulation','#0891b2','Privacy'],
      ['fw-zcdpa','Zimbabwe CDPA','Zimbabwe Cyber and Data Protection Act','#059669','Privacy'],
      ['fw-hipaa','HIPAA','Health insurance portability act','#dc2626','Healthcare'],
    ];
    for (const f of fws) run('INSERT OR IGNORE INTO frameworks (id,name,description,color,type) VALUES (?,?,?,?,?)', f);
  }
  const uCount = get('SELECT COUNT(*) as c FROM users').c;
  if (!uCount) {
    const bcrypt = require('bcryptjs');
    const { v4: uuid } = require('uuid');
    run('INSERT INTO users (id,name,email,password,role,avatar_initials) VALUES (?,?,?,?,?,?)',
      [uuid(), 'Admin User', 'admin@auditsphere.local', bcrypt.hashSync('admin123', 10), 'admin', 'AU']);
  }
}

module.exports = { init, prepare, run, all, get, exec, transaction };
