// Penelope face — texture-driven particle stippling.
//
// We sample assets/penelope_base.webp (a sharp front-facing photo of her)
// and distribute thousands of cyan particles where the image's features
// are densest: hair, eyes, lips, brows, nose ridge, jaw line.
//
// Approach:
//   1. Draw the photo into an offscreen canvas at 512×512.
//   2. For every pixel compute a feature-weight =
//          (1 − luminance) × 0.5
//        + Sobel-style gradient magnitude × 3.0
//      So darker areas (hair, eye sockets, lips) and edges (jaw,
//      cheekbone) accumulate weight.
//   3. Rejection-sample N particles in proportion to that weight.
//   4. Each particle keeps an (x, y) in image-space, mapped to a
//      centered ±1 world plane plus a tiny z offset from luminance
//      (darker → closer, gives depth).
//   5. A custom shader renders the cloud with cyan-tinted additive
//      blending, sub-pixel-soft circular sprites, slow kinetic drift,
//      breath / blink, and lip/jaw deformation from setReactivity().
//
// The face IS the photo — but rendered as electric kinetic data.

import * as THREE from '../vendor/three.module.js';

const IMG_URL = '../assets/penelope_base.webp';
const SAMPLE_SIZE = 512;          // analyze at 512×512
const PARTICLE_COUNT = 7000;       // total cyan dots
const HAIR_DARK_THRESHOLD = 0.18;  // luminance below this = "hair-class" particle


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
    const { width, height } = this.canvas.getBoundingClientRect();
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
    this.camera.position.set(0, 0, 2.6);

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
    };

    // Async: load image, build geometry, add to scene.
    this._buildFromImage().catch((e) => {
      console.warn('face image load failed; falling back to mesh-less placeholder', e);
    });
  }

  async _buildFromImage() {
    const img = await this._loadImage(IMG_URL);
    const tmp = document.createElement('canvas');
    tmp.width = SAMPLE_SIZE; tmp.height = SAMPLE_SIZE;
    const ctx = tmp.getContext('2d');
    // letterbox-fit so the photo's aspect is preserved
    const scale = Math.min(SAMPLE_SIZE / img.width, SAMPLE_SIZE / img.height);
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
    // Sobel-ish gradient + feature weight
    const weight = new Float32Array(W * H);
    let maxW = 0;
    for (let y = 1; y < H - 1; y++) {
      for (let x = 1; x < W - 1; x++) {
        const i = y * W + x;
        const grad = Math.abs(lum[i+1]   - lum[i-1])
                   + Math.abs(lum[i+W]   - lum[i-W]);
        // Darkness contributes too — hair / eyes / lips become particle-rich
        const darkness = Math.max(0, 0.9 - lum[i]);
        const w = darkness * 0.55 + grad * 3.2;
        weight[i] = w;
        if (w > maxW) maxW = w;
      }
    }

    // Rejection-sample particles
    const positions = new Float32Array(PARTICLE_COUNT * 3);
    const colors    = new Float32Array(PARTICLE_COUNT * 3);
    const sizes     = new Float32Array(PARTICLE_COUNT);
    const seeds     = new Float32Array(PARTICLE_COUNT);
    const clusters  = new Float32Array(PARTICLE_COUNT);  // 0=skin/hair, 1=feature-edge
    let placed = 0;
    let attempts = 0;
    while (placed < PARTICLE_COUNT && attempts < PARTICLE_COUNT * 40) {
      attempts++;
      const x = (Math.random() * W) | 0;
      const y = (Math.random() * H) | 0;
      const i = y * W + x;
      const wn = weight[i] / maxW;
      if (Math.random() > wn * wn) continue;        // bias toward strong features
      // Map to world: face plane is roughly ±0.9 in y, ±0.7 in x.
      const nx = (x / W - 0.5) * 1.4;
      const ny = -(y / H - 0.5) * 1.7;
      // Z offset: lighter (skin) is slightly back, dark (eye sockets, hair) slightly forward.
      const nz = (lum[i] - 0.45) * -0.18;
      const off = placed * 3;
      positions[off]     = nx;
      positions[off + 1] = ny;
      positions[off + 2] = nz;
      // Color: cyan core, hot-white highlights on feature edges.
      const g = weight[i] > 0.4 * maxW;            // strong feature?
      colors[off]     = g ? 0.35 : 0.05;
      colors[off + 1] = g ? 0.95 : 0.78;
      colors[off + 2] = 1.0;
      sizes[placed]   = 1.0 + Math.random() * 1.8 + (g ? 0.6 : 0);
      seeds[placed]   = Math.random();
      clusters[placed]= g ? 1.0 : 0.0;
      placed++;
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions.slice(0, placed*3), 3));
    geo.setAttribute('color',    new THREE.BufferAttribute(colors.slice(0, placed*3), 3));
    geo.setAttribute('aSize',    new THREE.BufferAttribute(sizes.slice(0, placed), 1));
    geo.setAttribute('aSeed',    new THREE.BufferAttribute(seeds.slice(0, placed), 1));
    geo.setAttribute('aCluster', new THREE.BufferAttribute(clusters.slice(0, placed), 1));

    const mat = new THREE.ShaderMaterial({
      uniforms: this.uniforms,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      vertexColors: true,
      vertexShader: `
        attribute float aSize;
        attribute float aSeed;
        attribute float aCluster;
        uniform float uTime;
        uniform float uBreath;
        uniform float uBlink;
        uniform float uJaw;
        uniform float uMouthOpen;
        uniform float uMouthWide;
        uniform float uCheek;
        uniform float uEye;
        uniform float uIntensity;
        uniform float uBootProgress;
        varying vec3  vCol;
        varying float vGlow;
        varying float vCluster;

        void main() {
          vec3 pos = position;
          float seed = aSeed;
          // Slow kinetic drift — sub-pixel motion gives the "alive data" feel
          pos.x += sin(uTime * 0.6 + seed * 9.0) * 0.0035;
          pos.y += cos(uTime * 0.5 + seed * 11.0) * 0.0035;
          pos.z += sin(uTime * 0.7 + seed * 7.0) * 0.0025;

          // breath: subtle whole-face scale
          pos *= (1.0 + 0.018 * uBreath);

          // jaw drop (bass + viseme): pull the lower-third down
          float lowerMask = smoothstep(0.0, -0.45, pos.y);
          pos.y -= (uJaw * 0.04 + uMouthOpen * 0.05) * lowerMask;

          // mouth wide stretch
          float mouthMask = smoothstep(0.18, 0.0, -pos.y) * smoothstep(0.18, 0.0, pos.y + 0.35);
          pos.x *= 1.0 + uMouthWide * 0.06 * mouthMask;

          // cheek bloom (mids): push outward at cheek y-band
          float cheekMask = smoothstep(0.0, 0.25, abs(pos.x) - 0.18) * smoothstep(-0.05, -0.3, pos.y);
          pos.xy += normalize(pos.xy + 1e-5) * uCheek * 0.02 * cheekMask;

          // blink: collapse eye y at the eye band
          float eyeMask = smoothstep(0.05, 0.0, abs(pos.y - 0.15));
          pos.y = mix(pos.y, 0.15, uBlink * eyeMask);

          // brow lift / eye shimmer (highs)
          pos.y += uEye * 0.008 * smoothstep(0.18, 0.35, pos.y);

          // boot assembly — start scattered, fly to face position
          vec3 scattered = position + vec3(
            (seed - 0.5) * 3.6,
            (fract(seed * 17.3) - 0.5) * 3.6,
            (fract(seed * 31.7) - 0.5) * 2.0
          );
          pos = mix(scattered, pos, smoothstep(0.0, 1.0, uBootProgress));

          vec4 mv = modelViewMatrix * vec4(pos, 1.0);
          gl_Position = projectionMatrix * mv;

          float sz = aSize;
          gl_PointSize = sz * (210.0 / -mv.z) * (0.65 + 0.5 * uBootProgress);

          vCol = color;
          vGlow = uIntensity * (0.65 + 0.45 * seed) * (0.6 + 0.4 * uBootProgress);
          vCluster = aCluster;
        }
      `,
      fragmentShader: `
        uniform vec3 uAccent;
        varying vec3  vCol;
        varying float vGlow;
        varying float vCluster;
        void main() {
          // soft circular point — radial falloff
          vec2 q = gl_PointCoord - 0.5;
          float d = length(q);
          if (d > 0.5) discard;
          float a = smoothstep(0.5, 0.0, d);
          // Mix cyan accent with sampled feature color, brighten on feature edges
          vec3 c = mix(uAccent, vCol, 0.55);
          c += vCluster * 0.35;       // feature edges get extra brightness
          c *= vGlow * 1.8;
          gl_FragColor = vec4(c, a);
        }
      `,
    });

    this.points = new THREE.Points(geo, mat);
    this.scene.add(this.points);
    console.log(`[face] built ${placed} particles from image`);
  }

  async _loadImage(src) {
    // In a packaged Electron build the assets live inside app.asar.unpacked
    // and the relative file:// path inside app.asar doesn't always resolve
    // for <img> tags. Prefer the IPC channel (returns base64) which goes
    // through main.js's resolveProjectFile -> unpacked path. Fall back to
    // a direct URL load for dev mode where assets are next to the script.
    const rel = src.startsWith('../') ? src.slice(3) : src;
    if (window.penelope?.readAsset) {
      try {
        const b64 = await window.penelope.readAsset(rel);
        if (b64) {
          // Detect type from extension; default to png — webp/jpeg both work
          const ext = rel.split('.').pop().toLowerCase();
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
    return await new Promise((res, rej) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => res(img);
      img.onerror = (e) => rej(e);
      img.src = new URL(src, import.meta.url).href;
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
