(function () {
  'use strict';
  const root = document.getElementById('groupSharing');
  if (!root) return;
  let workspace;
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
          else if (row.can_decide && caps[cap]) actions.appendChild(button(label, `decide:${kind}`, row.id));
        });
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
    const people = new Map(workspace.recipients.map(row => [row.id, row.full_name]));
    workspace.grants.forEach(row => {
      const box = text('article', '', 'gs-row');
      box.appendChild(text('strong', `${people.get(row.user_id) || 'Named person'} · ${row.capability}`));
      box.appendChild(text('small', `Review ${row.review_due_at} · expires ${row.expires_at}`));
      const actions = text('div', '', 'gs-actions');
      actions.appendChild(button('Revoke access', 'revoke-grant', row.id));
      box.appendChild(actions); target.appendChild(box);
    });
  }
  function renderDocuments() {
    const files = workspace.evidence.map(row => ({id: row.id, label: `${row.title} · v${row.version}`}));
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
    renderRelationships(); renderGrants(); renderDocuments();
  }
  async function act(method, path, body, success) {
    status.textContent = 'Saving…';
    try {
      await ApiClient.request(path, {method, body, actionId: 'group.sharing'});
      await refresh();
      status.textContent = success;
    } catch (error) {
      status.textContent = error.detail || error.message || 'The change could not be saved.';
    }
  }
  root.addEventListener('click', async event => {
    const control = event.target.closest('button[data-action]');
    if (!control) return;
    const id = encodeURIComponent(control.dataset.id);
    const action = control.dataset.action;
    if (action.startsWith('decide:')) {
      act('POST', `/evidence/api/group/relationships/${id}/decisions`, {kind: action.slice(7)}, 'Decision recorded.');
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
          agreement_ref: data.get('agreement_ref')}
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
