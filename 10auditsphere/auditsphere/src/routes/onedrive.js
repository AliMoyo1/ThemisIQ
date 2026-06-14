const express  = require('express');
const router   = express.Router();
const multer   = require('multer');
const path     = require('path');
const fs       = require('fs');
const { v4: uuid } = require('uuid');
const db       = require('../database');
const { uploadToOneDrive } = require('../services/microsoft');
const { log }  = require('../services/activityLog');

const upload = multer({ dest: '/tmp/od-uploads/', limits: { fileSize: 100 * 1024 * 1024 } });

// Link evidence to OneDrive (upload)
router.post('/upload/:evidenceId', upload.single('file'), async (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'No file uploaded' });

  const ev = db.get('SELECT e.*, a.name as audit_name FROM evidence e JOIN audits a ON e.audit_id=a.id WHERE e.id=?', [req.params.evidenceId]);
  if (!ev) return res.status(404).json({ error: 'Evidence not found' });

  const result = await uploadToOneDrive(req.file.path, req.file.originalname, ev.audit_name);
  try { fs.unlinkSync(req.file.path); } catch(_) {}

  if (result.ok) {
    db.run('UPDATE evidence SET onedrive_id=?, onedrive_url=? WHERE id=?', [result.id, result.url, req.params.evidenceId]);
    log({ action: 'onedrive_upload', entityType: 'evidence', entityId: req.params.evidenceId,
      entityName: ev.name, userId: req.session?.user?.id, userName: req.session?.user?.name, req });
    res.json({ success: true, onedrive_url: result.url, onedrive_id: result.id });
  } else {
    res.status(500).json({ error: result.error || 'OneDrive upload failed' });
  }
});

// Sync existing evidence file to OneDrive
router.post('/sync/:evidenceId', async (req, res) => {
  const ev = db.get('SELECT e.*, a.name as audit_name FROM evidence e JOIN audits a ON e.audit_id=a.id WHERE e.id=?', [req.params.evidenceId]);
  if (!ev) return res.status(404).json({ error: 'Evidence not found' });
  if (!ev.file_path || !fs.existsSync(ev.file_path)) return res.status(404).json({ error: 'Local file not found' });

  const result = await uploadToOneDrive(ev.file_path, ev.file_name, ev.audit_name);
  if (result.ok) {
    db.run('UPDATE evidence SET onedrive_id=?, onedrive_url=? WHERE id=?', [result.id, result.url, ev.id]);
    res.json({ success: true, onedrive_url: result.url });
  } else {
    res.json({ success: false, error: result.error, note: 'File saved locally — OneDrive unavailable' });
  }
});

// Sync all evidence for an audit to OneDrive
router.post('/sync-audit/:auditId', async (req, res) => {
  const evList = db.all("SELECT e.*, a.name as audit_name FROM evidence e JOIN audits a ON e.audit_id=a.id WHERE e.audit_id=? AND e.file_path IS NOT NULL AND e.onedrive_id IS NULL", [req.params.auditId]);
  const results = { synced: 0, failed: 0, errors: [] };
  for (const ev of evList) {
    if (!fs.existsSync(ev.file_path)) continue;
    const r = await uploadToOneDrive(ev.file_path, ev.file_name, ev.audit_name);
    if (r.ok) {
      db.run('UPDATE evidence SET onedrive_id=?, onedrive_url=? WHERE id=?', [r.id, r.url, ev.id]);
      results.synced++;
    } else {
      results.failed++;
      results.errors.push({ file: ev.file_name, error: r.error });
    }
  }
  res.json({ success: true, ...results });
});

module.exports = router;
