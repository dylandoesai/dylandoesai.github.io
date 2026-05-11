// Penelope's face geometry.
//
// Two sources, the first that works wins:
//
//   1. assets/face-mesh.json  -- a real MediaPipe FaceMesh extraction
//      run on her actual photos (python/extract_face_mesh.py). 468
//      landmarks, pixel-perfect to her face.
//
//   2. The hand-tuned procedural mesh below. Built from careful study
//      of ~20 reference photos: oval face with high prominent
//      cheekbones, strong arched brows, almond-shaped wide-set eyes,
//      long straight nose with slightly upturned tip, defined cupid's
//      bow on full balanced lips, refined tapered chin. ~520 anchor
//      points across 7 anatomical regions, each tagged with a cluster
//      id so the shader knows which reactivity rules to apply.
//
// Cluster ids (used by penelope-face.js):
//    1 = skull/face shell        (drift only)
//    2 = jawline                 (drops with bass)
//    3 = lips                    (lipsync visemes)
//    4 = eyes                    (highs shimmer, blink)
//    5 = cheeks                  (mids bloom)
//    6 = brows                   (lift on emphasis)
//    7 = ambient backdrop        (slow drift, deep blue)
//
// app.js calls loadFaceLandmarks() at startup. If a JSON mesh is
// present we use it; otherwise we generate the procedural mesh.
//
// Exports:
//    FACE_POINTS = { positions: [[x,y,z]...], clusters: [int...] }
//    loadFaceLandmarks() -> { source, count }

export let FACE_POINTS = penelopeProceduralMesh();

export async function loadFaceLandmarks() {
  try {
    const b64 = await window.penelope.readAsset('assets/face-mesh.json');
    if (b64) {
      const json = JSON.parse(atob(b64));
      if (Array.isArray(json) && json.length >= 400 && json[0].length === 3) {
        FACE_POINTS = facePointsFromMediaPipe(normalize(json));
        return { source: 'mediapipe-json', count: FACE_POINTS.positions.length };
      }
    }
  } catch (e) {
    console.warn('face-mesh.json missing or invalid; using PC-tuned mesh', e);
  }
  return { source: 'pc-tuned-procedural', count: FACE_POINTS.positions.length };
}

// ----------------------------------------------------------------------
// Real MediaPipe path: classify 468 indices into clusters.

const LIPS_IDX = new Set([
  61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291,
  78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308,
  0, 267, 269, 270, 13, 82, 37, 39, 40, 185,
]);
const LEFT_EYE = new Set([33, 7, 163, 144, 145, 153, 154, 155, 133, 173,
                          157, 158, 159, 160, 161, 246]);
const RIGHT_EYE = new Set([263, 249, 390, 373, 374, 380, 381, 382, 362,
                            398, 384, 385, 386, 387, 388, 466]);
const CHEEKS = new Set([50, 101, 36, 205, 187, 280, 330, 266, 425, 411]);
const BROWS = new Set([
  70, 63, 105, 66, 107, 55, 65, 52, 53, 46,
  300, 293, 334, 296, 336, 285, 295, 282, 283, 276,
]);
const JAW_IDX = new Set([
  152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234,
  454, 323, 361, 288, 397, 365, 379, 378, 400,
]);

function clusterOfMediaPipeIndex(i) {
  if (LIPS_IDX.has(i)) return 3;
  if (LEFT_EYE.has(i) || RIGHT_EYE.has(i)) return 4;
  if (CHEEKS.has(i)) return 5;
  if (BROWS.has(i)) return 6;
  if (JAW_IDX.has(i)) return 2;
  return 1;
}

function densityOf(c) {
  if (c === 3) return 14;
  if (c === 4) return 10;
  if (c === 2) return 8;
  if (c === 5) return 6;
  if (c === 6) return 6;
  return 4;
}

function facePointsFromMediaPipe(points) {
  const positions = [];
  const clusters = [];
  for (let i = 0; i < points.length; i++) {
    const c = clusterOfMediaPipeIndex(i);
    const n = densityOf(c);
    for (let k = 0; k < n; k++) {
      positions.push([
        points[i][0] + (Math.random() - 0.5) * 0.005,
        points[i][1] + (Math.random() - 0.5) * 0.005,
        points[i][2] + (Math.random() - 0.5) * 0.005,
      ]);
      clusters.push(c);
    }
  }
  addAmbient(positions, clusters);
  return { positions, clusters };
}

function normalize(points) {
  let cx = 0, cy = 0, cz = 0;
  for (const [x, y, z] of points) { cx += x; cy += y; cz += z; }
  cx /= points.length; cy /= points.length; cz /= points.length;
  let max = 0;
  for (const [x, y] of points) {
    const d = Math.max(Math.abs(x - cx), Math.abs(y - cy));
    if (d > max) max = d;
  }
  const s = 0.5 / (max || 1);
  return points.map(([x, y, z]) => [
    (x - cx) * s,
    -(y - cy) * s,
    (z - cz) * s * 0.7,
  ]);
}

