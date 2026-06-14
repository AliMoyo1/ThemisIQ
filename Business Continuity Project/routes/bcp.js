const express = require('express');
const router = express.Router();
const db = require('../models/db');
const { requireAuth } = require('../middleware/auth');
const { scheduleBcpReviewReminder } = require('../services/scheduler');
const { ACTIONS } = require('../services/audit');
const { buildPlanDoc, safeFilename } = require('../services/word-export');
const { reviewPlan, detectCoverage } = require('../services/plan-reviewer');

router.use(requireAuth);

const COVERAGE_TYPES = ['primary', 'secondary', 'partial', 'referenced'];

// All BIA records for this tenant — small payload used to render the BIA
// multi-select on the BCP form.
function listBias(tenantId) {
  return db.prepare(`
    SELECT id, process_name, department, owner, criticality, rto_hours, rpo_hours
    FROM bia_records
    WHERE tenant_id = ?
    ORDER BY CASE criticality WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 WHEN 'Low' THEN 3 ELSE 4 END,
             process_name COLLATE NOCASE
  `).all(tenantId);
}

// Processes that this plan covers, for the show page.
function biasForPlan(tenantId, planId) {
  return db.prepare(`
    SELECT bpl.id AS link_id, bpl.coverage_type, bpl.notes,
           b.id, b.process_name, b.department, b.owner, b.criticality, b.rto_hours, b.rpo_hours
    FROM bia_plan_links bpl
    JOIN bia_records b ON b.id = bpl.bia_id
    WHERE bpl.tenant_id = ? AND bpl.plan_id = ?
    ORDER BY CASE bpl.coverage_type
              WHEN 'primary' THEN 0 WHEN 'secondary' THEN 1
              WHEN 'partial' THEN 2 WHEN 'referenced' THEN 3 ELSE 4 END,
             CASE b.criticality WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 WHEN 'Low' THEN 3 ELSE 4 END,
             b.process_name COLLATE NOCASE
  `).all(tenantId, planId);
}

// Replace this plan's BIA links with whatever was submitted.
function syncLinksForPlan({ tenantId, planId, biaIds, coverageByBiaId, createdBy }) {
  const valid = (biaIds || []).map(Number).filter(n => Number.isFinite(n));
  const tx = db.transaction(() => {
    db.prepare(`DELETE FROM bia_plan_links WHERE tenant_id = ? AND plan_id = ?`).run(tenantId, planId);
    if (!valid.length) return 0;
    const ins = db.prepare(`
      INSERT INTO bia_plan_links (tenant_id, bia_id, plan_id, coverage_type, created_by)
      VALUES (?, ?, ?, ?, ?)
    `);
    let count = 0;
    for (const biaId of valid) {
      const owned = db.prepare(`SELECT 1 FROM bia_records WHERE id = ? AND tenant_id = ?`).get(biaId, tenantId);
      if (!owned) continue;
      let coverage = (coverageByBiaId && coverageByBiaId[biaId]) || 'primary';
      if (!COVERAGE_TYPES.includes(coverage)) coverage = 'primary';
      ins.run(tenantId, biaId, planId, coverage, createdBy || null);
      count++;
    }
    return count;
  });
  return tx();
}

router.get('/', (req, res) => {
  const rows = db.prepare(`SELECT * FROM bcp_plans WHERE tenant_id = ? ORDER BY updated_at DESC`).all(req.session.tenant.id);
  res.render('bcp/index', { title: 'Continuity Plans', rows });
});

router.get('/new', (req, res) => {
  const bias = listBias(req.session.tenant.id);
  res.render('bcp/form', { title: 'New plan', plan: null, bias, links: [] });
});

