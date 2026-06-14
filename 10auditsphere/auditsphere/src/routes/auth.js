const express = require('express');
const router = express.Router();
const bcrypt = require('bcryptjs');
const { v4: uuidv4 } = require('uuid');
const db = require('../database');

router.post('/login', (req, res) => {
  const { email, password } = req.body;
  if (!email || !password) return res.status(400).json({ error: 'Email and password required' });

  const user = db.prepare('SELECT * FROM users WHERE email = ?').get(email);
  if (!user) return res.status(401).json({ error: 'Invalid credentials' });

  const valid = bcrypt.compareSync(password, user.password);
  if (!valid) return res.status(401).json({ error: 'Invalid credentials' });

  req.session.user = { id: user.id, name: user.name, email: user.email, role: user.role, initials: user.avatar_initials };
  res.json({ success: true, user: req.session.user });
});

router.post('/logout', (req, res) => {
  req.session.destroy();
  res.json({ success: true });
});

router.get('/me', (req, res) => {
  if (!req.session.user) return res.status(401).json({ error: 'Not authenticated' });
  res.json(req.session.user);
});

router.post('/register', (req, res) => {
  const { name, email, password, role } = req.body;
  if (!name || !email || !password) return res.status(400).json({ error: 'All fields required' });

  const existing = db.prepare('SELECT id FROM users WHERE email = ?').get(email);
  if (existing) return res.status(409).json({ error: 'Email already registered' });

  const hash = bcrypt.hashSync(password, 10);
  const initials = name.split(' ').map(p => p[0]).join('').toUpperCase().slice(0, 2);
  const id = uuidv4();

  db.prepare(`INSERT INTO users (id, name, email, password, role, avatar_initials) VALUES (?, ?, ?, ?, ?, ?)`)
    .run(id, name, email, hash, role || 'member', initials);

  res.json({ success: true, id });
});

router.get('/users', (req, res) => {
  const users = db.prepare('SELECT id, name, email, role, avatar_initials, created_at FROM users').all();
  res.json(users);
});

module.exports = router;
