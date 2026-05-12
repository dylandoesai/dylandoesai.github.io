// Penelope's face: a stylized cyber rendering built from particles.
//
// Geometry strategy: we use MediaPipe FaceMesh's 468-point canonical face
// template (industry-standard, deterministic). Each landmark becomes the
// anchor for a tight cluster of particles. Additional ambient particles
// drift in a 3D field behind the face for depth.
//
// Reactivity (subtle, per user spec):
//   - bass (50-250 Hz)  -> jaw drop + mouth width
//   - mids (250-2k Hz)  -> cheek bloom
//   - highs (2k-8k Hz)  -> eye shimmer
//   - phoneme hint      -> viseme mouth shape (handed in from python)
//   - amplitude         -> overall glow intensity
//   - breath idle       -> slow z-axis sway, blink every 4-7s
//
// Implementation: a single THREE.Points with a custom shader. Per-particle
// attributes hold (a) base position on face, (b) wobble seed, (c) cluster
// id (0=skull, 1=jaw, 2=mouth, 3=eyes, 4=cheeks, 5=brows, 6=ambient).
// The shader displaces particles based on uniforms set from the JS layer.

import * as THREE from 'three';
import { FACE_POINTS } from './face-landmarks.js';

const VERT = /* glsl */ `
  attribute float aSeed;
  attribute float aCluster;
  attribute vec3 aBase;

  uniform float uTime;
  uniform float uBreath;
  uniform float uBlink;
  uniform float uJaw;       // 0..1, bass
  uniform float uMouthOpen; // 0..1, viseme amplitude
  uniform float uMouthWide; // -1..1, viseme shape (e.g. EE wide vs OO round)
  uniform float uCheek;     // 0..1, mids
  uniform float uEye;       // 0..1, highs
  uniform float uIntensity; // 0..1, overall energy
  uniform float uBootProgress; // 0..1, assembly animation

  varying float vCluster;
  varying float vGlow;

  vec3 hash3(float n) {
    return fract(sin(vec3(n, n+1.1, n+2.3)) * 43758.5453);
  }

  void main() {
    vec3 pos = aBase;
    vec3 seedV = hash3(aSeed * 9.17);

    // ambient drift on all particles
    float t = uTime * 0.6;
    pos += 0.0035 * vec3(
      sin(t + seedV.x * 6.28),
      cos(t * 1.3 + seedV.y * 6.28),
      sin(t * 0.7 + seedV.z * 6.28)
    );

    // breath: gentle z sway + scale
    pos *= (1.0 + 0.012 * uBreath);

    // cluster-specific reactivity (subtle)
    if (aCluster < 1.5) {
      // skull/general
    } else if (aCluster < 2.5) {
      // jaw: drop on bass
      pos.y -= uJaw * 0.06 * smoothstep(0.0, 1.0, -aBase.y + 0.1);
    } else if (aCluster < 3.5) {
      // mouth: open + wide/round
      float openMask = smoothstep(0.0, 0.05, 0.05 - abs(aBase.y + 0.18));
      pos.y -= uMouthOpen * 0.025 * openMask * sign(aBase.y + 0.18);
      pos.x *= 1.0 + uMouthWide * 0.04 * openMask;
    } else if (aCluster < 4.5) {
      // eyes: shimmer + blink
      float blink = 1.0 - uBlink * smoothstep(0.0, 1.0, 1.0);
      pos.y = mix(aBase.y, aBase.y * 0.85 + (aBase.y > 0.0 ? -0.005 : 0.005), uBlink);
      pos += 0.002 * uEye * (seedV - 0.5);
    } else if (aCluster < 5.5) {
      // cheeks: subtle bloom on mids
      pos += aBase * 0.01 * uCheek;
    } else if (aCluster < 6.5) {
      // brows: lift on emphasis
      pos.y += uEye * 0.01;
    }

    // boot assembly: lerp from a random scattered position into final
    vec3 scattered = aBase + (seedV - 0.5) * 2.4;
    pos = mix(scattered, pos, smoothstep(0.0, 1.0, uBootProgress));

    vec4 mv = modelViewMatrix * vec4(pos, 1.0);
    gl_Position = projectionMatrix * mv;

    float size = mix(1.5, 2.4, seedV.x);
    if (aCluster > 6.5) size *= 0.5; // ambient
    if (aCluster > 1.5 && aCluster < 4.5) size *= 1.15; // feature accents
    gl_PointSize = size * (300.0 / -mv.z) * (0.7 + 0.6 * uBootProgress);

    vCluster = aCluster;
    vGlow = uIntensity * (0.6 + 0.4 * seedV.y);
  }
`;

