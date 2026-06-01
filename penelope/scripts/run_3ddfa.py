"""3DDFA_V2 multi-photo identity reconstruction.

Run 3DDFA on each of the 25 reference photos. For each photo we get
62-d params (12 pose + 40 shape + 10 expression). We:

  1. Extract just the SHAPE coefficients per photo (identity).
  2. Average them across the 25 photos → identity-stable Penelope.
  3. Reconstruct the mesh from average shape + zero expression +
     frontal pose. This gives a canonical-pose 3D head of HER face
     (no pose-induced distortion, no expression-induced distortion).
  4. Save the canonical mesh + BFM triangulation.

Output:
    assets/penelope_3d_vertices.npy   averaged identity mesh (38365, 3)
    assets/penelope_3d_tri.npy        BFM triangulation (3, 76073)
    assets/penelope_3d_shape.npy      averaged shape coefficients (40,)
    assets/penelope_3d_per_photo/<name>.npz    per-photo params (for texture step)
"""

from __future__ import annotations

import json
import os
import pickle
import sys
from pathlib import Path

import cv2
import numpy as np

TDDFA_ROOT = Path("/tmp/3DDFA_V2")
sys.path.insert(0, str(TDDFA_ROOT))

PROJ_ROOT = Path(__file__).resolve().parent.parent
PHOTOS = sorted(list((PROJ_ROOT / "assets" / "reference").glob("IMG_*.JPG"))
              + list((PROJ_ROOT / "assets" / "reference").glob("IMG_*.WEBP")))
OUT_VERTS  = PROJ_ROOT / "assets" / "penelope_3d_vertices.npy"
OUT_TRI    = PROJ_ROOT / "assets" / "penelope_3d_tri.npy"
OUT_SHAPE  = PROJ_ROOT / "assets" / "penelope_3d_shape.npy"
PER_PHOTO  = PROJ_ROOT / "assets" / "penelope_3d_per_photo"


def mediapipe_face_bbox(image_path: Path, landmarker):
    import mediapipe as mp
    img = cv2.imread(str(image_path))
    if img is None:
        return None, None
    H, W = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    res = landmarker.detect(mp_img)
    if not res.face_landmarks:
        return None, None
    lm = res.face_landmarks[0]
    xs = [p.x * W for p in lm]; ys = [p.y * H for p in lm]
    l, t = int(min(xs)), int(min(ys))
    r, b = int(max(xs)), int(max(ys))
    w = r - l; h = b - t
    pad = max(w, h) * 0.18
    bbox = (max(0, int(l - pad)), max(0, int(t - pad)),
            min(W, int(r + pad)), min(H, int(b + pad)))
    return bbox, img


def main():
    print("=== 3DDFA identity-stable reconstruction ===", file=sys.stderr)
    PER_PHOTO.mkdir(exist_ok=True)

    # ── load TDDFA ──────────────────────────────────────────
    os.chdir(TDDFA_ROOT)
    os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'
    import yaml
    cfg = yaml.load(open(TDDFA_ROOT / "configs" / "mb1_120x120.yml"),
                    Loader=yaml.SafeLoader)
    from TDDFA_ONNX import TDDFA_ONNX
    from utils.tddfa_util import _parse_param, similar_transform
    tddfa = TDDFA_ONNX(**cfg)
    os.chdir(PROJ_ROOT)

    # The TDDFA exposes only the SPARSE 68-landmark bases via tddfa.u_base
    # etc. For dense (38365-vertex) reconstruction, load the BFM model
    # directly and grab the dense bases.
    from bfm.bfm import BFMModel
    bfm = BFMModel(str(TDDFA_ROOT / "configs" / "bfm_noneck_v3.pkl"),
                   shape_dim=40, exp_dim=10)
    u_dense     = bfm.u            # (3*N,) mean shape
    w_shp_dense = bfm.w_shp        # (3*N, 40) shape basis
    w_exp_dense = bfm.w_exp        # (3*N, 10) expression basis
    n_vert = u_dense.shape[0] // 3
    print(f"BFM dense: {n_vert} vertices, shape_basis {w_shp_dense.shape[1]}d",
          file=sys.stderr)

    # ── mediapipe landmarker for bboxes ────────────────────
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

    # ── process each photo: extract shape coeffs ────────────
    shape_coeffs = []
    photo_meta = []
    for p in PHOTOS:
        bbox, img = mediapipe_face_bbox(p, landmarker)
        if bbox is None:
            print(f"  no face: {p.name}", file=sys.stderr); continue
        boxes = [[bbox[0], bbox[1], bbox[2], bbox[3], 1.0]]
        param_lst, roi_box_lst = tddfa(img, boxes)
        param = param_lst[0]   # (62,)
        R, offset, alpha_shp, alpha_exp = _parse_param(param)
        shape_coeffs.append(alpha_shp.flatten())
        np.savez(PER_PHOTO / f"{p.stem}.npz",
                 param=param, roi_box=np.array(roi_box_lst[0]),
                 alpha_shp=alpha_shp.flatten(),
                 alpha_exp=alpha_exp.flatten(),
                 R=R, offset=offset.flatten())
        print(f"  {p.name}: shape_norm={np.linalg.norm(alpha_shp):.2f} "
              f"exp_norm={np.linalg.norm(alpha_exp):.2f}",
              file=sys.stderr)

    if not shape_coeffs:
        raise SystemExit("no faces extracted")

    shape_arr = np.stack(shape_coeffs, axis=0)
    print(f"\nshape coeffs: {shape_arr.shape}", file=sys.stderr)

    # ── DROP OUTLIERS via robust averaging ────────────────────
    # Per-coefficient median rather than mean — protects against
    # one weird-pose photo dragging the identity off.
    avg_shape = np.median(shape_arr, axis=0)
    print(f"avg shape coeffs (median): norm={np.linalg.norm(avg_shape):.2f}",
          file=sys.stderr)

    # ── reconstruct CANONICAL DENSE mesh ───────────────────
    # mesh = u_dense + w_shp_dense @ avg_shape + 0 (no expression)
    # u_dense layout: x0,y0,z0,x1,y1,z1,... (per-vertex interleaved)
    flat = u_dense.flatten() + w_shp_dense @ avg_shape
    # Try both layouts and pick the sensible one
    v_interleaved = flat.reshape(n_vert, 3)
    v_planar = flat.reshape(3, n_vert).T
    y_spread_i = v_interleaved[:, 1].max() - v_interleaved[:, 1].min()
    y_spread_p = v_planar[:, 1].max() - v_planar[:, 1].min()
    canonical = v_interleaved if y_spread_i > y_spread_p else v_planar
    print(f"canonical mesh: {canonical.shape}", file=sys.stderr)
    print(f"  x={canonical[:,0].min():.1f}..{canonical[:,0].max():.1f} "
          f"y={canonical[:,1].min():.1f}..{canonical[:,1].max():.1f} "
          f"z={canonical[:,2].min():.1f}..{canonical[:,2].max():.1f}",
          file=sys.stderr)

    # Triangulation
    tri = tddfa.tri    # (3, 76073)
    print(f"triangulation: {tri.shape}", file=sys.stderr)

    np.save(OUT_VERTS, canonical)
    np.save(OUT_TRI, tri)
    np.save(OUT_SHAPE, avg_shape)
    print(f"wrote {OUT_VERTS.name} ({canonical.shape[0]} verts in canonical frontal pose)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
