const express = require('express');
const router = express.Router();
const multer = require('multer');
const XLSX = require('xlsx');
const path = require('path');
const fs = require('fs');
const { v4: uuidv4 } = require('uuid');
const db = require('../models/db');
const ai = require('../services/ai');
const { sendReminder } = require('../services/email');
const { generateAuditReport } = require('../services/report');

// Multer config
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    const dir = path.join(__dirname, '..', 'uploads', 'evidence');
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    cb(null, dir);
  },
  filename: (req, file, cb) => cb(null, `${uuidv4()}-${file.originalname}`)
});
const upload = multer({ storage, limits: { fileSize: 50 * 1024 * 1024 } });

// ---- FRAMEWORKS ----
router.get('/frameworks', (req, res) => {
  const frameworks = db.prepare(`
    SELECT f.*, COUNT(DISTINCT a.id) as audit_count
    FROM frameworks f LEFT JOIN audits a ON f.id = a.framework_id
    WHERE f.is_active = 1
    GROUP BY f.id ORDER BY f.name
  `).all();
  res.json(frameworks);
});

router.post('/frameworks', (req, res) => {
  const { name, description, color, type } = req.body;
  if (!name) return res.status(400).json({ error: 'Name required' });
  const id = uuidv4();
  db.prepare('INSERT INTO frameworks (id, name, description, color, type) VALUES (?, ?, ?, ?, ?)').run(id, name, description || '', color || '#4f8ef7', type || 'Security');
  logAction('framework', id, 'created', { name });
  res.json({ id, name });
});

// ---- AUDITS ----
router.get('/audits', (req, res) => {
  const { framework_id } = req.query;
  let q = `SELECT a.*, f.name as framework_name, f.color as framework_color,
    COUNT(DISTINCT c.id) as total_controls,
    COUNT(DISTINCT CASE WHEN c.status='Complete' THEN c.id END) as completed_controls,
    julianday(a.audit_date) - julianday('now') as days_remaining
    FROM audits a JOIN frameworks f ON a.framework_id = f.id
    LEFT JOIN controls c ON a.id = c.audit_id`;
  const params = [];
  if (framework_id) { q += ' WHERE a.framework_id = ?'; params.push(framework_id); }
  q += ' GROUP BY a.id ORDER BY a.created_at DESC';
  res.json(db.prepare(q).all(...params));
});

router.post('/audits', (req, res) => {
  const { framework_id, name, audit_type, auditor, audit_lead, start_date, audit_date } = req.body;
  if (!framework_id || !name) return res.status(400).json({ error: 'framework_id and name required' });
  const id = uuidv4();
  db.prepare('INSERT INTO audits (id, framework_id, name, audit_type, auditor, audit_lead, start_date, audit_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)').run(id, framework_id, name, audit_type || 'External', auditor || '', audit_lead || '', start_date || '', audit_date || '');
  logAction('audit', id, 'created', { name });
  res.json({ id, name });
});

router.get('/audits/:id', (req, res) => {
  const audit = db.prepare(`
    SELECT a.*, f.name as framework_name, f.color,
    julianday(a.audit_date) - julianday('now') as days_remaining
    FROM audits a JOIN frameworks f ON a.framework_id = f.id WHERE a.id = ?
  `).get(req.params.id);
  if (!audit) return res.status(404).json({ error: 'Not found' });
  res.json(audit);
});

router.patch('/audits/:id', (req, res) => {
  const { name, audit_type, auditor, audit_lead, start_date, audit_date, status } = req.body;
  db.prepare('UPDATE audits SET name=COALESCE(?,name), audit_type=COALESCE(?,audit_type), auditor=COALESCE(?,auditor), audit_lead=COALESCE(?,audit_lead), start_date=COALESCE(?,start_date), audit_date=COALESCE(?,audit_date), status=COALESCE(?,status) WHERE id=?').run(name, audit_type, auditor, audit_lead, start_date, audit_date, status, req.params.id);
  res.json({ success: true });
});

