"""Apple Calendar events for today, via AppleScript.

We avoid PyObjC + EventKit (which requires entitlement signing) by
shelling to `osascript`. This works as long as the user has granted
Terminal / Penelope access to Calendar (System Settings -> Privacy ->
Calendars).
"""

from __future__ import annotations

import datetime as dt
import subprocess
import time


_SCRIPT = r"""
set output to ""
set startD to (current date) - (time of (current date))
set endD to startD + (24 * 60 * 60)
tell application "Calendar"
    repeat with cal in calendars
        try
            set evs to (every event of cal whose start date >= startD and start date < endD)
            repeat with e in evs
                set t to (start date of e)
                set tStr to (time string of t)
                set sumStr to (summary of e)
                set locStr to ""
                try
                    set locStr to (location of e)
                end try
                set epoch to (do shell script "date -j -f \"%A, %B %e, %Y at %I:%M:%S %p\" " & quoted form of ((date string of t) & " at " & (time string of t)) & " +%s")
                set output to output & epoch & tab & tStr & tab & sumStr & tab & locStr & linefeed
            end repeat
        end try
    end repeat
end tell
return output
"""


def today_events():
    try:
        r = subprocess.run(["osascript", "-e", _SCRIPT],
                           capture_output=True, text=True, timeout=8)
        if r.returncode != 0: return []
    except Exception:
        return []
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3: continue
        try:
            ts = int(parts[0])
        except ValueError:
            ts = None
        out.append({
            "start_ts": ts,
            "time": _fmt_time(ts) if ts else parts[1],
            "title": parts[2],
            "where": parts[3] if len(parts) > 3 else "",
        })
    out.sort(key=lambda e: e.get("start_ts") or 0)
    return out


def _fmt_time(ts):
    return time.strftime("%I:%M %p", time.localtime(ts)).lstrip("0")
