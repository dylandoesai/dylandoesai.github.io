"""Always-on Voice Activity Detection.

We use webrtcvad on 30 ms / 16 kHz frames. Speech frames are buffered;
after 800 ms of trailing silence (or 12 s of total audio) the buffer is
returned as a float32 numpy array ready for Whisper.

Barge-in: if state["speaking"] is True when we see fresh speech, we
emit an internal signal so the TTS player can cut off. The renderer
handles the actual cutoff (it owns the audio element); we simply stop
buffering until speaking goes False.
"""

from __future__ import annotations

import asyncio
import collections

import numpy as np
import sounddevice as sd
import webrtcvad

SR = 16000
FRAME_MS = 30
FRAME_LEN = int(SR * FRAME_MS / 1000)   # 480 samples
SILENCE_TAIL_MS = 800
MAX_UTTERANCE_S = 12

_vad = webrtcvad.Vad(2)  # 0..3, higher = more aggressive


async def next_utterance(state):
    """Block until a complete utterance is captured. Returns float32 np array."""
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def callback(indata, frames, _t, _s):
        loop.call_soon_threadsafe(q.put_nowait, bytes(indata))

    stream = sd.RawInputStream(samplerate=SR, blocksize=FRAME_LEN,
                                channels=1, dtype="int16",
                                callback=callback)
    stream.start()
    try:
        buffer = bytearray()
        silence_ms = 0
        in_speech = False
        elapsed_ms = 0
        while True:
            chunk = await q.get()
            elapsed_ms += FRAME_MS
            try:
                is_speech = _vad.is_speech(chunk, SR)
            except Exception:
                is_speech = False
            if is_speech:
                if not in_speech and state.get("speaking"):
                    # barge-in: tell renderer to stop TTS via state flag.
                    # The python side simply absorbs the next utterance.
                    state["speaking"] = False
                in_speech = True
                buffer.extend(chunk)
                silence_ms = 0
            else:
                if in_speech:
                    buffer.extend(chunk)
                    silence_ms += FRAME_MS
                    if silence_ms >= SILENCE_TAIL_MS:
                        break
                # else: idle silence; drop
            if elapsed_ms >= MAX_UTTERANCE_S * 1000 and in_speech:
                break
            if not state.get("active", True):
                return None
    finally:
        stream.stop()
        stream.close()

    if not buffer:
        return None
    pcm = np.frombuffer(buffer, dtype=np.int16).astype(np.float32) / 32768.0
    return pcm
