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
  active: false,
};

async function boot() {
  state.cfg = (await window.penelope.readConfig('config.json')) || {};

  // Load face geometry: prefer real MediaPipe JSON if extract_face_mesh.py
  // has been run, otherwise fall back to the PC-tuned procedural mesh
  // baked into face-landmarks.js.
  const lm = await loadFaceLandmarks();
  console.log(`face mesh: ${lm.source} (${lm.count} points)`);

  // 3D face
  state.face = new PenelopeFace($('face-canvas'));
  state.face.start();
  // boot to fully-assembled by default; we'll re-scatter and re-assemble
  // explicitly when the wake-phrase fires.
  state.face.uniforms.uBootProgress.value = 1;

  // Audio analyser drives shader reactivity from her TTS.
  // (The wake song plays through Spotify on the system level — not
  // routed through the renderer — so during the song the face shows
  // its idle breathing rather than FFT-driven motion.)
  state.audio = new AudioAnalyzer($('tts-audio'));
  function reactivityTick() {
    state.face.setReactivity(state.audio.sample());
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
    case 'go_sleep':
      handleSleep();
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
      // Webcam saw owner — no automatic wake (user requested wake-words only).
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
  const phrase = data.phrase || 'papis_home';
  const isFullWake = phrase === 'papis_home';

  if (data.already_active) {
    // small flourish, no song, no greeting
    state.face.bootAssemble(1500);
    return;
  }
  state.active = true;

  // Scatter face for the assembly
  state.face.uniforms.uBootProgress.value = 0;

  // Full wake -> tell Python to start the wake song in Spotify
  if (isFullWake) {
    try { await window.penelope.call('play_wake_song', {}); } catch (e) {
      console.warn('wake song failed', e);
    }
  }

  const panels = [$('left-panel'), $('right-panel'), $('bottom-panel')];
  await runBootSequence({
    face: state.face,
    panels,
    bootEl: $('boot-overlay'),
    statusEl: $('status-text'),
    duration: isFullWake ? 12000 : 2500,
    quick: !isFullWake,
  });

  if (isFullWake) {
    // Fade Spotify down so the greeting is audible, then deliver brief
    try { await window.penelope.call('stop_wake_song', {}); } catch {}
    await window.penelope.call('daily_brief', {});
  } else {
    await window.penelope.call('quick_greeting', {});
  }
}

function handleSleep() {
  state.active = false;
  $('status-text').textContent = 'standby';
  // Re-scatter the face so the next wake is dramatic
  state.face.uniforms.uBootProgress.value = 0;
  state.face.setIdle();
  // Main process hides the window in response to the go_sleep event.
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
