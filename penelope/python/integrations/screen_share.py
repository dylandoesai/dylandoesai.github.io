"""Screen-mirroring / AirPlay control for Penelope.

Two paths to actually FIRE mirroring (macOS gates this behind Control
Center and you can't open it from a script in a single AppleScript
call reliably across OS versions):

  1. Shortcuts bridge (preferred — same pattern as HomeKit).
     Dylan creates one Shortcut per device named e.g.
       "Penelope: mirror to apple tv"
       "Penelope: mirror to hisense"
       "Penelope: stop mirroring"
     Each one uses Shortcuts' built-in "Set Screen Mirroring" action.
     We fire via the `shortcuts` CLI.

  2. Control-Center accessibility AppleScript fallback.
     Drives the menu bar Control Center → Screen Mirroring tile → row
     for the named device. Fragile across macOS versions but works
     when no Shortcut is configured.

Discovery uses dns-sd to enumerate `_airplay._tcp` services on the
local network. Firestick / Chromecast won't show up — they don't
speak native AirPlay; install AirReceiver on the Firestick to expose
it.

API:
  list_receivers()                     -> [str]   AirPlay names on net
  mirror_to(name_fragment)             -> bool    via Shortcut OR accessibility
  stop_mirroring()                     -> bool
"""

from __future__ import annotations

import subprocess
import time


# --- discovery --------------------------------------------------------------

def list_fire_tv_devices(timeout: float = 3.0) -> list[str]:
    """Discover Amazon Fire TV / Firestick devices on the LAN via
    _amzn-wplay._tcp (Whisperplay). They won't accept native AirPlay
    unless they have AirReceiver app installed and running — the
    standalone Whisperplay record means the device is reachable but
    needs AirReceiver to be a mirror target."""
    try:
        proc = subprocess.Popen(
            ["dns-sd", "-B", "_amzn-wplay._tcp", "local."],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except FileNotFoundError:
        return []
    time.sleep(timeout)
    try: proc.terminate()
    except Exception: pass
    try:
        out, _ = proc.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        try: out, _ = proc.communicate(timeout=1)
        except Exception: out = ""
    seen = set()
    for line in (out or "").splitlines():
        if " Add " in line and "_amzn-wplay._tcp" in line:
            parts = line.rstrip("\n").split("_amzn-wplay._tcp.", 1)
            if len(parts) == 2:
                name = parts[1].strip()
                if name:
                    seen.add(name)
    return sorted(seen)


def list_receivers(timeout: float = 3.0) -> list[str]:
    """Discover _airplay._tcp services on the LAN via dns-sd.

    dns-sd keeps stdout open forever — we let it run for `timeout` seconds,
    kill it, and parse whatever it printed. readline() in a loop would
    block on the last line (no EOF until the process dies)."""
    try:
        proc = subprocess.Popen(
            ["dns-sd", "-B", "_airplay._tcp", "local."],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except FileNotFoundError:
        return []
    time.sleep(timeout)
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        out, _ = proc.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            out, _ = proc.communicate(timeout=1)
        except Exception:
            out = ""
    seen = set()
    for line in (out or "").splitlines():
        if " Add " in line and "_airplay._tcp" in line:
            parts = line.rstrip("\n").split("_airplay._tcp.", 1)
            if len(parts) == 2:
                name = parts[1].strip()
                if name:
                    seen.add(name)
    own = _own_computer_name()
    return [n for n in sorted(seen) if own is None or own.lower() not in n.lower()]


def _own_computer_name() -> str | None:
    try:
        r = subprocess.run(["scutil", "--get", "ComputerName"],
                           capture_output=True, text=True, timeout=3)
        return r.stdout.strip() or None
    except Exception:
        return None


# --- shortcuts path ---------------------------------------------------------

SHORTCUT_PREFIX = "Penelope:"


def _list_penelope_shortcuts() -> list[str]:
    try:
        r = subprocess.run(["shortcuts", "list"],
                           capture_output=True, text=True, timeout=6)
    except Exception:
        return []
    return [ln.strip() for ln in r.stdout.splitlines()
            if ln.strip().startswith(SHORTCUT_PREFIX)]


def _run_shortcut(name: str) -> bool:
    try:
        r = subprocess.run(["shortcuts", "run", name],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


# --- accessibility fallback -------------------------------------------------

# Drive Control Center → Screen Mirroring → pick row by device name.
# macOS 14+ structure: menu bar extra "Control Center" → checkbox row
# "Screen Mirroring" → expands inline → list of rows for discovered
# receivers. We click by `name` UI element. Fragile to UI tweaks; the
# Shortcuts path is preferred.
_FALLBACK_TEMPLATE = r'''
tell application "System Events"
    tell process "Control Center"
        set frontmost to true
        try
            click menu bar item "Control Center" of menu bar 1
        end try
        delay 0.6
        try
            click (first UI element of window 1 whose description is "Screen Mirroring")
        on error
            try
                click (first checkbox of window 1 whose name contains "Screen Mirroring")
            end try
        end try
        delay 0.6
        set targetName to "%TARGET%"
        try
            click (first UI element of window 1 whose name contains targetName)
            return "ok"
        on error errMsg
            return "miss: " & errMsg
        end try
    end tell
end tell
'''


def _fallback_mirror(target_name: str) -> bool:
    script = _FALLBACK_TEMPLATE.replace("%TARGET%", target_name)
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and "ok" in r.stdout
    except Exception:
        return False


# --- top-level API ----------------------------------------------------------

def mirror_to(name_fragment: str) -> dict:
    """Start screen mirroring to the AirPlay receiver whose name contains
    `name_fragment` (case-insensitive). Tries Shortcuts first, falls back
    to Control Center accessibility."""
    frag = (name_fragment or "").strip()
    if not frag:
        return {"ok": False, "reason": "empty fragment"}

    # 1) Shortcuts
    shortcuts = _list_penelope_shortcuts()
    for sc in shortcuts:
        body = sc[len(SHORTCUT_PREFIX):].strip().lower()
        if "mirror" in body and frag.lower() in body:
            if _run_shortcut(sc):
                return {"ok": True, "method": "shortcut", "name": sc}

    # 2) Accessibility fallback — find best receiver match
    receivers = list_receivers()
    target = next((r for r in receivers if frag.lower() in r.lower()), None)
    if target is None:
        return {"ok": False, "reason": "no receiver match",
                "available": receivers,
                "shortcuts": shortcuts}
    ok = _fallback_mirror(target)
    return {"ok": ok, "method": "accessibility", "target": target}


def stop_mirroring() -> dict:
    """Disable screen mirroring."""
    shortcuts = _list_penelope_shortcuts()
    for sc in shortcuts:
        body = sc[len(SHORTCUT_PREFIX):].strip().lower()
        if "stop" in body and "mirror" in body:
            if _run_shortcut(sc):
                return {"ok": True, "method": "shortcut", "name": sc}
    # Fallback: re-open Control Center → click Screen Mirroring → click currently-active device to toggle off
    script = r'''
    tell application "System Events"
        tell process "Control Center"
            set frontmost to true
            try
                click menu bar item "Control Center" of menu bar 1
                delay 0.5
                click (first checkbox of window 1 whose name contains "Screen Mirroring")
                delay 0.4
                set toggles to (every UI element of window 1 whose name contains "Stop Mirroring")
                if (count of toggles) > 0 then click item 1 of toggles
                return "ok"
            end try
        end tell
    end tell
    '''
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=8)
        return {"ok": r.returncode == 0, "method": "accessibility"}
    except Exception:
        return {"ok": False, "reason": "exception"}
