// AI Plan Reviewer — critiques a BCP against ISO 22301 + NIST CSF.
//
// Usage:
//   const { reviewPlan, REQUIRED_SECTIONS } = require('./plan-reviewer');
//   const review = await reviewPlan({ tenantId, plan });
//   // review = { overall_score, summary, strengths, gaps, recommendations,
//   //            section_coverage, raw_response, provider }

const { chat } = require('./ai');

// Canonical sections every ISO 22301 / NIST-CSF-aligned continuity plan should cover.
// Keyed with headings + synonyms so a simple regex scan can flag "you're missing X".
const REQUIRED_SECTIONS = [
  { key: 'purpose',       label: 'Purpose',                 aliases: ['purpose', 'objective', 'introduction'] },
  { key: 'scope',         label: 'Scope',                   aliases: ['scope', 'applicability', 'boundaries'] },
  { key: 'activation',    label: 'Activation Criteria',     aliases: ['activation', 'invocation', 'trigger'] },
  { key: 'roles',         label: 'Roles & Responsibilities',aliases: ['roles', 'responsibilities', 'crisis team', 'responsibility', 'raci'] },
  { key: 'immediate',     label: 'Immediate Response',      aliases: ['immediate response', 'first 60', 'initial response', 'incident response'] },
  { key: 'short_term',    label: 'Short-term Recovery',     aliases: ['short-term', 'short term', 'first 24', 'recovery procedures', 'recovery steps'] },
  { key: 'long_term',     label: 'Longer-term Recovery',    aliases: ['long-term', 'long term', 'full restoration', 'return to normal'] },
  { key: 'comms',         label: 'Communications',          aliases: ['communication', 'comms', 'stakeholder communication', 'notification'] },
  { key: 'dependencies',  label: 'Dependencies & Suppliers',aliases: ['dependencies', 'supplier', 'vendor', 'third party', 'alternate site'] },
  { key: 'rto_rpo',       label: 'RTO / RPO targets',       aliases: ['rto', 'rpo', 'recovery time objective', 'recovery point objective'] },
  { key: 'testing',       label: 'Testing & Exercising',    aliases: ['exercise', 'tabletop', 'test', 'drill', 'training'] },
  { key: 'review',        label: 'Review & Approval',       aliases: ['review', 'approval', 'version history', 'sign-off', 'maintenance'] }
];

/**
 * Quick heuristic coverage scan — runs before the AI call so the user sees a
 * skeleton even if the provider is offline. Returns an array of
 * {key, label, present} records.
 */
function detectCoverage(content) {
  const hay = (content || '').toLowerCase();
  return REQUIRED_SECTIONS.map(sec => {
    const present = sec.aliases.some(a => hay.includes(a.toLowerCase()));
    return { key: sec.key, label: sec.label, present };
  });
}

/**
 * Best-effort JSON block extraction. The model is asked to produce fenced JSON
 * but we fall back to bracket matching if it strays.
 */
function extractJson(text) {
  if (!text) return null;
  const fenced = text.match(/```json\s*([\s\S]*?)\s*```/i) || text.match(/```\s*([\s\S]*?)\s*```/);
  const candidate = fenced ? fenced[1] : text;
  // Find the first { and the matching closing }
  const start = candidate.indexOf('{');
  const end = candidate.lastIndexOf('}');
  if (start === -1 || end === -1 || end <= start) return null;
  const slice = candidate.slice(start, end + 1);
  try { return JSON.parse(slice); }
  catch (_) { return null; }
}

function clampScore(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return null;
  return Math.max(0, Math.min(100, Math.round(v)));
}

async function reviewPlan({ tenantId, plan, standards = ['ISO 22301', 'NIST CSF'] }) {
  const coverage = detectCoverage(plan.content);
  const missing = coverage.filter(c => !c.present).map(c => c.label).join(', ') || 'none (heuristically — AI may still find gaps)';

  const standardsList = standards.join(' + ');

  const prompt = `You are a senior Business Continuity auditor. Review the following continuity plan against ${standardsList} and common industry practice.

Return ONLY valid JSON inside a \`\`\`json fenced code block with this exact shape:
{
  "overall_score": <integer 0-100>,
  "summary": "<2-3 sentence executive verdict>",
  "strengths": ["bullet", "bullet", ...],
  "gaps": ["bullet", "bullet", ...],
  "recommendations": ["bullet", "bullet", ...],
  "standards_alignment": {
    "ISO 22301": "<1-2 sentences on alignment>",
    "NIST CSF":  "<1-2 sentences on alignment>"
  }
}

Scoring rubric:
- 90-100: publication-ready, audit-defensible
- 75-89:  solid with minor gaps
- 60-74:  usable draft, noticeable gaps
- <60:    needs rework before approval

Heuristic pre-scan flagged these sections as potentially missing: ${missing}

# Plan metadata
Title: ${plan.title}
Version: ${plan.version || '1.0'}
Scope: ${plan.scope || 'not specified'}
Owner: ${plan.owner || 'unassigned'}
Status: ${plan.status}

# Plan content (Markdown)
${plan.content || '(no content provided)'}

Be terse and specific. Quote the plan where useful. Don't invent facts that aren't in the text.`;

  const { reply, provider } = await chat({
    tenantId,
    messages: [{ role: 'user', content: prompt }]
  });

  const parsed = extractJson(reply) || {};
  const review = {
    overall_score:   clampScore(parsed.overall_score),
    summary:         parsed.summary || 'The reviewer did not return a structured summary. See raw response.',
    strengths:       Array.isArray(parsed.strengths)       ? parsed.strengths       : [],
    gaps:            Array.isArray(parsed.gaps)            ? parsed.gaps            : [],
    recommendations: Array.isArray(parsed.recommendations) ? parsed.recommendations : [],
    standards_alignment: parsed.standards_alignment || {},
    section_coverage: coverage,
    raw_response: reply,
    provider
  };

  // If the model didn't return a score, approximate from coverage so the card
  // still shows something sensible.
  if (review.overall_score === null) {
    const pct = Math.round(100 * coverage.filter(c => c.present).length / coverage.length);
    review.overall_score = pct;
  }
  return review;
}

module.exports = { reviewPlan, detectCoverage, REQUIRED_SECTIONS };
