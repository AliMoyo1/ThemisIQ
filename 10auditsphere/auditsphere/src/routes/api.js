const express = require('express');
const router = express.Router();
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const xlsx = require('xlsx');
const bcrypt = require('bcryptjs');
const db = require('../db/schema');
const AI = require('../services/ai');
const Email = require('../services/email');
const { generateAuditReport } = require('../services/reports');
require('dotenv').config();

// Multer setup
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    const dir = path.resolve(process.env.UPLOAD_PATH || './public/uploads');
    fs.mkdirSync(dir, { recursive: true });
    cb(null, dir);
  },
  filename: (req, file, cb) => {
    const ext = path.extname(file.originalname);
    cb(null, `${Date.now()}-${Math.random().toString(36).slice(2)}${ext}`);
  }
});
const upload = multer({ storage, limits: { fileSize: 50 * 1024 * 1024 } });

function log(userId, action, type, id, details) {
  try {
    db.prepare('INSERT INTO activity_log (user_id,action,entity_type,entity_id,details) VALUES (?,?,?,?,?)').run(userId, action, type, id, details ? JSON.stringify(details) : null);
  } catch(e) {}
}

// ─── AUTH ────────────────────────────────────────────────────────────────────

router.post('/auth/login', (req, res) => {
  const { email, password } = req.body;
  const user = db.prepare('SELECT * FROM users WHERE email=?').get(email);
  if (!user || !bcrypt.compareSync(password, user.password_hash)) {
    return res.status(401).json({ error: 'Invalid credentials' });
  }
  req.session.userId = user.id;
  req.session.userRole = user.role;
  res.json({ id: user.id, name: user.name, email: user.email, role: user.role });
});

router.post('/auth/logout', (req, res) => {
  req.session.destroy();
  res.json({ ok: true });
});

router.get('/auth/me', (req, res) => {
  if (!req.session.userId) return res.status(401).json({ error: 'Not logged in' });
  const user = db.prepare('SELECT id,name,email,role FROM users WHERE id=?').get(req.session.userId);
  res.json(user);
});

// ─── FRAMEWORKS ──────────────────────────────────────────────────────────────

router.get('/frameworks', (req, res) => {
  const rows = db.prepare('SELECT * FROM frameworks WHERE active=1 ORDER BY name').all();
  res.json(rows);
});

router.post('/frameworks', (req, res) => {
  const { name, description, color, type } = req.body;
  const result = db.prepare('INSERT INTO frameworks (name,description,color,type) VALUES (?,?,?,?)').run(name, description, color || '#4f8ef7', type || 'Security');
  log(req.session.userId, 'created', 'framework', result.lastInsertRowid, { name });
  res.json({ id: result.lastInsertRowid, name, description, color, type });
});

router.delete('/frameworks/:id', (req, res) => {
  db.prepare('UPDATE frameworks SET active=0 WHERE id=?').run(req.params.id);
  res.json({ ok: true });
});

// ─── AUDITS ──────────────────────────────────────────────────────────────────

router.get('/audits', (req, res) => {
  const rows = db.prepare(`
    SELECT a.*, f.name as framework_name, f.color as framework_color, u.name as lead_name,
    (SELECT COUNT(*) FROM controls WHERE audit_id=a.id) as total_controls,
    (SELECT COUNT(*) FROM controls WHERE audit_id=a.id AND status='Complete') as complete_controls
    FROM audits a
    LEFT JOIN frameworks f ON a.framework_id=f.id
    LEFT JOIN users u ON a.lead_id=u.id
    ORDER BY a.created_at DESC
  `).all();
  res.json(rows);
});

router.get('/audits/:id', (req, res) => {
  const audit = db.prepare(`SELECT a.*,f.name as framework_name,f.color as framework_color FROM audits a LEFT JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?`).get(req.params.id);
  if (!audit) return res.status(404).json({ error: 'Not found' });
  const controls = db.prepare(`
    SELECT c.*, u.name as assignee_name,
    (SELECT COUNT(*) FROM evidence_items WHERE control_id=c.id) as evidence_total,
    (SELECT COUNT(*) FROM evidence_files WHERE control_id=c.id) as evidence_uploaded
    FROM controls c LEFT JOIN users u ON c.assignee_id=u.id WHERE c.audit_id=? ORDER BY c.control_id`).all(req.params.id);
  const timeline = db.prepare('SELECT * FROM audit_timeline WHERE audit_id=? ORDER BY date').all(req.params.id);
  res.json({ ...audit, controls, timeline });
});