router.get('/:id', (req, res) => {
  const plan = db.prepare(`SELECT * FROM bcp_plans WHERE id = ? AND tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!plan) { req.flash('error', 'Plan not found.'); return res.redirect('/bcp'); }
  const linkedBias = biasForPlan(req.session.tenant.id, plan.id);
  res.render('bcp/show', { title: plan.title, plan, linkedBias });
});

router.get('/:id/edit', (req, res) => {
  const plan = db.prepare(`SELECT * FROM bcp_plans WHERE id = ? AND tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!plan) { req.flash('error', 'Plan not found.'); return res.redirect('/bcp'); }
  const bias = listBias(req.session.tenant.id);
  const links = db.prepare(`
    SELECT bia_id, coverage_type FROM bia_plan_links
    WHERE tenant_id = ? AND plan_id = ?
  `).all(req.session.tenant.id, plan.id);
  res.render('bcp/form', { title: 'Edit plan', plan, bias, links });
});

// AI plan reviewer — list past reviews + form to trigger a new one
router.get('/:id/review', (req, res) => {
  const tenantId = req.session.tenant.id;
  const plan = db.prepare(`SELECT * FROM bcp_plans WHERE id = ? AND tenant_id = ?`).get(req.params.id, tenantId);
  if (!plan) { req.flash('error', 'Plan not found.'); return res.redirect('/bcp'); }
  const reviews = db.prepare(`SELECT * FROM plan_reviews WHERE plan_id = ? AND tenant_id = ? ORDER BY created_at DESC`)
    .all(plan.id, tenantId);
  // Decode JSON for the first review (the rest are collapsed)
  const parsed = reviews.map(r => ({
    ...r,
    strengths:       safeList(r.strengths),
    gaps:            safeList(r.gaps),
    recommendations: safeList(r.recommendations),
    standards_alignment: safeObj(r.standards),
    section_coverage:    safeObj(r.section_coverage) || []
  }));
  const coverage = detectCoverage(plan.content);
  res.render('bcp/review', { title: 'Review: ' + plan.title, plan, reviews: parsed, coverage });
});

