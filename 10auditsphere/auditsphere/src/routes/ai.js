const express  = require('express');
const router   = express.Router();
const multer   = require('multer');
const path     = require('path');
const fs       = require('fs');
const db       = require('../database');
const aiSvc    = require('../services/ai');
const { parseChecklistFile } = require('../services/checklistParser');

const upload = multer({ dest: '/tmp/as-uploads/', limits: { fileSize: 50 * 1024 * 1024 } });

/* ── helpers ── */
function getAuditWithStats(auditId) {
  const audit    = db.get('SELECT a.*, f.name as framework_name FROM audits a JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?', [auditId]);
  const controls = db.all('SELECT c.*, COUNT(e.id) as evidence_count FROM controls c LEFT JOIN evidence e ON e.control_id=c.id WHERE c.audit_id=? GROUP BY c.id', [auditId]);
  const todayStr = new Date().toISOString().slice(0, 10);
  const complete = controls.filter(c => c.status === 'complete').length;
  const overdue  = controls.filter(c => c.status !== 'complete' && c.due_date && c.due_date < todayStr).length;
  const pending  = controls.length - complete - overdue;
  const criticalGaps = controls.filter(c => c.risk_level === 'Critical' && c.status !== 'complete').map(c => c.name);
  return { audit, controls, complete, overdue, pending, criticalGaps };
}

/* ══════════════════════════════════════════════════════════════════════
   PARSE CHECKLIST  — New multi-stage approach
   Stage 1: Extract ALL rows directly from Excel (no char limits, no AI)
   Stage 2: Send batches of 40 to Claude for risk scoring
   Stage 3: Return complete merged results
   ══════════════════════════════════════════════════════════════════════ */
router.post('/parse-checklist', upload.single('file'), async (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'File required' });

  const { framework_name, skip_ai } = req.body;
  const ext = path.extname(req.file.originalname).toLowerCase();
  const skipAI = skip_ai === 'true';

  try {
    const controls = await parseChecklistFile(
      req.file.path,
      framework_name || 'ISO 27001',
      skipAI,
      ext   // pass the extension detected from originalname
    );

    try { fs.unlinkSync(req.file.path); } catch (_) {}

    if (controls.length === 0) {
      return res.status(400).json({ error: 'No controls found in this file. Make sure it has a header row and data rows below it.' });
    }

    res.json({
      success: true,
      controls,
      count: controls.length,
      ai_scored: !skipAI,
      message: skipAI
        ? `Extracted ${controls.length} controls (no AI scoring — add API key to score risks)`
        : `Extracted and AI-scored ${controls.length} controls`,
    });

  } catch (e) {
    try { fs.unlinkSync(req.file.path); } catch (_) {}
    console.error('Checklist parse error:', e.message);
    res.status(500).json({ error: e.message });
  }
});

/* ── Gap analysis ── */
router.get('/gap-analysis/:auditId', async (req, res) => {
  try {
    const { audit, controls } = getAuditWithStats(req.params.auditId);
    if (!audit) return res.status(404).json({ error: 'Audit not found' });
    const analysis = await aiSvc.generateGapAnalysis(controls, audit.framework_name);
    res.json({ success: true, analysis });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── Suggest control details ── */
router.post('/suggest-control', async (req, res) => {
  const { control_id, name, framework } = req.body;
  if (!name || !framework) return res.status(400).json({ error: 'name and framework required' });
  try {
    res.json({ success: true, suggestion: await aiSvc.suggestControlDetails(control_id || '', name, framework) });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

/* ── Generate report ── */
router.post('/generate-report/:auditId', async (req, res) => {
  try {
    const { audit, controls, complete, overdue, pending, criticalGaps } = getAuditWithStats(req.params.auditId);
    if (!audit) return res.status(404).json({ error: 'Audit not found' });

    const narrative = await aiSvc.generateReportNarrative({
      auditName: audit.name, framework: audit.framework_name,
      completionPct: controls.length ? Math.round(complete / controls.length * 100) : 0,
      totalControls: controls.length, complete, pending, overdue,
      auditDate: audit.audit_date, criticalGaps: criticalGaps.slice(0, 5)
    });

    const auditPayload = {
      ...audit, id: req.params.auditId, framework: audit.framework_name,
      totalControls: controls.length, complete, pending, overdue,
      completionPct: controls.length ? Math.round(complete / controls.length * 100) : 0
    };

    const [pdfResult, docxResult] = await Promise.all([
      require('../services/pdfReport').generateAuditReportPDF(auditPayload, controls, narrative),
      require('../services/wordReport').generateAuditReportDocx(auditPayload, controls, narrative),
    ]);

    res.json({
      success: true, narrative,
      pdfFileName: pdfResult.fileName,
      docxFileName: docxResult.fileName,
      downloadPdfUrl:  `/api/ai/reports/download/${pdfResult.fileName}`,
      downloadDocxUrl: `/api/ai/reports/download/${docxResult.fileName}`,
    });
  } catch (e) { console.error('Report error:', e.message); res.status(500).json({ error: e.message }); }
});

/* ── Download report ── */
router.get('/reports/download/:fileName', (req, res) => {
  const fp = path.join(__dirname, '../../data/reports', req.params.fileName);
  if (!fs.existsSync(fp)) return res.status(404).json({ error: 'Report not found' });
  res.download(fp, req.params.fileName);
});

/* ── AI Chat ── */
router.post('/chat', async (req, res) => {
  const { message, audit_id } = req.body;
  if (!message) return res.status(400).json({ error: 'message required' });
  let context = {};
  if (audit_id) {
    const audit    = db.get('SELECT a.*, f.name as framework_name FROM audits a JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?', [audit_id]);
    const controls = db.all('SELECT status FROM controls WHERE audit_id=?', [audit_id]);
    const complete = controls.filter(c => c.status === 'complete').length;
    context = { framework: audit?.framework_name, total: controls.length, complete, pct: controls.length ? Math.round(complete / controls.length * 100) : 0 };
  }
  try { res.json({ success: true, answer: await aiSvc.askComplianceAI(message, context) }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

module.exports = router;
