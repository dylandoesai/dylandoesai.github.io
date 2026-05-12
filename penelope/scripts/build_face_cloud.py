"""Generate the photo-real Penelope particle cloud.

Reads:
    assets/face-mesh.json     (478 averaged 3D landmarks from 25 photos)
    assets/face-tess.json     (468 UVs + 898 triangles, MediaPipe canonical)
    assets/penelope_base.webp (the texture for color sampling)

Output:
    assets/face-cloud.bin     (binary float/uint particle data, ~96MB)
    assets/face-cloud-meta.json (counts + region offsets)

Particle layout per record (24 bytes):
    pos       3 × float32     (12B)  — 3D position on the deformed mesh
    rgb       3 × uint8       ( 3B)  — color sampled from the texture
    region    1 × uint8       ( 1B)  — 0=skin, 1=eye, 2=brow, 3=lip,
                                       4=nose, 5=hair, 6=jaw — drives blendshapes
    tri       1 × uint16      ( 2B)  — source triangle index (debugging)
    seed      1 × float32     ( 4B)  — per-particle kinetic / twinkle seed
    bary      2 × float16     ( 4B)  — packed barycentric (a, b); c = 1-a-b

That's 26B — round up to 28B with 2 bytes padding so each record is 4-aligned.

Run:
    python scripts/build_face_cloud.py [--count 8000000]
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MESH = ROOT / "assets" / "face-mesh.json"
TESS = ROOT / "assets" / "face-tess.json"
TEX  = ROOT / "assets" / "penelope_base.webp"
OUT  = ROOT / "assets" / "face-cloud.bin"
META = ROOT / "assets" / "face-cloud-meta.json"


# MediaPipe FaceMesh canonical landmark groupings (index sets).
# Used to tag each triangle with a feature region so the renderer
# can morph regions independently for blendshapes.
# Source: mediapipe.solutions.face_mesh.FACEMESH_* constants.

EYE_IDX = set([
    # left eye
    33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246,
    # right eye
    362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398,
    # iris
    468, 469, 470, 471, 472, 473, 474, 475, 476, 477,
])
BROW_IDX = set([
    # left brow
    70, 63, 105, 66, 107, 55, 65, 52, 53, 46,
    # right brow
    300, 293, 334, 296, 336, 285, 295, 282, 283, 276,
])
LIP_IDX = set([
    # outer
    61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291,
    409, 270, 269, 267, 0, 37, 39, 40, 185,
    # inner
    78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308,
    415, 310, 311, 312, 13, 82, 81, 80, 191,
])
NOSE_IDX = set([
    1, 2, 4, 5, 6, 19, 20, 94, 125, 141, 168, 195, 197,
    240, 235, 220, 218, 219, 305, 460, 438, 440, 457, 459,
])
JAW_IDX = set([
    152, 175, 199, 200, 18, 83, 313, 18, 32, 194, 211, 32, 140, 369, 396,
    176, 148, 152, 377, 400, 378, 379, 365, 397, 288, 361, 401, 435, 367, 364,
])


def _region_of(tri_idx, vidx_a, vidx_b, vidx_c):
    """Tag a triangle by majority-region of its 3 vertices."""
    counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 6: 0}
    for vi in (vidx_a, vidx_b, vidx_c):
        if vi in EYE_IDX:  counts[1] += 1
        elif vi in BROW_IDX: counts[2] += 1
        elif vi in LIP_IDX: counts[3] += 1
        elif vi in NOSE_IDX: counts[4] += 1
        elif vi in JAW_IDX: counts[6] += 1
        else: counts[0] += 1
    # Return the dominant region (1=eye beats 0=skin if any eye vertex present)
    if counts[1] >= 1: return 1   # eye region — extreme detail
    if counts[3] >= 1: return 3   # lip
    if counts[2] >= 1: return 2   # brow
    if counts[4] >= 2: return 4   # nose (needs 2 to dominate)
    if counts[6] >= 2: return 6   # jaw
    return 0                       # skin


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=8_000_000,
                    help="Total particles to generate (default: 8M)")
    args = ap.parse_args()
    N = args.count
    print(f"target: {N:,} particles", file=sys.stderr)

    # ── load inputs ─────────────────────────────────────────────────
    verts = np.array(json.loads(MESH.read_text()), dtype=np.float32)
    print(f"loaded {len(verts)} vertices from {MESH.name}", file=sys.stderr)
    tess = json.loads(TESS.read_text())
    uvs  = np.array(tess["uvs"], dtype=np.float32)
    tris = np.array(tess["triangles"], dtype=np.int32)
    print(f"loaded {len(uvs)} UVs and {len(tris)} triangles", file=sys.stderr)

    img = Image.open(TEX).convert("RGB")
    img_arr = np.array(img, dtype=np.uint8)
    H, W = img_arr.shape[:2]
    print(f"texture: {W}×{H}", file=sys.stderr)

    # ── compute triangle properties (area, region) ──────────────────
    # Vertices in face-mesh are in MediaPipe normalized image coords:
    #   x: 0..1 left→right, y: 0..1 top→bottom (image), z: depth
    # Convert to world space: center (0,0), flip y, scale up.
    vw = verts.copy()
    vw[:, 0] = (vw[:, 0] - 0.5) * 2.0          # x: -1..1
    vw[:, 1] = -(vw[:, 1] - 0.5) * 2.5         # y: flip + slightly taller
    vw[:, 2] = -vw[:, 2] * 1.8                  # z: invert (negative=closer in MP)

    # Per-triangle: area in world space, region tag, uvs
    t_v0 = vw[tris[:, 0]]
    t_v1 = vw[tris[:, 1]]
    t_v2 = vw[tris[:, 2]]
    # Triangle area = 0.5 * |cross(v1-v0, v2-v0)|
    edge1 = t_v1 - t_v0
    edge2 = t_v2 - t_v0
    cross = np.cross(edge1, edge2)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    print(f"area range: {area.min():.5f} .. {area.max():.5f}", file=sys.stderr)

    # Region tag per triangle
    regions = np.zeros(len(tris), dtype=np.uint8)
    for i, (a, b, c) in enumerate(tris):
        regions[i] = _region_of(i, int(a), int(b), int(c))
    print("region histogram (0=skin,1=eye,2=brow,3=lip,4=nose,6=jaw):",
          dict(zip(*np.unique(regions, return_counts=True))), file=sys.stderr)

    # ── importance weighting per triangle ──────────────────────────
    # Distribution we want: most particles on the skin SURFACE so the face
    # is solid, but a strong boost on small detail-heavy regions (eyes,
    # lips, brows) so they remain crisp.
    region_boost = {
        0: 1.0,   # skin
        1: 6.0,   # eye — extreme detail
        2: 4.0,   # brow
        3: 5.0,   # lip
        4: 2.0,   # nose
        6: 1.5,   # jaw
    }
    boost = np.array([region_boost.get(int(r), 1.0) for r in regions])
    weight = area * boost
    # Normalize → cumulative for fast sampling
    weight_norm = weight / weight.sum()
    cdf = np.cumsum(weight_norm)

    # ── sample N particles ─────────────────────────────────────────
    # Pick triangles weighted by area*boost
    print("sampling triangles…", file=sys.stderr)
    rng = np.random.default_rng(42)
    rs = rng.random(N, dtype=np.float64)
    chosen_tri = np.searchsorted(cdf, rs).astype(np.int32)
    chosen_tri = np.clip(chosen_tri, 0, len(tris) - 1)

    # Random barycentric coords (uniform on triangle surface)
    print("sampling barycentric coords…", file=sys.stderr)
    r1 = rng.random(N, dtype=np.float32)
    r2 = rng.random(N, dtype=np.float32)
    swap = r1 + r2 > 1.0
    r1 = np.where(swap, 1.0 - r1, r1)
    r2 = np.where(swap, 1.0 - r2, r2)
    a = 1.0 - r1 - r2
    b = r1
    c = r2

    # Look up triangle vertices for each particle
    v0_idx = tris[chosen_tri, 0]
    v1_idx = tris[chosen_tri, 1]
    v2_idx = tris[chosen_tri, 2]
    print("computing world positions…", file=sys.stderr)
    pos = (a[:, None] * vw[v0_idx]
         + b[:, None] * vw[v1_idx]
         + c[:, None] * vw[v2_idx]).astype(np.float32)

    # Interpolated UV — for color lookup (handles iris which doesn't have
    # UV: any vertex >= 468 falls back to vertex 0 UV which is safe.)
    safe_idx0 = np.clip(v0_idx, 0, 467)
    safe_idx1 = np.clip(v1_idx, 0, 467)
    safe_idx2 = np.clip(v2_idx, 0, 467)
    print("computing UVs…", file=sys.stderr)
    uv = (a[:, None] * uvs[safe_idx0]
        + b[:, None] * uvs[safe_idx1]
        + c[:, None] * uvs[safe_idx2]).astype(np.float32)

    # Sample texture at each UV → per-particle RGB
    # MediaPipe UVs: (u, v) with v=0 at top of image. Pillow numpy array is
    # row-major (row 0 = top). So texel row = v * (H-1).
    print("sampling texture…", file=sys.stderr)
    tx = np.clip(uv[:, 0] * (W - 1), 0, W - 1).astype(np.int32)
    ty = np.clip(uv[:, 1] * (H - 1), 0, H - 1).astype(np.int32)
    rgb = img_arr[ty, tx]    # (N, 3) uint8

    # Per-particle region tag (inherits from triangle)
    region_per = regions[chosen_tri]

    # Per-particle seed for kinetic drift
    seed = rng.random(N, dtype=np.float32)

    # ── pack into binary ───────────────────────────────────────────
    # Layout (28 bytes per particle, repeated N times):
    #   float32 x, float32 y, float32 z          12 B
    #   uint8 r, uint8 g, uint8 b                 3 B
    #   uint8 region                              1 B
    #   uint16 tri (debug, also used for region)  2 B
    #   uint16 _pad                               2 B
    #   float32 seed                              4 B
    #   float16 bary_a, float16 bary_b            4 B
    # = 28 B
    print("packing binary…", file=sys.stderr)
    rec_size = 28
    buf = np.zeros(N * rec_size, dtype=np.uint8)
    # Reinterpret slices for direct writes — much faster than per-row struct.pack
    view32 = buf.view(np.float32).reshape(N, rec_size // 4)
    view32[:, 0:3] = pos                              # x,y,z @ bytes 0-11
    # RGB + region + tri at bytes 12-17 (6 bytes)
    bytes_view = buf.reshape(N, rec_size)
    bytes_view[:, 12] = rgb[:, 0]
    bytes_view[:, 13] = rgb[:, 1]
    bytes_view[:, 14] = rgb[:, 2]
    bytes_view[:, 15] = region_per
    # uint16 tri at bytes 16-17
    tri_view = buf.view(np.uint16).reshape(N, rec_size // 2)
    tri_view[:, 8] = chosen_tri.astype(np.uint16)
    # seed at bytes 20-23 (after 2-byte pad at 18-19)
    view32[:, 5] = seed
    # bary as float16 at bytes 24-27
    bary16 = np.empty((N, 2), dtype=np.float16)
    bary16[:, 0] = a.astype(np.float16)
    bary16[:, 1] = b.astype(np.float16)
    view16 = buf.view(np.uint16).reshape(N, rec_size // 2)
    view16[:, 12:14] = bary16.view(np.uint16)

    OUT.write_bytes(buf.tobytes())
    print(f"wrote {OUT.name}: {OUT.stat().st_size / 1024 / 1024:.1f} MB", file=sys.stderr)

    META.write_text(json.dumps({
        "count": int(N),
        "record_size": rec_size,
        "layout": {
            "pos":    {"offset": 0,  "type": "float32", "count": 3},
            "rgb":    {"offset": 12, "type": "uint8",   "count": 3},
            "region": {"offset": 15, "type": "uint8",   "count": 1},
            "tri":    {"offset": 16, "type": "uint16",  "count": 1},
            "seed":   {"offset": 20, "type": "float32", "count": 1},
            "bary":   {"offset": 24, "type": "float16", "count": 2},
        },
        "regions": {
            "0": "skin", "1": "eye", "2": "brow", "3": "lip",
            "4": "nose", "6": "jaw",
        },
        "mesh_bounds": {
            "x": [float(vw[:, 0].min()), float(vw[:, 0].max())],
            "y": [float(vw[:, 1].min()), float(vw[:, 1].max())],
            "z": [float(vw[:, 2].min()), float(vw[:, 2].max())],
        },
    }, indent=2))
    print(f"wrote {META.name}", file=sys.stderr)


if __name__ == "__main__":
    main()