router.post('/:id/review', async (req, res, next) => {
  try {
    const tenantId = req.session.tenant.id;
    const plan = db.prepare(`SELECT * FROM bcp_plans WHERE id = ? AND tenant_id = ?`).get(req.params.id, tenantId);
    if (!plan) { req.flash('error', 'Plan not found.'); return res.redirect('/bcp'); }

    const standards = [];
    if (req.body.iso22301 === 'on' || req.body.iso22301 === '1' || req.body.iso22301 === true) standards.push('ISO 22301');
    if (req.body.nistcsf === 'on' || req.body.nistcsf === '1' || req.body.nistcsf === true)    standards.push('NIST CSF');
    if (!standards.length) { standards.push('ISO 22301', 'NIST CSF'); }

    const review = await reviewPlan({ tenantId, plan, standards });

    db.prepare(`INSERT INTO plan_reviews
      (tenant_id, plan_id, reviewer_id, reviewer_name, provider, overall_score, standards,
       summary, strengths, gaps, recommendations, section_coverage, raw_response)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
      .run(
        tenantId, plan.id, req.session.user.id, req.session.user.name, review.provider,
        review.overall_score, standards.join(','),
        review.summary,
        JSON.stringify(review.strengths),
        JSON.stringify(review.gaps),
        JSON.stringify(review.recommendations),
        JSON.stringify({ standards_alignment: review.standards_alignment, section_coverage: review.section_coverage }),
        review.raw_response
      );

    req.audit({ action: ACTIONS.AI_CALL, entity: 'bcp_plans', entityId: plan.id,
      summary: `AI plan review (${standards.join(' + ')}) — score ${review.overall_score}` });
    req.flash('success', 'AI review complete.');
    res.redirect('/bcp/' + plan.id + '/review');
  } catch (err) { next(err); }
});

router.post('/:id/review/:reviewId/delete', (req, res) => {
  db.prepare(`DELETE FROM plan_reviews WHERE id = ? AND plan_id = ? AND tenant_id = ?`)
    .run(req.params.reviewId, req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'plan_reviews', entityId: +req.params.reviewId, summary: 'Review removed' });
  req.flash('success', 'Review removed.');
  res.redirect('/bcp/' + req.params.id + '/review');
});

function safeList(raw) {
  if (!raw) return [];
  try { const v = JSON.parse(raw); return Array.isArray(v) ? v : []; }
  catch (_) { return []; }
}
function safeObj(raw) {
  if (!raw) return null;
  try { return JSON.parse(raw); }
  catch (_) { return null; }
}

// Export a plan as a branded .docx — available to anyone with read access
router.get('/:id/export.docx', async (req, res, next) => {
  try {
    const plan = db.prepare(`SELECT * FROM bcp_plans WHERE id = ? AND tenant_id = ?`)
      .get(req.params.id, req.session.tenant.id);
    if (!plan) { req.flash('error', 'Plan not found.'); return res.redirect('/bcp'); }

    const buf = await buildPlanDoc(plan, {
      tenantName: req.session.tenant.name,
      generatedBy: req.session.user.name
    });
    const filename = safeFilename(`${plan.title}_v${plan.version || '1.0'}`) + '.docx';

    req.audit({ action: ACTIONS.EXPORT, entity: 'bcp_plans', entityId: plan.id,
      summary: `Plan "${plan.title}" exported to Word` });

    res.setHeader('Content-Type',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
    res.setHeader('Content-Length', buf.length);
    res.end(buf);
  } catch (err) {
    next(err);
  }
});

router.post('/', (req, res) => {
  const b = req.body;
  const info = db.prepare(`
    INSERT INTO bcp_plans (tenant_id, title, scope, owner, version, status, content, last_reviewed, next_review)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    req.session.tenant.id, b.title, b.scope || null, b.owner || null,
    b.version || '1.0', b.status || 'draft', b.content || '',
    b.last_reviewed || null, b.next_review || null
  );
  const planId = info.lastInsertRowid;
  if (b.next_review) scheduleBcpReviewReminder(planId, req.session.tenant.id);

  const biaIds = [].concat(b.bia_ids || []);
  const coverageByBiaId = {};
  Object.keys(b).forEach(k => {
    const m = k.match(/^coverage_for_bia_(\d+)$/);
    if (m) coverageByBiaId[m[1]] = b[k];
  });
  const linked = syncLinksForPlan({
    tenantId: req.session.tenant.id, planId, biaIds, coverageByBiaId,
    createdBy: req.session.user.name
  });

  req.audit({ action: ACTIONS.CREATE, entity: 'bcp_plans', entityId: planId,
    summary: `Plan "${b.title}" created${linked ? ` · covers ${linked} process${linked === 1 ? '' : 'es'}` : ''}` });
  req.flash('success', 'Plan created.');
  res.redirect('/bcp/' + planId);
});

router.post('/:id', (req, res) => {
  const b = req.body;
  db.prepare(`
    UPDATE bcp_plans SET title=?, scope=?, owner=?, version=?, status=?, content=?, last_reviewed=?, next_review=?, updated_at=CURRENT_TIMESTAMP
    WHERE id = ? AND tenant_id = ?
  `).run(
    b.title, b.scope || null, b.owner || null, b.version || '1.0',
    b.status || 'draft', b.content || '', b.last_reviewed || null, b.next_review || null,
    req.params.id, req.session.tenant.id
  );

  const biaIds = [].concat(b.bia_ids || []);
  const coverageByBiaId = {};
  Object.keys(b).forEach(k => {
    const m = k.match(/^coverage_for_bia_(\d+)$/);
    if (m) coverageByBiaId[m[1]] = b[k];
  });
  const linked = syncLinksForPlan({
    tenantId: req.session.tenant.id, planId: +req.params.id, biaIds, coverageByBiaId,
    createdBy: req.session.user.name
  });

  req.audit({ action: ACTIONS.UPDATE, entity: 'bcp_plans', entityId: +req.params.id,
    summary: `Plan "${b.title}" updated · covers ${linked} process${linked === 1 ? '' : 'es'}` });
  req.flash('success', 'Plan updated.');
  res.redirect('/bcp/' + req.params.id);
});

router.post('/:id/delete', (req, res) => {
  db.prepare(`DELETE FROM bcp_plans WHERE id = ? AND tenant_id = ?`).run(req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'bcp_plans', entityId: +req.params.id, summary: 'Plan deleted' });
  req.flash('success', 'Plan deleted.');
  res.redirect('/bcp');
});

module.exports = router;
