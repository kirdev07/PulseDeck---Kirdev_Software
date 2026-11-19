// «Управление ПК» in the browser: the screens of the PulseDesk app (PulseDeck-MobileAPP) —
// Управление (power, volume, windows, programs, scenarios, site, search, screenshot), Файлы,
// Процессы, События. The PC serves them with the very handlers of the app under /pc/api/v1/…,
// and only to a browser paired over HTTPS with «Полный» on an HTTPS connection (otherwise
// the screen explains how to get there). Dangerous actions always ask first; files go to the
// Recycle Bin, never a permanent delete. Uses the helpers of app.js ($, el, icon, toast, state).
'use strict';

const pc = {
  tab: 'control', open: false, timer: null, poll: 0,
  windows: null, programs: null, scenarios: null,
  roots: null, folder: null, history: null, processes: null, filter: '', events: null,
};
const PC_TABS = [['control', 'Управление', 'i-remote'], ['files', 'Файлы', 'i-folder'],
  ['processes', 'Процессы', 'i-apps'], ['events', 'События', 'i-bell']];

// ----- the API of the app -----
async function pcApi(path, { method = 'GET', body, query, raw = false } = {}) {
  const url = new URL(`pc/api/v1/${path}`, location.href);
  for (const [key, value] of Object.entries(query || {})) url.searchParams.set(key, value);
  const headers = { Authorization: `Bearer ${state.token}` };
  let payload;
  if (body instanceof Blob) payload = body;
  else if (body !== undefined) { payload = JSON.stringify(body); headers['Content-Type'] = 'application/json'; }
  let response;
  try {
    response = await fetch(url, { method, headers, body: payload, cache: 'no-store' });
  } catch (e) {
    throw new Error('Нет связи с ПК.');
  }
  if (!response.ok) {
    let text = '';
    try { text = (await response.json()).error || ''; } catch (e) { /* not JSON */ }
    throw new Error(text || ({ 401: 'Этот браузер отключён от ПК.', 403: 'ПК не разрешает это действие.',
      404: 'ПК не поддерживает эту функцию. Обновите PulseDeck.', 423: 'ПК заблокирован. Управление недоступно.' })[response.status]
      || `Ошибка ПК (${response.status}).`);
  }
  return raw ? response : response.json();
}
const pcGet = (path, query) => pcApi(path, { query });
const pcPost = (path, body = {}) => pcApi(path, { method: 'POST', body });

// Runs an action; shows the PC's message (or `done`) or the error. Returns the result or null.
async function pcRun(done, work) {
  try {
    const result = await work();
    const text = (result && result.message) || done;
    if (text) toast(text);
    return result || {};
  } catch (e) {
    toast(e.message);
    return null;
  }
}

// ----- dialogs (confirm, choice, text) on the sheet style of the panel -----
function pcDialog(title, body, buttons) {
  return new Promise((resolve) => {
    const close = (value) => { box.remove(); resolve(value); };
    const box = el('div', { class: 'sheet dialog', onclick: (e) => { if (e.target === box) close(null); } },
      el('div', { class: 'sheet-card', role: 'dialog', 'aria-modal': 'true' },
        el('h2', { class: 'dialog-title', text: title }),
        ...(Array.isArray(body) ? body : [body]),
        el('div', { class: 'dialog-buttons' }, ...buttons.map(([label, value, kind]) =>
          el('button', { type: 'button', class: kind || '', text: label, onclick: () => close(typeof value === 'function' ? value() : value) })))));
    document.body.append(box);
    box.querySelector('input')?.focus();
  });
}
const pcConfirm = (text, verb = 'Да') =>
  pcDialog('Подтвердите', el('p', { class: 'muted', text }), [['Отмена', false, 'ghost'], [verb, true, 'primary']]);
