const express  = require('express');
const router   = express.Router();
const { v4: uuid } = require('uuid');
const db       = require('../database');
const { sendWeeklyDigest, performBackup } = require('../services/scheduler');

// Digest subscriptions
router.get('/subscriptions', (req, res) => {
  res.json(db.all('SELECT * FROM digest_subscriptions WHERE active=1 ORDER BY created_at DESC'));
});

router.post('/subscriptions', (req, res) => {
  const { email, name, frequency, audit_ids } = req.body;
  if (!email) return res.status(400).json({ error: 'email required' });
  const existing = db.get('SELECT id FROM digest_subscriptions WHERE email=?', [email]);
  if (existing) {
    db.run('UPDATE digest_subscriptions SET name=?,frequency=?,audit_ids=?,active=1 WHERE email=?',
      [name||email, frequency||'weekly', audit_ids||'all', email]);
    return res.json({ success: true, updated: true });
  }
  const id = uuid();
  db.run('INSERT INTO digest_subscriptions (id,email,name,frequency,audit_ids) VALUES (?,?,?,?,?)',
    [id, email, name||email, frequency||'weekly', audit_ids||'all']);
  res.json({ success: true, id });
});

router.delete('/subscriptions/:id', (req, res) => {
  db.run('UPDATE digest_subscriptions SET active=0 WHERE id=?', [req.params.id]);
  res.json({ success: true });
});

// Scheduled reports
router.get('/scheduled-reports', (req, res) => {
  res.json(db.all('SELECT * FROM scheduled_reports WHERE active=1'));
});

router.post('/scheduled-reports', (req, res) => {
  const { audit_id, email, frequency, format } = req.body;
  if (!audit_id || !email) return res.status(400).json({ error: 'audit_id and email required' });
  const id = uuid();
  db.run('INSERT INTO scheduled_reports (id,audit_id,email,frequency,format) VALUES (?,?,?,?,?)',
    [id, audit_id, email, frequency||'monthly', format||'both']);
  res.json({ success: true, id });
});

router.delete('/scheduled-reports/:id', (req, res) => {
  db.run('UPDATE scheduled_reports SET active=0 WHERE id=?', [req.params.id]);
  res.json({ success: true });
});

// Manual triggers (for testing)
router.post('/send-digest-now', async (req, res) => {
  try { await sendWeeklyDigest(); res.json({ success: true, message: 'Digest sent' }); }
  catch(e) { res.status(500).json({ error: e.message }); }
});

router.post('/test-email', async (req, res) => {
  const { sendEmail, weeklyDigestHTML } = require('../services/email');
  const to = req.body.to || process.env.MS_EMAIL || 'AliCompliance@outlook.com';
  const result = await sendEmail({
    to,
    subject: '[G.R.I.D AI] Test Email - Connection Working',
    html: weeklyDigestHTML({
      recipientName: 'Ali Moyo',
      audits: [{ name: 'Test Audit', framework_name: 'ISO 27001', audit_type: 'External',
                 completion_pct: 75, complete_controls: 9, total_controls: 12, overdue_controls: 1 }]
    }),
  });
  if (result.ok) {
    const msg = result.provider === 'ethereal'
      ? `No email provider configured — check server console for preview URL (ethereal.email test)`
      : `Test email sent via ${result.provider} to ${to}`;
    res.json({ success: true, message: msg, provider: result.provider });
  } else {
    res.status(500).json({ success: false, error: result.error });
  }
});

router.post('/backup-now', async (req, res) => {
  try { await performBackup(); res.json({ success: true, message: 'Backup completed' }); }
  catch(e) { res.status(500).json({ error: e.message }); }
});

// Compliance score history
router.get('/scores/:auditId', (req, res) => {
  res.json(db.all('SELECT * FROM compliance_scores WHERE audit_id=? ORDER BY recorded_at DESC LIMIT 60', [req.params.auditId]));
});

module.exports = router;
