(function () {
  'use strict';
  const root = document.getElementById('auditRooms');
  if (!root) return;
  const get = id => document.getElementById(id);
  let selected = null;
  let room = null;
  function el(tag, value, className) {
    const item = document.createElement(tag);
    item.textContent = value == null ? '' : String(value);
    if (className) item.className = className;
    return item;
  }
  function message(error) { return (error && (error.detail || error.message)) || 'The room could not be loaded.'; }
  function when(value) { return String(value || '').replace('T', ' ').slice(0, 16); }
  async function post(path, body, done) {
    get('arStatus').textContent = 'Saving…';
    try {
      const result = await ApiClient.request(path, {method: 'POST', body, actionId: 'group.room'});
      get('arStatus').textContent = done;
      await load();
      if (selected) await openRoom(selected);
      return result || true;
    } catch (error) { get('arStatus').textContent = message(error); return null; }
  }
  async function load() {
    let data;
    try { data = await ApiClient.request('/governance/api/group/rooms'); }
    catch (error) { get('arStatus').textContent = message(error); return; }
    const list = get('arList');
    list.replaceChildren();
    data.items.forEach(row => {
      const card = el('div', '', 'ar-card');
      card.append(el('strong', row.title));
      card.append(el('small', `${row.status} · ${row.auditor} · ${when(row.starts_at)} to ${when(row.ends_at)} UTC`));
      const open = el('button', 'Open room', 'btn btn-secondary');
      open.type = 'button';
      open.addEventListener('click', () => openRoom(row.id));
      const actions = el('div', '', 'ar-actions'); actions.append(open); card.append(actions);
      list.append(card);
    });
    if (!data.items.length) list.append(el('p', data.can_manage || data.can_approve ? 'No audit rooms yet.' : 'No room is open for you right now.'));
    const create = get('arCreate');
    create.hidden = !data.can_manage;
    if (data.can_manage && !create.dataset.loaded) {
      create.dataset.loaded = '1';
      try {
        const options = await ApiClient.request('/governance/api/group/rooms/candidates');
        create.elements.auditor_user_id.replaceChildren(...options.auditors.map(a => new Option(a.full_name, a.id)));
        const add = get('arAdd').elements.item;
        add.replaceChildren(
          ...options.packs.map(p => new Option(`Pack: ${p.title}`, `pack:${p.id}`)),
          ...options.documents.map(d => new Option(`Document: ${d.title}`, `publication:${d.id}`)));
        if (!options.auditors.length) get('arStatus').textContent = 'Add the auditor as a user with the External Auditor role first.';
      } catch (error) { get('arStatus').textContent = message(error); }
    }
  }
  function renderPack(pack, target) {
    target.append(el('p', `${pack.title} (${pack.period}) · ${pack.integrity_text}`));
    pack.entities.forEach(entity => {
      const card = el('div', '', 'ar-card');
      card.append(el('strong', entity.name));
      entity.figures.forEach(figure => card.append(el('small', `${figure.label}: ${figure.value == null ? 'not available' : figure.value} (${figure.state.replaceAll('_', ' ')})`)));
      (entity.issues || []).forEach(issue => card.append(el('small', `${issue.label}: ${issue.total} records`)));
      target.append(card);
    });
  }
  async function openItem(item) {
    const target = get('arOpened');
    try {
      const data = await ApiClient.request(`/governance/api/group/rooms/${selected}/items/${item.id}`);
      target.replaceChildren();
      if (data.kind === 'pack') renderPack(data.pack, target);
      else target.append(el('p', `${data.document.title} v${data.document.version} from ${data.document.source_name} (${data.document.classification})`));
      if (data.can_download) {
        (data.kind === 'pack' ? ['pdf', 'xlsx'] : ['pdf']).forEach(format => {
          const link = el('a', data.kind === 'pack' ? `Download ${format === 'pdf' ? 'PDF' : 'Excel'}` : 'Download file', 'btn btn-secondary');
          link.href = `/governance/api/group/rooms/${selected}/items/${item.id}/download?format=${format}`;
          target.append(link);
        });
      }
    } catch (error) { get('arStatus').textContent = message(error); }
  }
  async function openRoom(id) {
    try { room = await ApiClient.request(`/governance/api/group/rooms/${id}`); }
    catch (error) { get('arStatus').textContent = message(error); return; }
    selected = id;
    get('arDetail').hidden = false;
    get('arTitle').textContent = room.title;
    get('arMeta').textContent = `${room.status} · ${when(room.starts_at)} to ${when(room.ends_at)} UTC`;
    const items = get('arItems');
    items.replaceChildren();
    room.items.forEach(item => {
      const card = el('div', '', 'ar-card');
      card.append(el('strong', `${item.id}. ${item.available ? item.title : 'No longer available to the person who added it'}`));
      if (item.available) {
        const open = el('button', 'Open', 'btn btn-secondary');
        open.type = 'button';
        open.addEventListener('click', () => openItem(item));
        const actions = el('div', '', 'ar-actions'); actions.append(open); card.append(actions);
      }
      items.append(card);
    });
    if (!room.items.length) items.append(el('p', 'Nothing is in this room yet.'));
    get('arAdd').hidden = !room.can_add;
    get('arDecide').hidden = !room.can_decide;
    get('arAsk').hidden = !room.can_ask;
    get('arClose').hidden = !room.can_close;
    const messages = get('arMessages');
    messages.replaceChildren();
    room.messages.forEach(row => {
      const card = el('div', '', 'ar-card');
      card.append(el('strong', `${row.kind === 'question' ? 'Question' : 'Answer'} from ${row.author || 'unknown'} · ${when(row.created_at)}`));
      card.append(el('p', row.body));
      if (row.cites.length) card.append(el('small', `Cites room items ${row.cites.join(', ')}`));
      if (row.kind === 'question' && room.can_answer) {
        const form = el('form', '', 'ar-form');
        const body = document.createElement('textarea'); body.maxLength = 2000; body.rows = 2; body.required = true;
        const cites = document.createElement('input'); cites.placeholder = 'Item numbers, for example 1, 2'; cites.required = true;
        const bodyLabel = el('label', 'Answer'); bodyLabel.className = 'ar-wide'; bodyLabel.append(body);
        const citeLabel = el('label', 'Cites room items'); citeLabel.append(cites);
        const send = el('button', 'Answer', 'btn btn-secondary'); send.type = 'submit';
        form.append(bodyLabel, citeLabel, send);
        form.addEventListener('submit', event => {
          event.preventDefault();
          post(`/governance/api/group/rooms/${selected}/messages`, {body: body.value, reply_to: row.id,
            cites: cites.value.split(',').map(v => Number(v.trim())).filter(Number.isInteger)}, 'Answer sent.');
        });
        card.append(form);
      }
      messages.append(card);
    });
    if (!room.messages.length) messages.append(el('p', 'No questions yet.'));
    const events = get('arEvents');
    events.replaceChildren();
    if (room.events) {
      events.append(el('h2', 'Room history'));
      room.events.forEach(row => events.append(el('div', `${when(row.created_at)} · ${row.actor || 'unknown'} · ${row.action.replaceAll('_', ' ')} ${row.detail || ''}`, 'ar-card')));
    }
  }
  get('arCreate').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const result = await post('/governance/api/group/rooms', {
      title: form.elements.title.value, auditor_user_id: Number(form.elements.auditor_user_id.value),
      starts_at: new Date(form.elements.starts_at.value).toISOString(), ends_at: new Date(form.elements.ends_at.value).toISOString()},
    'Room proposed. Add its items, then a different person approves it.');
    if (result && result.id) { form.reset(); openRoom(result.id); }
  });
  get('arAdd').addEventListener('submit', event => {
    event.preventDefault();
    const form = event.currentTarget;
    const [kind, id] = form.elements.item.value.split(':');
    post(`/governance/api/group/rooms/${selected}/items`, {kind, ref_id: Number(id), allow_download: form.elements.allow_download.checked}, 'Item added.');
  });
  get('arDecide').addEventListener('submit', event => {
    event.preventDefault();
    const decision = event.submitter ? event.submitter.value : 'open';
    post(`/governance/api/group/rooms/${selected}/decision`, {decision, reason: event.currentTarget.elements.reason.value},
      decision === 'open' ? 'Room approved and open.' : 'Room rejected.');
  });
  get('arAsk').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    if (await post(`/governance/api/group/rooms/${selected}/messages`, {body: form.elements.body.value}, 'Question sent.')) form.reset();
  });
  get('arClose').addEventListener('submit', event => {
    event.preventDefault();
    post(`/governance/api/group/rooms/${selected}/close`, {reason: event.currentTarget.elements.reason.value}, 'Room closed.');
  });
  load().then(() => {
    const requested = Number(new URLSearchParams(location.search).get('room'));
    if (Number.isSafeInteger(requested) && requested > 0) openRoom(requested);
  });
})();
