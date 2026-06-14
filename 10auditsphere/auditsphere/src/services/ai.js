const Anthropic = require('@anthropic-ai/sdk');

function getClient() {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey || apiKey.trim() === '' || apiKey.startsWith('your-')) {
    throw new Error(
      'API key not set — open your .env file and set ANTHROPIC_API_KEY=sk-ant-...'
    );
  }
  if (!apiKey.startsWith('sk-ant-')) {
    throw new Error(
      'API key looks wrong — it should start with "sk-ant-". Check your .env file.'
    );
  }
  return new Anthropic({ apiKey: apiKey.trim() });
}

function friendlyError(err) {
  const msg = err?.message || String(err);
  if (err?.status === 401 || msg.includes('authentication_error') || msg.includes('invalid x-api-key') || msg.includes('invalid key')) {
    return 'Invalid Anthropic API key. Go to console.anthropic.com → API Keys, copy your key, and paste it into your .env file as ANTHROPIC_API_KEY=sk-ant-...';
  }
  if (err?.status === 403) return 'Anthropic API access denied. Check that your account has credits.';
  if (err?.status === 429) return 'Anthropic rate limit reached. Wait a moment and try again.';
  if (err?.status === 529 || msg.includes('overloaded')) return 'Anthropic API is temporarily overloaded. Please try again.';
  if (msg.includes('ENOTFOUND') || msg.includes('fetch failed')) return 'Cannot reach Anthropic API — check your internet connection.';
  return msg.replace(/\{"type":"error".*\}/, '').trim() || 'AI request failed';
}

async function callClaude(messages, system, maxTokens = 2000) {
  const ai   = getClient();
  const opts = { model: 'claude-sonnet-4-20250514', max_tokens: maxTokens, messages };
  if (system) opts.system = system;
  try {
    const r    = await ai.messages.create(opts);
    const text = r.content[0].text.trim();
    return text.replace(/```json|```/g, '').trim();
  } catch (err) {
    throw new Error(friendlyError(err));
  }
}

function safeParseJSON(text, fallback = null) {
  try { return JSON.parse(text); } catch (_) {}
  const arrMatch = text.match(/\[[\s\S]*\]/);
  if (arrMatch) { try { return JSON.parse(arrMatch[0]); } catch (_) {} }
  const objMatch = text.match(/\{[\s\S]*\}/);
  if (objMatch) { try { return JSON.parse(objMatch[0]); } catch (_) {} }
  return fallback;
}

/* ─── Batch risk scoring for checklist import ─── */
async function batchRiskScore(items, frameworkName) {
  const text = await callClaude([{
    role: 'user',
    content: `You are a ${frameworkName} compliance expert. For each evidence/control item, assign risk level and evidence count.

Items: ${JSON.stringify(items)}

Rules:
- risk_level: "Critical" (security boundary, encryption, access control), "High" (audit logs, vulnerability mgmt), "Medium" (policies, procedures, documentation), "Low" (awareness training, minor admin)
- evidence_required: 1-4 integer
- evidence_items: 1-3 short strings naming what to collect

Return ONLY a compact JSON object keyed by the seq field value (integers as strings):
{"1":{"risk_level":"High","evidence_required":2,"evidence_items":["Policy doc","Approval record"]}}`
  }], null, 4000);

  const parsed = safeParseJSON(text, {});
  const result = {};
  for (const [k, v] of Object.entries(parsed)) {
    result[Number(k)] = v;
  }
  return result;
}

/* ─── Public functions ─── */
async function parseChecklistWithAI(rawText, frameworkName) {
  // Legacy fallback - now only used for plain text/unknown formats
  const text = await callClaude([{
    role: 'user',
    content: `Parse this compliance checklist for ${frameworkName}. Extract all control/evidence items.
${rawText.slice(0, 6000)}
Return ONLY a JSON array: [{"control_id":"1","name":"Name","description":"Desc","risk_level":"High","evidence_required":1,"evidence_items":["Item"]}]`
  }], null, 4000);
  const parsed = safeParseJSON(text, []);
  if (!Array.isArray(parsed)) throw new Error('AI returned invalid format');
  return parsed;
}

async function generateGapAnalysis(controls, frameworkName) {
  const summary = controls.map(c => ({
    id: c.control_id, name: c.name, status: c.status,
    risk: c.risk_level, evidence: c.evidence_count || 0, required: c.evidence_required || 1
  }));
  const text = await callClaude([{
    role: 'user',
    content: `${frameworkName} gap analysis for these controls: ${JSON.stringify(summary)}
Return ONLY JSON: {"readiness_score":75,"risk_summary":"2-sentence summary","critical_gaps":["gap1"],"quick_wins":["win1"],"recommendations":[{"priority":"High","action":"action","impact":"impact"}],"estimated_completion":"X weeks"}`
  }]);
  return safeParseJSON(text, { readiness_score: 0, risk_summary: 'Analysis unavailable', critical_gaps: [], quick_wins: [], recommendations: [] });
}

async function suggestControlDetails(controlId, name, frameworkName) {
  const text = await callClaude([{
    role: 'user',
    content: `${frameworkName} control: ID="${controlId}" Name="${name}"
Return ONLY JSON: {"description":"2-3 sentences","risk_level":"Critical|High|Medium|Low","evidence_items":["Item 1","Item 2","Item 3"],"tips":"One practical tip"}`
  }]);
  return safeParseJSON(text, { description: '', risk_level: 'Medium', evidence_items: [], tips: '' });
}

async function generateReportNarrative(auditData) {
  const text = await callClaude([{
    role: 'user',
    content: `Professional audit report executive summary:
Audit: ${auditData.auditName}, Framework: ${auditData.framework}
Completion: ${auditData.completionPct}%, Total: ${auditData.totalControls}, Complete: ${auditData.complete}, Pending: ${auditData.pending}, Overdue: ${auditData.overdue}
Audit date: ${auditData.auditDate}, Critical gaps: ${(auditData.criticalGaps || []).join(', ') || 'None'}
Return ONLY JSON: {"executive_summary":"3-4 sentences","overall_status":"On Track|At Risk|Critical","key_findings":["f1","f2","f3"],"conclusion":"1-2 sentences"}`
  }], null, 1500);
  return safeParseJSON(text, { executive_summary: '', overall_status: 'In Progress', key_findings: [], conclusion: '' });
}

async function askComplianceAI(question, context) {
  return await callClaude(
    [{ role: 'user', content: question }],
    `You are G.R.I.D AI's compliance assistant. Help with ISO 27001, SOC 2, GDPR, PCI DSS, HIPAA, Zimbabwe CDPA, ISO 42001. Be concise and practical. Context: ${JSON.stringify(context || {})}`,
    800
  );
}


async function callClaudeRaw(messages, system, maxTokens = 2000) {
  return await callClaude(messages, system, maxTokens);
}

module.exports = { callClaudeRaw, parseChecklistWithAI, generateGapAnalysis, suggestControlDetails, generateReportNarrative, askComplianceAI, batchRiskScore };
