(function () {
  const value = document.getElementById('ccAttentionOpen');
  const note = document.getElementById('ccAttentionNote');
  if (!value || !note) return;
  fetch('/api/command-centre/attention', { credentials: 'same-origin', cache: 'no-store' })
    .then(response => {
      if (!response.ok) throw new Error('Attention count unavailable');
      return response.json();
    })
    .then(data => {
      if (data.state === 'not_measured') {
        note.textContent = 'No permitted sources to check.';
        return;
      }
      if (!Number.isInteger(data.open) || data.open < 0) throw new Error('Invalid count');
      value.textContent = data.state === 'partial' ? '≥' + data.open : String(data.open);
      note.textContent = data.state === 'partial'
        ? 'Partial count. Some checks could not be read; open the list for details.'
        : 'Open issues in the records you can view.';
    })
    .catch(() => {
      value.textContent = '—';
      note.textContent = 'Could not read issues just now. Open the list to retry.';
    });
})();
