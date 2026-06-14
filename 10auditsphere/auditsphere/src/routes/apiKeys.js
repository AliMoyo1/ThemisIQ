const express  = require('express');
const router   = express.Router();
const { v4: uuid } = require('uuid');
const crypto   = require('crypto');
const db       = require('../database');

router.get('/', (req, res) => {
  const keys = db.all('SELECT id,name,key_prefix,permissions,active,created_at,last_used FROM api_keys WHERE active=1 ORDER BY created_at DESC');
  res.json(keys);
});

router.post('/', (req, res) => {
  const { name, permissions } = req.body;
  if (!name) return res.status(400).json({ error: 'name required' });
  const rawKey   = 'gai_' + crypto.randomBytes(32).toString('hex');
  const keyHash  = crypto.createHash('sha256').update(rawKey).digest('hex');
  const keyPrefix= rawKey.slice(0, 12) + '...';
  const id       = uuid();
  db.run('INSERT INTO api_keys (id,name,key_hash,key_prefix,created_by,permissions) VALUES (?,?,?,?,?,?)',
    [id, name, keyHash, keyPrefix, req.session?.user?.name||'Admin', permissions||'read']);
  res.json({ success: true, id, key: rawKey, keyPrefix, note: 'Save this key — it will not be shown again' });
});

router.delete('/:id', (req, res) => {
  db.run('UPDATE api_keys SET active=0 WHERE id=?', [req.params.id]);
  res.json({ success: true });
});

// Middleware to validate API key for external API access
function validateApiKey(req, res, next) {
  const authHeader = req.headers['x-api-key'] || req.headers['authorization']?.replace('Bearer ', '');
  if (!authHeader) return next(); // no key — falls through to session auth
  const keyHash = crypto.createHash('sha256').update(authHeader).digest('hex');
  const key     = db.get("SELECT * FROM api_keys WHERE key_hash=? AND active=1", [keyHash]);
  if (!key) return res.status(401).json({ error: 'Invalid API key' });
  db.run('UPDATE api_keys SET last_used=? WHERE id=?', [new Date().toISOString(), key.id]);
  req.apiKey    = key;
  req.apiAccess = true;
  next();
}

module.exports = router;
module.exports.validateApiKey = validateApiKey;
