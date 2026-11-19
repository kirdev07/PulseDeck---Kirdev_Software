// PulseDeck Panel in the browser — the screen of the Android panel (PulseDeck-PanelAPP).
//
// Start: on plain HTTP the page asks the PC for its HTTPS port (/info) and checks whether this
// phone already trusts the PC's home certificate; if yes it moves to https://…, otherwise it
// shows «Защищённый режим» (install the certificate) with «only view» as the way out.
// Pairing: once, with the 6-digit code from «Телефон» (POST /pair); the token is kept per origin.
// Then a WebSocket (/ws): hello, access, metrics, media, sessions, error. Values come from the
// PC as they are; unknown ones stay «—».
//
// Customisation (gear → «Настройки») lives on this phone only (localStorage «pulsedeck.prefs»):
// theme (+ by time), accent, clock, animations, layout, tiles and their order, player parts,
// burn-in shift, clock screensaver without connection. The Android panel gets the same later.
'use strict';

// A script error shows on screen: on a phone there is no console to look at.
function showCrash(text) {
  let box = document.querySelector('.crash');
  if (!box) { box = document.createElement('div'); box.className = 'crash'; document.body.append(box); }
  box.textContent = `Ошибка веб-панели (пришлите скриншот): ${text}`;
}
window.addEventListener('error', (e) => showCrash(`${e.message} @ ${(e.filename || '').split('/').pop()}:${e.lineno}`));
window.addEventListener('unhandledrejection', (e) => showCrash(String(e.reason && (e.reason.stack || e.reason))));

const TOKEN_STORE = 'pulsedeck.token';
const SKIP_STORE = 'pulsedeck.insecure';
const PREFS_STORE = 'pulsedeck.prefs';
const $ = (id) => document.getElementById(id);
const state = {
  token: '', ws: null, retry: 0, control: false, secure: location.protocol === 'https:', reason: '',
  media: null, mediaAt: 0, coverKey: '', seeking: false, volumeBusy: -1e9, httpsPort: 0,
  metrics: null, volume: null, online: false,
};
let pendingCode = '';        // pairing code from the QR, kept while the user installs the certificate

// ----- storage -----
const store = {
  get(key) { try { return localStorage.getItem(key) || ''; } catch (e) { return ''; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* private mode */ } },
  drop(key) { try { localStorage.removeItem(key); } catch (e) { /* ignore */ } },
};

// ----- preferences -----
const TILES = {
  cpu: { icon: 'i-cpu', name: 'CPU', title: 'Процессор' },
  gpu: { icon: 'i-gpu', name: 'GPU', title: 'Видеокарта' },
  ram: { icon: 'i-ram', name: 'RAM', title: 'Память' },
  net: { icon: 'i-network', name: 'Сеть', title: 'Сеть' },
  disk: { icon: 'i-disk', name: 'Диск', title: 'Диск' },
  vram: { icon: 'i-gpu', name: 'VRAM', title: 'Видеопамять' },
  cores: { icon: 'i-cpu', name: 'Ядра', title: 'Ядра процессора' },
  volume: { icon: 'i-volume', name: 'Звук', title: 'Громкость ПК' },
};
const DEFAULTS = {
  theme: 'dark', themeByTime: false, dayFrom: '07:00', dayTo: '20:00',
  accent: 'white', clockWeight: 'thin', clockSize: 'm', clock24: true, seconds: false, showDate: true,
  bgDark: 'default', bgLight: 'default', clockColor: 'ink', uiFont: 'system', clockFont: 'system',
  idle: 'wave', idleSize: 'normal', buddy: 'none', motion: true, pulse: false,
  layout: 'panel', tiles: ['cpu', 'gpu', 'ram', 'net', 'disk'], tileOrder: Object.keys(TILES), disk: '',
  playerAlways: false, showCover: true, showProgress: true, showVolume: true, sparks: true,
  burnIn: true, offlineClock: true,
};
const CLOCK_COLORS = {          // «ink» = the theme's text colour (no override)
  accent: 'var(--accent)', white: '#ffffff', blue: '#7aa7ff', green: '#5fd99a', purple: '#b896ff',
  orange: '#ffb066', pink: '#ff8cc6', gold: '#ffd166', red: '#ff7a7a',
};
const COLOR_NAMES = { white: 'Белый', blue: 'Голубой', green: 'Зелёный', purple: 'Сиреневый', orange: 'Оранжевый',
                      pink: 'Розовый', gold: 'Золотой', red: 'Красный' };
const BACKGROUNDS = {
  dark: [['default', 'Чёрный', '#000000'], ['graphite', 'Графит', '#121417'], ['midnight', 'Ночь', '#0b1020'],
         ['forest', 'Лес', '#0a1712'], ['plum', 'Слива', '#170d1c'], ['wine', 'Вино', '#1c0a10'], ['coffee', 'Кофе', '#17110c']],
  light: [['default', 'Белый', '#ffffff'], ['cream', 'Крем', '#fbf6ec'], ['mint', 'Мята', '#edf8f1'], ['sky', 'Небо', '#edf3ff'],
          ['lavender', 'Лаванда', '#f3efff'], ['rose', 'Роза', '#fff0f3'], ['sand', 'Песок', '#f6efe3']],
};
const prefs = loadPrefs();

function loadPrefs() {
  let saved = {};
  try { saved = JSON.parse(store.get(PREFS_STORE) || '{}') || {}; } catch (e) { saved = {}; }
  const result = { ...DEFAULTS, ...saved };
  const old = store.get('pulsedeck.theme');           // before the preferences object
  if (!saved.theme && old) result.theme = old === 'light' ? 'light' : 'dark';
  if (saved.wave === false && !saved.idle) result.idle = 'none';      // the old «Волна» switch
  if (result.idle === 'stars') result.idle = 'starfield';             // renamed
  result.tiles = (result.tiles || []).filter((t) => TILES[t]);
  result.tileOrder = [...new Set([...(result.tileOrder || []).filter((t) => TILES[t]), ...Object.keys(TILES)])];
  return result;
}
function savePrefs() { store.set(PREFS_STORE, JSON.stringify(prefs)); }

function minutes(text) {
  const [h, m] = String(text || '').split(':').map(Number);
  return (h || 0) * 60 + (m || 0);
}
function currentTheme() {
  if (!prefs.themeByTime) return prefs.theme === 'light' ? 'light' : 'dark';
  const now = new Date();
  const t = now.getHours() * 60 + now.getMinutes();
  const from = minutes(prefs.dayFrom), to = minutes(prefs.dayTo);
  const day = from <= to ? t >= from && t < to : t >= from || t < to;
  return day ? 'light' : 'dark';
}

