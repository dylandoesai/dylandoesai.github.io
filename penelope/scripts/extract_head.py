"""Extract Penelope's full HEAD (face + hair) on white background.

For TripoSR-style 3D reconstruction we want a clean floating-head input:
  - Full head visible (hair on top, chin at bottom, ears on sides)
  - White background everywhere else (no shoulders, dress, scenery)
  - Tight crop with a little padding

Pipeline:
  1. MediaPipe face oval landmarks → tight face bounds
  2. Estimate head silhouette by expanding the face oval:
       - up by ~80% of face height (to capture hair)
       - sides by ~60% of face width (to capture hair flowing out)
       - down by ~15% (just under the chin/jaw, NOT into neck)
  3. Optional: use rembg with high alpha threshold to refine the
     silhouette so hair edges are accurate
  4. Composite onto white background, crop tight, save
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def extract_head(in_path: Path, out_path: Path, pad: int = 20):
    import mediapipe as mp
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision as mp_vision

    img_bgr = cv2.imread(str(in_path))
    if img_bgr is None:
        raise SystemExit(f"could not read {in_path}")
    H, W = img_bgr.shape[:2]
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

    fl_model = ROOT / "python" / "models" / "face_landmarker.task"
    base = mp_tasks.BaseOptions(model_asset_path=str(fl_model))
    opts = mp_vision.FaceLandmarkerOptions(
        base_options=base, running_mode=mp_vision.RunningMode.IMAGE,
        num_faces=1, min_face_detection_confidence=0.5,
    )
    landmarker = mp_vision.FaceLandmarker.create_from_options(opts)
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    res = landmarker.detect(mp_img)
    if not res.face_landmarks:
        raise SystemExit("no face detected")
    lm = res.face_landmarks[0]

    xs = np.array([p.x * W for p in lm], dtype=np.float32)
    ys = np.array([p.y * H for p in lm], dtype=np.float32)
    face_x0, face_x1 = xs.min(), xs.max()
    face_y0, face_y1 = ys.min(), ys.max()
    face_w = face_x1 - face_x0
    face_h = face_y1 - face_y0
    face_cx = (face_x0 + face_x1) / 2

    # Head bounding box — generous around the face but stops at the jaw
    head_x0 = max(0, int(face_cx - face_w * 0.95))
    head_x1 = min(W, int(face_cx + face_w * 0.95))
    head_y0 = max(0, int(face_y0 - face_h * 0.80))     # well above forehead → hair
    head_y1 = min(H, int(face_y1 + face_h * 0.15))     # just below chin → no neck

    print(f"head bbox: x=[{head_x0}, {head_x1}] y=[{head_y0}, {head_y1}] "
          f"({head_x1-head_x0}×{head_y1-head_y0} px)", file=sys.stderr)

    # ── REFINE silhouette via rembg ───────────────────────────────
    # rembg gives an accurate hair/skin alpha mask. We use the rembg
    # alpha INSIDE the head bbox; outside the bbox we force white.
    print("running rembg for hair silhouette refinement…", file=sys.stderr)
    from rembg import remove
    img_alpha = remove(img_bgr)   # BGRA result
    if img_alpha.shape[2] == 4:
        alpha = img_alpha[:, :, 3]
    else:
        alpha = np.full((H, W), 255, dtype=np.uint8)

    # Restrict alpha to the head bbox; outside bbox forced to 0 (white).
    bbox_mask = np.zeros((H, W), dtype=np.uint8)
    bbox_mask[head_y0:head_y1, head_x0:head_x1] = 255
    head_alpha = np.minimum(alpha, bbox_mask)

    # Composite onto WHITE
    a = head_alpha.astype(np.float32) / 255.0
    composite = (rgb.astype(np.float32) * a[:, :, None]
               + 255.0 * (1.0 - a[:, :, None])).astype(np.uint8)

    # Crop to head bbox + pad
    cx0 = max(0, head_x0 - pad)
    cy0 = max(0, head_y0 - pad)
    cx1 = min(W, head_x1 + pad)
    cy1 = min(H, head_y1 + pad)
    cropped = composite[cy0:cy1, cx0:cx1]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), cv2.cvtColor(cropped, cv2.COLOR_RGB2BGR))
    print(f"saved {cropped.shape[1]}×{cropped.shape[0]} head crop → {out_path}",
          file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    extract_head(args.input, args.output)


if __name__ == "__main__":
    main()
