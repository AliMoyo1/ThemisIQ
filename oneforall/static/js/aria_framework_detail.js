async function updateControl(id, data) {
  id = Number(id);
  if (!Number.isSafeInteger(id) || id < 1) return;
  const form = new FormData();
  Object.entries(data).forEach(([k,v]) => form.append(k, v));
  const res = await fetch('/aria/control/' + id + '/update', { method:'POST', body: form });
  const json = await res.json();
  if (json.ok) showToast('Control updated');
  else showToast(json.error || 'Error updating control', 'error');
}
function updateStatus(sel) { updateControl(sel.dataset.id, { status: sel.value }); }
function updatePriority(sel) { updateControl(sel.dataset.id, { priority: sel.value }); }
function updateOwner(input, id) { updateControl(id, { owner: input.value }); }
function updateDate(input, id) { updateControl(id, { target_date: input.value }); }

function openEditModal(id, name, notes, evid, ver, reviewDate) {
  document.getElementById('editId').value = id;
  document.getElementById('editName').value = name;
  document.getElementById('editNotes').value = notes;
  document.getElementById('editEvidRef').value = evid;
  document.getElementById('editVersion').value = ver;
  document.getElementById('editReviewDate').value = reviewDate;
  document.getElementById('editModal').classList.add('open');
}
document.querySelectorAll('.js-edit-control').forEach(function (button) {
  button.addEventListener('click', function () {
    openEditModal(Number(button.dataset.controlId), button.dataset.controlName,
      button.dataset.controlNotes, button.dataset.controlEvidence,
      button.dataset.controlVersion, button.dataset.controlReviewDate);
  });
});
function closeModal() { document.getElementById('editModal').classList.remove('open'); }
async function saveModal() {
  const id = document.getElementById('editId').value;
  await updateControl(id, {
    notes: document.getElementById('editNotes').value,
    evidence_ref: document.getElementById('editEvidRef').value,
    version: document.getElementById('editVersion').value,
    review_date: document.getElementById('editReviewDate').value,
    document_title: document.getElementById('editDocTitle').value,
  });
  closeModal();
}
function applyFilters() {
  const s = document.getElementById('statusFilter').value;
  const p = document.getElementById('priorityFilter').value;
  const c = document.getElementById('categoryFilter').value;
  const q = document.getElementById('searchInput').value;
  const params = new URLSearchParams();
  if (s) params.set('status', s);
  if (p) params.set('priority', p);
  if (c) params.set('category', c);
  if (q) params.set('search', q);
  window.location.search = params.toString();
}
document.getElementById('searchInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') applyFilters();
});
document.getElementById('editModal').addEventListener('click', e => {
  if (e.target === document.getElementById('editModal')) closeModal();
});
for (const id of ['statusFilter', 'priorityFilter', 'categoryFilter']) {
  document.getElementById(id)?.addEventListener('change', applyFilters);
}
document.getElementById('applyControlFilters')?.addEventListener('click', applyFilters);
document.querySelectorAll('.js-control-status').forEach(select => {
  select.addEventListener('change', () => updateStatus(select));
});
document.querySelectorAll('.js-control-priority').forEach(select => {
  select.addEventListener('change', () => updatePriority(select));
});
document.querySelectorAll('.js-control-owner').forEach(input => {
  input.addEventListener('blur', () => updateOwner(input, input.dataset.controlId));
});
document.querySelectorAll('.js-control-date').forEach(input => {
  input.addEventListener('change', () => updateDate(input, input.dataset.controlId));
});
document.querySelectorAll('.js-close-control-modal').forEach(button => {
  button.addEventListener('click', closeModal);
});
document.getElementById('saveControlModal')?.addEventListener('click', saveModal);
