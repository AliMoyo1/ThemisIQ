// Audit log viewer. Read-only for all roles, filter by entity/action/user.
// Export as CSV is available for admins (SOC 2 evidence).

const express = require('express');
const router = express.Router();
const db = require('../models/db');
const { requireAuth, requireRole } = require('../middleware/auth');
const { ACTIONS } = require('../services/audit');

router.use(requireAuth);

function buildFilter(req) {
  const where = ['tenant_id = ?'];
  const params = [req.session.tenant.id];

  if (req.query.action)   { where.push('action = ?');    params.push(req.query.action); }
  if (req.query.entity)   { where.push('entity = ?');    params.push(req.query.entity); }
  if (req.query.user)     { where.push('user_email = ?');params.push(req.query.user); }
  if (req.query.from)     { where.push("datetime(created_at) >= datetime(?)"); params.push(req.query.from); }
  if (req.query.to)       { where.push("datetime(created_at) <= datetime(?)"); params.push(req.query.to); }

  return { whereSql: where.join(' AND '), params };
}

router.get('/', (req, res) => {
  const { whereSql, params } = buildFilter(req);
  const rows = db.prepare(`SELECT * FROM audit_log WHERE ${whereSql} ORDER BY created_at DESC LIMIT 500`).all(...params);

  const actions = db.prepare(`SELECT DISTINCT action FROM audit_log WHERE tenant_id = ? ORDER BY action ASC`)
    .all(req.session.tenant.id).map(r => r.action);
  const entities = db.prepare(`SELECT DISTINCT entity FROM audit_log WHERE tenant_id = ? AND entity IS NOT NULL ORDER BY entity ASC`)
    .all(req.session.tenant.id).map(r => r.entity);
  const users = db.prepare(`SELECT DISTINCT user_email FROM audit_log WHERE tenant_id = ? AND user_email IS NOT NULL ORDER BY user_email ASC`)
    .all(req.session.tenant.id).map(r => r.user_email);

  res.render('audit/index', {
    title: 'Audit log',
    rows, actions, entities, users,
    filter: {
      action: req.query.action || '',
      entity: req.query.entity || '',
      user:   req.query.user   || '',
      from:   req.query.from   || '',
      to:     req.query.to     || ''
    }
  });
});

router.get('/export.csv', requireRole('admin', 'manager'), (req, res) => {
  const { whereSql, params } = buildFilter(req);
  const rows = db.prepare(`SELECT created_at, user_email, action, entity, entity_id, summary, ip
    FROM audit_log WHERE ${whereSql} ORDER BY created_at DESC`).all(...params);

  const header = ['created_at','user_email','action','entity','entity_id','summary','ip'];
  const esc = (v) => {
    if (v === null || v === undefined) return '';
    const s = String(v).replace(/"/g, '""');
    return /[",\n]/.test(s) ? `"${s}"` : s;
  };
  const body = rows.map(r => header.map(k => esc(r[k])).join(',')).join('\n');
  const csv = header.join(',') + '\n' + body;

  req.audit({ action: ACTIONS.EXPORT, entity: 'audit_log', summary: `Exported ${rows.length} entries` });
  res.setHeader('Content-Type', 'text/csv');
  res.setHeader('Content-Disposition', 'attachment; filename="audit-log.csv"');
  res.send(csv);
});

module.exports = router;
