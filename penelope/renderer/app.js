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

// If we're a detached panel window (loaded with #panel=<id>), hide
// every panel except the requested one and let it fill the screen.
// The same renderer code runs; only the layout differs.
function applyDetachLayout() {
  const m = (window.location.hash || '').match(/panel=([\w-]+)/);
  if (!m) return false;
  const which = m[1];
  document.body.classList.add('detached', `detached-${which}`);
  // Hide the other surfaces
  for (const id of ['left-panel', 'right-panel', 'bottom-panel',
                    'topbar', 'compose-dock', 'face-canvas']) {
    if (id === 'face-canvas') continue;  // keep face if user wants
    if (id === which || which.startsWith(id)) continue;
    const el = document.getElementById(id);
    if (el && id !== `${which}-panel`) {
      // Keep the matching aside if which='left' / 'right' / 'bottom'
      el.style.display = (id === `${which}-panel` || id.startsWith(which)) ? '' : 'none';
    }
  }
  // Show ONLY the requested card
  const idMap = {
    'revenue': 'revenue-card',
    'todo': 'todo-card',
    'yt': 'yt-card',
    'tt': 'tt-card',
    'schedule': 'schedule-card',
    'weather': 'weather-card',
    'transcript': 'transcript-card',
  };
  const target = document.getElementById(idMap[which] || which);
  if (target) {
    // hide siblings + lift target to fill
    target.style.position = 'absolute';
    target.style.inset = '0';
    target.style.margin = '0';
    target.style.padding = '32px';
    target.style.fontSize = '120%';
    document.body.appendChild(target);
    // hide everything else inside main
    for (const el of document.querySelectorAll('main > *')) {
      if (el !== target && el.id !== 'boot-overlay' && el.id !== 'face-canvas') {
        el.style.display = 'none';
      }
    }
  }
  return true;
}

