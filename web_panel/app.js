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
  uptime: { icon: 'i-power', name: 'ПК', title: 'Время работы ПК' },
  volume: { icon: 'i-volume', name: 'Звук', title: 'Громкость ПК' },
};
const DEFAULTS = {
  theme: 'dark', themeByTime: false, dayFrom: '07:00', dayTo: '20:00',
  accent: 'white', clockWeight: 'thin', clockSize: 'm', clock24: true, seconds: false, showDate: true,
  bgDark: 'default', bgLight: 'default', clockColor: 'ink', uiFont: 'system', clockFont: 'system',
  idle: 'wave', buddy: 'none', motion: true, pulse: false,
  layout: 'panel', tiles: ['cpu', 'gpu', 'ram', 'net', 'disk'], tileOrder: Object.keys(TILES), disk: '',
  playerAlways: false, showCover: true, showProgress: true, showVolume: true,
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
  root.dataset.clockFont = prefs.clockFont;
  const clock = CLOCK_COLORS[prefs.clockColor];
  if (clock) root.style.setProperty('--clock-color', clock); else root.style.removeProperty('--clock-color');
  if (prefs.idle !== 'none' && !IDLE[prefs.idle]) prefs.idle = 'wave';     // an unknown saved choice
  $('wave').dataset.kind = prefs.idle;
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
const shortCpu = (name) => (name || '').replace(/\(R\)|\(TM\)|CPU|Processor|@.*$/gi, '').replace(/\s+/g, ' ')
  .replace(/^\d+th Gen /i, '').trim();
const shortGpu = (name) => (name || '').replace(/NVIDIA |GeForce |AMD |Radeon\(TM\) |Laptop GPU|\d+GB/gi, '').replace(/\s+/g, ' ').trim();

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
    case 'uptime': return { value: uptime(m.uptime), sub: 'время работы', bar: undefined };
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
      cell.innerHTML = `<svg class="i"><use href="#${TILES[id].icon}"/></svg><div class="body"><div class="head">`
        + `<span></span><b class="num">—</b></div><div class="sub">—</div><div class="bar"><i></i></div></div>`;
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
  }
}

let knownDisks = '';
function showMetrics(m) {
  state.metrics = m;
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
};
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
  } else if (kind === 'eq') {             // rounded bars with a soft reflection
    const bars = 15, gap = 6, bw = (w - gap * (bars - 1)) / bars, base = h * 0.72;
    for (let i = 0; i < bars; i++) {
      const v = 0.18 + 0.82 * Math.abs(Math.sin(t / (480 + i * 47) + i * 1.3) * Math.sin(t / 1900 + i * 0.4));
      const bh = v * base, x = i * (bw + gap);
      c.globalAlpha = 1;
      c.beginPath(); c.roundRect ? c.roundRect(x, base - bh, bw, bh, bw / 2) : c.rect(x, base - bh, bw, bh); c.fill();
      c.globalAlpha = 0.18;
      c.beginPath(); c.roundRect ? c.roundRect(x, base + 3, bw, bh * 0.35, bw / 2) : c.rect(x, base + 3, bw, bh * 0.35); c.fill();
    }
    c.globalAlpha = 1;
  } else if (kind === 'breathe') {        // concentric rings, 4 s in / 4 s out
    const k = 0.5 + 0.5 * Math.sin(t / 1273);
    const r = (h / 2 - 6) * (0.55 + 0.45 * k);
    for (let ring = 3; ring >= 0; ring--) {
      c.beginPath(); c.arc(w / 2, mid, r * (1 - ring * 0.18), 0, Math.PI * 2);
      c.globalAlpha = (0.12 + 0.5 * k) * (1 - ring * 0.22);
      c.lineWidth = 1.6;
      c.stroke();
    }
    c.globalAlpha = 0.18 * k; c.beginPath(); c.arc(w / 2, mid, r * 0.42, 0, Math.PI * 2); c.fill();
    c.globalAlpha = 1;
  } else if (kind === 'orbit') {          // three planets on tilted ellipses around a glowing sun
    c.shadowColor = ink; c.shadowBlur = 14;
    c.beginPath(); c.arc(w / 2, mid, 6, 0, Math.PI * 2); c.fill();
    c.shadowBlur = 0;
    [[0.42, 0.26, 3200, 3], [0.3, 0.38, 5200, 2.4], [0.18, 0.2, 2100, 1.8]].forEach(([rx, ry, period, size], i) => {
      const a = (t / period) * Math.PI * 2 + i * 2;
      c.globalAlpha = 0.22; c.lineWidth = 1;
      c.beginPath(); c.ellipse(w / 2, mid, w * rx * 0.62, h * ry, 0, 0, Math.PI * 2); c.stroke();
      c.globalAlpha = 1;
      c.beginPath(); c.arc(w / 2 + Math.cos(a) * w * rx * 0.62, mid + Math.sin(a) * h * ry, size, 0, Math.PI * 2); c.fill();
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
  } else if (kind === 'ripples') {        // rings spreading from the centre, like a drop in water
    for (let i = 0; i < 4; i++) {
      const u = ((t / 3200) + i / 4) % 1;
      c.globalAlpha = (1 - u) * 0.8;
      c.lineWidth = 1.5;
      c.beginPath(); c.ellipse(w / 2, mid, u * w * 0.48, u * h * 0.46, 0, 0, Math.PI * 2); c.stroke();
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
  }
}

// Animations that fill the whole canvas fade out at its edges instead of ending in a hard box.
const SOFT_EDGES = new Set(['waves', 'aurora', 'fireflies', 'starfield', 'matrix']);
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

function startIdle() {
  const canvas = $('wave');
  const context = canvas.getContext('2d');
  let last = 0;
  function frame(now) {
    const kind = prefs.idle;
    if (!canvas.hidden && !document.hidden && IDLE[kind] && now - last > 33) {     // ~30 fps, as the panel
      last = now;
      const ratio = window.devicePixelRatio || 1;
      const width = Math.round(Math.min(480, window.innerWidth * 0.8));             // about the player's width
      const height = Math.min(IDLE[kind].h, Math.round(window.innerHeight * 0.22));
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
const FONTS = [['system', 'Системный'], ['rounded', 'Округлый'], ['mono', 'Моноширинный'], ['serif', 'С засечками'],
               ['hand', 'Рукописный']];
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
    pref('Интерфейс', chips('uiFont', FONTS.filter(([k]) => k !== 'hand'))),
    pref('Часы', chips('clockFont', FONTS)),

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

    el('h3', { text: 'Плеер' }),
    toggle('playerAlways', 'Показывать, даже когда ничего не играет'),
    toggle('showCover', 'Обложка'),
    toggle('showProgress', 'Полоса времени'),
    toggle('showVolume', 'Громкость ПК'),

    el('h3', { text: 'Анимации' }),
    pref('Когда ничего не играет', chips('idle', [...Object.entries(IDLE).map(([k, v]) => [k, v.name]), ['none', 'Нет']])),
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
