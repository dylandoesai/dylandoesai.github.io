"""Local Whisper transcription via faster-whisper.

We lazy-load the model on first use. base.en is the sweet spot for speed
vs accuracy on Apple Silicon; bump to small.en for better accuracy if you
have power to spare (set in config.json -> stt_model).
"""

from __future__ import annotations

import asyncio

import numpy as np

_model = None
_model_lock = asyncio.Lock()


async def _get_model(name: str = "base.en"):
    global _model
    async with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(name, compute_type="int8")
        return _model


async def transcribe(pcm: np.ndarray) -> str:
    model = await _get_model()
    loop = asyncio.get_running_loop()
    def _run():
        segments, _ = model.transcribe(
            pcm, language="en", beam_size=2,
            vad_filter=False, condition_on_previous_text=False,
        )
        return " ".join(s.text for s in segments).strip()
    return await loop.run_in_executor(None, _run)
