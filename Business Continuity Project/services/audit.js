// Central audit-log helper. Every sensitive mutation should call this.
// Kept small and synchronous so callers don't have to await.

const db = require('../models/db');

const ACTIONS = {
  CREATE: 'CREATE',
  UPDATE: 'UPDATE',
  DELETE: 'DELETE',
  LOGIN: 'LOGIN',
  LOGOUT: 'LOGOUT',
  INVITE: 'INVITE',
  ROLE_CHANGE: 'ROLE_CHANGE',
  EXPORT: 'EXPORT',
  SETTINGS: 'SETTINGS',
  AI_CALL: 'AI_CALL'
};

function record({ tenantId, userId, userEmail, action, entity, entityId, summary, ip, userAgent }) {
  try {
    db.prepare(`INSERT INTO audit_log
      (tenant_id, user_id, user_email, action, entity, entity_id, summary, ip, user_agent)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`)
      .run(
        tenantId || null,
        userId || null,
        userEmail || null,
        action,
        entity || null,
        entityId || null,
        summary || null,
        ip || null,
        userAgent || null
      );
  } catch (e) {
    // Never crash the request because of an audit failure.
    console.error('[audit] failed:', e.message);
  }
}

// Convenience helper bound to a request — infers user, tenant, ip, ua.
function fromReq(req) {
  return (partial) => record({
    tenantId: req.session?.tenant?.id,
    userId: req.session?.user?.id,
    userEmail: req.session?.user?.email,
    ip: req.ip || (req.headers['x-forwarded-for'] || '').split(',')[0] || req.connection?.remoteAddress,
    userAgent: req.headers['user-agent'],
    ...partial
  });
}

module.exports = { record, fromReq, ACTIONS };
