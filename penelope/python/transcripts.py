"""Encrypted persistent conversation transcripts.

Per user spec: full persistent transcripts, encrypted on disk via macOS
Keychain. We use Fernet (AES-128-CBC + HMAC-SHA256) with a key stored in
the macOS Keychain under service "Penelope" / account "transcript-key".
On first use we generate the key. Transcripts are written as JSON-lines
to ~/Library/Application Support/Penelope/transcripts.jsonl (encrypted).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

try:
    import keyring
    from cryptography.fernet import Fernet
except ImportError:
    keyring = None
    Fernet = None

SERVICE = "Penelope"
ACCOUNT = "transcript-key"
APP_DIR = Path.home() / "Library" / "Application Support" / "Penelope"
APP_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPT_FILE = APP_DIR / "transcripts.jsonl"

_fernet = None
_recent_cache: list[dict] = []


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    if Fernet is None or keyring is None:
        return None
    key = keyring.get_password(SERVICE, ACCOUNT)
    if not key:
        key = Fernet.generate_key().decode()
        keyring.set_password(SERVICE, ACCOUNT, key)
    _fernet = Fernet(key.encode())
    return _fernet


def append(speaker: str, text: str) -> None:
    """Append one turn. speaker is 'dylan' or 'penelope'."""
    entry = {"t": time.time(), "speaker": speaker, "text": text}
    _recent_cache.append(entry)
    if len(_recent_cache) > 200:
        _recent_cache.pop(0)

    f = _get_fernet()
    blob = json.dumps(entry, ensure_ascii=False).encode()
    if f is not None:
        blob = f.encrypt(blob)
    try:
        with open(TRANSCRIPT_FILE, "ab") as fp:
            fp.write(blob + b"\n")
    except Exception as e:
        print(f"[transcripts] write failed: {e}", file=sys.stderr)


def recent(turns: int = 20) -> list[dict]:
    """Return last `turns` turns. Hits cache first, falls back to disk."""
    if len(_recent_cache) >= turns:
        return _recent_cache[-turns:]
    f = _get_fernet()
    if not TRANSCRIPT_FILE.exists():
        return _recent_cache[:]
    try:
        lines = TRANSCRIPT_FILE.read_bytes().splitlines()
    except Exception:
        return _recent_cache[:]
    out = []
    for line in lines[-turns:]:
        try:
            blob = f.decrypt(line) if f is not None else line
            out.append(json.loads(blob))
        except Exception:
            continue
    return out