router.post('/audits', (req, res) => {
  const { name, framework_id, audit_type, auditor, lead_id, start_date, audit_date } = req.body;
  const result = db.prepare('INSERT INTO audits (name,framework_id,audit_type,auditor,lead_id,start_date,audit_date) VALUES (?,?,?,?,?,?,?)').run(name, framework_id, audit_type || 'External', auditor, lead_id, start_date, audit_date);
  const id = result.lastInsertRowid;
  // Auto-create timeline milestones
  if (start_date && audit_date) {
    const start = new Date(start_date);
    const end = new Date(audit_date);
    const mid = new Date((start.getTime() + end.getTime()) / 2);
    const fmt = d => d.toISOString().split('T')[0];
    [
      { title: 'Kick-off meeting', date: fmt(start), status: 'Pending' },
      { title: 'Evidence collection opens', date: fmt(new Date(start.getTime() + 7*86400000)), status: 'Pending' },
      { title: 'Internal review deadline', date: fmt(mid), status: 'Pending' },
      { title: 'Auditor evidence submission', date: fmt(new Date(end.getTime() - 14*86400000)), status: 'Pending' },
      { title: 'External audit date', date: fmt(end), status: 'Pending' }
    ].forEach(m => db.prepare('INSERT INTO audit_timeline (audit_id,title,date,status) VALUES (?,?,?,?)').run(id, m.title, m.date, m.status));
  }
  log(req.session.userId, 'created', 'audit', id, { name });
  res.json({ id, name });
});

router.patch('/audits/:id', (req, res) => {
  const { status, auditor, audit_date } = req.body;
  const fields = [], vals = [];
  if (status !== undefined) { fields.push('status=?'); vals.push(status); }
  if (auditor !== undefined) { fields.push('auditor=?'); vals.push(auditor); }
  if (audit_date !== undefined) { fields.push('audit_date=?'); vals.push(audit_date); }
  if (fields.length) { vals.push(req.params.id); db.prepare(`UPDATE audits SET ${fields.join(',')} WHERE id=?`).run(...vals); }
  res.json({ ok: true });
});

router.delete('/audits/:id', (req, res) => {
  db.prepare('DELETE FROM audits WHERE id=?').run(req.params.id);
  res.json({ ok: true });
});

// ─── CONTROLS ────────────────────────────────────────────────────────────────

router.get('/controls', (req, res) => {
  const { audit_id, status, risk_level } = req.query;
  let q = `SELECT c.*,u.name as assignee_name,
    (SELECT COUNT(*) FROM evidence_items WHERE control_id=c.id) as evidence_total,
    (SELECT COUNT(*) FROM evidence_files WHERE control_id=c.id) as evidence_uploaded
    FROM controls c LEFT JOIN users u ON c.assignee_id=u.id WHERE 1=1`;
  const params = [];
  if (audit_id) { q += ' AND c.audit_id=?'; params.push(audit_id); }
  if (status) { q += ' AND c.status=?'; params.push(status); }
  if (risk_level) { q += ' AND c.risk_level=?'; params.push(risk_level); }
  q += ' ORDER BY c.control_id';
  res.json(db.prepare(q).all(...params));
});

router.post('/controls', (req, res) => {
  const { audit_id, framework_id, control_id, name, description, risk_level, assignee_id, due_date, evidence_required } = req.body;
  const result = db.prepare('INSERT INTO controls (audit_id,framework_id,control_id,name,description,risk_level,assignee_id,due_date) VALUES (?,?,?,?,?,?,?,?)').run(audit_id, framework_id, control_id, name, description, risk_level || 'Medium', assignee_id || null, due_date || null);
  const cid = result.lastInsertRowid;
  if (evidence_required && Array.isArray(evidence_required)) {
    evidence_required.forEach(ev => db.prepare('INSERT INTO evidence_items (control_id,name) VALUES (?,?)').run(cid, ev));
  }
  log(req.session.userId, 'created', 'control', cid, { name });
  res.json({ id: cid, name });
});

