// PulseDeck Panel in the browser. Talks to PulseDeck on the PC over a WebSocket (/ws) with
// the access key from the link (#k=…). Values come from the PC as they are; unknown ones
// stay «—». Same messages as the Android panel: hello, metrics, media, error.
'use strict';

const KEY_STORE = 'pulsedeck.key';
const $ = (id) => document.getElementById(id);
const state = { key: '', ws: null, retry: 0, control: false, media: null, mediaAt: 0, coverKey: '' };

// ----- key: from the link's #fragment (never sent to the server in the URL), then remembered -----
function readKey() {
  const hash = new URLSearchParams(location.hash.slice(1));
  const fromLink = hash.get('k');
  if (fromLink) {
    try { localStorage.setItem(KEY_STORE, fromLink); } catch (e) { /* private mode: keep it in memory */ }
    history.replaceState(null, '', location.pathname);   // the key does not stay in the address bar
    return fromLink;
  }
  try { return localStorage.getItem(KEY_STORE) || ''; } catch (e) { return ''; }
}

function forgetKey(reason) {
  try { localStorage.removeItem(KEY_STORE); } catch (e) { /* ignore */ }
  state.key = '';
  showNoKey(reason);
}

function showNoKey(reason) {
  $('panel').hidden = true;
  $('offline').hidden = true;
  $('nokey').hidden = false;
  if (reason) $('nokey').querySelector('p').textContent = reason;
}