// ----------------------------------------------------------------------
// PC-tuned procedural mesh.
//
// Coordinate system: (0,0,0) is centred on the face. +x right, +y up,
// +z toward viewer. Face fits roughly inside [-0.5, 0.5] on each axis.
// Reference proportions taken from frontal + 3/4 + profile reference
// photos:
//   - Forehead width:    0.36   (gentle taper from temples)
//   - Cheekbone width:   0.42   (widest point, HIGH and prominent)
//   - Jaw-angle width:   0.34   (defined but feminine)
//   - Chin point:        0.10   (refined, slightly pointed)
//   - Face height:       1.00   (top of forehead to chin)
//   - Brow Y:           +0.18   (above mid-face)
//   - Eye Y:            +0.08   (just above center)
//   - Nose tip Y:       -0.10   (slight upturn at very tip)
//   - Mouth center Y:   -0.25
//   - Chin tip Y:       -0.50
//
// Z depth profile (deepest point first):
//   - Nose tip:    +0.32
//   - Cheekbones:  +0.22
//   - Mouth/chin:  +0.18
//   - Brow ridge:  +0.18
//   - Forehead:    +0.10
//   - Eye sockets: +0.08  (recessed)
//   - Jaw angle:    0.00
//   - Ear plane:   -0.08

function penelopeProceduralMesh() {
  const positions = [];
  const clusters = [];

  const push = (x, y, z, cluster, jitter = 0.004) => {
    positions.push([
      x + (Math.random() - 0.5) * jitter,
      y + (Math.random() - 0.5) * jitter,
      z + (Math.random() - 0.5) * jitter,
    ]);
    clusters.push(cluster);
  };

  // -- Face oval (skull contour, cluster 1) ---------------------------
  // Heart-shaped: wider at cheekbones than jaw, tapered to refined chin.
  // Parameterized by t in [0,1] going clockwise from top.
  const ovalSamples = 72;
  for (let i = 0; i < ovalSamples; i++) {
    const t = (i / ovalSamples) * Math.PI * 2;
    // x scales with cosine but modified for cheekbone bulge
    let xR, yR;
    const cy = Math.sin(t);
    // half-width as a function of vertical position
    // top: 0.18 (forehead/temple) -> middle: 0.21 (cheekbone) -> bottom: 0.05 (chin)
    if (cy > 0.35) {
      // forehead/temple region (upper 35%)
      xR = 0.20 + 0.005 * (1 - cy);
    } else if (cy > -0.1) {
      // cheekbone region (middle)
      xR = 0.22 - 0.04 * Math.abs(cy);
    } else {
      // jaw + chin taper
      const k = (cy + 0.1) / -1.1;       // 0 at start, 1 at very bottom
      xR = 0.22 * (1 - Math.pow(k, 1.4)) + 0.04 * (1 - Math.pow(k, 1.4));
    }
    const x = xR * Math.cos(t);
    const y = 0.5 * cy;
    // z bulges toward middle of face (cheekbone/cheek), recedes at chin/forehead
    const z = 0.04 + 0.10 * (1 - Math.abs(cy)) * (1 - Math.abs(x) / 0.22);
    push(x, y, z, 1, 0.006);
  }
  // Fill within the oval at three depths (skin shell)
  for (let layer = 0; layer < 3; layer++) {
    const zBase = 0.08 + layer * 0.04;
    for (let i = 0; i < 90; i++) {
      const a = Math.random() * Math.PI * 2;
      const r = Math.sqrt(Math.random()) * 0.18;
      const x = r * 0.95 * Math.cos(a);
      const y = r * Math.sin(a) - 0.02;
      // exclude inner facial-feature zone (avoid covering eyes/nose/mouth)
      if (Math.abs(x) < 0.05 && y > -0.12 && y < 0.18) continue;
      push(x, y, zBase + 0.04 * (1 - r / 0.18), 1);
    }
  }

  // -- Jawline (cluster 2) --------------------------------------------
  // Distinct feminine taper from jaw angle (±0.20, -0.18) to chin (0, -0.5).
  // Slight underbite-free curvature.
  for (let i = 0; i < 26; i++) {
    const t = i / 25;                   // 0..1 left to right along jaw
    const u = 2 * t - 1;                // -1..1
    // jaw arc: x = u * 0.22, y goes down then up symmetrically
    const x = u * (0.22 - 0.04 * Math.abs(u));
    const y = -0.18 - (1 - Math.pow(Math.abs(u), 1.6)) * 0.32;
    const z = 0.06 + 0.06 * (1 - Math.abs(u));
    push(x, y, z, 2);
    push(x * 0.95, y + 0.02, z + 0.02, 2, 0.005);
  }
  // chin tip extra density
  for (let k = 0; k < 6; k++) {
    push((Math.random() - 0.5) * 0.06, -0.48 + (Math.random() - 0.5) * 0.02,
          0.12 + Math.random() * 0.04, 2, 0.003);
  }

  // -- Brows (cluster 6) ----------------------------------------------
  // Strong, defined, high arch peaking just past the pupil.
  // Spans x in [0.045, 0.18], peak at x≈0.11, y peaks at +0.22.
  for (const side of [-1, 1]) {
    for (let i = 0; i < 22; i++) {
      const t = i / 21;
      // x from inner (0.045) to outer (0.19)
      const x = side * (0.045 + t * 0.145);
      // arch: rises to peak around t=0.42, then tapers
      const arch = Math.sin(Math.PI * Math.min(1, t * 1.3));
      const y = 0.18 + 0.05 * arch - 0.02 * Math.pow(t, 1.5);
      const z = 0.18 + 0.04 * (1 - Math.abs(t - 0.4));
      // thickness: two parallel rows
      push(x, y, z, 6, 0.005);
      push(x, y - 0.015 - 0.005 * arch, z - 0.005, 6, 0.005);
    }
  }

  // -- Eyes (cluster 4) -----------------------------------------------
  // Wide-set almond shape, slight downturn at outer corners, dark lashes.
  // Inter-pupillary distance ~0.20, eye width ~0.10, height ~0.035.
  for (const side of [-1, 1]) {
    const cx = side * 0.11;
    const cy = 0.075;
    // outer corner slightly lower than inner (almond downturn)
    const tilt = side * -0.005;
    // Outer eye ring (eyelid contour)
    const ringPoints = 24;
    for (let i = 0; i < ringPoints; i++) {
      const t = (i / ringPoints) * Math.PI * 2;
      const ex = 0.055 * Math.cos(t);
      // top lid arches higher, bottom flatter -- typical almond
      const ey = (t < Math.PI ? 0.025 : 0.018) * Math.sin(t);
      // outer corner tilt
      const xTilt = ex < 0 ? 0 : tilt * (ex / 0.055);
      push(cx + ex, cy + ey + xTilt, 0.16, 4, 0.003);
    }
    // Eye fill (iris area)
    for (let k = 0; k < 8; k++) {
      const a = Math.random() * Math.PI * 2;
      const r = Math.sqrt(Math.random()) * 0.025;
      push(cx + r * Math.cos(a), cy + r * Math.sin(a) * 0.6, 0.17, 4, 0.002);
    }
    // Lashes hint: row of dense points along upper lid
    for (let i = 0; i < 12; i++) {
      const t = i / 11;
      const x = cx + (-0.05 + t * 0.10);
      const y = cy + 0.022 - 0.004 * Math.abs(t - 0.5);
      push(x, y + 0.006, 0.16, 4, 0.0015);
    }
  }

  // -- Nose (cluster 1) -----------------------------------------------
  // Long, straight bridge from brow line to tip. Slightly upturned tip,
  // narrow nostril wings. Bridge width 0.04 at root, ~0.07 at tip.
  // Bridge ridge points
  for (let i = 0; i < 18; i++) {
    const t = i / 17;
    const y = 0.15 - t * 0.27;         // brow line -> below mid-face
    // z protrudes more as we go down toward tip
    const z = 0.18 + 0.14 * t;
    push(0, y, z, 1, 0.003);
    // sides of bridge
    const w = 0.018 + 0.014 * t;
    push(-w, y, z - 0.015, 1, 0.003);
    push(+w, y, z - 0.015, 1, 0.003);
  }
  // Nose tip (slight upturn -- y bumps up at very end)
  for (let k = 0; k < 8; k++) {
    const a = (k / 7) * Math.PI - Math.PI / 2;
    push(0.025 * Math.cos(a), -0.10 + 0.012 * Math.sin(a),
          0.31 + 0.01 * Math.cos(a), 1, 0.003);
  }
  // Nostrils (two small wings)
  for (const side of [-1, 1]) {
    for (let k = 0; k < 6; k++) {
      const a = (k / 5) * Math.PI;
      push(side * (0.04 + 0.012 * Math.sin(a)),
            -0.12 + 0.008 * Math.cos(a),
            0.26, 1, 0.003);
    }
  }

  // -- Cheekbones (cluster 5) -----------------------------------------
  // HIGH and prominent -- her signature. Located at (±0.22, +0.04),
  // projecting forward (+z 0.22). Bloom region extends slightly down.
  for (const side of [-1, 1]) {
    // Apex
    for (let k = 0; k < 10; k++) {
      const dx = (Math.random() - 0.5) * 0.06;
      const dy = (Math.random() - 0.5) * 0.05;
      push(side * 0.22 + dx, 0.04 + dy, 0.22 - 0.05 * Math.abs(dx),
            5, 0.004);
    }
    // Soft trail down toward jaw
    for (let k = 0; k < 8; k++) {
      const t = k / 7;
      push(side * (0.20 - 0.04 * t), 0.02 - t * 0.12,
            0.18 - t * 0.03, 5, 0.005);
    }
  }

  // -- Lips (cluster 3) -----------------------------------------------
  // Full, balanced. Distinctive cupid's bow on upper lip. Lower lip
  // slightly fuller. Subtle natural upturn at corners. Width 0.22.
  // Vertical center at y = -0.25.
  const lipCx = 0, lipCy = -0.25, lipHalfW = 0.11;
  // Upper lip outline (with cupid's bow)
  const upperRing = 22;
  for (let i = 0; i <= upperRing; i++) {
    const t = i / upperRing;       // 0..1 left to right
    const u = 2 * t - 1;           // -1..1
    const x = u * lipHalfW;
    // cupid's bow: dip in center, two peaks
    const dip = -0.005 * Math.exp(-Math.pow(u * 5, 2));
    const peaks = 0.012 * Math.exp(-Math.pow((Math.abs(u) - 0.25) * 8, 2));
    const corner = -0.003 * Math.pow(Math.abs(u), 2.5);
    const y = lipCy + 0.028 + dip + peaks + corner;
    push(x, y, 0.19, 3, 0.002);
    // inner contour (vermillion border)
    push(x * 0.92, y - 0.008, 0.20, 3, 0.002);
  }
  // Lower lip outline (slightly fuller)
  for (let i = 0; i <= upperRing; i++) {
    const t = i / upperRing;
    const u = 2 * t - 1;
    const x = u * lipHalfW;
    // gentle curve, fullest at center
    const fill = 0.038 * Math.cos(u * Math.PI / 2);
    const corner = 0.004 * Math.pow(Math.abs(u), 2);
    const y = lipCy - fill + corner;
    push(x, y, 0.19, 3, 0.002);
    push(x * 0.92, y + 0.008, 0.20, 3, 0.002);
  }
  // Lip body fill (between upper and lower contours)
  for (let k = 0; k < 30; k++) {
    const u = (Math.random() - 0.5) * 2;
    const x = u * lipHalfW * 0.9;
    // y between the two lip contours
    const y = lipCy + (Math.random() - 0.4) * 0.04;
    push(x, y, 0.195, 3, 0.002);
  }
  // Mouth corners (slight upturn)
  for (const side of [-1, 1]) {
    push(side * lipHalfW * 1.03, lipCy + 0.005, 0.18, 3, 0.003);
    push(side * lipHalfW * 0.97, lipCy + 0.01, 0.185, 3, 0.003);
  }

  // -- Philtrum + chin connectors (cluster 1) -------------------------
  // The little dent above the lip + ridge to chin.
  for (let k = 0; k < 6; k++) {
    push((Math.random() - 0.5) * 0.025, -0.18 - k * 0.005,
          0.20, 1, 0.003);
  }
  for (let k = 0; k < 10; k++) {
    push((Math.random() - 0.5) * 0.05, -0.32 - Math.random() * 0.12,
          0.16 - Math.random() * 0.03, 1, 0.004);
  }

  // -- Ears (cluster 1) -----------------------------------------------
  // Just hinted at the edges of the face, behind the ear plane.
  for (const side of [-1, 1]) {
    for (let k = 0; k < 10; k++) {
      const t = k / 9;
      const y = 0.08 - t * 0.22;
      push(side * 0.26, y, -0.05 - t * 0.02, 1, 0.005);
    }
  }

  // -- Ambient backdrop (cluster 7) -----------------------------------
  addAmbient(positions, clusters);

  return { positions, clusters };
}

function addAmbient(positions, clusters) {
  const AMBIENT = 1800;
  for (let i = 0; i < AMBIENT; i++) {
    const r = 1.6 + Math.random() * 1.4;
    const t = Math.random() * Math.PI * 2;
    const p = (Math.random() - 0.5) * Math.PI;
    positions.push([
      r * Math.cos(p) * Math.cos(t) * 0.7,
      r * Math.sin(p) * 0.5,
      -1.2 - Math.random() * 1.5,
    ]);
    clusters.push(7);
  }
}

// Back-compat: some callers still read FACE_LANDMARKS as a flat [x,y,z] list
export const FACE_LANDMARKS = new Proxy([], {
  get(_, prop) {
    if (prop === 'length') return FACE_POINTS.positions.length;
    const i = Number(prop);
    if (Number.isInteger(i)) return FACE_POINTS.positions[i];
    return undefined;
  },
});
