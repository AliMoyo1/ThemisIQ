(function () {
  'use strict';
  const root = document.getElementById('groupSharing');
  if (!root) return;
  let workspace;
  let evidenceMatches = [];
  let evidencePage = 1;
  let grantRows = [];
  let grantPage = 0;
  let grantLoading = false;
  let searchSequence = 0;
  const status = document.getElementById('gsStatus');
  const byId = id => document.getElementById(id);
  const text = (tag, value, className) => {
    const node = document.createElement(tag);
    node.textContent = String(value == null ? '' : value);
    if (className) node.className = className;
    return node;
  };
  const select = (form, name, rows, label) => {
    const field = form.elements[name];
    field.replaceChildren();
    field.appendChild(new Option(label, ''));
    rows.forEach(row => field.appendChild(new Option(row.label, String(row.id))));
  };
  const iso = value => {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) throw new Error('Choose a valid date and time.');
    return parsed.toISOString();
  };
  const button = (label, action, id) => {
    const node = text('button', label, 'btn btn-secondary');
    node.type = 'button';
    node.dataset.action = action;
    node.dataset.id = String(id);
    return node;
  };
  function renderRelationships() {
    const target = byId('gsRelationshipRows');
    target.replaceChildren();
    const caps = workspace.capabilities;
    if (!workspace.relationships.length) target.appendChild(text('p', 'No reviewed group relationships yet.'));
    workspace.relationships.forEach(row => {
      const box = text('article', '', 'gs-row');
      box.appendChild(text('strong', `${row.parent_name} → ${row.child_name}`));
      box.appendChild(text('small', `${row.status} · ${row.purpose} · review ${row.review_due_at || 'not set'}`));
      const terms = row.terms || {};
      box.appendChild(text('small', `Agreement ${terms.agreement_ref || 'unspecified'} · ${terms.legal_basis || 'no legal basis'} · jurisdictions: ${(terms.jurisdictions || []).join(', ')}`));
      box.appendChild(text('small', `Data: ${(terms.data_classes || []).join(', ')} · classifications: ${(terms.classifications || []).join(', ')} · audience: ${(terms.audiences || []).join(', ')} · fields: ${(terms.fields || []).join(', ')}`));
      if (row.status === 'proposed') {
        const decisions = [
          ['ack', 'Child acknowledgement', 'child_ack_by', 'group.relationship.ack'],
          ['privacy', 'Privacy review', 'privacy_review_by', 'group.terms.privacy'],
          ['legal', 'Legal review', 'legal_review_by', 'group.terms.legal']
        ];
        const actions = text('div', '', 'gs-actions');
        decisions.forEach(([kind, label, field, cap]) => {
          if (row[field]) actions.appendChild(text('small', `${label} recorded`));
          else if (row.can_decide && caps[cap] && (kind !== 'ack' || row.is_child)) actions.appendChild(button(label, `decide:${kind}`, row.id));
        });
        if (row.can_deem_notice) actions.appendChild(button('Record notice as given', 'deem', row.id));
        box.appendChild(actions);
      }
      if (row.status === 'active' && caps['group.relationship.manage']) {
        const actions = text('div', '', 'gs-actions');
        actions.appendChild(button('End relationship', 'end', row.id));
        box.appendChild(actions);
      }
      target.appendChild(box);
    });
    const proposal = byId('gsPropose');
    proposal.hidden = !caps['group.relationship.manage'];
    if (!proposal.hidden) {
      const orgs = workspace.organizations.map(row => ({id: row.id, label: row.name}));
      select(proposal, 'parent_org_id', orgs, 'Choose parent');
      select(proposal, 'child_org_id', orgs, 'Choose child');
      const list = byId('gsMeasureList');
      if (!list.childElementCount) (workspace.figure_measures || []).forEach(measure => {
        const label = document.createElement('label');
        const box = document.createElement('input');
        box.type = 'checkbox'; box.name = 'figure_measures'; box.value = measure.key;
        label.append(box, ' ' + measure.label);
        label.style.display = 'block';
        list.append(label);
      });
    }
  }
  function renderGrants() {
    const form = byId('gsGrant');
    form.hidden = !workspace.capabilities['group.grant.manage'];
    const active = workspace.relationships.filter(row => row.can_grant);
    if (!form.hidden) {
      select(form, 'relationship_id', active.map(row => ({id: row.id, label: `${row.parent_name} → ${row.child_name}`})), 'Choose relationship');
      select(form, 'user_id', workspace.recipients.map(row => ({id: row.id, label: row.full_name})), 'Choose person');
    }
    const target = byId('gsGrantRows'); target.replaceChildren();
    grantRows.forEach(row => {
      const box = text('article', '', 'gs-row');
      box.appendChild(text('strong', `${row.recipient_name || 'Former user'} · ${row.capability}`));
      box.appendChild(text('small', `${row.source_name} · review ${row.review_due_at} · expires ${row.expires_at}`));
      if (row.review_overdue) box.appendChild(text('small', 'Review overdue · access is paused'));
      box.appendChild(text('small', `Last matching action: ${row.last_matching_access_at || 'none recorded'} (may match another grant)`));
      const actions = text('div', '', 'gs-actions');
      if (row.can_review) actions.appendChild(button('Review access', 'review-grant', row.id));
      actions.appendChild(button('Revoke access', 'revoke-grant', row.id));
      box.appendChild(actions); target.appendChild(box);
    });
  }
  function renderDocuments() {
    const files = evidenceMatches.map(row => ({id: row.id, label: `${row.title} · v${row.version}`}));
    const rights = byId('gsRightsForm');
    rights.hidden = !workspace.capabilities['group.rights.review'];
    if (!rights.hidden) select(rights, 'evidence_id', files, 'Choose source document');
    const publish = byId('gsPublish');
    publish.hidden = !workspace.capabilities['group.document.publish'];
    if (!publish.hidden) {
      select(publish, 'evidence_id', files, 'Choose source document');
      select(publish, 'relationship_id', workspace.relationships.filter(row => row.can_publish)
        .map(row => ({id: row.id, label: `${row.parent_name} → ${row.child_name}`})), 'Choose relationship');
    }
    const target = byId('gsPublicationRows'); target.replaceChildren();
    workspace.publications.forEach(row => {
      const box = text('article', '', 'gs-row');
      box.appendChild(text('strong', `${row.title} · v${row.version}`));
      box.appendChild(text('small', `Expires ${row.expires_at}`));
      const actions = text('div', '', 'gs-actions');
      actions.appendChild(button('Revoke release', 'revoke-publication', row.id));
      box.appendChild(actions); target.appendChild(box);
    });
  }
  async function refresh() {
    workspace = await ApiClient.request('/evidence/api/group/workspace', {actionId: 'group.workspace'});
    evidenceMatches = workspace.evidence;
    byId('gsEvidenceSearch').hidden = !(workspace.capabilities['group.rights.review'] ||
      workspace.capabilities['group.document.publish']);
    renderRelationships(); renderDocuments();
    if (workspace.capabilities['group.grant.manage']) await loadGrants(1);
    else { grantRows = []; grantPage = 0; renderGrants(); byId('gsGrantMore').hidden = true; }
  }
  async function loadGrants(page) {
    if (grantLoading) return;
    grantLoading = true;
    const more = byId('gsGrantMore');
    const result = byId('gsGrantResult');
    more.disabled = true;
    result.textContent = 'Loading access grants…';
    try {
      const data = await ApiClient.request(`/evidence/api/group/grants?page=${page}`, {actionId: 'group.grant_review_queue'});
      grantRows = page === 1 ? data.items : grantRows.concat(data.items);
      grantPage = page;
      more.hidden = !data.has_more;
      result.textContent = `${grantRows.length} active grants shown`;
      renderGrants();
    } catch (error) { result.textContent = error.detail || 'Access grants are unavailable.'; }
    finally { grantLoading = false; more.disabled = false; }
  }
  byId('gsGrantMore').addEventListener('click', () => loadGrants(grantPage + 1));
  async function searchEvidence(page) {
    const sequence = ++searchSequence;
    const query = byId('gsEvidenceSearch').value.trim();
    const result = byId('gsEvidenceResult');
    result.textContent = 'Searching…';
    try {
      const data = await ApiClient.request(`/evidence/api/group/source-candidates?q=${encodeURIComponent(query)}&page=${page}`,
        {actionId: 'group.source_search'});
      if (sequence !== searchSequence) return;
      evidencePage = page;
      evidenceMatches = page === 1 ? data.items : evidenceMatches.concat(data.items);
      byId('gsEvidenceMore').hidden = !data.has_more;
      result.textContent = `${evidenceMatches.length} matching source documents shown`;
      renderDocuments();
    } catch (error) { if (sequence === searchSequence) result.textContent = error.detail || 'Search is unavailable.'; }
  }
  let searchTimer;
  byId('gsEvidenceSearch').addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => searchEvidence(1), 250);
  });
  byId('gsEvidenceMore').addEventListener('click', () => searchEvidence(evidencePage + 1));
  async function act(method, path, body, success) {
    status.textContent = 'Saving…';
    try {
      await ApiClient.request(path, {method, body, actionId: 'group.sharing'});
      await refresh();
      status.textContent = success;
      return true;
    } catch (error) {
      status.textContent = error.detail || error.message || 'The change could not be saved.';
      return false;
    }
  }
  root.addEventListener('click', async event => {
    const control = event.target.closest('button[data-action]');
    if (!control) return;
    const id = encodeURIComponent(control.dataset.id);
    const action = control.dataset.action;
    if (action.startsWith('decide:')) {
      act('POST', `/evidence/api/group/relationships/${id}/decisions`, {kind: action.slice(7)}, 'Decision recorded.');
    } else if (action === 'deem') {
      act('POST', `/evidence/api/group/relationships/${id}/notice`, {}, 'Notice recorded as given.');
    } else if (action === 'review-grant') {
      const grant = grantRows.find(row => String(row.id) === String(control.dataset.id));
      if (!grant || !grant.can_review) return;
      const form = byId('gsReviewGrant');
      form.reset(); form.elements.grant_id.value = String(grant.id);
      form.elements.decision.querySelector('option[value="narrow"]').disabled = grant.capability !== 'document.download';
      reviewDates();
      byId('gsReviewTarget').textContent = `Review ${grant.capability} for ${
        grant.recipient_name || 'former user'}. ` +
        'Access stops on its review date until independently renewed.';
      form.hidden = false; form.scrollIntoView({block: 'nearest'});
    } else if (action === 'revoke-grant') {
      if (confirm('Revoke this person’s access now?')) act('DELETE', `/evidence/api/group/grants/${id}`, null, 'Access revoked.');
    } else if (action === 'revoke-publication') {
      if (confirm('Revoke this publication now?')) act('DELETE', `/evidence/api/group/publications/${id}`, null, 'Publication revoked.');
    } else if (action === 'end') {
      try {
        const impact = await ApiClient.request(`/evidence/api/group/relationships/${id}/exit-impact`,
          {actionId: 'group.exit_impact'});
        const reason = prompt(`Ending this relationship will make ${impact.active_grants} grants and ${impact.active_publications} publications unavailable immediately. Enter the reason to proceed:`);
        if (reason !== null) act('DELETE', `/evidence/api/group/relationships/${id}`,
          {reason}, 'Relationship ended.');
      } catch (error) { status.textContent = error.detail || 'Impact is unavailable.'; }
    }
  });
  byId('gsPropose').addEventListener('submit', event => {
    event.preventDefault();
    const data = new FormData(event.target);
    const fields = ['title', 'category', 'version', 'source_name', 'classification', 'expires_at'];
    try {
      act('POST', '/evidence/api/group/relationships', {
        parent_org_id: Number(data.get('parent_org_id')), child_org_id: Number(data.get('child_org_id')),
        purpose: data.get('purpose'), review_due_at: iso(data.get('review_due_at')),
        terms: {data_classes: data.get('data_classes') === 'bytes' ? ['document_metadata', 'document_bytes'] : ['document_metadata'],
          classifications: [data.get('classification')], audiences: [data.get('audience')],
          fields, jurisdictions: [data.get('jurisdiction')], legal_basis: data.get('legal_basis'),
          agreement_ref: data.get('agreement_ref'), figure_measures: data.getAll('figure_measures')}
      }, 'Relationship proposed for review.');
    } catch (error) { status.textContent = error.message; }
  });
  byId('gsGrant').addEventListener('submit', event => {
    event.preventDefault(); const data = new FormData(event.target);
    try { act('POST', `/evidence/api/group/relationships/${encodeURIComponent(data.get('relationship_id'))}/grants`, {
      user_id: Number(data.get('user_id')), capability: data.get('capability'),
      review_due_at: iso(data.get('review_due_at')), expires_at: iso(data.get('expires_at'))
    }, 'Named access granted.'); } catch (error) { status.textContent = error.message; }
  });
  const reviewForm = byId('gsReviewGrant');
  const reviewDates = () => {
    const needed = reviewForm.elements.decision.value !== 'revoke';
    ['review_due_at', 'expires_at'].forEach(name => {
      reviewForm.elements[name].required = needed;
      reviewForm.elements[name].disabled = !needed;
    });
  };
  reviewForm.elements.decision.addEventListener('change', reviewDates);
  byId('gsReviewCancel').addEventListener('click', () => { reviewForm.hidden = true; reviewForm.reset(); });
  reviewForm.addEventListener('submit', async event => {
    event.preventDefault();
    const data = new FormData(reviewForm);
    const decision = data.get('decision');
    try {
      const saved = await act('POST', `/evidence/api/group/grants/${encodeURIComponent(data.get('grant_id'))}/review`, {
        decision, reason: data.get('reason'),
        review_due_at: decision === 'revoke' ? null : iso(data.get('review_due_at')),
        expires_at: decision === 'revoke' ? null : iso(data.get('expires_at'))
      }, 'Access review recorded.');
      if (saved) { reviewForm.hidden = true; reviewForm.reset(); }
    } catch (error) { status.textContent = error.message; }
  });
  byId('gsRightsForm').addEventListener('submit', event => {
    event.preventDefault(); const data = new FormData(event.target);
    act('POST', `/evidence/api/group/rights/${encodeURIComponent(data.get('evidence_id'))}`, {
      rights_state: data.get('rights_state'), permit_group_view: data.has('permit_group_view'),
      permit_group_download: data.has('permit_group_download'), basis: data.get('basis')
    }, 'Rights review recorded.');
  });
  byId('gsPublish').addEventListener('submit', event => {
    event.preventDefault(); const data = new FormData(event.target);
    const relation = workspace.relationships.find(row => String(row.id) === data.get('relationship_id'));
    if (!relation) { status.textContent = 'Choose an active relationship.'; return; }
    try { act('POST', `/evidence/api/group/relationships/${relation.id}/publications`, {
      evidence_id: Number(data.get('evidence_id')), classification: data.get('classification'),
      purpose: relation.purpose, expires_at: iso(data.get('expires_at'))
    }, 'Version released.'); } catch (error) { status.textContent = error.message; }
  });
  refresh().catch(error => { status.textContent = error.detail || 'Group sharing is unavailable.'; });
})();
