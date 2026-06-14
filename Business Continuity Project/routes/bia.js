const express = require('express');
const router = express.Router();
const db = require('../models/db');
const { requireAuth } = require('../middleware/auth');
const { ACTIONS } = require('../services/audit');

router.use(requireAuth);

// -- Helpers --------------------------------------------------------------
function criticalityOf(op, rep, reg, financial) {
  const maxImpact = Math.max(op || 0, rep || 0, reg || 0);
  if (maxImpact >= 5 || (financial || 0) >= 100000) return 'Critical';
  if (maxImpact >= 4 || (financial || 0) >= 25000) return 'High';
  if (maxImpact >= 3) return 'Medium';
  return 'Low';
}

const COVERAGE_TYPES = ['primary', 'secondary', 'partial', 'referenced'];

// Pull every plan for this tenant (used when rendering the BIA form's
// plan-picker). We keep it lightweight — only the columns the form needs.
function listPlans(tenantId) {
  return db.prepare(`
    SELECT id, title, version, status, owner
    FROM bcp_plans
    WHERE tenant_id = ?
    ORDER BY title COLLATE NOCASE
  `).all(tenantId);
}

// Resolve the plans currently linked to a BIA record along with coverage_type
// so the show page can render them as a "Recovery plans" card.
function plansForBia(tenantId, biaId) {
  return db.prepare(`
    SELECT bpl.id AS link_id, bpl.coverage_type, bpl.notes, bpl.created_at AS linked_at,
           p.id, p.title, p.version, p.status, p.owner
    FROM bia_plan_links bpl
    JOIN bcp_plans p ON p.id = bpl.plan_id
    WHERE bpl.tenant_id = ? AND bpl.bia_id = ?
    ORDER BY CASE bpl.coverage_type
              WHEN 'primary' THEN 0 WHEN 'secondary' THEN 1
              WHEN 'partial' THEN 2 WHEN 'referenced' THEN 3 ELSE 4 END,
             p.title COLLATE NOCASE
  `).all(tenantId, biaId);
}

// Small summary used on the BIA index — one row per BIA with a coverage state
// (green/amber/red) so the list view can surface orphaned critical processes.
function coverageStateFor(tenantId) {
  const rows = db.prepare(`
    SELECT b.id AS bia_id,
           MIN(CASE WHEN bpl.coverage_type = 'primary' THEN 0 ELSE 1 END) AS has_primary_flag,
           COUNT(bpl.id) AS link_count
    FROM bia_records b
    LEFT JOIN bia_plan_links bpl ON bpl.bia_id = b.id AND bpl.tenant_id = b.tenant_id
    WHERE b.tenant_id = ?
    GROUP BY b.id
  `).all(tenantId);
  const map = {};
  rows.forEach(r => {
    const linkCount = r.link_count || 0;
    let state = 'red';
    if (linkCount > 0) {
      state = r.has_primary_flag === 0 ? 'green' : 'amber';
    }
    map[r.bia_id] = { state, link_count: linkCount };
  });
  return map;
}

// Rewrite the link table for a BIA from a submitted form payload.
// `plan_ids` and `coverage_<planId>` come from the edit form.
function syncLinksForBia({ tenantId, biaId, planIds, coverageByPlanId, createdBy }) {
  const valid = (planIds || []).map(Number).filter(n => Number.isFinite(n));
  const tx = db.transaction(() => {
    db.prepare(`DELETE FROM bia_plan_links WHERE tenant_id = ? AND bia_id = ?`).run(tenantId, biaId);
    if (!valid.length) return 0;
    const ins = db.prepare(`
      INSERT INTO bia_plan_links (tenant_id, bia_id, plan_id, coverage_type, created_by)
      VALUES (?, ?, ?, ?, ?)
    `);
    let count = 0;
    for (const planId of valid) {
      // Only allow plans that actually belong to this tenant — defence-in-depth.
      const owned = db.prepare(`SELECT 1 FROM bcp_plans WHERE id = ? AND tenant_id = ?`).get(planId, tenantId);
      if (!owned) continue;
      let coverage = (coverageByPlanId && coverageByPlanId[planId]) || 'primary';
      if (!COVERAGE_TYPES.includes(coverage)) coverage = 'primary';
      ins.run(tenantId, biaId, planId, coverage, createdBy || null);
      count++;
    }
    return count;
  });
  return tx();
}

// -- Index ---------------------------------------------------------------
router.get('/', (req, res) => {
  const rows = db.prepare(`SELECT * FROM bia_records WHERE tenant_id = ? ORDER BY created_at DESC`).all(req.session.tenant.id);
  const coverage = coverageStateFor(req.session.tenant.id);
  res.render('bia/index', { title: 'Business Impact Analysis', rows, coverage });
});

// -- New ------------------------------------------------------------------
router.get('/new', (req, res) => {
  const plans = listPlans(req.session.tenant.id);
  res.render('bia/form', { title: 'New BIA record', record: null, plans, links: [] });
});