function applyPrefs() {
  const root = document.documentElement;
  root.dataset.theme = currentTheme();
  root.dataset.accent = prefs.accent;
  root.dataset.clockSize = prefs.clockSize;
  root.dataset.clockWeight = prefs.clockWeight;
  root.dataset.layout = prefs.layout;
  root.dataset.bg = root.dataset.theme === 'light' ? prefs.bgLight : prefs.bgDark;
  root.dataset.uiFont = prefs.uiFont;
  if (!CLOCK_FONTS[prefs.clockFont]) prefs.clockFont = 'system';
  root.dataset.clockFont = prefs.clockFont;
  const clock = CLOCK_COLORS[prefs.clockColor];
  if (clock) root.style.setProperty('--clock-color', clock); else root.style.removeProperty('--clock-color');
  if (prefs.idle !== 'none' && !IDLE[prefs.idle]) prefs.idle = 'wave';     // an unknown or removed saved choice
  $('wave').dataset.kind = prefs.idle;
  root.dataset.idleSize = prefs.idleSize;
  root.classList.toggle('no-motion', !prefs.motion);
  root.classList.toggle('pulse', prefs.pulse && prefs.motion);
  root.classList.toggle('hide-cover', !prefs.showCover);
  root.classList.toggle('hide-progress', !prefs.showProgress);
  root.classList.toggle('hide-volume', !prefs.showVolume);
  $('date').hidden = !prefs.showDate;
  const background = getComputedStyle(root).getPropertyValue('--bg').trim() || '#000000';
  document.querySelector('meta[name="theme-color"]').setAttribute('content', background);
  if (!prefs.burnIn) $('panel').style.transform = '';
  tickClock();
  renderMetrics();
  showMedia({ session: state.media, system_volume: state.volume, keepTime: true });
  showSaver();
  updateBuddy();
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
function uptime(sec) {
  if (sec == null) return '—';
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  return d ? `${d} д ${h} ч` : h ? `${h} ч ${m} мин` : `${m} мин`;
}
const setBar = (el, value) => { el.style.width = (value == null ? 0 : Math.min(100, Math.max(0, value))) + '%'; };
// Short model names for the small tiles: «i5-13420H», «Ryzen 7 5800X», «RTX 3050».
function shortCpu(name) {
  const text = (name || '').replace(/\(R\)|\(TM\)/gi, '');
  const model = text.match(/Core Ultra \d+ \w+|i[3579]-\w+|Ryzen \d+ \w+|Xeon \S+|Apple M\d\w*|Snapdragon \S+ \S+/i);
  return model ? model[0].replace(/^Apple /, '') : text.replace(/CPU|Processor|@.*$/gi, '').replace(/\s+/g, ' ').trim();
}
function shortGpu(name) {
  const text = (name || '').replace(/\(R\)|\(TM\)/gi, '');
  const model = text.match(/(RTX|GTX|RX|Arc) ?[A-Z]?\d{3,4}( ?(Ti|SUPER|XT|XTX))?|(UHD|Iris Xe|Iris|Radeon) Graphics( \d+)?/i);
  return model ? model[0] : text.replace(/NVIDIA |GeForce |AMD |Laptop GPU|\d+GB/gi, '').replace(/\s+/g, ' ').trim();
}

// ----- history for the tiles' sparklines and the detail graphs: the last ~3 minutes -----
const HISTORY_POINTS = 90;
const history = { cpu: [], gpu: [], ram: [], vram: [], down: [], up: [] };
function remember(m) {
  const vram = m.gpu.memory_total && m.gpu.memory_used != null ? 100 * m.gpu.memory_used / m.gpu.memory_total : null;
  const values = { cpu: m.cpu.load, gpu: m.gpu.load, ram: m.ram.percent, vram, down: m.net.down, up: m.net.up };
  for (const [key, value] of Object.entries(values)) {
    history[key].push(value);
    if (history[key].length > HISTORY_POINTS) history[key].shift();
  }
}
const SERIES = { cpu: ['cpu'], gpu: ['gpu'], ram: ['ram'], vram: ['vram'], net: ['down', 'up'] };

// A line graph of one or two series; percent series use 0..100, speeds their own maximum.
function drawGraph(canvas, keys, { fill = true, percent = true } = {}) {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth, height = canvas.clientHeight;
  if (!width || !height) return;
  if (canvas.width !== Math.round(width * ratio)) { canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio); }
  const c = canvas.getContext('2d');
  c.setTransform(ratio, 0, 0, ratio, 0, 0);
  c.clearRect(0, 0, width, height);
  const ink = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#fff';
  const top = percent ? 100 : Math.max(1, ...keys.flatMap((k) => history[k].filter((v) => v != null)));
  keys.forEach((key, index) => {
    const data = history[key];
    if (data.length < 2) return;
    const step = width / (HISTORY_POINTS - 1), start = width - (data.length - 1) * step;
    c.beginPath();
    let started = false;
    data.forEach((v, i) => {
      if (v == null) return;
      const x = start + i * step, y = height - 1 - (Math.min(v, top) / top) * (height - 3);
      if (!started) { c.moveTo(x, y); started = true; } else c.lineTo(x, y);
    });
    c.strokeStyle = ink;
    c.globalAlpha = index ? 0.5 : 1;
    c.lineWidth = index ? 1 : 1.4;
    c.stroke();
    if (fill && index === 0 && started) {
      c.lineTo(width, height); c.lineTo(start, height); c.closePath();
      c.globalAlpha = 0.12; c.fillStyle = ink; c.fill();
    }
    c.globalAlpha = 1;
  });
}

function tickClock() {
  const now = new Date();
  let h = now.getHours();
  const suffix = prefs.clock24 ? '' : (h < 12 ? ' AM' : ' PM');
  if (!prefs.clock24) h = h % 12 || 12;
  const hm = `${prefs.clock24 ? String(h).padStart(2, '0') : h}:${String(now.getMinutes()).padStart(2, '0')}`;
  const time = $('time');
  time.textContent = hm + suffix;
  if (prefs.seconds) {
    const sec = document.createElement('span');
    sec.className = 'sec';
    sec.textContent = String(now.getSeconds()).padStart(2, '0');
    time.append(sec);
  }
  $('date').textContent = now.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' });
  if (prefs.themeByTime && document.documentElement.dataset.theme !== currentTheme()) applyPrefs();
}

// ----- metrics: the panel's bottom row, tiles chosen in Настройки → Плитки -----
function tileData(id, m) {
  const disks = m.disks || [];
  switch (id) {
    case 'cpu': return { value: pct(m.cpu.load), sub: shortCpu(m.cpu.name) || (m.cpu.cores ? `${m.cpu.cores} потоков` : ''), bar: m.cpu.load };
    case 'gpu': return { value: pct(m.gpu.load), sub: (shortGpu(m.gpu.name) || '') + (m.gpu.memory_total ? ` · ${bytes(m.gpu.memory_total)}` : ''), bar: m.gpu.load };
    case 'ram': return { value: pct(m.ram.percent), sub: m.ram.used != null && m.ram.total ? `${bytes(m.ram.used)} / ${bytes(m.ram.total)}` : '', bar: m.ram.percent };
    case 'net': return { value: `↓${speed(m.net.down)}`, sub: `↑ ${speed(m.net.up)}`, bar: undefined };
    case 'disk': {
      const disk = disks.find((d) => d.name === prefs.disk) || disks[0];
      if (!disk) return { name: 'Диск', value: '—', sub: '', bar: null };
      return { name: disk.name, value: bytes(disk.free), sub: `свободно из ${bytes(disk.total)}`,
               bar: disk.total ? 100 * (disk.total - disk.free) / disk.total : null };
    }
    case 'vram': {
      const total = m.gpu.memory_total, used = m.gpu.memory_used;
      return { value: used != null && total ? pct(100 * used / total) : '—',
               sub: used != null && total ? `${bytes(used)} / ${bytes(total)}` : 'нет данных', bar: used != null && total ? 100 * used / total : null };
    }
    case 'cores': {
      const list = m.cpu.per_core || [];
      return { value: list.length ? `${list.length}` : '—', sub: list.length ? `макс. ${pct(Math.max(...list))}` : 'нет данных',
               bar: undefined, cores: list };
    }
    case 'volume': {
      const vol = state.volume;
      return { value: vol ? (vol.muted ? 'без звука' : `${vol.level}%`) : '—', sub: 'громкость ПК', bar: vol ? vol.level : null };
    }
    default: return { value: '—', sub: '', bar: null };
  }
}

function renderMetrics() {
  const box = $('metrics');
  const wanted = prefs.tileOrder.filter((id) => prefs.tiles.includes(id));
  if (box.dataset.tiles !== wanted.join()) {        // rebuild only when the choice changed
    box.dataset.tiles = wanted.join();
    box.replaceChildren(...wanted.map((id) => {
      const cell = document.createElement('div');
      cell.className = 'metric';
      cell.dataset.tile = id;
      cell.setAttribute('role', 'button');
      cell.tabIndex = 0;
      cell.innerHTML = `<svg class="i"><use href="#${TILES[id].icon}"/></svg><div class="body"><div class="head">`
        + `<span></span><b class="num">—</b></div><div class="sub">—</div><div class="bar"><i></i></div>`
        + (SERIES[id] ? '<canvas class="spark"></canvas>' : '') + (id === 'cores' ? '<div class="corestrip"></div>' : '') + '</div>';
      cell.addEventListener('click', () => openDetail(id));
      cell.querySelector('.head span').textContent = TILES[id].name;
      return cell;
    }));
  }
  if (!state.metrics) return;
  for (const cell of box.children) {
    const data = tileData(cell.dataset.tile, state.metrics);
    if (data.name) cell.querySelector('.head span').textContent = data.name;
    cell.querySelector('.head .num').textContent = data.value;
    cell.querySelector('.sub').textContent = data.sub || '—';
    const bar = cell.querySelector('.bar');
    bar.classList.toggle('hidden-bar', data.bar === undefined);
    setBar(bar.querySelector('i'), data.bar);
    const spark = cell.querySelector('.spark');
    if (spark) {
      spark.hidden = !prefs.sparks;
      if (prefs.sparks) drawGraph(spark, SERIES[cell.dataset.tile], { percent: cell.dataset.tile !== 'net' });
    }
    if (data.cores) {
      const strip = cell.querySelector('.corestrip');
      if (strip.children.length !== data.cores.length) strip.replaceChildren(...data.cores.map(() => document.createElement('i')));
      data.cores.forEach((v, i) => { strip.children[i].style.height = `${Math.max(8, v || 0)}%`; });
    }
  }
  if (!$('detail').hidden) renderDetail();
}

