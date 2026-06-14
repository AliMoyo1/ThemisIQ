const express = require('express');
const router = express.Router();
const { requireAuth } = require('../middleware/auth');
const { ACTIONS } = require('../services/audit');
const { buildBoardReport, gatherBoardMetrics } = require('../services/board-report');
const { safeFilename } = require('../services/word-export');

router.use(requireAuth);

// Reports home — landing page with summary KPIs + export controls
router.get('/', (req, res) => {
  const tenantId = req.session.tenant.id;
  // Give the page a live preview of this quarter's headline metrics.
  const metrics = gatherBoardMetrics(tenantId);
  res.render('reports/index', { title: 'Reports', metrics });
});

// Preview — renders the metrics in the browser so leadership can eyeball them
// before hitting export. Also supports custom date ranges via query string.
router.get('/board', (req, res) => {
  const tenantId = req.session.tenant.id;
  const { start, end, label } = req.query;
  const metrics = gatherBoardMetrics(tenantId, {
    periodStart: start || undefined,
    periodEnd: end || undefined,
    label: label || undefined
  });
  res.render('reports/board', { title: 'Board report preview', metrics });
});

// Export — produces the branded .docx
router.post('/board.docx', async (req, res, next) => {
  try {
    const tenantId = req.session.tenant.id;
    const { start, end, label, skip_narrative } = req.body;
    const metrics = gatherBoardMetrics(tenantId, {
      periodStart: start || undefined,
      periodEnd: end || undefined,
      label: label || undefined
    });
    const buf = await buildBoardReport(metrics, {
      tenantName: req.session.tenant.name,
      generatedBy: req.session.user.name,
      includeNarrative: !(skip_narrative === 'on' || skip_narrative === '1')
    });
    const filename = safeFilename(`Board_Report_${metrics.label}`) + '.docx';

    req.audit({
      action: ACTIONS.EXPORT,
      entity: 'reports',
      entityId: null,
      summary: `Board report (${metrics.label}) exported`
    });

    res.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
    res.setHeader('Content-Length', buf.length);
    res.end(buf);
  } catch (err) { next(err); }
});

module.exports = router;
