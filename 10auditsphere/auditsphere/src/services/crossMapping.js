/**
 * crossMapping.js — Finds overlapping controls across frameworks
 */
const db    = require('../database');
const aiSvc = require('./ai');
const { v4: uuid } = require('uuid');

async function findMappings(auditId) {
  const controls = db.all('SELECT * FROM controls WHERE audit_id = ?', [auditId]);
  if (controls.length === 0) return [];

  // Check existing mappings
  const existing = db.all(`
    SELECT cm.*, c1.name as control_a_name, c2.name as control_b_name,
           c1.control_id as control_a_id, c2.control_id as control_b_id
    FROM control_mappings cm
    JOIN controls c1 ON cm.control_id_a = c1.id
    JOIN controls c2 ON cm.control_id_b = c2.id
    WHERE c1.audit_id = ? OR c2.audit_id = ?
  `, [auditId, auditId]);

  return existing;
}

async function suggestMappingsWithAI(controlsA, controlsB, frameworkA, frameworkB) {
  const text = await aiSvc.callClaudeRaw([{
    role: 'user',
    content: `Find overlapping controls between ${frameworkA} and ${frameworkB}.

${frameworkA} controls (sample):
${controlsA.slice(0, 20).map(c => `- ${c.control_id}: ${c.name}`).join('\n')}

${frameworkB} controls (sample):
${controlsB.slice(0, 20).map(c => `- ${c.control_id}: ${c.name}`).join('\n')}

Return ONLY a JSON array of mappings:
[{"control_id_a":"id","control_id_b":"id","mapping_type":"equivalent|partial|related","notes":"Why they overlap"}]`
  }], null, 2000);

  try {
    const match = text.match(/\[[\s\S]*\]/);
    return match ? JSON.parse(match[0]) : [];
  } catch { return []; }
}

async function saveMappings(mappings) {
  for (const m of mappings) {
    const existing = db.get('SELECT id FROM control_mappings WHERE control_id_a=? AND control_id_b=?',
      [m.control_id_a, m.control_id_b]);
    if (!existing) {
      db.run('INSERT INTO control_mappings (id,control_id_a,control_id_b,mapping_type,notes) VALUES (?,?,?,?,?)',
        [uuid(), m.control_id_a, m.control_id_b, m.mapping_type || 'related', m.notes || '']);
    }
  }
}

module.exports = { findMappings, suggestMappingsWithAI, saveMappings };