// ----- tap a tile: details with a bigger graph -----
let detailId = '';
function openDetail(id) {
  detailId = id;
  $('detail').hidden = false;
  renderDetail();
}
function row(label, value) {
  return el('div', { class: 'drow' }, el('span', { text: label }), el('b', { class: 'num', text: value }));
}
function renderDetail() {
  const m = state.metrics;
  const body = $('detail-body');
  if (!m || !TILES[detailId]) return;
  $('detail-title').textContent = TILES[detailId].title;
  const parts = [];
  if (SERIES[detailId]) {
    const graph = el('canvas', { class: 'dgraph' });
    parts.push(graph, el('div', { class: 'dnote', text: 'последние 3 минуты' }));
    requestAnimationFrame(() => drawGraph(graph, SERIES[detailId], { percent: detailId !== 'net' }));
  }
  if (detailId === 'cpu' || detailId === 'cores') {
    parts.push(row('Нагрузка', pct(m.cpu.load)), row('Процессор', m.cpu.name || '—'), row('Потоков', m.cpu.cores ?? '—'));
    const cores = m.cpu.per_core || [];
    if (cores.length) parts.push(el('div', { class: 'dcores' }, ...cores.map((v, i) => {
      const fill = el('i'); fill.style.height = `${Math.max(2, v || 0)}%`;
      return el('div', { class: 'dcore', title: `Ядро ${i + 1}: ${pct(v)}` }, el('div', { class: 'dcol' }, fill), el('span', { text: String(i + 1) }));
    })));
  } else if (detailId === 'gpu' || detailId === 'vram') {
    const total = m.gpu.memory_total, used = m.gpu.memory_used;
    parts.push(row('Нагрузка', pct(m.gpu.load)), row('Видеокарта', m.gpu.name || '—'),
      row('Видеопамять', used != null && total ? `${bytes(used)} из ${bytes(total)}` : total ? `всего ${bytes(total)}` : '—'));
  } else if (detailId === 'ram') {
    parts.push(row('Занято', m.ram.used != null ? `${bytes(m.ram.used)} (${pct(m.ram.percent)})` : '—'),
      row('Свободно', m.ram.used != null && m.ram.total ? bytes(m.ram.total - m.ram.used) : '—'), row('Всего', bytes(m.ram.total)));
  } else if (detailId === 'net') {
    parts.push(row('Приём ↓', speed(m.net.down)), row('Отдача ↑', speed(m.net.up)),
      el('div', { class: 'dnote', text: 'Яркая линия — приём, бледная — отдача.' }));
  } else if (detailId === 'disk') {
    for (const d of m.disks || []) {
      const fill = el('i'); setBar(fill, d.total ? 100 * (d.total - d.free) / d.total : null);
      parts.push(el('div', { class: 'ddisk' }, row(d.label ? `${d.name} ${d.label}` : d.name, `${bytes(d.free)} свободно из ${bytes(d.total)}`),
        el('div', { class: 'bar' }, fill)));
    }
  } else if (detailId === 'volume') {
    const vol = state.volume;
    parts.push(row('Громкость ПК', vol ? (vol.muted ? 'без звука' : `${vol.level}%`) : '—'),
      el('div', { class: 'dnote', text: 'Менять громкость — ползунком в карточке плеера (нужен доступ «Полный»).' }));
  }
  body.replaceChildren(...parts);
}

// Next to the PC name: how long it has been on, and its battery if it is a laptop.
function showPcStatus(m) {
  $('pc-uptime').hidden = m.uptime == null;
  $('pc-uptime').textContent = m.uptime == null ? '' : `работает ${uptime(m.uptime)}`;
  const b = m.battery;
  $('pc-battery').hidden = !b;
  if (!b) return;
  $('pc-battery-level').setAttribute('width', String(Math.max(0.6, 13.4 * (b.percent || 0) / 100)));
  $('pc-battery-bolt').toggleAttribute('hidden', !b.plugged);
  $('pc-battery-text').textContent = `${Math.round(b.percent)}%`;
  $('pc-battery').classList.toggle('low', b.percent <= 20 && !b.plugged);
  $('pc-battery').title = b.plugged ? `ПК на зарядке: ${Math.round(b.percent)}%` : `Батарея ПК: ${Math.round(b.percent)}%`;
}

let knownDisks = '';
function showMetrics(m) {
  state.metrics = m;
  remember(m);
  showPcStatus(m);
  renderMetrics();
  updateBuddy();
  const disks = (m.disks || []).map((d) => d.name).join();
  if (disks !== knownDisks) {          // «Какой диск» in Настройки lists the PC's disks
    knownDisks = disks;
    buildSettings();
  }
}

