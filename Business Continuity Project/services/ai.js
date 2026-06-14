// Provider-agnostic AI service. Supports OpenAI or Anthropic, selected per tenant.
// Falls back to a helpful stub if no API key is configured so the product still
// works during development.

const axios = require('axios');
const db = require('../models/db');

const SYSTEM_BASE = `You are "Continuity Copilot", an expert assistant for Business Continuity Management.
You help users with BCM best practices, ISO 22301 compliance, NIST SP 800-34, disaster
recovery planning, business impact analysis, risk assessment, and incident response.

Rules:
- Be concise and practical. Prefer numbered steps or short bulleted lists.
- Cite relevant standards (ISO 22301, NIST, SOC 2) by name when applicable.
- If asked for plan content, produce professional, usable Markdown.
- Never invent regulations or fabricate citations.
- When asked about a scenario ("what do I do if..."), give an immediate-actions section first, then follow-up actions.`;

/**
 * Resolve which provider + credentials to use for this tenant.
 * Tenant-scoped keys override env defaults.
 */
function resolveProvider(tenantId) {
  const tenant = db.prepare('SELECT * FROM tenants WHERE id = ?').get(tenantId);
  const provider = (tenant && tenant.ai_provider) || process.env.AI_DEFAULT_PROVIDER || 'openai';

  if (provider === 'anthropic') {
    const key = (tenant && tenant.ai_anthropic_key) || process.env.ANTHROPIC_API_KEY;
    const model = process.env.ANTHROPIC_MODEL || 'claude-3-5-sonnet-20241022';
    return { provider, key, model };
  }
  const key = (tenant && tenant.ai_openai_key) || process.env.OPENAI_API_KEY;
  const model = process.env.OPENAI_MODEL || 'gpt-4o-mini';
  return { provider: 'openai', key, model };
}

function stubAnswer(prompt) {
  // Deterministic stub so the UI works end-to-end without an API key.
  const p = (prompt || '').toLowerCase();
  if (p.includes('iso 22301')) {
    return `**ISO 22301 in brief**

- An international standard for Business Continuity Management Systems (BCMS).
- Built around the Plan-Do-Check-Act cycle.
- Core requirements: context of the organization, leadership, planning, support, operation (BIA, risk assessment, strategy, procedures, exercising), performance evaluation, and improvement.
- Pair it with ISO 22313 for guidance and ISO 22317 for BIA-specific guidance.

_This is a stub response because no AI API key is configured yet. Add one in Settings → AI._`;
  }
  if (p.includes('ransomware') || p.includes('cyber')) {
    return `**Immediate actions for a suspected ransomware event**

1. Isolate affected hosts from the network (pull LAN / disable Wi-Fi).
2. Preserve evidence — do not power off; snapshot memory if possible.
3. Activate your Cyber Incident Response Plan and notify the CISO / incident commander.
4. Engage legal, communications, and your cyber insurance carrier.
5. Do not pay the ransom without legal and law-enforcement counsel.

**Next 24 hours**

- Forensic triage, scope determination, IOC collection.
- Regulator notification assessment (GDPR 72h window if applicable).
- Activate alternate processing or manual workaround procedures.

_Stub response — configure an AI key in Settings for live answers._`;
  }
  return `I'd be glad to help with your BCM question. To give you live, tailored answers, please add an OpenAI or Anthropic API key in Settings → AI. In the meantime, here is a general outline I'd cover:

1. Understand the scenario and its impact on critical processes.
2. Reference the relevant plan (BCP, DRP, crisis comms).
3. Trigger the activation criteria and stand up the response team.
4. Communicate internally and externally per the comms matrix.
5. Track all decisions and actions for the post-incident review.

_(stub response)_`;
}

async function callOpenAI({ key, model, messages }) {
  const url = 'https://api.openai.com/v1/chat/completions';
  const body = { model, messages, temperature: 0.4, max_tokens: 1200 };
  const { data } = await axios.post(url, body, {
    headers: { 'Authorization': `Bearer ${key}`, 'Content-Type': 'application/json' },
    timeout: 60_000
  });
  return data.choices?.[0]?.message?.content?.trim() || '';
}

async function callAnthropic({ key, model, messages }) {
  // Anthropic wants a separate system prompt + user/assistant alternation.
  const system = messages.find(m => m.role === 'system')?.content || SYSTEM_BASE;
  const convo = messages.filter(m => m.role !== 'system').map(m => ({
    role: m.role === 'assistant' ? 'assistant' : 'user',
    content: m.content
  }));
  const url = 'https://api.anthropic.com/v1/messages';
  const body = { model, system, messages: convo, max_tokens: 1200, temperature: 0.4 };
  const { data } = await axios.post(url, body, {
    headers: {
      'x-api-key': key,
      'anthropic-version': '2023-06-01',
      'Content-Type': 'application/json'
    },
    timeout: 60_000
  });
  return data.content?.[0]?.text?.trim() || '';
}

/**
 * chat({tenantId, userId, messages}) -> { reply, provider }
 * messages is [{role: 'user'|'assistant'|'system', content}]
 */
async function chat({ tenantId, messages }) {
  const { provider, key, model } = resolveProvider(tenantId);
  const fullMessages = messages.some(m => m.role === 'system')
    ? messages
    : [{ role: 'system', content: SYSTEM_BASE }, ...messages];

  if (!key) {
    const lastUser = [...messages].reverse().find(m => m.role === 'user');
    return { reply: stubAnswer(lastUser ? lastUser.content : ''), provider: `${provider}-stub` };
  }

  try {
    const reply = provider === 'anthropic'
      ? await callAnthropic({ key, model, messages: fullMessages })
      : await callOpenAI({ key, model, messages: fullMessages });
    return { reply, provider };
  } catch (err) {
    const detail = err.response?.data?.error?.message || err.message;
    console.error(`AI error (${provider}):`, detail);
    return { reply: `AI provider error: ${detail}`, provider: `${provider}-error` };
  }
}

/**
 * Generate a BCP plan draft using the selected provider.
 */
async function generatePlan({ tenantId, scenario, scope, industry, orgName }) {
  const userPrompt = `Draft a Business Continuity Plan in Markdown for the following context. Keep it practical, not fluffy.

Organization: ${orgName || 'the organization'}
Industry: ${industry || 'generic'}
Scope: ${scope || 'Enterprise'}
Scenario / disruption: ${scenario || 'A major operational disruption'}

Include these sections:
1. Purpose
2. Scope
3. Activation Criteria
4. Roles & Responsibilities (with a small RACI)
5. Immediate Response Procedures (first 60 minutes)
6. Short-term Recovery (first 24 hours)
7. Longer-term Recovery (24 hours to full restoration)
8. Communications (internal + external)
9. Dependencies and alternate sites / suppliers
10. Review & Approval (version 1.0, next review in 12 months)

Also suggest 3 tabletop exercise scenarios tied to this plan.`;
  const { reply, provider } = await chat({
    tenantId,
    messages: [{ role: 'user', content: userPrompt }]
  });
  return { content: reply, provider };
}

module.exports = { chat, generatePlan, resolveProvider, SYSTEM_BASE };
