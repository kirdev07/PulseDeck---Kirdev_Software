// The PC's track on the phone's lock screen and in Control Centre / the notification shade
// (Media Session API): title, artist, cover, position, and the buttons play/pause,
// previous/next, seek — they control the music on the PC.
//
// A browser shows that player only for a page that plays sound itself, so while this is on the
// page plays silence.wav in a loop (true silence; it does take the phone's audio, so music in
// another app on the phone pauses — that is how iOS works). It starts only from a tap (browser
// rule): the switch in Настройки, or the first tap on the page after it was switched on.
// Buttons work only where music control is allowed (HTTPS + «Полный»); otherwise view only.
// iPhone: the audio session is «playback» (iOS 17+), otherwise iOS stops the sound when the
// phone locks and the player disappears; the sound never pauses (after ~30 s on pause iOS
// drops the player), and if iOS pauses it (a call, Siri) it starts again on the next tap.
'use strict';

const lockScreen = { audio: null, on: false, waiting: false, cover: '' };
// A short report to the PC log (Журнал PulseDeck): the phone has no console to look at.
function lockLog(text) {
  try {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify({ type: 'log', text: `плеер блокировки: ${text}` }));
  } catch (e) { /* not important */ }
}
const lockScreenSupported = () => 'mediaSession' in navigator && typeof MediaMetadata === 'function';

function lockHandlers(active) {
  const ms = navigator.mediaSession;
  const playing = () => !!state.media && state.media.status === 'playing';
  const handlers = {
    play: () => { if (!playing()) send('toggle'); },
    pause: () => { if (playing()) send('toggle'); },
    stop: () => { if (playing()) send('toggle'); },
    previoustrack: () => send('prev'),
    nexttrack: () => send('next'),
    seekto: (details) => { if (details && details.seekTime >= 0) send('seek', Math.round(details.seekTime)); },
  };
  for (const [action, handler] of Object.entries(handlers)) {
    try { ms.setActionHandler(action, active && state.control ? handler : null); } catch (e) { /* not supported here */ }
  }
}

// Once per connection while the setting is on: what this browser supports.
function lockReport() {
  if (!prefs.lockScreen) return;
  lockLog(`включён; mediaSession: ${'mediaSession' in navigator ? 'да' : 'нет'}, audioSession: ${navigator.audioSession ? 'да' : 'нет'}, `
    + `экран Домой: ${matchMedia('(display-mode: standalone)').matches || navigator.standalone ? 'да' : 'нет'}, управление: ${state.control ? 'да' : 'нет'}, `
    + `звук: ${lockScreen.on && lockScreen.audio && !lockScreen.audio.paused ? 'играет' : 'нет'}`);
}

async function startLockScreen() {
  if (!lockScreenSupported()) { lockLog('mediaSession не поддерживается этим браузером'); return false; }
  try { if (navigator.audioSession) navigator.audioSession.type = 'playback'; } catch (e) { lockLog(`audioSession: ${e.name}`); }
  if (!lockScreen.audio) {
    const audio = new Audio('silence.wav');
    audio.loop = true;
    audio.preload = 'auto';
    audio.setAttribute('playsinline', '');
    audio.addEventListener('pause', () => {          // paused by the system: back on the next tap
      if (lockScreen.on && prefs.lockScreen) { lockLog('звук остановлен системой'); lockScreen.on = false; waitForTap(); }
    });
    audio.addEventListener('error', () => lockLog(`ошибка звука: ${audio.error ? audio.error.code : '?'}`));
    audio.addEventListener('playing', () => lockLog(`звук играет (${Math.round(audio.duration || 0)} с), audioSession: ${navigator.audioSession ? navigator.audioSession.type : 'нет'}`));
    document.body.append(audio);                   // some iOS versions want it in the page
    lockScreen.audio = audio;
  }
  try {
    await lockScreen.audio.play();
  } catch (e) {
    lockLog(`звук не запущен: ${e.name} — жду касания`);
    waitForTap();           // not from a tap (page just opened): start on the next tap
    return false;
  }
  lockScreen.on = true;
  lockScreen.waiting = false;
  lockScreen.cover = '';
  lockHandlers(true);
  updateLockScreen();
  return true;
}

function stopLockScreen() {
  lockScreen.on = false;                           // first: the pause below is ours, not the system's
  if (lockScreen.audio) lockScreen.audio.pause();
  if (!lockScreenSupported()) return;
  lockHandlers(false);
  navigator.mediaSession.metadata = null;
  navigator.mediaSession.playbackState = 'none';
}

document.addEventListener('visibilitychange', () => {
  if (lockScreen.on) lockLog(`страница ${document.hidden ? 'скрыта (экран заблокирован или другое приложение)' : 'снова видна'}, звук ${lockScreen.audio && !lockScreen.audio.paused ? 'играет' : 'стоит'}`);
});

function waitForTap() {
  if (lockScreen.waiting) return;
  lockScreen.waiting = true;
  const tap = () => {
    document.removeEventListener('pointerup', tap, true);
    lockScreen.waiting = false;
    if (prefs.lockScreen && !lockScreen.on) startLockScreen();
  };
  document.addEventListener('pointerup', tap, true);
}

// Called on every media message and when access changes.
function updateLockScreen() {
  if (!lockScreen.on || !lockScreenSupported()) return;
  const ms = navigator.mediaSession;
  const s = state.media;
  lockHandlers(true);
  if (!s) {
    ms.metadata = new MediaMetadata({ title: 'Ничего не играет', artist: `PulseDeck · ${$('pcname').textContent}`,
      artwork: [{ src: new URL('icon.png', location.href).href, sizes: '512x512', type: 'image/png' }] });
    ms.playbackState = 'paused';
    return;
  }
  const cover = s.cover
    ? new URL(`cover?key=${encodeURIComponent(s.cover)}&t=${encodeURIComponent(state.token)}`, location.href).href
    : new URL('icon.png', location.href).href;
  const key = [s.title, s.artist, s.album, cover].join('\n');
  if (key !== lockScreen.cover) {             // new metadata only when the track changes
    lockScreen.cover = key;
    ms.metadata = new MediaMetadata({ title: s.title || '—', artist: s.artist || s.source || '', album: s.album || s.source || '',
      artwork: [{ src: cover, sizes: '512x512', type: s.cover ? 'image/jpeg' : 'image/png' }] });
  }
  ms.playbackState = s.status === 'playing' ? 'playing' : 'paused';
  if (ms.setPositionState && s.duration > 0) {
    let position = s.position || 0;
    if (s.status === 'playing') position += (performance.now() - state.mediaAt) / 1000;
    try {   // the rate may not be 0; a paused state stops the bar by itself
      ms.setPositionState({ duration: s.duration, position: Math.min(Math.max(0, position), s.duration), playbackRate: 1 });
    } catch (e) { /* an old browser */ }
  }
}
