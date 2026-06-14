const express = require('express');
const bcrypt = require('bcryptjs');
const router = express.Router();
const db = require('../models/db');
const { requireAuth, requireRole } = require('../middleware/auth');
const { sendTestEmail } = require('../services/mailer');

router.use(requireAuth);

router.get('/', (req, res) => {
  const tenant = db.prepare('SELECT * FROM tenants WHERE id = ?').get(req.session.tenant.id);
  const users = db.prepare('SELECT id, name, email, role, created_at FROM users WHERE tenant_id = ? ORDER BY created_at ASC').all(req.session.tenant.id);
  res.render('settings/index', { title: 'Settings', tenantRecord: tenant, users });
});

// Update tenant profile
router.post('/tenant', requireRole('admin'), (req, res) => {
  const { name, industry } = req.body;
  db.prepare('UPDATE tenants SET name = ?, industry = ? WHERE id = ?')
    .run(name, industry || null, req.session.tenant.id);
  req.session.tenant.name = name;
  req.flash('success', 'Workspace updated.');
  res.redirect('/settings');
});

// Update AI provider + keys
router.post('/ai', requireRole('admin'), (req, res) => {
  const { ai_provider, ai_openai_key, ai_anthropic_key } = req.body;
  db.prepare(`
    UPDATE tenants SET ai_provider = ?, ai_openai_key = ?, ai_anthropic_key = ? WHERE id = ?
  `).run(
    ai_provider || 'openai',
    ai_openai_key || null,
    ai_anthropic_key || null,
    req.session.tenant.id
  );
  req.flash('success', 'AI configuration saved.');
  res.redirect('/settings#ai');
});

// Update current user's profile + password
router.post('/profile', (req, res) => {
  const { name, password } = req.body;
  const updates = ['name = ?'];
  const params = [name];
  if (password && password.length >= 8) {
    updates.push('password_hash = ?');
    params.push(bcrypt.hashSync(password, 10));
  }
  params.push(req.session.user.id);
  db.prepare(`UPDATE users SET ${updates.join(', ')} WHERE id = ?`).run(...params);
  req.session.user.name = name;
  req.flash('success', 'Profile saved.');
  res.redirect('/settings');
});

// Invite teammate
router.post('/invite', requireRole('admin', 'manager'), (req, res) => {
  const { name, email, role, password } = req.body;
  if (!name || !email || !password || password.length < 8) {
    req.flash('error', 'Name, email, and an 8+ character password are required.');
    return res.redirect('/settings');
  }
  const cleanEmail = email.trim().toLowerCase();
  const exists = db.prepare('SELECT id FROM users WHERE email = ?').get(cleanEmail);
  if (exists) { req.flash('error', 'Email already in use.'); return res.redirect('/settings'); }

  db.prepare(`INSERT INTO users (tenant_id, name, email, password_hash, role) VALUES (?, ?, ?, ?, ?)`)
    .run(req.session.tenant.id, name, cleanEmail, bcrypt.hashSync(password, 10), role || 'viewer');
  req.flash('success', `Invited ${name}.`);
  res.redirect('/settings');
});

// Change a user's role
router.post('/users/:id/role', requireRole('admin'), (req, res) => {
  const { role } = req.body;
  db.prepare('UPDATE users SET role = ? WHERE id = ? AND tenant_id = ?')
    .run(role, req.params.id, req.session.tenant.id);
  req.flash('success', 'Role updated.');
  res.redirect('/settings');
});

router.post('/users/:id/delete', requireRole('admin'), (req, res) => {
  if (+req.params.id === req.session.user.id) {
    req.flash('error', 'You cannot remove yourself.');
    return res.redirect('/settings');
  }
  db.prepare('DELETE FROM users WHERE id = ? AND tenant_id = ?').run(req.params.id, req.session.tenant.id);
  req.flash('success', 'User removed.');
  res.redirect('/settings');
});

// Test SMTP
router.post('/test-email', requireRole('admin', 'manager'), async (req, res) => {
  try {
    const result = await sendTestEmail(req.session.user.email);
    if (result.skipped) req.flash('error', 'SMTP not configured — nothing sent.');
    else req.flash('success', `Test email sent to ${req.session.user.email}.`);
  } catch (err) {
    req.flash('error', 'Test email failed: ' + err.message);
  }
  res.redirect('/settings#notifications');
});

module.exports = router;