// ----- media -----
function showMedia(msg) {
  const s = msg.session;
  if (!msg.keepTime) { state.media = s; state.mediaAt = performance.now(); }
  const showPlayer = !!s || prefs.playerAlways;
  $('player').hidden = !showPlayer;
  $('player').classList.toggle('playing', !!s && s.status === 'playing');
  $('wave').hidden = showPlayer || prefs.idle === 'none';
  $('title').textContent = s ? s.title : 'Ничего не играет';
  $('artist').textContent = s ? [s.artist, s.album].filter(Boolean).join(' · ') : '';
  $('sourcename').textContent = s ? s.source || '' : '';
  $('progress').hidden = !(s && s.duration > 0);
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
  if ('system_volume' in msg) state.volume = msg.system_volume;
  const vol = state.volume;
  $('volumerow').hidden = !vol;
  if (vol && performance.now() - state.volumeBusy > 1500) {      // not while the finger moves the slider
    $('volume').value = vol.level;
    $('volumevalue').textContent = vol.muted ? '0' : String(vol.level);
  }
  showControls();
  tickProgress();
  if (prefs.tiles.includes('volume')) renderMetrics();
  updateBuddy();
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
  for (const button of $('controls').querySelectorAll('button')) button.disabled = !state.control || !s;
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

// ----- idle animation (nothing plays). «Волна» is KiroX Motion of the panel; the others are
// decorative (they do not show real data). Drawn in the accent colour at ~30 fps. -----
const IDLE = {
  wave: { name: 'Волна', h: 28 }, waves: { name: 'Волны', h: 70 }, pulse: { name: 'Пульс', h: 80 },
  eq: { name: 'Эквалайзер', h: 90 }, breathe: { name: 'Дыхание', h: 120 }, orbit: { name: 'Орбиты', h: 120 },
  fireflies: { name: 'Светлячки', h: 110 }, ripples: { name: 'Рябь', h: 120 }, aurora: { name: 'Сияние', h: 110 },
  starfield: { name: 'Звёздное небо', h: 120 }, matrix: { name: 'Матрица', h: 110 },
  spectrum: { name: 'Круговой спектр', h: 150 }, helix: { name: 'ДНК', h: 90 }, pendulum: { name: 'Маятники', h: 120 },
  rain: { name: 'Дождь', h: 120 }, snow: { name: 'Снег', h: 130 }, bubbles: { name: 'Пузырьки', h: 130 },
  voice: { name: 'Голосовая волна', h: 70 }, galaxy: { name: 'Галактика', h: 140 }, grid: { name: 'Сетка точек', h: 120 },
  ring: { name: 'Неоновое кольцо', h: 140 }, dots: { name: 'Три точки', h: 60 }, infinity: { name: 'Бесконечность', h: 100 },
  heart: { name: 'Сердце', h: 120 }, seconds: { name: 'Секундное кольцо', h: 150 }, runner: { name: 'Бегущие точки', h: 80 },
  ocean: { name: 'Океан', h: 110 }, lissajous: { name: 'Лиссажу', h: 120 }, polygon: { name: 'Кристалл', h: 150 },
  confetti: { name: 'Конфетти', h: 130 },
};
// «Размер анимации»: about the player's width, almost the whole width, or all the free space.
const IDLE_SIZES = { normal: 'Обычный', wide: 'Широкий', full: 'Во весь экран' };
const rand = (seed) => { const x = Math.sin(seed * 9301 + 49297) * 233280; return x - Math.floor(x); };
const FLIES = Array.from({ length: 22 }, (_, i) => ({ x: rand(i), y: rand(i + 50), s: 0.4 + rand(i + 99), p: rand(i + 7) * 6.28 }));
const STARS = Array.from({ length: 90 }, (_, i) => ({ x: rand(i) * 2 - 1, y: rand(i + 200) * 2 - 1, z: rand(i + 400) }));
const DROPS = Array.from({ length: 26 }, (_, i) => ({ x: rand(i + 600), v: 0.5 + rand(i + 700), o: rand(i + 800) }));
const GLYPHS = 'ﾊﾐﾋｰｳｼﾅﾓﾆｻﾜﾂｵﾘｱﾎﾃﾏｹﾒｴｶｷﾑﾕﾗｾﾈｽﾀﾇﾍ0123456789';

function rgba(color, alpha) {
  // accent comes as #rrggbb or rgb(...); returns the same colour with this alpha
  const ctx = rgba.ctx || (rgba.ctx = document.createElement('canvas').getContext('2d'));
  ctx.fillStyle = color;
  const hex = ctx.fillStyle;                     // normalised #rrggbb
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function drawIdle(kind, c, w, h, t, ink) {
  const mid = h / 2;
  c.strokeStyle = ink; c.fillStyle = ink;
  if (kind === 'wave') {                  // exactly the panel: 48 steps, sin(i·0.42 − t/135)·2.3, scaled to the width
    const k = w / 144;
    c.beginPath();
    for (let i = 0; i <= 48; i++) {
      const x = (i / 48) * w, y = mid + Math.sin(i * 0.42 - t / 135) * 2.3 * Math.min(k, 2);
      if (i === 0) c.moveTo(x, y); else c.lineTo(x, y);
    }
    c.lineWidth = 1.15 * Math.min(k, 1.6);
    c.stroke();
  } else if (kind === 'waves') {          // three layered sine waves drifting at different speeds
    for (let layer = 0; layer < 3; layer++) {
      c.beginPath();
      for (let x = 0; x <= w; x += 3) {
        const y = mid + Math.sin(x / (38 + layer * 14) - t / (900 - layer * 220) + layer) * (h * (0.32 - layer * 0.08))
          * Math.sin((x / w) * Math.PI);
        if (x === 0) c.moveTo(x, y); else c.lineTo(x, y);
      }
      c.globalAlpha = 0.9 - layer * 0.28;
      c.lineWidth = 2 - layer * 0.4;
      c.stroke();
    }
    c.globalAlpha = 1;
  } else if (kind === 'pulse') {          // the logo's heartbeat running across, with a fading trail and glow
    const period = 2400, head = ((t % period) / period) * (w + 80) - 40;
    c.lineWidth = 2;
    c.shadowColor = ink; c.shadowBlur = 8;
    c.beginPath();
    for (let x = 0; x <= w; x += 2) {
      const d = x - head;
      let y = mid;
      if (d > -26 && d < 0) {
        const u = -d / 26;                // 0..1 along one beat: small bump, big spike, dip
        y = mid - (u < 0.2 ? Math.sin(u / 0.2 * Math.PI) * h * 0.08
          : u < 0.55 ? Math.sin((u - 0.2) / 0.35 * Math.PI) * h * 0.42
            : -Math.sin((u - 0.55) / 0.45 * Math.PI) * h * 0.16);
      }
      if (x === 0) c.moveTo(x, y); else c.lineTo(x, y);
    }
    const fade = c.createLinearGradient(head - w * 0.8, 0, head + 4, 0);
    fade.addColorStop(0, rgba(ink, 0)); fade.addColorStop(1, rgba(ink, 1));
    c.strokeStyle = fade;
    c.stroke();
    c.shadowBlur = 0;
    c.fillStyle = ink;
    if (head >= 0 && head <= w) { c.beginPath(); c.arc(head, mid, 3, 0, Math.PI * 2); c.fill(); }
  } else if (kind === 'eq') {             // rounded bars with a soft reflection; count and width follow the size
    const bars = Math.max(8, Math.min(32, Math.round(w / 22))), slot = w / bars;
    const bw = Math.min(12, slot * 0.55), base = h * 0.72;
    for (let i = 0; i < bars; i++) {
      const v = 0.18 + 0.82 * Math.abs(Math.sin(t / (480 + i * 47) + i * 1.3) * Math.sin(t / 1900 + i * 0.4));
      const bh = v * base, x = i * slot + (slot - bw) / 2;
      c.globalAlpha = 1;
      c.beginPath(); c.roundRect ? c.roundRect(x, base - bh, bw, bh, bw / 2) : c.rect(x, base - bh, bw, bh); c.fill();
      c.globalAlpha = 0.18;
      c.beginPath(); c.roundRect ? c.roundRect(x, base + 3, bw, bh * 0.35, bw / 2) : c.rect(x, base + 3, bw, bh * 0.35); c.fill();
    }
    c.globalAlpha = 1;
  } else if (kind === 'breathe') {        // concentric rings, 4 s in / 4 s out
    const k = 0.5 + 0.5 * Math.sin(t / 1273);
    const r = (Math.min(h / 2, w / 2) - 4) * (0.55 + 0.45 * k);
    for (let ring = 3; ring >= 0; ring--) {
      c.beginPath(); c.arc(w / 2, mid, r * (1 - ring * 0.18), 0, Math.PI * 2);
      c.globalAlpha = (0.12 + 0.5 * k) * (1 - ring * 0.22);
      c.lineWidth = 1.6;
      c.stroke();
    }
    c.globalAlpha = 0.18 * k; c.beginPath(); c.arc(w / 2, mid, r * 0.42, 0, Math.PI * 2); c.fill();
    c.globalAlpha = 1;
  } else if (kind === 'orbit') {          // three planets on tilted ellipses around a glowing sun (shape kept)
    const U = Math.min(w / 2, h * 1.45) * 0.92;
    c.shadowColor = ink; c.shadowBlur = 14;
    c.beginPath(); c.arc(w / 2, mid, Math.max(4, U * 0.05), 0, Math.PI * 2); c.fill();
    c.shadowBlur = 0;
    [[0.95, 3200, 3], [0.68, 5200, 2.4], [0.4, 2100, 1.8]].forEach(([f, period, size], i) => {
      const rx = U * f, ry = Math.min(rx * 0.34, h / 2 - 4), a = (t / period) * Math.PI * 2 + i * 2;
      c.globalAlpha = 0.22; c.lineWidth = 1;
      c.beginPath(); c.ellipse(w / 2, mid, rx, ry, 0, 0, Math.PI * 2); c.stroke();
      c.globalAlpha = 1;
      c.beginPath(); c.arc(w / 2 + Math.cos(a) * rx, mid + Math.sin(a) * ry, size, 0, Math.PI * 2); c.fill();
    });
  } else if (kind === 'fireflies') {      // soft dots drifting and glowing on and off
    c.shadowColor = ink; c.shadowBlur = 10;
    for (const f of FLIES) {
      const x = ((f.x + Math.sin(t / 4000 * f.s + f.p) * 0.08 + t / 90000 * f.s) % 1) * w;
      const y = (f.y + Math.cos(t / 3000 * f.s + f.p) * 0.12) * h;
      c.globalAlpha = 0.25 + 0.75 * Math.max(0, Math.sin(t / 900 * f.s + f.p));
      c.beginPath(); c.arc(x, y, 1.6 + f.s, 0, Math.PI * 2); c.fill();
    }
    c.shadowBlur = 0; c.globalAlpha = 1;
  } else if (kind === 'ripples') {        // rings spreading from the centre, like a drop in water (shape kept)
    const U = Math.min(w * 0.48, (h / 2 - 2) / 0.36);
    for (let i = 0; i < 4; i++) {
      const u = ((t / 3200) + i / 4) % 1;
      c.globalAlpha = (1 - u) * 0.8;
      c.lineWidth = 1.5;
      c.beginPath(); c.ellipse(w / 2, mid, u * U, u * U * 0.36, 0, 0, Math.PI * 2); c.stroke();
    }
    c.globalAlpha = 1;
  } else if (kind === 'aurora') {         // northern lights: soft ribbons of the accent colour
    for (let band = 0; band < 4; band++) {
      const grad = c.createLinearGradient(0, 0, 0, h);
      grad.addColorStop(0, rgba(ink, 0)); grad.addColorStop(0.5, rgba(ink, 0.22 - band * 0.04)); grad.addColorStop(1, rgba(ink, 0));
      c.fillStyle = grad;
      c.beginPath();
      c.moveTo(0, h);
      for (let x = 0; x <= w; x += 6) {
        c.lineTo(x, mid + Math.sin(x / (70 + band * 25) + t / (2600 + band * 700) + band) * h * 0.28
          + Math.sin(x / 23 + t / 1300) * 3 - band * 6);
      }
      c.lineTo(w, h); c.closePath(); c.fill();
    }
    c.fillStyle = ink;
  } else if (kind === 'starfield') {      // flying through stars
    for (const star of STARS) {
      const z = 1 - ((star.z + t / 9000) % 1);
      const x = w / 2 + (star.x / z) * w * 0.12, y = mid + (star.y / z) * h * 0.25;
      if (x < 0 || x > w || y < 0 || y > h) continue;
      c.globalAlpha = Math.min(1, (1 - z) * 1.4);
      c.beginPath(); c.arc(x, y, Math.max(0.4, (1 - z) * 2.2), 0, Math.PI * 2); c.fill();
    }
    c.globalAlpha = 1;
  } else if (kind === 'matrix') {         // falling glyph columns
    const size = 13;
    c.font = `${size}px ui-monospace, Menlo, monospace`;
    c.textAlign = 'center';
    for (const [i, drop] of DROPS.entries()) {
      const x = drop.x * w, head = ((t / 1000 * drop.v * 40 + drop.o * h * 3) % (h + 90)) - 30;
      for (let k = 0; k < 7; k++) {
        const y = head - k * size;
        if (y < 0 || y > h) continue;
        c.globalAlpha = k === 0 ? 1 : (1 - k / 7) * 0.6;
        c.fillText(GLYPHS[(i * 7 + k + Math.floor(t / 180)) % GLYPHS.length], x, y);
      }
    }
    c.globalAlpha = 1;
  } else {
    drawMore(kind, c, w, h, t, ink);
  }
}

const BUBBLES = Array.from({ length: 24 }, (_, i) => ({ x: rand(i + 900), r: 2 + rand(i + 950) * 7, v: 0.3 + rand(i + 990), o: rand(i + 1030) }));
const CONFETTI = Array.from({ length: 46 }, (_, i) => ({ x: rand(i + 1100), v: 0.4 + rand(i + 1150), o: rand(i + 1200),
                                                         s: 3 + rand(i + 1250) * 4, spin: rand(i + 1300) * 6 }));

// The second set of idle animations (12–30).
function drawMore(kind, c, w, h, t, ink) {
  const mid = h / 2, cx = w / 2, R = Math.min(w, h) / 2;
  if (kind === 'spectrum') {             // radial bars around a circle
    const r0 = R * 0.45, n = Math.max(36, Math.min(90, Math.round(r0 * 1.6)));
    c.lineWidth = Math.min(2.4, Math.max(1.2, (Math.PI * 2 * r0) / n * 0.45));
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 + t / 6000;
      const v = 0.15 + 0.85 * Math.abs(Math.sin(t / 420 + i * 0.55) * Math.sin(t / 1700 + i * 0.13));
      const r1 = r0 + 2 + v * R * 0.45;
      c.globalAlpha = 0.45 + 0.55 * v;
      c.beginPath(); c.moveTo(cx + Math.cos(a) * r0, mid + Math.sin(a) * r0); c.lineTo(cx + Math.cos(a) * r1, mid + Math.sin(a) * r1); c.stroke();
    }
    c.globalAlpha = 1;
  } else if (kind === 'helix') {         // DNA: two strands with rungs, turning
    for (let x = 0; x <= w; x += 10) {
      const a = x / 34 + t / 700, y1 = mid + Math.sin(a) * h * 0.36, y2 = mid - Math.sin(a) * h * 0.36;
      const front = Math.cos(a) > 0;
      c.globalAlpha = 0.25; c.lineWidth = 1;
      c.beginPath(); c.moveTo(x, y1); c.lineTo(x, y2); c.stroke();
      c.globalAlpha = front ? 1 : 0.45; c.beginPath(); c.arc(x, y1, front ? 3 : 2, 0, Math.PI * 2); c.fill();
      c.globalAlpha = front ? 0.45 : 1; c.beginPath(); c.arc(x, y2, front ? 2 : 3, 0, Math.PI * 2); c.fill();
    }
    c.globalAlpha = 1;
  } else if (kind === 'rain') {          // thin slanted rain
    c.lineWidth = 1.2;
    for (const [i, d] of DROPS.entries()) {
      const y = ((t / 1000 * (160 + d.v * 140) + d.o * h * 4) % (h + 30)) - 15;
      const x = (d.x * w + y * 0.18 + i * 7) % w;
      c.globalAlpha = 0.35 + 0.5 * d.v;
      c.beginPath(); c.moveTo(x, y); c.lineTo(x - 3, y - 12); c.stroke();
    }
    c.globalAlpha = 1;
  } else if (kind === 'bubbles') {       // bubbles rising with a wobble
    c.lineWidth = 1.2;
    for (const b of BUBBLES) {
      const u = ((t / 1000 * b.v * 0.12) + b.o) % 1;
      const x = b.x * w + Math.sin(t / 700 + b.o * 20) * 6, y = h + b.r - u * (h + b.r * 2);
      c.globalAlpha = 0.25 + 0.6 * Math.sin(u * Math.PI);
      c.beginPath(); c.arc(x, y, b.r, 0, Math.PI * 2); c.stroke();
      c.beginPath(); c.arc(x - b.r * 0.35, y - b.r * 0.35, Math.max(0.6, b.r * 0.18), 0, Math.PI * 2); c.fill();
    }
    c.globalAlpha = 1;
  } else if (kind === 'voice') {         // mirrored waveform, like a voice message
    const n = Math.floor(w / 6);
    for (let i = 0; i < n; i++) {
      const x = i * 6 + 2;
      const env = Math.sin((i / n) * Math.PI);
      const v = (0.15 + 0.85 * Math.abs(Math.sin(i * 0.9 + t / 260) * Math.sin(i * 0.23 - t / 900))) * env;
      c.globalAlpha = 0.5 + 0.5 * env;
      c.fillRect(x, mid - v * h * 0.45, 3, Math.max(2, v * h * 0.9));
    }
    c.globalAlpha = 1;
  } else if (kind === 'galaxy') {        // a rotating spiral of dots
    for (let i = 0; i < 260; i++) {
      const arm = i % 2, k = i / 260;
      const a = k * Math.PI * 5 + arm * Math.PI + t / 3000;
      const r = k * R * 0.95;
      c.globalAlpha = 0.25 + 0.75 * (1 - k);
      c.beginPath(); c.arc(cx + Math.cos(a) * r * (w / h > 2 ? 1.8 : 1), mid + Math.sin(a) * r * 0.6, 0.6 + (1 - k) * 1.6, 0, Math.PI * 2); c.fill();
    }
    c.globalAlpha = 1;
  } else if (kind === 'grid') {          // a grid of dots with a travelling ripple
    const step = 16;
    for (let x = step / 2; x < w; x += step) {
      for (let y = step / 2; y < h; y += step) {
        const d = Math.hypot(x - cx, (y - mid) * 1.6);
        const v = 0.5 + 0.5 * Math.sin(d / 18 - t / 400);
        c.globalAlpha = 0.15 + 0.75 * v;
        c.beginPath(); c.arc(x, y, 0.8 + v * 1.6, 0, Math.PI * 2); c.fill();
      }
    }
    c.globalAlpha = 1;
  } else if (kind === 'dots') {          // three dots bouncing, the «typing» loader
    for (let i = 0; i < 3; i++) {
      const v = Math.max(0, Math.sin(t / 260 - i * 0.7));
      c.globalAlpha = 0.4 + 0.6 * v;
      const r = Math.max(4, Math.min(10, h * 0.11));
      c.beginPath(); c.arc(cx + (i - 1) * r * 3.6, mid - v * h * 0.22, r, 0, Math.PI * 2); c.fill();
    }
    c.globalAlpha = 1;
  } else if (kind === 'infinity') {      // a glowing tracer running along ∞
    const ax = Math.min(w * 0.42, h * 1.15), ay = Math.min(ax * 0.42, h * 0.4);
    c.lineWidth = 1; c.globalAlpha = 0.2; c.beginPath();
    for (let i = 0; i <= 120; i++) { const s = (i / 120) * Math.PI * 2; const x = cx + ax * Math.sin(s), y = mid + ay * Math.sin(s) * Math.cos(s) * 2;
      if (i === 0) c.moveTo(x, y); else c.lineTo(x, y); }
    c.stroke();
    c.shadowColor = ink; c.shadowBlur = 10;
    for (let k = 0; k < 18; k++) {
      const s = t / 900 - k * 0.06;
      c.globalAlpha = 1 - k / 18;
      c.beginPath(); c.arc(cx + ax * Math.sin(s), mid + ay * Math.sin(s) * Math.cos(s) * 2, 3.2 - k * 0.15, 0, Math.PI * 2); c.fill();
    }
    c.shadowBlur = 0; c.globalAlpha = 1;
  } else if (kind === 'heart') {         // a heart beating twice a second… then resting
    const beat = t % 1200, k = beat < 160 ? 1 + 0.12 * Math.sin(beat / 160 * Math.PI) : beat < 360 ? 1 + 0.07 * Math.sin((beat - 160) / 200 * Math.PI) : 1;
    const s = Math.min(w * 0.7 / 32, h * 0.78 / 30) * k;
    c.save(); c.translate(cx, mid + h * 0.04); c.scale(s, s);
    c.beginPath();
    for (let i = 0; i <= 100; i++) { const a = (i / 100) * Math.PI * 2;
      const x = 16 * Math.sin(a) ** 3, y = -(13 * Math.cos(a) - 5 * Math.cos(2 * a) - 2 * Math.cos(3 * a) - Math.cos(4 * a));
      if (i === 0) c.moveTo(x, y); else c.lineTo(x, y); }
    c.restore();
    c.shadowColor = ink; c.shadowBlur = 12 * (k - 0.9) * 5;
    c.lineWidth = 2; c.stroke();
    c.globalAlpha = 0.15 + (k - 1) * 3; c.fill();
    c.shadowBlur = 0; c.globalAlpha = 1;
  } else if (kind === 'seconds') {       // the real seconds of the phone's clock as a ring
    const now = new Date(), sec = now.getSeconds() + now.getMilliseconds() / 1000;
    const r = R * 0.8;
    c.lineWidth = 3; c.globalAlpha = 0.15; c.beginPath(); c.arc(cx, mid, r, 0, Math.PI * 2); c.stroke();
    c.globalAlpha = 1; c.beginPath(); c.arc(cx, mid, r, -Math.PI / 2, -Math.PI / 2 + (sec / 60) * Math.PI * 2); c.stroke();
    for (let i = 0; i < 12; i++) { const a = (i / 12) * Math.PI * 2; c.globalAlpha = 0.35;
      c.beginPath(); c.arc(cx + Math.cos(a) * (r - 9), mid + Math.sin(a) * (r - 9), 1.2, 0, Math.PI * 2); c.fill(); }
    c.globalAlpha = 1;
    c.font = `${Math.round(r * 0.5)}px ui-monospace, Menlo, monospace`; c.textAlign = 'center'; c.textBaseline = 'middle';
    c.fillText(String(Math.floor(sec)).padStart(2, '0'), cx, mid + 1);
    c.textBaseline = 'alphabetic';
  } else if (kind === 'ocean') {         // filled waves, one behind another
    for (let layer = 0; layer < 3; layer++) {
      c.globalAlpha = 0.22 + layer * 0.22;
      c.beginPath(); c.moveTo(0, h);
      for (let x = 0; x <= w; x += 4) {
        c.lineTo(x, h * (0.45 + layer * 0.15) + Math.sin(x / (60 - layer * 12) + t / (1400 - layer * 300) + layer * 2) * h * 0.08);
      }
      c.lineTo(w, h); c.closePath(); c.fill();
    }
    c.globalAlpha = 1;
  } else if (kind === 'lissajous') {     // a slowly morphing Lissajous figure
    const a = 3, b = 2, delta = t / 2500;
    c.lineWidth = 1.4; c.beginPath();
    for (let i = 0; i <= 400; i++) { const s = (i / 400) * Math.PI * 2;
      const rx = Math.min(w * 0.42, h * 0.42 * 1.35), ry = rx / 1.35;
      const x = cx + Math.sin(a * s + delta) * rx, y = mid + Math.sin(b * s) * ry;
      if (i === 0) c.moveTo(x, y); else c.lineTo(x, y); }
    c.globalAlpha = 0.85; c.stroke(); c.globalAlpha = 1;
  } else if (kind === 'polygon') {       // a crystal: nested polygons turning against each other
    c.lineWidth = 1.3;
    for (let ring = 0; ring < 4; ring++) {
      const sides = 6, r = R * (0.85 - ring * 0.18), rot = (ring % 2 ? -1 : 1) * t / (3000 + ring * 900);
      c.globalAlpha = 0.9 - ring * 0.18;
      c.beginPath();
      for (let i = 0; i <= sides; i++) { const ang = rot + (i / sides) * Math.PI * 2;
        const x = cx + Math.cos(ang) * r, y = mid + Math.sin(ang) * r; if (i === 0) c.moveTo(x, y); else c.lineTo(x, y); }
      c.stroke();
    }
    c.globalAlpha = 1;
  } else if (kind === 'pendulum') {     // a pendulum wave: each ball a little slower than the next
    const n = Math.max(9, Math.min(22, Math.round(w / 26))), slot = w / n, r = Math.max(3, Math.min(7, slot * 0.22));
    for (let i = 0; i < n; i++) {
      const y = mid + Math.sin(t / 1000 * (2 + i * 0.12)) * (h / 2 - r - 3);
      c.globalAlpha = 0.25; c.lineWidth = 1;
      c.beginPath(); c.moveTo(i * slot + slot / 2, mid); c.lineTo(i * slot + slot / 2, y); c.stroke();
      c.globalAlpha = 1;
      c.beginPath(); c.arc(i * slot + slot / 2, y, r, 0, Math.PI * 2); c.fill();
    }
  } else if (kind === 'snow') {         // soft flakes drifting down
    for (const f of FLIES) {
      const y = ((t / 1000 * (8 + f.s * 14)) + f.y * h * 3) % (h + 10) - 5;
      const x = (f.x * w + Math.sin(t / 2200 * f.s + f.p) * 14) % w;
      c.globalAlpha = 0.4 + 0.5 * f.s / 1.4;
      c.beginPath(); c.arc(x, y, 1 + f.s * 1.6, 0, Math.PI * 2); c.fill();
    }
    c.globalAlpha = 1;
  } else if (kind === 'ring') {         // a neon arc spinning with a fading tail
    const r = R * 0.78, a = t / 520;
    c.lineWidth = Math.max(2, R * 0.06);
    c.globalAlpha = 0.12; c.beginPath(); c.arc(cx, mid, r, 0, Math.PI * 2); c.stroke();
    c.shadowColor = ink; c.shadowBlur = 12;
    for (let k = 0; k < 24; k++) {
      c.globalAlpha = (1 - k / 24) * 0.9;
      c.beginPath(); c.arc(cx, mid, r, a - k * 0.09 - 0.09, a - k * 0.09); c.stroke();
    }
    c.shadowBlur = 0; c.globalAlpha = 1;
  } else if (kind === 'runner') {       // a row of dots making a travelling sine wave
    const n = Math.max(16, Math.min(48, Math.round(w / 12))), slot = w / n;
    for (let i = 0; i < n; i++) {
      const v = Math.sin(i * 0.42 - t / 260);
      c.globalAlpha = 0.35 + 0.65 * (v + 1) / 2;
      c.beginPath(); c.arc(i * slot + slot / 2, mid + v * h * 0.28, Math.max(1.6, Math.min(4, slot * 0.22)) * (1 + v * 0.25), 0, Math.PI * 2); c.fill();
    }
    c.globalAlpha = 1;
  } else if (kind === 'confetti') {      // slow confetti in the accent colour and its shades
    for (const p of CONFETTI) {
      const y = ((t / 1000 * (25 + p.v * 30)) + p.o * h * 3) % (h + 20) - 10;
      const x = p.x * w + Math.sin(t / 900 + p.o * 10) * 10;
      c.save(); c.translate(x, y); c.rotate(t / 600 * p.spin);
      c.globalAlpha = 0.45 + 0.55 * p.v;
      c.fillRect(-p.s / 2, -p.s / 4, p.s, p.s / 2);
      c.restore();
    }
    c.globalAlpha = 1;
  }
}

// Animations that fill the whole canvas fade out at its edges instead of ending in a hard box.
const SOFT_EDGES = new Set(['waves', 'aurora', 'fireflies', 'starfield', 'matrix', 'rain', 'bubbles', 'grid', 'ocean',
                            'confetti', 'snow', 'helix', 'voice', 'runner']);
function softEdges(c, w, h) {
  c.save();
  c.globalCompositeOperation = 'destination-in';
  const across = c.createLinearGradient(0, 0, w, 0);
  across.addColorStop(0, 'rgba(0,0,0,0)'); across.addColorStop(0.18, 'rgba(0,0,0,1)');
  across.addColorStop(0.82, 'rgba(0,0,0,1)'); across.addColorStop(1, 'rgba(0,0,0,0)');
  c.fillStyle = across;
  c.fillRect(0, 0, w, h);
  const down = c.createLinearGradient(0, 0, 0, h);
  down.addColorStop(0, 'rgba(0,0,0,0)'); down.addColorStop(0.2, 'rgba(0,0,0,1)');
  down.addColorStop(0.8, 'rgba(0,0,0,1)'); down.addColorStop(1, 'rgba(0,0,0,0)');
  c.fillStyle = down;
  c.fillRect(0, 0, w, h);
  c.restore();
}

function idleBox(kind) {
  const free = canvasRoom();
  if (prefs.idleSize === 'full') return [Math.max(120, free.width), Math.max(60, free.height)];
  const width = Math.round(Math.min(prefs.idleSize === 'wide' ? 1100 : 480,
                                    window.innerWidth * (prefs.idleSize === 'wide' ? 0.92 : 0.8)));
  const tall = prefs.idleSize === 'wide' ? 1.35 : 1;
  return [width, Math.round(Math.min(IDLE[kind].h * tall, free.height || window.innerHeight * 0.22))];
}
// The free space between the clock and the tiles (the canvas itself does not count).
function canvasRoom() {
  const center = $('wave').parentElement;
  const box = center.getBoundingClientRect();
  let used = 0;
  for (const child of center.children) if (child !== $('wave') && !child.hidden) used += child.getBoundingClientRect().height;
  return { width: Math.round(box.width), height: Math.round(Math.max(0, box.height - used - 16)) };
}

function startIdle() {
  const canvas = $('wave');
  const context = canvas.getContext('2d');
  let last = 0;
  function frame(now) {
    const kind = prefs.idle;
    if (!canvas.hidden && !document.hidden && IDLE[kind] && now - last > 33) {     // ~30 fps, as the panel
      last = now;
      const ratio = window.devicePixelRatio || 1;
      const [width, height] = idleBox(kind);
      if (canvas.width !== width * ratio || canvas.height !== height * ratio) {
        canvas.width = width * ratio; canvas.height = height * ratio;
        canvas.style.width = `${width}px`; canvas.style.height = `${height}px`;
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      context.lineCap = 'round';
      context.lineJoin = 'round';
      const ink = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#ffffff';
      const still = !prefs.motion || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      drawIdle(kind, context, width, height, still ? 0 : now, ink);
      if (SOFT_EDGES.has(kind)) softEdges(context, width, height);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

// ----- emoji companion: the phone's own emoji, gentle CSS motion -----
// «Котик» reacts to the real PC: asleep when idle, nods while music plays, panics above 85 % CPU,
// sad without a connection.
function catMood() {
  if (!state.online) return 'sad';
  if ((state.metrics?.cpu?.load ?? 0) >= 85) return 'hot';
  if (state.media && state.media.status === 'playing') return 'vibe';
  return 'sleep';
}
const CAT = { sleep: ['😽', '💤'], vibe: ['😸', '🎵'], hot: ['🙀', '🔥'], sad: ['😿', ''] };
let buddyKind = '';
function updateBuddy() {
  const box = $('buddy');
  const kind = $('panel').hidden ? 'none' : prefs.buddy;
  box.hidden = kind === 'none';
  if (kind === 'none') { box.replaceChildren(); buddyKind = ''; return; }
  if (kind === 'cat') {
    const mood = catMood();
    if (buddyKind !== `cat:${mood}`) {
      buddyKind = `cat:${mood}`;
      box.className = `buddy cat ${mood}`;
      const [face, extra] = CAT[mood];
      box.replaceChildren(el('span', { class: 'b face', text: face }),
        extra ? el('span', { class: 'b extra', text: extra }) : null,
        extra ? el('span', { class: 'b extra second', text: extra }) : null);
    }
    return;
  }
  if (buddyKind === kind) return;
  buddyKind = kind;
  box.className = `buddy ${{ walk: 'walk', snow: 'rain', hearts: 'hearts', sparkle: 'sparkle' }[kind]}`;
  const items = [];
  if (kind === 'walk') items.push(el('span', { class: 'b', text: '🐈' }));
  if (kind === 'snow') for (let i = 0; i < 9; i++) {
    const flake = el('span', { class: 'b', text: i % 3 ? '❄️' : '·' });
    flake.style.left = `${(i * 11 + 4) % 100}%`;
    flake.style.animationDuration = `${14 + (i * 7) % 11}s`;
    flake.style.animationDelay = `${-(i * 2.3)}s`;
    flake.style.fontSize = `${12 + (i * 5) % 12}px`;
    items.push(flake);
  }
  if (kind === 'hearts') for (let i = 0; i < 5; i++) {
    const heart = el('span', { class: 'b', text: ['💖', '💗', '💕', '💞', '💓'][i] });
    heart.style.left = `${55 + i * 8}%`;
    heart.style.animationDelay = `${i * 1.9}s`;
    heart.style.animationDuration = `${8 + i}s`;
    items.push(heart);
  }
  if (kind === 'sparkle') for (let i = 0; i < 8; i++) {
    const star = el('span', { class: 'b', text: '✨' });
    star.style.left = `${30 + ((i * 37) % 40)}%`;
    star.style.top = `${4 + ((i * 23) % 30)}%`;
    star.style.animationDelay = `${i * 0.45}s`;
    items.push(star);
  }
  box.replaceChildren(...items);
}

// ----- AMOLED burn-in protection: shift the whole screen a few px every two minutes -----
function startBurnIn() {
  setInterval(() => {
    if (!prefs.burnIn) return;
    const dx = Math.round(Math.random() * 8 - 4), dy = Math.round(Math.random() * 6 - 3);
    $('panel').style.transform = `translate(${dx}px, ${dy}px)`;
  }, 120000);
}

// ----- connection -----
function setStatus(online) {
  state.online = online;
  $('dot').classList.toggle('on', online);
  showSaver();
  updateBuddy();
}

// Without a connection: the clock screensaver (Настройки → Экран) or the «Нет связи» overlay.
function showSaver() {
  const offline = !state.online && !!state.token && !$('panel').hidden;
  document.body.classList.toggle('saver', offline && prefs.offlineClock);
  $('offline').hidden = !(offline && !prefs.offlineClock);
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
  $('offline-text').textContent = 'Переподключаюсь… Проверьте, что PulseDeck запущен, а телефон в той же сети Wi-Fi.';
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

// ----- settings sheet: customisation sections -----
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  node.append(...children.filter(Boolean));
  return node;
}
function icon(id) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'i');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#${id}`);
  svg.append(use);
  return svg;
}
function set(key, value) {
  prefs[key] = value;
  savePrefs();
  applyPrefs();
  buildSettings();
}
const FONTS = [['system', 'Системный'], ['rounded', 'Округлый'], ['mono', 'Моноширинный'], ['serif', 'С засечками']];
// Clock fonts (the CSS stacks: html[data-clock-font] in app.css).
const CLOCK_FONTS = {
  system: ['Системный', 'inherit'],
  rounded: ['Округлый', 'ui-rounded, "SF Pro Rounded", "Arial Rounded MT Bold", "Nunito", sans-serif'],
  condensed: ['Узкий', '"Avenir Next Condensed", "sans-serif-condensed", "Roboto Condensed", "Arial Narrow", sans-serif'],
  geometric: ['Геометрический', 'Futura, "Century Gothic", "Avenir Next", "Product Sans", sans-serif'],
  didot: ['Элегантный', 'Didot, "Bodoni 72", "Bodoni MT", "Noto Serif Display", serif'],
  serif: ['С засечками', 'ui-serif, "New York", Georgia, "Noto Serif", serif'],
  mono: ['Моноширинный', 'ui-monospace, "SF Mono", "Roboto Mono", Menlo, Consolas, monospace'],
  typewriter: ['Машинка', '"American Typewriter", "Cutive Mono", "serif-monospace", "Courier New", monospace'],
  hand: ['Рукописный', '"Snell Roundhand", "Dancing Script", "Segoe Script", cursive'],
  marker: ['Маркер', '"Marker Felt", "Chalkboard SE", "Coming Soon", casual, "Comic Sans MS", cursive'],
};
function fontPicker() {
  return el('div', { class: 'fonts' }, ...Object.entries(CLOCK_FONTS).map(([key, [name, stack]]) => {
    const sample = el('span', { class: 'sample', text: '12:34' });
    sample.style.fontFamily = stack;
    return el('button', { type: 'button', class: prefs.clockFont === key ? 'on' : '', 'aria-label': name,
                          onclick: () => set('clockFont', key) }, sample, el('span', { class: 'name', text: name }));
  }));
}
function chips(key, options, swatch) {
  return el('div', { class: 'chips' }, ...options.map(([value, label, color]) => {
    const button = el('button', { type: 'button', class: (swatch ? 'swatch ' : '') + (prefs[key] === value ? 'on' : ''),
                                  'aria-label': label, title: label, onclick: () => set(key, value) }, swatch ? null : label);
    if (swatch) button.style.background = color;
    return button;
  }));
}
function toggle(key, label) {
  const button = el('button', { type: 'button', class: 'switch', role: 'switch', 'aria-checked': String(!!prefs[key]),
                                'aria-label': label, onclick: () => set(key, !prefs[key]) }, el('i'));
  return el('div', { class: 'pref row' }, el('span', { text: label }), button);
}
function pref(label, control) {
  return el('div', { class: 'pref' }, el('span', { class: 'label', text: label }), control);
}

function buildSettings() {
  const box = $('prefs');
  const accentInk = currentTheme() === 'light' ? '#0a0a0a' : '#ffffff';
  const sections = [
    el('h3', { text: 'Тема и цвет' }),
    pref('Тема', chips('theme', [['dark', 'Тёмная'], ['light', 'Белая']])),
    toggle('themeByTime', 'Белая днём, тёмная вечером'),
    prefs.themeByTime ? el('div', { class: 'times-row' }, 'Белая с',
      el('input', { type: 'time', value: prefs.dayFrom, onchange: (e) => set('dayFrom', e.target.value || '07:00') }),
      'до', el('input', { type: 'time', value: prefs.dayTo, onchange: (e) => set('dayTo', e.target.value || '20:00') })) : null,
    pref('Цвет акцента', chips('accent', [['white', 'Как текст', accentInk], ['blue', 'Синий', '#4c8dff'],
      ['green', 'Зелёный', '#34c77b'], ['purple', 'Фиолетовый', '#a679ff'], ['orange', 'Оранжевый', '#ff9f43'],
      ['red', 'Красный', '#ff5c5c'], ['pink', 'Розовый', '#ff6fb5']], true)),
    currentTheme() === 'light'
      ? pref('Фон (белая тема)', chips('bgLight', BACKGROUNDS.light, true))
      : pref('Фон (тёмная тема)', chips('bgDark', BACKGROUNDS.dark, true)),
    pref('Цвет часов', chips('clockColor', [['ink', 'Как текст', accentInk], ['accent', 'Как акцент', 'var(--accent)'],
      ...Object.entries(CLOCK_COLORS).filter(([k]) => k !== 'accent').map(([k, v]) => [k, COLOR_NAMES[k] || k, v])], true)),

    el('h3', { text: 'Шрифты' }),
    pref('Интерфейс', chips('uiFont', FONTS)),
    pref('Часы', fontPicker()),

    el('h3', { text: 'Раскладка' }),
    chips('layout', [['panel', 'Panel'], ['clock', 'Часы'], ['music', 'Музыка'], ['monitoring', 'Мониторинг']]),

    el('h3', { text: 'Часы' }),
    pref('Толщина', chips('clockWeight', [['thin', 'Тонкие'], ['regular', 'Обычные'], ['bold', 'Жирные']])),
    pref('Размер', chips('clockSize', [['s', 'S'], ['m', 'M'], ['l', 'L']])),
    toggle('clock24', '24 часа'),
    toggle('seconds', 'Секунды'),
    toggle('showDate', 'Дата'),

    el('h3', { text: 'Плитки внизу' }),
    tilesEditor(),
    prefs.tiles.includes('disk') && (state.metrics?.disks || []).length > 1
      ? pref('Какой диск', el('select', { onchange: (e) => set('disk', e.target.value) },
        ...state.metrics.disks.map((d) => { const o = new Option(d.label ? `${d.name} ${d.label}` : d.name, d.name); o.selected = d.name === (prefs.disk || state.metrics.disks[0].name); return o; })))
      : null,

    toggle('sparks', 'Мини-графики в плитках'),
    el('div', { class: 'note-text', text: 'Нажмите на плитку — откроются подробности: большой график, ядра, все диски.' }),

    el('h3', { text: 'Плеер' }),
    toggle('playerAlways', 'Показывать, даже когда ничего не играет'),
    toggle('showCover', 'Обложка'),
    toggle('showProgress', 'Полоса времени'),
    toggle('showVolume', 'Громкость ПК'),

    el('h3', { text: 'Анимации' }),
    pref('Когда ничего не играет', chips('idle', [...Object.entries(IDLE).map(([k, v]) => [k, v.name]), ['none', 'Нет']])),
    prefs.idle !== 'none' ? pref('Размер анимации', chips('idleSize', Object.entries(IDLE_SIZES))) : null,
    pref('Компаньон', chips('buddy', [['none', 'Нет'], ['cat', '🐱 Котик с настроением'], ['walk', '🐈 Котик гуляет'],
      ['hearts', '💖 Сердечки'], ['snow', '❄️ Снегопад'], ['sparkle', '✨ Звёздочки']])),
    prefs.buddy === 'cat' ? el('div', { class: 'note-text',
      text: 'Спит 😽, когда ничего не происходит; качает головой 😸 под музыку; паникует 🙀, если процессор загружен больше 85 %; грустит 😿 без связи с ПК.' }) : null,
    toggle('motion', 'Плавные переходы и анимации'),
    toggle('pulse', 'Обложка пульсирует, пока играет'),

    el('h3', { text: 'Экран' }),
    toggle('burnIn', 'Защита от выгорания (AMOLED)'),
    toggle('offlineClock', 'Без связи — только часы'),
  ];
  box.replaceChildren(...sections.filter(Boolean));
}

function tilesEditor() {
  const order = prefs.tileOrder;
  return el('div', { class: 'tiles' }, ...order.map((id, index) => {
    const checkbox = el('input', { type: 'checkbox', onchange: (e) => {
      set('tiles', e.target.checked ? [...prefs.tiles, id] : prefs.tiles.filter((t) => t !== id));
    } });
    checkbox.checked = prefs.tiles.includes(id);
    const move = (delta) => {
      const next = [...order];
      [next[index], next[index + delta]] = [next[index + delta], next[index]];
      set('tileOrder', next);
    };
    const up = el('button', { type: 'button', class: 'move', 'aria-label': 'Выше', onclick: () => move(-1) }, icon('i-up'));
    const down = el('button', { type: 'button', class: 'move', 'aria-label': 'Ниже', onclick: () => move(1) }, icon('i-down'));
    up.disabled = index === 0;
    down.disabled = index === order.length - 1;
    return el('div', { class: 'tile-row' }, el('label', {}, checkbox, icon(TILES[id].icon), TILES[id].title), up, down);
  }));
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
  applyPrefs();
  buildSettings();
  setInterval(tickClock, 1000);
  setInterval(tickProgress, 1000);
  startIdle();
  startBurnIn();
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
  $('open-settings').addEventListener('click', () => { buildSettings(); $('sheet').hidden = false; });
  $('close-settings').addEventListener('click', () => { $('sheet').hidden = true; });
  $('close-detail').addEventListener('click', () => { $('detail').hidden = true; });
  $('detail').addEventListener('click', (event) => { if (event.target === $('detail')) $('detail').hidden = true; });
  $('sheet').addEventListener('click', (event) => { if (event.target === $('sheet')) $('sheet').hidden = true; });
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
