const express  = require('express');
const router   = express.Router();
const { v4: uuid } = require('uuid');
const db       = require('../database');
const { log }  = require('../services/activityLog');

function now() { return new Date().toISOString(); }

router.get('/', (req, res) => {
  const { status, risk } = req.query;
  let q = 'SELECT * FROM vendors WHERE 1=1';
  const p = [];
  if (status) { q += ' AND status=?'; p.push(status); }
  if (risk)   { q += ' AND risk_level=?'; p.push(risk); }
  q += ' ORDER BY name';
  const vendors = db.all(q, p);
  // Attach latest assessment
  vendors.forEach(v => {
    v.latest_assessment = db.get('SELECT * FROM vendor_assessments WHERE vendor_id=? ORDER BY created_at DESC LIMIT 1', [v.id]);
  });
  res.json(vendors);
});

router.get('/:id', (req, res) => {
  const v = db.get('SELECT * FROM vendors WHERE id=?', [req.params.id]);
  if (!v) return res.status(404).json({ error: 'Not found' });
  v.assessments = db.all('SELECT * FROM vendor_assessments WHERE vendor_id=? ORDER BY created_at DESC', [req.params.id]);
  res.json(v);
});

router.post('/', (req, res) => {
  const { name, contact_name, contact_email, category, risk_level, compliance_frameworks, next_assessment, certificate_expiry, notes } = req.body;
  if (!name) return res.status(400).json({ error: 'name required' });
  const id = uuid();
  db.run(`INSERT INTO vendors (id,name,contact_name,contact_email,category,risk_level,compliance_frameworks,next_assessment,certificate_expiry,notes)
    VALUES (?,?,?,?,?,?,?,?,?,?)`,
    [id, name, contact_name||'', contact_email||'', category||'', risk_level||'Medium',
     Array.isArray(compliance_frameworks) ? compliance_frameworks.join(',') : (compliance_frameworks||''),
     next_assessment||null, certificate_expiry||null, notes||'']);
  log({ action: 'vendor_created', entityType: 'vendor', entityId: id, entityName: name,
    userId: req.session?.user?.id, userName: req.session?.user?.name, req });
  res.json({ success: true, id });
});

router.patch('/:id', (req, res) => {
  const fields = ['name','contact_name','contact_email','category','risk_level','compliance_frameworks','next_assessment','certificate_expiry','status','notes','last_assessed'];
  const sets = [], vals = [];
  for (const f of fields) if (req.body[f] !== undefined) { sets.push(`${f}=?`); vals.push(req.body[f]||null); }
  if (sets.length) { vals.push(req.params.id); db.run(`UPDATE vendors SET ${sets.join(',')} WHERE id=?`, vals); }
  res.json({ success: true });
});

router.delete('/:id', (req, res) => {
  db.run('DELETE FROM vendor_assessments WHERE vendor_id=?', [req.params.id]);
  db.run('DELETE FROM vendors WHERE id=?', [req.params.id]);
  res.json({ success: true });
});

// Assessments
router.post('/:id/assessments', (req, res) => {
  const { score, findings, action_required, next_due, assessed_by } = req.body;
  const id = uuid();
  db.run(`INSERT INTO vendor_assessments (id,vendor_id,assessed_by,score,findings,action_required,next_due)
    VALUES (?,?,?,?,?,?,?)`,
    [id, req.params.id, assessed_by||req.session?.user?.name||'Admin',
     score||0, findings||'', action_required||'', next_due||null]);
  db.run('UPDATE vendors SET last_assessed=?, next_assessment=? WHERE id=?',
    [now().slice(0,10), next_due||null, req.params.id]);
  res.json({ success: true, id });
});

module.exports = router;
