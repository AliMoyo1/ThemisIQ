// Dependency graph module.
// Manages nodes (processes, systems, vendors, sites, teams, assets, data) and
// directed edges between them. Renders an interactive graph (vis-network via CDN)
// and exposes a JSON feed + an "impact path" endpoint that walks outgoing edges
// from a given node to show what would be affected if it went down.

const express = require('express');
const router = express.Router();
const db = require('../models/db');
const { requireAuth, requireRole } = require('../middleware/auth');
const { ACTIONS } = require('../services/audit');

router.use(requireAuth);

const NODE_TYPES = ['process', 'system', 'vendor', 'site', 'team', 'asset', 'data'];
const EDGE_LABELS = ['depends_on', 'feeds', 'hosts', 'supports', 'fails_over_to'];

// ---- INDEX (graph canvas) ----
router.get('/', (req, res) => {
  const tid = req.session.tenant.id;
  const nodes = db.prepare('SELECT * FROM dependency_nodes WHERE tenant_id = ? ORDER BY name').all(tid);
  const edges = db.prepare('SELECT * FROM dependency_edges WHERE tenant_id = ? ORDER BY id').all(tid);

  const stats = {
    nodes: nodes.length,
    edges: edges.length,
    critical: nodes.filter(n => n.criticality === 'Critical').length,
    orphans: nodes.filter(n =>
      !edges.some(e => e.source_id === n.id || e.target_id === n.id)
    ).length,
    types: NODE_TYPES.map(t => ({ t, c: nodes.filter(n => n.node_type === t).length }))
  };

  res.render('dependencies/index', {
    title: 'Dependency graph',
    nodes, edges, stats,
    nodeTypes: NODE_TYPES, edgeLabels: EDGE_LABELS
  });
});

// ---- JSON feed for the visualization layer ----
router.get('/graph.json', (req, res) => {
  const tid = req.session.tenant.id;
  const nodes = db.prepare('SELECT * FROM dependency_nodes WHERE tenant_id = ?').all(tid);
  const edges = db.prepare('SELECT * FROM dependency_edges WHERE tenant_id = ?').all(tid);
  res.json({ nodes, edges });
});

// ---- Node CRUD ----
router.get('/nodes/new', requireRole('admin', 'manager'), (req, res) => {
  res.render('dependencies/node_form', { title: 'New node', node: null, nodeTypes: NODE_TYPES });
});

router.get('/nodes/:id/edit', requireRole('admin', 'manager'), (req, res) => {
  const node = db.prepare('SELECT * FROM dependency_nodes WHERE id = ? AND tenant_id = ?')
    .get(req.params.id, req.session.tenant.id);
  if (!node) { req.flash('error', 'Node not found.'); return res.redirect('/dependencies'); }
  res.render('dependencies/node_form', { title: 'Edit node', node, nodeTypes: NODE_TYPES });
});

router.post('/nodes', requireRole('admin', 'manager'), (req, res) => {
  const b = req.body;
  const info = db.prepare(`INSERT INTO dependency_nodes
    (tenant_id, node_type, name, description, criticality, ref_table, ref_id)
    VALUES (?, ?, ?, ?, ?, ?, ?)`)
    .run(req.session.tenant.id,
      b.node_type || 'process', b.name,
      b.description || null, b.criticality || 'Medium',
      b.ref_table || null, b.ref_id ? +b.ref_id : null);
  req.audit({ action: ACTIONS.CREATE, entity: 'dependency_nodes', entityId: info.lastInsertRowid, summary: `Node "${b.name}" added` });
  req.flash('success', 'Node added.');
  res.redirect('/dependencies');
});

router.post('/nodes/:id', requireRole('admin', 'manager'), (req, res) => {
  const b = req.body;
  db.prepare(`UPDATE dependency_nodes SET
    node_type=?, name=?, description=?, criticality=?, ref_table=?, ref_id=?, updated_at=CURRENT_TIMESTAMP
    WHERE id = ? AND tenant_id = ?`)
    .run(b.node_type, b.name, b.description || null, b.criticality || 'Medium',
      b.ref_table || null, b.ref_id ? +b.ref_id : null,
      req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.UPDATE, entity: 'dependency_nodes', entityId: +req.params.id, summary: `Node "${b.name}" updated` });
  req.flash('success', 'Node updated.');
  res.redirect('/dependencies');
});

