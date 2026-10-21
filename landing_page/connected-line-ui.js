/* Wires the hero's controls to the connected line scene (connected-line.js). */
import { startConnectedLine, STATIONS } from './connected-line.js';

const root = document.getElementById('hero-visual');

function webglAvailable() {
  try {
    const c = document.createElement('canvas');
    return !!(window.WebGLRenderingContext && (c.getContext('webgl2') || c.getContext('webgl')));
  } catch (e) {
    return false;
  }
}

function fallback() {
  root.classList.add('is-fallback');
  root.querySelector('.cl-fallback').hidden = false;
  root.querySelector('.cl-loading').classList.add('done');
}

if (root && root.classList.contains('connected-line')) {
  if (!webglAvailable()) fallback();
  else start();
}

function start() {
  const tooltip = root.querySelector('.cl-tooltip');
  const stageEl = root.querySelector('#cl-stage');
  const moduleEl = root.querySelector('#cl-module');
  const stepEl = root.querySelector('#cl-step');
  const track = root.querySelector('.cl-track i');
  const hint = root.querySelector('.cl-hint');
  const playButton = root.querySelector('#cl-play');
  const pressed = (selector, attr, value) =>
    root.querySelectorAll(selector).forEach(b => b.setAttribute('aria-pressed', String(b.dataset[attr] === value)));

  startConnectedLine(root, {
    onReady: () => root.querySelector('.cl-loading').classList.add('done'),
    onError: fallback,
    onState: ({ mode, camera, playing }) => {
      pressed('[data-cl-mode]', 'clMode', mode);
      pressed('[data-cl-camera]', 'clCamera', camera);
      root.classList.toggle('is-incident', mode === 'incident');
      playButton.setAttribute('aria-pressed', String(!playing));
      playButton.setAttribute('aria-label', playing ? 'Pause the line' : 'Play the line');
      playButton.querySelector('.cl-pause').hidden = !playing;
      playButton.querySelector('.cl-resume').hidden = playing;
    },
    onStage: (index, station, siloed) => {
      stepEl.textContent = `${String(index + 1).padStart(2, '0')} / ${String(STATIONS.length).padStart(2, '0')}`;
      stageEl.textContent = station.stage;
      moduleEl.textContent = station.name;
      root.style.setProperty('--cl-stage-ink', station.accent);
      root.style.setProperty('--cl-stage-light', station.ink);
      root.classList.toggle('is-siloed', siloed);
      root.querySelector('.cl-silo-note').textContent = `Siloed: stopped in ${station.name}. Nothing reaches the next module.`;
    },
    onProgress: phase => { track.style.width = `${Math.round(phase * 1000) / 10}%`; },
    onHover: info => {
      tooltip.classList.toggle('visible', !!info);
      if (!info) return;
      tooltip.querySelector('strong').textContent = '';
      const n = document.createElement('span');
      n.textContent = String(info.index + 1).padStart(2, '0');
      tooltip.querySelector('strong').append(n, info.name);
      tooltip.querySelector('p').textContent = info.detail;
      tooltip.style.left = `${Math.min(info.width - 250, Math.max(8, info.x + 16))}px`;
      tooltip.style.top = `${Math.max(8, Math.min(info.height - 110, info.y - 70))}px`;
    },
    onEngage: on => {
      hint.textContent = on ? 'Scroll or pinch to zoom · Drag to rotate · Click a station to focus' : 'Drag to rotate · Click the scene, then scroll to zoom';
    },
  });
  const api = root.connectedLine;
  if (!api) return;
  root.querySelectorAll('[data-cl-mode]').forEach(b => b.addEventListener('click', () => api.setMode(b.dataset.clMode)));
  root.querySelectorAll('[data-cl-camera]').forEach(b => b.addEventListener('click', () => api.setCamera(b.dataset.clCamera)));
  root.querySelector('#cl-zoom-in').addEventListener('click', () => api.zoom(0.82));
  root.querySelector('#cl-zoom-out').addEventListener('click', () => api.zoom(1.22));
  playButton.addEventListener('click', () => (playButton.getAttribute('aria-pressed') === 'true' ? api.play() : api.pause()));
}