// ---- CONTROLS ----
router.get('/controls', (req, res) => {
  const { audit_id, status, risk_level } = req.query;
  if (!audit_id) return res.status(400).json({ error: 'audit_id required' });
  let q = `SELECT c.*,
    COUNT(DISTINCT e.id) as ev_count,
    COUNT(DISTINCT er.id) as ev_req
    FROM controls c
    LEFT JOIN evidence e ON e.control_id = c.id
    LEFT JOIN evidence_requirements er ON er.control_id = c.id
    WHERE c.audit_id = ?`;
  const params = [audit_id];
  if (status) { q += ' AND c.status = ?'; params.push(status); }
  if (risk_level) { q += ' AND c.risk_level = ?'; params.push(risk_level); }
  q += ' GROUP BY c.id ORDER BY c.control_id';
  res.json(db.prepare(q).all(...params));
});

router.post('/controls', (req, res) => {
  const { audit_id, framework_id, control_id, name, description, risk_level, assigned_to, assigned_email, due_date } = req.body;
  if (!audit_id || !name) return res.status(400).json({ error: 'audit_id and name required' });
  const fwId = framework_id || db.prepare('SELECT framework_id FROM audits WHERE id=?').get(audit_id)?.framework_id;
  const id = uuidv4();
  db.prepare('INSERT INTO controls (id, audit_id, framework_id, control_id, name, description, risk_level, assigned_to, assigned_email, due_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)').run(id, audit_id, fwId, control_id || '', name, description || '', risk_level || 'Medium', assigned_to || '', assigned_email || '', due_date || '');
  logAction('control', id, 'created', { control_id, name });
  res.json({ id, name });
});

router.patch('/controls/:id', (req, res) => {
  const { name, description, risk_level, assigned_to, assigned_email, due_date, status, notes } = req.body;
  db.prepare(`UPDATE controls SET
    name=COALESCE(?,name), description=COALESCE(?,description),
    risk_level=COALESCE(?,risk_level), assigned_to=COALESCE(?,assigned_to),
    assigned_email=COALESCE(?,assigned_email), due_date=COALESCE(?,due_date),
    status=COALESCE(?,status), notes=COALESCE(?,notes) WHERE id=?`)
    .run(name, description, risk_level, assigned_to, assigned_email, due_date, status, notes, req.params.id);
  logAction('control', req.params.id, 'updated', req.body);
  res.json({ success: true });
});

router.delete('/controls/:id', (req, res) => {
  db.prepare('DELETE FROM controls WHERE id=?').run(req.params.id);
  res.json({ success: true });
});

// ---- EVIDENCE REQUIREMENTS ----
router.get('/controls/:id/requirements', (req, res) => {
  res.json(db.prepare('SELECT * FROM evidence_requirements WHERE control_id=?').all(req.params.id));
});

router.post('/controls/:id/requirements', (req, res) => {
  const { description } = req.body;
  const id = uuidv4();
  db.prepare('INSERT INTO evidence_requirements (id, control_id, description) VALUES (?, ?, ?)').run(id, req.params.id, description);
  res.json({ id, description });
});

router.patch('/requirements/:id', (req, res) => {
  const { is_satisfied, evidence_id } = req.body;
  db.prepare('UPDATE evidence_requirements SET is_satisfied=?, evidence_id=? WHERE id=?').run(is_satisfied ? 1 : 0, evidence_id || null, req.params.id);
  res.json({ success: true });
});

// ---- EVIDENCE ----
router.get('/evidence', (req, res) => {
  const { audit_id, control_id } = req.query;
  let q = `SELECT e.*, c.control_id as ctrl_ref, c.name as control_name FROM evidence e LEFT JOIN controls c ON e.control_id = c.id WHERE 1=1`;
  const params = [];
  if (audit_id) { q += ' AND e.audit_id=?'; params.push(audit_id); }
  if (control_id) { q += ' AND e.control_id=?'; params.push(control_id); }
  q += ' ORDER BY e.uploaded_at DESC';
  res.json(db.prepare(q).all(...params));
});

