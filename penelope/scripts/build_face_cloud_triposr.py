"""Build the Penelope particle cloud from the TripoSR 3D head mesh.

Inputs:
    /tmp/triposr_head_v3/0/mesh.obj       144K verts, 186K tris, with UVs
    /tmp/triposr_head_v3/0/texture.png    2048x2048 UV atlas

Output:
    assets/face-cloud.bin                 8M particles × 28 bytes
    assets/face-cloud-meta.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MESH_FP = Path("/tmp/triposr_head_v3/0/mesh.obj")
TEX_FP  = Path("/tmp/triposr_head_v3/0/texture.png")
OUT     = ROOT / "assets" / "face-cloud.bin"
META    = ROOT / "assets" / "face-cloud-meta.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=8_000_000)
    args = ap.parse_args()
    N = args.count
    print(f"target: {N:,} particles", file=sys.stderr)

    # ── load mesh ────────────────────────────────────────────
    m = trimesh.load(MESH_FP, process=False)
    verts = np.asarray(m.vertices, dtype=np.float32)
    tris  = np.asarray(m.faces, dtype=np.int32)
    uvs   = np.asarray(m.visual.uv, dtype=np.float32)
    print(f"mesh: {len(verts)} verts, {len(tris)} tris, {len(uvs)} UVs",
          file=sys.stderr)

    # Center + scale to fit viewport. Earlier orbit told us face was at
    # yaw=45 in mesh space — rotate -45° around Y so face ends up at +Z.
    centroid = verts.mean(axis=0)
    verts = verts - centroid
    # TripoSR's mesh has the face pointing in +X direction (verified by
    # rendering at yaw=90 with face-toward-camera). With our R matrix
    # convention, rotation by -90° maps +X → +Z (Three.js camera looks
    # at +Z by default).
    import math
    theta = -math.pi * 90 / 180
    R = np.array([
        [ math.cos(theta), 0, math.sin(theta)],
        [               0, 1,              0],
        [-math.sin(theta), 0, math.cos(theta)],
    ], dtype=np.float32)
    verts = verts @ R.T

    # Normalize to viewport height = 1.6, flip Y so top of head is +Y
    # (TripoSR / OBJ convention has +Y down; Three.js wants +Y up).
    height = verts[:, 1].max() - verts[:, 1].min()
    wscale = 1.6 / height
    verts = verts * wscale
    verts[:, 1] = -verts[:, 1]   # flip Y so head is right-side up
    # Y inversion if needed — TripoSR y-axis might be inverted from
    # our world (y-up). After examining the orbit images, top of head
    # was UP in world view, but pyrender uses Y-up so should be fine.
    # Will verify visually.

    print(f"world bounds: x={verts[:,0].min():.3f}..{verts[:,0].max():.3f} "
          f"y={verts[:,1].min():.3f}..{verts[:,1].max():.3f} "
          f"z={verts[:,2].min():.3f}..{verts[:,2].max():.3f}",
          file=sys.stderr)

    # ── load texture ─────────────────────────────────────────
    img = Image.open(TEX_FP).convert("RGB")
    img_arr = np.array(img, dtype=np.uint8)
    H_img, W_img = img_arr.shape[:2]
    print(f"texture: {W_img}×{H_img}", file=sys.stderr)

    # ── triangle areas + per-region tagging ─────────────────
    t_v0 = verts[tris[:, 0]]
    t_v1 = verts[tris[:, 1]]
    t_v2 = verts[tris[:, 2]]
    cross = np.cross(t_v1 - t_v0, t_v2 - t_v0)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    print(f"area range: {area.min():.5f}..{area.max():.5f} "
          f"(median {np.median(area):.5f})", file=sys.stderr)

    # Region tags by spatial Y (since TripoSR mesh doesn't have known
    # landmark indices). Face area is at top of head, mouth lower, etc.
    # Top of head ~ y=0.8, chin ~ y=-0.8.
    vy = verts[:, 1]
    region_v = np.zeros(len(verts), dtype=np.uint8)
    region_v[vy > 0.45] = 7    # hair region (top of head)
    region_v[(vy > 0.20) & (vy <= 0.45)] = 2   # forehead/brow
    region_v[(vy > 0.05) & (vy <= 0.20)] = 1   # eye band
    region_v[(vy > -0.10) & (vy <= 0.05)] = 4  # nose
    region_v[(vy > -0.30) & (vy <= -0.10)] = 3 # lip
    region_v[vy <= -0.30] = 6                   # jaw

    # Per-triangle region = majority of its 3 vertices
    regions = np.zeros(len(tris), dtype=np.uint8)
    for i, (a, b, c) in enumerate(tris):
        rs = [region_v[a], region_v[b], region_v[c]]
        regions[i] = max(set(rs), key=rs.count)

    # Boost density on feature regions
    region_boost = {0: 1.0, 1: 3.0, 2: 2.0, 3: 3.5, 4: 1.8, 6: 1.2, 7: 1.0}
    boost = np.array([region_boost.get(int(r), 1.0) for r in regions])
    weight = area * boost
    cdf = np.cumsum(weight / weight.sum())

    # ── sample N particles ──────────────────────────────────
    print("sampling…", file=sys.stderr)
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
    pos = (a[:, None] * verts[v0_idx]
         + b[:, None] * verts[v1_idx]
         + c[:, None] * verts[v2_idx]).astype(np.float32)

    # Per-particle UV (barycentric interp of vertex UVs)
    p_uv = (a[:, None] * uvs[v0_idx]
          + b[:, None] * uvs[v1_idx]
          + c[:, None] * uvs[v2_idx]).astype(np.float32)
    # OBJ UVs are y-up, image coords are y-down → flip v
    p_uv[:, 1] = 1.0 - p_uv[:, 1]
    tx = np.clip(p_uv[:, 0] * (W_img - 1), 0, W_img - 1).astype(np.int32)
    ty = np.clip(p_uv[:, 1] * (H_img - 1), 0, H_img - 1).astype(np.int32)
    rgb = img_arr[ty, tx]
    region_per = regions[chosen]
    seed = rng.random(N, dtype=np.float32)

    # ── pack 28B records ───────────────────────────────────
    print("packing…", file=sys.stderr)
    rec_size = 28
    buf = np.zeros(N * rec_size, dtype=np.uint8)
    v32 = buf.view(np.float32).reshape(N, rec_size // 4)
    v32[:, 0:3] = pos
    bv = buf.reshape(N, rec_size)
    bv[:, 12] = rgb[:, 0]
    bv[:, 13] = rgb[:, 1]
    bv[:, 14] = rgb[:, 2]
    bv[:, 15] = region_per
    v32[:, 5] = seed

    OUT.write_bytes(buf.tobytes())
    print(f"wrote {OUT.name}: {OUT.stat().st_size/1024/1024:.1f} MB",
          file=sys.stderr)

    META.write_text(json.dumps({
        "count": int(N),
        "count_face": int(N),
        "count_hair": 0,
        "record_size": rec_size,
        "source": "TripoSR head-cropped IMG_7419, 144K verts, 186K tris",
        "mesh_verts": int(len(verts)),
        "mesh_tris": int(len(tris)),
        "layout": {
            "pos":    {"offset": 0,  "type": "float32", "count": 3},
            "rgb":    {"offset": 12, "type": "uint8",   "count": 3},
            "region": {"offset": 15, "type": "uint8",   "count": 1},
            "seed":   {"offset": 20, "type": "float32", "count": 1},
        },
        "world_bounds": {
            "x": [float(verts[:,0].min()), float(verts[:,0].max())],
            "y": [float(verts[:,1].min()), float(verts[:,1].max())],
            "z": [float(verts[:,2].min()), float(verts[:,2].max())],
        },
    }, indent=2))


if __name__ == "__main__":
    main()
