// Lightweight Retrieval-Augmented Generation service.
//
// Design goals:
//   - Works with zero external dependencies (no vector DB, no embeddings required).
//   - Chunking: ~600-character windows, snapped to sentence boundaries, 80-char overlap.
//   - Scoring: BM25-style idf-weighted term overlap between the query and each chunk.
//   - Generation: builds a system prompt with the top-K retrieved chunks and delegates to services/ai.js.
//
// When an API key is configured, answers are produced by the tenant's chosen provider.
// When no key is set, we fall back to the AI service's stub, but still cite real chunks
// so the UX is complete end-to-end during development.

const db = require('../models/db');
const ai = require('./ai');

const STOPWORDS = new Set([
  'the','a','an','and','or','but','if','then','else','for','of','on','in','to','is','are','was','were',
  'be','been','being','as','at','by','from','this','that','these','those','with','it','its','his','her',
  'our','their','we','you','they','i','me','my','mine','your','yours','us','our','ours','him','he','she',
  'what','which','who','whom','whose','how','when','where','why','will','would','can','could','should',
  'do','does','did','done','so','not','no','yes','also','such','into','than','there','here','about'
]);

function tokenize(str) {
  if (!str) return [];
  return str.toLowerCase()
    .replace(/[^a-z0-9\s'-]/g, ' ')
    .split(/\s+/)
    .filter(t => t.length > 1 && !STOPWORDS.has(t));
}

/**
 * Split raw text into overlapping, sentence-aware chunks.
 * Returns an array of strings.
 */
function chunkText(text, { targetSize = 600, overlap = 80 } = {}) {
  if (!text) return [];
  const clean = text.replace(/\r\n/g, '\n').trim();
  // Split on sentence enders and newlines so we stay inside natural boundaries.
  const sentences = clean.split(/(?<=[.!?])\s+|\n{2,}/).map(s => s.trim()).filter(Boolean);

  const chunks = [];
  let current = '';
  for (const s of sentences) {
    if (!current.length) { current = s; continue; }
    if ((current.length + 1 + s.length) <= targetSize) {
      current += ' ' + s;
    } else {
      chunks.push(current);
      // Start next chunk with a tail-overlap from the previous one to preserve context.
      const tail = current.slice(Math.max(0, current.length - overlap));
      current = tail + ' ' + s;
    }
  }
  if (current.trim().length) chunks.push(current.trim());
  return chunks;
}

/**
 * Persist chunks for a document, replacing anything already on file.
 */
function indexDocument(tenantId, documentId, text) {
  db.prepare('DELETE FROM document_chunks WHERE tenant_id = ? AND document_id = ?')
    .run(tenantId, documentId);

  const chunks = chunkText(text || '');
  const insert = db.prepare(`INSERT INTO document_chunks
    (tenant_id, document_id, chunk_index, content, token_count) VALUES (?, ?, ?, ?, ?)`);
  chunks.forEach((c, i) => {
    insert.run(tenantId, documentId, i, c, tokenize(c).length);
  });
  db.prepare('UPDATE documents SET chunk_count = ? WHERE id = ? AND tenant_id = ?')
    .run(chunks.length, documentId, tenantId);
  return chunks.length;
}

/**
 * Retrieve top-K chunks for a query across the tenant's corpus.
 * Simple BM25-ish scoring: sum of idf * tf for query terms that appear in the chunk.
 */
function retrieve(tenantId, query, { k = 5, documentId = null } = {}) {
  const qTokens = tokenize(query);
  if (!qTokens.length) return [];

  const where = documentId
    ? 'WHERE c.tenant_id = ? AND c.document_id = ?'
    : 'WHERE c.tenant_id = ?';
  const params = documentId ? [tenantId, documentId] : [tenantId];

  const rows = db.prepare(`SELECT c.id, c.document_id, c.chunk_index, c.content,
      d.title AS doc_title, d.source_kind AS doc_kind
    FROM document_chunks c
    JOIN documents d ON d.id = c.document_id
    ${where}`).all(...params);

  if (!rows.length) return [];

  // Document frequency per query term
  const df = Object.fromEntries(qTokens.map(t => [t, 0]));
  const rowTokens = rows.map(r => {
    const toks = tokenize(r.content);
    const seen = new Set(toks);
    for (const t of qTokens) if (seen.has(t)) df[t] += 1;
    return toks;
  });

  const N = rows.length;
  const avgdl = rowTokens.reduce((s, t) => s + t.length, 0) / Math.max(1, N);
  const k1 = 1.5, b = 0.75;

  const scored = rows.map((r, i) => {
    const toks = rowTokens[i];
    const tf = {};
    for (const t of toks) tf[t] = (tf[t] || 0) + 1;
    let score = 0;
    for (const qt of qTokens) {
      const f = tf[qt] || 0;
      if (!f) continue;
      const idf = Math.log(1 + (N - df[qt] + 0.5) / (df[qt] + 0.5));
      const denom = f + k1 * (1 - b + b * (toks.length / Math.max(1, avgdl)));
      score += idf * (f * (k1 + 1)) / denom;
    }
    return { ...r, score: +score.toFixed(3) };
  }).filter(r => r.score > 0);

  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, k);
}

/**
 * Ask a question against the tenant corpus. Returns { answer, citations, provider }.
 */
async function ask({ tenantId, question, k = 5, documentId = null }) {
  const chunks = retrieve(tenantId, question, { k, documentId });
  if (!chunks.length) {
    return {
      answer: 'I could not find any relevant content in your document library to answer that. Try uploading the plan, policy, or procedure first, or rephrase the question.',
      citations: [],
      provider: 'no-corpus'
    };
  }

  const context = chunks.map((c, i) =>
    `[Source ${i + 1} — ${c.doc_title} (chunk ${c.chunk_index})]\n${c.content}`
  ).join('\n\n---\n\n');

  const systemPrompt = `You are the Document Q&A assistant for BCM Sentinel.
Answer the user's question USING ONLY the provided sources below. When you use a fact from a source,
cite it inline like [Source 1] or [Source 3]. If the sources do not cover the question, say so plainly.
Prefer concise bullet lists for steps and procedures.

SOURCES:
${context}`;

  const { reply, provider } = await ai.chat({
    tenantId,
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: question }
    ]
  });

  return {
    answer: reply,
    citations: chunks.map((c, i) => ({
      label: `Source ${i + 1}`,
      document_id: c.document_id,
      chunk_id: c.id,
      chunk_index: c.chunk_index,
      doc_title: c.doc_title,
      doc_kind: c.doc_kind,
      score: c.score,
      snippet: c.content.slice(0, 240) + (c.content.length > 240 ? '…' : '')
    })),
    provider
  };
}

module.exports = { chunkText, indexDocument, retrieve, ask, tokenize };
