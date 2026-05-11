// Revenue panel: totals, per-source breakdown, sparkline chart.
// Data shape (config/revenue.json):
//   {
//     "total_today": 1234.50,
//     "total_mtd": 23450.10,
//     "total_ytd": 198320.00,
//     "currency": "USD",
//     "series_daily": [120, 180, 210, ...]   // last ~30 days
//     "sources": [
//       {"name": "Stripe", "today": 800, "mtd": 14000},
//       {"name": "Gumroad", "today": 220, "mtd": 4500},
//       {"name": "AdSense", "today": 214.50, "mtd": 4950.10}
//     ]
//   }

export function renderRevenue(data) {
  const fmt = new Intl.NumberFormat('en-US', {
    style: 'currency', currency: data.currency || 'USD',
    maximumFractionDigits: 0,
  });
  document.getElementById('revenue-total').textContent =
    fmt.format(data.total_today || 0);

  drawSparkline(document.getElementById('revenue-chart'),
                data.series_daily || []);

  const list = document.getElementById('revenue-list');
  list.innerHTML = '';
  list.appendChild(li('MTD', fmt.format(data.total_mtd || 0)));
  list.appendChild(li('YTD', fmt.format(data.total_ytd || 0)));
  for (const s of (data.sources || [])) {
    list.appendChild(li(s.name, fmt.format(s.today || 0)));
  }
}

function li(k, v) {
  const el = document.createElement('li');
  el.innerHTML = `<span>${k}</span><b>${v}</b>`;
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
  // gradient fill underneath
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
