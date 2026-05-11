// Penelope renderer entry. Wires up the face visualizer, audio analyzer,
// side panels, conversation transcript, and the JSON-RPC bridge to Python.

import { PenelopeFace } from './visualizer/penelope-face.js';
import { loadFaceLandmarks } from './visualizer/face-landmarks.js';
import { AudioAnalyzer } from './visualizer/audio-analyzer.js';
import { runBootSequence } from './visualizer/boot-sequence.js';
import { renderRevenue } from './panels/revenue-panel.js';
import { renderAnalytics } from './panels/analytics-panel.js';
import { renderSchedule } from './panels/schedule-panel.js';

const $ = (id) => document.getElementById(id);

const state = {
  cfg: null,
  face: null,
  audio: null,
  audioBoot: null,
  speaking: false,
  briefPlayedToday: false,
  active: false,
};

async function boot() {
  state.cfg = (await window.penelope.readConfig('config.json')) || {};

  // Load face landmarks (user-supplied Penelope mesh if available)
  const lm = await loadFaceLandmarks();
  console.log(`face mesh: ${lm.source} (${lm.count} points)`);

  // 3D face
  state.face = new PenelopeFace($('face-canvas'));
  state.face.start();
  // boot to fully-assembled by default; we'll re-scatter and re-assemble
  // explicitly when the wake-phrase fires.
  state.face.uniforms.uBootProgress.value = 1;

  // Audio analysers (one for TTS, one for the wake-song)
  state.audio = new AudioAnalyzer($('tts-audio'));
  state.audioBoot = new AudioAnalyzer($('papis-home-audio'));

  // Drive shader reactivity from whichever audio is currently producing sound
  function reactivityTick() {
    const a = state.audio.sample();
    const b = state.audioBoot.sample();
    // pick the louder source
    const src = a.amp > b.amp ? a : b;
    state.face.setReactivity(src);
    requestAnimationFrame(reactivityTick);
  }
  reactivityTick();

  // Subscribe to Python events
  window.penelope.on('penelope:event', handlePyEvent);

  // Load + render panels
  await refreshPanels();

  // Hook clock
  tickClock();
  setInterval(tickClock, 1000);

  // Cursor auto-hide
  let cursorTimer = null;
  document.addEventListener('mousemove', () => {
    document.body.classList.add('show-cursor');
    clearTimeout(cursorTimer);
    cursorTimer = setTimeout(() => document.body.classList.remove('show-cursor'), 2500);
  });

  // Tell Python we're ready and let it start the hotword listener
  try {
    await window.penelope.call('start', {});
  } catch (e) {
    console.warn('python not ready:', e.message);
    appendTranscript('penelope', '(offline — python backend not running)');
  }
}

function handlePyEvent(evt) {
  switch (evt.event) {
    case 'log':
      console.log('[py]', evt.data);
      break;
    case 'hotword':
      handleWake(evt.data);
      break;
    case 'user_transcript':
      appendTranscript('user', evt.data.text);
      break;
    case 'assistant_text':
      appendTranscript('penelope', evt.data.text);
      break;
    case 'assistant_audio':
      playTts(evt.data.url, evt.data.visemes || []);
      break;
    case 'assistant_thinking':
      $('status-text').textContent = 'thinking';
      break;
    case 'assistant_idle':
      $('status-text').textContent = 'listening';
      state.face.setIdle();
      break;
    case 'face_seen':
      if (!state.briefPlayedToday) {
        state.briefPlayedToday = true;
        handleWake({ first_sight: true });
      }
      break;
    case 'proactive_alert':
      handleAlert(evt.data);
      break;
    case 'data_updated':
      refreshPanels();
      break;
    case 'python_exit':
      $('status-text').textContent = 'offline';
      break;
  }
}