router.patch('/controls/:id', (req, res) => {
  const { status, assignee_id, due_date, notes } = req.body;
  const fields = [], vals = [];
  if (status !== undefined) { fields.push('status=?'); vals.push(status); }
  if (assignee_id !== undefined) { fields.push('assignee_id=?'); vals.push(assignee_id); }
  if (due_date !== undefined) { fields.push('due_date=?'); vals.push(due_date); }
  if (notes !== undefined) { fields.push('notes=?'); vals.push(notes); }
  if (fields.length) { vals.push(req.params.id); db.prepare(`UPDATE controls SET ${fields.join(',')} WHERE id=?`).run(...vals); }
  // Auto-update status based on evidence
  const ctrl = db.prepare('SELECT * FROM controls WHERE id=?').get(req.params.id);
  if (ctrl) {
    const total = db.prepare('SELECT COUNT(*) as c FROM evidence_items WHERE control_id=?').get(req.params.id).c;
    const uploaded = db.prepare('SELECT COUNT(*) as c FROM evidence_files WHERE control_id=?').get(req.params.id).c;
    if (total > 0 && uploaded >= total && !status) db.prepare("UPDATE controls SET status='Complete' WHERE id=?").run(req.params.id);
    else if (uploaded > 0 && !status) db.prepare("UPDATE controls SET status='In Progress' WHERE id=?").run(req.params.id);
  }
  log(req.session.userId, 'updated', 'control', req.params.id, req.body);
  res.json({ ok: true });
});

router.delete('/controls/:id', (req, res) => {
  db.prepare('DELETE FROM evidence_items WHERE control_id=?').run(req.params.id);
  db.prepare('DELETE FROM evidence_files WHERE control_id=?').run(req.params.id);
  db.prepare('DELETE FROM controls WHERE id=?').run(req.params.id);
  res.json({ ok: true });
});

// ─── EVIDENCE ────────────────────────────────────────────────────────────────

router.get('/evidence/:controlId', (req, res) => {
  const items = db.prepare('SELECT * FROM evidence_items WHERE control_id=?').all(req.params.controlId);
  const files = db.prepare('SELECT ef.*,u.name as uploader_name FROM evidence_files ef LEFT JOIN users u ON ef.uploaded_by=u.id WHERE ef.control_id=? ORDER BY ef.created_at DESC').all(req.params.controlId);
  res.json({ items, files });
});

router.post('/evidence/upload', upload.single('file'), async (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'No file uploaded' });
  const { control_id, evidence_item_id, notes, expires_at } = req.body;
  const ctrl = db.prepare('SELECT * FROM controls WHERE id=?').get(control_id);
  const result = db.prepare('INSERT INTO evidence_files (control_id,evidence_item_id,filename,original_name,file_path,file_size,mime_type,uploaded_by,notes,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)').run(
    control_id, evidence_item_id || null, req.file.filename, req.file.originalname,
    req.file.path, req.file.size, req.file.mimetype,
    req.session.userId || 1, notes || null, expires_at || null
  );
  // Auto-update control status
  const total = db.prepare('SELECT COUNT(*) as c FROM evidence_items WHERE control_id=?').get(control_id)?.c || 0;
  const uploaded = db.prepare('SELECT COUNT(*) as c FROM evidence_files WHERE control_id=?').get(control_id).c;
  if (total > 0 && uploaded >= total) db.prepare("UPDATE controls SET status='Complete' WHERE id=?").run(control_id);
  else db.prepare("UPDATE controls SET status='In Progress' WHERE id=?").run(control_id);
  log(req.session.userId, 'uploaded', 'evidence', result.lastInsertRowid, { file: req.file.originalname, control_id });
  // AI review
  let aiReview = null;
  if (ctrl) {
    try { aiReview = await AI.reviewEvidence(ctrl.name, ctrl.description, req.file.originalname, req.file.mimetype); } catch(e) {}
  }
  res.json({ id: result.lastInsertRowid, filename: req.file.filename, ai_review: aiReview });
});

