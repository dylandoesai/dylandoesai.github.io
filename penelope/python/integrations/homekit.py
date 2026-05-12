"""HomeKit scaffolding via the Shortcuts app + JXA.

Apple does not expose HomeKit to AppleScript directly. The reliable
end-around is the Shortcuts app, which has built-in HomeKit actions
that fire `Run Home Scene` / `Control My Home`. We invoke shortcuts
that Dylan creates per accessory, and we shell out to the `shortcuts`
CLI which has been on macOS since 12.0.

Setup Dylan needs to do once (one-time, in the Shortcuts app):
  - Make a shortcut per scene/accessory he wants Penelope to control.
    Name them with the prefix "Penelope:", e.g. "Penelope: bedroom off",
    "Penelope: movie mode", "Penelope: porch lights on".
  - That's it — they auto-appear here.

API:
  list_scenes()                      -> [shortcut_name, ...]
  run(shortcut_name)                 -> bool
  run_scene(name_fragment)           -> bool   # fuzzy match within Penelope: prefix
"""

from __future__ import annotations

import subprocess


PREFIX = "Penelope:"


def _shortcuts_cli_available() -> bool:
    try:
        r = subprocess.run(["which", "shortcuts"],
                           capture_output=True, text=True, timeout=4)
        return r.returncode == 0
    except Exception:
        return False


def list_scenes():
    """Returns the names of every Shortcut beginning with the `Penelope:` prefix."""
    if not _shortcuts_cli_available():
        return []
    try:
        r = subprocess.run(["shortcuts", "list"],
                           capture_output=True, text=True, timeout=8)
    except Exception:
        return []
    out = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith(PREFIX):
            out.append(line)
    return out


def run(shortcut_name: str) -> bool:
    """Fire the named shortcut. Name must match exactly (case-insensitive)."""
    if not _shortcuts_cli_available():
        return False
    try:
        r = subprocess.run(["shortcuts", "run", shortcut_name],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


def run_scene(fragment: str) -> bool:
    """Fuzzy-match a fragment against Penelope: shortcuts and fire the first hit."""
    frag = (fragment or "").strip().lower()
    if not frag:
        return False
    for name in list_scenes():
        rest = name[len(PREFIX):].strip().lower()
        if frag in rest:
            return run(name)
    return False
