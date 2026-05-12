// Penelope renderer entry — Transcendence aesthetic.
// Every "panel" is a chrome-less floating module of glowing kinetic text.
// All 7 channels render as their own draggable constellation showing
// every platform's subs + 28d views.

import { PenelopeFace } from './visualizer/penelope-face.js';
import { AudioAnalyzer } from './visualizer/audio-analyzer.js';
import { runBootSequence } from './visualizer/boot-sequence.js';
import { bigNumber, smallNumber, barChart, sparkline } from './visualizer/particle-graph.js';

const $ = (id) => document.getElementById(id);

const state = { cfg: null, face: null, audio: null, speaking: false, active: false };
const LAYOUT_KEY = 'penelope.layout.v2';

const PLATFORMS = [
  { key: 'youtube', short: 'YT', url: (h) => `https://www.youtube.com/${h || ''}` },
  { key: 'tiktok',  short: 'TT', url: (h) => `https://www.tiktok.com/${h || ''}` },
  { key: 'instagram', short: 'IG', url: (h) => h ? `https://www.instagram.com/${h.replace(/^@/, '')}/` : 'https://www.instagram.com/' },
  { key: 'facebook', short: 'FB', url: (h) => h ? `https://www.facebook.com/${h.replace(/^@/, '')}/` : 'https://www.facebook.com/' },
  { key: 'x',       short: 'X',  url: (h) => h ? `https://x.com/${h.replace(/^@/, '')}` : 'https://x.com/' },
];

const DASHBOARDS = {
  Stripe:     'https://dashboard.stripe.com/',
  Gumroad:    'https://app.gumroad.com/dashboard',
  AdSense:    'https://adsense.google.com/',
  ElevenLabs: 'https://elevenlabs.io/app/voice-lab',
};

async function boot() {
  state.cfg = (await window.penelope.readConfig('config.json')) || {};

  // 3D face — texture-driven particle stippling from her actual photo.
  // Start SCATTERED (uBootProgress=0). On wake, runBootSequence drives
  // the cinematic assembly. Modules also start hidden until the wake
  // animation slides them in.
  state.face = new PenelopeFace($('face-canvas'));
  state.face.start();
  state.face.uniforms.uBootProgress.value = 0;
  document.body.classList.add('pre-wake');

  state.audio = new AudioAnalyzer($('tts-audio'));
  (function tick() {
    state.face.setReactivity(state.audio.sample());
    requestAnimationFrame(tick);
  })();

  // Subscribe to Python events
  window.penelope.on('penelope:event', handlePyEvent);

  // Build channel constellations now (one floating module per brand)
  await buildChannelConstellations();
  // Default-position any unsaved modules so they don't pile at 0,0
  defaultPositions();
  // Hydrate saved positions
  restoreLayout();
  // Wire drag + resize on every module / channel-mod
  for (const m of document.querySelectorAll('.module, .channel-mod')) makeMovable(m);

  // Pull live data into modules
  await refreshAll();
  setInterval(refreshAll, 60000);

  // Clock
  tickClock(); setInterval(tickClock, 1000);

  // Cursor auto-hide
  let cursorTimer = null;
  document.addEventListener('mousemove', () => {
    document.body.classList.add('show-cursor');
    clearTimeout(cursorTimer);
    cursorTimer = setTimeout(() => document.body.classList.remove('show-cursor'), 2500);
  });

  // Reset layout button
  const reset = $('reset-layout');
  if (reset) reset.addEventListener('click', () => {
    localStorage.removeItem(LAYOUT_KEY);
    for (const m of document.querySelectorAll('.module, .channel-mod')) {
      m.style.left = m.style.top = m.style.width = m.style.height = '';
    }
    defaultPositions();
    if (state.face?.pulse) state.face.pulse(0.5, 700);
  });

  wireCompose();

  // Tell Python we're ready
  try { await window.penelope.call('start', {}); }
  catch (e) { console.warn('python not ready:', e.message); }
}

// ── Channel constellations (one per brand, 5 platforms each) ───────────

