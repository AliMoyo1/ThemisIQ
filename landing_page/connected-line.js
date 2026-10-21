/* The connected line: an interactive 3D machine for the landing page hero.
 *
 * Eight stations stand on one metal plate, joined by a conveyor belt: the seven ThemisIQ modules and Reports, where
 * the cycle completes. An incident travels the belt through every station and changes as each one picks it up. Modes:
 * Assembled, Cutaway (the shells are cut open at deck height), Stations (spread apart with labels), One incident (the
 * camera follows a single incident) and Silos (walls rise between the stations and the belt stops). Cameras: Overview,
 * Side, Top, Station and Flight. Drag to rotate; click into the scene, then scroll or pinch to zoom.
 *
 * Adapted from the Agentic Factory 3D component (MIT, procedural three.js: no models, no images). Its plate, belt,
 * lighting, modes, cameras and four of its machines (Engine, Admin, Cabinet, Storefront) are reused as stations.
 * Illustrative only. three.js 0.170.0 is served from ./vendor/three (MIT, see its LICENSE).
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const TAU = Math.PI * 2;

// The incident's route. `machine` is which factory machine the station reuses; `pos` is its place on the plate.
// Colours are the app's own module colours (templates/base_shell.html): `glow`/`accent` is the module's --accent,
// `light`/`ink` its --accent-light, used where text sits on the dark station screens. Reports takes the platform colour.
export const STATIONS = [
  { id: 'sentinel', name: 'Privacy', code: 'SENTINEL', machine: 'cabinet', pos: [-4.95, -2.45], glow: 0x3b5bdb, accent: '#3b5bdb', light: 0x74a0e8, ink: '#74a0e8',
    stage: 'Breach confirmed', detail: 'Privacy records the breach and the notice duties for each jurisdiction.',
    screen: { title: 'BREACH CASES', rows: [['Customer data exposure', 'Confirmed'], ['Vendor portal access', 'Assessing'], ['Mis-sent statement', 'Closed']] } },
  { id: 'bcm', name: 'Resilience', code: 'BCM', machine: 'admin', pos: [-1.65, -2.55], glow: 0x3d4660, accent: '#3d4660', light: 0x6e7a9a, ink: '#6e7a9a',
    stage: 'Incident opened', detail: 'Resilience opens the incident and activates the plan that covers it.',
    screen: { title: 'INCIDENT RESPONSE', rows: [['Contain the exposure', 'In progress'], ['Notify stakeholders', 'Queued'], ['Restore the service', 'Queued']] } },
  { id: 'erm', name: 'Enterprise risk', code: 'ERM', machine: 'engine', pos: [1.65, -2.55], glow: 0x881337, accent: '#881337', light: 0xbe123c, ink: '#be123c',
    stage: 'Obligation tracked', detail: 'Enterprise risk tracks the regulatory obligation as a risk against appetite.',
    screen: { title: 'OBLIGATION', lines: ['Regulatory notice', 'tracked as a risk.', 'Appetite checked.', 'Owner assigned.'] } },
  { id: 'orm', name: 'Operations risk', code: 'ORM', machine: 'cabinet', pos: [4.95, -2.45], glow: 0x7c3a0a, accent: '#7c3a0a', light: 0xbe6428, ink: '#be6428',
    stage: 'Event logged', detail: 'Operations risk logs the event and its operational impact.',
    screen: { title: 'OPERATIONAL EVENTS', rows: [['Data exposure', 'Logged'], ['Process failure', 'In review'], ['Near miss', 'Closed']] } },
  { id: 'grid', name: 'Audit', code: 'GRID', machine: 'admin', pos: [6.3, 0.35], glow: 0x059669, accent: '#059669', light: 0x34d399, ink: '#34d399',
    stage: 'Audit review', detail: 'Audit reviews what happened and raises a finding with a corrective action.',
    screen: { title: 'AUDIT REVIEW', rows: [['Access control test', 'Testing'], ['Incident log check', 'Queued'], ['Finding and action', 'Queued']] } },
  { id: 'aria', name: 'Governance', code: 'ARIA', machine: 'engine', pos: [3.55, 2.7], glow: 0x7d6527, accent: '#7d6527', light: 0xc4a656, ink: '#c4a656',
    stage: 'Controls rechecked', detail: 'Governance rechecks the controls and revises the policy behind them.',
    screen: { title: 'POLICY REVIEW', lines: ['Access policy', 'revision drafted.', 'Control owners', 'asked to confirm.'] } },
  { id: 'aig', name: 'AI Governance', code: 'AI GOV', machine: 'cabinet', pos: [0.35, 2.85], glow: 0x0f766e, accent: '#0f766e', light: 0x2dd4bf, ink: '#2dd4bf',
    stage: 'AI use re-review', detail: 'AI Governance flags the AI uses that touch the affected data for re-review.',
    screen: { title: 'AI USES', rows: [['Ticket summarizer', 'Re-review'], ['Fraud scoring', 'Approved'], ['Chat assistant', 'Approved']] } },
  { id: 'reports', name: 'Reports', code: 'REPORTS', machine: 'storefront', pos: [-3.65, 2.7], glow: 0x1e3a8a, accent: '#1e3a8a', light: 0x60a5fa, ink: '#60a5fa',
    stage: 'Cycle complete', detail: 'Reports bring it together for leadership, signed off by an independent reviewer.',
    screen: { title: 'INCIDENT REPORT' } },
];

const THEMES = {
  sage: { base: 0x34433d, body: 0x3c4c46, edge: 0x7e8c84, dark: 0x141c1a, ivory: 0xe3e7df, signal: 0xc89a3a, silo: 0x326e62,
          drafting: 0x5f7268, shadow: 0.2, hemiSky: 0xe3efe6, hemiGround: 0x2a2a20 },
  dusk: { base: 0x1f2b39, body: 0x283747, edge: 0x5f7084, dark: 0x0c131c, ivory: 0xd6dce3, signal: 0xe5cb82, silo: 0x9bc5fc,
          drafting: 0x6c88a6, shadow: 0.34, hemiSky: 0xcfe0f4, hemiGround: 0x101820 },
};

export function startConnectedLine(root, ui = {}) {
  const cleanups = [];
  const listen = (target, type, fn, opts) => { target.addEventListener(type, fn, opts); cleanups.push(() => target.removeEventListener(type, fn, opts)); };
  const host = root.querySelector('.cl-scene');
  const labelsHost = root.querySelector('.cl-labels');
  const fontFamily = getComputedStyle(document.body).fontFamily || 'sans-serif';
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const coarse = matchMedia('(pointer:coarse)').matches;
  const themeName = () => (document.documentElement.dataset.theme === 'dusk' ? 'dusk' : 'sage');
  let theme = THEMES[themeName()];
  const W = () => host.clientWidth, H = () => host.clientHeight;

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  } catch (e) {
    ui.onError?.();
    return () => {};
  }
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(devicePixelRatio, W() < 900 ? 1.5 : 1.75));
  renderer.setSize(W(), H());
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.12;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.localClippingEnabled = true;
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(33, W() / Math.max(1, H()), 0.1, 160);
  const controls = new OrbitControls(camera, renderer.domElement);
  Object.assign(controls, { enableDamping: true, dampingFactor: 0.065, enablePan: false, minDistance: 7, maxDistance: 60,
    minPolarAngle: 0.09, maxPolarAngle: Math.PI * 0.475, rotateSpeed: 0.48, zoomSpeed: 0.7 });
  // In a landing page the wheel and the finger belong to the page until the visitor clicks into the scene.
  let engaged = false;
  function engage(on) {
    engaged = on;
    controls.enableZoom = on;
    if (coarse) controls.enableRotate = on;
    root.classList.toggle('is-engaged', on);
    ui.onEngage?.(on);
  }
  engage(false);
  if (!coarse) controls.enableRotate = true;

  const pmrem = new THREE.PMREMGenerator(renderer), room = new RoomEnvironment();
  const env = pmrem.fromScene(room, 0.04);
  scene.environment = env.texture; scene.environmentIntensity = 0.62;
  room.dispose(); pmrem.dispose();
  const hemi = new THREE.HemisphereLight(theme.hemiSky, theme.hemiGround, 2); scene.add(hemi);
  const key = new THREE.DirectionalLight(0xfff1d8, 4.2);
  key.position.set(-4, 12, 7); key.castShadow = true; key.shadow.mapSize.set(2048, 2048);
  Object.assign(key.shadow.camera, { left: -11, right: 11, top: 9, bottom: -9, near: 0.5, far: 35 });
  key.shadow.normalBias = 0.035; key.shadow.bias = -0.0002; key.shadow.radius = 4; scene.add(key);
  const rim = new THREE.DirectionalLight(0xc4d4ed, 3.1); rim.position.set(3, 7, -8); scene.add(rim);
  const warm = new THREE.PointLight(0xffd88a, 24, 20, 2); warm.position.set(-4, 5, 3); scene.add(warm);
  const front = new THREE.DirectionalLight(0xffffff, 1); front.position.set(5, 3, 10); scene.add(front);

  const mat = (color, metalness = 0.1, roughness = 0.4, extra = {}) => new THREE.MeshStandardMaterial({ color, metalness, roughness, ...extra });
  const M = {
    body: mat(theme.body, 0.75, 0.29), base: mat(theme.base, 0.85, 0.32), edge: mat(theme.edge, 0.85, 0.24),
    chrome: mat(0xc3cad0, 0.92, 0.18), dark: mat(theme.dark, 0.45, 0.38), rubber: mat(0x0b1015, 0.1, 0.6),
    ivory: mat(theme.ivory, 0.48, 0.26), copper: mat(0xc57e45, 0.85, 0.3),
    signal: mat(theme.signal, 0.2, 0.25, { emissive: theme.signal, emissiveIntensity: 1.5 }),
    // Silo walls take the landing page's main colour (--accent in styles.css).
    wall: mat(theme.silo, 0.2, 0.2, { transparent: true, opacity: 0.5, depthWrite: false, side: THREE.DoubleSide, emissive: theme.silo, emissiveIntensity: 0.35 }),
    wallEdge: mat(theme.silo, 0.2, 0.3, { emissive: theme.silo, emissiveIntensity: 0.9 }),
  };
  // Station shells are cut open at deck height in Cutaway mode.
  const cutPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 10);
  const shellMaterials = [];
  function shell(m) {
    const s = m.clone(); s.clippingPlanes = [cutPlane]; s.clipShadows = true; s.side = THREE.DoubleSide; shellMaterials.push({ s, m }); return s;
  }
  const S = { body: shell(M.body), ivory: shell(M.ivory) };
  const tintWall = () => M.wall.color.setHex(theme.silo).lerp(new THREE.Color(0xffffff), 0.45);
  tintWall();

  const geometries = new Map();
  function boxGeo(w, h, d, r = 0.04) {
    const k = `b${w},${h},${d},${r}`;
    if (!geometries.has(k)) geometries.set(k, r ? new RoundedBoxGeometry(w, h, d, 2, Math.min(r, w / 3, h / 3, d / 3)) : new THREE.BoxGeometry(w, h, d));
    return geometries.get(k);
  }
  function box(parent, w, h, d, x, y, z, m = M.body, r = 0.04) {
    const o = new THREE.Mesh(boxGeo(w, h, d, r), m); o.position.set(x, y, z); o.castShadow = true; o.receiveShadow = true; parent.add(o); return o;
  }
  function cyl(parent, r, h, x, y, z, m = M.chrome, r2 = r, segments = 24) {
    const k = `c${r},${r2},${h},${segments}`;
    if (!geometries.has(k)) geometries.set(k, new THREE.CylinderGeometry(r, r2, h, segments));
    const o = new THREE.Mesh(geometries.get(k), m); o.position.set(x, y, z); o.castShadow = true; o.receiveShadow = true; parent.add(o); return o;
  }
  function ball(parent, r, x, y, z, m = M.chrome) {
    const k = `s${r}`; if (!geometries.has(k)) geometries.set(k, new THREE.SphereGeometry(r, 12, 8));
    const o = new THREE.Mesh(geometries.get(k), m); o.position.set(x, y, z); parent.add(o); return o;
  }
  function tube(parent, pts, r, m = M.chrome) {
    const curve = new THREE.CatmullRomCurve3(pts.map(p => new THREE.Vector3(...p)));
    const o = new THREE.Mesh(new THREE.TubeGeometry(curve, Math.max(12, pts.length * 7), r, 8, false), m); o.castShadow = true; parent.add(o); return o;
  }
  function screw(parent, x, y, z) { cyl(parent, 0.055, 0.026, x, y, z, M.chrome, undefined, 12); box(parent, 0.068, 0.005, 0.009, x, y + 0.014, z, M.dark, 0); }
  function canvasTexture(w, h, draw) {
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const ctx = c.getContext('2d'); draw(ctx, w, h);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = Math.min(4, renderer.capabilities.getMaxAnisotropy());
    return { texture: t, ctx };
  }
  function print(ctx, txt, x, y, size = 20, color = '#f2f4ee', weight = 500) { ctx.fillStyle = color; ctx.font = `${weight} ${size}px ${fontFamily}`; ctx.fillText(txt, x, y); }
  function screen(parent, w, h, x, y, z, tex) {
    const o = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex.texture || tex, toneMapped: false }));
    o.position.set(x, y, z); parent.add(o); return o;
  }

  const machine = new THREE.Group(); scene.add(machine);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), new THREE.ShadowMaterial({ opacity: theme.shadow }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -0.43; floor.receiveShadow = true; scene.add(floor);

  // The plate.
  const PW = 15.6, PD = 9.4;
  box(machine, PW, 0.38, PD, 0, -0.09, 0, M.base, 0.17);
  box(machine, PW - 0.2, 0.055, PD - 0.17, 0, 0.13, 0, M.edge, 0.11);
  box(machine, PW - 0.31, 0.09, PD - 0.29, 0, 0.19, 0, M.body, 0.1);
  box(machine, PW - 0.9, 0.026, 0.032, 0, -0.17, PD / 2 + 0.01, M.signal, 0.01);
  for (const x of [-(PW / 2 - 0.8), PW / 2 - 0.8]) for (const z of [-(PD / 2 - 0.8), PD / 2 - 0.8]) {
    cyl(machine, 0.39, 0.25, x, -0.31, z, M.rubber); cyl(machine, 0.29, 0.09, x, -0.4, z, M.dark); screw(machine, x, 0.253, z);
  }
  const engraving = canvasTexture(1536, 150, (c, w, h) => {
    c.fillStyle = '#20302b'; c.fillRect(0, 0, w, h); c.strokeStyle = '#4d5c55'; c.lineWidth = 2; c.strokeRect(2, 2, w - 4, h - 4);
    print(c, 'THEMISIQ', 45, 70, 40, '#e3e7df', 650);
    print(c, '·  every module on one line', 300, 70, 34, '#b8c2bc', 450);
    print(c, 'CONNECTED GRC    /    NO SILOS', 47, 122, 19, '#7d8c84', 500);
  });
  const plate = screen(machine, 5.4, 0.53, 4.6, 0.25, PD / 2 - 0.3, engraving); plate.rotation.x = -Math.PI / 2;

  // Drafting rings around the plate.
  const drafting = new THREE.Group(); scene.add(drafting);
  const draftMat = new THREE.LineBasicMaterial({ color: theme.drafting, transparent: true, opacity: 0.16 });
  const dp = [];
  for (const r of [8.6, 9.2]) for (let i = 0; i < 120; i++) for (const j of [i, i + 1]) { const a = (j / 120) * TAU; dp.push(new THREE.Vector3(Math.cos(a) * r, -0.4, Math.sin(a) * r * 0.66)); }
  for (let i = 0; i < 56; i++) { const a = (i / 56) * TAU, r = 9.2, l = i % 4 === 0 ? 0.18 : 0.08; dp.push(new THREE.Vector3(Math.cos(a) * r, -0.395, Math.sin(a) * r * 0.66), new THREE.Vector3(Math.cos(a) * (r + l), -0.395, Math.sin(a) * (r + l) * 0.66)); }
  drafting.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(dp), draftMat));

  // Stations.
  const stations = [], gears = [], reels = [], printheads = [], outputs = [], toggles = [], incomings = [], queues = [], posts = [];
  function gear(parent, x, y, z, r = 0.3) {
    const g = new THREE.Group(); g.position.set(x, y, z); parent.add(g);
    cyl(g, r, 0.09, 0, 0, 0, M.copper); cyl(g, r * 0.66, 0.105, 0, 0, 0, M.dark); cyl(g, r * 0.22, 0.14, 0, 0, 0, M.chrome);
    for (let i = 0; i < 12; i++) { const a = (i / 12) * TAU; const b = box(g, r * 0.26, 0.085, r * 0.2, Math.cos(a) * r, 0, Math.sin(a) * r, M.copper, 0.008); b.rotation.y = -a; }
    g.userData.moving = true; gears.push(g); return g;
  }
  function listScreen(st, w, h) {
    return canvasTexture(w, h, (c) => {
      c.fillStyle = '#121b1f'; c.fillRect(0, 0, w, h);
      print(c, st.screen.title, 26, 48, 24, '#e6ebe4', 600);
      print(c, st.code, w - 26 - st.code.length * 13, 48, 18, st.ink, 600);
      const rowH = (h - 110) / 3;
      st.screen.rows.forEach(([label, state], i) => {
        const y = 74 + i * (rowH + 8);
        c.fillStyle = '#1f2c31'; c.beginPath(); c.roundRect(20, y, w - 40, rowH, 8); c.fill();
        c.fillStyle = i === 0 ? st.ink : '#5f716c'; c.beginPath(); c.arc(50, y + rowH / 2, 13, 0, TAU); c.fill();
        print(c, label, 78, y + rowH / 2 - 4, 21, '#dfe4dc', 550);
        print(c, state.toUpperCase(), 78, y + rowH / 2 + 22, 14, i === 0 ? st.ink : '#8a9b95', 600);
      });
    });
  }
  function buildCabinet(g, st) {
    box(g, 1.75, 1.77, 1.02, 0, 1.24, -0.13, S.body, 0.12);
    box(g, 1.58, 0.13, 1.09, 0, 2.16, -0.13, shell(mat(st.glow, 0.5, 0.3)), 0.04);
    box(g, 1.47, 1.38, 0.055, 0, 1.31, 0.405, M.dark, 0.025);
    screen(g, 1.31, 1.255, 0, 1.37, 0.44, listScreen(st, 480, 460));
    box(g, 1.27, 0.075, 0.29, 0, 0.57, 0.55, M.chrome, 0.02);
    for (let i = 0; i < 3; i++) box(g, 1.15, 0.021, 0.12, 0, 0.58 + i * 0.15, -0.35, M.copper, 0.006);
    tube(g, [[0.69, 0.43, -0.2], [0.89, 0.65, -0.2], [0.89, 1.8, -0.2], [0.65, 1.99, -0.2]], 0.033, M.chrome);
    const incoming = new THREE.Group(); incoming.userData.moving = true; g.add(incoming);
    box(incoming, 0.86, 0.42, 0.043, 0, 0, 0, M.signal, 0.035);
    screen(incoming, 0.82, 0.39, 0, 0, 0.026, canvasTexture(432, 204, (c, w, h) => {
      c.fillStyle = st.accent; c.fillRect(0, 0, w, h);
      print(c, st.stage, 26, 92, 36, '#ffffff', 650);
      print(c, `${st.name}  +`, 26, 144, 24, 'rgba(255,255,255,.82)', 500);
    }));
    incomings.push(incoming);
  }
  function buildAdmin(g, st) {
    box(g, 1.9, 0.66, 1.36, 0, 0.67, -0.04, S.body, 0.11);
    const top = new THREE.Group(); top.position.set(0, 1.01, -0.08); top.rotation.x = -0.32; g.add(top);
    box(top, 1.76, 0.12, 1.27, 0, 0, 0, S.ivory, 0.04);
    const q = canvasTexture(640, 340, () => {}); queues.push({ q, st });
    const s = screen(top, 1.53, 0.79, 0, 0.067, -0.17, q); s.rotation.x = -Math.PI / 2;
    for (let i = 0; i < 4; i++) {
      const x = -0.57 + i * 0.38;
      cyl(top, 0.074, 0.035, x, 0.1, 0.45, M.dark);
      const t = cyl(top, 0.025, 0.15, x, 0.19, 0.45, M.chrome); t.rotation.x = -0.4; t.userData.moving = true; toggles.push(t);
      ball(top, 0.04, x, 0.275, 0.421, M.ivory);
    }
    cyl(g, 0.075, 0.06, 0.77, 1.05, -0.62, mat(st.glow, 0.1, 0.3, { emissive: st.light, emissiveIntensity: 0.8 }));
    for (let i = 0; i < 7; i++) box(g, 0.55, 0.027, 0.02, 0, 0.46 + i * 0.05, 0.655, M.dark, 0.003);
  }
  function drawQueue({ q, st }, t) {
    const c = q.ctx;
    c.fillStyle = '#111b20'; c.fillRect(0, 0, 640, 340);
    print(c, st.screen.title, 25, 45, 21, '#b9c4bf', 600);
    print(c, st.code, 640 - 25 - st.code.length * 12, 45, 18, st.ink, 600);
    st.screen.rows.forEach(([label, state], i) => {
      const y = 74 + i * 76;
      c.fillStyle = '#202c30'; c.beginPath(); c.roundRect(21, y, 598, 61, 6); c.fill();
      c.fillStyle = i === 0 ? st.ink : '#626f69'; c.fillRect(34, y + 10, 27, 41);
      print(c, label, 77, y + 29, 19, '#d4d8cc');
      print(c, state.toUpperCase(), 77, y + 49, 11, i === 0 ? st.ink : '#81948f');
      c.fillStyle = '#334348'; c.fillRect(377, y + 26, 214, 7);
      c.fillStyle = i === 0 ? st.ink : '#607475';
      c.fillRect(377, y + 26, i === 0 ? ((t * 0.15) % 1) * 214 : 41 + i * 27, 7);
    });
    q.texture.needsUpdate = true;
  }
  function buildEngine(g, st) {
    box(g, 1.74, 0.62, 1.33, 0, 0.65, -0.05, S.ivory, 0.13);
    box(g, 1.5, 0.1, 1.16, 0, 0.99, -0.04, S.body, 0.025);
    for (const x of [-0.68, 0.68]) { cyl(g, 0.065, 1.73, x, 1.35, -0.18, M.chrome); box(g, 0.22, 1.8, 0.22, x, 1.37, -0.44, S.ivory, 0.035); }
    box(g, 1.82, 0.27, 0.4, 0, 2.28, -0.35, shell(mat(st.glow, 0.5, 0.3)), 0.045);
    box(g, 1.55, 0.06, 0.06, 0, 2.13, -0.115, M.chrome, 0.01);
    const head = new THREE.Group(); g.add(head); head.position.set(0, 1.9, -0.08); head.userData.moving = true;
    box(head, 0.45, 0.36, 0.44, 0, 0, 0, M.body, 0.05); cyl(head, 0.11, 0.13, 0, -0.24, 0.03, M.chrome, 0.04);
    box(head, 0.24, 0.045, 0.022, 0, 0.09, 0.23, M.signal, 0.01);
    printheads.push(head);
    tube(g, [[-0.68, 2.1, -0.35], [-0.42, 2.52, -0.4], [0.25, 2.5, -0.4], [0.35, 2.01, -0.12]], 0.032, M.dark);
    for (const [x, y] of [[-1.03, 1.82], [-0.94, 2.78]]) {
      const reel = new THREE.Group(); reel.position.set(x, y, -0.48); g.add(reel); reel.userData.moving = true;
      const core = cyl(reel, 0.4, 0.22, 0, 0, 0, M.dark); core.rotation.x = Math.PI / 2;
      for (const z of [-0.14, 0.14]) { const d = cyl(reel, 0.46, 0.045, 0, 0, z, M.chrome); d.rotation.x = Math.PI / 2; }
      const axle = cyl(reel, 0.095, 0.37, 0, 0, 0, mat(st.glow, 0.5, 0.3)); axle.rotation.x = Math.PI / 2;
      reels.push(reel);
    }
    const doc = canvasTexture(384, 640, () => {});
    const out = new THREE.Group(); out.userData.moving = true; g.add(out);
    box(out, 0.62, 1.08, 0.055, 0, 1.36, 0.61, M.dark, 0.035); screen(out, 0.56, 0.98, 0, 1.36, 0.641, doc);
    outputs.push({ group: out, doc, st });
    box(g, 1.14, 0.12, 0.2, 0, 0.83, 0.66, M.dark, 0.025);
    for (const x of [-0.42, 0.42]) { const r = cyl(g, 0.115, 0.18, x, 0.92, 0.6, M.chrome); r.rotation.z = Math.PI / 2; }
  }
  function drawDoc({ doc, st }, t) {
    const c = doc.ctx, w = 384;
    c.fillStyle = '#f2f1ea'; c.fillRect(0, 0, w, 640);
    c.fillStyle = st.accent; c.fillRect(0, 0, w, 120);
    print(c, st.code, 26, 52, 26, '#ffffff', 700); print(c, st.screen.title, 26, 94, 22, 'rgba(255,255,255,.88)', 600);
    const n = Math.floor(t * 0.7) % st.screen.lines.length;
    for (let i = 0; i < 2; i++) print(c, st.screen.lines[(n + i) % st.screen.lines.length], 26, 190 + i * 44, 26, '#27342f', 550);
    for (let i = 0; i < 6; i++) { c.fillStyle = '#c9cfc6'; c.fillRect(26, 300 + i * 28, 300 - (i % 3) * 50, 8); }
    c.fillStyle = st.accent; c.fillRect(26, 600, Math.max(10, ((t * 0.13) % 1) * 330), 6);
    doc.texture.needsUpdate = true;
  }
  // Reports: the factory's Storefront screen, showing the finished incident report.
  let reportTex = null;
  function buildStorefront(g, st) {
    box(g, 1.35, 0.18, 0.88, 0, 0.44, 0, S.ivory, 0.045);
    cyl(g, 0.095, 1.04, 0, 0.93, -0.31, M.chrome);
    box(g, 0.56, 0.91, 0.14, 0, 0.99, -0.34, S.body, 0.04);
    box(g, 2.42, 1.72, 0.2, 0, 1.94, -0.17, S.ivory, 0.08);
    box(g, 2.28, 1.59, 0.1, 0, 1.94, -0.044, M.dark, 0.045);
    reportTex = canvasTexture(896, 592, () => {});
    screen(g, 2.16, 1.43, 0, 1.95, 0.011, reportTex);
    ball(g, 0.024, 0, 2.747, -0.05, M.dark);
    box(g, 0.21, 0.019, 0.008, 0, 1.149, 0.013, M.signal, 0.003);
    const post = new THREE.Group(); post.userData.moving = true; g.add(post);
    box(post, 0.59, 0.77, 0.045, 0.94, 0.81, 0.55, M.ivory, 0.025);
    screen(post, 0.55, 0.72, 0.94, 0.81, 0.575, canvasTexture(220, 290, (c, w, h) => {
      c.fillStyle = '#f4f1ea'; c.fillRect(0, 0, w, h);
      c.fillStyle = st.accent; c.fillRect(15, 16, 190, 120);
      print(c, 'SIGNED OFF', 17, 175, 22, '#283030', 650);
      print(c, 'Independent', 17, 205, 17, '#55605a'); print(c, 'reviewer', 17, 228, 17, '#55605a');
      c.fillStyle = '#b0b5b0'; c.fillRect(17, 250, 153, 6);
    }));
    posts.push(post);
  }
  function drawReport(progress) {
    if (!reportTex) return;
    const c = reportTex.ctx, w = 896, h = 592;
    c.fillStyle = '#edece3'; c.fillRect(0, 0, w, h);
    c.fillStyle = '#dedfd7'; c.fillRect(0, 0, w, 56);
    c.fillStyle = '#adaeaa'; for (let i = 0; i < 3; i++) { c.beginPath(); c.arc(26 + i * 19, 27, 4, 0, TAU); c.fill(); }
    print(c, 'app.themisiq.net/reports', 90, 34, 16, '#6a7271');
    print(c, 'INCIDENT REPORT', 33, 104, 24, '#22282b', 700);
    print(c, 'Customer data exposure', 33, 140, 20, '#55605a', 500);
    STATIONS.slice(0, 7).forEach((s, i) => {
      const done = progress > i;
      const y = 172 + i * 50;
      c.fillStyle = done ? s.accent : '#d6d8d0'; c.beginPath(); c.roundRect(33, y, 26, 26, 6); c.fill();
      if (done) print(c, '✓', 39, y + 20, 18, '#ffffff', 700);
      print(c, s.name, 76, y + 19, 19, done ? '#22282b' : '#9aa19b', 600);
      print(c, s.stage, 290, y + 19, 17, done ? '#55605a' : '#b3b8b1', 500);
    });
    c.fillStyle = '#232a2b'; c.beginPath(); c.roundRect(600, 172, 260, 150, 10); c.fill();
    print(c, progress >= 7 ? 'CYCLE COMPLETE' : 'IN PROGRESS', 622, 210, 18, progress >= 7 ? '#6ee7b7' : '#e5cb82', 700);
    print(c, `${Math.min(7, Math.floor(progress))} of 7 modules`, 622, 250, 22, '#f2f4ee', 600);
    c.fillStyle = '#3a4446'; c.fillRect(622, 278, 216, 8);
    c.fillStyle = '#6ee7b7'; c.fillRect(622, 278, 216 * Math.min(1, progress / 7), 8);
    print(c, 'Shared with the board  ↗', 600, 372, 20, '#22282b', 600);
    print(c, 'ONE INCIDENT  ·  EVERY MODULE  ·  ONE REPORT', 33, 566, 13, '#879088', 600);
    reportTex.texture.needsUpdate = true;
  }

  STATIONS.forEach((st, i) => {
    const group = new THREE.Group(); group.position.set(st.pos[0], 0.29, st.pos[1]); machine.add(group);
    const glowMat = mat(st.glow, 0.2, 0.25, { emissive: st.light, emissiveIntensity: 0.5 });
    box(group, 2.05, 0.12, 1.78, 0, 0.03, 0, M.dark, 0.1);
    box(group, 1.97, 0.03, 1.7, 0, 0.12, 0, glowMat, 0.09);
    box(group, 2.03, 0.17, 1.75, 0, 0.215, 0, M.body, 0.1);
    for (const x of [-0.85, 0.85]) for (const z of [-0.7, 0.7]) screw(group, x, 0.311, z);
    gear(group, -0.35, 0.45, 0, 0.27); gear(group, 0.22, 0.45, 0.12, 0.21);
    box(group, 0.6, 0.15, 0.36, 0.52, 0.47, -0.33, M.dark);
    for (let j = 0; j < 6; j++) box(group, 0.025, 0.16, 0.37, 0.3 + j * 0.08, 0.47, -0.33, M.edge, 0.004);
    tube(group, [[-0.7, 0.4, -0.4], [-0.55, 0.48, 0.4], [0.35, 0.45, 0.6], [0.7, 0.58, 0.23]], 0.023, glowMat);
    screen(group, 1.54, 0.345, 0, 0.27, 0.891, canvasTexture(512, 116, (c) => {
      c.fillStyle = '#121a18'; c.fillRect(0, 0, 512, 116);
      print(c, String(i + 1).padStart(2, '0'), 24, 76, 42, st.ink, 600);
      print(c, st.name.toUpperCase(), 111, 73, st.name.length > 12 ? 30 : 35, '#e3e7df', 600);
    }));
    ({ cabinet: buildCabinet, admin: buildAdmin, engine: buildEngine, storefront: buildStorefront })[st.machine](group, st);
    const label = document.createElement('div');
    label.className = 'cl-label';
    label.innerHTML = `<div class="cl-stem"></div><div class="cl-label-card"><div class="cl-label-title"><span>${String(i + 1).padStart(2, '0')}</span></div><div class="cl-label-meta"></div></div>`;
    label.querySelector('.cl-label-title').append(st.name);
    label.querySelector('.cl-label-meta').textContent = st.stage;
    label.style.setProperty('--station-ink', st.accent);
    labelsHost.appendChild(label); cleanups.push(() => label.remove());
    stations.push({ ...st, index: i, group, base: group.position.clone(), glowMat, label, anchor: new THREE.Vector3(0, 0.25, 1.05) });
  });
  drawReport(0);

  // The belt: a closed loop past the front of every station.
  const ports = stations.map(s => {
    const p = s.base.clone();
    if (s.pos[1] < -1) p.z += 1.3; else if (s.pos[1] > 1) p.z -= 1.3; else p.x -= 1.4;
    p.y = 0.84; return p;
  });
  const loopPts = [...ports, new THREE.Vector3(-6.2, 0.84, 0.15)];
  const path = new THREE.CatmullRomCurve3(loopPts, true, 'catmullrom', 0.3);
  const belt = new THREE.Group(); machine.add(belt);
  const frameMesh = new THREE.Mesh(new THREE.TubeGeometry(path, 200, 0.35, 8, true), M.dark);
  frameMesh.scale.y = 0.3; frameMesh.position.y = 0.51; belt.add(frameMesh);
  const beltCount = 190, slats = new THREE.InstancedMesh(boxGeo(0.135, 0.065, 0.63, 0.012), M.body, beltCount);
  slats.receiveShadow = true; slats.instanceMatrix.setUsage(THREE.DynamicDrawUsage); belt.add(slats);
  const dummy = new THREE.Object3D(), pVec = new THREE.Vector3(), tVec = new THREE.Vector3();
  function updateBelt(t) {
    for (let i = 0; i < beltCount; i++) {
      const u = (i / beltCount + t * 0.01) % 1;
      path.getPointAt(u, pVec); path.getTangentAt(u, tVec);
      dummy.position.copy(pVec); dummy.rotation.set(0, -Math.atan2(tVec.z, tVec.x), 0); dummy.updateMatrix(); slats.setMatrixAt(i, dummy.matrix);
    }
    slats.instanceMatrix.needsUpdate = true;
  }
  updateBelt(0);
  for (const side of [-1, 1]) {
    const pts = [];
    for (let i = 0; i < 200; i++) { path.getPointAt(i / 200, pVec); path.getTangentAt(i / 200, tVec); pts.push(pVec.clone().add(new THREE.Vector3(-tVec.z * 0.36 * side, 0.09, tVec.x * 0.36 * side))); }
    belt.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts, true), 200, 0.028, 6, true), M.chrome));
  }
  for (let i = 0; i < 18; i++) { const p = path.getPointAt(i / 18); cyl(belt, 0.045, 0.43, p.x, 0.53, p.z, M.chrome); }

  // Copper lines join each station to the next, independent of the belt.
  const pipes = new THREE.Group(); machine.add(pipes);
  for (let i = 0; i < stations.length - 1; i++) {
    const a = stations[i].base, b = stations[i + 1].base;
    pipes.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3([
      a.clone().add(new THREE.Vector3(0.4, -0.05, 0)), a.clone().lerp(b, 0.35).add(new THREE.Vector3(0, -0.08, 0)),
      a.clone().lerp(b, 0.65).add(new THREE.Vector3(0, -0.08, 0)), b.clone().add(new THREE.Vector3(-0.4, -0.05, 0)),
    ]), 30, 0.05, 8, false), M.copper));
  }

  // Silo walls across the belt between neighbouring stations.
  function nearestU(p) {
    let best = 0, dist = Infinity;
    for (let i = 0; i < 500; i++) { const q = path.getPointAt(i / 500), d = (q.x - p.x) ** 2 + (q.z - p.z) ** 2; if (d < dist) { dist = d; best = i / 500; } }
    return best;
  }
  const portU = ports.map(nearestU);
  const walls = new THREE.Group(); machine.add(walls);
  for (let i = 0; i < stations.length; i++) {
    const u0 = portU[i], u1 = portU[(i + 1) % stations.length];
    const mid = (u0 + (((u1 - u0) + 1) % 1) / 2) % 1;
    const p = path.getPointAt(mid), tan = path.getTangentAt(mid);
    const wall = new THREE.Group(); wall.position.set(p.x, 0.2, p.z); wall.rotation.y = -Math.atan2(tan.z, tan.x); wall.userData.moving = true;
    box(wall, 0.05, 2.2, 2.2, 0, 1.1, 0, M.wall, 0.02);
    box(wall, 0.12, 0.09, 2.24, 0, 2.2, 0, M.wallEdge, 0.02);
    box(wall, 0.12, 0.09, 2.24, 0, 0.02, 0, M.wallEdge, 0.02);
    wall.scale.y = 0.001; wall.visible = false; walls.add(wall);
  }

  // Incident cards: one face per station; the face changes as each station picks it up.
  const faceTextures = stations.map(s => canvasTexture(256, 352, (c, w, h) => {
    c.fillStyle = '#f2f1ea'; c.fillRect(0, 0, w, h);
    c.fillStyle = s.accent; c.fillRect(0, 0, w, 110);
    print(c, s.code, 20, 46, 24, '#ffffff', 700);
    print(c, `STEP ${s.index + 1}`, 20, 86, 16, 'rgba(255,255,255,.82)', 600);
    const words = s.stage.split(' ');
    print(c, words[0], 20, 170, 34, '#1d2925', 650); print(c, words.slice(1).join(' '), 20, 210, 34, '#1d2925', 650);
    for (let i = 0; i < 4; i++) { c.fillStyle = '#c9cfc6'; c.fillRect(20, 250 + i * 20, 200 - (i % 2) * 60, 6); }
  }));
  const packets = [];
  for (let i = 0; i < 6; i++) {
    const g = new THREE.Group(); g.userData.moving = true; machine.add(g);
    box(g, 0.47, 0.71, 0.04, 0, 0, 0, M.ivory, 0.022);
    const faces = faceTextures.map(tex => { const s = screen(g, 0.43, 0.665, 0, 0, 0.024, tex); s.material.side = THREE.DoubleSide; s.visible = false; return s; });
    const halo = new THREE.Mesh(new THREE.RingGeometry(0.4, 0.414, 40), new THREE.MeshBasicMaterial({ color: theme.signal, transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthWrite: false }));
    halo.rotation.x = -Math.PI / 2; halo.position.y = -0.37; g.add(halo); halo.visible = false;
    packets.push({ group: g, faces, halo, stage: -1, phase: 0 });
  }

  // Merge static geometry per parent and material; moving parts and painted screens stay separate.
  function compact(group) {
    for (const child of [...group.children]) if (child.isGroup && !child.userData.moving) compact(child);
    const buckets = new Map();
    for (const child of group.children) {
      if (!child.isMesh || child.isInstancedMesh || child.userData.moving || Array.isArray(child.material) || child.material.map) continue;
      const k = child.material.uuid; if (!buckets.has(k)) buckets.set(k, []); buckets.get(k).push(child);
    }
    for (const list of buckets.values()) {
      if (list.length < 2) continue;
      const geos = list.map(m => { m.updateMatrix(); const g = m.geometry.index ? m.geometry.toNonIndexed() : m.geometry.clone(); return g.applyMatrix4(m.matrix); });
      const merged = mergeGeometries(geos, false); geos.forEach(g => g.dispose());
      if (!merged) continue;
      const mesh = new THREE.Mesh(merged, list[0].material); mesh.castShadow = list.some(x => x.castShadow); mesh.receiveShadow = true;
      list.forEach(m => group.remove(m)); group.add(mesh);
    }
  }
  compact(machine);
  stations.forEach(s => s.group.traverse(o => { o.userData.station = s.id; }));

  // Theme: Sage and Dusk recolour the steel, the signal, the shadow and the drafting rings.
  function applyTheme() {
    theme = THEMES[themeName()];
    for (const [k, v] of [['body', 'body'], ['base', 'base'], ['edge', 'edge'], ['dark', 'dark'], ['ivory', 'ivory']]) M[k].color.setHex(theme[v]);
    M.signal.color.setHex(theme.signal); M.signal.emissive.setHex(theme.signal);
    tintWall(); M.wall.emissive.setHex(theme.silo); M.wallEdge.color.setHex(theme.silo); M.wallEdge.emissive.setHex(theme.silo);
    shellMaterials.forEach(({ s, m }) => s.color.copy(m.color));
    packets.forEach(p => p.halo.material.color.setHex(theme.signal));
    floor.material.opacity = theme.shadow; draftMat.color.setHex(theme.drafting);
    hemi.color.setHex(theme.hemiSky); hemi.groundColor.setHex(theme.hemiGround);
  }
  const themeObserver = new MutationObserver(applyTheme);
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  cleanups.push(() => themeObserver.disconnect());

  // Modes and cameras.
  let mode = 'assembled', cameraMode = 'overview', playing = !reduceMotion, simTime = 0, spread = 0, wallLevel = 0;
  let prevStage = -1;
  let selected = 'sentinel', hovered = null, dragging = false, wasDragged = false, downX = 0, downY = 0;
  let cameraAnimating = true, flightTime = 0, lastDraw = -1, visible = true, lastInteraction = performance.now();
  let width = W(), height = H(), mobile = width <= 700, baseDistance = 25, sized = false, readySent = false;
  const desiredPosition = new THREE.Vector3(), desiredTarget = new THREE.Vector3(0, 1, 0);
  const viewDirection = new THREE.Vector3(10.5, 10.8, 17).normalize();
  function layoutCamera() {
    if (!W() || !H()) return;
    const first = !sized; sized = true;
    width = W(); height = H(); mobile = width <= 700;
    renderer.setSize(width, height); camera.aspect = width / height;
    // Lift the picture so the line sits above the control bars at the bottom of the hero.
    camera.setViewOffset(width, height, 0, height * (mobile ? 0.08 : 0.12), width, height);
    const fov = THREE.MathUtils.degToRad(camera.fov / 2);
    const horizontalFit = (PW + 2.6) / (2 * Math.tan(fov) * camera.aspect * 0.94);
    const verticalFit = (PD + 2.4) / (2 * Math.tan(fov) * 0.72);
    baseDistance = Math.max(horizontalFit, verticalFit) * (mobile ? 0.86 : 1.03);
    controls.maxDistance = Math.max(60, baseDistance * 1.6);
    camera.updateProjectionMatrix(); setCameraGoal(); cameraAnimating = true;
    if (first) { camera.position.copy(desiredPosition); controls.target.copy(desiredTarget); controls.update(); cameraAnimating = false; }
  }
  function setCameraGoal() {
    const expand = mode === 'stations' ? 1.2 : 1;
    if (cameraMode === 'station') {
      const s = stations.find(x => x.id === selected);
      desiredTarget.copy(s.group.position).add(new THREE.Vector3(0, 1.25, 0));
      desiredPosition.copy(desiredTarget).addScaledVector(viewDirection, mobile ? 9 : 11);
    } else {
      desiredTarget.set(0, 1, 0);
      const d = baseDistance * expand;
      if (cameraMode === 'side') desiredPosition.set(15, 5, 18).normalize().multiplyScalar(d).add(desiredTarget);
      else if (cameraMode === 'top') desiredPosition.set(0.01, d, 0.8).add(desiredTarget);
      else desiredPosition.copy(viewDirection).multiplyScalar(d).add(desiredTarget);
    }
  }
  const MODES = ['assembled', 'cutaway', 'stations', 'incident', 'silos'];
  const CAMERAS = ['overview', 'side', 'top', 'station', 'flight'];
  function sync() { ui.onState?.({ mode, camera: cameraMode, playing, selected }); }
  const api = {
    setMode(name) {
      if (!MODES.includes(name)) return false;
      mode = name; lastInteraction = performance.now(); prevStage = -1; // the readout restates where the incident is
      if (mode === 'incident') { simTime = 0; lastDraw = -1; api.play(); cameraMode = 'overview'; }
      else if (cameraMode === 'station') cameraMode = 'overview';
      setCameraGoal(); cameraAnimating = true; sync(); return true;
    },
    setCamera(name) {
      if (!CAMERAS.includes(name)) return false;
      cameraMode = name; if (mode === 'incident') mode = 'assembled';
      lastInteraction = performance.now(); flightTime = 0; setCameraGoal(); cameraAnimating = true; sync(); return true;
    },
    focusStation(id) {
      if (!stations.some(s => s.id === id)) return false;
      selected = id; if (mode === 'incident') mode = 'assembled';
      cameraMode = 'station'; lastInteraction = performance.now(); setCameraGoal(); cameraAnimating = true; sync(); return true;
    },
    zoom(factor) {
      const offset = camera.position.clone().sub(controls.target);
      const next = THREE.MathUtils.clamp(offset.length() * factor, controls.minDistance, controls.maxDistance);
      desiredPosition.copy(controls.target).add(offset.setLength(next)); desiredTarget.copy(controls.target);
      cameraAnimating = true; lastInteraction = performance.now();
    },
    play() { playing = true; sync(); return true; },
    pause() { playing = false; sync(); return true; },
    engage,
  };
  root.connectedLine = api;

  listen(window, 'resize', layoutCamera);
  const resizeObserver = new ResizeObserver(layoutCamera); resizeObserver.observe(host); cleanups.push(() => resizeObserver.disconnect());
  layoutCamera();
  controls.addEventListener('start', () => { dragging = true; cameraAnimating = false; lastInteraction = performance.now(); });
  controls.addEventListener('end', () => { dragging = false; lastInteraction = performance.now(); });

  const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
  function hitStation(x, y) {
    pointer.set((x / width) * 2 - 1, (-y / height) * 2 + 1); raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects(stations.map(s => s.group), true);
    return hits.length ? stations.find(s => s.id === hits[0].object.userData.station) : null;
  }
  const local = e => { const r = host.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  listen(renderer.domElement, 'pointermove', e => {
    const [x, y] = local(e);
    if (Math.hypot(x - downX, y - downY) > 5) wasDragged = true;
    if (dragging) return;
    const s = hitStation(x, y); hovered = s ? s.id : null;
    renderer.domElement.style.cursor = s ? 'pointer' : 'grab';
    ui.onHover?.(s ? { index: s.index, name: s.name, detail: s.detail, ink: s.ink, x, y, width, height } : null);
  });
  listen(renderer.domElement, 'pointerleave', () => { hovered = null; ui.onHover?.(null); if (!coarse) engage(false); });
  listen(renderer.domElement, 'pointerdown', e => { [downX, downY] = local(e); wasDragged = false; ui.onHover?.(null); if (!engaged) engage(true); });
  listen(renderer.domElement, 'pointerup', e => {
    if (wasDragged) return;
    const s = hitStation(...local(e)); if (s) { api.focusStation(s.id); ui.onStation?.(s.id); }
  });
  // On touch screens, a tap outside the scene gives the finger back to the page.
  if (coarse) listen(document, 'pointerdown', e => { if (engaged && !root.contains(e.target)) engage(false); });
  listen(document, 'visibilitychange', () => { visible = !document.hidden; lastFrame = performance.now(); });
  const io = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting && !document.hidden; lastFrame = performance.now(); }, { threshold: 0.01 });
  io.observe(renderer.domElement); cleanups.push(() => io.disconnect());

  const anchor = new THREE.Vector3();
  const LOOP = 30; // seconds for the incident to go round the whole line
  let lastFrame = performance.now(), rafId = 0;
  function animate(now) {
    rafId = requestAnimationFrame(animate);
    const dt = Math.max(0, Math.min((now - lastFrame) / 1000, 0.045)); lastFrame = now;
    if (!visible) return;
    const smooth = 1 - Math.exp(-dt * 5);
    wallLevel = THREE.MathUtils.lerp(wallLevel, mode === 'silos' ? 1 : 0, smooth);
    const flow = playing ? Math.max(0, 1 - wallLevel * 1.4) : 0;
    if (playing) flightTime += dt;
    simTime += dt * flow;
    const t = simTime, tact = (t * TAU) / 4;
    spread = THREE.MathUtils.lerp(spread, mode === 'stations' ? 1 : 0, smooth);
    cutPlane.constant = THREE.MathUtils.lerp(cutPlane.constant, mode === 'cutaway' ? 0.99 : 10, smooth);
    walls.children.forEach(w => { w.visible = wallLevel > 0.02; w.scale.y = Math.max(0.001, wallLevel); });
    stations.forEach((s, i) => {
      s.group.position.copy(s.base);
      s.group.position.x *= 1 + spread * 0.22; s.group.position.z *= 1 + spread * 0.32;
      s.group.position.y += spread * (i % 2 ? 0.32 : 0.55);
    });
    belt.scale.set(1 + spread * 0.08, 1, 1 + spread * 0.12);
    pipes.scale.set(1 + spread * 0.2, 1, 1 + spread * 0.28);
    gears.forEach((g, i) => { g.rotation.y = t * (i % 2 ? -1 : 1) * 1.1; });
    reels.forEach((r, i) => { r.rotation.z = -t * (i % 2 ? 0.65 : 0.85); });
    printheads.forEach(h => { h.position.x = Math.sin(tact) * 0.42; h.position.y = 1.91 + Math.sin(tact * 2) * 0.055; });
    outputs.forEach(o => { o.group.position.y = ((t / 4) % 1) * 0.25; });
    posts.forEach(p => { p.position.y = Math.sin(tact) * 0.04; });
    toggles.forEach((o, i) => { o.rotation.x = Math.sin(tact + i) > 0 ? -0.4 : 0.4; });
    incomings.forEach((g, i) => {
      const b = ((t / 4) + i * 0.33) % 1;
      g.position.set(Math.sin(b * Math.PI) * 0.24, 2.9 - b * 1.9, 1.1 - b * 0.55);
      g.rotation.z = Math.sin(b * Math.PI) * -0.14;
      g.scale.setScalar(Math.min(1, b * 8 + 0.15, (1 - b) * 7 + 0.1));
    });
    if (t - lastDraw > 1 / 15 || lastDraw < 0) { queues.forEach(q => drawQueue(q, t)); outputs.forEach(o => drawDoc(o, t)); updateBelt(t); lastDraw = t; }

    // Incidents on the belt. The lead incident (packet 0) drives the readout, the report and One incident mode.
    let leadProgress = 0;
    packets.forEach((p, i) => {
      const phase = ((t / LOOP) + i / packets.length) % 1;
      const u = (portU[0] + phase) % 1;
      path.getPointAt(u, p.group.position);
      p.group.position.x *= 1 + spread * 0.08; p.group.position.z *= 1 + spread * 0.12; p.group.position.y += 0.43;
      path.getTangentAt(u, tVec); p.group.rotation.set(0, -Math.atan2(tVec.z, tVec.x) + Math.PI / 2, 0);
      let stage = 0;
      for (let k = 0; k < portU.length; k++) if (((u - portU[k] + 1) % 1) < ((u - portU[stage] + 1) % 1)) stage = k;
      if (p.stage !== stage) { p.faces.forEach((f, j) => { f.visible = j === stage; }); p.stage = stage; }
      p.phase = phase;
      p.group.visible = mode !== 'incident' || i === 0;
      p.halo.visible = i === 0 && (mode === 'incident' || mode === 'silos');
      p.group.scale.setScalar(mode === 'incident' && i === 0 ? 1.35 : 1);
      if (i === 0) leadProgress = stage + Math.min(1, ((u - portU[stage] + 1) % 1) / Math.max(0.001, ((portU[(stage + 1) % portU.length] - portU[stage] + 1) % 1)));
    });
    const lead = packets[0];
    if (lead.stage !== prevStage) {
      prevStage = lead.stage;
      drawReport(lead.stage === stations.length - 1 ? 7 : lead.stage);
      ui.onStage?.(lead.stage, stations[lead.stage], mode === 'silos');
    }
    ui.onProgress?.(lead.phase);
    if (mode === 'incident' && !dragging && playing) {
      desiredTarget.copy(lead.group.position);
      desiredPosition.copy(desiredTarget).addScaledVector(viewDirection, mobile ? 10 : 14);
      cameraAnimating = true;
    } else if (cameraMode === 'flight' && playing && !dragging) {
      const a = flightTime * 0.12, d = baseDistance * (mode === 'stations' ? 1.2 : 1);
      desiredTarget.set(0, 1, 0);
      desiredPosition.set(Math.sin(a + 0.55) * d * 0.83, d * (0.5 + Math.sin(a * 0.7) * 0.09), Math.cos(a + 0.55) * d * 0.83).add(desiredTarget);
      cameraAnimating = true;
    } else if (cameraMode === 'station' && cameraAnimating) setCameraGoal();

    stations.forEach((s, i) => {
      const pulse = Math.pow(Math.max(0, Math.sin(tact - i * 0.9)), 7);
      const lit = hovered === s.id || (cameraMode === 'station' && selected === s.id) || i === lead.stage;
      s.glowMat.emissiveIntensity = THREE.MathUtils.lerp(s.glowMat.emissiveIntensity, lit ? 3.2 : 0.55 + pulse * 0.6, smooth);
    });
    if (cameraAnimating && !dragging) {
      const speed = 1 - Math.exp(-dt * (mode === 'incident' ? 2.2 : 3));
      camera.position.lerp(desiredPosition, speed); controls.target.lerp(desiredTarget, speed);
      if (cameraMode !== 'flight' && mode !== 'incident' && camera.position.distanceTo(desiredPosition) < 0.015 && controls.target.distanceTo(desiredTarget) < 0.015) cameraAnimating = false;
    }
    controls.autoRotate = playing && !reduceMotion && !dragging && !cameraAnimating && mode !== 'incident' && cameraMode === 'overview' && now - lastInteraction > 6500;
    controls.autoRotateSpeed = 0.24;
    controls.update(dt);

    // Station labels in Stations mode, projected after the camera moves.
    stations.forEach((s) => {
      const show = mode === 'stations';
      s.label.classList.toggle('visible', show);
      if (!show) return;
      anchor.copy(s.group.position).add(s.anchor).project(camera);
      // A compact pill centred under the front of each station, kept clear of the readout and the controls.
      const x = THREE.MathUtils.clamp((anchor.x * 0.5 + 0.5) * width, 60, width - 60);
      const y = THREE.MathUtils.clamp((-anchor.y * 0.5 + 0.5) * height + 4, 70, height - 150);
      s.label.style.transform = `translate(calc(${x}px - 50%),${y}px)`;
    });
    renderer.render(scene, camera);
    if (!readySent && sized) { readySent = true; ui.onReady?.(); }
  }
  rafId = requestAnimationFrame(animate);
  cleanups.push(() => {
    cancelAnimationFrame(rafId); controls.dispose();
    scene.traverse(o => { if (o.geometry) o.geometry.dispose(); const list = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : []; list.forEach(m => { if (m.map) m.map.dispose(); m.dispose(); }); });
    geometries.forEach(g => g.dispose()); env.dispose(); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove();
    if (root.connectedLine === api) delete root.connectedLine;
  });
  renderer.compile(scene, camera);
  sync();
  return () => cleanups.reverse().forEach(fn => fn());
}
