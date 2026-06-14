const Anthropic = require('@anthropic-ai/sdk');

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

// Analyze evidence text and suggest which controls it satisfies
async function analyzeEvidence(evidenceText, controls) {
  const controlList = controls.map(c => `- ${c.control_id}: ${c.name}`).join('\n');
  const response = await client.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 1024,
    messages: [{
      role: 'user',
      content: `You are a compliance audit expert. Given this uploaded evidence text, identify which controls from the list it likely satisfies. Return JSON only.

Evidence text (first 2000 chars):
${evidenceText.substring(0, 2000)}

Controls to check:
${controlList}

Return JSON: {"matches": [{"control_id": "A.5.1", "confidence": "high|medium|low", "reason": "brief reason"}], "summary": "brief summary of what this evidence covers"}`
    }]
  });
  try {
    const text = response.content[0].text.replace(/```json|```/g, '').trim();
    return JSON.parse(text);
  } catch { return { matches: [], summary: 'Could not parse AI response' }; }
}

// Generate gap analysis for an audit
async function generateGapAnalysis(audit, controls, evidenceStats) {
  const controlSummary = controls.map(c =>
    `${c.control_id} | ${c.name} | Risk: ${c.risk_level} | Status: ${c.status} | Evidence: ${c.evidence_count || 0}/${c.evidence_required || 0}`
  ).join('\n');

  const response = await client.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 2048,
    messages: [{
      role: 'user',
      content: `You are a senior compliance auditor. Analyze this audit status and provide a professional gap analysis. Return JSON only.

Audit: ${audit.name}
Framework: ${audit.framework_name}
Audit Date: ${audit.audit_date}
Days Remaining: ${audit.days_remaining}

Control Status:
${controlSummary}

Return JSON:
{
  "overall_readiness": "percentage 0-100",
  "risk_rating": "High|Medium|Low",
  "critical_gaps": ["list of critical gaps"],
  "recommendations": ["prioritized action items"],
  "timeline_feasibility": "assessment of whether audit date is achievable",
  "executive_summary": "2-3 sentence executive summary"
}`
    }]
  });
  try {
    const text = response.content[0].text.replace(/```json|```/g, '').trim();
    return JSON.parse(text);
  } catch { return { executive_summary: 'Gap analysis unavailable', critical_gaps: [], recommendations: [] }; }
}

// Auto-generate evidence requirements from control description
async function generateEvidenceRequirements(control, frameworkName) {
  const response = await client.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 512,
    messages: [{
      role: 'user',
      content: `You are a ${frameworkName} compliance expert. For this control, list the typical evidence items an auditor would require. Return JSON only.

Control ID: ${control.control_id}
Control Name: ${control.name}
Description: ${control.description || control.name}

Return JSON: {"requirements": ["evidence item 1", "evidence item 2", ...], "notes": "any important notes"}`
    }]
  });
  try {
    const text = response.content[0].text.replace(/```json|```/g, '').trim();
    return JSON.parse(text);
  } catch { return { requirements: [], notes: '' }; }
}

// Parse uploaded Excel/PDF checklist and map to controls
async function parseChecklistWithAI(checklistText, frameworkName) {
  const response = await client.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 4096,
    messages: [{
      role: 'user',
      content: `You are a compliance expert. Parse this auditor checklist and extract controls. Return JSON only.

Framework: ${frameworkName}
Checklist content:
${checklistText.substring(0, 6000)}

Return JSON:
{
  "controls": [
    {
      "control_id": "extracted or generated ID",
      "name": "control name",
      "description": "description if available",
      "risk_level": "Critical|High|Medium|Low",
      "evidence_requirements": ["item1", "item2"]
    }
  ],
  "total_found": number,
  "notes": "any parsing notes"
}`
    }]
  });
  try {
    const text = response.content[0].text.replace(/```json|```/g, '').trim();
    return JSON.parse(text);
  } catch { return { controls: [], total_found: 0, notes: 'Parse failed' }; }
}

// Generate audit report narrative
async function generateReportNarrative(audit, controls, evidenceSummary) {
  const completed = controls.filter(c => c.status === 'Complete').length;
  const response = await client.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 1500,
    messages: [{
      role: 'user',
      content: `Generate a professional audit report narrative for this compliance audit. Return JSON only.

Audit: ${audit.name}
Framework: ${audit.framework_name}
Period: ${audit.start_date} to ${audit.audit_date}
Total Controls: ${controls.length}
Completed: ${completed}
Completion Rate: ${Math.round((completed/controls.length)*100)}%

Return JSON:
{
  "executive_summary": "professional executive summary paragraph",
  "scope_statement": "audit scope statement",
  "methodology": "methodology paragraph",
  "findings_overview": "findings overview paragraph",
  "conclusion": "conclusion paragraph"
}`
    }]
  });
  try {
    const text = response.content[0].text.replace(/```json|```/g, '').trim();
    return JSON.parse(text);
  } catch {
    return {
      executive_summary: `This audit report covers the ${audit.framework_name} compliance assessment.`,
      scope_statement: 'The audit scope covers all applicable controls.',
      methodology: 'Evidence-based audit methodology was applied.',
      findings_overview: `${completed} of ${controls.length} controls have been satisfied.`,
      conclusion: 'The audit is progressing as planned.'
    };
  }
}

// Chat with AI about the audit
async function auditChat(message, auditContext) {
  const response = await client.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 1024,
    system: `You are an expert compliance and audit advisor helping with ${auditContext.framework} compliance. 
You have access to their audit data: ${JSON.stringify(auditContext)}.
Be concise, practical, and specific. Focus on actionable advice.`,
    messages: [{ role: 'user', content: message }]
  });
  return response.content[0].text;
}

module.exports = { analyzeEvidence, generateGapAnalysis, generateEvidenceRequirements, parseChecklistWithAI, generateReportNarrative, auditChat };