function pcAsk(title, value = '', placeholder = '') {
  const input = el('input', { class: 'text-input', type: 'text', value, placeholder, autocomplete: 'off' });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') input.closest('.sheet-card').querySelector('.primary').click(); });
  return pcDialog(title, input, [['Отмена', null, 'ghost'], ['Готово', () => input.value.trim() || null, 'primary']]);
}
function pcPower(kind) {
  const verb = kind === 'restart' ? 'Перезагрузить' : 'Выключить';
  let minutes = 0;
  const options = [[0, 'Через 10 секунд'], [5, 'Через 5 минут'], [15, 'Через 15 минут'], [30, 'Через 30 минут'], [60, 'Через час']];
  const list = el('div', { class: 'choice' }, ...options.map(([value, label]) =>
    el('button', { type: 'button', class: value === 0 ? 'on' : '', text: label, onclick: (e) => {
      minutes = value;
      for (const b of list.children) b.classList.toggle('on', b === e.currentTarget);
    } })));
  return pcDialog(`${verb} ПК?`, [el('p', { class: 'muted', text: 'Несохранённые данные на ПК могут пропасть. Таймер можно отменить.' }), list],
    [['Отмена', null, 'ghost'], [verb, () => minutes, 'primary']]);
}

// ----- the screen -----
function pcAllowed() { return state.control && state.secure; }

function openPc(tab) {
  pc.open = true;
  if (tab) pc.tab = tab;
  $('panel').hidden = true;
  $('pc').hidden = false;
  renderPc();
  pcLoadTab();
  clearInterval(pc.poll);
  pc.poll = setInterval(() => { if (!document.hidden && pc.open && pc.tab === 'control' && pcAllowed()) pcTimer(); }, 5000);
}
function closePc() {
  pc.open = false;
  clearInterval(pc.poll);
  $('pc').hidden = true;
  $('panel').hidden = false;
}

function pcLoadTab() {
  if (!pcAllowed()) return;
  if (pc.tab === 'control') pcTimer();
  if (pc.tab === 'files' && !pc.roots) pcRoots();
  if (pc.tab === 'processes') pcProcesses();
  if (pc.tab === 'events') pcEvents();
}

function renderPc() {
  if (!pc.open) return;
  $('pc-tabs').replaceChildren(...PC_TABS.map(([id, title, ic]) =>
    el('button', { type: 'button', class: id === pc.tab ? 'on' : '', 'aria-label': title,
      onclick: () => { if (pc.tab !== id) { pc.tab = id; renderPc(); pcLoadTab(); $('pc-body').scrollTop = 0; } } },
    icon(ic), el('span', { text: title }))));
  $('pc-title').textContent = PC_TABS.find(([id]) => id === pc.tab)[1];
  const body = $('pc-body');
  if (!pcAllowed()) { body.replaceChildren(pcLocked()); return; }
  body.replaceChildren(...({ control: pcControl, files: pcFiles, processes: pcProcessList, events: pcEventList })[pc.tab]());
}

function pcLocked() {
  let text;
  if (!state.secure) text = 'Управление ПК работает только в защищённом режиме (HTTPS). Установите сертификат ПК: Настройки → «Подключение».';
  else if (state.reason === 'insecure') text = 'Этот браузер подключён без шифрования. На ПК нажмите «Отозвать» и подключите его снова уже по HTTPS.';
  else if (state.reason === 'view') text = 'Этот браузер подключён только для просмотра. На ПК: «Телефон» → «Подключённые устройства» → «Доступ» → «Полный».';
  else text = 'Управление недоступно: ПК заблокирован или нет связи.';
  return el('div', { class: 'card empty' }, icon('i-lock'), el('p', { text }));
}

const section = (title) => el('h3', { class: 'pc-section', text: title });
function listRow(ic, title, sub, onclick, extra) {
  return el('button', { type: 'button', class: 'list-row', onclick },
    ic ? icon(ic) : el('span', { class: 'pad' }),
    el('span', { class: 'row-text' }, el('span', { class: 'row-title', text: title }), sub ? el('span', { class: 'row-sub', text: sub }) : null),
    extra || null);
}
const note = (text) => el('div', { class: 'row-note', text });

