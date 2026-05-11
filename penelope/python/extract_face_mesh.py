"""Extract Penelope Cruz's actual 3D face geometry from reference photos.

Usage:
    python python/extract_face_mesh.py assets/reference/penelope.jpg \
        -o assets/face-mesh.json

The output JSON is an array of [x, y, z] triplets in MediaPipe's normalized
image coordinates (x and y in 0..1, z is depth relative to face width). The
renderer (renderer/visualizer/face-landmarks.js) loads this file at startup
and uses the points as the anchor cloud for the particle face. After this
step, the particles literally form her face.

MediaPipe 0.10.x ships the new Tasks API; the legacy `mp.solutions.face_mesh`
module is gone. We use `mediapipe.tasks.python.vision.FaceLandmarker` and
auto-download Google's public `face_landmarker.task` model on first run.
Output count is 478 with iris (was 468 in legacy mode); renderer is
tolerant of either since it indexes by landmark id.

If you have multiple reference photos at different angles, pass them all
and we'll average the meshes (improves depth accuracy):

    python python/extract_face_mesh.py \
        assets/reference/penelope_front.jpg \
        assets/reference/penelope_three_quarter.jpg \
        -o assets/face-mesh.json

Personal-use note: This script processes images you provide. Penelope is a
private app for your personal use; redistributing the extracted landmarks
or any derivative likeness is not authorized by this tool.
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path


MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)


def ensure_model(model_path: Path) -> Path:
    if model_path.exists() and model_path.stat().st_size > 100_000:
        return model_path
    model_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading face_landmarker.task → {model_path}", file=sys.stderr)
    with urllib.request.urlopen(MODEL_URL, timeout=60) as r, \
            open(model_path, "wb") as f:
        f.write(r.read())
    return model_path


def make_landmarker(model_path: Path):
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision

    base = mp_tasks.BaseOptions(model_asset_path=str(model_path))
    opts = vision.FaceLandmarkerOptions(
        base_options=base,
        running_mode=vision.RunningMode.IMAGE,
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
    )
    return vision.FaceLandmarker.create_from_options(opts)


def extract(landmarker, image_path: Path):
    try:
        import cv2
        import mediapipe as mp
    except ImportError as e:
        print(f"missing dep: {e}\n  pip install opencv-python mediapipe",
              file=sys.stderr)
        sys.exit(1)

    img = cv2.imread(str(image_path))
    if img is None:
        raise SystemExit(f"could not read {image_path}")
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = landmarker.detect(image)
    if not result.face_landmarks:
        raise SystemExit(f"no face detected in {image_path}")
    lm = result.face_landmarks[0]
    return [[p.x, p.y, p.z] for p in lm]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("-o", "--output", type=Path,
                    default=Path("assets/face-mesh.json"))
    ap.add_argument("--model", type=Path,
                    default=Path("python/models/face_landmarker.task"),
                    help="Path to face_landmarker.task (auto-downloaded if missing)")
    args = ap.parse_args()

    model_path = ensure_model(args.model)
    landmarker = make_landmarker(model_path)

    meshes = []
    for p in args.images:
        if not p.is_file():
            print(f"skipping non-file: {p}", file=sys.stderr)
            continue
        print(f"extracting from {p}", file=sys.stderr)
        try:
            meshes.append(extract(landmarker, p))
        except SystemExit as e:
            print(f"  skipped: {e}", file=sys.stderr)

    if not meshes:
        raise SystemExit("no faces extracted from any reference photo")

    # Average across photos
    n = len(meshes[0])
    avg = [[0.0, 0.0, 0.0] for _ in range(n)]
    kept = 0
    for m in meshes:
        if len(m) != n:
            print(f"  skipping (length mismatch: {len(m)} vs {n})",
                  file=sys.stderr)
            continue
        kept += 1
        for i, p in enumerate(m):
            avg[i][0] += p[0]; avg[i][1] += p[1]; avg[i][2] += p[2]
    for i in range(n):
        avg[i][0] /= kept; avg[i][1] /= kept; avg[i][2] /= kept

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(avg))
    print(f"wrote {n} landmarks (averaged from {kept} photos) to {args.output}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
