const express = require('express');
const bcrypt = require('bcryptjs');
const router = express.Router();
const db = require('../models/db');
const { record: audit, ACTIONS } = require('../services/audit');

// -- Helpers --------------------------------------------------------------
function slugify(s) {
  return (s || '').toString().toLowerCase().trim()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48);
}

// -- GET /login -----------------------------------------------------------
router.get('/login', (req, res) => {
  if (req.session.user) return res.redirect('/dashboard');
  res.render('auth/login', { title: 'Sign in', layout: 'layout' });
});

// -- POST /login ----------------------------------------------------------
router.post('/login', (req, res) => {
  const { email, password } = req.body;
  if (!email || !password) {
    req.flash('error', 'Email and password are required.');
    return res.redirect('/login');
  }
  const user = db.prepare('SELECT * FROM users WHERE email = ?').get(email.trim().toLowerCase());
  if (!user || !bcrypt.compareSync(password, user.password_hash)) {
    req.flash('error', 'Invalid credentials.');
    return res.redirect('/login');
  }
  const tenant = db.prepare('SELECT * FROM tenants WHERE id = ?').get(user.tenant_id);
  req.session.user = { id: user.id, name: user.name, email: user.email, role: user.role };
  req.session.tenant = { id: tenant.id, name: tenant.name, slug: tenant.slug };
  audit({ tenantId: tenant.id, userId: user.id, userEmail: user.email, action: ACTIONS.LOGIN,
    entity: 'users', entityId: user.id, summary: 'User signed in',
    ip: req.ip, userAgent: req.headers['user-agent'] });
  req.flash('success', `Welcome back, ${user.name.split(' ')[0]}.`);
  res.redirect('/dashboard');
});

// -- GET /signup ----------------------------------------------------------
router.get('/signup', (req, res) => {
  if (req.session.user) return res.redirect('/dashboard');
  res.render('auth/signup', { title: 'Create workspace', layout: 'layout' });
});

// -- POST /signup ---------------------------------------------------------
router.post('/signup', (req, res) => {
  const { company, industry, name, email, password } = req.body;
  if (!company || !name || !email || !password) {
    req.flash('error', 'All fields are required.');
    return res.redirect('/signup');
  }
  if (password.length < 8) {
    req.flash('error', 'Password must be at least 8 characters.');
    return res.redirect('/signup');
  }

  const cleanEmail = email.trim().toLowerCase();
  const existing = db.prepare('SELECT id FROM users WHERE email = ?').get(cleanEmail);
  if (existing) {
    req.flash('error', 'An account with that email already exists.');
    return res.redirect('/signup');
  }

  let slug = slugify(company);
  let attempt = 0;
  while (db.prepare('SELECT id FROM tenants WHERE slug = ?').get(slug)) {
    attempt += 1; slug = `${slugify(company)}-${attempt}`;
  }

  const tx = db.transaction(() => {
    const tenantIns = db.prepare(`INSERT INTO tenants (name, slug, industry, ai_provider) VALUES (?, ?, ?, ?)`)
      .run(company, slug, industry || null, process.env.AI_DEFAULT_PROVIDER || 'openai');
    const tenantId = tenantIns.lastInsertRowid;

    const hash = bcrypt.hashSync(password, 10);
    const userIns = db.prepare(`INSERT INTO users (tenant_id, name, email, password_hash, role) VALUES (?, ?, ?, ?, 'admin')`)
      .run(tenantId, name, cleanEmail, hash);

    return { tenantId, userId: userIns.lastInsertRowid };
  });

  try {
    const { tenantId, userId } = tx();
    const user = db.prepare('SELECT * FROM users WHERE id = ?').get(userId);
    const tenant = db.prepare('SELECT * FROM tenants WHERE id = ?').get(tenantId);
    req.session.user = { id: user.id, name: user.name, email: user.email, role: user.role };
    req.session.tenant = { id: tenant.id, name: tenant.name, slug: tenant.slug };
    audit({ tenantId: tenant.id, userId: user.id, userEmail: user.email, action: ACTIONS.CREATE,
      entity: 'tenants', entityId: tenant.id, summary: `Workspace "${company}" created`,
      ip: req.ip, userAgent: req.headers['user-agent'] });
    req.flash('success', `Workspace "${company}" is ready. Welcome aboard.`);
    res.redirect('/dashboard');
  } catch (err) {
    console.error(err);
    req.flash('error', 'Unable to create workspace. Please try again.');
    res.redirect('/signup');
  }
});

// -- POST /logout ---------------------------------------------------------
router.post('/logout', (req, res) => {
  const u = req.session.user, t = req.session.tenant;
  if (u && t) audit({ tenantId: t.id, userId: u.id, userEmail: u.email, action: ACTIONS.LOGOUT,
    entity: 'users', entityId: u.id, summary: 'User signed out',
    ip: req.ip, userAgent: req.headers['user-agent'] });
  req.session.destroy(() => res.redirect('/login'));
});

module.exports = router;
