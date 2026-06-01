"""Place a call from the Mac via FaceTime / Continuity (your iPhone).

On macOS, `tel:` and `facetime-audio:` URLs trigger a call through your
paired iPhone (Continuity must be enabled in System Settings -> General
-> AirDrop & Handoff -> Continuity).

API:
  call(number, audio_only=True) -> bool
"""

from __future__ import annotations

import subprocess


def _normalize(num: str) -> str:
    # Strip everything except digits and a leading +
    out = []
    for i, ch in enumerate(num):
        if ch == '+' and i == 0:
            out.append(ch)
        elif ch.isdigit():
            out.append(ch)
    return ''.join(out)


def call(number: str, audio_only: bool = True) -> bool:
    n = _normalize(number)
    if not n:
        return False
    scheme = "facetime-audio" if audio_only else "facetime"
    # Fallback: use `tel:` (carrier voice call through paired iPhone).
    # FaceTime-audio is iMessage/FT only; tel works for any number.
    url = f"tel:{n}"
    try:
        r = subprocess.run(["open", url],
                           capture_output=True, text=True, timeout=8)
        return r.returncode == 0
    except Exception:
        return False
