"""Enroll Dylan's voice so Penelope only wakes for him.

Two usage modes:

  Live recording (recommended — uses the default mic):
      python python/enroll_voice.py --record 5

      Records 5 separate ~4s clips. Speak naturally each time —
      "Papi's home", "Hey Penelope", a sentence, etc. The averaged
      embedding goes to assets/owner_voice.npy.

  From existing audio files:
      python python/enroll_voice.py path/to/clip1.wav path/to/clip2.wav

After enrollment, hotword.py and vad_listener.py will gate on
cosine-similarity > 0.72 before reacting.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

import voice_id


def record_clip(seconds: float = 4.0, sr: int = 16000) -> np.ndarray:
    import sounddevice as sd
    print(f"  → speak for {seconds}s starting in 1.5s …", file=sys.stderr, flush=True)
    time.sleep(1.5)
    print("  → REC", file=sys.stderr, flush=True)
    data = sd.rec(int(seconds * sr), samplerate=sr, channels=1, dtype="float32")
    sd.wait()
    print("  → stop", file=sys.stderr, flush=True)
    return data.flatten()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("samples", nargs="*", help="WAV/M4A clips of Dylan speaking")
    ap.add_argument("--record", type=int, default=0,
                    help="Record N clips live (~4s each) instead of using files")
    ap.add_argument("--seconds", type=float, default=4.0,
                    help="Seconds per live clip (default 4)")
    args = ap.parse_args()

    samples: list = []
    if args.record > 0:
        print(f"Live enrollment: {args.record} clips × {args.seconds}s each.",
              file=sys.stderr)
        print("Speak naturally — vary phrases. Each clip gets a 1.5s countdown.",
              file=sys.stderr)
        for i in range(args.record):
            print(f"\nClip {i+1}/{args.record}", file=sys.stderr)
            samples.append(record_clip(seconds=args.seconds))
    if args.samples:
        samples.extend(args.samples)

    if not samples:
        print("no samples — pass file paths or --record N", file=sys.stderr)
        sys.exit(1)

    result = voice_id.enroll(samples)
    print(result)
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
