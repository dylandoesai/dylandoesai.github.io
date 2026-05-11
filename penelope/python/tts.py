"""Edge TTS synthesis + viseme generation.

Per spec the voice is auditioned at first launch from:
  - Helena (es-VE) -- warm Latin Spanish
  - Elvira (es-ES) -- Spain Castilian
  - Jenny  (en-US) -- American English

The chosen voice is written to config.json -> tts_voice. We synthesize
to mp3, save to a temp file, and return a file:// URL the renderer can
play.

Visemes: edge-tts emits SSML word-boundary events with start/duration in
hectoseconds. We approximate visemes (open/wide pair) by mapping each
word's vowels: AH/AA -> open=0.9 wide=0.0, EE -> open=0.4 wide=1.0,
OO/UU -> open=0.5 wide=-1.0, etc. Plain-text approximation is
good enough for the cyber face; perceptual realism comes mostly from
the amplitude band already driving the jaw.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TTS_CACHE = ROOT / ".tts_cache"
TTS_CACHE.mkdir(exist_ok=True)

DEFAULT_VOICE = "es-VE-PaolaNeural"  # warm Latin Spanish; Edge equivalent of "Helena"

VOICE_ALIASES = {
    "helena": "es-VE-PaolaNeural",
    "elvira": "es-ES-ElviraNeural",
    "jenny":  "en-US-JennyNeural",
}


async def synthesize(text: str, config: dict):
    import edge_tts
    voice = VOICE_ALIASES.get((config.get("tts_voice") or "helena").lower(),
                              DEFAULT_VOICE)
    rate = config.get("tts_rate", "-8%")    # slow + warm per user spec
    pitch = config.get("tts_pitch", "-2Hz")
    out = TTS_CACHE / f"{uuid.uuid4().hex}.mp3"

    visemes = []
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    word_boundaries = []
    with open(out, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_boundaries.append(chunk)

    # Word -> approximate viseme stream
    for wb in word_boundaries:
        t = wb["offset"] / 10_000_000  # 100ns ticks -> seconds
        dur = wb["duration"] / 10_000_000
        word = (wb.get("text") or "").lower()
        open_v, wide_v = _word_to_viseme(word)
        visemes.append({"t": t, "open": open_v, "wide": wide_v})
        # close the mouth between words
        visemes.append({"t": t + dur * 0.95, "open": 0.05, "wide": 0.0})

    # Renderer reads via file:// URL
    return f"file://{out}", visemes


def _word_to_viseme(word: str) -> tuple[float, float]:
    if not word:
        return 0.0, 0.0
    vowels = [c for c in word if c in "aeiouy"]
    if not vowels:
        return 0.1, 0.0
    v = vowels[0]
    # crude vowel -> shape
    table = {
        "a": (0.9, 0.0),
        "e": (0.55, 0.9),
        "i": (0.4, 1.0),
        "o": (0.7, -0.9),
        "u": (0.45, -1.0),
        "y": (0.5, 0.5),
    }
    return table.get(v, (0.5, 0.0))


def cleanup_old(max_age_s: int = 600):
    now = time.time()
    for p in TTS_CACHE.glob("*.mp3"):
        try:
            if now - p.stat().st_mtime > max_age_s:
                p.unlink()
        except FileNotFoundError:
            pass
