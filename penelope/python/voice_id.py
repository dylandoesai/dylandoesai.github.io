"""Speaker verification — only respond when Dylan is the one talking.

Uses resemblyzer (Google's GE2E speaker embeddings, ~256-d float vectors).
Once enrolled with 3-5 short voice samples, every VAD utterance + hotword
trigger is gated on cosine similarity to the owner embedding. Strangers
saying "Papi's home" near the mic won't wake her.

Files:
    assets/owner_voice.npy      - averaged owner embedding (256-d float32)
    assets/owner_voice_meta.json - threshold + enrollment metadata

Module API:
    enroll(audio_paths_or_pcm)   -> dict   (saves to disk)
    is_owner(audio_pcm_16k)      -> (is_owner: bool, similarity: float)
    threshold()                  -> float
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
EMB_PATH = ASSETS / "owner_voice.npy"
META_PATH = ASSETS / "owner_voice_meta.json"
DEFAULT_THRESHOLD = 0.55  # cosine similarity. Dropped from 0.72 because
# Dylan's enrolled embedding came from a different recording session
# (the 75-min reference clip) than his MacBook Air built-in mic captures
# now — cross-recording-condition drift puts honest matches at ~0.55-0.65.
# 0.55 is still tighter than the resemblyzer paper's "different speaker"
# baseline of ~0.45 but loose enough that legitimate Dylan-speech clears.


_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        from resemblyzer import VoiceEncoder
        _encoder = VoiceEncoder("cpu")
    return _encoder


def _embed_pcm(pcm_f32_16k: np.ndarray) -> np.ndarray:
    """Embed a mono 16kHz float32 array."""
    from resemblyzer import preprocess_wav
    wav = preprocess_wav(pcm_f32_16k.astype(np.float32), source_sr=16000)
    return _get_encoder().embed_utterance(wav)


def _embed_file(path: str) -> np.ndarray:
    from resemblyzer import preprocess_wav
    wav = preprocess_wav(Path(path))
    return _get_encoder().embed_utterance(wav)


def enroll(samples) -> dict:
    """Average embeddings from N samples and save as the owner profile.

    samples: list of file paths OR list of np.float32 1D arrays at 16kHz.
    """
    if not samples:
        return {"ok": False, "reason": "no samples"}
    ASSETS.mkdir(parents=True, exist_ok=True)
    embs = []
    for s in samples:
        if isinstance(s, (str, Path)):
            embs.append(_embed_file(str(s)))
        elif isinstance(s, np.ndarray):
            embs.append(_embed_pcm(s))
    if not embs:
        return {"ok": False, "reason": "no usable samples"}
    avg = np.mean(np.stack(embs, axis=0), axis=0)
    # Normalize so cosine similarity is just dot product
    avg = avg / max(1e-9, np.linalg.norm(avg))
    np.save(EMB_PATH, avg.astype(np.float32))
    META_PATH.write_text(json.dumps({
        "enrolled_at": int(time.time()),
        "n_samples": len(embs),
        "threshold": DEFAULT_THRESHOLD,
        "encoder": "resemblyzer (GE2E, 256-d)",
    }, indent=2))
    return {"ok": True, "samples": len(embs), "path": str(EMB_PATH)}


def _load_owner():
    if not EMB_PATH.exists():
        return None
    try:
        return np.load(EMB_PATH).astype(np.float32)
    except Exception:
        return None


def threshold() -> float:
    if not META_PATH.exists():
        return DEFAULT_THRESHOLD
    try:
        return float(json.loads(META_PATH.read_text()).get("threshold",
                                                            DEFAULT_THRESHOLD))
    except Exception:
        return DEFAULT_THRESHOLD


def is_owner(pcm_f32_16k: np.ndarray) -> tuple[bool, float]:
    """Return (is_owner, cosine_similarity) for an audio clip.

    If no owner profile exists yet, returns (True, 0.0) — fail-open so
    Penelope is usable before enrollment. Caller can decide whether to
    enforce based on owner_enrolled()."""
    owner = _load_owner()
    if owner is None:
        return True, 0.0
    try:
        emb = _embed_pcm(pcm_f32_16k)
    except Exception:
        return False, 0.0
    emb = emb / max(1e-9, np.linalg.norm(emb))
    sim = float(np.dot(owner, emb))
    return sim >= threshold(), sim


def owner_enrolled() -> bool:
    return EMB_PATH.exists()