async function handleWake(data) {
  if (state.active && !data.first_sight) {
    // already active; quick visual flourish only
    state.face.bootAssemble(2500);
    return;
  }
  state.active = true;

  // Scatter face for the cinematic build
  state.face.uniforms.uBootProgress.value = 0;

  // Decide whether to play the song
  const playSong = !state.briefPlayedToday;
  state.briefPlayedToday = true;
  const song = $('papis-home-audio');
  if (playSong) {
    // The user will supply assets/songs/papis_home.mp3
    const songB64 = await window.penelope.readAsset('assets/songs/papis_home.mp3');
    if (songB64) {
      song.src = `data:audio/mpeg;base64,${songB64}`;
      song.currentTime = 0;
    } else {
      song.removeAttribute('src');
    }
  } else {
    song.removeAttribute('src');
  }

  const panels = [$('left-panel'), $('right-panel'), $('bottom-panel')];
  await runBootSequence({
    face: state.face,
    panels,
    song: playSong ? song : null,
    bootEl: $('boot-overlay'),
    statusEl: $('status-text'),
  });

  // Tell Python to begin the daily brief
  await window.penelope.call('daily_brief', {});
}

function appendTranscript(who, text) {
  const t = $('transcript');
  const div = document.createElement('div');
  div.className = `turn ${who}`;
  div.textContent = text;
  t.appendChild(div);
  while (t.childElementCount > 60) t.removeChild(t.firstChild);
  t.scrollTop = t.scrollHeight;
}

async function playTts(url, visemes) {
  const a = $('tts-audio');
  a.src = url;
  state.face.setIdle();
  state.speaking = true;
  $('status-text').textContent = 'speaking';
  if (visemes && visemes.length) scheduleVisemes(visemes, a);
  try { await a.play(); } catch (e) { console.warn(e); }
  a.onended = () => {
    state.speaking = false;
    state.face.setIdle();
    $('status-text').textContent = 'listening';
  };
}

function scheduleVisemes(visemes, audioEl) {
  // visemes: [{t: seconds, open: 0..1, wide: -1..1}, ...]
  let idx = 0;
  const step = () => {
    if (audioEl.paused || audioEl.ended) return;
    const t = audioEl.currentTime;
    while (idx < visemes.length - 1 && visemes[idx + 1].t <= t) idx++;
    const cur = visemes[idx];
    state.face.setViseme({ open: cur.open, wide: cur.wide });
    requestAnimationFrame(step);
  };
  step();
}

async function refreshPanels() {
  const revenue = await window.penelope.readConfig('revenue.json');
  const analytics = await window.penelope.readConfig('analytics.json');
  const schedule = await window.penelope.readConfig('schedule.json');
  const todos = await window.penelope.readConfig('todos.json');
  if (revenue) renderRevenue(revenue);
  if (analytics) renderAnalytics(analytics);
  if (schedule || todos) renderSchedule(schedule || { events: [] }, todos || { items: [] });
}

function handleAlert(alert) {
  // user spec: all-three (chime + visual pulse + voice).
  // chime + voice are handled python-side; here we do the visual pulse.
  const targetId = alert.panel ? `${alert.panel}-card` : null;
  const el = targetId ? document.getElementById(targetId) : null;
  if (el) {
    el.animate(
      [
        { boxShadow: '0 0 0 1px rgba(0,229,255,0.06) inset, 0 0 24px rgba(0,229,255,0.07)' },
        { boxShadow: '0 0 0 2px rgba(0,229,255,0.6) inset, 0 0 60px rgba(0,229,255,0.8)' },
        { boxShadow: '0 0 0 1px rgba(0,229,255,0.06) inset, 0 0 24px rgba(0,229,255,0.07)' },
      ],
      { duration: 1400, iterations: 1 },
    );
  }
  if (alert.text) appendTranscript('penelope', alert.text);
}

function tickClock() {
  const d = new Date();
  const hh = d.getHours() % 12 || 12;
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  const ampm = d.getHours() >= 12 ? 'PM' : 'AM';
  $('clock').textContent = `${hh}:${mm}:${ss} ${ampm}`;
}

// Devtools helpers
window.penelopeDev = {
  reloadData: refreshPanels,
  fakeWake: () => handleWake({}),
  scatter: () => { state.face.uniforms.uBootProgress.value = 0; },
};

boot().catch(e => {
  console.error('boot failed', e);
  document.body.innerHTML = `<pre style="color:#0ff;padding:24px">${e.stack}</pre>`;
});
