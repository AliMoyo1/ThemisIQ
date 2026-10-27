(() => {
  'use strict';

  const password = document.getElementById('password');
  const reveal = document.getElementById('pwToggle');
  if (password && reveal) {
    reveal.addEventListener('click', () => {
      const shown = password.type === 'password';
      password.type = shown ? 'text' : 'password';
      reveal.textContent = shown ? 'Hide' : 'Show';
      reveal.setAttribute('aria-label', shown ? 'Hide password' : 'Show password');
      reveal.setAttribute('aria-pressed', String(shown));
    });
  }

  const form = document.getElementById('loginForm');
  const submit = document.getElementById('submitBtn');
  const submitLabel = submit?.querySelector('.login-submit-label');
  const resetSubmit = () => {
    if (!submit) return;
    submit.disabled = false;
    submit.classList.remove('loading');
    submit.removeAttribute('aria-busy');
    if (submitLabel) submitLabel.textContent = 'Sign in';
  };
  form?.addEventListener('submit', () => {
    submit.disabled = true;
    submit.classList.add('loading');
    submit.setAttribute('aria-busy', 'true');
    if (submitLabel) submitLabel.textContent = 'Signing in';
    window.setTimeout(resetSubmit, 8000);
  });
  window.addEventListener('pageshow', resetSubmit);

  const video = document.getElementById('loginBackground');
  const toggle = document.getElementById('bgMotionToggle');
  if (!video || !toggle) return;

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const smallScreen = window.matchMedia('(max-width: 680px)');
  const saveData = Boolean(navigator.connection?.saveData);
  if (saveData) return;

  let userPaused = false;
  let started = false;
  function syncToggle() {
    toggle.textContent = userPaused ? 'Play background' : 'Pause background';
    toggle.setAttribute('aria-label', toggle.textContent + ' video');
    toggle.setAttribute('aria-pressed', String(!userPaused));
  }
  function showPoster() {
    video.classList.remove('is-ready');
    toggle.hidden = true;
  }
  async function playVideo() {
    if (document.hidden || userPaused || reduceMotion.matches || smallScreen.matches) return;
    try {
      await video.play();
    } catch {
      showPoster();
    }
  }
  video.addEventListener('playing', () => {
    video.classList.add('is-ready');
    toggle.hidden = false;
    syncToggle();
  });
  video.addEventListener('error', showPoster);
  toggle.addEventListener('click', () => {
    userPaused = !userPaused;
    if (userPaused) video.pause();
    else void playVideo();
    syncToggle();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) video.pause();
    else if (!started) start();
    else if (!userPaused) void playVideo();
  });
  reduceMotion.addEventListener?.('change', () => {
    if (reduceMotion.matches) {
      video.pause();
      showPoster();
    } else if (!started) {
      start();
    } else if (!userPaused) {
      void playVideo();
    }
  });
  smallScreen.addEventListener?.('change', () => {
    if (smallScreen.matches) {
      video.pause();
      toggle.hidden = true;
    } else if (!started) {
      start();
    } else if (!userPaused) {
      void playVideo();
    }
  });

  function start() {
    if (started || reduceMotion.matches || smallScreen.matches || document.hidden) return;
    const source = video.dataset.src;
    if (!source) return;
    video.src = source;
    started = true;
    void playVideo();
  }
  window.addEventListener('load', () => {
    if ('requestIdleCallback' in window) window.requestIdleCallback(start, {timeout: 1600});
    else window.setTimeout(start, 250);
  }, {once: true});
})();
