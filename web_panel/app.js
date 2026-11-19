// PulseDeck Panel in the browser. The browser pairs once with the 6-digit code from
// «Телефон» on the PC (POST /pair) and keeps its own token; then it talks to PulseDeck
// over a WebSocket (/ws). Values come from the PC as they are; unknown ones stay «—».
// Messages as for the Android panel: hello, metrics, media, error; plus access (control on/off).
'use strict';

const TOKEN_STORE = 'pulsedeck.token';
const $ = (id) => document.getElementById(id);
const state = { token: '', ws: null, retry: 0, control: false, media: null, mediaAt: 0, coverKey: '' };

// ----- token of this browser -----
function loadToken() {
  try { return localStorage.getItem(TOKEN_STORE) || ''; } catch (e) { return ''; }
}
function saveToken(token) {
  state.token = token;
  try { localStorage.setItem(TOKEN_STORE, token); } catch (e) { /* private mode: only for this visit */ }
}
function forgetToken(reason) {
  try { localStorage.removeItem(TOKEN_STORE); } catch (e) { /* ignore */ }
  state.token = '';
  if (state.ws) state.ws.close();
  showPairing(reason);
}

// «Браузер (iPhone)», «Браузер (Android)» … — the name shown in «Телефон» on the PC.
function deviceName() {
  const ua = navigator.userAgent;
  const where = /iPad/.test(ua) ? 'iPad' : /iPhone/.test(ua) ? 'iPhone' : /Android/.test(ua) ? 'Android'
    : /Mac OS X/.test(ua) ? 'Mac' : /Windows/.test(ua) ? 'Windows' : 'устройство';
  return `Браузер (${where})`;
}

// ----- pairing -----
function showPairing(reason) {
  $('panel').hidden = true;
  $('offline').hidden = true;
  $('pairing').hidden = false;
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
    saveToken(data.token);
    $('pairing').hidden = true;
    $('panel').hidden = false;
    connect();
  } catch (e) {
    showPairing(e.message === 'Failed to fetch' ? 'Нет связи с ПК. Телефон в той же сети Wi-Fi?' : e.message);
  } finally {
    $('pairbtn').disabled = false;
    $('pairbtn').textContent = 'Подключить';
  }
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
  showControls();
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
  tickProgress();
}

function showControls() {
  const s = state.media;
  $('controls').hidden = !(s && state.control);
  $('playbtn').textContent = s && s.status === 'playing' ? '⏸' : '▶';
  $('playbtn').setAttribute('aria-label', s && s.status === 'playing' ? 'Пауза' : 'Играть');
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
      state.control = !!msg.control;
      setStatus(state.control ? 'Подключено · управление музыкой' : 'Подключено · просмотр', true);
      $('offline').hidden = true;
      $('pairing').hidden = true;
      $('panel').hidden = false;
      showControls();
    } else if (msg.type === 'access') {
      state.control = !!msg.control;
      setStatus(state.control ? 'Подключено · управление музыкой' : 'Подключено · просмотр', true);
      showControls();
    } else if (msg.type === 'metrics') {
      showMetrics(msg);
    } else if (msg.type === 'media') {
      showMedia(msg);
    } else if (msg.type === 'error') {
      flash(msg.message || 'Ошибка');
    }
  };
  ws.onclose = (event) => {
    if (state.ws === ws) state.ws = null;
    if (event.code === 4001) {          // «Отозвать» on the PC
      forgetToken('Доступ этого телефона отозван на ПК. Чтобы подключиться снова, покажите новый код.');
      return;
    }
    if (!opened && state.token) {
      // Refused before opening: either the token is unknown (revoked while offline) or the PC is away.
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
  setStatus('Нет связи', false);
  if (!$('panel').hidden) {
    $('offline').hidden = false;
    $('offline-text').textContent = 'Переподключаюсь… Проверьте, что PulseDeck запущен, а телефон в той же сети Wi-Fi.';
  }
  const delay = Math.min(15000, 1000 * 2 ** state.retry++);
  setTimeout(() => { if (!state.ws && state.token) connect(); }, delay);
}

let flashTimer = 0;
function flash(text) {
  $('message').textContent = text;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { $('message').textContent = ''; }, 4000);
}

// ----- keep the screen on (Wake Lock: Chrome, Safari 16.4+) -----
let wakeLock = null;
let wantAwake = false;
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
  $('awake').addEventListener('click', () => { wantAwake = !wakeLock; keepAwake(wantAwake); });
  updateAwakeButton();
  // The browser drops the lock when the tab is hidden; take it again on return.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && wantAwake && wakeLock === null) keepAwake(true);
  });
  $('codeinput').addEventListener('input', (event) => {
    const digits = event.target.value.replace(/\D/g, '').slice(0, 6);
    event.target.value = digits.length > 3 ? `${digits.slice(0, 3)} ${digits.slice(3)}` : digits;
  });
  $('pairform').addEventListener('submit', (event) => {
    event.preventDefault();
    pair($('codeinput').value);
  });

  // QR code from the PC: http://pc:8780/#pair=123456 — the code is used once, then removed.
  const fromQr = new URLSearchParams(location.hash.slice(1)).get('pair');
  if (fromQr) history.replaceState(null, '', location.pathname);
  state.token = loadToken();
  if (fromQr && !state.token) {
    showPairing();
    $('codeinput').value = fromQr;
    pair(fromQr);
    return;
  }
  if (!state.token) { showPairing(); return; }
  $('panel').hidden = false;
  connect();
});
