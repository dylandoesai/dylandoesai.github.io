"""Multi-view texture compositor.

For each of the 25 reference photos:
  1. Reconstruct that photo's expressive mesh in canonical pose space
  2. Apply photo's pose (R, offset, roi_box) to project to image coords
  3. Sample per-vertex color from the photo at projected coords
  4. Compute per-vertex frontality = max(0, normal_z) — how directly
     that vertex faces the camera in this photo
  5. Build face-oval mask in image coords to drop background pixels

Then for each canonical vertex, combine all 25 photo-color samples by
frontality-weighted average. Result: a complete per-vertex texture
that covers the front and partial sides of Penelope's face from her
actual photos (not just a single front photo).

Output:
    assets/penelope_vertex_colors.npy   (N, 3) uint8 averaged colors
    assets/penelope_vertex_alpha.npy    (N,)   uint8 confidence (sum
                                                of frontality weights;
                                                0 = no photo covered
                                                this vertex from any
                                                angle)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

TDDFA_ROOT = Path("/tmp/3DDFA_V2")
sys.path.insert(0, str(TDDFA_ROOT))

PROJ_ROOT = Path(__file__).resolve().parent.parent
VERTS_FP  = PROJ_ROOT / "assets" / "penelope_3d_vertices.npy"
TRIS_FP   = PROJ_ROOT / "assets" / "penelope_3d_tri.npy"
PER_PHOTO = PROJ_ROOT / "assets" / "penelope_3d_per_photo"
REF_DIR   = PROJ_ROOT / "assets" / "reference"
OUT_COL   = PROJ_ROOT / "assets" / "penelope_vertex_colors.npy"
OUT_ALPHA = PROJ_ROOT / "assets" / "penelope_vertex_alpha.npy"


def compute_vertex_normals(verts, tris):
    """Per-vertex normals (averaged from adjacent triangle normals)."""
    N = len(verts)
    normals = np.zeros((N, 3), dtype=np.float32)
    # Triangle normals
    v0 = verts[tris[:, 0]]; v1 = verts[tris[:, 1]]; v2 = verts[tris[:, 2]]
    tri_normals = np.cross(v1 - v0, v2 - v0)
    # Normalize (some can be 0 for degenerate tris)
    lens = np.linalg.norm(tri_normals, axis=1, keepdims=True) + 1e-9
    tri_normals = tri_normals / lens
    # Accumulate to each vertex
    np.add.at(normals, tris[:, 0], tri_normals)
    np.add.at(normals, tris[:, 1], tri_normals)
    np.add.at(normals, tris[:, 2], tri_normals)
    # Normalize per-vertex
    lens = np.linalg.norm(normals, axis=1, keepdims=True) + 1e-9
    return normals / lens


def face_oval_mask(image, landmarker):
    """Return (H, W) uint8 mask from MediaPipe face oval."""
    import mediapipe as mp
    H, W = image.shape[:2]
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    res = landmarker.detect(mp_img)
    if not res.face_landmarks:
        return None
    lm = res.face_landmarks[0]
    OVAL_IDX = [
        10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
        397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
        172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
    ]
    pts = np.array([
        [int(lm[i].x * W), int(lm[i].y * H)] for i in OVAL_IDX
    ], dtype=np.int32)
    mask = np.zeros((H, W), dtype=np.uint8)
    cv2.fillPoly(mask, [pts], 255)
    mask = cv2.GaussianBlur(mask, (21, 21), 0)
    return mask


def main():
    print("=== multi-view texture compositor ===", file=sys.stderr)

    os.chdir(TDDFA_ROOT)
    os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'
    from bfm.bfm import BFMModel
    from utils.tddfa_util import similar_transform
    bfm = BFMModel("/tmp/3DDFA_V2/configs/bfm_noneck_v3.pkl",
                   shape_dim=40, exp_dim=10)
    os.chdir(PROJ_ROOT)
    n_vert = bfm.u.shape[0] // 3

    canonical = np.load(VERTS_FP).astype(np.float32)
    tris_raw = np.load(TRIS_FP)
    tris = tris_raw.T.astype(np.int32) if tris_raw.shape[0] == 3 else tris_raw.astype(np.int32)
    print(f"canonical: {canonical.shape}, tris: {tris.shape}", file=sys.stderr)

    # Per-vertex normals on canonical mesh
    normals_canonical = compute_vertex_normals(canonical, tris)

    # MediaPipe landmarker for masking
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision as mp_vision
    fl_model = PROJ_ROOT / "python" / "models" / "face_landmarker.task"
    base = mp_tasks.BaseOptions(model_asset_path=str(fl_model))
    opts = mp_vision.FaceLandmarkerOptions(
        base_options=base, running_mode=mp_vision.RunningMode.IMAGE,
        num_faces=1, min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
    )
    landmarker = mp_vision.FaceLandmarker.create_from_options(opts)

    # Accumulators
    col_sum = np.zeros((n_vert, 3), dtype=np.float64)
    weight_sum = np.zeros(n_vert, dtype=np.float64)

    npz_files = sorted(PER_PHOTO.glob("*.npz"))
    print(f"compositing {len(npz_files)} photos…", file=sys.stderr)
    for npz_path in npz_files:
        stem = npz_path.stem
        # Find matching reference photo
        photo_path = None
        for ext in (".JPG", ".jpg", ".WEBP", ".webp"):
            candidate = REF_DIR / f"{stem}{ext}"
            if candidate.exists():
                photo_path = candidate; break
        if photo_path is None:
            print(f"  no photo for {stem}", file=sys.stderr); continue

        params = np.load(npz_path)
        R = params["R"]
        offset_pp = params["offset"]
        alpha_shp = params["alpha_shp"]
        alpha_exp = params["alpha_exp"]
        roi_box = params["roi_box"]

        # Reconstruct THIS photo's expressive mesh (canonical pose)
        flat = bfm.u.flatten() + bfm.w_shp @ alpha_shp + bfm.w_exp @ alpha_exp
        a = flat.reshape(n_vert, 3)
        b = flat.reshape(3, n_vert).T
        photo_canonical = a if (a[:,1].max() - a[:,1].min()) > (b[:,1].max() - b[:,1].min()) else b

        # Project to image space via pose
        # R @ vertex.T + offset
        projected = (R @ photo_canonical.T + offset_pp.reshape(3, 1)).T   # (N, 3)
        pts2d = similar_transform(projected.T, roi_box, size=120)
        pts2d = np.asarray(pts2d).T   # (N, 3)

        # Load photo + mask
        img_bgr = cv2.imread(str(photo_path))
        H, W = img_bgr.shape[:2]
        mask = face_oval_mask(img_bgr, landmarker)
        if mask is None:
            print(f"  no face in {stem}", file=sys.stderr); continue
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

        # Per-vertex sample
        tx = np.clip(pts2d[:, 0], 0, W - 1).astype(np.int32)
        ty = np.clip(pts2d[:, 1], 0, H - 1).astype(np.int32)
        vert_colors = img_rgb[ty, tx]   # (N, 3) uint8

        # Mask alpha — drop vertices outside face oval
        mask_alpha = mask[ty, tx].astype(np.float32) / 255.0

        # Per-vertex frontality. 3DDFA's R is a SCALED rotation (det≈0
        # because it includes the pose scale factor), so we extract the
        # pure rotation by SVD-orthogonalizing R first.
        U, S, Vt = np.linalg.svd(R)
        R_rot = U @ Vt   # pure rotation, det=±1
        rotated_normals = (R_rot @ normals_canonical.T).T
        # BFM normals point OUT of the face (z=-1 in unrotated space for
        # front-facing verts). After rotation by R_rot, front-facing
        # vertices have negative rotated_z (camera looks down -Z in
        # BFM photo space). Take max(0, -z).
        frontality = np.maximum(0.0, -rotated_normals[:, 2])
        if frontality.max() < 0.1:
            # Sign convention flip — try the other direction
            frontality = np.maximum(0.0, rotated_normals[:, 2])

        # Combined weight per vertex
        w = (mask_alpha * frontality).astype(np.float64)

        col_sum += vert_colors.astype(np.float64) * w[:, None]
        weight_sum += w
        n_active = (w > 0.01).sum()
        print(f"  {stem}: {n_active:,}/{n_vert:,} verts contributed "
              f"(avg frontality {frontality.mean():.2f})", file=sys.stderr)

    # Compute final per-vertex colors
    final_alpha = np.minimum(255, (weight_sum * 60).astype(np.uint8))
    safe_w = np.where(weight_sum > 1e-6, weight_sum, 1.0)
    final_col = (col_sum / safe_w[:, None]).astype(np.uint8)
    final_col[weight_sum < 1e-6] = 0   # zero out uncovered verts

    print(f"\nfinal: {(weight_sum > 0.01).sum():,} / {n_vert:,} verts covered",
          file=sys.stderr)

    np.save(OUT_COL, final_col)
    np.save(OUT_ALPHA, final_alpha)
    print(f"wrote {OUT_COL.name} and {OUT_ALPHA.name}", file=sys.stderr)


if __name__ == "__main__":
    main()