router.patch('/evidence/files/:id/approve', (req, res) => {
  const { status } = req.body;
  db.prepare("UPDATE evidence_files SET status=?,approved_by=?,approved_at=CURRENT_TIMESTAMP WHERE id=?").run(status || 'Approved', req.session.userId || 1, req.params.id);
  res.json({ ok: true });
});

router.delete('/evidence/files/:id', (req, res) => {
  const file = db.prepare('SELECT * FROM evidence_files WHERE id=?').get(req.params.id);
  if (file) {
    try { fs.unlinkSync(file.file_path); } catch(e) {}
    db.prepare('DELETE FROM evidence_files WHERE id=?').run(req.params.id);
  }
  res.json({ ok: true });
});

// ─── CHECKLIST IMPORT ────────────────────────────────────────────────────────

router.post('/import/checklist', upload.single('file'), async (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'No file' });
  const { audit_id, framework_id, framework_name } = req.body;

  let rawText = '';
  const ext = path.extname(req.file.originalname).toLowerCase();

  try {
    if (ext === '.xlsx' || ext === '.xls' || ext === '.csv') {
      const wb = xlsx.readFile(req.file.path);
      const ws = wb.Sheets[wb.SheetNames[0]];
      const rows = xlsx.utils.sheet_to_json(ws, { defval: '' });
      rawText = rows.map(r => Object.values(r).join(' | ')).join('\n');
      // Try direct column mapping first
      const directControls = rows.filter(r => r.name || r.Name || r.control || r.Control).map(r => ({
        control_id: r.control_id || r['Control ID'] || r.ID || '',
        name: r.name || r.Name || r.control || r.Control || r.description || '',
        description: r.description || r.Description || r.details || '',
        risk_level: r.risk || r.Risk || r.risk_level || 'Medium',
        evidence_required: (r.evidence || r.Evidence || '').split(',').map(s=>s.trim()).filter(Boolean)
      })).filter(c => c.name);
      if (directControls.length > 0) {
        const insertCtrl = db.prepare('INSERT INTO controls (audit_id,framework_id,control_id,name,description,risk_level) VALUES (?,?,?,?,?,?)');
        const insertEv = db.prepare('INSERT INTO evidence_items (control_id,name) VALUES (?,?)');
        directControls.forEach(c => {
          const r = insertCtrl.run(audit_id, framework_id, c.control_id, c.name, c.description, c.risk_level);
          c.evidence_required.forEach(e => insertEv.run(r.lastInsertRowid, e));
        });
        return res.json({ method: 'direct', count: directControls.length });
      }
    } else {
      rawText = fs.readFileSync(req.file.path, 'utf-8').slice(0, 10000);
    }
    // Use AI to parse
    const controls = await AI.parseChecklist(rawText, framework_name || 'ISO 27001');
    const insertCtrl = db.prepare('INSERT INTO controls (audit_id,framework_id,control_id,name,description,risk_level) VALUES (?,?,?,?,?,?)');
    const insertEv = db.prepare('INSERT INTO evidence_items (control_id,name) VALUES (?,?)');
    controls.forEach(c => {
      const r = insertCtrl.run(audit_id, framework_id, c.control_id || '', c.name, c.description || '', c.risk_level || 'Medium');
      (c.evidence_required || []).forEach(e => insertEv.run(r.lastInsertRowid, e));
    });
    res.json({ method: 'ai', count: controls.length });
  } catch (err) {
    console.error('Import error:', err);
    res.status(500).json({ error: err.message });
  }
});

// ─── AI ENDPOINTS ────────────────────────────────────────────────────────────

