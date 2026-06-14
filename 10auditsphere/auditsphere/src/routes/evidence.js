const express  = require('express');
const router   = express.Router();
const multer   = require('multer');
const path     = require('path');
const fs       = require('fs');
const { v4: uuid } = require('uuid');
const db       = require('../database');

const uploadDir = path.join(__dirname, '../../data/uploads');
fs.mkdirSync(uploadDir, { recursive: true });

const storage = multer.diskStorage({
  destination: (_req, _file, cb) => cb(null, uploadDir),
  filename:    (_req, file, cb) => cb(null, `${uuid()}${path.extname(file.originalname)}`)
});
const upload = multer({
  storage,
  limits: { fileSize: 50 * 1024 * 1024 },
  fileFilter: (_req, file, cb) => {
    const ok = ['.pdf','.xlsx','.xls','.csv','.png','.jpg','.jpeg','.docx','.doc','.txt','.zip'];
    const ext = path.extname(file.originalname).toLowerCase();
    ok.includes(ext) ? cb(null, true) : cb(new Error(`File type ${ext} not allowed`));
  }
});

function now() { return new Date().toISOString(); }

/* ── POST upload evidence for a control ── */
router.post('/controls/:controlId/evidence', upload.single('file'), (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'No file uploaded' });
  const { name, description, expiry_date, uploaded_by } = req.body;
  const ctrl = db.get('SELECT audit_id, evidence_required FROM controls WHERE id = ?', [req.params.controlId]);
  if (!ctrl) return res.status(404).json({ error: 'Control not found' });

  const evName = name || req.file.originalname;
  const existing = db.get('SELECT id, version FROM evidence WHERE control_id = ? AND name = ?',
    [req.params.controlId, evName]);

  if (existing) {
    const old = db.get('SELECT * FROM evidence WHERE id = ?', [existing.id]);
    db.run('INSERT INTO evidence_versions (id,evidence_id,file_path,file_name,version,uploaded_by,created_at) VALUES (?,?,?,?,?,?,?)',
      [uuid(), existing.id, old.file_path, old.file_name, old.version, uploaded_by||'Unknown', now()]);
    db.run(`UPDATE evidence SET file_path=?,file_name=?,file_size=?,file_type=?,version=version+1,status='pending',description=?,expiry_date=? WHERE id=?`,
      [req.file.path, req.file.originalname, req.file.size, req.file.mimetype,
       description||old.description, expiry_date||old.expiry_date, existing.id]);
    return res.json({ success: true, id: existing.id, versioned: true });
  }

  const id = uuid();
  db.run(`INSERT INTO evidence (id,control_id,audit_id,name,description,file_path,file_name,file_size,file_type,status,uploaded_by,expiry_date,created_at)
          VALUES (?,?,?,?,?,?,?,?,?,'pending',?,?,?)`,
    [id, req.params.controlId, ctrl.audit_id, evName, description||'',
     req.file.path, req.file.originalname, req.file.size, req.file.mimetype,
     uploaded_by||'Unknown', expiry_date||null, now()]);

  // Auto-progress control status
  const count = db.get("SELECT COUNT(*) as c FROM evidence WHERE control_id = ? AND status != 'rejected'", [req.params.controlId]).c;
  if (count >= ctrl.evidence_required) {
    db.run("UPDATE controls SET status='in_progress' WHERE id=? AND status='not_started'", [req.params.controlId]);
  }
  res.json({ success: true, id });
});

/* ── GET download evidence ── */
router.get('/evidence/:id/download', (req, res) => {
  const ev = db.get('SELECT * FROM evidence WHERE id = ?', [req.params.id]);
  if (!ev || !fs.existsSync(ev.file_path)) return res.status(404).json({ error: 'File not found' });
  res.download(ev.file_path, ev.file_name);
});

/* ── PATCH evidence status ── */
router.patch('/evidence/:id', (req, res) => {
  const { status, approved_by } = req.body;
  db.run('UPDATE evidence SET status=COALESCE(?,status), approved_by=COALESCE(?,approved_by) WHERE id=?',
    [status||null, approved_by||null, req.params.id]);

  if (status === 'approved') {
    const ev = db.get('SELECT control_id FROM evidence WHERE id = ?', [req.params.id]);
    if (ev) {
      const ctrl = db.get('SELECT evidence_required FROM controls WHERE id = ?', [ev.control_id]);
      const approved = db.get("SELECT COUNT(*) as c FROM evidence WHERE control_id = ? AND status = 'approved'", [ev.control_id]).c;
      if (approved >= (ctrl?.evidence_required || 1)) {
        db.run("UPDATE controls SET status='complete' WHERE id=?", [ev.control_id]);
      }
    }
  }
  res.json({ success: true });
});

/* ── DELETE evidence ── */
router.delete('/evidence/:id', (req, res) => {
  const ev = db.get('SELECT * FROM evidence WHERE id = ?', [req.params.id]);
  if (ev?.file_path && fs.existsSync(ev.file_path)) {
    try { fs.unlinkSync(ev.file_path); } catch(_) {}
  }
  db.run('DELETE FROM evidence_versions WHERE evidence_id = ?', [req.params.id]);
  db.run('DELETE FROM evidence WHERE id = ?', [req.params.id]);
  res.json({ success: true });
});

/* ── GET version history ── */
router.get('/evidence/:id/versions', (req, res) => {
  res.json(db.all('SELECT * FROM evidence_versions WHERE evidence_id = ? ORDER BY version DESC', [req.params.id]));
});

/* Multer error handler */
router.use((err, _req, res, _next) => {
  if (err.code === 'LIMIT_FILE_SIZE') return res.status(400).json({ error: 'File too large (max 50MB)' });
  res.status(400).json({ error: err.message });
});

module.exports = router;
