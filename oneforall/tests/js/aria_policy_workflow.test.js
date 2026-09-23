'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const workflowSource = fs.readFileSync(
  path.resolve(__dirname, '../../static/js/aria_policy_workflow.js'),
  'utf8'
);

function makeElement(id) {
  const classes = new Set();
  return {
    id,
    style: {},
    attributes: {},
    disabled: false,
    value: '',
    textContent: '',
    innerHTML: '',
    options: [],
    selectedIndex: -1,
    classList: {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      toggle: (name, force) => {
        if (force === true) classes.add(name);
        else if (force === false) classes.delete(name);
        else if (classes.has(name)) classes.delete(name);
        else classes.add(name);
      },
      contains: (name) => classes.has(name),
    },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    removeAttribute(name) { delete this.attributes[name]; },
    addEventListener() {},
    appendChild() {},
    focus() {},
  };
}

function loadWorkflow(fetchImpl) {
  const ids = [
    'draftEditor', 'policyContent', 'editorTabEdit', 'editorTabPreview',
    'draftUnsavedIndicator', 'draftSavedIndicator', 'draftStatusBar',
    'emptyState', 'loadingState', 'outputBody', 'outputActions',
    'workflowPanel', 'workflowConfirmBtn', 'workflowPreviewSection',
    'workflowPdfContainer', 'workflowConfirmHint', 'draftSaveBtn',
  ];
  const elements = new Map(ids.map((id) => [id, makeElement(id)]));
  const toasts = [];
  const requests = [];

  const window = {
    addEventListener() {},
    showToast(message, type) { toasts.push({ message, type }); },
    AriaMarkdown: { isAvailable: () => true, renderInto() {} },
    AriaPdfViewer: { render: async () => ({ pageCount: 1 }) },
    location: { href: '' },
  };
  const document = {
    readyState: 'loading',
    getElementById: (id) => elements.get(id) || null,
    createElement: (tag) => makeElement(tag),
    addEventListener() {},
  };
  const fetch = async (url, options) => {
    requests.push({ url, options: options || {} });
    return fetchImpl(url, options || {});
  };
  const context = vm.createContext({
    window,
    document,
    fetch,
    console,
    encodeURIComponent,
    setTimeout: (callback) => { callback(); return 1; },
    clearTimeout() {},
  });
  vm.runInContext(workflowSource, context, { filename: 'aria_policy_workflow.js' });

  return {
    ui: window.AriaPolicyWorkflow.ui,
    elements,
    requests,
    toasts,
    window,
  };
}

function draft(overrides) {
  return Object.assign({
    id: 'draft-1',
    body: '# Saved policy',
    state: 'ready',
    build_id: 'build-1',
    lock_version: 3,
    version_major: 1,
    version_minor: 0,
    reserved_doc_id: 'DOC-0001',
    business_unit_id: null,
  }, overrides || {});
}

test('editing removes the stale preview and visibly disables confirmation', () => {
  const app = loadWorkflow(async () => {
    throw new Error('fetch should not be called');
  });
  app.ui.enterDraftEditingMode(draft());

  const preview = app.elements.get('workflowPreviewSection');
  const pdf = app.elements.get('workflowPdfContainer');
  const confirm = app.elements.get('workflowConfirmBtn');
  const hint = app.elements.get('workflowConfirmHint');
  preview.style.display = '';
  pdf.innerHTML = '<canvas></canvas>';
  confirm.disabled = false;

  app.elements.get('draftEditor').value = '# Changed policy';
  app.ui.onEditorInput();

  assert.equal(preview.style.display, 'none');
  assert.equal(pdf.innerHTML, '');
  assert.equal(confirm.disabled, true);
  assert.equal(confirm.attributes['aria-disabled'], 'true');
  assert.match(hint.textContent, /draft changed/i);
});

test('saving mirrors server-side build invalidation in the browser', async () => {
  const saved = draft({ state: 'editing', build_id: null, lock_version: 4 });
  const app = loadWorkflow(async (url, options) => {
    assert.equal(url, '/aria/api/policy-drafts/draft-1');
    assert.equal(options.method, 'PUT');
    return { ok: true, status: 200, json: async () => ({ ok: true, draft: saved }) };
  });
  app.ui.enterDraftEditingMode(draft());

  const preview = app.elements.get('workflowPreviewSection');
  const confirm = app.elements.get('workflowConfirmBtn');
  preview.style.display = '';
  confirm.disabled = false;

  await app.ui.saveDraft();

  assert.equal(preview.style.display, 'none');
  assert.equal(confirm.disabled, true);
  assert.match(app.elements.get('workflowConfirmHint').textContent, /draft saved/i);
  assert.equal(
    app.toasts.at(-1).message,
    'Draft saved. Apply the template again before confirming.'
  );
});

test('confirm without a current build explains the required action', async () => {
  const app = loadWorkflow(async () => {
    throw new Error('fetch should not be called');
  });
  app.ui.enterDraftEditingMode(draft({ state: 'editing', build_id: null }));

  await app.ui.confirmDraft();

  assert.equal(app.requests.length, 0);
  assert.match(app.toasts.at(-1).message, /build a current preview/i);
});

test('valid confirmation shows progress and redirects after success', async () => {
  let resolveRequest;
  const app = loadWorkflow((url, options) => new Promise((resolve) => {
    assert.equal(url, '/aria/api/policy-drafts/draft-1/confirm');
    assert.equal(options.method, 'POST');
    resolveRequest = resolve;
  }));
  app.ui.enterDraftEditingMode(draft());

  const action = app.ui.confirmDraft();
  await new Promise((resolve) => setImmediate(resolve));

  const confirm = app.elements.get('workflowConfirmBtn');
  assert.equal(confirm.disabled, true);
  assert.equal(confirm.textContent, 'Confirming…');
  assert.match(app.elements.get('workflowConfirmHint').textContent, /confirming this version/i);

  resolveRequest({
    ok: true,
    status: 200,
    json: async () => ({
      ok: true,
      doc_id: 'DOC-0001',
      detail_url: '/aria/documents?open=DOC-0001',
    }),
  });
  await action;

  assert.equal(app.window.location.href, '/aria/documents?open=DOC-0001');
  assert.equal(app.toasts.at(-1).message, 'Version confirmed. Opening the document…');
});