// ----- Управление -----
function pcTile(ic, title, onclick) {
  return el('button', { type: 'button', class: 'tile-button', onclick }, icon(ic), el('span', { text: title }));
}
async function pcTimer() {
  try {
    const status = await pcGet('status');
    const was = JSON.stringify(pc.timer);
    pc.timer = status.power || null;
    if (JSON.stringify(pc.timer) !== was && pc.tab === 'control') renderPc();
  } catch (e) { /* the next round */ }
}
function pcControl() {
  const parts = [];
  if (pc.timer) {
    const what = pc.timer.action === 'restart' ? 'Перезагрузка' : 'Выключение';
    const s = pc.timer.seconds;
    parts.push(el('div', { class: 'card timer' }, el('span', { text: `${what} через ${Math.floor(s / 60)} мин ${s % 60} с` }),
      el('button', { type: 'button', class: 'primary', text: 'Отменить',
        onclick: () => pcRun('Отменено', async () => { const r = await pcPost('system/cancel'); pc.timer = null; renderPc(); return r; }) })));
  }
  const power = async (kind) => {
    const minutes = await pcPower(kind);
    if (minutes === null) return;
    const name = kind === 'restart' ? 'Перезагрузка' : 'Выключение';
    await pcRun(minutes ? `${name} через ${minutes} мин. Можно отменить.` : `${name} через 10 с. Можно отменить.`,
      () => pcPost(`system/${kind}`, { minutes }));
    pcTimer();
  };
  const ask = async (text, done, path) => { if (await pcConfirm(text)) pcRun(done, () => pcPost(path)); };
  parts.push(el('div', { class: 'tile-grid' },
    pcTile('i-power', 'Выключить', () => power('shutdown')),
    pcTile('i-restart', 'Перезагрузить', () => power('restart')),
    pcTile('i-moon', 'Сон', () => ask('Перевести ПК в сон? Связь с телефоном прервётся.', 'ПК засыпает', 'system/sleep')),
    pcTile('i-lock', 'Блокировка', () => ask('Заблокировать ПК? Управление с телефона будет недоступно до разблокировки.', 'ПК заблокирован', 'system/lock')),
    pcTile('i-close', 'Закрыть окно', () => ask('Закрыть активное окно на ПК? Несохранённые данные в нём могут пропасть.', 'Окно закрыто', 'system/close_active')),
    pcTile('i-image', 'Скриншот', pcScreenshot)));

  const vol = state.volume;
  if (vol) {
    const value = el('span', { class: 'num', text: vol.muted ? 'без звука' : String(vol.level) });
    const slider = el('input', { type: 'range', min: '0', max: '100', step: '1', 'aria-label': 'Громкость ПК' });
    slider.value = vol.level;
    slider.addEventListener('input', () => { state.volumeBusy = performance.now(); value.textContent = slider.value; });
    slider.addEventListener('change', () => { state.volumeBusy = performance.now(); send('volume', Number(slider.value)); });
    const mute = el('button', { type: 'button', class: `icon-button${vol.muted ? ' muted-on' : ''}`, 'aria-label': 'Без звука',
      onclick: () => pcRun('', () => pcPost('volume', { muted: !(state.volume && state.volume.muted) })) }, icon('i-volume'));
    parts.push(section('Громкость ПК'), el('div', { class: 'card volume-card' }, mute, slider, value));
  }

  parts.push(section('Дополнительно'));
  const card = el('div', { class: 'card list' });
  card.append(listRow('i-window', 'Окна', 'Показать, свернуть, развернуть, закрыть', async () => {
    const r = await pcRun('', () => pcGet('windows'));
    if (r) { pc.windows = stableOrder(pc.windows, r.windows || []); renderPc(); }
  }));
  if (pc.windows) {
    if (!pc.windows.length) card.append(note('Открытых окон нет.'));
    for (const w of pc.windows) card.append(pcWindowRow(w));
  }
  card.append(listRow('i-apps', 'Запустить программу', 'Программы, настроенные в PulseDeck на ПК', async () => {
    const r = await pcRun('', () => pcGet('programs'));
    if (r) { pc.programs = r.programs || []; renderPc(); }
  }));
  if (pc.programs) {
    if (!pc.programs.length) card.append(note('На ПК нет настроенных программ (PulseDeck → Программы).'));
    for (const p of pc.programs) card.append(listRow(null, p.name, '', () => pcRun(`Запущено: ${p.name}`, () => pcPost(`programs/${encodeURIComponent(p.id)}/run`))));
  }
  card.append(listRow('i-pulse', 'Сценарии', 'Несколько программ одной кнопкой', async () => {
    const r = await pcRun('', () => pcGet('scenarios'));
    if (r) { pc.scenarios = r.scenarios || []; renderPc(); }
  }));
  if (pc.scenarios) {
    if (!pc.scenarios.length) card.append(note('Сценариев нет.'));
    for (const s of pc.scenarios) card.append(listRow(null, s.name, `программ: ${s.count}`, () => pcRun('Сценарий запущен', () => pcPost(`scenarios/${encodeURIComponent(s.id)}/run`))));
  }
  card.append(listRow('i-link', 'Открыть сайт', 'В браузере на ПК', async () => {
    const url = await pcAsk('Адрес сайта', '', 'example.com');
    if (url) pcRun('Открыто на ПК', () => pcPost('open_url', { url: /^https?:\/\//i.test(url) ? url : `https://${url}` }));
  }));
  card.append(listRow('i-search', 'Поиск в интернете', 'Google на ПК', async () => {
    const query = await pcAsk('Что найти');
    if (query) pcRun('Открыто на ПК', () => pcPost('search', { query }));
  }));
  parts.push(card);
  return parts;
}

// The PC lists windows in z-order, which changes after every action; keep rows where they were.
function stableOrder(old, fresh) {
  if (!old) return fresh;
  const byHwnd = new Map(fresh.map((w) => [w.hwnd, w]));
  const kept = old.map((w) => byHwnd.get(w.hwnd)).filter(Boolean);
  return kept.concat(fresh.filter((w) => !kept.some((k) => k.hwnd === w.hwnd)));
}
function pcWindowRow(w) {
  const act = async (action, label) => {
    if (action === 'close' && !(await pcConfirm(`Закрыть окно «${w.title}»?`, 'Закрыть'))) return;
    const r = await pcRun(label, () => pcPost(`windows/${w.hwnd}/${action}`));
    if (r) {
      const fresh = await pcGet('windows').catch(() => null);
      if (fresh) { pc.windows = stableOrder(pc.windows, fresh.windows || []); renderPc(); }
    }
  };
  return el('div', { class: 'window-row' }, el('div', { class: 'row-title', text: w.title }),
    el('div', { class: 'chips small' }, ...[['focus', 'Показать'], ['min', 'Свернуть'], ['max', 'Развернуть'], ['close', 'Закрыть']]
      .map(([action, label]) => el('button', { type: 'button', text: label, onclick: () => act(action, '') }))));
}

async function pcScreenshot() {
  toast('Снимаю экран ПК…');
  try {
    const response = await pcApi('screenshot', { query: { monitor: '0', width: String(Math.min(3840, Math.round(screen.width * (devicePixelRatio || 1) * 1.5))) }, raw: true });
    const url = URL.createObjectURL(await response.blob());
    const view = el('div', { class: 'shot', onclick: () => { view.remove(); URL.revokeObjectURL(url); } },
      el('img', { src: url, alt: 'Скриншот ПК' }), el('div', { class: 'shot-hint', text: 'Нажмите, чтобы закрыть' }));
    document.body.append(view);
  } catch (e) {
    toast(e.message);
  }
}

// ----- Файлы -----
async function pcRoots() {
  const r = await pcRun('', () => pcGet('files/roots'));
  if (r) { pc.roots = r.roots || []; if (pc.tab === 'files') renderPc(); }
}
async function pcOpenFolder(path) {
  const r = await pcRun('', () => pcGet('files/list', { path }));
  if (r) { pc.folder = r; pc.history = null; renderPc(); $('pc-body').scrollTop = 0; }
}
function fileSize(n) { return n ? bytes(n) : ''; }
function pcFiles() {
  const parts = [];
  // the deepest root that holds the open folder (Рабочий стол, not also «Диск C:»)
  const inside = (pc.roots || []).filter((r) => pc.folder && pc.folder.path.toLowerCase().startsWith(r.path.toLowerCase()))
    .sort((a, b) => b.path.length - a.path.length)[0];
  parts.push(el('div', { class: 'chips' }, ...(pc.roots || []).map((root) =>
    el('button', { type: 'button', class: root === inside ? 'on' : '', text: root.name,
      onclick: () => pcOpenFolder(root.path) }))));
  const upload = el('input', { type: 'file', hidden: '' });
  upload.addEventListener('change', () => { if (upload.files[0]) pcUpload(upload.files[0]); });
  parts.push(el('div', { class: 'file-actions' },
    el('button', { type: 'button', class: 'ghost', onclick: () => upload.click() }, icon('i-upload'), el('span', { text: 'Отправить на ПК' })),
    el('button', { type: 'button', class: 'ghost', onclick: async () => {
      const r = await pcRun('', () => pcGet('history'));
      if (r) { pc.history = r.history || []; renderPc(); }
    } }, icon('i-download'), el('span', { text: 'История' })), upload));
  if (pc.history) {
    parts.push(section('История передач'));
    const card = el('div', { class: 'card list' });
    if (!pc.history.length) card.append(note('Передач ещё не было.'));
    for (const t of pc.history.slice(0, 50)) {
      const ok = ['sent', 'received'].includes(t.status);
      card.append(el('div', { class: 'list-row static' }, icon(t.direction === 'incoming' ? 'i-upload' : 'i-download'),
        el('span', { class: 'row-text' }, el('span', { class: 'row-title', text: t.name }),
          el('span', { class: 'row-sub', text: `${t.time} · ${t.direction === 'incoming' ? 'на ПК' : 'с ПК'}${ok ? '' : ' · ошибка'}` }))));
    }
    parts.push(card);
    return parts;
  }
  if (!pc.folder) { parts.push(note(pc.roots ? 'Выберите диск или папку.' : 'Загружаю…')); return parts; }
  const f = pc.folder;
  parts.push(el('div', { class: 'path-row' },
    f.parent ? el('button', { type: 'button', class: 'icon-button', 'aria-label': 'Вверх', onclick: () => pcOpenFolder(f.parent) }, icon('i-up')) : null,
    el('span', { class: 'path', text: f.path }),
    el('button', { type: 'button', class: 'icon-button', 'aria-label': 'Новая папка', onclick: async () => {
      const name = await pcAsk('Новая папка');
      if (name && await pcRun('Папка создана', () => pcPost('files/mkdir', { path: f.path, name }))) pcOpenFolder(f.path);
    } }, icon('i-plus'))));
  const card = el('div', { class: 'card list' });
  if (!f.items.length) card.append(note('Папка пуста.'));
  const sep = f.path.endsWith('\\') ? '' : '\\';
  for (const item of f.items.slice(0, 500)) {
    const full = f.path + sep + item.name;
    card.append(listRow(item.dir ? 'i-folder' : 'i-file', item.name, item.dir ? '' : fileSize(item.size),
      () => (item.dir ? pcOpenFolder(full) : pcFileMenu(full, item))));
  }
  if (f.items.length > 500) card.append(note(`Показаны первые 500 из ${f.items.length}.`));
  parts.push(card);
  return parts;
}
async function pcFileMenu(path, item) {
  const choice = await pcDialog(item.name, el('p', { class: 'muted', text: fileSize(item.size) }),
    [['Скачать', 'download', 'primary'], ['Переименовать', 'rename', 'ghost'], ['В корзину', 'delete', 'ghost'], ['Отмена', null, 'ghost']]);
  const folder = pc.folder.path;
  if (choice === 'download') pcDownload(path, item.name);
  if (choice === 'rename') {
    const name = await pcAsk('Новое имя', item.name);
    if (name && name !== item.name && await pcRun('Переименовано', () => pcPost('files/rename', { path, name }))) pcOpenFolder(folder);
  }
  if (choice === 'delete' && await pcConfirm(`Переместить «${item.name}» в корзину на ПК? Его можно будет восстановить.`, 'В корзину')) {
    if (await pcRun('Перемещено в корзину', () => pcPost('files/delete', { path }))) pcOpenFolder(folder);
  }
}
async function pcDownload(path, name) {
  toast(`Скачиваю «${name}»…`);
  try {
    const response = await pcApi('files/download', { query: { path }, raw: true });
    const blob = await response.blob();
    const standalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone;
    const file = typeof File === 'function' ? new File([blob], name, { type: blob.type || 'application/octet-stream' }) : null;
    if (standalone && file && navigator.canShare && navigator.canShare({ files: [file] })) {
      // An app from the home screen has no downloads: the share sheet saves it («Сохранить в Файлы»).
      // It needs a fresh tap, so the file waits for «Сохранить».
      const shared = (e) => { if (e && e.name !== 'AbortError') toast('Не удалось сохранить файл.'); };
      await pcDialog(name, el('p', { class: 'muted', text: `Файл получен (${fileSize(blob.size)}).` }),
        [['Отмена', false, 'ghost'], ['Сохранить', () => { navigator.share({ files: [file] }).catch(shared); return true; }, 'primary']]);
      return;
    }
    const url = URL.createObjectURL(blob);
    const link = el('a', { href: url, download: name });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (e) {
    toast(e.message);
  }
}
async function pcUpload(file) {
  if (file.size > 200 * 1024 * 1024) { toast('Файл больше 200 МБ.'); return; }
  toast(`Отправляю «${file.name}»…`);
  await pcRun('Отправлено на ПК', () => pcApi('files/upload', { method: 'POST', body: file, query: { name: file.name } }));
}

// ----- Процессы -----
async function pcProcesses() {
  const r = await pcRun('', () => pcGet('processes'));
  if (r) { pc.processes = r.processes || []; if (pc.tab === 'processes') renderPc(); }
}
function pcProcessList() {
  const search = el('input', { class: 'text-input', type: 'search', placeholder: 'Поиск процесса', value: pc.filter });
  const card = el('div', { class: 'card list' });
  const fill = () => {
    const q = pc.filter.toLowerCase();
    const items = (pc.processes || []).filter((p) => !q || p.name.toLowerCase().includes(q))
      .sort((a, b) => (b.cpu - a.cpu) || (b.memory - a.memory)).slice(0, 150);
    card.replaceChildren(...(pc.processes ? (items.length ? items : [null]) : [undefined]).map((p) => {
      if (p === undefined) return note('Загружаю…');
      if (p === null) return note('Ничего не найдено.');
      const end = p.protected ? null : el('button', { type: 'button', class: 'chip-button', text: 'Завершить', onclick: async (e) => {
        e.stopPropagation();
        if (!(await pcConfirm(`Завершить «${p.name}» (PID ${p.pid})? Несохранённые данные в нём пропадут.`, 'Завершить'))) return;
        if (await pcRun('', () => pcPost(`processes/${p.pid}/kill`))) pcProcesses();
      } });
      return el('div', { class: 'list-row static' }, el('span', { class: 'row-text' }, el('span', { class: 'row-title', text: p.name }),
        el('span', { class: 'row-sub', text: `CPU ${Math.round(p.cpu)}% · ${bytes(p.memory)} · PID ${p.pid}` })), end);
    }));
  };
  search.addEventListener('input', () => { pc.filter = search.value; fill(); });
  fill();
  return [el('div', { class: 'search-row' }, search,
    el('button', { type: 'button', class: 'icon-button', 'aria-label': 'Обновить', onclick: pcProcesses }, icon('i-restart'))), card];
}

// ----- События -----
async function pcEvents() {
  const r = await pcRun('', () => pcGet('events', { after: '0' }));
  if (r) { pc.events = (r.events || []).slice().reverse(); if (pc.tab === 'events') renderPc(); }
}
function pcEventList() {
  const card = el('div', { class: 'card list' });
  if (!pc.events) card.append(note('Загружаю…'));
  else if (!pc.events.length) card.append(note('Событий пока нет: блокировка ПК, предупреждения о нагрузке появятся здесь.'));
  else for (const e of pc.events) {
    card.append(el('div', { class: 'list-row static' }, icon('i-bell'),
      el('span', { class: 'row-text' }, el('span', { class: 'row-title', text: e.title }),
        el('span', { class: 'row-sub', text: [e.time, e.text].filter(Boolean).join(' · ') }))));
  }
  return [card];
}

// The access may change while the screen is open (revoked, «Полный» switched on, PC locked).
function pcAccessChanged() { if (pc.open) { renderPc(); pcLoadTab(); } }

// The PC volume changed (slider, mute, keys on the PC): redraw the card, not while it is dragged.
let pcVolumeShown = '';
function pcVolumeChanged() {
  const now = JSON.stringify(state.volume);
  if (now === pcVolumeShown) return;
  pcVolumeShown = now;
  if (pc.open && pc.tab === 'control' && pcAllowed() && performance.now() - state.volumeBusy > 1500) renderPc();
}
