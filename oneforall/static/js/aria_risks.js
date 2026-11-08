(() => {
  const modal = document.getElementById('addRiskModal');
  const form = document.getElementById('addRiskForm');
  if (!modal || !form) return;
  document.querySelector('[data-open-risk-modal]')?.addEventListener('click', () => modal.classList.add('open'));
  document.querySelectorAll('[data-close-risk-modal]').forEach(button =>
    button.addEventListener('click', () => modal.classList.remove('open')));
  modal.addEventListener('click', event => {
    if (event.target === modal) modal.classList.remove('open');
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const response = await fetch('/aria/risks/add', {method: 'POST', body: new FormData(form)});
    const data = await response.json();
    if (data.ok) {
      showToast('Risk added');
      setTimeout(() => location.reload(), 1000);
    } else {
      showToast(data.error || 'Error adding risk', 'error');
    }
  });
})();
