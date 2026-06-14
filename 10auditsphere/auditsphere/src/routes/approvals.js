const express  = require('express');
const router   = express.Router();
const { v4: uuid } = require('uuid');
const db       = require('../database');
const { sendEmail, approvalRequestHTML, approvalDecisionHTML } = require('../services/email');
const { log }  = require('../services/activityLog');

function now() { return new Date().toISOString(); }

// Get approval stages for evidence
router.get('/evidence/:evidenceId', (req, res) => {
  res.json(db.all('SELECT * FROM approval_stages WHERE evidence_id = ? ORDER BY created_at', [req.params.evidenceId]));
});

// Request approval (creates a stage)
router.post('/request', async (req, res) => {
  const { evidence_id, approver_email, approver_name, stage } = req.body;
  if (!evidence_id || !approver_email) return res.status(400).json({ error: 'evidence_id and approver_email required' });

  const ev   = db.get('SELECT e.*, c.name as control_name FROM evidence e JOIN controls c ON e.control_id=c.id WHERE e.id=?', [evidence_id]);
  if (!ev) return res.status(404).json({ error: 'Evidence not found' });

  const id = uuid();
  db.run(`INSERT INTO approval_stages (id,evidence_id,stage,status,assigned_to,assigned_email)
    VALUES (?,?,?,?,?,?)`,
    [id, evidence_id, stage || 'manager_review', 'pending', approver_name || approver_email, approver_email]);

  db.run("UPDATE evidence SET status = 'pending' WHERE id = ?", [evidence_id]);

  await sendEmail({
    to: approver_email,
    subject: `[G.R.I.D AI] Evidence awaiting approval: ${ev.name}`,
    html: approvalRequestHTML({
      approverName: approver_name || approver_email,
      evidenceName: ev.name,
      controlName: ev.control_name,
      uploaderName: ev.uploaded_by,
      reviewUrl: `${process.env.APP_URL || 'http://localhost:3000'}`,
    }),
  });

  log({ action: 'approval_requested', entityType: 'evidence', entityId: evidence_id,
    entityName: ev.name, userId: req.session?.user?.id, userName: req.session?.user?.name, req });

  res.json({ success: true, id });
});

// Approve or reject
router.post('/decide', async (req, res) => {
  const { stage_id, decision, comment, evidence_id } = req.body;
  if (!stage_id || !decision || !evidence_id) return res.status(400).json({ error: 'stage_id, decision, evidence_id required' });

  db.run('UPDATE approval_stages SET status=?, comment=?, acted_at=? WHERE id=?',
    [decision, comment || '', now(), stage_id]);

  const ev     = db.get('SELECT e.*, c.name as control_name, c.assigned_to, c.evidence_required FROM evidence e JOIN controls c ON e.control_id=c.id WHERE e.id=?', [evidence_id]);
  const newStatus = decision === 'approved' ? 'approved' : 'rejected';
  db.run('UPDATE evidence SET status=?, approved_by=?, approved_at=? WHERE id=?',
    [newStatus, req.session?.user?.name || 'Reviewer', now(), evidence_id]);

  // Auto-complete control if all evidence approved
  if (decision === 'approved' && ev) {
    const approvedCount = db.get("SELECT COUNT(*) as c FROM evidence WHERE control_id=? AND status='approved'", [ev.control_id]).c;
    if (approvedCount >= (ev.evidence_required || 1)) {
      db.run("UPDATE controls SET status='complete' WHERE id=?", [ev.control_id]);
    }
  }

  // Notify uploader
  if (ev?.uploaded_by) {
    const uploader = db.get('SELECT email FROM users WHERE name = ?', [ev.uploaded_by])
      || db.get('SELECT email FROM users WHERE id = (SELECT assigned_to FROM controls WHERE id=?)', [ev.control_id]);
    if (uploader?.email) {
      await sendEmail({
        to: uploader.email,
        subject: `[G.R.I.D AI] Evidence ${decision}: ${ev.name}`,
        html: approvalDecisionHTML({
          uploaderName: ev.uploaded_by, evidenceName: ev.name,
          decision, comment, reviewerName: req.session?.user?.name || 'Reviewer',
        }),
      });
    }
  }

  log({ action: `evidence_${decision}`, entityType: 'evidence', entityId: evidence_id,
    entityName: ev?.name, userId: req.session?.user?.id, userName: req.session?.user?.name,
    details: { comment }, req });

  res.json({ success: true });
});

module.exports = router;
