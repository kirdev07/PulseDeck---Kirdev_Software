// PulseDeck Panel in the browser — the screen of the Android panel (PulseDeck-PanelAPP).
//
// Start: on plain HTTP the page asks the PC for its HTTPS port (/info) and checks whether this
// phone already trusts the PC's home certificate; if yes it moves to https://…, otherwise it
// shows «Защищённый режим» (install the certificate) with «only view» as the way out.
// Pairing: once, with the 6-digit code from «Телефон» (POST /pair); the token is kept per origin.
// Then a WebSocket (/ws): hello, access, metrics, media, sessions, error. Values come from the
// PC as they are; unknown ones stay «—».
'use strict';

const TOKEN_STORE = 'pulsedeck.token';
const SKIP_STORE = 'pulsedeck.insecure';
const THEME_STORE = 'pulsedeck.theme';
const $ = (id) => document.getElementById(id);
const state = {
  token: '', ws: null, retry: 0, control: false, secure: location.protocol === 'https:', reason: '',
  media: null, mediaAt: 0, coverKey: '', seeking: false, volumeBusy: -1e9, httpsPort: 0,
};
let pendingCode = '';        // pairing code from the QR, kept while the user installs the certificate

// ----- storage -----
const store = {
  get(key) { try { return localStorage.getItem(key) || ''; } catch (e) { return ''; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* private mode */ } },
  drop(key) { try { localStorage.removeItem(key); } catch (e) { /* ignore */ } },
};

// ----- theme: «Тёмная» (as the panel) or «Белая» -----
function applyTheme(theme) {
  theme = theme === 'light' ? 'light' : 'dark';       // anything else (an old «auto» too) → dark
  document.documentElement.dataset.theme = theme;
  for (const chip of $('themes').children) chip.classList.toggle('on', chip.dataset.theme === theme);
  const background = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#000000';
  document.querySelector('meta[name="theme-color"]').setAttribute('content', background);
}

function forgetToken(reason) {
  store.drop(TOKEN_STORE);
  state.token = '';
  if (state.ws) state.ws.close();
  showPairing(reason);
}

// «Браузер (iPhone)», «PulseDeck (iPhone, экран Домой)» … — the name shown in «Телефон» on the PC.
function deviceName() {
  const ua = navigator.userAgent;
  const where = /iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) ? 'iPad'
    : /iPhone/.test(ua) ? 'iPhone' : /Android/.test(ua) ? 'Android'
    : /Mac OS X/.test(ua) ? 'Mac' : /Windows/.test(ua) ? 'Windows' : 'устройство';
  // A page opened from the home-screen icon keeps its own storage, separate from Safari.
  const standalone = navigator.standalone || window.matchMedia('(display-mode: standalone)').matches;
  return standalone ? `PulseDeck (${where}, экран Домой)` : `Браузер (${where})`;
}
const isApple = () => /iPhone|iPad|Macintosh/.test(navigator.userAgent);

function only(id) {
  for (const screen of ['setup', 'pairing', 'panel']) $(screen).hidden = screen !== id;
  $('offline').hidden = true;
}

// ----- secure mode (HTTP → HTTPS) -----
async function httpsTrusted(port) {
  if (!port) return false;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    await fetch(`https://${location.hostname}:${port}/info`, { mode: 'no-cors', cache: 'no-store', signal: controller.signal });
    clearTimeout(timer);
    return true;            // the TLS handshake succeeded: the certificate is trusted
  } catch (e) {
    return false;
  }
}

function goSecure() {
  const hash = pendingCode ? `#pair=${encodeURIComponent(pendingCode)}` : '';
  location.replace(`https://${location.hostname}:${state.httpsPort}/${hash}`);
}

function showSetup(message) {
  only('setup');
  $('steps-ios').hidden = !isApple();
  $('steps-android').hidden = isApple();
  $('setuperror').hidden = !message;
  $('setuperror').textContent = message || '';
}

async function checkSecure(manual) {
  $('check-https').disabled = true;
  $('check-https').textContent = 'Проверяю…';
  const ok = await httpsTrusted(state.httpsPort);
  $('check-https').disabled = false;
  $('check-https').textContent = 'Проверить';
  if (ok) { goSecure(); return true; }
  if (manual) showSetup('Сертификат пока не принят. Проверьте, что включено «Доверие сертификатам» (iPhone) или сертификат ЦС установлен (Android).');
  return false;
}

