// Tabletop / walkthrough / simulation exercises and their
// after-action reports (AAR). Each exercise may link to a BCP plan.

const express = require('express');
const router = express.Router();
const db = require('../models/db');
const { requireAuth } = require('../middleware/auth');
const { ACTIONS } = require('../services/audit');
const { buildExerciseDoc, safeFilename } = require('../services/word-export');

router.use(requireAuth);

router.get('/', (req, res) => {
  const rows = db.prepare(`
    SELECT e.*, p.title AS plan_title
    FROM exercises e
    LEFT JOIN bcp_plans p ON p.id = e.plan_id AND p.tenant_id = e.tenant_id
    WHERE e.tenant_id = ?
    ORDER BY COALESCE(e.scheduled_date, e.created_at) DESC
  `).all(req.session.tenant.id);
  const stats = {
    total: rows.length,
    planned: rows.filter(r => r.status === 'planned').length,
    completed: rows.filter(r => r.status === 'completed').length,
    passed: rows.filter(r => r.outcome === 'pass').length
  };
  res.render('exercises/index', { title: 'Exercises', rows, stats });
});

router.get('/new', (req, res) => {
  const plans = db.prepare(`SELECT id, title FROM bcp_plans WHERE tenant_id = ? ORDER BY title ASC`)
    .all(req.session.tenant.id);
  res.render('exercises/form', { title: 'Schedule exercise', exercise: null, plans });
});

router.get('/:id', (req, res) => {
  const ex = db.prepare(`SELECT e.*, p.title AS plan_title
    FROM exercises e LEFT JOIN bcp_plans p ON p.id = e.plan_id AND p.tenant_id = e.tenant_id
    WHERE e.id = ? AND e.tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!ex) { req.flash('error', 'Exercise not found.'); return res.redirect('/exercises'); }
  res.render('exercises/show', { title: ex.title, exercise: ex });
});

router.get('/:id/edit', (req, res) => {
  const ex = db.prepare(`SELECT * FROM exercises WHERE id = ? AND tenant_id = ?`)
    .get(req.params.id, req.session.tenant.id);
  if (!ex) { req.flash('error', 'Exercise not found.'); return res.redirect('/exercises'); }
  const plans = db.prepare(`SELECT id, title FROM bcp_plans WHERE tenant_id = ? ORDER BY title ASC`)
    .all(req.session.tenant.id);
  res.render('exercises/form', { title: 'Edit exercise', exercise: ex, plans });
});

// Export exercise + its AAR as a branded .docx
router.get('/:id/export.docx', async (req, res, next) => {
  try {
    const ex = db.prepare(`SELECT e.*, p.title AS plan_title
      FROM exercises e LEFT JOIN bcp_plans p ON p.id = e.plan_id AND p.tenant_id = e.tenant_id
      WHERE e.id = ? AND e.tenant_id = ?`).get(req.params.id, req.session.tenant.id);
    if (!ex) { req.flash('error', 'Exercise not found.'); return res.redirect('/exercises'); }

    const buf = await buildExerciseDoc(ex, {
      tenantName: req.session.tenant.name,
      generatedBy: req.session.user.name
    });
    const filename = safeFilename(`${ex.title}_${ex.type || 'exercise'}`) + '.docx';

    req.audit({ action: ACTIONS.EXPORT, entity: 'exercises', entityId: ex.id,
      summary: `Exercise "${ex.title}" exported to Word` });

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
  const info = db.prepare(`INSERT INTO exercises
    (tenant_id, title, type, scenario, plan_id, scheduled_date, duration_minutes,
     facilitator, participants, objectives, status, outcome,
     aar_summary, aar_strengths, aar_gaps, aar_actions)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
    .run(
      req.session.tenant.id, b.title, b.type || 'tabletop', b.scenario || null,
      b.plan_id ? +b.plan_id : null, b.scheduled_date || null,
      b.duration_minutes ? +b.duration_minutes : null,
      b.facilitator || null, b.participants || null, b.objectives || null,
      b.status || 'planned', b.outcome || null,
      b.aar_summary || null, b.aar_strengths || null, b.aar_gaps || null, b.aar_actions || null
    );
  req.audit({ action: ACTIONS.CREATE, entity: 'exercises', entityId: info.lastInsertRowid, summary: `Exercise "${b.title}" scheduled` });
  req.flash('success', 'Exercise scheduled.');
  res.redirect('/exercises/' + info.lastInsertRowid);
});

router.post('/:id', (req, res) => {
  const b = req.body;
  db.prepare(`UPDATE exercises SET
    title=?, type=?, scenario=?, plan_id=?, scheduled_date=?, duration_minutes=?,
    facilitator=?, participants=?, objectives=?, status=?, outcome=?,
    aar_summary=?, aar_strengths=?, aar_gaps=?, aar_actions=?,
    updated_at=CURRENT_TIMESTAMP
    WHERE id = ? AND tenant_id = ?`)
    .run(
      b.title, b.type || 'tabletop', b.scenario || null,
      b.plan_id ? +b.plan_id : null, b.scheduled_date || null,
      b.duration_minutes ? +b.duration_minutes : null,
      b.facilitator || null, b.participants || null, b.objectives || null,
      b.status || 'planned', b.outcome || null,
      b.aar_summary || null, b.aar_strengths || null, b.aar_gaps || null, b.aar_actions || null,
      req.params.id, req.session.tenant.id
    );
  req.audit({ action: ACTIONS.UPDATE, entity: 'exercises', entityId: +req.params.id, summary: `Exercise "${b.title}" updated` });
  req.flash('success', 'Exercise updated.');
  res.redirect('/exercises/' + req.params.id);
});

router.post('/:id/delete', (req, res) => {
  db.prepare(`DELETE FROM exercises WHERE id = ? AND tenant_id = ?`)
    .run(req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'exercises', entityId: +req.params.id, summary: 'Exercise removed' });
  req.flash('success', 'Exercise removed.');
  res.redirect('/exercises');
});

module.exports = router;
