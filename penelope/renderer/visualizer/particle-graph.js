// Particle graph renderer — every module body uses this so the entire UI
// reads as the same kinetic electric-blue hologram material as her face.
//
// Each "graph" is a 2D canvas. We compute a target point cloud once per
// data update (text glyphs stippled into dots, bar columns built from
// stacked dots, sparkline traced as a dot trail), then a single shared
// animation loop drifts every dot subtly and redraws with additive
// cyan blending. Star Wars hologram, full-interface.

const ACCENT = '#00E5FF';
const ACCENT_RGB = [0, 229, 255];

const _registry = [];          // [{canvas, dots, draw}]
let _rafStarted = false;

function startLoop() {
  if (_rafStarted) return;
  _rafStarted = true;
  const tick = () => {
    const t = performance.now() / 1000;
    for (const it of _registry) it.draw(t);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function makeDot(x, y, brightness = 1, size = 1.2) {
  return {
    bx: x, by: y,                       // base position
    x, y,
    sz: size,
    b: brightness,
    sd: Math.random() * Math.PI * 2,    // drift seed
    sr: 0.6 + Math.random() * 1.8,      // drift radius
    sp: 0.6 + Math.random() * 1.4,      // drift speed
  };
}

function resizeCanvas(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = canvas.clientWidth || 240;
  const h = canvas.clientHeight || 80;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  return { ctx, w, h };
}

function drawDots(ctx, dots, t, w, h) {
  ctx.clearRect(0, 0, w, h);
  ctx.globalCompositeOperation = 'lighter';
  for (const d of dots) {
    // kinetic drift
    const dx = Math.sin(t * d.sp + d.sd) * d.sr;
    const dy = Math.cos(t * d.sp * 0.85 + d.sd * 1.3) * d.sr;
    const x = d.bx + dx;
    const y = d.by + dy;
    const flick = 0.75 + 0.25 * Math.sin(t * 2.0 + d.sd);
    // core
    ctx.fillStyle = `rgba(${ACCENT_RGB[0]},${ACCENT_RGB[1]},${ACCENT_RGB[2]},${0.85 * d.b * flick})`;
    ctx.beginPath();
    ctx.arc(x, y, d.sz, 0, Math.PI * 2);
    ctx.fill();
    // soft halo
    ctx.fillStyle = `rgba(${ACCENT_RGB[0]},${ACCENT_RGB[1]},${ACCENT_RGB[2]},${0.18 * d.b * flick})`;
    ctx.beginPath();
    ctx.arc(x, y, d.sz * 3, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalCompositeOperation = 'source-over';
}


// ── Text → dots: stipple a glyph string into a sparse point cloud ──

function stippleText(text, w, h, opts = {}) {
  const fontSize = opts.fontSize || Math.floor(h * 0.72);
  const tmp = document.createElement('canvas');
  tmp.width = w; tmp.height = h;
  const c = tmp.getContext('2d');
  c.fillStyle = '#fff';
  c.font = `${opts.weight || 300} ${fontSize}px ui-monospace, "JetBrains Mono", "SF Mono", Menlo, monospace`;
  c.textAlign = opts.align || 'left';
  c.textBaseline = 'middle';
  c.fillText(String(text), opts.align === 'center' ? w / 2 : (opts.padLeft || 4),
             h / 2 + (opts.yOffset || 0));
  const data = c.getImageData(0, 0, w, h).data;
  const stride = opts.stride || 3;
  const dots = [];
  for (let y = 0; y < h; y += stride) {
    for (let x = 0; x < w; x += stride) {
      const a = data[(y * w + x) * 4 + 3];
      if (a > 80) {
        dots.push(makeDot(x + (Math.random() - 0.5) * 1.5,
                          y + (Math.random() - 0.5) * 1.5,
                          0.6 + Math.random() * 0.4,
                          0.7 + Math.random() * 0.8));
      }
    }
  }
  return dots;
}


// ── Public API ─────────────────────────────────────────────────────────

export function bigNumber(canvas, text) {
  const { ctx, w, h } = resizeCanvas(canvas);
  const dots = stippleText(text, w, h, {
    fontSize: Math.floor(h * 0.78),
    align: 'left',
    weight: 200,
    stride: 2,
  });
  registerOrUpdate(canvas, dots, ctx, w, h);
}

export function smallNumber(canvas, text) {
  const { ctx, w, h } = resizeCanvas(canvas);
  const dots = stippleText(text, w, h, {
    fontSize: Math.floor(h * 0.6),
    align: 'left',
    weight: 300,
    stride: 2,
  });
  registerOrUpdate(canvas, dots, ctx, w, h);
}

export function barChart(canvas, values, opts = {}) {
  const { ctx, w, h } = resizeCanvas(canvas);
  if (!values || !values.length) {
    registerOrUpdate(canvas, [], ctx, w, h);
    return;
  }
  const max = Math.max(...values, 1);
  const bw = w / values.length;
  const gap = Math.max(2, bw * 0.18);
  const dots = [];
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    const bh = (v / max) * (h - 12);
    const x0 = i * bw + gap / 2;
    const x1 = (i + 1) * bw - gap / 2;
    const y0 = h - 4 - bh;
    const y1 = h - 4;
    // Fill column with stippled dots — density proportional to value (so taller bars are also more dense)
    const density = 0.55 + 0.4 * (v / max);
    for (let y = y0; y < y1; y += 3) {
      for (let x = x0; x < x1; x += 3) {
        if (Math.random() < density) {
          dots.push(makeDot(x + (Math.random() - 0.5) * 1.2,
                            y + (Math.random() - 0.5) * 1.2,
                            0.55 + Math.random() * 0.45,
                            0.6 + Math.random() * 0.6));
        }
      }
    }
  }
  registerOrUpdate(canvas, dots, ctx, w, h);
}

export function sparkline(canvas, values) {
  const { ctx, w, h } = resizeCanvas(canvas);
  if (!values || !values.length) {
    registerOrUpdate(canvas, [], ctx, w, h);
    return;
  }
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const dots = [];
  const pad = 6;
  for (let i = 0; i < values.length; i++) {
    const x = pad + (i / (values.length - 1)) * (w - pad * 2);
    const y = h - pad - ((values[i] - min) / range) * (h - pad * 2);
    // Multiple dots per point for thickness + trail
    for (let k = 0; k < 4; k++) {
      const ox = (Math.random() - 0.5) * 2;
      const oy = (Math.random() - 0.5) * 2;
      dots.push(makeDot(x + ox, y + oy,
                        0.7 + Math.random() * 0.3,
                        0.8 + Math.random() * 0.6));
    }
  }
  registerOrUpdate(canvas, dots, ctx, w, h);
}


// Internal — keep one entry per canvas in the shared animation registry.
function registerOrUpdate(canvas, dots, ctx, w, h) {
  let it = _registry.find(r => r.canvas === canvas);
  if (!it) {
    it = { canvas, dots, draw: null };
    _registry.push(it);
  } else {
    it.dots = dots;
  }
  it.draw = (t) => drawDots(ctx, it.dots, t, w, h);
  startLoop();
}