router.post('/ai/suggest-evidence', async (req, res) => {
  try {
    const { control_id } = req.body;
    const ctrl = db.prepare('SELECT c.*,f.name as framework FROM controls c LEFT JOIN frameworks f ON c.framework_id=f.id WHERE c.id=?').get(control_id);
    if (!ctrl) return res.status(404).json({ error: 'Control not found' });
    const suggestions = await AI.suggestEvidence(ctrl);
    // Save suggestions as evidence items if not already present
    const existing = db.prepare('SELECT name FROM evidence_items WHERE control_id=?').all(control_id).map(e => e.name.toLowerCase());
    suggestions.filter(s => !existing.includes(s.toLowerCase())).forEach(s => {
      db.prepare('INSERT INTO evidence_items (control_id,name) VALUES (?,?)').run(control_id, s);
    });
    res.json({ suggestions });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

router.post('/ai/audit-health', async (req, res) => {
  try {
    const { audit_id } = req.body;
    const audit = db.prepare('SELECT a.*,f.name as framework_name FROM audits a LEFT JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?').get(audit_id);
    if (!audit) return res.status(404).json({ error: 'Audit not found' });
    const total = db.prepare('SELECT COUNT(*) as c FROM controls WHERE audit_id=?').get(audit_id).c;
    const complete = db.prepare("SELECT COUNT(*) as c FROM controls WHERE audit_id=? AND status='Complete'").get(audit_id).c;
    const inProgress = db.prepare("SELECT COUNT(*) as c FROM controls WHERE audit_id=? AND status='In Progress'").get(audit_id).c;
    const overdue = db.prepare("SELECT COUNT(*) as c FROM controls WHERE audit_id=? AND due_date < date('now') AND status!='Complete'").get(audit_id).c;
    const missingEvidence = db.prepare("SELECT COUNT(*) as c FROM evidence_items ei WHERE ei.control_id IN (SELECT id FROM controls WHERE audit_id=?) AND NOT EXISTS (SELECT 1 FROM evidence_files ef WHERE ef.evidence_item_id=ei.id)").get(audit_id).c;
    const criticalPending = db.prepare("SELECT COUNT(*) as c FROM controls WHERE audit_id=? AND risk_level='Critical' AND status!='Complete'").get(audit_id).c;
    const daysToAudit = audit.audit_date ? Math.ceil((new Date(audit.audit_date) - new Date()) / 86400000) : null;
    const analysis = await AI.analyzeAuditHealth({
      name: audit.name, framework: audit.framework_name,
      daysToAudit, completionPct: total > 0 ? Math.round(complete/total*100) : 0,
      totalControls: total, complete, inProgress, notStarted: total-complete-inProgress,
      overdue, missingEvidence, criticalPending
    });
    res.json(analysis);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

router.post('/ai/cross-framework', async (req, res) => {
  try {
    const { control_id } = req.body;
    const ctrl = db.prepare('SELECT c.*,f.name as framework FROM controls c LEFT JOIN frameworks f ON c.framework_id=f.id WHERE c.id=?').get(control_id);
    if (!ctrl) return res.status(404).json({ error: 'Not found' });
    const allFws = db.prepare('SELECT name FROM frameworks WHERE active=1').all().map(f => f.name).filter(f => f !== ctrl.framework);
    const mappings = await AI.mapCrossFramework(ctrl.name, ctrl.description, ctrl.framework, allFws);
    res.json({ mappings });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── REPORTS ────────────────────────────────────────────────────────────────

router.post('/reports/generate', async (req, res) => {
  try {
    const { audit_id, format } = req.body;
    const audit = db.prepare('SELECT a.*,f.name as framework_name FROM audits a LEFT JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?').get(audit_id);
    if (!audit) return res.status(404).json({ error: 'Audit not found' });
    const controls = db.prepare(`SELECT c.*,(SELECT COUNT(*) FROM evidence_items WHERE control_id=c.id) as evidence_total,(SELECT COUNT(*) FROM evidence_files WHERE control_id=c.id) as evidence_uploaded FROM controls c WHERE c.audit_id=?`).all(audit_id);
    const total = controls.length, complete = controls.filter(c => c.status === 'Complete').length;
    const overdue = controls.filter(c => c.due_date && new Date(c.due_date) < new Date() && c.status !== 'Complete').length;
    const daysToAudit = audit.audit_date ? Math.ceil((new Date(audit.audit_date) - new Date()) / 86400000) : 0;
    const reportData = {
      name: audit.name, framework: audit.framework_name,
      audit_date: audit.audit_date, auditor: audit.auditor,
      totalControls: total, complete, overdue,
      completionPct: total > 0 ? Math.round(complete/total*100) : 0,
      daysToAudit, health_score: total > 0 ? Math.round(complete/total*100) : 0,
      controls
    };
    const narrative = await AI.generateReportNarrative(reportData);
    const pdfBuffer = await generateAuditReport(reportData, narrative);
    if (format === 'email' && req.body.email) {
      await Email.sendAuditReport(req.body.email, audit.name, pdfBuffer);
      return res.json({ ok: true, message: 'Report emailed' });
    }
    res.setHeader('Content-Type', 'application/pdf');
    res.setHeader('Content-Disposition', `attachment; filename="${audit.name.replace(/[^a-z0-9]/gi,'_')}_report.pdf"`);
    res.send(pdfBuffer);
  } catch (err) {
    console.error('Report error:', err);
    res.status(500).json({ error: err.message });
  }
});

// ─── REMINDERS ───────────────────────────────────────────────────────────────

router.post('/reminders/send', async (req, res) => {
  const { audit_id } = req.body;
  const controls = db.prepare(`
    SELECT c.*,u.name as assignee_name,u.email as assignee_email
    FROM controls c LEFT JOIN users u ON c.assignee_id=u.id
    WHERE c.audit_id=? AND c.status!='Complete' AND u.email IS NOT NULL
  `).all(audit_id);
  const byUser = {};
  controls.forEach(c => {
    if (!byUser[c.assignee_email]) byUser[c.assignee_email] = { name: c.assignee_name, items: [] };
    byUser[c.assignee_email].items.push({ control_id: c.control_id, name: c.name, due_date: c.due_date, status: c.due_date && new Date(c.due_date) < new Date() ? 'Overdue' : 'Pending' });
  });
  const results = [];
  for (const [email, data] of Object.entries(byUser)) {
    const r = await Email.sendReminderEmail(email, data.name, data.items);
    results.push({ email, ...r });
  }
  res.json({ results });
});

// ─── USERS ───────────────────────────────────────────────────────────────────

router.get('/users', (req, res) => {
  res.json(db.prepare('SELECT id,name,email,role,created_at FROM users ORDER BY name').all());
});

router.post('/users', async (req, res) => {
  const { name, email, password, role } = req.body;
  const hash = bcrypt.hashSync(password || 'changeme123', 10);
  try {
    const r = db.prepare('INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?)').run(name, email, hash, role || 'owner');
    res.json({ id: r.lastInsertRowid, name, email, role });
  } catch(e) { res.status(400).json({ error: 'Email already exists' }); }
});

// ─── ACTIVITY LOG ────────────────────────────────────────────────────────────

router.get('/activity', (req, res) => {
  const rows = db.prepare(`SELECT a.*,u.name as user_name FROM activity_log a LEFT JOIN users u ON a.user_id=u.id ORDER BY a.created_at DESC LIMIT 50`).all();
  res.json(rows);
});

// ─── DASHBOARD STATS ─────────────────────────────────────────────────────────

router.get('/stats/:audit_id', (req, res) => {
  const id = req.params.audit_id;
  const total = db.prepare('SELECT COUNT(*) as c FROM controls WHERE audit_id=?').get(id).c;
  const complete = db.prepare("SELECT COUNT(*) as c FROM controls WHERE audit_id=? AND status='Complete'").get(id).c;
  const inProgress = db.prepare("SELECT COUNT(*) as c FROM controls WHERE audit_id=? AND status='In Progress'").get(id).c;
  const overdue = db.prepare("SELECT COUNT(*) as c FROM controls WHERE audit_id=? AND due_date < date('now') AND status!='Complete'").get(id).c;
  const evidenceTotal = db.prepare('SELECT COUNT(*) as c FROM evidence_items ei JOIN controls c ON ei.control_id=c.id WHERE c.audit_id=?').get(id).c;
  const evidenceUploaded = db.prepare('SELECT COUNT(*) as c FROM evidence_files ef JOIN controls c ON ef.control_id=c.id WHERE c.audit_id=?').get(id).c;
  const audit = db.prepare('SELECT audit_date FROM audits WHERE id=?').get(id);
  const daysToAudit = audit?.audit_date ? Math.ceil((new Date(audit.audit_date) - new Date()) / 86400000) : null;
  res.json({ total, complete, inProgress, notStarted: total-complete-inProgress, overdue, evidenceTotal, evidenceUploaded, daysToAudit, completionPct: total>0 ? Math.round(complete/total*100) : 0 });
});

module.exports = router;
