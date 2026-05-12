// Penelope face — Star Wars hologram approach.
//
// The previous build stippled the photo into 7000 huge additively-blended
// particles, which saturated into a glowing blob. New approach:
//
//   1. Render the photo on a plane with a custom shader that:
//      - converts to luminance and tints cyan
//      - adds moving horizontal scanlines (interference)
//      - flickers + breathes opacity
//      - quantizes brightness so it reads as data, not a photo
//   2. Sprinkle a thin layer of tiny crisp particle dots ABOVE the
//      photo plane — these drift kinetically along feature contours.
//
// Result: Penelope's actual face is recognizable, with the kinetic
// electric-blue "she's a hologram" feel layered on top.

import * as THREE from '../vendor/three.module.js';

const IMG_REL = 'assets/penelope_base.webp';
const SAMPLE_SIZE = 768;            // higher sample = sharper feature edges
const PARTICLE_COUNT = 80000;        // dense enough that the face is built
                                     // entirely by particle density — no
                                     // photo plane needed. M-series Macs
                                     // handle 100k points easily.


export class PenelopeFace {
  constructor(canvas) {
    this.canvas = canvas;
    this._raf = null;
    this._mode = 'warm';
    this._idleIntensity = 0.65;
    this._breathRate = 0.45;
    this._vJaw = 0; this._vCheek = 0; this._vEye = 0;
    this._vMouthOpen = 0; this._vMouthWide = 0;
    this._vIntensity = 0.65;
    this._blinkT = 0; this._blinking = false;
    this._bootStart = null;
    this._bootDuration = 12000;
    this._bootResolve = null;

    this._initThree();
    this._scheduleBlink();
    window.addEventListener('resize', () => this._handleResize());
  }

  _initThree() {
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas, antialias: true, alpha: true,
      preserveDrawingBuffer: false,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(window.innerWidth, window.innerHeight, false);
    this.renderer.setClearColor(0x000000, 0);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(
      35, window.innerWidth / window.innerHeight, 0.01, 100);
    this.camera.position.set(0, 0, 2.4);

    this.clock = new THREE.Clock();

    this.uniforms = {
      uTime:         { value: 0 },
      uBreath:       { value: 0 },
      uBlink:        { value: 0 },
      uJaw:          { value: 0 },
      uMouthOpen:    { value: 0 },
      uMouthWide:    { value: 0 },
      uCheek:        { value: 0 },
      uEye:          { value: 0 },
      uIntensity:    { value: 0.65 },
      uBootProgress: { value: 0 },
      uAccent:       { value: new THREE.Color(0x00E5FF) },
      uTexture:      { value: null },
      uPhotoOpacity: { value: 0 },     // ramps to 1 during boot
    };

    this._buildFromImage().catch((e) => {
      console.warn('[face] image load failed', e);
    });
  }

  async _buildFromImage() {
    const img = await this._loadImage(IMG_REL);
    const tmp = document.createElement('canvas');
    tmp.width = SAMPLE_SIZE; tmp.height = SAMPLE_SIZE;
    const ctx = tmp.getContext('2d');
    // Cover-fit
    const scale = Math.max(SAMPLE_SIZE / img.width, SAMPLE_SIZE / img.height);
    const dw = img.width * scale, dh = img.height * scale;
    const dx = (SAMPLE_SIZE - dw) / 2, dy = (SAMPLE_SIZE - dh) / 2;
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, SAMPLE_SIZE, SAMPLE_SIZE);
    ctx.drawImage(img, dx, dy, dw, dh);
    const data = ctx.getImageData(0, 0, SAMPLE_SIZE, SAMPLE_SIZE).data;