router.post('/evidence/upload', upload.single('file'), async (req, res) => {
  const { control_id, audit_id, description, uploaded_by, expires_at } = req.body;
  if (!req.file) return res.status(400).json({ error: 'No file uploaded' });
  const id = uuidv4();
  db.prepare('INSERT INTO evidence (id, control_id, audit_id, name, description, filename, original_name, file_type, file_size, status, uploaded_by, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)').run(id, control_id, audit_id, req.file.originalname, description || '', req.file.filename, req.file.originalname, req.file.mimetype, req.file.size, 'Uploaded', uploaded_by || 'User', expires_at || null);

  // Auto-analyze evidence with AI
  let aiResult = null;
  try {
    const text = await extractTextFromFile(req.file);
    if (text && process.env.ANTHROPIC_API_KEY) {
      const controls = db.prepare('SELECT * FROM controls WHERE audit_id=?').all(audit_id);
      aiResult = await ai.analyzeEvidence(text, controls);
    }
  } catch (e) { console.log('AI analysis skipped:', e.message); }

  logAction('evidence', id, 'uploaded', { file: req.file.originalname, control_id });
  res.json({ id, filename: req.file.originalname, aiResult });
});

router.patch('/evidence/:id', (req, res) => {
  const { status, notes } = req.body;
  db.prepare('UPDATE evidence SET status=COALESCE(?,status), notes=COALESCE(?,notes) WHERE id=?').run(status, notes, req.params.id);
  res.json({ success: true });
});

router.delete('/evidence/:id', (req, res) => {
  const ev = db.prepare('SELECT filename FROM evidence WHERE id=?').get(req.params.id);
  if (ev) {
    const fp = path.join(__dirname, '..', 'uploads', 'evidence', ev.filename);
    if (fs.existsSync(fp)) fs.unlinkSync(fp);
    db.prepare('DELETE FROM evidence WHERE id=?').run(req.params.id);
  }
  res.json({ success: true });
});

router.get('/evidence/:id/download', (req, res) => {
  const ev = db.prepare('SELECT * FROM evidence WHERE id=?').get(req.params.id);
  if (!ev) return res.status(404).json({ error: 'Not found' });
  const fp = path.join(__dirname, '..', 'uploads', 'evidence', ev.filename);
  if (!fs.existsSync(fp)) return res.status(404).json({ error: 'File not found' });
  res.download(fp, ev.original_name);
});

