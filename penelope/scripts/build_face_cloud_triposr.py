"""Build the Penelope particle cloud from the TripoSR 3D head mesh.

Uses MediaPipe to find her actual facial feature positions on the
rendered 3D head, then tags particles by 3D proximity to those features
(not naive world-Y bands).

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
import math
import sys
from pathlib import Path

import cv2
import numpy as np
import trimesh
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
# Switched from IMG_7419 (small, smiling, tilted) to IMG_7427 (3415x3415
# high-res, clean front, neutral expression — shows her jawline + nose
# profile properly per Dylan's spec). Plus a different HEAD CROP source
# image since extract_head.py was run on IMG_7427.
MESH_FP   = Path("/tmp/triposr_7427/0/mesh.obj")
TEX_FP    = Path("/tmp/triposr_7427/0/texture.png")
HEAD_CROP_FP = Path("/tmp/penelope_head_7427.png")
OUT     = ROOT / "assets" / "face-cloud.bin"
META    = ROOT / "assets" / "face-cloud-meta.json"


# MediaPipe FaceMesh landmark groupings — used to compute centroids
# for the major facial features.
LANDMARKS = {
    "left_eye":   [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246],
    "right_eye":  [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398],
    "left_brow":  [70, 63, 105, 66, 107],
    "right_brow": [336, 296, 334, 293, 300],
    "nose":       [1, 2, 4, 5, 6, 19, 94, 168, 197],
    "upper_lip":  [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291],
    "lower_lip":  [146, 91, 181, 84, 17, 314, 405, 321, 375],
    "jaw":        [152, 175, 199, 200, 18, 176, 148, 377, 400, 378, 379, 365, 397],
}

# Region IDs (matches existing renderer/shader)
REGION = {
    "skin": 0, "left_eye": 1, "right_eye": 1,
    "left_brow": 2, "right_brow": 2, "nose": 4,
    "upper_lip": 3, "lower_lip": 3, "jaw": 6, "hair": 7,
}


def render_mesh_orthographic(verts, tris, W=512, H=512):
    """Render the front of the mesh orthographically to a 2D image.

    Returns (rendered_rgb, depth_map). Each pixel of depth_map records
    the closest mesh vertex index that projects to it (or -1).
    """
    # Project verts orthographically
    px = ((verts[:, 0] / 1.2 + 0.5) * W).astype(np.int32)
    py = ((-verts[:, 1] / 1.2 + 0.5) * H).astype(np.int32)
    pz = verts[:, 2]
    in_view = (px >= 0) & (px < W) & (py >= 0) & (py < H)
    px, py, pz = px[in_view], py[in_view], pz[in_view]
    vidx = np.where(in_view)[0]

    # Z-buffer: keep frontmost (largest z) per pixel
    order = np.argsort(pz)[::-1]
    flat = py[order] * W + px[order]
    _, first = np.unique(flat, return_index=True)
    front_pixels = order[first]

    # Generate a face_visible mask (where the head appears)
    img = np.zeros((H, W), dtype=np.uint8)
    img[py[front_pixels], px[front_pixels]] = 255
    # Fill small holes for MediaPipe to find a face
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    img = cv2.morphologyEx(img, cv2.MORPH_CLOSE, kernel)
    return img


def detect_face_landmarks_2d(rendered_rgb_image):
    """Run MediaPipe on a rendered front view → 478 (x, y) landmark
    pixels. Returns None if no face detected."""
    import mediapipe as mp
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision as mp_vision
    fl_model = ROOT / "python" / "models" / "face_landmarker.task"
    base = mp_tasks.BaseOptions(model_asset_path=str(fl_model))
    opts = mp_vision.FaceLandmarkerOptions(
        base_options=base,
        running_mode=mp_vision.RunningMode.IMAGE,
        num_faces=1,
        min_face_detection_confidence=0.3,
        min_face_presence_confidence=0.3,
    )
    landmarker = mp_vision.FaceLandmarker.create_from_options(opts)
    H, W = rendered_rgb_image.shape[:2]
    rgb = cv2.cvtColor(rendered_rgb_image, cv2.COLOR_BGR2RGB) \
        if rendered_rgb_image.ndim == 3 else \
        cv2.cvtColor(rendered_rgb_image, cv2.COLOR_GRAY2RGB)
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    res = landmarker.detect(mp_img)
    if not res.face_landmarks:
        return None
    lm = res.face_landmarks[0]
    return np.array([[p.x * W, p.y * H] for p in lm], dtype=np.float32)


def landmarks_on_head_crop():
    """Run MediaPipe on /tmp/penelope_head.png (the head crop that fed
    TripoSR). MediaPipe reliably finds the face there. Returns (N, 2)
    pixel-space landmark positions in the head-crop's coordinate frame.
    """
    import mediapipe as mp
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision as mp_vision
    fl_model = ROOT / "python" / "models" / "face_landmarker.task"
    base = mp_tasks.BaseOptions(model_asset_path=str(fl_model))
    opts = mp_vision.FaceLandmarkerOptions(
        base_options=base,
        running_mode=mp_vision.RunningMode.IMAGE,
        num_faces=1,
    )
    landmarker = mp_vision.FaceLandmarker.create_from_options(opts)
    img_bgr = cv2.imread(str(HEAD_CROP_FP))
    H, W = img_bgr.shape[:2]
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    res = landmarker.detect(mp_img)
    if not res.face_landmarks:
        raise SystemExit("MediaPipe failed on the head crop too")
    lm = res.face_landmarks[0]
    return np.array([[p.x * W, p.y * H] for p in lm], dtype=np.float32), W, H


def render_textured_front(verts, tris, uvs, tex_img, W=512, H=512):
    """Render the textured mesh from front via dense barycentric sampling.
    Same projection convention as our verify script — known to show the
    face when sorted front-to-back. Used to detect MediaPipe landmarks
    for feature-aware region tagging.
    """
    # Sample N points barycentrically on the mesh, render with z-buffer.
    # Higher samples = denser render = MediaPipe finds the face.
    rng = np.random.default_rng(0)
    N_render = 3_000_000
    # Pick triangles weighted by area
    t_v0 = verts[tris[:, 0]]; t_v1 = verts[tris[:, 1]]; t_v2 = verts[tris[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(t_v1 - t_v0, t_v2 - t_v0), axis=1)
    cdf_local = np.cumsum(area / area.sum())
    chosen = np.clip(np.searchsorted(cdf_local, rng.random(N_render)), 0, len(tris)-1)
    r1 = rng.random(N_render, dtype=np.float32)
    r2 = rng.random(N_render, dtype=np.float32)
    swap = r1 + r2 > 1.0
    r1 = np.where(swap, 1.0 - r1, r1); r2 = np.where(swap, 1.0 - r2, r2)
    a, b, c = 1.0 - r1 - r2, r1, r2
    v0_idx = tris[chosen, 0]; v1_idx = tris[chosen, 1]; v2_idx = tris[chosen, 2]
    pos = (a[:, None] * verts[v0_idx] + b[:, None] * verts[v1_idx]
         + c[:, None] * verts[v2_idx])
    uv = (a[:, None] * uvs[v0_idx] + b[:, None] * uvs[v1_idx]
        + c[:, None] * uvs[v2_idx])
    tH, tW = tex_img.shape[:2]
    uv = uv.copy(); uv[:, 1] = 1.0 - uv[:, 1]
    tx = np.clip(uv[:, 0] * (tW - 1), 0, tW - 1).astype(np.int32)
    ty = np.clip(uv[:, 1] * (tH - 1), 0, tH - 1).astype(np.int32)
    colors = tex_img[ty, tx]

    sx = ((pos[:, 0] / 1.2 + 0.5) * W).astype(np.int32)
    sy = ((-pos[:, 1] / 1.2 + 0.5) * H).astype(np.int32)
    sz = pos[:, 2]
    in_view = (sx >= 0) & (sx < W) & (sy >= 0) & (sy < H)
    sx, sy, sz, colors = sx[in_view], sy[in_view], sz[in_view], colors[in_view]
    order = np.argsort(sz)[::-1]   # frontmost first
    flat = sy[order] * W + sx[order]
    _, first = np.unique(flat, return_index=True)
    img = np.zeros((H, W, 3), dtype=np.uint8)
    img[sy[order][first], sx[order][first]] = colors[order][first]
    return img


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

    # Center + rotate so face is at +Z, flip Y for Y-up.
    # Verified by orbiting raw mesh: face is at +X direction (visible
    # at camera yaw=90), upside down (chin at top). Rotate by -90°
    # around Y maps +X → +Z. Then Y-flip below puts head right-side up.
    centroid = verts.mean(axis=0)
    verts = verts - centroid
    theta = -math.pi * 90 / 180
    R = np.array([
        [ math.cos(theta), 0, math.sin(theta)],
        [               0, 1,              0],
        [-math.sin(theta), 0, math.cos(theta)],
    ], dtype=np.float32)
    verts = verts @ R.T
    height = verts[:, 1].max() - verts[:, 1].min()
    wscale = 1.6 / height
    verts = verts * wscale
    verts[:, 1] = -verts[:, 1]
    print(f"world bounds: x={verts[:,0].min():.3f}..{verts[:,0].max():.3f} "
          f"y={verts[:,1].min():.3f}..{verts[:,1].max():.3f} "
          f"z={verts[:,2].min():.3f}..{verts[:,2].max():.3f}",
          file=sys.stderr)

    # ── load texture ─────────────────────────────────────────
    tex_img = np.array(Image.open(TEX_FP).convert("RGB"), dtype=np.uint8)
    tH, tW = tex_img.shape[:2]
    print(f"texture: {tW}×{tH}", file=sys.stderr)

    # ── FEATURE-AWARE region tagging ─────────────────────────
    # Run MediaPipe on the head crop that fed TripoSR (where MediaPipe
    # reliably finds the face). Back-project pixel coords to mesh XY
    # via the known head-crop dimensions vs world mesh bounds.
    print("running MediaPipe on /tmp/penelope_head.png…", file=sys.stderr)
    lm_pix, hc_W, hc_H = landmarks_on_head_crop()
    print(f"  found {len(lm_pix)} landmarks in {hc_W}×{hc_H} head crop",
          file=sys.stderr)

    # Map head-crop pixel coords → mesh-world XY.
    # Head crop is centered around her face; mesh XY occupies a similar
    # spatial layout. Use linear mapping from pixel → world.
    mesh_x_min, mesh_x_max = verts[:, 0].min(), verts[:, 0].max()
    mesh_y_min, mesh_y_max = verts[:, 1].min(), verts[:, 1].max()
    # Pixel (px, py) → normalized (0..1) → world
    lm_world_xy = np.empty((len(lm_pix), 2), dtype=np.float32)
    lm_world_xy[:, 0] = (lm_pix[:, 0] / hc_W) * (mesh_x_max - mesh_x_min) + mesh_x_min
    # Photo-y goes top-down; world-y goes up. So flip and remap.
    lm_world_xy[:, 1] = (1.0 - lm_pix[:, 1] / hc_H) * (mesh_y_max - mesh_y_min) + mesh_y_min

    # Each landmark gets a 3D position by finding the closest mesh vertex
    # in (x, y) — but ONLY among FRONT-FACING vertices (the upper half
    # of the z range, since face is at +Z).
    z_threshold = np.percentile(verts[:, 2], 50)   # median z; front half
    front_mask = verts[:, 2] > z_threshold
    front_verts = verts[front_mask]
    front_indices = np.where(front_mask)[0]
    print(f"back-projecting landmarks to {front_mask.sum()} front-facing verts (z > {z_threshold:.2f})…",
          file=sys.stderr)
    feature_centers = {}
    for fname, idxs in LANDMARKS.items():
        pts3d = []
        for idx in idxs:
            if idx >= len(lm_world_xy):
                continue
            lx, ly = lm_world_xy[idx]
            d2 = (front_verts[:, 0] - lx)**2 + (front_verts[:, 1] - ly)**2
            v = np.argmin(d2)
            pts3d.append(front_verts[v])
        if pts3d:
            feature_centers[fname] = np.mean(pts3d, axis=0)

    print(f"  feature centers: " + ", ".join(
        f"{k}=({v[0]:.2f},{v[1]:.2f},{v[2]:.2f})"
        for k, v in feature_centers.items()), file=sys.stderr)

    # Estimate face size (eye-to-eye distance) for distance thresholds
    if "left_eye" in feature_centers and "right_eye" in feature_centers:
        eye_dist = np.linalg.norm(feature_centers["left_eye"] -
                                   feature_centers["right_eye"])
    else:
        eye_dist = 0.3
    print(f"  eye-to-eye distance: {eye_dist:.3f}", file=sys.stderr)

    # Per-vertex region: nearest feature within max_dist; else skin or hair
    print("tagging vertices by feature proximity…", file=sys.stderr)
    # Distance radius for each feature (scaled by eye_dist)
    feature_radius = {
        "left_eye":   eye_dist * 0.45,
        "right_eye":  eye_dist * 0.45,
        "left_brow":  eye_dist * 0.40,
        "right_brow": eye_dist * 0.40,
        "nose":       eye_dist * 0.50,
        "upper_lip":  eye_dist * 0.55,
        "lower_lip":  eye_dist * 0.55,
        "jaw":        eye_dist * 0.70,
    }
    region_v = np.zeros(len(verts), dtype=np.uint8)
    # Default: hair if behind a face plane threshold, else skin
    # Face plane: anything with z > eye_z - 0.2 (in front of skull) AND
    # within face-front area is face. Behind that is hair/skull.
    face_z_min = (feature_centers.get("nose", verts.mean(axis=0))[2] - 0.4)
    is_face_front = verts[:, 2] > face_z_min
    region_v[~is_face_front] = REGION["hair"]
    region_v[is_face_front] = REGION["skin"]

    # For each face feature, tag vertices within radius
    for fname, center in feature_centers.items():
        rad = feature_radius.get(fname, 0.15)
        # Distance only in XY plane (front-facing features have similar Z)
        d2 = ((verts[:, 0] - center[0])**2
            + (verts[:, 1] - center[1])**2)
        mask = (d2 < rad**2) & is_face_front
        region_v[mask] = REGION[fname]

    print(f"  region histogram: " + ", ".join(
        f"{r}={c}" for r, c in zip(*np.unique(region_v, return_counts=True))),
        file=sys.stderr)

    # ── FACE CENTERING ──────────────────────────────────────────
    # TripoSR mesh extends well above the actual face (hair takes the
    # upper half). Translate the mesh down so the FACE CENTER (between
    # eyes) sits at world Y=0, which is where the camera looks. This
    # makes her eyes meet Dylan's eyes by default.
    if "left_eye" in feature_centers and "right_eye" in feature_centers:
        face_center_y = (feature_centers["left_eye"][1]
                       + feature_centers["right_eye"][1]) / 2
        face_center_x = (feature_centers["left_eye"][0]
                       + feature_centers["right_eye"][0]) / 2
        print(f"  centering face: x_shift={-face_center_x:.3f} y_shift={-face_center_y:.3f}",
              file=sys.stderr)
        verts[:, 0] -= face_center_x
        verts[:, 1] -= face_center_y
        # Update feature centers too
        for k in feature_centers:
            feature_centers[k] = feature_centers[k] - np.array([face_center_x, face_center_y, 0.0])

    # Per-triangle region = majority of its 3 vertices
    regions = np.zeros(len(tris), dtype=np.uint8)
    for i, (a, b, c) in enumerate(tris):
        rs = [region_v[a], region_v[b], region_v[c]]
        regions[i] = max(set(rs), key=rs.count)

    # ── triangle areas ───────────────────────────────────────
    t_v0 = verts[tris[:, 0]]
    t_v1 = verts[tris[:, 1]]
    t_v2 = verts[tris[:, 2]]
    cross = np.cross(t_v1 - t_v0, t_v2 - t_v0)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    region_boost = {0: 1.0, 1: 3.5, 2: 2.5, 3: 4.0, 4: 2.0, 6: 1.5, 7: 1.0}
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

    # Single-photo UV texture from IMG_7427. The multi-view composite
    # attempt produced ghosting due to PnP misalignment across 25 photos
    # with varied poses — would need much tighter pose refinement to
    # use those for texture. The single-photo result is clean.
    p_uv = (a[:, None] * uvs[v0_idx]
          + b[:, None] * uvs[v1_idx]
          + c[:, None] * uvs[v2_idx]).astype(np.float32)
    p_uv[:, 1] = 1.0 - p_uv[:, 1]
    tx = np.clip(p_uv[:, 0] * (tW - 1), 0, tW - 1).astype(np.int32)
    ty = np.clip(p_uv[:, 1] * (tH - 1), 0, tH - 1).astype(np.int32)
    rgb = tex_img[ty, tx]
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
        "source": "TripoSR mesh + MediaPipe feature-aware region tagging",
        "mesh_verts": int(len(verts)),
        "mesh_tris": int(len(tris)),
        "feature_centers": {k: v.tolist() for k, v in feature_centers.items()},
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
