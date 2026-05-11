"""Hotword detection.

Two wake phrases:
  - "Papi's home"   -> phrase="papis_home"   (full activation, song, brief)
  - "Hey Penelope"  -> phrase="hey_penelope" (quick wake, no song, no brief)

Two backends; the first one that works is used:

  1. Porcupine custom keywords (preferred).
     Requires:
       - config.json -> picovoice_access_key: "<your key>"
       - assets/papis_home_mac.ppn
       - assets/hey_penelope_mac.ppn
     Very low CPU; sub-200ms latency.

  2. Whisper-polled fallback (zero-config).
     Records 2-second sliding windows and runs them through faster-whisper.
     If the transcript contains either phrase (or close variants), fire.
     ~1-2s latency; works out of the box.

The chosen backend runs in a background thread and calls on_detect(phrase)
where phrase is "papis_home" or "hey_penelope".
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
    papi_ppn = ROOT / "assets" / "papis_home_mac.ppn"
    hey_ppn = ROOT / "assets" / "hey_penelope_mac.ppn"

    if key and papi_ppn.exists():
        try:
            paths = [str(papi_ppn)]
            labels = ["papis_home"]
            if hey_ppn.exists():
                paths.append(str(hey_ppn))
                labels.append("hey_penelope")
            _run_porcupine(key, paths, labels, on_detect)
            return
        except Exception as e:
            print(f"[hotword] porcupine failed, falling back: {e}",
                  file=sys.stderr)

    _run_whisper_fallback(on_detect)


# ----- Porcupine backend ---------------------------------------------------

def _run_porcupine(access_key: str, ppn_paths, labels, on_detect):
    import pvporcupine
    pp = pvporcupine.create(access_key=access_key, keyword_paths=ppn_paths)
    sr = pp.sample_rate
    frame_len = pp.frame_length

    with sd.RawInputStream(samplerate=sr, blocksize=frame_len,
                           channels=1, dtype="int16") as stream:
        while True:
            buf, _ = stream.read(frame_len)
            pcm = struct.unpack_from("h" * frame_len, buf)
            idx = pp.process(pcm)
            if idx >= 0 and idx < len(labels):
                on_detect(labels[idx])


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
            which = _match_wake(text)
            if which:
                on_detect(which)
                # cool-down so we don't re-fire on echo of the song
                time.sleep(15)
                buf[:] = 0


PAPI_VARIANTS = [
    "papi's home", "papis home", "papi is home", "papi home",
    "poppy's home", "poppi's home", "papa's home",
]
HEY_VARIANTS = [
    "hey penelope", "hi penelope", "hey penny", "hey penelopy",
    "okay penelope", "yo penelope",
]


def _match_wake(text: str):
    t = text.lower()
    if any(v in t for v in PAPI_VARIANTS): return "papis_home"
    if any(v in t for v in HEY_VARIANTS):  return "hey_penelope"
    return None
