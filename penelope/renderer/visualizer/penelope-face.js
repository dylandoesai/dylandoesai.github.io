// Penelope face — 8M-particle photoreal hologram.
//
// The mesh is built offline by scripts/build_face_cloud.py:
//   1. MediaPipe FaceLandmarker extracts 478 3D landmarks from each of
//      the 25 Penelope Cruz reference photos.
//   2. The landmarks are averaged → a personal-identity 3D face mesh.
//   3. MediaPipe's canonical 898-triangle tessellation connects them.
//   4. 8M particles are sampled barycentrically on the mesh surface,
//      weighted by triangle area × feature importance (eyes/lips/brows
//      get extreme density, skin gets uniform coverage).
//   5. Each particle gets its color sampled from the texture at its UV
//      position, plus a region tag (skin/eye/brow/lip/nose/jaw) for
//      blendshape morphing.
//
// All of that is packed into assets/face-cloud.bin (213 MB, 8M × 28B).
//
// This module just loads the binary into GPU buffers and renders it.

import * as THREE from '../vendor/three.module.js';

const META_REL = 'assets/face-cloud-meta.json';
const CLOUD_REL = 'assets/face-cloud.bin';


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
    this._vSmile = 0; this._vBrowLift = 0;
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
      canvas: this.canvas, antialias: false, alpha: true,
      preserveDrawingBuffer: false, powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(window.innerWidth, window.innerHeight, false);
    this.renderer.setClearColor(0x000000, 0);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(
      28, window.innerWidth / window.innerHeight, 0.01, 100);
    this.camera.position.set(0, 0, 3.2);

    this.clock = new THREE.Clock();

    this.uniforms = {
      uTime:         { value: 0 },
      uBreath:       { value: 0 },
      uBlink:        { value: 0 },
      uJaw:          { value: 0 },
      uMouthOpen:    { value: 0 },
      uMouthWide:    { value: 0 },
      uSmile:        { value: 0 },
      uBrowLift:     { value: 0 },
      uCheek:        { value: 0 },
      uEye:          { value: 0 },
      uIntensity:    { value: 0.65 },
      uBootProgress: { value: 0 },
      uAccent:       { value: new THREE.Color(0x00E5FF) },
    };

    this._buildFromCloud().catch((e) => {
      console.warn('[face] cloud load failed', e);
    });
  }

  async _buildFromCloud() {
    const t0 = performance.now();

    // Fetch metadata
    let meta;
    if (window.penelope?.readAsset) {
      const b64 = await window.penelope.readAsset(META_REL);
      meta = JSON.parse(atob(b64));
    } else {
      const r = await fetch(new URL('../' + META_REL, import.meta.url).href);
      meta = await r.json();
    }
    const N = meta.count;
    const RS = meta.record_size;
    console.log(`[face] loading ${N.toLocaleString()} particles (${(N*RS/1024/1024)|0} MB)…`);

    // Fetch binary — use Buffer transport when available (transparent
    // Uint8Array on the renderer side, no base64 doubling).
    let bin;
    if (window.penelope?.readAssetBinary) {
      const buf = await window.penelope.readAssetBinary(CLOUD_REL);
      bin = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
    } else {
      const r = await fetch(new URL('../' + CLOUD_REL, import.meta.url).href);
      bin = new Uint8Array(await r.arrayBuffer());
    }
    console.log(`[face] binary loaded: ${(bin.byteLength/1024/1024)|0} MB in ${(performance.now()-t0)|0}ms`);

    // Reinterpret directly — no per-particle JS loop
    const buf = bin.buffer.slice(bin.byteOffset, bin.byteOffset + bin.byteLength);
    // Strided typed-array views: each particle is 28 bytes.
    // We need contiguous attribute arrays for THREE, so we extract.
    const positions = new Float32Array(N * 3);
    const colors    = new Uint8Array(N * 3);   // uint8 → normalized in shader
    const regions   = new Uint8Array(N);
    const seeds     = new Float32Array(N);

    const f32 = new Float32Array(buf);
    const u8  = new Uint8Array(buf);
    const stride32 = RS / 4;
    for (let i = 0; i < N; i++) {
      const f = i * stride32;
      const b = i * RS;
      // position (3 × float32 at offset 0)
      positions[i*3]   = f32[f];
      positions[i*3+1] = f32[f+1];
      positions[i*3+2] = f32[f+2];
      // rgb (3 × uint8 at offset 12)
      colors[i*3]   = u8[b+12];
      colors[i*3+1] = u8[b+13];
      colors[i*3+2] = u8[b+14];
      // region at offset 15
      regions[i] = u8[b+15];
      // seed (float32 at offset 20)
      seeds[i] = f32[f+5];
    }
    console.log(`[face] unpacked in ${(performance.now()-t0)|0}ms total`);

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('aColor',   new THREE.BufferAttribute(colors, 3, true));   // normalized 0..1
    geo.setAttribute('aRegion',  new THREE.BufferAttribute(regions, 1));
    geo.setAttribute('aSeed',    new THREE.BufferAttribute(seeds, 1));

    const mat = new THREE.ShaderMaterial({
      uniforms: this.uniforms,
      transparent: true,
      blending: THREE.NormalBlending,
      depthWrite: false,
      vertexShader: `
        attribute vec3  aColor;
        attribute float aRegion;
        attribute float aSeed;
        uniform float uTime;
        uniform float uBreath;
        uniform float uBlink;
        uniform float uJaw;
        uniform float uMouthOpen;
        uniform float uMouthWide;
        uniform float uSmile;
        uniform float uBrowLift;
        uniform float uIntensity;
        uniform float uBootProgress;
        varying vec3  vColor;
        varying float vGlow;
        varying float vSeed;

        void main() {
          vec3 pos = position;
          float seed = aSeed;
          float region = aRegion;   // 0=skin 1=eye 2=brow 3=lip 4=nose 6=jaw

          // Whole-head breath
          pos *= 1.0 + 0.008 * uBreath;

          // Sub-pixel kinetic drift — same seeded sin/cos as the rest of the UI
          pos.x += sin(uTime * 0.9 + seed * 11.0) * 0.0025;
          pos.y += cos(uTime * 0.7 + seed * 13.0) * 0.0025;
          pos.z += sin(uTime * 1.1 + seed *  7.0) * 0.0018;

          // ── Blendshape morphs by region ─────────────────────────
          // EYE region collapses on blink
          float isEye  = step(0.5, region) * step(region, 1.5);
          pos.y = mix(pos.y, mix(pos.y, 0.05, 0.7), isEye * uBlink);

          // BROW region lifts up on browLift / surprise
          float isBrow = step(1.5, region) * step(region, 2.5);
          pos.y += isBrow * uBrowLift * 0.06;

          // LIP region: jawOpen pulls lower lip down, smile pulls corners
          float isLip  = step(2.5, region) * step(region, 3.5);
          float jawAmt = (uJaw * 0.04 + uMouthOpen * 0.06);
          // Lower lip = lip particles with y < 0
          float lowerLip = isLip * smoothstep(0.0, -0.1, pos.y);
          pos.y -= jawAmt * lowerLip;
          // Mouth wide stretches lip particles outward
          pos.x += isLip * uMouthWide * 0.04 * sign(pos.x);
          // Smile pulls outer lip corners up
          float cornerMask = isLip * smoothstep(0.25, 0.45, abs(pos.x));
          pos.y += uSmile * 0.025 * cornerMask;

          // JAW region drops on heavy bass / open mouth
          float isJaw = step(5.5, region) * step(region, 6.5);
          pos.y -= isJaw * (uJaw * 0.05 + uMouthOpen * 0.07);

          // ── Boot scatter → converge ─────────────────────────────
          vec3 scattered = position + vec3(
            (seed - 0.5) * 6.0,
            (fract(seed * 17.3) - 0.5) * 6.0,
            (fract(seed * 31.7) - 0.5) * 2.5
          );
          float prog = smoothstep(0.0, 1.0, uBootProgress);
          pos = mix(scattered, pos, prog);

          vec4 mv = modelViewMatrix * vec4(pos, 1.0);
          gl_Position = projectionMatrix * mv;
          // Crisp tiny points: ~1px regardless of distance from camera
          gl_PointSize = (0.9 + 0.7 * uBootProgress) * (140.0 / -mv.z);

          vColor = aColor;
          vGlow = uIntensity * (0.55 + 0.45 * seed) * uBootProgress;
          vSeed = seed;
        }
      `,
      fragmentShader: `
        precision highp float;
        uniform vec3 uAccent;
        uniform float uTime;
        varying vec3  vColor;
        varying float vGlow;
        varying float vSeed;
        void main() {
          vec2 q = gl_PointCoord - 0.5;
          float d = length(q);
          if (d > 0.5) discard;
          float a = smoothstep(0.5, 0.08, d);

          // Each particle's color = cyan-shifted sample of the source
          // texture. Highlights pop white-ish, midtones cyan, shadows
          // deep blue. Keeps the photo recognizable in the cloud.
          float lum = dot(vColor, vec3(0.299, 0.587, 0.114));
          vec3 c = uAccent * (0.35 + 1.4 * lum);
          c += vec3(0.85, 1.0, 1.0) * pow(lum, 5.0) * 0.55;

          // Sub-pixel twinkle
          float twinkle = 0.75 + 0.25 * sin(uTime * 2.2 + vSeed * 21.0);
          gl_FragColor = vec4(c * (0.55 + 0.5 * vGlow), a * twinkle * 0.75);
        }
      `,
    });

    this.points = new THREE.Points(geo, mat);
    this.scene.add(this.points);
    console.log(`[face] mesh on GPU. total boot ${(performance.now()-t0)|0}ms`);
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

  setEmotion(e) {
    // e = { smile: 0..1, browLift: 0..1 }
    if (!e) return;
    if (e.smile != null)    this._vSmile = e.smile;
    if (e.browLift != null) this._vBrowLift = e.browLift;
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
      this._vSmile = 0.25; this._vBrowLift = 0.15;
    } else if (mode === 'professional') {
      this._idleIntensity = 0.52;
      this._breathRate = 0.55;
      this._vSmile = 0; this._vBrowLift = 0;
    } else {  // warm
      this._idleIntensity = 0.65;
      this._breathRate = 0.45;
      this._vSmile = 0.12; this._vBrowLift = 0.04;
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
      u.uSmile.value     = lerp(u.uSmile.value,     this._vSmile,     0.06);
      u.uBrowLift.value  = lerp(u.uBrowLift.value,  this._vBrowLift,  0.06);
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
