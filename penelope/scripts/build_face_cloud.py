"""Generate the photo-real 3D Penelope head particle cloud — TRUE 3D.

Uses the BFM-based dense 3D head reconstruction from 3DDFA_V2:
    assets/penelope_3d_vertices.npy  (38365, 3) averaged from 25 photos
    assets/penelope_3d_tri.npy        (3, 76073) BFM triangulation

The mesh is in IMAGE PIXEL coordinates (x: 0..1920, y: 0..1080,
z: depth-in-pixels relative to face). Real face has ~620 pixels of
depth — proper 3D head geometry, not a flat mask.

Particles are sampled barycentrically on the 76K triangles, weighted by
area × per-region importance. Texture color comes from the front-facing
reference photo at each particle's projected UV.

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
VERTS_FP    = ROOT / "assets" / "penelope_3d_vertices.npy"  # canonical (neutral) mesh
TRIS_FP     = ROOT / "assets" / "penelope_3d_tri.npy"
TEX         = ROOT / "assets" / "penelope_base.webp"
PHOTO_PARAMS = ROOT / "assets" / "penelope_3d_per_photo" / "IMG_7419.npz"
VTX_COLORS  = ROOT / "assets" / "penelope_vertex_colors.npy"   # multi-view composite
VTX_ALPHA   = ROOT / "assets" / "penelope_vertex_alpha.npy"
OUT         = ROOT / "assets" / "face-cloud.bin"
META        = ROOT / "assets" / "face-cloud-meta.json"


def build_face_mask(image, mediapipe_landmarks):
    """Return a (H, W) uint8 alpha mask where the face is 1, else 0.

    Uses MediaPipe's outer face contour (the silhouette landmarks) to
    draw a filled face polygon — same shape MediaPipe's face detector
    would mark out. Particles whose UV falls outside get dropped so
    only Penelope herself contributes, not the photo's backdrop.
    """
    import cv2
    H, W = image.shape[:2]
    # MediaPipe face oval contour (outer silhouette) — 36 landmark
    # indices from MediaPipe's FACEMESH_FACE_OVAL connections.
    OVAL_IDX = [
        10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
        397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
        172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
    ]
    pts = np.array([
        [int(mediapipe_landmarks[i].x * W), int(mediapipe_landmarks[i].y * H)]
        for i in OVAL_IDX
    ], dtype=np.int32)
    mask = np.zeros((H, W), dtype=np.uint8)
    cv2.fillPoly(mask, [pts], 255)
    # Slight feather so the boundary isn't hard
    mask = cv2.GaussianBlur(mask, (15, 15), 0)
    return mask


def detect_face_oval():
    """Run MediaPipe FaceLandmarker on IMG_7419 to get the face oval."""
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision as mp_vision
    fl_model = ROOT / "python" / "models" / "face_landmarker.task"
    base = mp_tasks.BaseOptions(model_asset_path=str(fl_model))
    opts = mp_vision.FaceLandmarkerOptions(
        base_options=base,
        running_mode=mp_vision.RunningMode.IMAGE,
        num_faces=1, min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
    )
    landmarker = mp_vision.FaceLandmarker.create_from_options(opts)
    img_bgr = cv2.imread(str(TEX))
    H, W = img_bgr.shape[:2]
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    res = landmarker.detect(mp_img)
    return res.face_landmarks[0], img_bgr


def build_hair_layer(N_hair: int, rng: np.random.Generator) -> np.ndarray:
    """Sample N_hair particles from the HAIR + SHOULDERS region of the
    source photo. Returns a (N_hair * 28) uint8 buffer in the same
    record format as the face cloud, with region=7 (HAIR) and positioned
    at z behind the face mesh.

    Hair region detection: dilate the face oval outward + downward to
    capture flowing hair and shoulder line, then subtract the face oval
    and drop bright background pixels.
    """
    import cv2 as _cv2
    img_bgr = _cv2.imread(str(TEX))
    H_img, W_img = img_bgr.shape[:2]
    img_rgb = _cv2.cvtColor(img_bgr, _cv2.COLOR_BGR2RGB)

    mp_lm, _ = detect_face_oval()
    face_mask = build_face_mask(img_bgr, mp_lm)

    # Hair area: dilate face mask by ~30% of face size, then subtract
    # face mask. Also drop pixels too far from the face (background).
    face_area = (face_mask > 64).astype(np.uint8) * 255
    # Dilation kernel sized by face bbox
    ys, xs = np.where(face_area > 0)
    if len(ys) == 0:
        return np.zeros(N_hair * 28, dtype=np.uint8)
    face_w = xs.max() - xs.min(); face_h = ys.max() - ys.min()
    kernel_size = int(max(face_w, face_h) * 0.35)
    kernel = _cv2.getStructuringElement(_cv2.MORPH_ELLIPSE,
                                         (kernel_size, kernel_size))
    expanded = _cv2.dilate(face_area, kernel)
    hair_region = (expanded > 0) & ~(face_area > 64)
    # Additionally drop super-bright pixels (white background) — hair
    # in IMG_7419 is dark brown; background is near-white
    img_lum = img_rgb.mean(axis=2)
    hair_region = hair_region & (img_lum < 200)
    hair_ys, hair_xs = np.where(hair_region)
    print(f"  hair region: {len(hair_ys):,} pixels", file=sys.stderr)
    if len(hair_ys) == 0:
        return np.zeros(N_hair * 28, dtype=np.uint8)

    # Sample N_hair pixels uniformly from the hair region
    pick = rng.integers(0, len(hair_ys), N_hair)
    py = hair_ys[pick]; px = hair_xs[pick]
    rgb = img_rgb[py, px]    # (N_hair, 3) uint8

    # Map photo pixels (px, py) to world coords. Use the same scale as
    # the face mesh. Face occupied photo-y 0.215..0.842 → world-y -0.834..0.766
    # → pixel_y_to_world_y(py) = -((py / H_img) - cy) * scale where:
    #   cy = (0.215 + 0.842) / 2 = 0.5285  (face center in photo)
    #   scale = 1.6 / (0.842 - 0.215) = 2.551 (so face fills target height 1.6)
    cy_norm = 0.5285
    scale = 1.6 / (0.842 - 0.215)
    cx_norm = 0.5     # rough center; could be tightened
    world_x = ((px / W_img) - cx_norm) * scale * 1.778   # 16:9 correction
    world_y = -((py / H_img) - cy_norm) * scale
    # Curved depth — hair forms a 3D shell behind/around the head, not
    # a flat plane. Hair at the centerline goes deep (z=-0.85), hair at
    # the sides comes forward (z=-0.40) so when the head rotates, the
    # hair shell rotates naturally with it.
    x_norm = world_x / np.maximum(1e-6, np.abs(world_x).max())  # -1..1
    curve = 0.30 * (1.0 - x_norm * x_norm)  # parabolic, max at center
    world_z = -0.40 - curve - rng.random(N_hair, dtype=np.float32) * 0.10
    pos = np.stack([world_x.astype(np.float32),
                    world_y.astype(np.float32),
                    world_z.astype(np.float32)], axis=1)

    seed = rng.random(N_hair, dtype=np.float32)
    # Pack same 28-byte layout as face particles. region=7=HAIR.
    rec_size = 28
    buf = np.zeros(N_hair * rec_size, dtype=np.uint8)
    view32 = buf.view(np.float32).reshape(N_hair, rec_size // 4)
    view32[:, 0:3] = pos
    bytes_view = buf.reshape(N_hair, rec_size)
    bytes_view[:, 12] = rgb[:, 0]
    bytes_view[:, 13] = rgb[:, 1]
    bytes_view[:, 14] = rgb[:, 2]
    bytes_view[:, 15] = 7              # HAIR region
    view32[:, 5] = seed
    return buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=8_000_000)
    args = ap.parse_args()
    N = args.count
    print(f"target: {N:,} particles", file=sys.stderr)

    verts = np.load(VERTS_FP).astype(np.float32)
    tris_raw = np.load(TRIS_FP)
    if tris_raw.shape[0] == 3 and tris_raw.shape[1] != 3:
        tris = tris_raw.T.astype(np.int32)
    else:
        tris = tris_raw.astype(np.int32)
    print(f"canonical mesh: {len(verts)} verts, {len(tris)} tris", file=sys.stderr)

    # Color now comes from multi-view per-vertex atlas (assembled by
    # scripts/build_texture_atlas.py from all 25 photos). No image-space
    # UV projection needed at the cloud level — barycentric interp of
    # the per-vertex colors gives each particle its final RGB.

    # World normalize: center on origin, flip y, scale to target height
    cx = verts[:, 0].mean(); cy = verts[:, 1].mean(); cz = verts[:, 2].mean()
    height = verts[:, 1].max() - verts[:, 1].min()
    target_height = 1.6
    wscale = target_height / height
    vw = np.empty_like(verts)
    vw[:, 0] =  (verts[:, 0] - cx) * wscale
    vw[:, 1] = -(verts[:, 1] - cy) * wscale     # flip y (image-y is top-down)
    vw[:, 2] = -(verts[:, 2] - cz) * wscale     # invert z so positive=toward camera
    print(f"world bounds: x={vw[:,0].min():.3f}..{vw[:,0].max():.3f} "
          f"y={vw[:,1].min():.3f}..{vw[:,1].max():.3f} "
          f"z={vw[:,2].min():.3f}..{vw[:,2].max():.3f}", file=sys.stderr)

    # ── triangle areas + region tags ─────────────────────────────────
    t_v0 = vw[tris[:, 0]]
    t_v1 = vw[tris[:, 1]]
    t_v2 = vw[tris[:, 2]]
    edge1 = t_v1 - t_v0
    edge2 = t_v2 - t_v0
    cross = np.cross(edge1, edge2)
    area = 0.5 * np.linalg.norm(cross, axis=1)

    # Region tagging by Y position (no canonical landmark indexing on
    # this 38K mesh — use spatial heuristics instead)
    # Y > 0.45 = forehead/brow; 0.10..0.45 = eyes/nose; -0.20..0.10 = mouth
    # below -0.20 = jaw
    vy = vw[:, 1]
    region_per_vert = np.zeros(len(vw), dtype=np.uint8)
    region_per_vert[vy > 0.30] = 2     # brow region
    region_per_vert[(vy > 0.10) & (vy <= 0.30)] = 1   # eye region
    region_per_vert[(vy > -0.10) & (vy <= 0.10)] = 4  # nose region
    region_per_vert[(vy > -0.30) & (vy <= -0.10)] = 3 # lip region
    region_per_vert[vy <= -0.30] = 6                   # jaw region

    # Per-triangle: majority region of its 3 vertices
    regions = np.zeros(len(tris), dtype=np.uint8)
    for i, (a, b, c) in enumerate(tris):
        rs = [region_per_vert[a], region_per_vert[b], region_per_vert[c]]
        regions[i] = max(set(rs), key=rs.count)

    # Per-region density boost
    region_boost = {0: 1.0, 1: 4.0, 2: 2.5, 3: 3.5, 4: 1.8, 6: 1.2}
    boost = np.array([region_boost.get(int(r), 1.0) for r in regions])
    weight = area * boost
    cdf = np.cumsum(weight / weight.sum())

    # ── sample N particles ──────────────────────────────────────────
    # Per-vertex normals — for proper 3D lighting in the shader
    print("computing vertex normals…", file=sys.stderr)
    vert_normals = np.zeros((len(vw), 3), dtype=np.float32)
    v0 = vw[tris[:, 0]]; v1 = vw[tris[:, 1]]; v2 = vw[tris[:, 2]]
    tri_normals = np.cross(v1 - v0, v2 - v0)
    lens = np.linalg.norm(tri_normals, axis=1, keepdims=True) + 1e-9
    tri_normals = tri_normals / lens
    np.add.at(vert_normals, tris[:, 0], tri_normals)
    np.add.at(vert_normals, tris[:, 1], tri_normals)
    np.add.at(vert_normals, tris[:, 2], tri_normals)
    lens = np.linalg.norm(vert_normals, axis=1, keepdims=True) + 1e-9
    vert_normals = vert_normals / lens
    # Convention check — flip so normals point OUT of the face (away from origin)
    # Sample: vertex near nose tip (max z) should have normal with positive z
    nose_idx = np.argmax(vw[:, 2])
    if vert_normals[nose_idx, 2] < 0:
        vert_normals = -vert_normals
        print("  flipped normals to face out of head", file=sys.stderr)

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
    pos = (a[:, None] * vw[v0_idx]
         + b[:, None] * vw[v1_idx]
         + c[:, None] * vw[v2_idx]).astype(np.float32)
    # Per-particle normal (barycentric interp + renormalize)
    nrm = (a[:, None] * vert_normals[v0_idx]
         + b[:, None] * vert_normals[v1_idx]
         + c[:, None] * vert_normals[v2_idx])
    nrm = nrm / (np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-9)
    nrm = nrm.astype(np.float32)

    # ── Multi-view per-vertex texture ──────────────────────────────
    # Color each particle by barycentric-interpolating the multi-view
    # per-vertex colors that build_texture_atlas.py composited from all
    # 25 photos. Each canonical vertex carries a confidence-weighted
    # average color from every photo that saw it from a frontal angle.
    print("computing per-particle color from multi-view atlas…", file=sys.stderr)
    vtx_col = np.load(VTX_COLORS).astype(np.float32)   # (N_vert, 3)
    vtx_alpha = np.load(VTX_ALPHA).astype(np.float32) / 255.0   # (N_vert,)
    # Interpolate per-particle (uses the same barycentric weights as position)
    interp_col = (a[:, None] * vtx_col[v0_idx]
                + b[:, None] * vtx_col[v1_idx]
                + c[:, None] * vtx_col[v2_idx])
    interp_alpha = (a * vtx_alpha[v0_idx]
                  + b * vtx_alpha[v1_idx]
                  + c * vtx_alpha[v2_idx])
    # Apply alpha to color so uncovered particles get RGB=(0,0,0) →
    # the shader discards them via `if (lum < 0.015) discard`
    rgb = (interp_col * interp_alpha[:, None]).clip(0, 255).astype(np.uint8)
    print(f"  particles covered: {(interp_alpha > 0.05).sum():,} / {N:,}",
          file=sys.stderr)

    region_per_p = regions[chosen]
    seed = rng.random(N, dtype=np.float32)

    # ── pack ─────────────────────────────────────────────────────────
    print("packing…", file=sys.stderr)
    rec_size = 28
    buf = np.zeros(N * rec_size, dtype=np.uint8)
    view32 = buf.view(np.float32).reshape(N, rec_size // 4)
    view32[:, 0:3] = pos
    bytes_view = buf.reshape(N, rec_size)
    bytes_view[:, 12] = rgb[:, 0]
    bytes_view[:, 13] = rgb[:, 1]
    bytes_view[:, 14] = rgb[:, 2]
    bytes_view[:, 15] = region_per_p
    tri_view = buf.view(np.uint16).reshape(N, rec_size // 2)
    # cap tri index at uint16 max — 76K triangles fits in uint16 (up to 65535)
    # 3DDFA has 76,073 triangles → exceeds uint16! Use uint32 for tri instead.
    # Quick fix: just store tri mod 65536 (we don't actually use it at render time)
    tri_view[:, 8] = (chosen & 0xFFFF).astype(np.uint16)
    view32[:, 5] = seed
    bary16 = np.empty((N, 2), dtype=np.float16)
    bary16[:, 0] = a.astype(np.float16)
    bary16[:, 1] = b.astype(np.float16)
    view16 = buf.view(np.uint16).reshape(N, rec_size // 2)
    view16[:, 12:14] = bary16.view(np.uint16)

    # ── HAIR LAYER ──────────────────────────────────────────────
    # BFM mesh is forehead-to-chin; no hair. Sample ~2M particles from
    # the hair/silhouette region of IMG_7419 (above the face oval) and
    # place them at z behind the face mesh so they frame the head.
    print("sampling hair particles…", file=sys.stderr)
    hair_buf = build_hair_layer(N_hair=2_000_000, rng=rng)
    # CRITICAL: hair BEFORE face in the binary so it renders first
    # (back-to-front) with alpha blending — face draws on top of hair.
    OUT.write_bytes(hair_buf.tobytes() + buf.tobytes())
    print(f"wrote {OUT.name}: {OUT.stat().st_size / 1024 / 1024:.1f} MB "
          f"({N + 2_000_000} total = 2M hair + {N} face)", file=sys.stderr)

    META.write_text(json.dumps({
        "count": int(N + 2_000_000),
        "count_face": int(N),
        "count_hair": 2_000_000,
        "record_size": rec_size,
        "source": "3DDFA_V2 BFM (face) + photo hair layer",
        "mesh_verts": int(len(vw)),
        "mesh_tris": int(len(tris)),
        "layout": {
            "pos":    {"offset": 0,  "type": "float32", "count": 3},
            "rgb":    {"offset": 12, "type": "uint8",   "count": 3},
            "region": {"offset": 15, "type": "uint8",   "count": 1},
            "tri":    {"offset": 16, "type": "uint16",  "count": 1},
            "seed":   {"offset": 20, "type": "float32", "count": 1},
            "bary":   {"offset": 24, "type": "float16", "count": 2},
        },
        "world_bounds": {
            "x": [float(vw[:, 0].min()), float(vw[:, 0].max())],
            "y": [float(vw[:, 1].min()), float(vw[:, 1].max())],
            "z": [float(vw[:, 2].min()), float(vw[:, 2].max())],
        },
    }, indent=2))


if __name__ == "__main__":
    main()
