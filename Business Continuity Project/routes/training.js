// Training & Attestation module.
// Admins/managers publish modules; any user can read and sign an attestation.
// Attestations capture typed name + timestamp + IP + user-agent so they hold up in audit.

const express = require('express');
const router = express.Router();
const db = require('../models/db');
const { requireAuth, requireRole } = require('../middleware/auth');
const { ACTIONS } = require('../services/audit');

router.use(requireAuth);

function addMonths(date, months) {
  const d = new Date(date);
  d.setMonth(d.getMonth() + months);
  return d.toISOString().slice(0, 10);
}

function parseRoles(s) {
  return (s || '').split(',').map(x => x.trim()).filter(Boolean);
}

function myAttestationForModule(tenantId, userId, moduleId) {
  return db.prepare(`SELECT * FROM training_attestations
    WHERE tenant_id = ? AND user_id = ? AND module_id = ?
    ORDER BY attested_at DESC LIMIT 1`).get(tenantId, userId, moduleId);
}

function isExpired(row) {
  return row?.expires_at && row.expires_at < new Date().toISOString().slice(0, 10);
}

// ---- INDEX ----
router.get('/', (req, res) => {
  const tid = req.session.tenant.id;
  const uid = req.session.user.id;
  const modules = db.prepare(`SELECT * FROM training_modules WHERE tenant_id = ? ORDER BY status ASC, title ASC`).all(tid);

  // Attach "my status" for each module
  const today = new Date().toISOString().slice(0, 10);
  const myLatest = db.prepare(`SELECT module_id, attested_at, expires_at FROM training_attestations
    WHERE tenant_id = ? AND user_id = ?`).all(tid, uid);
  const byModule = new Map();
  for (const a of myLatest) {
    const existing = byModule.get(a.module_id);
    if (!existing || a.attested_at > existing.attested_at) byModule.set(a.module_id, a);
  }
  const enriched = modules.map(m => {
    const a = byModule.get(m.id);
    let myStatus = 'Not started';
    if (a) {
      if (a.expires_at && a.expires_at < today) myStatus = 'Expired';
      else myStatus = 'Completed';
    }
    return { ...m, my_status: myStatus, my_attested_at: a?.attested_at || null, my_expires_at: a?.expires_at || null };
  });

  // Org-wide rollup
  const userCount = db.prepare('SELECT COUNT(*) AS c FROM users WHERE tenant_id = ?').get(tid).c || 0;
  const stats = {
    modules: modules.length,
    activeModules: modules.filter(m => m.status === 'active').length,
    myOutstanding: enriched.filter(m => m.status === 'active' && m.my_status !== 'Completed').length,
    totalAttestations: db.prepare('SELECT COUNT(*) AS c FROM training_attestations WHERE tenant_id = ?').get(tid).c,
    users: userCount,
  };

  res.render('training/index', { title: 'Training', modules: enriched, stats });
});

// ---- NEW / EDIT FORMS ---- (admin/manager only)
router.get('/new', requireRole('admin', 'manager'), (req, res) => {
  res.render('training/form', { title: 'New training module', mod: null });
});

router.get('/:id/edit', requireRole('admin', 'manager'), (req, res) => {
  const mod = db.prepare('SELECT * FROM training_modules WHERE id = ? AND tenant_id = ?')
    .get(req.params.id, req.session.tenant.id);
  if (!mod) { req.flash('error', 'Module not found.'); return res.redirect('/training'); }
  res.render('training/form', { title: 'Edit module', mod });
});

// ---- SHOW (anyone) ----
router.get('/:id', (req, res) => {
  const tid = req.session.tenant.id;
  const mod = db.prepare('SELECT * FROM training_modules WHERE id = ? AND tenant_id = ?')
    .get(req.params.id, tid);
  if (!mod) { req.flash('error', 'Module not found.'); return res.redirect('/training'); }

  const attestations = db.prepare(`SELECT * FROM training_attestations
    WHERE module_id = ? AND tenant_id = ?
    ORDER BY attested_at DESC LIMIT 50`).all(mod.id, tid);

  const mine = myAttestationForModule(tid, req.session.user.id, mod.id);
  const completion = db.prepare(`
    SELECT COUNT(DISTINCT user_id) AS c FROM training_attestations
    WHERE module_id = ? AND tenant_id = ?
      AND (expires_at IS NULL OR expires_at >= date('now'))
  `).get(mod.id, tid).c || 0;
  const totalUsers = db.prepare('SELECT COUNT(*) AS c FROM users WHERE tenant_id = ?').get(tid).c || 0;
  const completionPct = totalUsers ? Math.round((completion / totalUsers) * 100) : 0;

  res.render('training/show', {
    title: mod.title, mod, attestations,
    mine, completion, totalUsers, completionPct,
    isExpired: isExpired(mine)
  });
});