// ---- CHECKLIST IMPORT ----
router.post('/import/checklist', upload.single('file'), async (req, res) => {
  const { audit_id } = req.body;
  if (!req.file || !audit_id) return res.status(400).json({ error: 'File and audit_id required' });

  const audit = db.prepare('SELECT a.*, f.name as framework_name FROM audits a JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?').get(audit_id);
  if (!audit) return res.status(404).json({ error: 'Audit not found' });

  let extractedControls = [];
  let parseMethod = 'excel';

  try {
    if (req.file.mimetype.includes('sheet') || req.file.originalname.endsWith('.xlsx') || req.file.originalname.endsWith('.xls')) {
      // Parse Excel
      const wb = XLSX.readFile(req.file.path);
      const ws = wb.Sheets[wb.SheetNames[0]];
      const data = XLSX.utils.sheet_to_json(ws, { defval: '' });

      if (data.length > 0 && process.env.ANTHROPIC_API_KEY) {
        // Use AI to map columns
        const text = data.slice(0, 50).map(r => Object.entries(r).map(([k,v]) => `${k}: ${v}`).join(' | ')).join('\n');
        const parsed = await ai.parseChecklistWithAI(text, audit.framework_name);
        extractedControls = parsed.controls;
        parseMethod = 'ai-excel';
      } else {
        // Fallback: map common column names
        extractedControls = data.map(row => ({
          control_id: row['Control ID'] || row['ID'] || row['Ref'] || '',
          name: row['Control Name'] || row['Name'] || row['Control'] || row['Description'] || Object.values(row)[1] || '',
          description: row['Description'] || row['Details'] || '',
          risk_level: row['Risk'] || row['Risk Level'] || 'Medium',
          evidence_requirements: []
        })).filter(c => c.name);
      }
    } else {
      // PDF or text — use AI
      const text = fs.readFileSync(req.file.path, 'utf8').substring(0, 8000);
      if (process.env.ANTHROPIC_API_KEY) {
        const parsed = await ai.parseChecklistWithAI(text, audit.framework_name);
        extractedControls = parsed.controls;
        parseMethod = 'ai-pdf';
      }
    }
  } catch (e) {
    console.error('Import error:', e);
    return res.status(500).json({ error: 'Failed to parse file: ' + e.message });
  }

  // Insert controls into DB
  let inserted = 0;
  const insertCtrl = db.prepare('INSERT INTO controls (id, audit_id, framework_id, control_id, name, description, risk_level) VALUES (?, ?, ?, ?, ?, ?, ?)');
  const insertReq = db.prepare('INSERT INTO evidence_requirements (id, control_id, description) VALUES (?, ?, ?)');

  const insertAll = db.transaction(() => {
    for (const ctrl of extractedControls) {
      if (!ctrl.name) continue;
      const cid = uuidv4();
      insertCtrl.run(cid, audit_id, audit.framework_id, ctrl.control_id || '', ctrl.name, ctrl.description || '', ctrl.risk_level || 'Medium');
      (ctrl.evidence_requirements || []).forEach(req => insertReq.run(uuidv4(), cid, req));
      inserted++;
    }
  });
  insertAll();

  // Cleanup temp file
  fs.unlinkSync(req.file.path);
  logAction('audit', audit_id, 'checklist_imported', { count: inserted, method: parseMethod });
  res.json({ success: true, inserted, parseMethod, total: extractedControls.length });
});

// ---- REMINDERS ----
router.get('/reminders', (req, res) => {
  const { audit_id } = req.query;
  res.json(db.prepare(`
    SELECT r.*, c.control_id as ctrl_ref, c.name as control_name
    FROM reminders r JOIN controls c ON r.control_id=c.id WHERE r.audit_id=?
  `).all(audit_id));
});

router.post('/reminders', (req, res) => {
  const { control_id, audit_id, email, frequency } = req.body;
  if (!control_id || !email) return res.status(400).json({ error: 'control_id and email required' });
  const id = uuidv4();
  db.prepare('INSERT INTO reminders (id, control_id, audit_id, email, frequency) VALUES (?, ?, ?, ?, ?)').run(id, control_id, audit_id, email, frequency || 'weekly');
  res.json({ id });
});

router.post('/reminders/:id/send-now', async (req, res) => {
  const reminder = db.prepare('SELECT r.*, c.control_id, c.name, c.risk_level, c.due_date, f.name as framework_name FROM reminders r JOIN controls c ON r.control_id=c.id JOIN audits a ON r.audit_id=a.id JOIN frameworks f ON a.framework_id=f.id WHERE r.id=?').get(req.params.id);
  if (!reminder) return res.status(404).json({ error: 'Not found' });
  const result = await sendReminder(reminder, reminder);
  res.json(result);
});