// -- Show -----------------------------------------------------------------
router.get('/:id', (req, res) => {
  const record = db.prepare(`SELECT * FROM bia_records WHERE id = ? AND tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!record) { req.flash('error', 'Record not found.'); return res.redirect('/bia'); }
  const linkedPlans = plansForBia(req.session.tenant.id, record.id);
  res.render('bia/show', { title: record.process_name, record, linkedPlans });
});

// -- Edit -----------------------------------------------------------------
router.get('/:id/edit', (req, res) => {
  const record = db.prepare(`SELECT * FROM bia_records WHERE id = ? AND tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!record) { req.flash('error', 'Record not found.'); return res.redirect('/bia'); }
  const plans = listPlans(req.session.tenant.id);
  const links = db.prepare(`
    SELECT plan_id, coverage_type FROM bia_plan_links
    WHERE tenant_id = ? AND bia_id = ?
  `).all(req.session.tenant.id, record.id);
  res.render('bia/form', { title: 'Edit BIA record', record, plans, links });
});

// -- Create / Update ------------------------------------------------------
router.post('/', (req, res) => {
  const b = req.body;
  const criticality = criticalityOf(+b.operational_impact, +b.reputational_impact, +b.regulatory_impact, +b.financial_impact_per_day);
  const info = db.prepare(`
    INSERT INTO bia_records (tenant_id, process_name, department, owner, description, rto_hours, rpo_hours,
      financial_impact_per_day, operational_impact, reputational_impact, regulatory_impact, criticality, dependencies)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    req.session.tenant.id, b.process_name, b.department || null, b.owner || null, b.description || null,
    b.rto_hours || null, b.rpo_hours || null, b.financial_impact_per_day || null,
    b.operational_impact || null, b.reputational_impact || null, b.regulatory_impact || null,
    criticality, b.dependencies || null
  );
  const biaId = info.lastInsertRowid;

  // Plan links (optional on create)
  const planIds = [].concat(b.plan_ids || []);
  const coverageByPlanId = {};
  Object.keys(b).forEach(k => {
    const m = k.match(/^coverage_for_plan_(\d+)$/);
    if (m) coverageByPlanId[m[1]] = b[k];
  });
  const linked = syncLinksForBia({
    tenantId: req.session.tenant.id, biaId, planIds, coverageByPlanId,
    createdBy: req.session.user.name
  });

  req.audit({ action: ACTIONS.CREATE, entity: 'bia_records', entityId: biaId,
    summary: `BIA "${b.process_name}" added${linked ? ` · linked to ${linked} plan${linked === 1 ? '' : 's'}` : ''}` });
  req.flash('success', 'BIA record created.');
  res.redirect('/bia/' + biaId);
});

router.post('/:id', (req, res) => {
  const b = req.body;
  const criticality = criticalityOf(+b.operational_impact, +b.reputational_impact, +b.regulatory_impact, +b.financial_impact_per_day);
  db.prepare(`
    UPDATE bia_records SET process_name=?, department=?, owner=?, description=?, rto_hours=?, rpo_hours=?,
      financial_impact_per_day=?, operational_impact=?, reputational_impact=?, regulatory_impact=?, criticality=?,
      dependencies=?, updated_at=CURRENT_TIMESTAMP
    WHERE id = ? AND tenant_id = ?
  `).run(
    b.process_name, b.department || null, b.owner || null, b.description || null,
    b.rto_hours || null, b.rpo_hours || null, b.financial_impact_per_day || null,
    b.operational_impact || null, b.reputational_impact || null, b.regulatory_impact || null,
    criticality, b.dependencies || null,
    req.params.id, req.session.tenant.id
  );

  const planIds = [].concat(b.plan_ids || []);
  const coverageByPlanId = {};
  Object.keys(b).forEach(k => {
    const m = k.match(/^coverage_for_plan_(\d+)$/);
    if (m) coverageByPlanId[m[1]] = b[k];
  });
  const linked = syncLinksForBia({
    tenantId: req.session.tenant.id, biaId: +req.params.id, planIds, coverageByPlanId,
    createdBy: req.session.user.name
  });

  req.audit({ action: ACTIONS.UPDATE, entity: 'bia_records', entityId: +req.params.id,
    summary: `BIA "${b.process_name}" updated · ${linked} plan link${linked === 1 ? '' : 's'}` });
  req.flash('success', 'BIA record updated.');
  res.redirect('/bia/' + req.params.id);
});

// -- Delete ---------------------------------------------------------------
router.post('/:id/delete', (req, res) => {
  db.prepare(`DELETE FROM bia_records WHERE id = ? AND tenant_id = ?`).run(req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'bia_records', entityId: +req.params.id, summary: 'BIA record removed' });
  req.flash('success', 'BIA record deleted.');
  res.redirect('/bia');
});

module.exports = router;
