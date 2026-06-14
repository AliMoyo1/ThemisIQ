const express  = require('express');
const router   = express.Router();
const { v4: uuid } = require('uuid');
const crypto   = require('crypto');
const db       = require('../database');
const { sendEmail, auditShareHTML } = require('../services/email');
const { log }  = require('../services/activityLog');

function now() { return new Date().toISOString(); }

// Create share link
router.post('/', (req, res) => {
  const { audit_id, label, expires_days, auditor_email, auditor_name } = req.body;
  if (!audit_id) return res.status(400).json({ error: 'audit_id required' });

  const token     = crypto.randomBytes(32).toString('hex');
  const id        = uuid();
  const expiresAt = expires_days
    ? new Date(Date.now() + parseInt(expires_days) * 86400000).toISOString().slice(0, 10)
    : null;

  db.run(`INSERT INTO share_links (id,audit_id,token,label,created_by,expires_at)
    VALUES (?,?,?,?,?,?)`,
    [id, audit_id, token, label || 'External Auditor Access', req.session?.user?.name || 'Admin', expiresAt]);

  const shareUrl = `${process.env.APP_URL || 'http://localhost:3000'}/shared/${token}`;

  // Send email to auditor if provided
  if (auditor_email) {
    const audit = db.get('SELECT a.*, f.name as framework_name FROM audits a JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?', [audit_id]);
    sendEmail({
      to: auditor_email,
      subject: `[G.R.I.D AI] Audit Access: ${audit?.name || 'Compliance Audit'}`,
      html: auditShareHTML({
        auditorName: auditor_name || auditor_email,
        auditName: audit?.name || 'Compliance Audit',
        shareUrl,
        expiresAt,
        createdBy: req.session?.user?.name || 'G.R.I.D AI',
      }),
    });
  }

  log({ action: 'share_link_created', entityType: 'audit', entityId: audit_id,
    entityName: label, userId: req.session?.user?.id, userName: req.session?.user?.name,
    details: { auditor_email, expires_days }, req });

  res.json({ success: true, id, token, shareUrl, expiresAt });
});

// List share links for an audit
router.get('/audit/:auditId', (req, res) => {
  res.json(db.all('SELECT * FROM share_links WHERE audit_id = ? ORDER BY created_at DESC', [req.params.auditId]));
});

// Validate a share link (public — no auth required)
router.get('/validate/:token', (req, res) => {
  const link = db.get('SELECT * FROM share_links WHERE token = ? AND active = 1', [req.params.token]);
  if (!link) return res.status(404).json({ error: 'Link not found or revoked' });
  if (link.expires_at && link.expires_at < new Date().toISOString().slice(0, 10)) {
    return res.status(403).json({ error: 'This link has expired' });
  }
  db.run('UPDATE share_links SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?',
    [now(), link.id]);
  const audit = db.get(`SELECT a.*, f.name as framework_name FROM audits a JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?`, [link.audit_id]);
  const controls = db.all(`SELECT c.*, COUNT(e.id) as evidence_count FROM controls c LEFT JOIN evidence e ON e.control_id=c.id WHERE c.audit_id=? GROUP BY c.id`, [link.audit_id]);
  audit.controls = controls;
  audit.total_controls    = controls.length;
  audit.complete_controls = controls.filter(c => c.status === 'complete').length;
  audit.completion_pct    = audit.total_controls > 0 ? Math.round(audit.complete_controls / audit.total_controls * 100) : 0;
  res.json({ ok: true, audit, link: { label: link.label, expires_at: link.expires_at, created_by: link.created_by } });
});

// Revoke link
router.delete('/:id', (req, res) => {
  db.run('UPDATE share_links SET active = 0 WHERE id = ?', [req.params.id]);
  res.json({ success: true });
});

module.exports = router;
