const express  = require('express');
const router   = express.Router();
const { v4: uuid } = require('uuid');
const db       = require('../database');
const { sendEmail, ncAlertHTML } = require('../services/email');
const { log }  = require('../services/activityLog');

function now() { return new Date().toISOString(); }

router.get('/', (req, res) => {
  const { audit_id, status } = req.query;
  let q = `SELECT nc.*, u.name as owner_name, a.name as audit_name
    FROM non_conformances nc LEFT JOIN users u ON nc.owner_id=u.id
    JOIN audits a ON nc.audit_id=a.id WHERE 1=1`;
  const p = [];
  if (audit_id) { q += ' AND nc.audit_id=?'; p.push(audit_id); }
  if (status)   { q += ' AND nc.status=?';   p.push(status); }
  q += ' ORDER BY nc.created_at DESC';
  res.json(db.all(q, p));
});

router.get('/:id', (req, res) => {
  const nc = db.get('SELECT nc.*, u.name as owner_name FROM non_conformances nc LEFT JOIN users u ON nc.owner_id=u.id WHERE nc.id=?', [req.params.id]);
  if (!nc) return res.status(404).json({ error: 'Not found' });
  res.json(nc);
});

router.post('/', async (req, res) => {
  const { audit_id, control_id, title, description, severity, owner_id, owner_email, root_cause, corrective_action, due_date } = req.body;
  if (!audit_id || !title) return res.status(400).json({ error: 'audit_id and title required' });
  const id = uuid();
  db.run(`INSERT INTO non_conformances (id,audit_id,control_id,title,description,severity,raised_by,owner_id,owner_email,root_cause,corrective_action,due_date)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`,
    [id, audit_id, control_id||null, title, description||'', severity||'Major',
     req.session?.user?.name||'System', owner_id||null, owner_email||'', root_cause||'', corrective_action||'', due_date||null]);

  // Notify owner
  if (owner_email) {
    const audit = db.get('SELECT name FROM audits WHERE id=?', [audit_id]);
    await sendEmail({
      to: owner_email,
      subject: `[G.R.I.D AI] Non-Conformance Assigned: ${title}`,
      html: ncAlertHTML({
        ownerName: req.body.owner_name || owner_email, ncTitle: title, severity: severity||'Major',
        dueDate: due_date, raisedBy: req.session?.user?.name||'Admin', auditName: audit?.name||'',
      }),
    });
  }

  log({ action: 'nc_raised', entityType: 'non_conformance', entityId: id, entityName: title,
    userId: req.session?.user?.id, userName: req.session?.user?.name, req });
  res.json({ success: true, id });
});

router.patch('/:id', (req, res) => {
  const nc = db.get('SELECT id FROM non_conformances WHERE id=?', [req.params.id]);
  if (!nc) return res.status(404).json({ error: 'Not found' });
  const fields = ['title','description','severity','owner_id','owner_email','root_cause','corrective_action','status','due_date'];
  const sets = [], vals = [];
  for (const f of fields) if (req.body[f] !== undefined) { sets.push(`${f}=?`); vals.push(req.body[f]||null); }
  if (req.body.status === 'closed') { sets.push('closed_at=?'); vals.push(now()); }
  if (sets.length) { vals.push(req.params.id); db.run(`UPDATE non_conformances SET ${sets.join(',')} WHERE id=?`, vals); }
  log({ action: 'nc_updated', entityType: 'non_conformance', entityId: req.params.id,
    userId: req.session?.user?.id, userName: req.session?.user?.name, req });
  res.json({ success: true });
});

router.delete('/:id', (req, res) => {
  db.run('DELETE FROM non_conformances WHERE id=?', [req.params.id]);
  res.json({ success: true });
});

module.exports = router;
