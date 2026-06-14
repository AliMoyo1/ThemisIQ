const express  = require('express');
const router   = express.Router();
const { v4: uuid } = require('uuid');
const db       = require('../database');
const { suggestMappingsWithAI, saveMappings, findMappings } = require('../services/crossMapping');

// Get mappings for an audit
router.get('/:auditId', async (req, res) => {
  const mappings = await findMappings(req.params.auditId);
  res.json(mappings);
});

// AI-suggest mappings between two audits
router.post('/suggest', async (req, res) => {
  const { audit_id_a, audit_id_b } = req.body;
  if (!audit_id_a || !audit_id_b) return res.status(400).json({ error: 'audit_id_a and audit_id_b required' });

  const auditA     = db.get('SELECT a.*, f.name as fw FROM audits a JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?', [audit_id_a]);
  const auditB     = db.get('SELECT a.*, f.name as fw FROM audits a JOIN frameworks f ON a.framework_id=f.id WHERE a.id=?', [audit_id_b]);
  const controlsA  = db.all('SELECT id,control_id,name FROM controls WHERE audit_id=?', [audit_id_a]);
  const controlsB  = db.all('SELECT id,control_id,name FROM controls WHERE audit_id=?', [audit_id_b]);

  if (!auditA || !auditB) return res.status(404).json({ error: 'Audit not found' });

  try {
    const suggestions = await suggestMappingsWithAI(controlsA, controlsB, auditA.fw, auditB.fw);
    // Convert control_id references to our DB ids
    const resolved = suggestions.map(s => {
      const cA = controlsA.find(c => c.control_id === s.control_id_a || c.id === s.control_id_a);
      const cB = controlsB.find(c => c.control_id === s.control_id_b || c.id === s.control_id_b);
      if (!cA || !cB) return null;
      return { control_id_a: cA.id, control_id_b: cB.id, mapping_type: s.mapping_type, notes: s.notes };
    }).filter(Boolean);

    res.json({ success: true, suggestions: resolved, count: resolved.length });
  } catch(e) { res.status(500).json({ error: e.message }); }
});

// Save mappings
router.post('/save', async (req, res) => {
  const { mappings } = req.body;
  if (!Array.isArray(mappings)) return res.status(400).json({ error: 'mappings array required' });
  await saveMappings(mappings);
  res.json({ success: true, saved: mappings.length });
});

// Manual mapping
router.post('/', (req, res) => {
  const { control_id_a, control_id_b, mapping_type, notes } = req.body;
  if (!control_id_a || !control_id_b) return res.status(400).json({ error: 'Both control IDs required' });
  const id = uuid();
  db.run('INSERT OR IGNORE INTO control_mappings (id,control_id_a,control_id_b,mapping_type,notes) VALUES (?,?,?,?,?)',
    [id, control_id_a, control_id_b, mapping_type||'related', notes||'']);
  res.json({ success: true, id });
});

router.delete('/:id', (req, res) => {
  db.run('DELETE FROM control_mappings WHERE id=?', [req.params.id]);
  res.json({ success: true });
});

module.exports = router;