// ----- formatting -----
const pct = (v) => (v == null ? '—' : Math.round(v));
function bytes(v) {
  if (v == null) return '—';
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return (v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)).toString().replace('.', ',') + ' ' + units[i];
}
const speed = (v) => (v == null ? '—' : bytes(v) + '/с');
function uptime(sec) {
  if (sec == null) return '—';
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  return d ? `${d} д ${h} ч` : h ? `${h} ч ${m} мин` : `${m} мин`;
}
function clockTime(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = String(sec % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}
const setBar = (el, value) => { el.style.width = (value == null ? 0 : Math.min(100, Math.max(0, value))) + '%'; };

// ----- clock (phone time) -----
function tickClock() {
  const now = new Date();
  $('time').textContent = now.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  $('date').textContent = now.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' });
}

// ----- metrics -----
function tile(id, load, sub) {
  const el = $(id);
  el.querySelector('.num').textContent = pct(load);
  setBar(el.querySelector('.bar i'), load);
  el.querySelector('.sub').textContent = sub || '—';
}

function showMetrics(m) {
  tile('cpu', m.cpu.load, m.cpu.name || (m.cpu.cores ? `${m.cpu.cores} потоков` : ''));
  const ramSub = m.ram.used != null && m.ram.total ? `${bytes(m.ram.used)} из ${bytes(m.ram.total)}` : '';
  tile('ram', m.ram.percent, ramSub);
  let gpuSub = m.gpu.name || '';
  if (m.gpu.memory_total && m.gpu.memory_used != null) gpuSub += ` · ${bytes(m.gpu.memory_used)} / ${bytes(m.gpu.memory_total)}`;
  tile('gpu', m.gpu.load, gpuSub);

  const cores = $('cpu').querySelector('.cores');
  const list = m.cpu.per_core || [];
  if (cores.children.length !== list.length) cores.replaceChildren(...list.map(() => document.createElement('i')));
  list.forEach((v, i) => { cores.children[i].style.height = Math.max(3, (v || 0) * 0.32) + 'px'; });

  $('down').textContent = speed(m.net.down);
  $('up').textContent = speed(m.net.up);
  $('uptime').textContent = uptime(m.uptime);

  const disks = $('disks');
  disks.replaceChildren(...(m.disks || []).map((d) => {
    const used = d.total ? 100 * (d.total - d.free) / d.total : null;
    const row = document.createElement('div');
    const head = document.createElement('div');
    head.className = 'disk-head';
    const name = document.createElement('span');
    name.textContent = d.label ? `${d.name} ${d.label}` : d.name;
    const free = document.createElement('span');
    free.textContent = `свободно ${bytes(d.free)} из ${bytes(d.total)}`;
    head.append(name, free);
    const bar = document.createElement('div');
    bar.className = 'bar';
    const fill = document.createElement('i');
    bar.append(fill);
    setBar(fill, used);
    row.append(head, bar);
    return row;
  }));
  if (!m.disks || !m.disks.length) disks.textContent = '—';
}

// ----- media -----
function showMedia(msg) {
  const s = msg.session;
  state.media = s;
  state.mediaAt = performance.now();
  $('title').textContent = s ? s.title : 'Ничего не играет';
  $('artist').textContent = s ? [s.artist, s.album].filter(Boolean).join(' · ') : '';
  $('source').textContent = s ? (s.status === 'playing' ? 'Играет' : 'Пауза') + (s.source ? ' · ' + s.source : '') : 'Сейчас играет';
  $('progress').hidden = !(s && s.duration > 0);
  $('controls').hidden = !(s && state.control);
  $('playbtn').textContent = s && s.status === 'playing' ? '⏸' : '▶';
  $('playbtn').setAttribute('aria-label', s && s.status === 'playing' ? 'Пауза' : 'Играть');
  const coverKey = s && s.cover ? s.cover : '';
  if (coverKey !== state.coverKey) {
    state.coverKey = coverKey;
    const img = $('coverimg');
    if (coverKey) {
      img.onload = () => { img.hidden = false; };
      img.onerror = () => { img.hidden = true; };
      img.src = `cover?key=${encodeURIComponent(coverKey)}&k=${encodeURIComponent(state.key)}`;
    } else {
      img.hidden = true;
      img.removeAttribute('src');
    }
  }
  tickProgress();
}

function tickProgress() {
  const s = state.media;
  if (!s || !(s.duration > 0)) return;
  let pos = s.position || 0;
  if (s.status === 'playing') pos += (performance.now() - state.mediaAt) / 1000;   // between updates from the PC
  pos = Math.min(pos, s.duration);
  setBar($('seek'), 100 * pos / s.duration);
  $('pos').textContent = clockTime(pos);
  $('dur').textContent = clockTime(s.duration);
}

// ----- connection -----
function setStatus(text, online) {
  $('state').textContent = text;
  $('dot').classList.toggle('on', online);
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws?k=${encodeURIComponent(state.key)}`);
  state.ws = ws;
  let opened = false;
  ws.onopen = () => { opened = true; state.retry = 0; };
  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch (e) { return; }
    if (msg.type === 'hello') {
      $('pcname').textContent = msg.name || 'ПК';
      state.control = !!msg.control;
      setStatus('Подключено', true);
      $('offline').hidden = true;
      $('panel').hidden = false;
      $('nokey').hidden = true;
    } else if (msg.type === 'metrics') {
      showMetrics(msg);
    } else if (msg.type === 'media') {
      showMedia(msg);
    } else if (msg.type === 'error') {
      flash(msg.message || 'Ошибка');
    }
  };
  ws.onclose = (event) => {
    state.ws = null;
    if (!opened && state.retry >= 1) {
      // The server refuses the key with HTTP 403 before the socket opens; ask the PC how it is.
      fetch(`cover?key=&k=${encodeURIComponent(state.key)}`, { cache: 'no-store' }).then((r) => {
        if (r.status === 403) forgetKey('Ключ доступа больше не действует (на ПК создан новый). Отсканируйте новый QR-код: PulseDeck → Настройки → Веб-панель.');
        else scheduleReconnect();
      }).catch(scheduleReconnect);
      return;
    }
    scheduleReconnect(event.code);
  };
}

function scheduleReconnect() {
  if (!state.key) return;
  setStatus('Нет связи', false);
  if (!$('panel').hidden) {
    $('offline').hidden = false;
    $('offline-text').textContent = 'Переподключаюсь… Проверьте, что PulseDeck запущен, а телефон в той же сети Wi-Fi.';
  }
  const delay = Math.min(15000, 1000 * 2 ** state.retry++);
  setTimeout(() => { if (!state.ws && state.key) connect(); }, delay);
}

let flashTimer = 0;
function flash(text) {
  $('message').textContent = text;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { $('message').textContent = ''; }, 4000);
}

// ----- keep the screen on (Wake Lock: Chrome, Safari 16.4+) -----
let wakeLock = null;
async function keepAwake(on) {
  try {
    if (on && 'wakeLock' in navigator) {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => { wakeLock = null; updateAwakeButton(); });
    } else if (wakeLock) {
      await wakeLock.release();
      wakeLock = null;
    }
  } catch (e) {
    flash('Браузер не разрешил держать экран включённым.');
  }
  updateAwakeButton();
}
function updateAwakeButton() {
  const button = $('awake');
  if (!('wakeLock' in navigator)) { button.hidden = true; return; }
  button.textContent = wakeLock ? 'Экран не гаснет ✓' : 'Не гасить экран';
}

// ----- start -----
document.addEventListener('DOMContentLoaded', () => {
  tickClock();
  setInterval(tickClock, 1000);
  setInterval(tickProgress, 1000);
  $('controls').addEventListener('click', (event) => {
    const cmd = event.target.closest('button')?.dataset.cmd;
    if (cmd && state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify({ type: 'command', action: cmd }));
  });
  let wantAwake = false;
  $('awake').addEventListener('click', () => { wantAwake = !wakeLock; keepAwake(wantAwake); });
  updateAwakeButton();
  // The browser drops the lock when the tab is hidden; take it again on return.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && wantAwake && wakeLock === null) keepAwake(true);
  });
  $('keyform').addEventListener('submit', (event) => {
    event.preventDefault();
    let value = $('keyinput').value.trim();
    const match = value.match(/[#&]k=([^&]+)/);       // a whole link pasted
    if (match) value = decodeURIComponent(match[1]);
    if (value.length < 16) { $('keyinput').focus(); return; }
    try { localStorage.setItem(KEY_STORE, value); } catch (e) { /* ignore */ }
    state.key = value;
    $('nokey').hidden = true;
    $('panel').hidden = false;
    connect();
  });

  state.key = readKey();
  if (!state.key) { showNoKey(); return; }
  $('panel').hidden = false;
  connect();
});
