// Revenue panel: totals, per-source breakdown, sparkline chart.
// Now clickable — each row deep-links to the source dashboard and pulses
// the face on click.
//
// Data shape (config/revenue.json):
//   {
//     "total_today": 1234.50, "total_mtd": ..., "total_ytd": ...,
//     "currency": "USD", "series_daily": [...],
//     "sources": [{"name": "Stripe", "today": 800, "mtd": 14000}, ...]
//   }

const SOURCE_URLS = {
  Stripe:     'https://dashboard.stripe.com/',
  Gumroad:    'https://app.gumroad.com/dashboard',
  AdSense:    'https://adsense.google.com/',
  ElevenLabs: 'https://elevenlabs.io/app/voice-lab',
};

function openUrl(url) {
  if (!url) return;
  // electron preload exposes openExternal; renderer-only fallback to window.open
  if (window.penelope?.openExternal) window.penelope.openExternal(url);
  else window.open(url, '_blank');
}

function pulse() {
  if (window.penelopeDev?.pulse) window.penelopeDev.pulse();
}

export function renderRevenue(data) {
  const fmt = new Intl.NumberFormat('en-US', {
    style: 'currency', currency: data.currency || 'USD',
    maximumFractionDigits: 0,
  });

  const totalEl = document.getElementById('revenue-total');
  totalEl.textContent = fmt.format(data.total_today || 0);
  totalEl.style.cursor = 'pointer';
  totalEl.title = 'Open Stripe dashboard';
  totalEl.onclick = () => { pulse(); openUrl(SOURCE_URLS.Stripe); };

  const chart = document.getElementById('revenue-chart');
  drawSparkline(chart, data.series_daily || []);
  chart.style.cursor = 'pointer';
  chart.title = 'Click to open Stripe Express dashboard';
  chart.onclick = () => { pulse(); openUrl('https://connect.stripe.com/express_login'); };

  const list = document.getElementById('revenue-list');
  list.innerHTML = '';
  list.appendChild(li('MTD', fmt.format(data.total_mtd || 0)));
  list.appendChild(li('YTD', fmt.format(data.total_ytd || 0)));
  for (const s of (data.sources || [])) {
    const url = SOURCE_URLS[s.name];
    list.appendChild(li(s.name, fmt.format(s.today || 0), url));
  }
}

function li(k, v, url) {
  const el = document.createElement('li');
  el.innerHTML = `<span>${k}</span><b>${v}</b>`;
  if (url) {
    el.style.cursor = 'pointer';
    el.title = `Open ${k} dashboard`;
    el.onclick = () => { pulse(); openUrl(url); };
    el.addEventListener('mouseenter', () =>
      el.style.boxShadow = 'inset 0 0 0 1px rgba(0,229,255,0.4)');
    el.addEventListener('mouseleave', () => el.style.boxShadow = '');
  }
  return el;
}

function drawSparkline(canvas, points) {
  if (!canvas || !points.length) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  canvas.width = canvas.clientWidth * dpr;
  canvas.height = canvas.clientHeight * dpr;
  ctx.scale(dpr, dpr);
  const w = canvas.clientWidth, h = canvas.clientHeight;
  ctx.clearRect(0, 0, w, h);
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const pad = 8;
  ctx.strokeStyle = '#00E5FF';
  ctx.lineWidth = 1.5;
  ctx.shadowColor = '#00E5FF';
  ctx.shadowBlur = 8;
  ctx.beginPath();
  points.forEach((v, i) => {
    const x = pad + (i / (points.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.lineTo(w - pad, h - pad);
  ctx.lineTo(pad, h - pad);
  ctx.closePath();
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, 'rgba(0,229,255,0.35)');
  g.addColorStop(1, 'rgba(0,229,255,0)');
  ctx.fillStyle = g;
  ctx.shadowBlur = 0;
  ctx.fill();
}
