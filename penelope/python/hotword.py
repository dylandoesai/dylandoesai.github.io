"""Hotword detection for "Papi's home".

Two backends; the first one that works is used:

  1. Porcupine custom keyword (preferred).
     Requires:
       - config.json -> picovoice_access_key: "<your key>"
       - assets/papis_home_mac.ppn  (download from console.picovoice.ai)
     Very low CPU; sub-200ms latency.

  2. Whisper-polled fallback (zero-config).
     Records 2-second sliding windows and runs them through faster-whisper.
     If the transcript contains "papi's home" (or close variants), fire.
     ~1-2s latency; works out of the box.

The chosen backend runs in a background thread and calls on_detect(phrase)
when the wake phrase is heard.
"""

from __future__ import annotations

import os
import struct
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(__file__).resolve().parent.parent


def run(state: dict, on_detect):
    cfg = state.get("config") or {}
    key = cfg.get("picovoice_access_key")
    ppn = ROOT / "assets" / "papis_home_mac.ppn"

    if key and ppn.exists():
        try:
            _run_porcupine(key, str(ppn), on_detect)
            return
        except Exception as e:
            print(f"[hotword] porcupine failed, falling back: {e}",
                  file=sys.stderr)

    _run_whisper_fallback(on_detect)


# ----- Porcupine backend ---------------------------------------------------

def _run_porcupine(access_key: str, ppn_path: str, on_detect):
    import pvporcupine
    pp = pvporcupine.create(access_key=access_key,
                            keyword_paths=[ppn_path])
    sr = pp.sample_rate
    frame_len = pp.frame_length

    with sd.RawInputStream(samplerate=sr, blocksize=frame_len,
                           channels=1, dtype="int16") as stream:
        while True:
            buf, _ = stream.read(frame_len)
            pcm = struct.unpack_from("h" * frame_len, buf)
            if pp.process(pcm) >= 0:
                on_detect("papi's home")


# ----- Whisper fallback ----------------------------------------------------

def _run_whisper_fallback(on_detect):
    from faster_whisper import WhisperModel
    model = WhisperModel("tiny.en", compute_type="int8")
    sr = 16000
    window = 2.0  # seconds
    step = 0.6    # seconds between checks
    buf = np.zeros(int(sr * window), dtype=np.float32)

    def cb(indata, *_):
        nonlocal buf
        block = indata[:, 0]
        buf = np.roll(buf, -len(block))
        buf[-len(block):] = block

    with sd.InputStream(samplerate=sr, channels=1, dtype="float32",
                        callback=cb, blocksize=int(sr * step)):
        last_check = 0
        while True:
            now = time.time()
            if now - last_check < step:
                time.sleep(0.05); continue
            last_check = now
            audio = buf.copy()
            # Quick energy gate to skip silence
            if float(np.abs(audio).mean()) < 0.004:
                continue
            try:
                segments, _ = model.transcribe(
                    audio, language="en", beam_size=1,
                    vad_filter=True, condition_on_previous_text=False)
                text = " ".join(seg.text for seg in segments).lower().strip()
            except Exception:
                continue
            if not text:
                continue
            if _matches_wake(text):
                on_detect(text)
                # cool-down so we don't re-fire on echo of the song
                time.sleep(15)
                buf[:] = 0


WAKE_VARIANTS = [
    "papi's home", "papis home", "papi is home", "papi home",
    "poppy's home", "poppi's home",
]


def _matches_wake(text: str) -> bool:
    t = text.lower()
    return any(v in t for v in WAKE_VARIANTS)