async function buildChannelConstellations() {
  const host = $('channels-host');
  host.innerHTML = '';
  const chCfg = await window.penelope.readConfig('channels.json');
  const channels = (chCfg?.channels || []);
  for (const ch of channels) {
    const el = document.createElement('div');
    el.className = 'channel-mod';
    el.id = `ch-${ch.id}`;
    el.dataset.mod = `ch-${ch.id}`;
    el.dataset.handles = JSON.stringify(
      Object.fromEntries(PLATFORMS.map(p => [p.key, ((ch.platforms || {})[p.key] || {}).handle || '']))
    );
    // Each channel: name + readable 5-bar chart with subs counts
    el.innerHTML = `
      <div class="ch-name">${escapeHtml(ch.name)}</div>
      <div class="ch-bars m-bars" data-ch="${ch.id}"></div>
      <div class="ch-foot" data-ch-foot="${ch.id}"></div>
    `;
    host.appendChild(el);
  }
  // Click a channel's bar chart → opens upload-post analytics
  for (const c of host.querySelectorAll('.ch-bars')) {
    c.addEventListener('click', () => {
      if (window.penelope?.openExternal) {
        window.penelope.openExternal('https://app.upload-post.com/analytics');
        state.face?.pulse?.(0.3);
      }
    });
  }
}

function fillChannelData(analytics, channelsCfg) {
  // analytics: { youtube: {channels: [...]}, tiktok: {...}, ... }
  const byBrand = {};
  for (const p of PLATFORMS) {
    const bucket = (analytics?.[p.key] || {}).channels || [];
    for (const row of bucket) {
      const k = row.name || row.brand || '';
      if (!byBrand[k]) byBrand[k] = {};
      byBrand[k][p.key] = row;
    }
  }
  for (const ch of (channelsCfg?.channels || [])) {
    // Build a 5-element vector — one bar per platform, value = 28d views
    const vals = PLATFORMS.map(p => byBrand[ch.name]?.[p.key]?.views_28d || 0);
    const bars = document.querySelector(`.ch-bars[data-ch="${ch.id}"]`);
    if (bars) {
      bars.innerHTML = '';
      const max = Math.max(1, ...vals);
      vals.forEach((v, i) => {
        const bar = document.createElement('div');
        bar.className = 'bar';
        bar.style.height = `${Math.max(2, (v / max) * 100)}%`;
        bar.title = `${PLATFORMS[i].short}: ${fmt(v)} views (28d)`;
        bars.appendChild(bar);
      });
    }
    const foot = document.querySelector(`[data-ch-foot="${ch.id}"]`);
    if (foot) {
      const total = vals.reduce((a, b) => a + b, 0);
      foot.textContent = total ? `${fmt(total)} VIEWS · 28D` : '—';
    }
  }
}

// ── Default positions (only used until Dylan moves things) ─────────────

function defaultPositions() {
  // Don't override anything that's been moved already
  const map = loadLayoutMap();
  const W = window.innerWidth, H = window.innerHeight;
  // Left edge: 4 personal modules stacked top-to-bottom
  const defaults = {
    'm-revenue':   { left: 28,    top: 90 },
    'm-weather':   { left: 28,    top: 250 },
    'm-schedule':  { left: 28,    top: 380 },
    'm-todos':     { left: 28,    top: 560 },
  };
  // Right edge: 7 channels stacked top-to-bottom, narrower so they fit
  const channels = document.querySelectorAll('.channel-mod');
  const chHeight = Math.max(86, Math.floor((H - 120) / Math.max(1, channels.length)));
  channels.forEach((c, i) => {
    if (!map[c.id]) {
      c.style.left = (W - 260) + 'px';
      c.style.top  = (90 + i * chHeight) + 'px';
    }
  });
  for (const [id, p] of Object.entries(defaults)) {
    if (map[id]) continue;
    const el = document.getElementById(id);
    if (el) { el.style.left = p.left + 'px'; el.style.top = p.top + 'px'; }
  }
}

// ── Drag + resize + persistence ────────────────────────────────────────

function loadLayoutMap() {
  try { return JSON.parse(localStorage.getItem(LAYOUT_KEY) || '{}'); }
  catch { return {}; }
}
function saveLayoutMap(m) { localStorage.setItem(LAYOUT_KEY, JSON.stringify(m)); }
function restoreLayout() {
  const map = loadLayoutMap();
  for (const m of document.querySelectorAll('.module, .channel-mod')) {
    const s = map[m.id]; if (!s) continue;
    m.style.left = s.left + 'px';
    m.style.top = s.top + 'px';
    if (s.width) m.style.width = s.width + 'px';
    if (s.height) m.style.height = s.height + 'px';
  }
}
function persist(m) {
  if (!m.id) return;
  const r = m.getBoundingClientRect();
  const map = loadLayoutMap();
  map[m.id] = { left: r.left|0, top: r.top|0, width: r.width|0, height: r.height|0 };
  saveLayoutMap(map);
}

