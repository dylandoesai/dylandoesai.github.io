"""Face recognition + presence detection via the always-on webcam.

Per user spec: webcam always on, trained from a photo folder.

Setup:
  1. Put 5-20 photos of yourself in penelope/assets/owner_faces/
     (any filename, jpg or png).
  2. On first run, this module computes embeddings for each photo and
     caches them at .penelope/owner_embeddings.npy.
  3. The webcam loop runs at ~3 fps. When a face is detected and matches
     the owner, on_seen() fires (debounced once per 30 min).

This is intentionally lightweight; it does NOT do mood detection in v1
(can be added by training a tiny CNN on FER+ or similar). It tells
Penelope two things: "is anyone in front of the Mac" and "is it Dylan".

If face_recognition or opencv isn't installed, we no-op gracefully.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER_DIR = ROOT / "assets" / "owner_faces"
CACHE = ROOT / ".penelope_owner_embeddings.npy"

SEEN_COOLDOWN_S = 30 * 60  # fire on_seen at most once every 30 min


def start(state: dict, on_seen=None):
    t = threading.Thread(target=_loop, args=(state, on_seen), daemon=True)
    t.start()
    return t


def _loop(state, on_seen):
    try:
        import cv2
        import numpy as np
        import face_recognition
    except Exception as e:
        print(f"[face_recog] disabled: {e}", file=sys.stderr)
        return

    owner_enc = _load_or_build_owner_embeddings()
    if owner_enc is None or len(owner_enc) == 0:
        print(f"[face_recog] no owner photos in {OWNER_DIR} -- presence only",
              file=sys.stderr)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[face_recog] could not open webcam", file=sys.stderr)
        return

    last_fired = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.5); continue
        small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        try:
            locs = face_recognition.face_locations(rgb)
        except Exception:
            locs = []
        if not locs:
            time.sleep(0.4); continue

        is_owner = True
        if owner_enc is not None and len(owner_enc):
            try:
                enc = face_recognition.face_encodings(rgb, locs)
            except Exception:
                enc = []
            is_owner = any(
                face_recognition.compare_faces(owner_enc, e, tolerance=0.55).count(True) > 0
                for e in enc
            )

        state["face_present"] = True
        state["face_is_owner"] = bool(is_owner)
        now = time.time()
        if is_owner and on_seen and (now - last_fired) > SEEN_COOLDOWN_S:
            last_fired = now
            try: on_seen()
            except Exception: pass
        time.sleep(0.35)


def _load_or_build_owner_embeddings():
    try:
        import numpy as np
        import face_recognition
    except Exception:
        return None
    if CACHE.exists():
        try: return np.load(CACHE, allow_pickle=True)
        except Exception: pass
    if not OWNER_DIR.exists():
        return None
    encs = []
    for p in OWNER_DIR.iterdir():
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png"): continue
        try:
            img = face_recognition.load_image_file(str(p))
            e = face_recognition.face_encodings(img)
            if e: encs.append(e[0])
        except Exception as ex:
            print(f"[face_recog] skip {p.name}: {ex}", file=sys.stderr)
    if not encs:
        return None
    import numpy as np
    arr = np.array(encs)
    try: np.save(CACHE, arr)
    except Exception: pass
    return arr
