// Coverage dashboard — one page that answers the question:
// "Are our critical business processes actually covered by a continuity plan?"
//
// It surfaces three things:
//   1. Coverage breakdown for BIA processes (green / amber / red, split by criticality)
//   2. Orphan plans (plans that aren't linked to any BIA process)
//   3. A detail table of every BIA record with its linked plans
const express = require('express');
const router = express.Router();
const db = require('../models/db');
const { requireAuth } = require('../middleware/auth');

router.use(requireAuth);

router.get('/', (req, res) => {
  const tenantId = req.session.tenant.id;

  // All BIA records for this tenant with a pre-aggregated link summary.
  // has_primary_flag = 0 means at least one link is 'primary' (min is 0).
  const bias = db.prepare(`
    SELECT b.*,
           COUNT(bpl.id) AS link_count,
           MIN(CASE WHEN bpl.coverage_type = 'primary' THEN 0 ELSE 1 END) AS has_primary_flag
    FROM bia_records b
    LEFT JOIN bia_plan_links bpl ON bpl.bia_id = b.id AND bpl.tenant_id = b.tenant_id
    WHERE b.tenant_id = ?
    GROUP BY b.id
    ORDER BY CASE b.criticality WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 WHEN 'Low' THEN 3 ELSE 4 END,
             b.process_name COLLATE NOCASE
  `).all(tenantId);

  // Each BIA gets a coverage state plus a pre-fetched set of linked plans
  // (small lookup — 90%+ of tenants will have <50 BIA records).
  const linkByBia = db.prepare(`
    SELECT bpl.bia_id, bpl.coverage_type, p.id AS plan_id, p.title, p.version, p.status
    FROM bia_plan_links bpl
    JOIN bcp_plans p ON p.id = bpl.plan_id
    WHERE bpl.tenant_id = ?
    ORDER BY CASE bpl.coverage_type
              WHEN 'primary' THEN 0 WHEN 'secondary' THEN 1
              WHEN 'partial' THEN 2 WHEN 'referenced' THEN 3 ELSE 4 END,
             p.title COLLATE NOCASE
  `).all(tenantId);
  const plansByBia = {};
  linkByBia.forEach(l => {
    (plansByBia[l.bia_id] = plansByBia[l.bia_id] || []).push(l);
  });

  // Categorise every BIA record.
  const rows = bias.map(b => {
    const linkCount = b.link_count || 0;
    let state = 'red';
    if (linkCount > 0) state = b.has_primary_flag === 0 ? 'green' : 'amber';
    return { ...b, state, plans: plansByBia[b.id] || [] };
  });

  // Aggregate counts for the summary cards.
  const summary = {
    total: rows.length,
    green: rows.filter(r => r.state === 'green').length,
    amber: rows.filter(r => r.state === 'amber').length,
    red:   rows.filter(r => r.state === 'red').length,
    criticalRed: rows.filter(r => r.state === 'red' && (r.criticality === 'Critical' || r.criticality === 'High')).length
  };

  // Orphan plans — plans that exist but aren't linked to any BIA process.
  const orphanPlans = db.prepare(`
    SELECT p.*
    FROM bcp_plans p
    LEFT JOIN bia_plan_links bpl ON bpl.plan_id = p.id AND bpl.tenant_id = p.tenant_id
    WHERE p.tenant_id = ? AND bpl.id IS NULL
    ORDER BY p.updated_at DESC
  `).all(tenantId);

  res.render('coverage/index', {
    title: 'Coverage map',
    rows,
    summary,
    orphanPlans
  });
});

module.exports = router;
