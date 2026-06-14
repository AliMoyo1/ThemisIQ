const express = require('express');
const router = express.Router();
const db = require('../models/db');
const { requireAuth } = require('../middleware/auth');
const { chat } = require('../services/ai');

router.use(requireAuth);

function loadHistory(tenantId, userId, limit = 20) {
  return db.prepare(`
    SELECT role, content FROM chat_messages
    WHERE tenant_id = ? AND user_id = ?
    ORDER BY id DESC LIMIT ?
  `).all(tenantId, userId, limit).reverse();
}

router.get('/', (req, res) => {
  const messages = loadHistory(req.session.tenant.id, req.session.user.id, 40);
  res.render('chatbot/index', { title: 'BCM Chatbot', messages });
});

router.post('/', async (req, res) => {
  const { message } = req.body;
  if (!message || !message.trim()) return res.redirect('/chatbot');

  const tid = req.session.tenant.id;
  const uid = req.session.user.id;

  db.prepare(`INSERT INTO chat_messages (tenant_id, user_id, role, content) VALUES (?, ?, 'user', ?)`)
    .run(tid, uid, message.trim());

  const history = loadHistory(tid, uid, 12);

  try {
    const { reply, provider } = await chat({ tenantId: tid, messages: history });
    db.prepare(`INSERT INTO chat_messages (tenant_id, user_id, role, content, provider) VALUES (?, ?, 'assistant', ?, ?)`)
      .run(tid, uid, reply, provider);
  } catch (err) {
    console.error(err);
    db.prepare(`INSERT INTO chat_messages (tenant_id, user_id, role, content, provider) VALUES (?, ?, 'assistant', ?, 'error')`)
      .run(tid, uid, 'Sorry — I ran into an error. Please try again or check your AI keys in Settings.');
  }

  res.redirect('/chatbot');
});

router.post('/clear', (req, res) => {
  db.prepare(`DELETE FROM chat_messages WHERE tenant_id = ? AND user_id = ?`)
    .run(req.session.tenant.id, req.session.user.id);
  req.flash('success', 'Chat history cleared.');
  res.redirect('/chatbot');
});

module.exports = router;