function makeMovable(m) {
  const drag = m.querySelector('.m-label, .ch-name');
  if (drag) drag.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    const r = m.getBoundingClientRect();
    const sx = e.clientX, sy = e.clientY, sl = r.left, st = r.top;
    m.style.zIndex = '90';
    document.body.style.cursor = 'grabbing';
    function move(ev) {
      m.style.left = (sl + ev.clientX - sx) + 'px';
      m.style.top = (st + ev.clientY - sy) + 'px';
    }
    function up() {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      document.body.style.cursor = '';
      persist(m);
    }
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });

  // SE resize handle
  if (!m.querySelector('.resize-handle')) {
    const h = document.createElement('div');
    h.className = 'resize-handle';
    m.appendChild(h);
    h.addEventListener('pointerdown', (e) => {
      e.preventDefault(); e.stopPropagation();
      const r = m.getBoundingClientRect();
      const sx = e.clientX, sy = e.clientY, sw = r.width, sh = r.height;
      document.body.style.cursor = 'nwse-resize';
      function move(ev) {
        m.style.width = Math.max(160, sw + ev.clientX - sx) + 'px';
        m.style.height = Math.max(60, sh + ev.clientY - sy) + 'px';
      }
      function up() {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        document.body.style.cursor = '';
        persist(m);
      }
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
  }
}

// ── Data refresh from Python sidecar ───────────────────────────────────

async function refreshAll() {
  let live = null;
  try { live = await window.penelope.call('get_panel_data', {}); } catch {}
  if (!live) return;
  renderRevenue(live.revenue);
  renderWeather(live.weather);
  renderSchedule(live.schedule, live.todos);
  const chCfg = await window.penelope.readConfig('channels.json');
  fillChannelData(live.analytics || {}, chCfg);
}

function renderRevenue(rev) {
  if (!rev) return;
  const big = $('rev-big');
  big.textContent = `$${(rev.total_mtd || 0).toFixed(2)}`;
  big.onclick = () => {
    window.penelope?.openExternal?.('https://connect.stripe.com/express_login');
    state.face?.pulse?.(0.3);
  };
  // Real bars per source — readable, hover for source name
  const sources = (rev.sources || []).filter(s => s.name);
  const chart = $('rev-chart');
  chart.innerHTML = '';
  const max = Math.max(1, ...sources.map(s => s.mtd || 0));
  for (const s of sources) {
    const bar = document.createElement('div');
    bar.className = 'bar';
    bar.style.height = `${Math.max(2, (s.mtd / max) * 100)}%`;
    bar.title = `${s.name}: $${(s.mtd || 0).toFixed(2)}`;
    chart.appendChild(bar);
  }
  chart.onclick = () => window.penelope?.openExternal?.('https://connect.stripe.com/express_login');
  // Footer: source names
  $('rev-foot').textContent = sources.map(s => s.name.toUpperCase()).join(' · ');
}

function renderWeather(wx) {
  if (!wx) return;
  const t = wx.temp_f ?? wx.temperature_f ?? '—';
  const c = wx.condition || '';
  const city = wx.city ? ` · ${wx.city.toUpperCase()}` : '';
  $('wx-label').textContent = `WEATHER${city}${c ? ' · ' + c.toUpperCase() : ''}`;
  const big = $('wx-temp');
  big.textContent = `${t}°`;
  big.onclick = () => {
    window.penelope?.openExternal?.('weather://');
    state.face?.pulse?.(0.3);
  };
}

function renderSchedule(schedule, todos) {
  // Real text list of today's calendar events
  const events = (schedule?.events || []).slice(0, 6);
  const sched = $('sched-list');
  sched.innerHTML = '';
  if (!events.length) {
    sched.innerHTML = '<li class="empty">nothing on the calendar</li>';
  } else {
    for (const e of events) {
      const li = document.createElement('li');
      li.innerHTML = `<span class="t">${escapeHtml(e.time || '')}</span>` +
                     `<span>${escapeHtml(e.title || '')}</span>`;
      li.onclick = () => window.penelope?.openExternal?.('ical://');
      sched.appendChild(li);
    }
  }

  // Real text list of upcoming reminders (next 7 days)
  const items = (todos?.items || []).slice(0, 8);
  const todo = $('todo-list');
  todo.innerHTML = '';
  if (!items.length) {
    todo.innerHTML = '<li class="empty">no reminders coming up</li>';
  } else {
    for (const it of items) {
      const li = document.createElement('li');
      li.innerHTML = `<span class="t">${escapeHtml(it.when || '·')}</span>` +
                     `<span>${escapeHtml(it.text || '')}</span>`;
      li.onclick = () => window.penelope?.openExternal?.('x-apple-reminderkit://');
      todo.appendChild(li);
    }
  }
}

// ── Python event dispatch ──────────────────────────────────────────────

function handlePyEvent(evt) {
  switch (evt.event) {
    case 'log': console.log('[py]', evt.data); break;
    case 'hotword': handleWake(evt.data); break;
    case 'go_sleep': handleSleep(); break;
    case 'user_transcript': appendThread('user', evt.data.text); break;
    case 'assistant_text': appendThread('penelope', evt.data.text); break;
    case 'assistant_audio': playTts(evt.data.url, evt.data.visemes || []); break;
    case 'assistant_thinking': $('status-text').textContent = 'thinking'; break;
    case 'assistant_idle':
      $('status-text').textContent = 'listening';
      state.face?.setIdle();
      break;
    case 'mode_changed':
      state.face?.setMode?.(evt.data.mode); break;
    case 'assistant_emotion':
      // Brain inferred sentiment from her response — drive smile/brow
      // blendshapes so her face expresses the mood while she speaks.
      // null values reset to mode default.
      if (evt.data.smile == null && evt.data.browLift == null) {
        state.face?.setMode?.(state.cfg?.mode || 'warm');
      } else {
        state.face?.setEmotion?.(evt.data);
      }
      break;
    case 'data_updated': refreshAll(); break;
  }
}

async function handleWake(data) {
  const phrase = data?.phrase || 'papis_home';
  const isFull = phrase === 'papis_home';
  if (data?.already_active) {
    // Already awake — small flourish, don't re-run the whole brief
    state.face?.pulse?.(0.6, 800);
    return;
  }
  state.active = true;
  document.body.classList.remove('pre-wake');

  // Wait for the 267MB face cloud to finish parsing onto the GPU
  // before kicking off the boot animation. Otherwise particles pop
  // in mid-assembly looking glitchy.
  if (state.face && !state.face._ready) {
    $('status-text').textContent = 'loading';
    console.log('[wake] waiting for face cloud…');
    await state.face.whenReady();
    console.log('[wake] face ready');
  }

  state.face.uniforms.uBootProgress.value = 0;
  if (isFull) {
    try { await window.penelope.call('play_wake_song', {}); } catch {}
  }
  refreshAll().catch(() => {});
  await runBootSequence({
    face: state.face,
    panels: [...document.querySelectorAll('.module, .channel-mod')],
    bootEl: $('boot-overlay'),
    statusEl: $('status-text'),
    duration: isFull ? 12000 : 2500,
    quick: !isFull,
  });
  if (isFull) {
    try { await window.penelope.call('stop_wake_song', {}); } catch {}
    await window.penelope.call('daily_brief', {});
  } else {
    await window.penelope.call('quick_greeting', {});
  }
}

function handleSleep() {
  state.active = false;
  $('status-text').textContent = 'standby';
  // Scatter the face back out + hide modules so the next wake plays
  // the full assembly animation again.
  state.face.uniforms.uBootProgress.value = 0;
  state.face?.setIdle();
  document.body.classList.add('pre-wake');
}

// ── Compose ─────────────────────────────────────────────────────────────

function wireCompose() {
  const input = $('compose-input');
  const row = $('compose-row');
  const thread = $('compose-thread');
  const attRow = $('compose-attachments');
  if (!input) return;
  const pending = [];

  function appendThread(role, html) {
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    div.innerHTML = html;
    // Any <a> inside this message routes through openExternal so Electron
    // hands the URL to the system browser instead of trying to navigate.
    div.querySelectorAll('a[href]').forEach((a) => {
      a.addEventListener('click', (e) => {
        e.preventDefault();
        const u = a.getAttribute('href');
        if (u) window.penelope?.openExternal?.(u);
      });
    });
    thread.appendChild(div);
    thread.scrollTop = thread.scrollHeight;
    if (state.face?.pulse) state.face.pulse(0.25, 400);
  }
  // Auto-linkify a plain-text message body before appending.
  function appendTextWithLinks(role, text) {
    const safe = escapeHtml(text);
    const linked = safe.replace(/(https?:\/\/[^\s<>"']+)/g,
      '<a href="$1">$1</a>');
    appendThread(role, linked);
  }
  window.penelopeCompose = { appendThread, appendTextWithLinks };

  async function fileToB64(file) {
    return new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => {
        const s = String(r.result), i = s.indexOf(',');
        res(i >= 0 ? s.slice(i + 1) : s);
      };
      r.onerror = rej;
      r.readAsDataURL(file);
    });
  }
  async function ingestFile(file) {
    try {
      const b64 = await fileToB64(file);
      pending.push({ name: file.name, mime: file.type || 'application/octet-stream', b64 });
      const chip = document.createElement('span');
      chip.className = 'att';
      chip.textContent = (file.type?.startsWith('image/') ? '🖼 ' : '📎 ') + file.name;
      attRow.appendChild(chip);
    } catch {}
  }

  document.addEventListener('dragover', (e) => { e.preventDefault(); row.classList.add('dragging'); });
  document.addEventListener('dragleave', () => row.classList.remove('dragging'));
  document.addEventListener('drop', async (e) => {
    e.preventDefault(); row.classList.remove('dragging');
    for (const f of (e.dataTransfer?.files || [])) await ingestFile(f);
    input.focus();
  });
  input.addEventListener('paste', async (e) => {
    for (const it of (e.clipboardData?.items || [])) {
      if (it.kind === 'file') { e.preventDefault(); await ingestFile(it.getAsFile()); }
    }
  });
  input.addEventListener('focus', () => row.classList.add('focused'));
  input.addEventListener('blur', () => row.classList.remove('focused'));
  input.addEventListener('keydown', async (e) => {
    if (e.key !== 'Enter' || e.shiftKey) return;
    e.preventDefault();
    const text = input.innerText.trim();
    const atts = pending.splice(0);
    attRow.innerHTML = '';
    input.innerText = '';
    if (!text && !atts.length) return;
    appendThread('user', escapeHtml(text || '(attachment)') +
      (atts.length ? ` <span style="opacity:.5">[+${atts.length}]</span>` : ''));
    try {
      const r = await window.penelope.call('text_message', { text, attachments: atts });
      if (r?.links?.length) for (const l of r.links)
        appendThread('penelope', `<a href="${escapeAttr(l.url)}" target="_blank">${escapeHtml(l.label || l.url)}</a>`);
      if (r?.text) appendThread('penelope', escapeHtml(r.text));
    } catch (e) {
      appendThread('penelope', `<i style="color:#f66">${escapeHtml(String(e.message || e))}</i>`);
    }
  });
}

function appendThread(role, text) {
  if (window.penelopeCompose) window.penelopeCompose.appendTextWithLinks(role, String(text));
}

async function playTts(url, visemes) {
  const a = $('tts-audio');
  a.src = url;
  state.face?.setIdle();
  state.speaking = true;
  $('status-text').textContent = 'speaking';
  if (visemes?.length) scheduleVisemes(visemes, a);
  try { await a.play(); } catch (e) { console.warn(e); }
  a.onended = () => {
    state.speaking = false;
    state.face?.setIdle();
    $('status-text').textContent = 'listening';
  };
}
function scheduleVisemes(visemes, audioEl) {
  let idx = 0;
  function step() {
    if (audioEl.paused || audioEl.ended) return;
    const t = audioEl.currentTime;
    while (idx < visemes.length - 1 && visemes[idx + 1].t <= t) idx++;
    state.face?.setViseme({ open: visemes[idx].open, wide: visemes[idx].wide });
    requestAnimationFrame(step);
  }
  step();
}

function tickClock() {
  const d = new Date();
  const hh = d.getHours() % 12 || 12;
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  const ampm = d.getHours() >= 12 ? 'PM' : 'AM';
  $('clock').textContent = `${hh}:${mm}:${ss} ${ampm}`;
}

function fmt(n) {
  if (!n) return '0';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return String(n | 0);
}
function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function escapeAttr(s) { return escapeHtml(s).replace(/'/g, '&#39;'); }

window.penelopeDev = {
  reloadData: refreshAll,
  fakeWake: () => handleWake({}),
  scatter: () => { state.face.uniforms.uBootProgress.value = 0; },
  pulse: (s = 0.35) => state.face?.pulse?.(s),
};

boot().catch((e) => {
  console.error('boot failed', e);
  document.body.innerHTML = `<pre style="color:#0ff;padding:24px">${e.stack}</pre>`;
});