const FRAG = /* glsl */ `
  precision highp float;
  varying float vCluster;
  varying float vGlow;
  uniform float uTime;

  void main() {
    vec2 uv = gl_PointCoord - 0.5;
    float d = length(uv);
    if (d > 0.5) discard;
    float a = smoothstep(0.5, 0.0, d);
    a *= a;

    // base cyan
    vec3 col = vec3(0.0, 0.9, 1.0);
    // feature accents lean slightly white-hot
    if (vCluster > 1.5 && vCluster < 6.5) col = mix(col, vec3(0.7, 1.0, 1.0), 0.25);
    // ambient particles deeper blue
    if (vCluster > 6.5) col = vec3(0.0, 0.5, 1.0);

    col *= (0.6 + 0.8 * vGlow);
    gl_FragColor = vec4(col, a * 0.95);
  }
`;

export class PenelopeFace {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({
      canvas, antialias: false, alpha: true,
      powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setClearColor(0x000000, 0);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, 1, 0.01, 100);
    this.camera.position.set(0, 0, 2.4);
    this.scene.add(this.camera);

    this.clock = new THREE.Clock();
    this.lowPower = false;

    this.uniforms = {
      uTime: { value: 0 },
      uBreath: { value: 0 },
      uBlink: { value: 0 },
      uJaw: { value: 0 },
      uMouthOpen: { value: 0 },
      uMouthWide: { value: 0 },
      uCheek: { value: 0 },
      uEye: { value: 0 },
      uIntensity: { value: 0.6 },
      uBootProgress: { value: 0 },
    };

    this._buildGeometry();
    this._handleResize();
    window.addEventListener('resize', () => this._handleResize());

    // blink scheduler
    this._scheduleBlink();

    // boot starts at 0 (scattered). Call boot() to assemble.
    this._bootTarget = 0;

    // viseme targets (smoothed)
    this._vJaw = 0;
    this._vMouthOpen = 0;
    this._vMouthWide = 0;
    this._vCheek = 0;
    this._vEye = 0;
    this._vIntensity = 0.6;
  }