// ---- AI ENDPOINTS ----
router.post('/ai/gap-analysis', async (req, res) => {
  if (!process.env.ANTHROPIC_API_KEY) return res.status(400).json({ error: 'ANTHROPIC_API_KEY not configured' });
  const { audit_id } = req.body;
  const audit = db.prepare('SELECT a.*, f.name as framework_name, julianday(a.audit_date)-julianday("now") as days_remaining FROM audits a JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?').get(audit_id);
  const controls = db.prepare('SELECT c.*, COUNT(e.id) as evidence_count FROM controls c LEFT JOIN evidence e ON e.control_id=c.id WHERE c.audit_id=? GROUP BY c.id').all(audit_id);
  try {
    const result = await ai.generateGapAnalysis(audit, controls, {});
    const id = uuidv4();
    db.prepare('INSERT INTO ai_analyses (id, audit_id, analysis_type, result) VALUES (?, ?, ?, ?)').run(id, audit_id, 'gap_analysis', JSON.stringify(result));
    res.json(result);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.post('/ai/generate-requirements', async (req, res) => {
  if (!process.env.ANTHROPIC_API_KEY) return res.status(400).json({ error: 'ANTHROPIC_API_KEY not configured' });
  const { control_id } = req.body;
  const control = db.prepare('SELECT c.*, f.name as framework_name FROM controls c JOIN audits a ON c.audit_id=a.id JOIN frameworks f ON a.framework_id=f.id WHERE c.id=?').get(control_id);
  if (!control) return res.status(404).json({ error: 'Control not found' });
  try {
    const result = await ai.generateEvidenceRequirements(control, control.framework_name);
    // Save to DB
    const insertReq = db.prepare('INSERT INTO evidence_requirements (id, control_id, description) VALUES (?, ?, ?)');
    const insertAll = db.transaction(() => result.requirements.forEach(r => insertReq.run(uuidv4(), control_id, r)));
    insertAll();
    res.json(result);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.post('/ai/chat', async (req, res) => {
  if (!process.env.ANTHROPIC_API_KEY) return res.status(400).json({ error: 'ANTHROPIC_API_KEY not configured' });
  const { message, audit_id } = req.body;
  const audit = db.prepare('SELECT a.*, f.name as framework_name FROM audits a JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?').get(audit_id);
  const controls = db.prepare('SELECT * FROM controls WHERE audit_id=? LIMIT 30').all(audit_id);
  try {
    const reply = await ai.auditChat(message, { ...audit, controls_summary: `${controls.filter(c=>c.status==='Complete').length}/${controls.length} complete` });
    res.json({ reply });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// ---- REPORTS ----
router.get('/reports/pdf/:audit_id', async (req, res) => {
  const audit = db.prepare('SELECT a.*, f.name as framework_name FROM audits a JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?').get(req.params.audit_id);
  if (!audit) return res.status(404).json({ error: 'Audit not found' });
  const controls = db.prepare(`
    SELECT c.*, COUNT(DISTINCT e.id) as ev_count, COUNT(DISTINCT er.id) as ev_req
    FROM controls c LEFT JOIN evidence e ON e.control_id=c.id LEFT JOIN evidence_requirements er ON er.control_id=c.id
    WHERE c.audit_id=? GROUP BY c.id ORDER BY c.control_id
  `).all(req.params.audit_id);
  const evidence = db.prepare('SELECT e.*, c.control_id as control_name FROM evidence e LEFT JOIN controls c ON e.control_id=c.id WHERE e.audit_id=?').all(req.params.audit_id);

  let narrative = {};
  if (process.env.ANTHROPIC_API_KEY) {
    try { narrative = await ai.generateReportNarrative(audit, controls, evidence); } catch (e) {}
  }

  try {
    const pdf = await generateAuditReport(audit, controls, evidence, narrative);
    res.setHeader('Content-Type', 'application/pdf');
    res.setHeader('Content-Disposition', `attachment; filename="${audit.name.replace(/[^a-z0-9]/gi,'_')}_Report.pdf"`);
    res.send(pdf);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

router.get('/reports/excel/:audit_id', (req, res) => {
  const audit = db.prepare('SELECT a.*, f.name as framework_name FROM audits a JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?').get(req.params.audit_id);
  const controls = db.prepare('SELECT c.*, COUNT(e.id) as ev_count FROM controls c LEFT JOIN evidence e ON e.control_id=c.id WHERE c.audit_id=? GROUP BY c.id ORDER BY c.control_id').all(req.params.audit_id);
  const evidence = db.prepare('SELECT e.*, c.control_id as ctrl_ref, c.name as control_name FROM evidence e LEFT JOIN controls c ON e.control_id=c.id WHERE e.audit_id=?').all(req.params.audit_id);

  const wb = XLSX.utils.book_new();

  // Controls sheet
  const ctrlData = controls.map(c => ({
    'Control ID': c.control_id, 'Name': c.name, 'Description': c.description,
    'Risk Level': c.risk_level, 'Status': c.status,
    'Assigned To': c.assigned_to, 'Due Date': c.due_date,
    'Evidence Count': c.ev_count, 'Notes': c.notes
  }));
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(ctrlData), 'Controls');

  // Evidence sheet
  const evData = evidence.map(e => ({
    'Control': e.ctrl_ref + ' - ' + e.control_name, 'File Name': e.original_name,
    'Description': e.description, 'Status': e.status,
    'Uploaded By': e.uploaded_by, 'Uploaded At': e.uploaded_at, 'Expires': e.expires_at
  }));
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(evData), 'Evidence');

  // Summary sheet
  const completed = controls.filter(c => c.status === 'Complete').length;
  const summaryData = [
    { Metric: 'Audit Name', Value: audit.name },
    { Metric: 'Framework', Value: audit.framework_name },
    { Metric: 'Audit Type', Value: audit.audit_type },
    { Metric: 'Auditor', Value: audit.auditor },
    { Metric: 'Audit Date', Value: audit.audit_date },
    { Metric: 'Total Controls', Value: controls.length },
    { Metric: 'Completed', Value: completed },
    { Metric: 'Completion %', Value: controls.length > 0 ? `${Math.round(completed/controls.length*100)}%` : '0%' },
    { Metric: 'Evidence Items', Value: evidence.length },
    { Metric: 'Report Generated', Value: new Date().toISOString() },
  ];
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(summaryData), 'Summary');

  const buf = XLSX.write(wb, { type: 'buffer', bookType: 'xlsx' });
  res.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
  res.setHeader('Content-Disposition', `attachment; filename="${(audit.name||'audit').replace(/[^a-z0-9]/gi,'_')}_Report.xlsx"`);
  res.send(buf);
});

// ---- DASHBOARD STATS ----
router.get('/dashboard/:audit_id', (req, res) => {
  const audit = db.prepare('SELECT a.*, f.name as framework_name, f.color, julianday(a.audit_date)-julianday("now") as days_remaining FROM audits a JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?').get(req.params.audit_id);
  if (!audit) return res.status(404).json({ error: 'Not found' });
  const controls = db.prepare('SELECT c.*, COUNT(DISTINCT e.id) as ev_count, COUNT(DISTINCT er.id) as ev_req FROM controls c LEFT JOIN evidence e ON e.control_id=c.id LEFT JOIN evidence_requirements er ON er.control_id=c.id WHERE c.audit_id=? GROUP BY c.id ORDER BY c.control_id').all(req.params.audit_id);
  const evidence = db.prepare('SELECT * FROM evidence WHERE audit_id=?').all(req.params.audit_id);
  const total = controls.length, completed = controls.filter(c=>c.status==='Complete').length;
  const overdue = controls.filter(c=>c.due_date && c.status!=='Complete' && new Date(c.due_date) < new Date()).length;
  const pending_ev = controls.filter(c=>c.status!=='Complete' && c.ev_count===0).length;
  res.json({ audit, controls, evidence, stats: { total, completed, overdue, pending_ev, completion_pct: total>0?Math.round(completed/total*100):0 } });
});

// ---- ACTIVITY LOG ----
router.get('/log', (req, res) => {
  const { audit_id } = req.query;
  res.json(db.prepare('SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 50').all());
});

// Helper
async function extractTextFromFile(file) {
  if (file.mimetype === 'text/plain') return fs.readFileSync(file.path, 'utf8');
  if (file.mimetype.includes('sheet') || file.originalname.endsWith('.xlsx')) {
    const wb = XLSX.readFile(file.path);
    return wb.SheetNames.map(n => XLSX.utils.sheet_to_csv(wb.Sheets[n])).join('\n');
  }
  return '';
}

function logAction(entity_type, entity_id, action, details) {
  try {
    db.prepare('INSERT INTO audit_log (id, entity_type, entity_id, action, details) VALUES (?, ?, ?, ?, ?)').run(uuidv4(), entity_type, entity_id, action, JSON.stringify(details));
  } catch (e) {}
}

module.exports = router;
