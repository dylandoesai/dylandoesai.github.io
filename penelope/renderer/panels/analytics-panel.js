// Analytics panel: clickable per-platform stats + bar chart + top rows.
// Clicking a channel row opens that platform's page for that handle.
// Clicking the platform header opens the upload-post dashboard.

const PLATFORM_URL = {
  yt: 'https://studio.youtube.com/',
  tt: 'https://www.tiktok.com/business/dashboard/',
  ig: 'https://www.instagram.com/',
  fb: 'https://www.facebook.com/',
  x:  'https://x.com/',
};

const PLATFORM_HANDLE_URL = {
  yt: (h) => h ? `https://www.youtube.com/${h.replace(/^@/, '@')}` : PLATFORM_URL.yt,
  tt: (h) => h ? `https://www.tiktok.com/${h.replace(/^@/, '@')}`  : PLATFORM_URL.tt,
  ig: (h) => h ? `https://www.instagram.com/${h.replace(/^@/, '')}/` : PLATFORM_URL.ig,
  fb: (h) => h ? `https://www.facebook.com/${h.replace(/^@/, '')}/` : PLATFORM_URL.fb,
  x:  (h) => h ? `https://x.com/${h.replace(/^@/, '')}` : PLATFORM_URL.x,
};

function openUrl(url) {
  if (!url) return;
  if (window.penelope?.openExternal) window.penelope.openExternal(url);
  else window.open(url, '_blank');
}
function pulse() { if (window.penelopeDev?.pulse) window.penelopeDev.pulse(); }

export function renderAnalytics(data) {
  renderPlatform('yt', data.youtube || {});
  renderPlatform('tt', data.tiktok || {});
}

function renderPlatform(prefix, p) {
  const channels = p.channels || [];
  const sumSubs = channels.reduce((s, c) => s + (c.subs || 0), 0);
  const sumViews = channels.reduce((s, c) => s + (c.views_today || 0), 0);
  const sumViews28 = channels.reduce((s, c) => s + (c.views_28d || 0), 0);

  const stats = document.getElementById(`${prefix}-stats`);
  stats.innerHTML = `
    <div class="stat"><span class="label">Subs</span><div class="value">${fmt(sumSubs)}</div></div>
    <div class="stat"><span class="label">Views 24h</span><div class="value">${fmt(sumViews)}</div></div>
    <div class="stat"><span class="label">Views 28d</span><div class="value">${fmt(sumViews28)}</div></div>
  `;
  stats.style.cursor = 'pointer';
  stats.title = 'Open upload-post analytics';
  stats.onclick = () => { pulse(); openUrl('https://app.upload-post.com/analytics'); };

  const chart = document.getElementById(`${prefix}-chart`);
  drawBars(chart, p.series_views || []);
  chart.style.cursor = 'pointer';
  chart.title = `Open ${prefix === 'yt' ? 'YouTube Studio' : 'TikTok Studio'}`;
  chart.onclick = () => { pulse(); openUrl(PLATFORM_URL[prefix]); };

  // Top performers across channels with clickable rows linking out to
  // each channel's platform page for that brand.
  const top = document.getElementById(`${prefix}-top`);
  top.innerHTML = '';
  const all = [];
  for (const c of channels) {
    for (const v of (c.top || [])) {
      all.push({ ...v, ch: c.name, handle: c.platform_handle });
    }
  }
  all.sort((a, b) => (b.views || 0) - (a.views || 0));
  // Fallback: if no top videos, show per-channel rows with subs/views_28d
  if (!all.length) {
    for (const c of channels.slice(0, 4)) {
      const el = document.createElement('li');
      el.innerHTML = `<span>${c.name}</span><b>${fmt(c.subs || 0)} subs · ${fmt(c.views_28d || 0)} v</b>`;
      el.style.cursor = 'pointer';
      el.title = `Open ${c.name} on ${prefix.toUpperCase()}`;
      el.onclick = () => { pulse(); openUrl(PLATFORM_HANDLE_URL[prefix](c.platform_handle)); };
      el.addEventListener('mouseenter', () =>
        el.style.boxShadow = 'inset 0 0 0 1px rgba(0,229,255,0.4)');
      el.addEventListener('mouseleave', () => el.style.boxShadow = '');
      top.appendChild(el);
    }
    return;
  }
  for (const v of all.slice(0, 4)) {
    const el = document.createElement('li');
    const label = v.ch ? `${v.ch} · ${truncate(v.title || '', 18)}`
                       : truncate(v.title || '', 24);
    el.innerHTML = `<span>${label}</span><b>${fmt(v.views || 0)}</b>`;
    el.style.cursor = 'pointer';
    el.title = `Open ${v.ch} on ${prefix.toUpperCase()}`;
    el.onclick = () => { pulse(); openUrl(PLATFORM_HANDLE_URL[prefix](v.handle)); };
    el.addEventListener('mouseenter', () =>
      el.style.boxShadow = 'inset 0 0 0 1px rgba(0,229,255,0.4)');
    el.addEventListener('mouseleave', () => el.style.boxShadow = '');
    top.appendChild(el);
  }
}

function fmt(n) {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return String(n);
}
function truncate(s, n) { return s.length > n ? s.slice(0, n - 1) + '…' : s; }

function drawBars(canvas, points) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  canvas.width = canvas.clientWidth * dpr;
  canvas.height = canvas.clientHeight * dpr;
  ctx.scale(dpr, dpr);
  const w = canvas.clientWidth, h = canvas.clientHeight;
  ctx.clearRect(0, 0, w, h);
  if (!points.length) return;
  const max = Math.max(...points) || 1;
  const bw = (w - 8) / points.length;
  ctx.fillStyle = '#00E5FF';
  ctx.shadowColor = '#00E5FF';
  ctx.shadowBlur = 6;
  for (let i = 0; i < points.length; i++) {
    const bh = (points[i] / max) * (h - 8);
    const x = 4 + i * bw;
    const y = h - 4 - bh;
    ctx.fillRect(x + 1, y, bw - 2, bh);
  }
}
