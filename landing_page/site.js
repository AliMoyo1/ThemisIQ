/* Production-only lead form and consent controls for the static landing page. */
(() => {
  const form = document.getElementById('demoForm');
  const button = document.getElementById('demoBtn');
  const message = document.getElementById('demoMsg');
  const success = document.getElementById('demoSuccess');
  if (form && button && message && success) {
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      const name = form.elements.name.value.trim();
      const email = form.elements.email.value.trim();
      const company = form.elements.company.value.trim();
      if (!name || !email) {
        message.textContent = 'Please enter your name and work email.';
        return;
      }
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      message.textContent = 'Sending your request…';
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 15000);
      try {
        const response = await fetch('https://app.themisiq.net/api/demo-request', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({name, email, company, plan: ''}),
          signal: controller.signal
        });
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || 'Please try again.');
        form.hidden = true;
        success.hidden = false;
        document.getElementById('demoSuccessEmail').textContent = email;
        success.focus();
      } catch (error) {
        message.textContent = error.name === 'AbortError'
          ? 'The request timed out. Please try again or email hello@themisiq.net.'
          : (error.message && error.message !== 'Failed to fetch'
              ? error.message
              : 'Could not connect. Please email hello@themisiq.net.');
      } finally {
        window.clearTimeout(timeout);
        button.disabled = false;
        button.removeAttribute('aria-busy');
      }
    });
  }

  const banner = document.getElementById('cookieBanner');
  if (banner) {
    try {
      banner.hidden = Boolean(window.localStorage.getItem('cookie_consent'));
    } catch (_) {
      banner.hidden = false;
    }
    banner.querySelectorAll('[data-cookie-choice]').forEach(button => {
      button.addEventListener('click', () => {
        try { window.localStorage.setItem('cookie_consent', button.dataset.cookieChoice); } catch (_) {}
        banner.hidden = true;
      });
    });
  }
})();
