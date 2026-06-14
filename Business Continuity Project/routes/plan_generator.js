const express = require('express');
const router = express.Router();
const db = require('../models/db');
const { requireAuth } = require('../middleware/auth');
const { generatePlan } = require('../services/ai');

router.use(requireAuth);

router.get('/', (req, res) => {
  res.render('plan_generator/index', { title: 'AI Plan Generator', draft: null, form: {} });
});

router.post('/', async (req, res) => {
  const { scope, scenario, industry } = req.body;
  const tenant = db.prepare('SELECT * FROM tenants WHERE id = ?').get(req.session.tenant.id);
  try {
    const { content, provider } = await generatePlan({
      tenantId: req.session.tenant.id,
      scope, scenario, industry: industry || tenant.industry,
      orgName: tenant.name
    });
    res.render('plan_generator/index', {
      title: 'AI Plan Generator',
      draft: { content, provider, title: (scope ? scope + ' continuity plan' : 'Continuity plan') },
      form: { scope, scenario, industry }
    });
  } catch (err) {
    console.error(err);
    req.flash('error', 'Plan generation failed: ' + err.message);
    res.redirect('/plan-generator');
  }
});

// Save generated draft as a real BCP plan
router.post('/save', (req, res) => {
  const { title, scope, content } = req.body;
  if (!title || !content) { req.flash('error', 'Missing title or content.'); return res.redirect('/plan-generator'); }
  const info = db.prepare(`
    INSERT INTO bcp_plans (tenant_id, title, scope, owner, version, status, content, last_reviewed, next_review)
    VALUES (?, ?, ?, ?, '1.0', 'draft', ?, NULL, date('now','+1 year'))
  `).run(req.session.tenant.id, title, scope || null, req.session.user.name, content);
  req.flash('success', 'Plan saved to your BCP library.');
  res.redirect('/bcp/' + info.lastInsertRowid);
});

module.exports = router;
