"""Extract Penelope Cruz's actual 3D face geometry from reference photos.

Usage:
    python python/extract_face_mesh.py assets/reference/penelope.jpg \
        -o assets/face-mesh.json

The output JSON is an array of 468 [x, y, z] triplets in MediaPipe's
normalized image coordinates (x and y in 0..1, z is depth relative to
face width). The renderer (renderer/visualizer/face-landmarks.js) loads
this file at startup and uses the points as the anchor cloud for the
particle face. After this step, the particles literally form her face.

If you have multiple reference photos at different angles, pass them all
and we'll average the meshes (improves depth accuracy):

    python python/extract_face_mesh.py \
        assets/reference/penelope_front.jpg \
        assets/reference/penelope_three_quarter.jpg \
        -o assets/face-mesh.json

Personal-use note: This script processes images you provide. Penelope is
a private app for your personal use; redistributing the extracted
landmarks or any derivative likeness is not authorized by this tool.
"""

import argparse
import json
import sys
from pathlib import Path


def extract(image_path: Path):
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

    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        refine_landmarks=True,
        max_num_faces=1,
        min_detection_confidence=0.5,
    ) as fm:
        result = fm.process(rgb)
        if not result.multi_face_landmarks:
            raise SystemExit(f"no face detected in {image_path}")
        lm = result.multi_face_landmarks[0].landmark
        return [[p.x, p.y, p.z] for p in lm]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("-o", "--output", type=Path,
                    default=Path("assets/face-mesh.json"))
    args = ap.parse_args()

    meshes = []
    for p in args.images:
        print(f"extracting from {p}", file=sys.stderr)
        meshes.append(extract(p))

    # Average if multiple
    n = len(meshes[0])
    avg = [[0.0, 0.0, 0.0] for _ in range(n)]
    for m in meshes:
        if len(m) != n:
            print(f"  skipping (length mismatch: {len(m)} vs {n})",
                  file=sys.stderr)
            continue
        for i, p in enumerate(m):
            avg[i][0] += p[0]; avg[i][1] += p[1]; avg[i][2] += p[2]
    k = len(meshes)
    for i in range(n):
        avg[i][0] /= k; avg[i][1] /= k; avg[i][2] /= k

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(avg))
    print(f"wrote {n} landmarks to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
