"""Apple Reminders via AppleScript.

System Settings -> Privacy -> Reminders -> enable Terminal/Penelope.
"""

from __future__ import annotations

import subprocess
import time


_SCRIPT_TODAY = r"""
set output to ""
tell application "Reminders"
    set lst to {}
    set today to (current date)
    set todayEnd to today + (24 * 60 * 60)
    repeat with l in lists
        repeat with r in (reminders of l whose completed is false)
            try
                set d to due date of r
                if d is missing value then
                    set output to output & "0" & tab & (name of r) & linefeed
                else
                    set epoch to (do shell script "date -j -f \"%A, %B %e, %Y at %I:%M:%S %p\" " & quoted form of ((date string of d) & " at " & (time string of d)) & " +%s")
                    set output to output & epoch & tab & (name of r) & linefeed
                end if
            on error
                set output to output & "0" & tab & (name of r) & linefeed
            end try
        end repeat
    end repeat
end tell
return output
"""


def today():
    try:
        r = subprocess.run(["osascript", "-e", _SCRIPT_TODAY],
                           capture_output=True, text=True, timeout=8)
        if r.returncode != 0: return []
    except Exception:
        return []
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) < 2: continue
        try: ts = int(parts[0])
        except ValueError: ts = 0
        out.append({"due_ts": ts, "title": parts[1].strip()})
    return out


def due_soon(window_s: int = 120):
    now = time.time()
    return [r for r in today()
            if r["due_ts"] and 0 < r["due_ts"] - now <= window_s]
