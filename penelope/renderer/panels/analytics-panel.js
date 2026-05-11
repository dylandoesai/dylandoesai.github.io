// Analytics panel: YouTube + TikTok via upload-post.com.
// Data shape (config/analytics.json):
//   {
//     "youtube": {
//       "channels": [
//         {"name": "...", "handle": "...", "subs": 0, "views_today": 0,
//          "views_28d": 0, "top": [{"title": "...", "views": 0}, ...]}
//       ],
//       "series_views": [120, 180, ...]  // last 14 days aggregate
//     },
//     "tiktok": { ...same shape... }
//   }

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

  drawBars(document.getElementById(`${prefix}-chart`),
           p.series_views || []);

  // Top performers across channels.
  // Each row shows the canonical brand name (= YouTube channel name)
  // alongside the post title; the per-platform handle isn't repeated
  // because the parent card already says which platform we're on.
  const top = document.getElementById(`${prefix}-top`);
  top.innerHTML = '';
  const all = [];
  for (const c of channels) for (const v of (c.top || [])) all.push({ ...v, ch: c.name });
  all.sort((a, b) => (b.views || 0) - (a.views || 0));
  for (const v of all.slice(0, 4)) {
    const el = document.createElement('li');
    const label = v.ch ? `${v.ch} · ${truncate(v.title || '', 18)}`
                       : truncate(v.title || '', 24);
    el.innerHTML = `<span>${label}</span><b>${fmt(v.views || 0)}</b>`;
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
