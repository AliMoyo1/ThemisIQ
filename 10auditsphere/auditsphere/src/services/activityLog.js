/**
 * activityLog.js — Immutable audit trail for every action
 */
const db = require('../database');
const { v4: uuid } = require('uuid');

function log({ action, entityType, entityId, entityName, userId, userName, details, req }) {
  try {
    const ip = req ? (req.headers['x-forwarded-for'] || req.socket?.remoteAddress || '') : '';
    db.run(
      `INSERT INTO activity_log (id,action,entity_type,entity_id,entity_name,user_id,user_name,details,ip_address)
       VALUES (?,?,?,?,?,?,?,?,?)`,
      [uuid(), action, entityType || '', entityId || '', entityName || '',
       userId || '', userName || '', typeof details === 'object' ? JSON.stringify(details) : (details || ''), ip]
    );
  } catch (e) {
    console.error('Activity log error:', e.message);
  }
}

function getLog({ entityId, entityType, userId, limit = 100, offset = 0 }) {
  let q = 'SELECT * FROM activity_log WHERE 1=1';
  const p = [];
  if (entityId)   { q += ' AND entity_id = ?';   p.push(entityId); }
  if (entityType) { q += ' AND entity_type = ?';  p.push(entityType); }
  if (userId)     { q += ' AND user_id = ?';       p.push(userId); }
  q += ' ORDER BY created_at DESC LIMIT ? OFFSET ?';
  p.push(limit, offset);
  return db.all(q, p);
}

module.exports = { log, getLog };
