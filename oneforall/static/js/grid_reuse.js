(function () {
  'use strict';
  const root = document.getElementById('gridReuse');
  if (!root) return;
  const get = id => document.getElementById(id);
  const RELATION = {full: 'Full match', partial: 'Partial match', none: 'No match'};
  let page = 1;
  let preview = null;
  function el(tag, value, className) {
    const node = document.createElement(tag);
    node.textContent = value == null ? '' : String(value);
    if (className) node.className = className;
    return node;
  }
  function say(text) { get('grStatus').textContent = text; }
  function message(error) { return (error && (error.detail || error.message)) || 'That did not work. Reload the page and try again.'; }
  function list(items) {
    const ul = el('ul', '');
    items.forEach(text => ul.append(el('li', text)));
    return ul;
  }
  function pair() {
    const form = get('grPick').elements;
    return {target: Number(form.target.value), source: Number(form.source.value)};
  }
  async function post(path, body) {
    return ApiClient.request(path, {method: 'POST', body, actionId: 'grid.reuse'});
  }
  async function reviewMapping(id, kind) {
    say('Saving…');
    try { await post(`/grid/api/reuse/mappings/${id}/review`, {kind}); }
    catch (error) { say(message(error)); return; }
    await show();
    say(kind === 'equivalent' ? 'Mapping recorded as equivalent.' : 'Mapping recorded as partial.');
  }
  function row(r) {
    const tr = document.createElement('tr');
    const pick = el('td', '');
    if (r.would_change) {
      const box = document.createElement('input');
      box.type = 'checkbox'; box.value = r.target.id; box.dataset.fingerprint = r.fingerprint;
      box.setAttribute('aria-label', `Apply to ${r.target.ref || ''} ${r.target.name}`);
      pick.append(box);
    } else pick.append(el('span', r.relation === 'none' ? '' : 'Nothing new', 'gr-muted'));
    tr.append(pick);
    const target = el('td', '');
    target.append(el('strong', `${r.target.ref || ''} ${r.target.name}`), el('div', r.target.status || 'Not Started', 'gr-muted'));
    tr.append(target);
    const match = el('td', '');
    match.append(el('span', RELATION[r.relation], 'gr-chip is-' + r.relation), el('div', r.basis, 'gr-muted'));
    if (r.mapping_id) {
      const actions = el('div', '', 'gr-actions');
      [['equivalent', 'Mark equivalent'], ['partial', 'Mark partial']].forEach(([kind, label]) => {
        const b = el('button', label, 'btn btn-ghost btn-sm'); b.type = 'button';
        b.addEventListener('click', () => reviewMapping(r.mapping_id, kind));
        actions.append(b);
      });
      match.append(actions);
    }
    tr.append(match);
    const source = el('td', '');
    if (r.source) source.append(el('strong', `${r.source.ref || ''} ${r.source.name}`), el('div', r.source.status || 'Not Started', 'gr-muted'));
    tr.append(source);
    const accepted = el('td', '');
    if (r.answer) accepted.append(el('div', `Answer accepted ${r.answer.accepted_at}: ${r.answer.text}`));
    if (r.proof.length) accepted.append(list(r.proof.map(p => `${p.title} (version ${p.version})`)));
    if (r.note) accepted.append(el('div', 'The answer would be added as a suggestion.', 'gr-muted'));
    if (r.carry.length) accepted.append(el('div', `${r.carry.length} file(s) would be linked, waiting for review.`, 'gr-muted'));
    tr.append(accepted);
    const held = el('td', '');
    if (r.held_back.length) held.append(list(r.held_back));
    tr.append(held);
    return tr;
  }
  async function show() {
    const {target, source} = pair();
    if (!target || !source) { say('Choose both audits.'); return; }
    try { preview = await ApiClient.request(`/grid/api/reuse/preview?target=${target}&source=${source}&page=${page}`); }
    catch (error) { say(message(error)); return; }
    get('grPreview').hidden = false;
    get('grTitle').textContent = `${preview.target.name}, from ${preview.source.name}`;
    const c = preview.counts;
    get('grSummary').replaceChildren(el('span', `${c.full} full`, 'gr-chip is-full'), el('span', `${c.partial} partial`, 'gr-chip is-partial'),
      el('span', `${c.none} with no match`, 'gr-chip'), el('span', `${c.would_change} would change`, 'gr-chip'));
    get('grNote').textContent = preview.note;
    get('grRows').replaceChildren(...preview.rows.map(row));
    get('grPage').textContent = `Page ${preview.page} of ${preview.pages}`;
    get('grPrev').disabled = preview.page <= 1;
    get('grNext').disabled = preview.page >= preview.pages;
    get('grApply').disabled = preview.target.locked;
    await history(target);
  }
  async function history(target) {
    let data;
    try { data = await ApiClient.request(`/grid/api/reuse/history?target=${target}`); } catch (error) { say(message(error)); return; }
    get('grHistoryPanel').hidden = !data.items.length;
    get('grHistory').replaceChildren(...data.items.map(h => {
      const card = el('div', '', 'gr-actions');
      card.append(el('span', `${String(h.applied_at).slice(0, 16)} · ${h.applied_by || ''} · from ${h.source || 'an audit'} · ${h.rows} control(s)` +
        (h.undone_at ? ` · undone ${String(h.undone_at).slice(0, 16)}: ${h.undo_reason}` : '')));
      if (!h.undone_at) {
        const reason = document.createElement('input');
        reason.type = 'text'; reason.maxLength = 1000; reason.placeholder = 'Reason for undoing';
        reason.setAttribute('aria-label', 'Reason for undoing');
        const undo = el('button', 'Undo', 'btn btn-secondary btn-sm'); undo.type = 'button';
        undo.addEventListener('click', async () => {
          say('Saving…');
          try { await post(`/grid/api/reuse/decisions/${h.id}/undo`, {reason: reason.value}); }
          catch (error) { say(message(error)); return; }
          await show();
          say('Undone. What it added is gone.');
        });
        card.append(reason, undo);
      }
      return card;
    }));
  }
  get('grPick').addEventListener('submit', event => { event.preventDefault(); page = 1; say(''); show(); });
  get('grPrev').addEventListener('click', () => { page = Math.max(1, page - 1); show(); });
  get('grNext').addEventListener('click', () => { page += 1; show(); });
  get('grApply').addEventListener('click', async () => {
    const rows = [...get('grRows').querySelectorAll('input[type=checkbox]:checked')].map(b => ({
      target_control_id: Number(b.value), fingerprint: b.dataset.fingerprint}));
    if (!rows.length) { say('Choose at least one row.'); return; }
    const {target, source} = pair();
    let result;
    say('Saving…');
    try { result = await post('/grid/api/reuse/apply', {target_audit_id: target, source_audit_id: source, rows}); }
    catch (error) { say(message(error)); return; }
    await show();
    say(`Applied to ${result.applied} control(s): ${result.links} file(s) linked for review, ${result.notes} answer(s) added as suggestions.`);
  });
  (async () => {
    let data;
    try { data = await ApiClient.request('/grid/api/reuse/audits'); } catch (error) { say(message(error)); return; }
    const form = get('grPick').elements;
    const options = data.items.map(a => [a.id, a.name + (a.date ? ` (${String(a.date).slice(0, 10)})` : '')]);
    form.target.replaceChildren(...options.map(([id, label]) => new Option(label, id)));
    form.source.replaceChildren(...options.map(([id, label]) => new Option(label, id)));
    if (options.length > 1) form.source.selectedIndex = 1;
  })();
})();
