// Document Q&A routes (RAG over uploaded plans / policies / runbooks).
//
// Upload path accepts either:
//   a) A multipart/form-data file (handled without multer — we parse the
//      raw-body with busboy-free light parsing since the app is configured
//      for urlencoded/json bodies). For simplicity and zero extra deps,
//      this endpoint accepts pasted-text uploads AND a lightweight JSON
//      file upload where the client reads the file in the browser and
//      posts its text content as `content`. This keeps us free of multer.
//
// Note: text extraction for .pdf / .docx is out of scope here. Users can paste
// text, or copy from the BCP Markdown editor. Tested with plan exports and
// policy text blocks.

const express = require('express');
const router = express.Router();
const db = require('../models/db');
const { requireAuth, requireRole } = require('../middleware/auth');
const { ACTIONS } = require('../services/audit');
const rag = require('../services/rag');

router.use(requireAuth);

// ---- INDEX ----
router.get('/', (req, res) => {
  const tid = req.session.tenant.id;
  const docs = db.prepare(`SELECT d.*, p.title AS plan_title
    FROM documents d LEFT JOIN bcp_plans p ON p.id = d.linked_plan_id
    WHERE d.tenant_id = ?
    ORDER BY d.created_at DESC`).all(tid);
  const recentQueries = db.prepare(`SELECT * FROM document_queries WHERE tenant_id = ?
    ORDER BY created_at DESC LIMIT 10`).all(tid);
  const stats = {
    docs: docs.length,
    chunks: docs.reduce((s, d) => s + (d.chunk_count || 0), 0),
    bytes: docs.reduce((s, d) => s + (d.bytes || 0), 0),
    queries: db.prepare('SELECT COUNT(*) AS c FROM document_queries WHERE tenant_id = ?').get(tid).c || 0
  };
  res.render('documents/index', { title: 'Document Q&A', docs, recentQueries, stats });
});

router.get('/new', requireRole('admin', 'manager', 'responder'), (req, res) => {
  const plans = db.prepare('SELECT id, title FROM bcp_plans WHERE tenant_id = ? ORDER BY title')
    .all(req.session.tenant.id);
  res.render('documents/form', { title: 'Upload document', doc: null, plans });
});

// ---- SHOW ----
router.get('/:id', (req, res) => {
  const tid = req.session.tenant.id;
  const doc = db.prepare(`SELECT d.*, p.title AS plan_title
    FROM documents d LEFT JOIN bcp_plans p ON p.id = d.linked_plan_id
    WHERE d.id = ? AND d.tenant_id = ?`).get(req.params.id, tid);
  if (!doc) { req.flash('error', 'Document not found.'); return res.redirect('/documents'); }
  const chunks = db.prepare(`SELECT id, chunk_index, content, token_count
    FROM document_chunks WHERE document_id = ? AND tenant_id = ?
    ORDER BY chunk_index ASC LIMIT 50`).all(doc.id, tid);
  res.render('documents/show', { title: doc.title, doc, chunks });
});

// ---- CREATE (paste-text upload) ----
router.post('/', requireRole('admin', 'manager', 'responder'), (req, res) => {
  const b = req.body;
  const content = (b.content || '').trim();
  if (!b.title || !content) {
    req.flash('error', 'Provide a title and paste the document content.');
    return res.redirect('/documents/new');
  }
  const info = db.prepare(`INSERT INTO documents
    (tenant_id, title, source_kind, filename, mime, bytes, uploaded_by, tags, content, linked_plan_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
    .run(
      req.session.tenant.id, b.title, b.source_kind || 'plan',
      b.filename || null, b.mime || 'text/plain',
      Buffer.byteLength(content, 'utf8'),
      req.session.user.name,
      b.tags || null, content,
      b.linked_plan_id ? +b.linked_plan_id : null
    );
  const id = info.lastInsertRowid;
  const n = rag.indexDocument(req.session.tenant.id, id, content);
  req.audit({ action: ACTIONS.CREATE, entity: 'documents', entityId: id, summary: `Document "${b.title}" uploaded (${n} chunks)` });
  req.flash('success', `Indexed ${n} chunks.`);
  res.redirect('/documents/' + id);
});

// ---- RE-INDEX ----
router.post('/:id/reindex', requireRole('admin', 'manager'), (req, res) => {
  const tid = req.session.tenant.id;
  const doc = db.prepare('SELECT id, content, title FROM documents WHERE id = ? AND tenant_id = ?')
    .get(req.params.id, tid);
  if (!doc) { req.flash('error', 'Document not found.'); return res.redirect('/documents'); }
  const n = rag.indexDocument(tid, doc.id, doc.content);
  req.audit({ action: ACTIONS.UPDATE, entity: 'documents', entityId: doc.id, summary: `Re-indexed "${doc.title}" (${n} chunks)` });
  req.flash('success', `Re-indexed: ${n} chunks.`);
  res.redirect('/documents/' + doc.id);
});

// ---- DELETE ----
router.post('/:id/delete', requireRole('admin', 'manager'), (req, res) => {
  const tid = req.session.tenant.id;
  const d = db.prepare('SELECT title FROM documents WHERE id = ? AND tenant_id = ?')
    .get(req.params.id, tid);
  db.prepare('DELETE FROM documents WHERE id = ? AND tenant_id = ?').run(req.params.id, tid);
  req.audit({ action: ACTIONS.DELETE, entity: 'documents', entityId: +req.params.id, summary: `Document "${d?.title || ''}" removed` });
  req.flash('success', 'Document removed.');
  res.redirect('/documents');
});

// ---- ASK (Q&A page) ----
router.get('/ask/query', (req, res) => {
  const tid = req.session.tenant.id;
  const docs = db.prepare(`SELECT id, title FROM documents WHERE tenant_id = ? ORDER BY title`).all(tid);
  const history = db.prepare(`SELECT * FROM document_queries WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 20`).all(tid);
  res.render('documents/qa', {
    title: 'Ask your documents',
    docs, history,
    initial: null
  });
});

router.post('/ask/query', async (req, res) => {
  const tid = req.session.tenant.id;
  const question = (req.body.question || '').trim();
  const documentId = req.body.document_id ? +req.body.document_id : null;
  if (!question) { req.flash('error', 'Please enter a question.'); return res.redirect('/documents/ask/query'); }

  const { answer, citations, provider } = await rag.ask({ tenantId: tid, question, documentId });

  db.prepare(`INSERT INTO document_queries (tenant_id, user_id, question, answer, cited_chunk_ids, provider)
    VALUES (?, ?, ?, ?, ?, ?)`)
    .run(tid, req.session.user.id, question, answer,
      citations.map(c => c.chunk_id).join(','), provider);

  req.audit({ action: ACTIONS.AI_CALL, entity: 'document_queries', summary: `RAG Q: ${question.slice(0, 80)}` });

  const docs = db.prepare(`SELECT id, title FROM documents WHERE tenant_id = ? ORDER BY title`).all(tid);
  const history = db.prepare(`SELECT * FROM document_queries WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 20`).all(tid);

  res.render('documents/qa', {
    title: 'Ask your documents',
    docs, history,
    initial: { question, answer, citations, provider, documentId }
  });
});

module.exports = router;