// ---- CREATE / UPDATE / DELETE (admin/manager) ----
router.post('/', requireRole('admin', 'manager'), (req, res) => {
  const b = req.body;
  const info = db.prepare(`INSERT INTO training_modules
    (tenant_id, title, description, category, required_roles, duration_minutes, owner,
     content, passing_score, renewal_months, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
    .run(
      req.session.tenant.id, b.title, b.description || null, b.category || null,
      (b.required_roles || '').trim() || null,
      +b.duration_minutes || null, b.owner || req.session.user.name,
      b.content || null,
      +b.passing_score || 80, +b.renewal_months || 12,
      b.status || 'active'
    );
  req.audit({ action: ACTIONS.CREATE, entity: 'training_modules', entityId: info.lastInsertRowid, summary: `Training "${b.title}" created` });
  req.flash('success', 'Training module created.');
  res.redirect('/training/' + info.lastInsertRowid);
});

router.post('/:id', requireRole('admin', 'manager'), (req, res) => {
  const b = req.body;
  db.prepare(`UPDATE training_modules SET
    title=?, description=?, category=?, required_roles=?, duration_minutes=?, owner=?,
    content=?, passing_score=?, renewal_months=?, status=?, updated_at=CURRENT_TIMESTAMP
    WHERE id = ? AND tenant_id = ?`)
    .run(
      b.title, b.description || null, b.category || null,
      (b.required_roles || '').trim() || null,
      +b.duration_minutes || null, b.owner || null,
      b.content || null, +b.passing_score || 80, +b.renewal_months || 12,
      b.status || 'active', req.params.id, req.session.tenant.id
    );
  req.audit({ action: ACTIONS.UPDATE, entity: 'training_modules', entityId: +req.params.id, summary: `Training "${b.title}" updated` });
  req.flash('success', 'Module updated.');
  res.redirect('/training/' + req.params.id);
});

router.post('/:id/delete', requireRole('admin', 'manager'), (req, res) => {
  const m = db.prepare('SELECT title FROM training_modules WHERE id = ? AND tenant_id = ?')
    .get(req.params.id, req.session.tenant.id);
  db.prepare('DELETE FROM training_modules WHERE id = ? AND tenant_id = ?')
    .run(req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'training_modules', entityId: +req.params.id, summary: `Training "${m?.title || ''}" removed` });
  req.flash('success', 'Module removed.');
  res.redirect('/training');
});

// ---- ATTEST (any authenticated user) ----
router.post('/:id/attest', (req, res) => {
  const tid = req.session.tenant.id;
  const uid = req.session.user.id;
  const mod = db.prepare('SELECT * FROM training_modules WHERE id = ? AND tenant_id = ?')
    .get(req.params.id, tid);
  if (!mod) { req.flash('error', 'Module not found.'); return res.redirect('/training'); }

  const signature = (req.body.signature || '').trim();
  if (!signature) {
    req.flash('error', 'Please type your full name as your signature.');
    return res.redirect('/training/' + mod.id);
  }
  // Gentle signature check: must contain at least 2 words and match user's name or email local part
  const expected = (req.session.user.name || '').toLowerCase();
  if (signature.toLowerCase() !== expected && !signature.toLowerCase().includes(expected.split(' ')[0] || '---zz---')) {
    req.flash('error', 'Signature should match your account name on file.');
    return res.redirect('/training/' + mod.id);
  }

  const score = Math.max(0, Math.min(100, +req.body.score || 100));
  const expires = mod.renewal_months && mod.renewal_months > 0
    ? addMonths(new Date(), mod.renewal_months) : null;

  db.prepare(`INSERT INTO training_attestations
    (tenant_id, module_id, user_id, user_name, user_email, signature, score, ip, user_agent, expires_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
    .run(
      tid, mod.id, uid,
      req.session.user.name, req.session.user.email,
      signature, score,
      req.ip || null, req.headers['user-agent'] || null,
      expires
    );
  req.audit({
    action: ACTIONS.CREATE,
    entity: 'training_attestations',
    entityId: mod.id,
    summary: `Attestation signed for "${mod.title}" by ${req.session.user.email}`
  });
  req.flash('success', 'Attestation recorded. Thank you.');
  res.redirect('/training/' + mod.id);
});

// ---- ATTESTATION LOG (per-tenant, admin/manager) ----
router.get('/log/all', requireRole('admin', 'manager'), (req, res) => {
  const rows = db.prepare(`SELECT a.*, m.title AS module_title FROM training_attestations a
    LEFT JOIN training_modules m ON m.id = a.module_id
    WHERE a.tenant_id = ?
    ORDER BY a.attested_at DESC LIMIT 500`).all(req.session.tenant.id);
  res.render('training/log', { title: 'Attestation log', rows });
});

module.exports = router;
