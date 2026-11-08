(() => {
  const modal = document.getElementById('uploadTplModal');
  const form = document.getElementById('tplUploadForm');
  if (!modal || !form) return;
  document.querySelector('[data-open-template-modal]')?.addEventListener('click', () => modal.classList.add('open'));
  document.querySelector('[data-close-template-modal]')?.addEventListener('click', () => modal.classList.remove('open'));
  modal.addEventListener('click', event => {
    if (event.target === modal) modal.classList.remove('open');
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const file = document.getElementById('tpl-file').files[0];
    if (!file) { showToast('Select a file', 'error'); return; }
    const body = new FormData();
    body.append('file', file);
    body.append('name', document.getElementById('tpl-name').value.trim());
    body.append('description', document.getElementById('tpl-desc').value.trim());
    body.append('doc_type', document.getElementById('tpl-doc-type').value);
    body.append('is_default', document.getElementById('tpl-default').value);
    const response = await fetch('/aria/api/templates', {method: 'POST', body});
    const data = await response.json();
    if (data.ok) {
      showToast('Template uploaded');
      setTimeout(() => location.reload(), 1000);
    } else {
      showToast(data.error || 'Failed', 'error');
    }
  });

  document.querySelectorAll('.js-delete-template').forEach(button => {
    button.addEventListener('click', async () => {
      const id = Number(button.dataset.templateId);
      if (!Number.isSafeInteger(id) || id < 1) return;
      if (!confirm('Delete template "' + button.dataset.templateName + '"? This cannot be undone.')) return;
      const response = await fetch('/aria/api/templates/' + id, {method: 'DELETE'});
      const data = await response.json();
      if (data.ok) {
        showToast('Template deleted');
        setTimeout(() => location.reload(), 800);
      } else {
        showToast(data.error || 'Failed', 'error');
      }
    });
  });
})();