router.post('/nodes/:id/delete', requireRole('admin', 'manager'), (req, res) => {
  const n = db.prepare('SELECT name FROM dependency_nodes WHERE id = ? AND tenant_id = ?')
    .get(req.params.id, req.session.tenant.id);
  db.prepare('DELETE FROM dependency_nodes WHERE id = ? AND tenant_id = ?')
    .run(req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'dependency_nodes', entityId: +req.params.id, summary: `Node "${n?.name || ''}" removed` });
  req.flash('success', 'Node removed.');
  res.redirect('/dependencies');
});

// ---- Edge CRUD ----
router.post('/edges', requireRole('admin', 'manager'), (req, res) => {
  const b = req.body;
  if (!b.source_id || !b.target_id || +b.source_id === +b.target_id) {
    req.flash('error', 'Pick two distinct nodes.');
    return res.redirect('/dependencies');
  }
  const info = db.prepare(`INSERT INTO dependency_edges
    (tenant_id, source_id, target_id, label, strength, notes)
    VALUES (?, ?, ?, ?, ?, ?)`)
    .run(req.session.tenant.id, +b.source_id, +b.target_id,
      b.label || 'depends_on', Math.min(5, Math.max(1, +b.strength || 3)),
      b.notes || null);
  req.audit({ action: ACTIONS.CREATE, entity: 'dependency_edges', entityId: info.lastInsertRowid, summary: `Edge ${b.source_id}→${b.target_id} (${b.label || 'depends_on'})` });
  req.flash('success', 'Relationship added.');
  res.redirect('/dependencies');
});

router.post('/edges/:id/delete', requireRole('admin', 'manager'), (req, res) => {
  db.prepare('DELETE FROM dependency_edges WHERE id = ? AND tenant_id = ?')
    .run(req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'dependency_edges', entityId: +req.params.id, summary: 'Edge removed' });
  req.flash('success', 'Relationship removed.');
  res.redirect('/dependencies');
});

// ---- Impact path: BFS from a root following outgoing edges ----
router.get('/impact/:id', (req, res) => {
  const tid = req.session.tenant.id;
  const root = db.prepare('SELECT * FROM dependency_nodes WHERE id = ? AND tenant_id = ?')
    .get(req.params.id, tid);
  if (!root) { req.flash('error', 'Node not found.'); return res.redirect('/dependencies'); }

  const allNodes = db.prepare('SELECT * FROM dependency_nodes WHERE tenant_id = ?').all(tid);
  const nodeById = Object.fromEntries(allNodes.map(n => [n.id, n]));
  const outgoing = {};
  const incoming = {};
  const edges = db.prepare('SELECT * FROM dependency_edges WHERE tenant_id = ?').all(tid);
  for (const e of edges) {
    (outgoing[e.source_id] ||= []).push(e);
    (incoming[e.target_id] ||= []).push(e);
  }

  function bfs(fromId, adj) {
    const visited = new Set([fromId]);
    const levels = [[{ id: fromId, edge: null, depth: 0 }]];
    let frontier = [fromId];
    while (frontier.length) {
      const next = [];
      const levelRows = [];
      for (const id of frontier) {
        for (const e of (adj[id] || [])) {
          const otherId = adj === outgoing ? e.target_id : e.source_id;
          if (visited.has(otherId)) continue;
          visited.add(otherId);
          next.push(otherId);
          levelRows.push({ id: otherId, edge: e, depth: levels.length });
        }
      }
      if (levelRows.length) levels.push(levelRows);
      frontier = next;
    }
    return levels.map(lvl => lvl.map(x => ({
      node: nodeById[x.id],
      edge: x.edge,
      depth: x.depth
    }))).filter(lvl => lvl.length);
  }

  const downstream = bfs(root.id, outgoing);   // what the root affects if it fails
  const upstream = bfs(root.id, incoming);     // what the root depends on

  res.render('dependencies/impact', {
    title: 'Impact: ' + root.name,
    root, downstream, upstream
  });
});

module.exports = router;