// ----- pairing -----
function showPairing(reason) {
  only('pairing');
  const error = $('pairerror');
  error.hidden = !reason;
  error.textContent = reason || '';
}

async function pair(code) {
  const digits = String(code || '').replace(/\D/g, '');
  if (digits.length !== 6) { showPairing('Код — 6 цифр с экрана «Телефон» на ПК.'); return; }
  $('pairbtn').disabled = true;
  $('pairbtn').textContent = 'Подключаю…';
  try {
    const response = await fetch('pair', {
      method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: digits, name: deviceName() }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.token) throw new Error(data.error || 'ПК отклонил подключение.');
    state.token = data.token;
    store.set(TOKEN_STORE, data.token);
    only('panel');
    connect();
  } catch (e) {
    showPairing(e.name === 'TypeError' ? 'Нет связи с ПК. Телефон в той же сети Wi-Fi?' : e.message);
  } finally {
    $('pairbtn').disabled = false;
    $('pairbtn').textContent = 'Подключить';
  }
}

// ----- formatting -----
const pct = (v) => (v == null ? '—' : `${Math.round(v)}%`);
function bytes(v) {
  if (v == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}
const speed = (v) => (v == null ? '—' : `${bytes(v)}/s`);
function clockTime(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = String(sec % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}
const setBar = (el, value) => { el.style.width = (value == null ? 0 : Math.min(100, Math.max(0, value))) + '%'; };
const shortCpu = (name) => (name || '').replace(/\(R\)|\(TM\)|CPU|Processor|@.*$/gi, '').replace(/\s+/g, ' ')
  .replace(/^\d+th Gen /i, '').trim();
const shortGpu = (name) => (name || '').replace(/NVIDIA |GeForce |AMD |Radeon\(TM\) |Laptop GPU|\d+GB/gi, '').replace(/\s+/g, ' ').trim();

function tickClock() {
  const now = new Date();
  $('time').textContent = now.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  $('date').textContent = now.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' });
}

// ----- metrics (the panel's bottom row) -----
function metric(id, value, sub, bar) {
  const el = $(id);
  el.querySelector('.head .num').textContent = value;
  el.querySelector('.sub').textContent = sub || '—';
  const fill = el.querySelector('.bar i');
  if (fill) setBar(fill, bar);
}

function showMetrics(m) {
  metric('m-cpu', pct(m.cpu.load), shortCpu(m.cpu.name) || (m.cpu.cores ? `${m.cpu.cores} потоков` : ''), m.cpu.load);
  const vram = m.gpu.memory_total ? ` · ${bytes(m.gpu.memory_total)}` : '';
  metric('m-gpu', pct(m.gpu.load), (shortGpu(m.gpu.name) || '') + vram, m.gpu.load);
  metric('m-ram', pct(m.ram.percent), m.ram.used != null && m.ram.total ? `${bytes(m.ram.used)} / ${bytes(m.ram.total)}` : '', m.ram.percent);
  $('down').textContent = `↓${speed(m.net.down)}`;
  $('up').textContent = `↑ ${speed(m.net.up)}`;
  const disk = (m.disks || [])[0];
  if (disk) {
    $('diskname').textContent = disk.name;
    $('diskfree').textContent = bytes(disk.free);
    $('disksub').textContent = `свободно из ${bytes(disk.total)}`;
    setBar($('diskbar'), disk.total ? 100 * (disk.total - disk.free) / disk.total : null);
  }
}

// ----- media -----
function showMedia(msg) {
  const s = msg.session;
  state.media = s;
  state.mediaAt = performance.now();
  $('player').hidden = !s;
  $('wave').hidden = !!s;
  if (s) {
    $('title').textContent = s.title;
    $('artist').textContent = [s.artist, s.album].filter(Boolean).join(' · ');
    $('sourcename').textContent = s.source || '';
    $('progress').hidden = !(s.duration > 0);
  }
  const coverKey = s && s.cover ? s.cover : '';
  if (coverKey !== state.coverKey) {
    state.coverKey = coverKey;
    const img = $('coverimg');
    if (coverKey) {
      img.onload = () => { img.hidden = false; };
      img.onerror = () => { img.hidden = true; };
      img.src = `cover?key=${encodeURIComponent(coverKey)}&t=${encodeURIComponent(state.token)}`;
    } else {
      img.hidden = true;
      img.removeAttribute('src');
    }
  }
  const vol = msg.system_volume;
  $('volumerow').hidden = !vol;
  if (vol && performance.now() - state.volumeBusy > 1500) {      // not while the finger moves the slider
    $('volume').value = vol.level;
    $('volumevalue').textContent = vol.muted ? '0' : String(vol.level);
  }
  showControls();
  tickProgress();
}

function showSessions(items) {
  const select = $('source');
  const chosen = select.value;
  const options = [new Option('Автоматически', '')];
  for (const s of items) {
    const label = s.title ? `${s.source} — ${s.title}` : s.source;
    options.push(new Option(label.slice(0, 60), s.id));
  }
  select.replaceChildren(...options);
  select.value = options.some((o) => o.value === chosen) ? chosen : '';
  if (select.value !== chosen) send('source', '');      // the chosen app stopped playing
}

function showControls() {
  const s = state.media;
  for (const button of $('controls').querySelectorAll('button')) button.disabled = !state.control;
  const playing = s && s.status === 'playing';
  $('playicon').setAttribute('href', playing ? '#i-pause' : '#i-play');
  $('playbtn').setAttribute('aria-label', playing ? 'Пауза' : 'Играть');
  $('seek').disabled = !state.control;
  $('volume').disabled = !state.control;
  const hint = $('accesshint');
  let text = '';
  if (!state.control && state.reason === 'view') {
    text = 'Только просмотр. Чтобы управлять музыкой, на ПК: «Телефон» → «Подключённые устройства» → «Доступ» → «Полный».';
  } else if (!state.control && state.reason === 'insecure') {
    text = state.secure
      ? 'Этот телефон подключён без шифрования. Чтобы управлять музыкой, на ПК нажмите «Отозвать» и подключите его снова.'
      : 'Управление музыкой — в защищённом режиме. Нажмите, чтобы настроить.';
  }
  hint.hidden = !text || !s;
  hint.textContent = text;
  hint.onclick = !state.control && state.reason === 'insecure' && !state.secure
    ? () => { store.drop(SKIP_STORE); showSetup(); } : null;
  showSecureInfo();
}

function showSecureInfo() {
  const info = $('secureinfo');
  const lock = '<svg class="i"><use href="#i-lock"/></svg>';
  const text = state.secure
    ? (state.control ? 'Защищённое соединение (HTTPS). Управление музыкой разрешено.' : 'Защищённое соединение (HTTPS). Только просмотр — «Полный» включается на ПК.')
    : 'Без шифрования (HTTP): только просмотр. Для управления установите сертификат ПК.';
  info.innerHTML = (state.secure ? lock : '') + '<span></span>';
  info.querySelector('span').textContent = text;
  $('state').innerHTML = state.secure ? lock : '';
}

function tickProgress() {
  const s = state.media;
  if (!s || !(s.duration > 0) || state.seeking) return;
  let pos = s.position || 0;
  if (s.status === 'playing') pos += (performance.now() - state.mediaAt) / 1000;   // between updates from the PC
  pos = Math.min(pos, s.duration);
  $('seek').max = Math.floor(s.duration);
  $('seek').value = Math.floor(pos);
  $('pos').textContent = clockTime(pos);
  $('dur').textContent = clockTime(s.duration);
}

function send(action, value) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(value === undefined ? { type: 'command', action } : { type: 'command', action, value }));
  }
}

