"""Train custom OpenWakeWord models for 'Papi's home' and 'Hey Penelope'.

Uses synthetic TTS to generate hundreds of positive samples across many
voices, accents, and prosody settings. OWW's `train_custom_model` then
fits a small CNN that fires sub-200ms on detection.

Output:
    assets/wake_models/papis_home.onnx
    assets/wake_models/hey_penelope.onnx

Then hotword.py uses these as the middle tier (Porcupine → OpenWakeWord
→ Whisper polling fallback).

Run:
    python scripts/train_wake_words.py
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets" / "wake_models"
TRAIN_DIR = ROOT / "build" / "wake_train"


VOICES = [
    "en-US-AriaNeural", "en-US-JennyNeural", "en-US-AnaNeural",
    "en-US-MichelleNeural", "en-US-EmmaNeural", "en-US-AvaNeural",
    "en-US-GuyNeural", "en-US-DavisNeural", "en-US-EricNeural",
    "en-US-AndrewNeural", "en-US-BrianNeural", "en-US-RogerNeural",
    "en-GB-SoniaNeural", "en-GB-LibbyNeural", "en-GB-RyanNeural",
    "en-AU-NatashaNeural", "en-AU-WilliamNeural",
    "en-IE-EmilyNeural", "en-CA-LiamNeural",
]

PHRASES = {
    "papis_home": [
        "Papi's home",
        "Papis home",
        "Papi is home",
        "Hey, Papi's home",
        "Papi’s home",  # smart quote
    ],
    "hey_penelope": [
        "Hey Penelope",
        "Hi Penelope",
        "Hey Penny",
        "Hey Penelope, you there?",
        "Penelope hey",
    ],
}


async def synth(text: str, voice: str, rate: str, pitch: str, out: Path):
    import edge_tts
    out.parent.mkdir(parents=True, exist_ok=True)
    c = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await c.save(str(out))


async def gen_positives(label: str):
    label_dir = TRAIN_DIR / label / "positive"
    label_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    tasks = []
    for phrase in PHRASES[label]:
        for voice in VOICES:
            for rate in ("-15%", "+0%", "+15%"):
                for pitch in ("-3Hz", "+0Hz", "+3Hz"):
                    fn = label_dir / f"{n:04d}_{voice.replace('-','_')}.mp3"
                    n += 1
                    tasks.append(synth(phrase, voice, rate, pitch, fn))
    print(f"[{label}] synthesizing {len(tasks)} positive samples …", flush=True)
    # Chunk to avoid hammering edge-tts
    chunk = 10
    for i in range(0, len(tasks), chunk):
        await asyncio.gather(*tasks[i:i + chunk])
        if (i // chunk) % 5 == 0:
            print(f"  …{i + chunk}/{len(tasks)}", flush=True)
    print(f"[{label}] done. {n} samples in {label_dir}", flush=True)
    return n


def train_model(label: str):
    """Use OpenWakeWord's training script to fit a CNN on the synth set."""
    print(f"[{label}] training …", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # OWW provides a high-level helper; on macOS we use the `train` module
    # with our positive folder and OWW's bundled negative dataset.
    cmd = [
        sys.executable, "-m", "openwakeword.train",
        "--model-name", label,
        "--positive-directory", str(TRAIN_DIR / label / "positive"),
        "--output-directory", str(OUT_DIR),
    ]
    import subprocess
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 90)
    print(r.stdout[-2000:] if r.stdout else "(no stdout)")
    if r.returncode != 0:
        print("STDERR:", r.stderr[-2000:], flush=True)
        return False
    return True


async def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for label in PHRASES:
        await gen_positives(label)
    for label in PHRASES:
        ok = train_model(label)
        print(f"[{label}] train ok={ok}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