async function boot() {
  // Detached-panel mode: applies layout + still proceeds to render data
  applyDetachLayout();

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

  // Wire the invisible compose dock (text channel)
  wireCompose();

  // Wire the ⤢ detach buttons on every panel header
  for (const btn of document.querySelectorAll('button.detach')) {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = btn.getAttribute('data-panel');
      if (id && window.penelope?.detachPanel) {
        window.penelope.detachPanel(id);
        if (state.face?.pulse) state.face.pulse(0.4, 500);
      }
    });
  }

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
    case 'mode_changed':
      if (state.face && typeof state.face.setMode === 'function') {
        state.face.setMode(evt.data.mode);
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

  // Kick off fresh panel data fetch in parallel with the boot animation
  // so panels show LIVE numbers the moment they slide in (not stale JSON).
  refreshPanels().catch(e => console.warn('panel refresh failed', e));

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

// Weather widget is rendered into #weather-now by refreshPanels; clicking
// pulses the face and opens Apple's Weather.app (weather:// scheme).
async function refreshWeatherWidget(weatherEvt) {
  const el = document.getElementById('weather-now');
  if (!el || !weatherEvt) return;
  const t = weatherEvt.temp_f ?? weatherEvt.temperature_f ?? '?';
  const c = weatherEvt.condition || weatherEvt.source || '';
  const src = weatherEvt.source ? ` · ${weatherEvt.source}` : '';
  el.innerHTML = `<div class="big">${t}°F</div><div>${c}${src}</div>`;
  el.style.cursor = 'pointer';
  el.title = 'Open Weather.app';
  el.onclick = () => {
    if (state.face && state.face.pulse) state.face.pulse(0.35);
    if (window.penelope?.openExternal) window.penelope.openExternal('weather://');
  };
}

async function refreshPanels() {
  // Prefer LIVE data from the Python sidecar (brain.gather_revenue +
  // gather_analytics + apple_cal.today_events + apple_reminders.scheduled_today).
  // Fall back to the static JSON files if the bridge isn't ready (boot,
  // first render before start() returns).
  let revenue, analytics, schedule, todos, weather;
  try {
    const live = await window.penelope.call('get_panel_data', {});
    if (live) {
      revenue = live.revenue;
      analytics = live.analytics;
      schedule = live.schedule;
      todos = live.todos;
      weather = live.weather;
    }
  } catch (e) {
    console.warn('panel live-data failed, falling back to JSON', e);
  }
  if (!revenue)   revenue   = await window.penelope.readConfig('revenue.json');
  if (!analytics) analytics = await window.penelope.readConfig('analytics.json');
  if (!schedule)  schedule  = await window.penelope.readConfig('schedule.json');
  if (!todos)     todos     = await window.penelope.readConfig('todos.json');

  if (revenue) renderRevenue(revenue);
  if (analytics) renderAnalytics(analytics);
  if (schedule || todos) renderSchedule(schedule || { events: [] }, todos || { items: [] });
  if (weather) refreshWeatherWidget(weather);
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

// ─── Compose dock — the invisible text channel under Penelope ──
// Type text + paste/drag-drop images, screenshots, files, or links.
// Penelope's verbal reply still speaks via TTS; any links / long text
// she returns are appended to #compose-thread above the input.

function wireCompose() {
  const input = document.getElementById('compose-input');
  const row = document.getElementById('compose-row');
  const thread = document.getElementById('compose-thread');
  const attRow = document.getElementById('compose-attachments');
  if (!input || !row) return;

  const pending = [];   // [{name, mime, b64}]

  function addAttachmentChip(name, mime) {
    const chip = document.createElement('span');
    chip.className = 'att';
    chip.textContent = (mime?.startsWith('image/') ? '🖼 ' : '📎 ') + name;
    attRow.appendChild(chip);
  }

  function appendThread(role, html) {
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    div.innerHTML = html;
    thread.appendChild(div);
    thread.scrollTop = thread.scrollHeight;
    // particle pulse so the face acknowledges the new message
    if (state.face?.pulse) state.face.pulse(0.25, 400);
  }
  // Expose so brain events can write into the thread
  window.penelopeCompose = { appendThread };

  async function fileToB64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => {
        const s = r.result;
        const idx = String(s).indexOf(',');
        resolve(idx >= 0 ? String(s).slice(idx + 1) : String(s));
      };
      r.onerror = reject;
      r.readAsDataURL(file);
    });
  }

  async function ingestFile(file) {
    try {
      const b64 = await fileToB64(file);
      pending.push({ name: file.name, mime: file.type || 'application/octet-stream', b64 });
      addAttachmentChip(file.name, file.type);
    } catch (e) { console.warn('attach failed', e); }
  }

  // Drag-drop anywhere on the body lights up the compose row
  document.addEventListener('dragover', (e) => { e.preventDefault(); row.classList.add('dragging'); });
  document.addEventListener('dragleave', () => row.classList.remove('dragging'));
  document.addEventListener('drop', async (e) => {
    e.preventDefault();
    row.classList.remove('dragging');
    for (const f of (e.dataTransfer?.files || [])) await ingestFile(f);
    input.focus();
  });

  // Cmd+V paste: image OR text
  input.addEventListener('paste', async (e) => {
    const items = e.clipboardData?.items || [];
    for (const it of items) {
      if (it.kind === 'file') {
        const f = it.getAsFile();
        if (f) {
          e.preventDefault();
          await ingestFile(f);
        }
      }
    }
  });

  input.addEventListener('focus', () => row.classList.add('focused'));
  input.addEventListener('blur', () => row.classList.remove('focused'));

  // Enter sends, Shift+Enter newline
  input.addEventListener('keydown', async (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const text = input.innerText.trim();
      const atts = pending.splice(0);
      attRow.innerHTML = '';
      input.innerText = '';
      if (!text && !atts.length) return;
      const echoText = text || '(attachment)';
      const attLabel = atts.length ? ` <span style="opacity:.5">[+${atts.length} file${atts.length>1?'s':''}]</span>` : '';
      appendThread('user', escapeHtmlSafe(echoText) + attLabel);
      try {
        const reply = await window.penelope.call('text_message',
          { text, attachments: atts });
        // Penelope speaks via the normal assistant_audio/text event path;
        // here we render any utility links/text she returned.
        if (reply?.links?.length) {
          for (const l of reply.links) {
            appendThread('penelope',
              `<a href="${escapeAttr(l.url)}" target="_blank">${escapeHtmlSafe(l.label || l.url)}</a>`);
          }
        }
        if (reply?.text) appendThread('penelope', escapeHtmlSafe(reply.text));
      } catch (err) {
        appendThread('penelope', `<i style="color:#f66">${escapeHtmlSafe(String(err.message || err))}</i>`);
      }
    }
  });
}

function escapeHtmlSafe(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                   .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function escapeAttr(s) { return escapeHtmlSafe(s).replace(/'/g, '&#39;'); }


// Devtools + interactive helpers used by clickable panels.
window.penelopeDev = {
  reloadData: refreshPanels,
  fakeWake: () => handleWake({}),
  scatter: () => { state.face.uniforms.uBootProgress.value = 0; },
  // Brief particle pulse triggered when Dylan clicks a panel surface.
  pulse: (strength = 0.35) => {
    if (state.face && typeof state.face.pulse === 'function') {
      state.face.pulse(strength);
    }
  },
};

boot().catch(e => {
  console.error('boot failed', e);
  document.body.innerHTML = `<pre style="color:#0ff;padding:24px">${e.stack}</pre>`;
});
