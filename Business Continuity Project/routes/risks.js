const express = require('express');
const router = express.Router();
const db = require('../models/db');
const { requireAuth } = require('../middleware/auth');
const { scheduleRiskDueReminder } = require('../services/scheduler');
const { ACTIONS } = require('../services/audit');

router.use(requireAuth);

router.get('/', (req, res) => {
  const rows = db.prepare(`SELECT * FROM risks WHERE tenant_id = ? ORDER BY score DESC, created_at DESC`).all(req.session.tenant.id);
  res.render('risks/index', { title: 'Risk Register', rows });
});

router.get('/new', (req, res) => {
  res.render('risks/form', { title: 'New risk', risk: null });
});

router.get('/:id', (req, res) => {
  const risk = db.prepare(`SELECT * FROM risks WHERE id = ? AND tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!risk) { req.flash('error', 'Risk not found.'); return res.redirect('/risks'); }
  res.render('risks/show', { title: risk.title, risk });
});

router.get('/:id/edit', (req, res) => {
  const risk = db.prepare(`SELECT * FROM risks WHERE id = ? AND tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!risk) { req.flash('error', 'Risk not found.'); return res.redirect('/risks'); }
  res.render('risks/form', { title: 'Edit risk', risk });
});

router.post('/', (req, res) => {
  const b = req.body;
  const likelihood = +b.likelihood || 0, impact = +b.impact || 0;
  const score = likelihood * impact;
  const info = db.prepare(`
    INSERT INTO risks (tenant_id, title, category, description, likelihood, impact, score, treatment, mitigation, owner, status, due_date)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    req.session.tenant.id, b.title, b.category || null, b.description || null,
    likelihood, impact, score, b.treatment || 'Mitigate', b.mitigation || null,
    b.owner || null, b.status || 'open', b.due_date || null
  );
  if (b.due_date) scheduleRiskDueReminder(info.lastInsertRowid, req.session.tenant.id);
  req.audit({ action: ACTIONS.CREATE, entity: 'risks', entityId: info.lastInsertRowid, summary: `Risk "${b.title}" logged` });
  req.flash('success', 'Risk logged.');
  res.redirect('/risks');
});

router.post('/:id', (req, res) => {
  const b = req.body;
  const likelihood = +b.likelihood || 0, impact = +b.impact || 0;
  const score = likelihood * impact;
  db.prepare(`
    UPDATE risks SET title=?, category=?, description=?, likelihood=?, impact=?, score=?, treatment=?, mitigation=?, owner=?, status=?, due_date=?, updated_at=CURRENT_TIMESTAMP
    WHERE id = ? AND tenant_id = ?
  `).run(
    b.title, b.category || null, b.description || null, likelihood, impact, score,
    b.treatment || 'Mitigate', b.mitigation || null, b.owner || null, b.status || 'open',
    b.due_date || null, req.params.id, req.session.tenant.id
  );
  req.audit({ action: ACTIONS.UPDATE, entity: 'risks', entityId: +req.params.id, summary: `Risk "${b.title}" updated` });
  req.flash('success', 'Risk updated.');
  res.redirect('/risks/' + req.params.id);
});

router.post('/:id/delete', (req, res) => {
  db.prepare(`DELETE FROM risks WHERE id = ? AND tenant_id = ?`).run(req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'risks', entityId: +req.params.id, summary: 'Risk removed' });
  req.flash('success', 'Risk removed.');
  res.redirect('/risks');
});

module.exports = router;
