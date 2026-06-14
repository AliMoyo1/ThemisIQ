const express = require('express');
const router  = express.Router();
const { v4: uuid } = require('uuid');
const db      = require('../database');

function now() { return new Date().toISOString(); }

/* ── GET all controls for an audit ── */
router.get('/audits/:auditId/controls', (req, res) => {
  const { status, risk } = req.query;
  let rows = db.all(`
    SELECT c.*, u.name as assigned_name, u.avatar_initials,
           u.email as assigned_email, COUNT(e.id) as evidence_count
    FROM controls c
    LEFT JOIN users u ON c.assigned_to = u.id
    LEFT JOIN evidence e ON e.control_id = c.id
    WHERE c.audit_id = ?
    GROUP BY c.id ORDER BY c.created_at
  `, [req.params.auditId]);
  if (status) rows = rows.filter(r => r.status === status);
  if (risk)   rows = rows.filter(r => r.risk_level === risk);
  res.json(rows);
});

/* ── GET single control ── */
router.get('/controls/:id', (req, res) => {
  const ctrl = db.get(`
    SELECT c.*, u.name as assigned_name, u.avatar_initials, u.email as assigned_email,
           a.name as audit_name, f.name as framework_name
    FROM controls c
    LEFT JOIN users u ON c.assigned_to = u.id
    LEFT JOIN audits a ON c.audit_id = a.id
    LEFT JOIN frameworks f ON a.framework_id = f.id
    WHERE c.id = ?
  `, [req.params.id]);
  if (!ctrl) return res.status(404).json({ error: 'Not found' });
  ctrl.evidence  = db.all('SELECT * FROM evidence WHERE control_id = ? ORDER BY created_at', [req.params.id]);
  ctrl.comments  = db.all('SELECT * FROM comments WHERE control_id = ? ORDER BY created_at', [req.params.id]);
  ctrl.reminders = db.all('SELECT * FROM reminders WHERE control_id = ? AND active = 1', [req.params.id]);
  res.json(ctrl);
});

/* ── POST create control ── */
router.post('/audits/:auditId/controls', (req, res) => {
  const { control_id, name, description, risk_level, assigned_to, due_date, evidence_required, notes } = req.body;
  if (!name) return res.status(400).json({ error: 'Name required' });
  const id = uuid();
  db.run(
    `INSERT INTO controls (id,audit_id,control_id,name,description,risk_level,assigned_to,due_date,evidence_required,notes,created_at)
     VALUES (?,?,?,?,?,?,?,?,?,?,?)`,
    [id, req.params.auditId, control_id||'', name, description||'', risk_level||'Medium',
     assigned_to||null, due_date||null, evidence_required||1, notes||'', now()]
  );
  res.json({ success: true, id });
});

/* ── POST bulk import (no transaction — sql.js auto-persists each run) ── */
router.post('/audits/:auditId/controls/bulk', (req, res) => {
  const { controls } = req.body;
  if (!Array.isArray(controls)) return res.status(400).json({ error: 'controls array required' });
  try {
    for (const c of controls) {
      db.run(
        `INSERT INTO controls (id,audit_id,control_id,name,description,risk_level,evidence_required,notes,created_at)
         VALUES (?,?,?,?,?,?,?,?,?)`,
        [uuid(), req.params.auditId, c.control_id||'', c.name||'Unnamed', c.description||'',
         c.risk_level||'Medium', c.evidence_required||1, JSON.stringify(c.evidence_items||[]), now()]
      );
    }
    res.json({ success: true, count: controls.length });
  } catch(e) {
    res.status(500).json({ error: e.message });
  }
});

/* ── PATCH update control ── */
router.patch('/controls/:id', (req, res) => {
  if (!db.get('SELECT id FROM controls WHERE id = ?', [req.params.id]))
    return res.status(404).json({ error: 'Not found' });
  const fields = ['name','description','risk_level','status','assigned_to','due_date',
                  'evidence_required','notes','control_id'];
  const sets = [], vals = [];
  for (const f of fields) {
    if (req.body[f] !== undefined) { sets.push(`${f}=?`); vals.push(req.body[f]||null); }
  }
  if (sets.length) { vals.push(req.params.id); db.run(`UPDATE controls SET ${sets.join(',')} WHERE id=?`, vals); }
  res.json({ success: true });
});

/* ── DELETE control ── */
router.delete('/controls/:id', (req, res) => {
  db.run('DELETE FROM evidence WHERE control_id = ?', [req.params.id]);
  db.run('DELETE FROM comments WHERE control_id = ?', [req.params.id]);
  db.run('DELETE FROM reminders WHERE control_id = ?', [req.params.id]);
  db.run('DELETE FROM controls WHERE id = ?', [req.params.id]);
  res.json({ success: true });
});

/* ── POST comment ── */
router.post('/controls/:id/comments', (req, res) => {
  const { content, user_name } = req.body;
  if (!content) return res.status(400).json({ error: 'Content required' });
  const id = uuid();
  db.run('INSERT INTO comments (id,control_id,user_name,content,created_at) VALUES (?,?,?,?,?)',
    [id, req.params.id, user_name||'Anonymous', content, now()]);
  res.json({ success: true, id });
});

/* ── POST reminder ── */
router.post('/controls/:id/reminders', async (req, res) => {
  const { email, frequency } = req.body;
  if (!email) return res.status(400).json({ error: 'Email required' });
  const id = uuid();
  db.run('INSERT INTO reminders (id,control_id,user_email,frequency,created_at) VALUES (?,?,?,?,?)',
    [id, req.params.id, email, frequency||'weekly', now()]);
  try {
    const ctrl = db.get(`SELECT c.*, a.name as audit_name FROM controls c JOIN audits a ON c.audit_id=a.id WHERE c.id=?`, [req.params.id]);
    const { sendEmail, reminderEmailHTML } = require('../services/email');
    await sendEmail({ to: email, subject: `[AuditSphere] Reminder set for ${ctrl.name}`,
      html: reminderEmailHTML({ controlName: ctrl.name, controlId: ctrl.control_id,
        dueDate: ctrl.due_date, auditName: ctrl.audit_name, recipientName: 'you' }) });
  } catch(e) { console.log('Reminder email note:', e.message); }
  res.json({ success: true, id });
});

/* ── GET evidence for control ── */
router.get('/controls/:id/evidence', (req, res) => {
  res.json(db.all('SELECT * FROM evidence WHERE control_id = ? ORDER BY created_at', [req.params.id]));
});

module.exports = router;