    const W = SAMPLE_SIZE, H = SAMPLE_SIZE;
    const lum = new Float32Array(W * H);
    for (let i = 0; i < W * H; i++) {
      const j = i * 4;
      lum[i] = (0.299 * data[j] + 0.587 * data[j+1] + 0.114 * data[j+2]) / 255;
    }
    // Feature weight: bright skin areas get base density (so the face HAS
    // surface), edges/dark features (eyes, brows, lips, hair, jaw line)
    // get MUCH higher density. Background gets zero so she emerges from
    // the void.
    const weight = new Float32Array(W * H);
    let maxW = 0;
    for (let y = 1; y < H - 1; y++) {
      for (let x = 1; x < W - 1; x++) {
        const i = y * W + x;
        // Sobel-style gradient (edges)
        const gx = Math.abs(lum[i+1] - lum[i-1]) + 0.5 * Math.abs(lum[i+W+1] - lum[i+W-1]);
        const gy = Math.abs(lum[i+W] - lum[i-W]) + 0.5 * Math.abs(lum[i+W+1] - lum[i-W+1]);
        const grad = gx + gy;
        const lumi = lum[i];
        // Background mask: below 0.04 luminance → drop entirely
        const onFace = lumi > 0.04 ? 1 : 0;
        // Three contributions:
        //   1) base density on her face (skin surface)
        //   2) extra density on dark features (hair, eyes, lips)
        //   3) BIG extra on edges (jaw line, brow line, lip outline)
        const base = onFace * 0.18;
        const dark = onFace * Math.max(0, 0.55 - lumi) * 1.4;
        const edge = grad * 5.0;
        const w = base + dark + edge;
        weight[i] = w;
        if (w > maxW) maxW = w;
      }
    }

