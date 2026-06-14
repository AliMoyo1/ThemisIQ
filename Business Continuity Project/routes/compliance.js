// Compliance tracker with baseline ISO 22301 catalog and evidence repo.
// If a tenant has no controls yet for a framework, we seed the catalog.

const express = require('express');
const router = express.Router();
const db = require('../models/db');
const { requireAuth } = require('../middleware/auth');
const { FRAMEWORKS } = require('../services/frameworks');
const { ACTIONS } = require('../services/audit');

router.use(requireAuth);

const STATUSES = ['not_started', 'in_progress', 'implemented', 'verified'];

function seedFrameworkIfEmpty(tenantId, framework) {
  const existing = db.prepare(`SELECT COUNT(*) AS c FROM compliance_controls WHERE tenant_id = ? AND framework = ?`)
    .get(tenantId, framework).c;
  if (existing > 0) return;
  const catalog = FRAMEWORKS[framework];
  if (!catalog) return;
  const ins = db.prepare(`INSERT INTO compliance_controls (tenant_id, framework, clause, title, description) VALUES (?, ?, ?, ?, ?)`);
  catalog.forEach(c => ins.run(tenantId, framework, c.clause, c.title, c.description));
}

function computeMaturity(rows) {
  if (rows.length === 0) return 0;
  const weight = { not_started: 0, in_progress: 0.4, implemented: 0.8, verified: 1 };
  const total = rows.reduce((sum, r) => sum + (weight[r.status] ?? 0), 0);
  return Math.round((total / rows.length) * 100);
}

router.get('/', (req, res) => {
  const framework = req.query.framework || 'ISO 22301';
  seedFrameworkIfEmpty(req.session.tenant.id, framework);

  const rows = db.prepare(`SELECT * FROM compliance_controls WHERE tenant_id = ? AND framework = ? ORDER BY clause ASC`)
    .all(req.session.tenant.id, framework);

  const counts = STATUSES.reduce((acc, s) => {
    acc[s] = rows.filter(r => r.status === s).length;
    return acc;
  }, {});

  const maturity = computeMaturity(rows);

  res.render('compliance/index', {
    title: framework + ' compliance',
    framework,
    frameworks: Object.keys(FRAMEWORKS),
    rows, counts, maturity
  });
});

router.get('/:id', (req, res) => {
  const control = db.prepare(`SELECT * FROM compliance_controls WHERE id = ? AND tenant_id = ?`)
    .get(req.params.id, req.session.tenant.id);
  if (!control) { req.flash('error', 'Control not found.'); return res.redirect('/compliance'); }
  const evidence = db.prepare(`SELECT * FROM compliance_evidence WHERE control_id = ? AND tenant_id = ? ORDER BY created_at DESC`)
    .all(control.id, req.session.tenant.id);
  res.render('compliance/show', { title: control.clause + ' · ' + control.title, control, evidence, STATUSES });
});

router.post('/:id', (req, res) => {
  const b = req.body;
  db.prepare(`UPDATE compliance_controls SET
    status = ?, owner = ?, evidence_notes = ?, last_reviewed = ?, next_review = ?,
    updated_at = CURRENT_TIMESTAMP
    WHERE id = ? AND tenant_id = ?`)
    .run(
      b.status || 'not_started', b.owner || null, b.evidence_notes || null,
      b.last_reviewed || null, b.next_review || null,
      req.params.id, req.session.tenant.id
    );
  req.audit({ action: ACTIONS.UPDATE, entity: 'compliance_controls', entityId: +req.params.id, summary: `Control updated to ${b.status}` });
  req.flash('success', 'Control updated.');
  res.redirect('/compliance/' + req.params.id);
});

router.post('/:id/evidence', (req, res) => {
  const b = req.body;
  const control = db.prepare(`SELECT id FROM compliance_controls WHERE id = ? AND tenant_id = ?`)
    .get(req.params.id, req.session.tenant.id);
  if (!control) { req.flash('error', 'Control not found.'); return res.redirect('/compliance'); }

  db.prepare(`INSERT INTO compliance_evidence (tenant_id, control_id, title, ref_url, notes, uploaded_by)
    VALUES (?, ?, ?, ?, ?, ?)`)
    .run(req.session.tenant.id, control.id, b.title, b.ref_url || null, b.notes || null,
      req.session.user.name);
  req.audit({ action: ACTIONS.CREATE, entity: 'compliance_evidence', entityId: control.id, summary: `Evidence "${b.title}" added` });
  req.flash('success', 'Evidence attached.');
  res.redirect('/compliance/' + control.id);
});

router.post('/:id/evidence/:evidenceId/delete', (req, res) => {
  db.prepare(`DELETE FROM compliance_evidence WHERE id = ? AND control_id = ? AND tenant_id = ?`)
    .run(req.params.evidenceId, req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'compliance_evidence', entityId: +req.params.evidenceId, summary: 'Evidence removed' });
  req.flash('success', 'Evidence removed.');
  res.redirect('/compliance/' + req.params.id);
});

module.exports = router;
