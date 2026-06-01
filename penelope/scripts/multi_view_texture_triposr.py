"""Multi-view texture composite for the TripoSR mesh.

For each of the 25 reference photos:
  1. Detect MediaPipe 478 landmarks
  2. Solve PnP using the mesh's known feature centers (eyes, brows,
     nose, lips, jaw) as 3D anchor points
  3. Project all mesh vertices through that camera pose
  4. Sample per-vertex RGB from the photo
  5. Frontality weight: max(0, vertex_normal · -view_direction)

Composite: per-vertex weighted average of RGB across all 25 photos
where the vertex was visible from a front-facing angle.

Output:
    assets/penelope_multiview_colors.npy   (N_verts, 3) uint8
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import cv2
import numpy as np
import trimesh
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MESH_FP = Path("/tmp/triposr_7427/0/mesh.obj")
HEAD_CROP_FP = Path("/tmp/penelope_head_7427.png")
REF_DIR = ROOT / "assets" / "reference"
OUT_COL = ROOT / "assets" / "penelope_multiview_colors.npy"
OUT_W   = ROOT / "assets" / "penelope_multiview_weights.npy"

# MediaPipe landmarks → feature groups for both base mesh and other photos.
# 3D anchor indices (in landmark space). We use a subset of landmarks
# that are robustly detected in most photos.
ANCHOR_IDS = [
    33, 263,    # outer eye corners (left, right)
    1,          # nose tip
    61, 291,    # mouth corners
    152,        # chin
    10,         # forehead center
    234, 454,   # cheekbones
]


def detect_landmarks(image_bgr, landmarker):
    import mediapipe as mp
    H, W = image_bgr.shape[:2]
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    res = landmarker.detect(mp_img)
    if not res.face_landmarks:
        return None
    lm = res.face_landmarks[0]
    return np.array([[p.x * W, p.y * H] for p in lm], dtype=np.float32)


def make_landmarker():
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
    return mp_vision.FaceLandmarker.create_from_options(opts)


def get_3d_anchors_on_mesh(verts, landmarks_on_head_crop, hc_W, hc_H):
    """For each ANCHOR landmark, find the closest 3D mesh vertex.
    Returns (M, 3) anchor positions in mesh-world space."""
    # Map landmark pixels to mesh world XY (same logic as build_face_cloud)
    mesh_x_min, mesh_x_max = verts[:, 0].min(), verts[:, 0].max()
    mesh_y_min, mesh_y_max = verts[:, 1].min(), verts[:, 1].max()
    lm_wxy = np.empty((len(landmarks_on_head_crop), 2), dtype=np.float32)
    lm_wxy[:, 0] = (landmarks_on_head_crop[:, 0] / hc_W) * (mesh_x_max - mesh_x_min) + mesh_x_min
    lm_wxy[:, 1] = (1.0 - landmarks_on_head_crop[:, 1] / hc_H) * (mesh_y_max - mesh_y_min) + mesh_y_min
    # Only use FRONT-FACING vertices (high Z)
    z_thresh = np.percentile(verts[:, 2], 50)
    front_mask = verts[:, 2] > z_thresh
    front_verts = verts[front_mask]

    anchors_3d = []
    for idx in ANCHOR_IDS:
        if idx >= len(lm_wxy):
            anchors_3d.append([0, 0, 0]); continue
        lx, ly = lm_wxy[idx]
        d2 = (front_verts[:, 0] - lx)**2 + (front_verts[:, 1] - ly)**2
        v = np.argmin(d2)
        anchors_3d.append(front_verts[v])
    return np.array(anchors_3d, dtype=np.float32)


def main():
    print("=== multi-view texture composite ===", file=sys.stderr)

    # Load mesh + apply same transforms as build_face_cloud_triposr.py
    m = trimesh.load(MESH_FP, process=False)
    verts = np.asarray(m.vertices, dtype=np.float32)
    verts -= verts.mean(axis=0)
    theta = -math.pi * 90 / 180
    R = np.array([[math.cos(theta), 0, math.sin(theta)],
                  [0, 1, 0], [-math.sin(theta), 0, math.cos(theta)]],
                 dtype=np.float32)
    verts = verts @ R.T
    height = verts[:, 1].max() - verts[:, 1].min()
    wscale = 1.6 / height
    verts = verts * wscale
    verts[:, 1] = -verts[:, 1]
    print(f"mesh loaded: {len(verts)} verts", file=sys.stderr)

    # Compute vertex normals
    tris = np.asarray(m.faces, dtype=np.int32)
    normals = np.zeros_like(verts)
    v0 = verts[tris[:, 0]]; v1 = verts[tris[:, 1]]; v2 = verts[tris[:, 2]]
    tn = np.cross(v1 - v0, v2 - v0)
    tn = tn / (np.linalg.norm(tn, axis=1, keepdims=True) + 1e-9)
    np.add.at(normals, tris[:, 0], tn)
    np.add.at(normals, tris[:, 1], tn)
    np.add.at(normals, tris[:, 2], tn)
    normals = normals / (np.linalg.norm(normals, axis=1, keepdims=True) + 1e-9)
    # Ensure normals point outward (positive Z toward camera for face verts)
    if normals[np.argmax(verts[:, 2]), 2] < 0:
        normals = -normals
    print(f"normals computed", file=sys.stderr)

    landmarker = make_landmarker()

    # ── Step 1: anchor 3D points using the base photo (IMG_7427) ──
    head_bgr = cv2.imread(str(HEAD_CROP_FP))
    base_lm = detect_landmarks(head_bgr, landmarker)
    hc_H, hc_W = head_bgr.shape[:2]
    anchors_3d = get_3d_anchors_on_mesh(verts, base_lm, hc_W, hc_H)
    print(f"anchor 3D points (base):\n{anchors_3d}", file=sys.stderr)

    # ── Step 2: for each photo, solve PnP ───────────────────────────
    photo_files = sorted([f for f in REF_DIR.iterdir()
                          if f.suffix.lower() in ('.jpg', '.webp')])
    print(f"processing {len(photo_files)} photos…", file=sys.stderr)

    color_sum = np.zeros((len(verts), 3), dtype=np.float64)
    weight_sum = np.zeros(len(verts), dtype=np.float64)

    for i, ph in enumerate(photo_files):
        img_bgr = cv2.imread(str(ph))
        if img_bgr is None:
            continue
        H, W = img_bgr.shape[:2]
        lm = detect_landmarks(img_bgr, landmarker)
        if lm is None:
            print(f"  [{i+1}/{len(photo_files)}] {ph.name}: NO FACE", file=sys.stderr)
            continue

        # Extract anchor 2D points for this photo
        anchors_2d = lm[ANCHOR_IDS].astype(np.float32)

        # Solve PnP: camera pose given 3D points + their 2D projections
        # Approximate camera intrinsics (focal length ~= image width)
        focal = max(W, H)
        cam_matrix = np.array([
            [focal, 0, W/2],
            [0, focal, H/2],
            [0, 0, 1]
        ], dtype=np.float64)
        dist_coeffs = np.zeros((4, 1))

        ok, rvec, tvec = cv2.solvePnP(
            anchors_3d.astype(np.float64), anchors_2d.astype(np.float64),
            cam_matrix, dist_coeffs, flags=cv2.SOLVEPNP_EPNP)
        if not ok:
            print(f"  [{i+1}/{len(photo_files)}] {ph.name}: PnP FAILED", file=sys.stderr)
            continue
        # Refine with iterative LM
        ok, rvec, tvec = cv2.solvePnP(
            anchors_3d.astype(np.float64), anchors_2d.astype(np.float64),
            cam_matrix, dist_coeffs, rvec, tvec, useExtrinsicGuess=True,
            flags=cv2.SOLVEPNP_ITERATIVE)

        # Project ALL mesh vertices through this camera
        proj_pts, _ = cv2.projectPoints(
            verts.astype(np.float64), rvec, tvec, cam_matrix, dist_coeffs)
        proj_pts = proj_pts.squeeze(1)   # (N, 2)

        # Camera direction in world space: rvec is rotation FROM world to camera
        # The camera looks down the camera's local +Z. Camera-to-world rotation = R(rvec).T
        Rmat, _ = cv2.Rodrigues(rvec)
        view_dir_world = (Rmat.T @ np.array([0, 0, 1]))   # cam Z in world

        # Per-vertex frontality = max(0, normal · -view_dir)
        frontality = np.maximum(0.0, -(normals @ view_dir_world))

        # Sample photo at projected pixels
        in_view = ((proj_pts[:, 0] >= 0) & (proj_pts[:, 0] < W) &
                   (proj_pts[:, 1] >= 0) & (proj_pts[:, 1] < H) &
                   (frontality > 0.1))
        if in_view.sum() == 0:
            print(f"  [{i+1}/{len(photo_files)}] {ph.name}: no verts in view", file=sys.stderr)
            continue

        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        tx = np.clip(proj_pts[:, 0], 0, W - 1).astype(np.int32)
        ty = np.clip(proj_pts[:, 1], 0, H - 1).astype(np.int32)
        sampled = img_rgb[ty, tx]   # (N, 3) uint8

        w = (in_view.astype(np.float32) * frontality).astype(np.float64)
        color_sum += sampled.astype(np.float64) * w[:, None]
        weight_sum += w
        print(f"  [{i+1}/{len(photo_files)}] {ph.name}: "
              f"{in_view.sum():,}/{len(verts):,} verts contributed "
              f"(avg frontality {frontality[in_view].mean():.2f})",
              file=sys.stderr)

    # ── Composite ───────────────────────────────────────────────────
    print(f"\ncomposite:", file=sys.stderr)
    print(f"  verts with any coverage: {(weight_sum > 0).sum():,} / {len(verts):,}",
          file=sys.stderr)
    safe_w = np.where(weight_sum > 1e-6, weight_sum, 1.0)
    final_col = (color_sum / safe_w[:, None]).clip(0, 255).astype(np.uint8)
    final_col[weight_sum < 1e-6] = 0
    weights_norm = np.minimum(255, weight_sum * 30).astype(np.uint8)

    np.save(OUT_COL, final_col)
    np.save(OUT_W, weights_norm)
    print(f"wrote {OUT_COL.name} and {OUT_W.name}", file=sys.stderr)


if __name__ == "__main__":
    main()