    // Dense rejection sampling — 80k particles
    const positions = new Float32Array(PARTICLE_COUNT * 3);
    const seeds     = new Float32Array(PARTICLE_COUNT);
    const sizes     = new Float32Array(PARTICLE_COUNT);
    const bright    = new Float32Array(PARTICLE_COUNT);
    let placed = 0;
    let attempts = 0;
    const cap = PARTICLE_COUNT * 60;
    while (placed < PARTICLE_COUNT && attempts < cap) {
      attempts++;
      const x = (Math.random() * W) | 0;
      const y = (Math.random() * H) | 0;
      const i = y * W + x;
      const wn = weight[i] / maxW;
      if (Math.random() > wn) continue;
      // Plane mapping: 1.5 wide × 1.875 tall portrait
      const nx = (x / W - 0.5) * 1.5;
      const ny = -(y / H - 0.5) * 1.875;
      // Slight depth from luminance (lighter = forward → subtle 3D feel)
      const nz = (lum[i] - 0.5) * 0.06;
      const off = placed * 3;
      positions[off]     = nx;
      positions[off + 1] = ny;
      positions[off + 2] = nz;
      seeds[placed]      = Math.random();
      // Tiny dots, 0.8-1.6 device-px. Bright pixels get slightly bigger
      // particles so highlights pop subtly. No additive blow-out.
      sizes[placed]      = 0.7 + Math.random() * 0.6;
      bright[placed]     = lum[i];
      placed++;
    }
    console.log(`[face] ${placed} particles placed (attempted ${attempts})`);

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions.slice(0, placed*3), 3));
    geo.setAttribute('aSeed',    new THREE.BufferAttribute(seeds.slice(0, placed), 1));
    geo.setAttribute('aSize',    new THREE.BufferAttribute(sizes.slice(0, placed), 1));
    geo.setAttribute('aBright',  new THREE.BufferAttribute(bright.slice(0, placed), 1));

    const mat = new THREE.ShaderMaterial({
      uniforms: this.uniforms,
      transparent: true,
      blending: THREE.NormalBlending,
      depthWrite: false,
      vertexShader: `
        attribute float aSeed;
        attribute float aSize;
        attribute float aBright;
        uniform float uTime;
        uniform float uBootProgress;
        uniform float uIntensity;
        uniform float uBreath;
        uniform float uJaw;
        uniform float uMouthOpen;
        uniform float uBlink;
        varying float vGlow;
        varying float vBright;
        varying float vSeed;

        void main() {
          vec3 pos = position;
          float seed = aSeed;

          // Subtle whole-face breath
          pos *= 1.0 + 0.012 * uBreath;

          // Sub-pixel kinetic drift — gives the "alive data" feel
          pos.x += sin(uTime * 0.9 + seed * 11.0) * 0.003;
          pos.y += cos(uTime * 0.7 + seed * 13.0) * 0.003;
          pos.z += sin(uTime * 1.1 + seed * 7.0) * 0.002;

          // Jaw drop — pull lower-third down on TTS bass
          float lowerMask = smoothstep(0.0, -0.6, pos.y);
          pos.y -= (uJaw * 0.04 + uMouthOpen * 0.05) * lowerMask;

          // Blink — collapse eye band
          float eyeMask = smoothstep(0.06, 0.0, abs(pos.y - 0.18));
          pos.y = mix(pos.y, 0.18, uBlink * eyeMask);

          // Boot scatter -> assembly: random offsets that fade to base
          vec3 scattered = position + vec3(
            (seed - 0.5) * 5.0,
            (fract(seed * 17.3) - 0.5) * 5.0,
            (fract(seed * 31.7) - 0.5) * 2.0
          );
          float prog = smoothstep(0.0, 1.0, uBootProgress);
          pos.xy = mix(scattered.xy, pos.xy, prog);
          pos.z  = mix(scattered.z,  pos.z,  prog);

          vec4 mv = modelViewMatrix * vec4(pos, 1.0);
          gl_Position = projectionMatrix * mv;

          // Tiny crisp points — 0.8-1.6px at full assembly
          gl_PointSize = aSize * 1.4 * (0.65 + 0.6 * uBootProgress);

          vGlow = uIntensity * (0.5 + 0.5 * seed) * uBootProgress;
          vBright = aBright;
          vSeed = seed;
        }
      `,
      fragmentShader: `
        uniform vec3 uAccent;
        uniform float uTime;
        varying float vGlow;
        varying float vBright;
        varying float vSeed;
        void main() {
          // Hard tiny dot with very soft edge
          vec2 q = gl_PointCoord - 0.5;
          float d = length(q);
          if (d > 0.5) discard;
          float a = smoothstep(0.5, 0.08, d);
          // Twinkle: each particle pulses at its own seeded rhythm
          float twinkle = 0.78 + 0.22 * sin(uTime * 2.4 + vSeed * 25.0);
          // Brighter particles where the source photo was light (skin
          // highlights, eyes, teeth). Cap so they don't blow out.
          vec3 col = uAccent * (0.75 + 0.55 * vBright + 0.55 * vGlow);
          col += vec3(1.0) * pow(vBright, 5.0) * 0.4;
          gl_FragColor = vec4(col, a * twinkle * (0.55 + 0.45 * vGlow));
        }
      `,
    });

    this.points = new THREE.Points(geo, mat);
    this.scene.add(this.points);
    // Mark plane as null so the rest of the code knows we're particle-only.
    this.plane = null;
  }

  async _loadImage(src) {
    // Prefer IPC channel (returns base64) — works inside packaged app.
    if (window.penelope?.readAsset) {
      try {
        const b64 = await window.penelope.readAsset(src);
        if (b64) {
          const ext = src.split('.').pop().toLowerCase();
          const mime = ext === 'webp' ? 'image/webp'
                     : ext === 'jpg' || ext === 'jpeg' ? 'image/jpeg'
                     : ext === 'png' ? 'image/png' : 'image/*';
          return await new Promise((res, rej) => {
            const img = new Image();
            img.onload = () => res(img);
            img.onerror = (e) => rej(e);
            img.src = `data:${mime};base64,${b64}`;
          });
        }
      } catch (e) {
        console.warn('[face] readAsset failed, falling back to URL:', e);
      }
    }
    // Dev fallback
    return await new Promise((res, rej) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => res(img);
      img.onerror = (e) => rej(e);
      img.src = new URL('../' + src, import.meta.url).href;
    });
  }

  _scheduleBlink() {
    const wait = 4000 + Math.random() * 3500;
    setTimeout(() => {
      this._blinkT = 0; this._blinking = true;
      this._scheduleBlink();
    }, wait);
  }

  _handleResize() {
    const w = window.innerWidth, h = window.innerHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  setLowPower(on) {
    this.renderer.setPixelRatio(on ? 1 : Math.min(window.devicePixelRatio || 1, 2));
  }

  bootAssemble(durationMs = 12000) {
    return new Promise((resolve) => {
      this._bootStart = performance.now();
      this._bootDuration = durationMs;
      this._bootResolve = resolve;
    });
  }

  setReactivity(bands) {
    if (!bands) return;
    this._vJaw = bands.bass || 0;
    this._vCheek = bands.mid || 0;
    this._vEye = bands.high || 0;
    this._vIntensity = 0.5 + (bands.amp || 0) * 0.5;
  }

  setViseme(v) {
    if (!v) return;
    this._vMouthOpen = v.open || 0;
    this._vMouthWide = v.wide || 0;
  }

  setIdle() {
    this._vJaw = 0; this._vCheek = 0; this._vEye = 0;
    this._vMouthOpen = 0; this._vMouthWide = 0;
    this._vIntensity = this._idleIntensity;
  }

  setMode(mode) {
    this._mode = mode || 'warm';
    if (mode === 'flirty') {
      this._idleIntensity = 0.78;
      this._breathRate = 0.32;
    } else if (mode === 'professional') {
      this._idleIntensity = 0.52;
      this._breathRate = 0.55;
    } else {
      this._idleIntensity = 0.65;
      this._breathRate = 0.45;
    }
  }

  pulse(strength = 0.35, durationMs = 600) {
    const prev = this._vIntensity;
    this._vIntensity = Math.min(1, prev + strength);
    setTimeout(() => { this._vIntensity = prev; }, durationMs);
  }

  start() {
    const tick = () => {
      const dt = this.clock.getDelta();
      const t = this.clock.elapsedTime;
      const u = this.uniforms;
      u.uTime.value = t;
      u.uBreath.value = Math.sin(t * this._breathRate) * 0.5 + 0.5;

      if (this._blinking) {
        this._blinkT += dt;
        const dur = 0.16;
        u.uBlink.value = this._blinkT < dur / 2
          ? this._blinkT / (dur / 2)
          : Math.max(0, 1 - (this._blinkT - dur / 2) / (dur / 2));
        if (this._blinkT > dur) { this._blinking = false; u.uBlink.value = 0; }
      } else {
        u.uBlink.value = 0;
      }

      const lerp = (a, b, k) => a + (b - a) * k;
      u.uJaw.value       = lerp(u.uJaw.value,       this._vJaw,       0.25);
      u.uMouthOpen.value = lerp(u.uMouthOpen.value, this._vMouthOpen, 0.35);
      u.uMouthWide.value = lerp(u.uMouthWide.value, this._vMouthWide, 0.25);
      u.uCheek.value     = lerp(u.uCheek.value,     this._vCheek,     0.18);
      u.uEye.value       = lerp(u.uEye.value,       this._vEye,       0.22);
      u.uIntensity.value = lerp(u.uIntensity.value, this._vIntensity, 0.1);

      // Photo opacity follows boot — ramps from 0 to 1 over assembly
      u.uPhotoOpacity.value = lerp(u.uPhotoOpacity.value,
                                    u.uBootProgress.value, 0.06);

      if (this._bootStart) {
        const elapsed = performance.now() - this._bootStart;
        const p = Math.min(1, elapsed / this._bootDuration);
        u.uBootProgress.value = 1 - Math.pow(1 - p, 3);
        if (p >= 1 && this._bootResolve) {
          this._bootResolve();
          this._bootResolve = null;
          this._bootStart = null;
        }
      }

      this.renderer.render(this.scene, this.camera);
      this._raf = requestAnimationFrame(tick);
    };
    this._raf = requestAnimationFrame(tick);
  }

  stop() { if (this._raf) cancelAnimationFrame(this._raf); }
}