  _buildGeometry() {
    // FACE_POINTS = { positions: [[x,y,z], ...], clusters: [int, ...] }
    // Already pre-classified per-point by face-landmarks.js (either from a
    // real MediaPipe extraction of her photos, or the PC-tuned procedural
    // mesh). Each anchor point becomes one shader particle.
    const src = FACE_POINTS;
    const n = src.positions.length;
    const positions = new Float32Array(n * 3);
    const seeds = new Float32Array(n);
    const clusters = new Float32Array(n);

    for (let i = 0; i < n; i++) {
      const p = src.positions[i];
      positions[i * 3 + 0] = p[0];
      positions[i * 3 + 1] = p[1];
      positions[i * 3 + 2] = p[2];
      seeds[i] = Math.random() * 100;
      clusters[i] = src.clusters[i];
    }

    const geom = new THREE.BufferGeometry();
    geom.setAttribute('aBase', new THREE.BufferAttribute(positions, 3));
    geom.setAttribute('aSeed', new THREE.BufferAttribute(seeds, 1));
    geom.setAttribute('aCluster', new THREE.BufferAttribute(clusters, 1));
    geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));

    const mat = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      uniforms: this.uniforms,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    this.points = new THREE.Points(geom, mat);
    this.scene.add(this.points);
  }

  rebuild() {
    // Called when face-landmarks.js loads a different mesh (e.g. real
    // MediaPipe JSON arrives after init). Drops the old geometry and
    // rebuilds from the current FACE_POINTS.
    if (this.points) {
      this.scene.remove(this.points);
      this.points.geometry.dispose();
      this.points.material.dispose();
      this.points = null;
    }
    this._buildGeometry();
  }

  _handleResize() {
    const w = window.innerWidth, h = window.innerHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  _scheduleBlink() {
    const wait = 4000 + Math.random() * 3000;
    setTimeout(() => {
      this._blinkT = 0;
      this._blinking = true;
      this._scheduleBlink();
    }, wait);
  }

  setLowPower(on) {
    this.lowPower = on;
    this.renderer.setPixelRatio(on ? 1 : Math.min(window.devicePixelRatio || 1, 2));
  }

  // Subtle visual differentiation per personality mode. Keep cyan #00E5FF
  // as the canonical accent (locked in spec), but shift baseline intensity
  // + breath cadence + ambient drift so the face FEELS different in each.
  setMode(mode) {
    this._mode = mode || 'warm';
    if (mode === 'flirty') {
      this._idleIntensity = 0.72;
      this._breathRate = 0.32;     // slower, deeper
      this._ambientDrift = 1.4;
    } else if (mode === 'professional') {
      this._idleIntensity = 0.48;
      this._breathRate = 0.55;     // steadier
      this._ambientDrift = 0.7;    // less drift, crisper
    } else { // warm (default)
      this._idleIntensity = 0.6;
      this._breathRate = 0.45;
      this._ambientDrift = 1.0;
    }
  }

  // Begin the 12-second cinematic assembly.
  // Returns a Promise that resolves when done.
  bootAssemble(durationMs = 12000) {
    return new Promise((resolve) => {
      this._bootStart = performance.now();
      this._bootDuration = durationMs;
      this._bootResolve = resolve;
    });
  }

  setReactivity(bands) {
    // bands = { bass, mid, high, amp }, all 0..1
    if (!bands) return;
    this._vJaw = bands.bass;
    this._vCheek = bands.mid;
    this._vEye = bands.high;
    this._vIntensity = 0.5 + bands.amp * 0.5;
  }

  setViseme(viseme) {
    // viseme: { open: 0..1, wide: -1..1 }
    if (!viseme) return;
    this._vMouthOpen = viseme.open;
    this._vMouthWide = viseme.wide;
  }

  setIdle() {
    this._vJaw = 0; this._vCheek = 0; this._vEye = 0;
    this._vMouthOpen = 0; this._vMouthWide = 0;
    this._vIntensity = this._idleIntensity != null ? this._idleIntensity : 0.55;
  }

  // Brief blue-particle pulse — used when Dylan clicks an interactive
  // panel surface. Returns immediately; the face brightens for ~600ms
  // and the eye + cheek shimmer briefly to acknowledge the click.
  pulse(strength = 0.35, durationMs = 600) {
    const prevI = this._vIntensity;
    const prevE = this._vEye;
    const prevC = this._vCheek;
    this._vIntensity = Math.min(1, (prevI || 0.6) + strength);
    this._vEye = Math.min(1, (prevE || 0) + strength * 0.7);
    this._vCheek = Math.min(1, (prevC || 0) + strength * 0.4);
    setTimeout(() => {
      this._vIntensity = prevI;
      this._vEye = prevE;
      this._vCheek = prevC;
    }, durationMs);
  }

  start() {
    const tick = () => {
      const dt = this.clock.getDelta();
      const t = this.clock.elapsedTime;
      const u = this.uniforms;
      u.uTime.value = t;

      // breath: slow sinusoid, rate per mode (flirty slow/deep, pro steady)
      const breathRate = this._breathRate != null ? this._breathRate : 0.45;
      u.uBreath.value = Math.sin(t * breathRate) * 0.5 + 0.5;

      // blink: short triangle pulse over ~150ms
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

      // smooth toward targets
      const lerp = (a, b, k) => a + (b - a) * k;
      u.uJaw.value = lerp(u.uJaw.value, this._vJaw, 0.25);
      u.uMouthOpen.value = lerp(u.uMouthOpen.value, this._vMouthOpen, 0.35);
      u.uMouthWide.value = lerp(u.uMouthWide.value, this._vMouthWide, 0.25);
      u.uCheek.value = lerp(u.uCheek.value, this._vCheek, 0.18);
      u.uEye.value = lerp(u.uEye.value, this._vEye, 0.22);
      u.uIntensity.value = lerp(u.uIntensity.value, this._vIntensity, 0.1);

      // boot animation
      if (this._bootStart) {
        const elapsed = performance.now() - this._bootStart;
        const p = Math.min(1, elapsed / this._bootDuration);
        // eased cubic
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
