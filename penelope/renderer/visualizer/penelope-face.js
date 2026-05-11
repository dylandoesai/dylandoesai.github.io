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
import { FACE_LANDMARKS } from './face-landmarks.js';

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
    // FACE_LANDMARKS: array of [x,y,z] normalized to roughly [-0.5..0.5].
    // We expand each landmark into ~6-10 particles depending on its cluster.
    const positions = [];
    const seeds = [];
    const clusters = [];

    const pushParticle = (base, cluster, jitter = 0.005) => {
      const x = base[0] + (Math.random() - 0.5) * jitter;
      const y = base[1] + (Math.random() - 0.5) * jitter;
      const z = base[2] + (Math.random() - 0.5) * jitter;
      positions.push(x, y, z);
      seeds.push(Math.random() * 100);
      clusters.push(cluster);
    };

    // Cluster classification by landmark index (FaceMesh canonical):
    //   1 = skull/face shell (default)
    //   2 = jawline
    //   3 = lips/mouth
    //   4 = eyes
    //   5 = cheeks
    //   6 = brows
    const JAW_IDX = new Set([
      // chin contour 152..400 region (a few canonical jaw points)
      152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234,
      454, 323, 361, 288, 397, 365, 379, 378, 400,
    ]);
    const LIPS_IDX = new Set([
      // outer + inner lip ring
      61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291,
      78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308,
      0, 267, 269, 270, 13, 82, 37, 39, 40, 185,
    ]);
    const LEFT_EYE = new Set([33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]);
    const RIGHT_EYE = new Set([263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466]);
    const CHEEKS = new Set([50, 101, 36, 205, 187, 280, 330, 266, 425, 411]);
    const BROWS = new Set([
      70, 63, 105, 66, 107, 55, 65, 52, 53, 46,
      300, 293, 334, 296, 336, 285, 295, 282, 283, 276,
    ]);

    const clusterOf = (i) => {
      if (LIPS_IDX.has(i)) return 3;
      if (LEFT_EYE.has(i) || RIGHT_EYE.has(i)) return 4;
      if (CHEEKS.has(i)) return 5;
      if (BROWS.has(i)) return 6;
      if (JAW_IDX.has(i)) return 2;
      return 1;
    };

    const densityOf = (c) => {
      if (c === 3) return 14; // lips dense (lip sync visibility)
      if (c === 4) return 10; // eyes dense
      if (c === 2) return 8;
      if (c === 5) return 6;
      if (c === 6) return 6;
      return 4; // skull default
    };

    for (let i = 0; i < FACE_LANDMARKS.length; i++) {
      const c = clusterOf(i);
      const n = densityOf(c);
      for (let k = 0; k < n; k++) pushParticle(FACE_LANDMARKS[i], c);
    }

    // Ambient backdrop particles (per user spec: "Black + ambient particle field")
    const AMBIENT = 1800;
    for (let i = 0; i < AMBIENT; i++) {
      const r = 1.6 + Math.random() * 1.4;
      const t = Math.random() * Math.PI * 2;
      const p = (Math.random() - 0.5) * Math.PI;
      pushParticle([
        r * Math.cos(p) * Math.cos(t) * 0.7,
        r * Math.sin(p) * 0.5,
        -1.2 - Math.random() * 1.5,
      ], 7, 0.0);
    }

    const geom = new THREE.BufferGeometry();
    geom.setAttribute('aBase', new THREE.Float32BufferAttribute(positions, 3));
    geom.setAttribute('aSeed', new THREE.Float32BufferAttribute(seeds, 1));
    geom.setAttribute('aCluster', new THREE.Float32BufferAttribute(clusters, 1));
    geom.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));

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
    this._vIntensity = 0.55;
  }

  start() {
    const tick = () => {
      const dt = this.clock.getDelta();
      const t = this.clock.elapsedTime;
      const u = this.uniforms;
      u.uTime.value = t;

      // breath: slow sinusoid
      u.uBreath.value = Math.sin(t * 0.45) * 0.5 + 0.5;

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