// ----- KiroX Motion: the panel's idle wave (48 steps, sin(i·0.42 − t/135ms)·2.3) -----
function startWave() {
  const canvas = $('wave');
  const context = canvas.getContext('2d');
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let last = 0;
  function frame(now) {
    if (!canvas.hidden && !document.hidden && now - last > 33) {        // ~30 fps, as the panel
      last = now;
      const ratio = window.devicePixelRatio || 1;
      const width = 144, height = 18;
      if (canvas.width !== width * ratio) { canvas.width = width * ratio; canvas.height = height * ratio; }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      context.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#fff';
      context.lineWidth = 1.15;
      context.lineCap = 'round';
      context.beginPath();
      const phase = still ? 0 : now / 135;
      for (let i = 0; i <= 48; i++) {
        const x = (i / 48) * width;
        const y = height / 2 + Math.sin(i * 0.42 - phase) * 2.3;
        if (i === 0) context.moveTo(x, y); else context.lineTo(x, y);
      }
      context.stroke();
    }
    if (!still) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

// ----- connection -----
function setStatus(online) {
  $('dot').classList.toggle('on', online);
}

function connect() {
  if (!state.token) { showPairing(); return; }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws?t=${encodeURIComponent(state.token)}`);
  state.ws = ws;
  let opened = false;
  ws.onopen = () => { opened = true; state.retry = 0; };
  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch (e) { return; }
    if (msg.type === 'hello') {
      $('pcname').textContent = msg.name || 'ПК';
      only('panel');
      setStatus(true);
    } else if (msg.type === 'access') {
      state.control = !!msg.control;
      state.reason = msg.reason || '';
      showControls();
    } else if (msg.type === 'metrics') {
      showMetrics(msg);
    } else if (msg.type === 'media') {
      showMedia(msg);
    } else if (msg.type === 'sessions') {
      showSessions(msg.items || []);
    } else if (msg.type === 'error') {
      toast(msg.message || 'Ошибка');
    }
  };
  ws.onclose = (event) => {
    if (state.ws === ws) state.ws = null;
    if (event.code === 4001) {
      forgetToken('Доступ этого телефона отозван на ПК. Чтобы подключиться снова, покажите новый код.');
      return;
    }
    if (!opened && state.token) {
      fetch(`cover?key=&t=${encodeURIComponent(state.token)}`, { cache: 'no-store' }).then((r) => {
        if (r.status === 403) forgetToken('Этот телефон больше не подключён к ПК. Покажите на ПК новый код.');
        else scheduleReconnect();
      }).catch(scheduleReconnect);
      return;
    }
    scheduleReconnect();
  };
}

function scheduleReconnect() {
  if (!state.token) return;
  setStatus(false);
  if (!$('panel').hidden) {
    $('offline').hidden = false;
    $('offline-text').textContent = 'Переподключаюсь… Проверьте, что PulseDeck запущен, а телефон в той же сети Wi-Fi.';
  }
  const delay = Math.min(15000, 1000 * 2 ** state.retry++);
  setTimeout(() => { if (!state.ws && state.token) connect(); }, delay);
}

let toastTimer = 0;
function toast(text) {
  const el = $('toast');
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
}

// ----- keep the screen on (Wake Lock: HTTPS only; Chrome, Safari 16.4+) -----
let wakeLock = null;
let wantAwake = false;
async function keepAwake(on) {
  try {
    if (on && 'wakeLock' in navigator) {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => { wakeLock = null; updateAwake(); });
    } else if (wakeLock) {
      await wakeLock.release();
      wakeLock = null;
    }
  } catch (e) {
    toast('Браузер не разрешил держать экран включённым.');
  }
  updateAwake();
}
function updateAwake() {
  const button = $('awake');
  button.disabled = !('wakeLock' in navigator);
  button.setAttribute('aria-checked', wakeLock ? 'true' : 'false');
  button.title = button.disabled ? 'Доступно только в защищённом режиме (HTTPS)' : '';
}

// ----- battery of this phone (Battery Status API: Chrome on Android; Safari on iPhone has none) -----
async function startBattery() {
  if (!navigator.getBattery) return;            // not offered by this browser: the icon stays hidden
  let battery;
  try { battery = await navigator.getBattery(); } catch (e) { return; }
  const show = () => {
    const level = Math.round(battery.level * 100);
    $('battery').hidden = false;
    $('battery').classList.toggle('low', level <= 20 && !battery.charging);
    $('battery-level').setAttribute('width', String(Math.max(0.6, 13.4 * battery.level)));
    $('battery-bolt').toggleAttribute('hidden', !battery.charging);
    $('battery-text').textContent = `${level}%`;
    $('battery').title = battery.charging ? `Заряжается: ${level}%` : `Батарея телефона: ${level}%`;
  };
  show();
  battery.addEventListener('levelchange', show);
  battery.addEventListener('chargingchange', show);
}

// ----- start -----
function startPanel(code) {
  state.token = store.get(TOKEN_STORE);
  if (code && !state.token) {
    showPairing();
    $('codeinput').value = code;
    pair(code);
    return;
  }
  if (!state.token) { showPairing(); return; }
  only('panel');
  connect();
}

document.addEventListener('DOMContentLoaded', async () => {
  applyTheme(store.get(THEME_STORE) || 'dark');
  tickClock();
  setInterval(tickClock, 1000);
  setInterval(tickProgress, 1000);
  startWave();
  startBattery();
  showSecureInfo();

  $('controls').addEventListener('click', (event) => {
    const cmd = event.target.closest('button')?.dataset.cmd;
    if (cmd) send(cmd);
  });
  const seek = $('seek');
  seek.addEventListener('input', () => { state.seeking = true; $('pos').textContent = clockTime(Number(seek.value)); });
  seek.addEventListener('change', () => {
    state.seeking = false;
    send('seek', Number(seek.value));
    if (state.media) { state.media.position = Number(seek.value); state.mediaAt = performance.now(); }
  });
  const volume = $('volume');
  volume.addEventListener('input', () => { state.volumeBusy = performance.now(); $('volumevalue').textContent = volume.value; });
  volume.addEventListener('change', () => { state.volumeBusy = performance.now(); send('volume', Number(volume.value)); });

  // settings sheet
  $('open-settings').addEventListener('click', () => { $('sheet').hidden = false; });
  $('close-settings').addEventListener('click', () => { $('sheet').hidden = true; });
  $('sheet').addEventListener('click', (event) => { if (event.target === $('sheet')) $('sheet').hidden = true; });
  $('themes').addEventListener('click', (event) => {
    const theme = event.target.closest('button')?.dataset.theme;
    if (theme) { store.set(THEME_STORE, theme); applyTheme(theme); }
  });
  $('source').addEventListener('change', () => send('source', $('source').value));
  $('awake').addEventListener('click', () => { wantAwake = !wakeLock; keepAwake(wantAwake); });
  updateAwake();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && wantAwake && wakeLock === null) keepAwake(true);
  });
  $('forget').addEventListener('click', () => {
    $('sheet').hidden = true;
    forgetToken('Телефон отключён на этом устройстве. Удалите его и на ПК: «Телефон» → «Отозвать».');
  });

  // pairing and secure mode
  $('codeinput').addEventListener('input', (event) => {
    const digits = event.target.value.replace(/\D/g, '').slice(0, 6);
    event.target.value = digits.length > 3 ? `${digits.slice(0, 3)} ${digits.slice(3)}` : digits;
  });
  $('pairform').addEventListener('submit', (event) => { event.preventDefault(); pair($('codeinput').value); });
  $('check-https').addEventListener('click', () => checkSecure(true));
  $('skip-https').addEventListener('click', () => { store.set(SKIP_STORE, '1'); startPanel(pendingCode); });

  // QR code from the PC: …/#pair=123456 — used once, then removed from the address bar.
  pendingCode = new URLSearchParams(location.hash.slice(1)).get('pair') || '';

  if (location.protocol === 'http:') {
    // Plain HTTP: prefer the HTTPS panel when this phone already trusts the PC.
    try {
      const info = await (await fetch('info', { cache: 'no-store' })).json();
      state.httpsPort = info.https_port || 0;
    } catch (e) { state.httpsPort = 0; }
    if (state.httpsPort && await httpsTrusted(state.httpsPort)) { goSecure(); return; }
    if (pendingCode) history.replaceState(null, '', location.pathname);
    if (state.httpsPort && !store.get(SKIP_STORE) && !store.get(TOKEN_STORE)) {
      showSetup();          // new phone: offer the secure mode first; the code waits
      return;
    }
    startPanel(pendingCode);
    return;
  }
  if (pendingCode) history.replaceState(null, '', location.pathname);
  startPanel(pendingCode);
});
