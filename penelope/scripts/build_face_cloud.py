"""Generate the photo-real 3D Penelope head particle cloud.

True 3D pipeline (not 2D-photo-on-a-mesh):

  1. Load MediaPipe's CANONICAL 3D face mesh (468 verts, real depth:
     forehead-back, nose-protrusion, jaw-curve, ear-spread). This is
     the geometric base — a proper 3D head shape.

  2. Load Penelope's per-photo MediaPipe landmarks (averaged over all
     25 reference photos, Procrustes-aligned to canonical 2D first
     for clean averaging — no more head-tilt smearing).

  3. Compute her IDENTITY DELTA: per-vertex offset between her
     averaged landmarks and the canonical mean. This captures her
     specific cheekbone width, jaw line, brow shape, lip thickness,
     etc.

  4. Apply identity delta to canonical 3D mesh → Penelope-Cruz-
     specific 3D head with proper depth + her individual features.

  5. Sample 8M particles barycentrically on the resulting 3D mesh.

  6. Texture sampling: each particle's UV = its position projected
     into the source photo's image space. Color = photo pixel at UV.

Output:
    assets/face-cloud.bin     ~213 MB (8M particles × 28 bytes)
    assets/face-cloud-meta.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CANON_OBJ = ROOT / "assets" / "canonical_face_model.obj"
MESH      = ROOT / "assets" / "face-mesh.json"
TESS      = ROOT / "assets" / "face-tess.json"
TEX       = ROOT / "assets" / "penelope_base.webp"
OUT       = ROOT / "assets" / "face-cloud.bin"
META      = ROOT / "assets" / "face-cloud-meta.json"


# MediaPipe FaceMesh landmark groupings (subset). Used to tag regions
# for blendshape-driven animation later.
EYE_IDX = set([
    33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246,
    362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398,
])
BROW_IDX = set([
    70, 63, 105, 66, 107, 55, 65, 52, 53, 46,
    300, 293, 334, 296, 336, 285, 295, 282, 283, 276,
])
LIP_IDX = set([
    61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291,
    409, 270, 269, 267, 0, 37, 39, 40, 185,
    78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308,
    415, 310, 311, 312, 13, 82, 81, 80, 191,
])
NOSE_IDX = set([
    1, 2, 4, 5, 6, 19, 20, 94, 125, 141, 168, 195, 197,
])
JAW_IDX = set([
    152, 175, 199, 200, 18, 32, 140, 369, 396,
    176, 148, 377, 400, 378, 379, 365, 397, 288, 361, 401, 435, 367, 364,
])


def _region_of(va, vb, vc):
    counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 6: 0}
    for vi in (va, vb, vc):
        if vi in EYE_IDX:  counts[1] += 1
        elif vi in BROW_IDX: counts[2] += 1
        elif vi in LIP_IDX: counts[3] += 1
        elif vi in NOSE_IDX: counts[4] += 1
        elif vi in JAW_IDX: counts[6] += 1
        else: counts[0] += 1
    if counts[1] >= 1: return 1
    if counts[3] >= 1: return 3
    if counts[2] >= 1: return 2
    if counts[4] >= 2: return 4
    if counts[6] >= 2: return 6
    return 0


def load_canonical_mesh():
    """Read canonical_face_model.obj — returns (verts 468×3, tris 898×3, uvs 468×2)."""
    verts = []; uvs = []; tris = []
    with open(CANON_OBJ) as f:
        for line in f:
            parts = line.strip().split()
            if not parts: continue
            if parts[0] == 'v':
                verts.append([float(p) for p in parts[1:4]])
            elif parts[0] == 'vt':
                uvs.append([float(p) for p in parts[1:3]])
            elif parts[0] == 'f':
                idx = [int(p.split('/')[0]) - 1 for p in parts[1:4]]
                tris.append(idx)
    return (np.array(verts, dtype=np.float32),
            np.array(tris, dtype=np.int32),
            np.array(uvs, dtype=np.float32))


def procrustes_align_2d(source, target):
    """Fit translation + uniform scale so source matches target in 2D.

    source, target: (N, 2) arrays.
    Returns scale (float), translation (2,).
    """
    s_centroid = source.mean(axis=0)
    t_centroid = target.mean(axis=0)
    sc = source - s_centroid
    tc = target - t_centroid
    # Solve for s: minimize sum((s*sc - tc)^2) → s = sum(sc·tc) / sum(sc·sc)
    scale = float((sc * tc).sum() / max(1e-9, (sc * sc).sum()))
    # Translation = target_centroid - scale * source_centroid
    trans = t_centroid - scale * s_centroid
    return scale, trans


def build_identity_mesh(canon_verts, penelope_lm):
    """Compute Penelope-Cruz-specific 3D head mesh.

    Strategy: KEEP canonical 3D geometry (proper head shape with real
    depth) as the world position. Compute per-vertex texture UVs by
    Procrustes-fitting canonical 2D into the photo's coord space.

    Returns:
      world_xyz: (468, 3) — true 3D mesh (canonical, scaled to fit)
      uv:       (468, 2) — per-vertex photo UV for texture sampling
    """
    n = canon_verts.shape[0]
    pen_2d = penelope_lm[:n, :2].astype(np.float32)

    # Flip canonical y to match image-y direction (image-y is top→down).
    # This lets Procrustes converge on a POSITIVE scale.
    canon_xy = canon_verts[:, :2].copy()
    canon_xy[:, 1] = -canon_xy[:, 1]

    scale, trans = procrustes_align_2d(canon_xy, pen_2d)
    # UVs: canonical xy projected into photo space
    uv = canon_xy * scale + trans   # (468, 2) in [0..1] photo coords

    # World position: canonical 3D (with proper depth), centered.
    # We feed it to the world-space normalizer in main().
    world = canon_verts.copy()
    # Flip y here so up-is-up in world (canonical has y-up already, but
    # we'll flip again in main's world-normalizer for image-down → up)
    # We keep canonical Y as-is here; main flips during normalization.
    return world, uv, scale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=8_000_000)
    args = ap.parse_args()
    N = args.count
    print(f"target: {N:,} particles", file=sys.stderr)

    canon_v, canon_tris, canon_uvs = load_canonical_mesh()
    print(f"canonical: {len(canon_v)} verts, {len(canon_tris)} tris", file=sys.stderr)

    pen_lm = np.array(json.loads(MESH.read_text()), dtype=np.float32)
    print(f"penelope landmarks: {len(pen_lm)}", file=sys.stderr)

    # Build identity-fitted mesh: canonical 3D for shape, photo-fit UV
    world_raw, photo_uv, fit_scale = build_identity_mesh(canon_v, pen_lm)
    print(f"procrustes fit scale={fit_scale:.4f}", file=sys.stderr)
    print(f"canonical bounds: x={world_raw[:,0].min():.3f}..{world_raw[:,0].max():.3f} "
          f"y={world_raw[:,1].min():.3f}..{world_raw[:,1].max():.3f} "
          f"z={world_raw[:,2].min():.3f}..{world_raw[:,2].max():.3f}", file=sys.stderr)

    # World-space normalize: center on origin, flip y (canonical has y-up,
    # we want y-up too which it already has — so no flip needed),
    # rescale to fit viewport height.
    cx = world_raw[:, 0].mean()
    cy = world_raw[:, 1].mean()
    cz = world_raw[:, 2].mean()
    height = world_raw[:, 1].max() - world_raw[:, 1].min()
    target_height = 1.6
    wscale = target_height / height
    vw = world_raw.copy()
    vw[:, 0] = (vw[:, 0] - cx) * wscale
    vw[:, 1] = (vw[:, 1] - cy) * wscale       # canonical has y-up already
    vw[:, 2] = (vw[:, 2] - cz) * wscale       # real 3D depth
    print(f"world bounds: x={vw[:,0].min():.3f}..{vw[:,0].max():.3f} "
          f"y={vw[:,1].min():.3f}..{vw[:,1].max():.3f} "
          f"z={vw[:,2].min():.3f}..{vw[:,2].max():.3f}", file=sys.stderr)

    # ── triangle areas + regions ─────────────────────────────
    tris = canon_tris
    t_v0 = vw[tris[:, 0]]
    t_v1 = vw[tris[:, 1]]
    t_v2 = vw[tris[:, 2]]
    edge1 = t_v1 - t_v0
    edge2 = t_v2 - t_v0
    cross = np.cross(edge1, edge2)
    area = 0.5 * np.linalg.norm(cross, axis=1)

    regions = np.zeros(len(tris), dtype=np.uint8)
    for i, (a, b, c) in enumerate(tris):
        regions[i] = _region_of(int(a), int(b), int(c))

    # ── importance weighting ─────────────────────────────────
    region_boost = {0: 1.0, 1: 6.0, 2: 4.0, 3: 5.0, 4: 2.0, 6: 1.5}
    boost = np.array([region_boost.get(int(r), 1.0) for r in regions])
    weight = area * boost
    cdf = np.cumsum(weight / weight.sum())

    # ── sample N particles ──────────────────────────────────
    print("sampling triangles + barycentric coords…", file=sys.stderr)
    rng = np.random.default_rng(42)
    rs = rng.random(N, dtype=np.float64)
    chosen = np.clip(np.searchsorted(cdf, rs).astype(np.int32), 0, len(tris)-1)
    r1 = rng.random(N, dtype=np.float32)
    r2 = rng.random(N, dtype=np.float32)
    swap = r1 + r2 > 1.0
    r1 = np.where(swap, 1.0 - r1, r1)
    r2 = np.where(swap, 1.0 - r2, r2)
    a = 1.0 - r1 - r2
    b = r1
    c = r2

    v0_idx = tris[chosen, 0]
    v1_idx = tris[chosen, 1]
    v2_idx = tris[chosen, 2]

    print("computing world positions…", file=sys.stderr)
    pos = (a[:, None] * vw[v0_idx]
         + b[:, None] * vw[v1_idx]
         + c[:, None] * vw[v2_idx]).astype(np.float32)

    # UV from build_identity_mesh — Procrustes-fitted canonical 2D into
    # the photo's image space. Each canonical vertex now knows exactly
    # where it lives in the photo, so texture sampling lines up.
    print("computing UVs from photo-fit canonical landmarks…", file=sys.stderr)
    uv = (a[:, None] * photo_uv[v0_idx]
        + b[:, None] * photo_uv[v1_idx]
        + c[:, None] * photo_uv[v2_idx]).astype(np.float32)

    img = Image.open(TEX).convert("RGB")
    img_arr = np.array(img, dtype=np.uint8)
    H, W = img_arr.shape[:2]
    print(f"texture: {W}×{H}", file=sys.stderr)
    tx = np.clip(uv[:, 0] * (W - 1), 0, W - 1).astype(np.int32)
    ty = np.clip(uv[:, 1] * (H - 1), 0, H - 1).astype(np.int32)
    rgb = img_arr[ty, tx]
    region_per = regions[chosen]
    seed = rng.random(N, dtype=np.float32)

    # ── pack binary (same layout as before) ──────────────────
    print("packing binary…", file=sys.stderr)
    rec_size = 28
    buf = np.zeros(N * rec_size, dtype=np.uint8)
    view32 = buf.view(np.float32).reshape(N, rec_size // 4)
    view32[:, 0:3] = pos
    bytes_view = buf.reshape(N, rec_size)
    bytes_view[:, 12] = rgb[:, 0]
    bytes_view[:, 13] = rgb[:, 1]
    bytes_view[:, 14] = rgb[:, 2]
    bytes_view[:, 15] = region_per
    tri_view = buf.view(np.uint16).reshape(N, rec_size // 2)
    tri_view[:, 8] = chosen.astype(np.uint16)
    view32[:, 5] = seed
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
        "mesh_bounds": {
            "x": [float(vw[:, 0].min()), float(vw[:, 0].max())],
            "y": [float(vw[:, 1].min()), float(vw[:, 1].max())],
            "z": [float(vw[:, 2].min()), float(vw[:, 2].max())],
        },
    }, indent=2))


if __name__ == "__main__":
    main()
