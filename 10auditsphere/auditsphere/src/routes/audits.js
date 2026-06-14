const express = require('express');
const router  = express.Router();
const { v4: uuid } = require('uuid');
const db      = require('../database');

function now() { return new Date().toISOString(); }
const today   = () => new Date().toISOString().slice(0,10);

/* ── FRAMEWORKS ── */
router.get('/frameworks', (_req, res) => {
  res.json(db.all('SELECT * FROM frameworks ORDER BY name'));
});

router.post('/frameworks', (req, res) => {
  const { name, description, color, type } = req.body;
  if (!name) return res.status(400).json({ error: 'Name required' });
  const id = 'fw-' + uuid().slice(0,8);
  db.run('INSERT INTO frameworks (id,name,description,color,type,is_custom,created_at) VALUES (?,?,?,?,?,1,?)',
    [id, name, description||'', color||'#4f8ef7', type||'Custom', now()]);
  res.json({ success: true, id });
});

/* ── AUDITS ── */
router.get('/audits', (_req, res) => {
  const audits = db.all(`
    SELECT a.*, f.name as framework_name, f.color as framework_color,
           u.name as lead_name
    FROM audits a
    JOIN frameworks f ON a.framework_id = f.id
    LEFT JOIN users u ON a.lead_id = u.id
    ORDER BY a.created_at DESC
  `);

  const todayStr = today();
  for (const a of audits) {
    const controls = db.all('SELECT status, due_date FROM controls WHERE audit_id = ?', [a.id]);
    a.total_controls    = controls.length;
    a.complete_controls = controls.filter(c => c.status === 'complete').length;
    a.overdue_controls  = controls.filter(c => c.status !== 'complete' && c.due_date && c.due_date < todayStr).length;
    a.completion_pct    = a.total_controls > 0 ? Math.round(a.complete_controls / a.total_controls * 100) : 0;
  }
  res.json(audits);
});

router.post('/audits', (req, res) => {
  const { name, framework_id, audit_type, auditor, lead_id, start_date, audit_date } = req.body;
  if (!name)        return res.status(400).json({ error: 'Name required' });
  if (!framework_id) return res.status(400).json({ error: 'Framework required' });
  const id = uuid();
  db.run(
    `INSERT INTO audits (id,name,framework_id,audit_type,auditor,lead_id,start_date,audit_date,created_at)
     VALUES (?,?,?,?,?,?,?,?,?)`,
    [id, name, framework_id, audit_type||'External', auditor||'', lead_id||null, start_date||null, audit_date||null, now()]
  );
  res.json({ success: true, id });
});

router.get('/audits/:id', (req, res) => {
  const audit = db.get(`
    SELECT a.*, f.name as framework_name, f.color as framework_color, u.name as lead_name
    FROM audits a
    JOIN frameworks f ON a.framework_id = f.id
    LEFT JOIN users u ON a.lead_id = u.id
    WHERE a.id = ?
  `, [req.params.id]);
  if (!audit) return res.status(404).json({ error: 'Not found' });

  const controls = db.all(`
    SELECT c.*, u.name as assigned_name, u.avatar_initials,
           COUNT(e.id) as evidence_count
    FROM controls c
    LEFT JOIN users u ON c.assigned_to = u.id
    LEFT JOIN evidence e ON e.control_id = c.id
    WHERE c.audit_id = ?
    GROUP BY c.id
    ORDER BY c.created_at
  `, [req.params.id]);

  const todayStr = today();
  audit.controls         = controls;
  audit.total_controls   = controls.length;
  audit.complete_controls= controls.filter(c => c.status === 'complete').length;
  audit.pending_controls = controls.filter(c => c.status !== 'complete' && (!c.due_date || c.due_date >= todayStr)).length;
  audit.overdue_controls = controls.filter(c => c.status !== 'complete' && c.due_date && c.due_date < todayStr).length;
  audit.completion_pct   = audit.total_controls > 0 ? Math.round(audit.complete_controls / audit.total_controls * 100) : 0;

  res.json(audit);
});

router.patch('/audits/:id', (req, res) => {
  const audit = db.get('SELECT id FROM audits WHERE id = ?', [req.params.id]);
  if (!audit) return res.status(404).json({ error: 'Not found' });

  const { name, auditor, lead_id, start_date, audit_date, status } = req.body;
  const sets = []; const vals = [];
  const f = (col, val) => { if (val !== undefined) { sets.push(`${col}=?`); vals.push(val||null); }};
  f('name', name); f('auditor', auditor); f('lead_id', lead_id);
  f('start_date', start_date); f('audit_date', audit_date); f('status', status);
  if (sets.length) { vals.push(req.params.id); db.run(`UPDATE audits SET ${sets.join(',')} WHERE id=?`, vals); }
  res.json({ success: true });
});

router.delete('/audits/:id', (req, res) => {
  // cascade
  const controls = db.all('SELECT id FROM controls WHERE audit_id = ?', [req.params.id]);
  for (const c of controls) {
    db.run('DELETE FROM evidence WHERE control_id = ?', [c.id]);
    db.run('DELETE FROM comments WHERE control_id = ?', [c.id]);
    db.run('DELETE FROM reminders WHERE control_id = ?', [c.id]);
  }
  db.run('DELETE FROM controls WHERE audit_id = ?', [req.params.id]);
  db.run('DELETE FROM audits WHERE id = ?', [req.params.id]);
  res.json({ success: true });
});

module.exports = router;
