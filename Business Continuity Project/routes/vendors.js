// Vendor / third-party risk management routes.
// Scoring is derived from four 1–5 scales (financial, operational,
// compliance, concentration). Risk score is the max of the four times
// the criticality tier, clamped to 0..25 for a familiar heatmap feel.

const express = require('express');
const router = express.Router();
const db = require('../models/db');
const { requireAuth } = require('../middleware/auth');
const { ACTIONS } = require('../services/audit');

router.use(requireAuth);

function computeScores(b) {
  const fin = +b.financial_score || 0;
  const ops = +b.operational_score || 0;
  const comp = +b.compliance_score || 0;
  const conc = +b.concentration_risk || 0;
  const tier = Math.min(5, Math.max(1, +b.tier || 3));
  const severity = Math.max(fin, ops, comp, conc);
  const score = Math.min(25, severity * (6 - tier)); // tier 1 = most critical multiplier 5
  let criticality = 'Low';
  if (score >= 18) criticality = 'Critical';
  else if (score >= 12) criticality = 'High';
  else if (score >= 6) criticality = 'Medium';
  return { fin, ops, comp, conc, tier, score, criticality };
}

router.get('/', (req, res) => {
  const rows = db.prepare(`SELECT * FROM vendors WHERE tenant_id = ? ORDER BY risk_score DESC, name ASC`)
    .all(req.session.tenant.id);
  const stats = {
    total: rows.length,
    critical: rows.filter(r => r.criticality === 'Critical').length,
    dueForReview: rows.filter(r => r.next_review && r.next_review <= new Date().toISOString().slice(0, 10)).length,
    tier1: rows.filter(r => r.tier === 1).length
  };
  res.render('vendors/index', { title: 'Vendors', rows, stats });
});

router.get('/new', (req, res) => {
  res.render('vendors/form', { title: 'New vendor', vendor: null });
});

router.get('/:id', (req, res) => {
  const vendor = db.prepare(`SELECT * FROM vendors WHERE id = ? AND tenant_id = ?`)
    .get(req.params.id, req.session.tenant.id);
  if (!vendor) { req.flash('error', 'Vendor not found.'); return res.redirect('/vendors'); }
  const assessments = db.prepare(`SELECT * FROM vendor_assessments
    WHERE vendor_id = ? AND tenant_id = ? ORDER BY assessed_on DESC, id DESC`)
    .all(vendor.id, req.session.tenant.id);
  res.render('vendors/show', { title: vendor.name, vendor, assessments });
});

router.get('/:id/edit', (req, res) => {
  const vendor = db.prepare(`SELECT * FROM vendors WHERE id = ? AND tenant_id = ?`)
    .get(req.params.id, req.session.tenant.id);
  if (!vendor) { req.flash('error', 'Vendor not found.'); return res.redirect('/vendors'); }
  res.render('vendors/form', { title: 'Edit vendor', vendor });
});

router.post('/', (req, res) => {
  const b = req.body;
  const s = computeScores(b);
  const info = db.prepare(`INSERT INTO vendors
    (tenant_id, name, category, service_provided, owner, contact_name, contact_email, contact_phone,
     criticality, tier, data_sensitivity, sla, contract_renewal,
     risk_score, financial_score, operational_score, compliance_score, concentration_risk,
     status, notes, last_reviewed, next_review)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
    .run(
      req.session.tenant.id, b.name, b.category || null, b.service_provided || null, b.owner || null,
      b.contact_name || null, b.contact_email || null, b.contact_phone || null,
      s.criticality, s.tier, b.data_sensitivity || null, b.sla || null, b.contract_renewal || null,
      s.score, s.fin, s.ops, s.comp, s.conc,
      b.status || 'active', b.notes || null, b.last_reviewed || null, b.next_review || null
    );
  req.audit({ action: ACTIONS.CREATE, entity: 'vendors', entityId: info.lastInsertRowid, summary: `Vendor ${b.name} added` });
  req.flash('success', 'Vendor added.');
  res.redirect('/vendors/' + info.lastInsertRowid);
});

router.post('/:id', (req, res) => {
  const b = req.body;
  const s = computeScores(b);
  db.prepare(`UPDATE vendors SET
    name=?, category=?, service_provided=?, owner=?, contact_name=?, contact_email=?, contact_phone=?,
    criticality=?, tier=?, data_sensitivity=?, sla=?, contract_renewal=?,
    risk_score=?, financial_score=?, operational_score=?, compliance_score=?, concentration_risk=?,
    status=?, notes=?, last_reviewed=?, next_review=?, updated_at=CURRENT_TIMESTAMP
    WHERE id = ? AND tenant_id = ?`)
    .run(
      b.name, b.category || null, b.service_provided || null, b.owner || null,
      b.contact_name || null, b.contact_email || null, b.contact_phone || null,
      s.criticality, s.tier, b.data_sensitivity || null, b.sla || null, b.contract_renewal || null,
      s.score, s.fin, s.ops, s.comp, s.conc,
      b.status || 'active', b.notes || null, b.last_reviewed || null, b.next_review || null,
      req.params.id, req.session.tenant.id
    );
  req.audit({ action: ACTIONS.UPDATE, entity: 'vendors', entityId: +req.params.id, summary: `Vendor ${b.name} updated` });
  req.flash('success', 'Vendor updated.');
  res.redirect('/vendors/' + req.params.id);
});

router.post('/:id/delete', (req, res) => {
  const v = db.prepare('SELECT name FROM vendors WHERE id = ? AND tenant_id = ?')
    .get(req.params.id, req.session.tenant.id);
  db.prepare(`DELETE FROM vendors WHERE id = ? AND tenant_id = ?`).run(req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'vendors', entityId: +req.params.id, summary: `Vendor ${v?.name || ''} removed` });
  req.flash('success', 'Vendor removed.');
  res.redirect('/vendors');
});

// ---- Assessments (snapshots) ----
router.post('/:id/assessments', (req, res) => {
  const b = req.body;
  const vendor = db.prepare('SELECT id FROM vendors WHERE id = ? AND tenant_id = ?')
    .get(req.params.id, req.session.tenant.id);
  if (!vendor) { req.flash('error', 'Vendor not found.'); return res.redirect('/vendors'); }
  db.prepare(`INSERT INTO vendor_assessments (tenant_id, vendor_id, assessed_on, assessor, score, summary, findings)
    VALUES (?, ?, COALESCE(?, CURRENT_DATE), ?, ?, ?, ?)`)
    .run(req.session.tenant.id, vendor.id, b.assessed_on || null,
      b.assessor || req.session.user.name, +b.score || null,
      b.summary || null, b.findings || null);
  req.audit({ action: ACTIONS.CREATE, entity: 'vendor_assessments', entityId: vendor.id, summary: 'Assessment recorded' });
  req.flash('success', 'Assessment recorded.');
  res.redirect('/vendors/' + vendor.id);
});

module.exports = router;
