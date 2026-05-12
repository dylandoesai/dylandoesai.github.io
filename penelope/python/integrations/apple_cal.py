"""Apple Calendar events for today + push Dylan's shift rotation as
events into a dedicated "Penelope · Work" calendar.

We avoid PyObjC + EventKit (which requires entitlement signing) by
shelling to `osascript`. This works as long as the user has granted
Terminal / Penelope access to Calendar (System Settings -> Privacy ->
Calendars).

Original implementation did `do shell script "date -j …"` per event,
which timed out on accounts with many calendars. This rewrite keeps
all date math inside AppleScript.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import time


# Skip the read-only / noisy calendars — they're huge and not actionable.
_SKIP_CALENDARS = {"Birthdays", "US Holidays", "Siri Suggestions"}


# Read every non-noise calendar's events in [today 00:00, today+1 00:00).
# All date formatting in AppleScript — no per-event shell-outs.
_SCRIPT_TODAY = r"""
set output to ""
set startD to (current date)
set time of startD to 0
set endD to startD + (24 * 60 * 60)
set skipList to {"Birthdays", "US Holidays", "Siri Suggestions"}
tell application "Calendar"
    repeat with cal in calendars
        set cn to name of cal
        if skipList does not contain cn then
            try
                set evs to (every event of cal whose start date is greater than or equal to startD and start date is less than endD)
                repeat with e in evs
                    set t to (start date of e)
                    set y to (year of t) as string
                    set m to text -2 thru -1 of ("0" & ((month of t) as integer))
                    set dd to text -2 thru -1 of ("0" & (day of t))
                    set hh to text -2 thru -1 of ("0" & (hours of t))
                    set mm to text -2 thru -1 of ("0" & (minutes of t))
                    set sortKey to y & m & dd & hh & mm
                    set summText to ""
                    try
                        set summText to (summary of e)
                    end try
                    set locText to ""
                    try
                        set locText to (location of e)
                    end try
                    set output to output & sortKey & tab & summText & tab & locText & tab & cn & linefeed
                end repeat
            end try
        end if
    end repeat
end tell
return output
"""


def today_events():
    try:
        r = subprocess.run(["osascript", "-e", _SCRIPT_TODAY],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return []
    except Exception:
        return []
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        sort_key = parts[0]
        title = parts[1]
        where = parts[2] if len(parts) > 2 else ""
        cal = parts[3] if len(parts) > 3 else ""
        try:
            t = time.strptime(sort_key[:12], "%Y%m%d%H%M")
            ts = int(time.mktime(t))
            tstr = time.strftime("%I:%M %p", t).lstrip("0")
        except ValueError:
            ts = None
            tstr = ""
        out.append({
            "start_ts": ts,
            "time": tstr,
            "title": title,
            "where": where,
            "calendar": cal,
        })
    out.sort(key=lambda e: e.get("start_ts") or 0)
    return out


# ----- Push shift schedule into Calendar ---------------------------------

WORK_CAL = "Penelope · Work"


def _osa(script: str, timeout: int = 25) -> tuple[int, str, str]:
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def ensure_work_calendar() -> bool:
    """Create the Penelope · Work calendar if missing. Returns True if it exists."""
    rc, out, err = _osa(f'''
        tell application "Calendar"
            set found to false
            repeat with c in calendars
                if name of c is "{WORK_CAL}" then set found to true
            end repeat
            if not found then
                make new calendar with properties {{name:"{WORK_CAL}"}}
            end if
            return "ok"
        end tell
    ''')
    return rc == 0


def create_event(title: str, start: dt.datetime, end: dt.datetime | None = None,
                 calendar: str = "Calendar", location: str = "",
                 notes: str = "") -> bool:
    """Create an event on the named calendar. Default calendar is 'Calendar'.
    end defaults to start + 1h if not provided."""
    if end is None:
        end = start + dt.timedelta(hours=1)
    safe_t = title.replace('"', '\\"')
    safe_l = location.replace('"', '\\"')
    safe_n = notes.replace('"', '\\"')
    safe_c = calendar.replace('"', '\\"')
    s = start.strftime("%m/%d/%Y %I:%M %p").lstrip("0")
    e = end.strftime("%m/%d/%Y %I:%M %p").lstrip("0")
    script = f'''
        tell application "Calendar"
            tell calendar "{safe_c}"
                make new event with properties {{summary:"{safe_t}", start date:date "{s}", end date:date "{e}", location:"{safe_l}", description:"{safe_n}"}}
            end tell
        end tell
    '''
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def push_shift_schedule(cfg: dict, days_ahead: int = 30) -> dict:
    """Push the next `days_ahead` work days from work_schedule.json into the
    Penelope · Work calendar. Idempotent: skips dates already on that
    calendar with a matching summary."""
    import shift_state  # avoid circular at top
    if not ensure_work_calendar():
        return {"ok": False, "reason": "could not create calendar"}

    ws = cfg.get("work_schedule") or {}
    times = ws.get("shift_times") or {
        "day":   {"start": "07:00", "end": "19:00"},
        "night": {"start": "19:00", "end": "07:00"},
    }

    today = dt.date.today()
    added = 0
    skipped = 0
    failed = 0
    for n in range(days_ahead):
        d = today + dt.timedelta(days=n)
        letter = shift_state.letter_for_date({"work_schedule": ws}, d)
        if letter not in ("D", "N"):
            continue
        kind = "day" if letter == "D" else "night"
        start = times[kind]["start"]
        end = times[kind]["end"]
        # Night shift ends the next morning
        end_offset = 1 if kind == "night" else 0
        end_date = d + dt.timedelta(days=end_offset)
        title = f"O-I Kalama — {'Day' if kind == 'day' else 'Night'} shift"

        date_str_start = f"{d.month}/{d.day}/{d.year} {start}"
        date_str_end = f"{end_date.month}/{end_date.day}/{end_date.year} {end}"

        # Skip if already there
        check_script = f'''
            tell application "Calendar"
                tell calendar "{WORK_CAL}"
                    set startD to date "{date_str_start}"
                    set endD to startD + (60 * 60)
                    set existing to (every event whose start date >= startD and start date < endD)
                    return (count of existing)
                end tell
            end tell
        '''
        rc, out, err = _osa(check_script, timeout=15)
        if rc == 0 and out.strip().isdigit() and int(out.strip()) > 0:
            skipped += 1
            continue

        create_script = f'''
            tell application "Calendar"
                tell calendar "{WORK_CAL}"
                    set startD to date "{date_str_start}"
                    set endD to date "{date_str_end}"
                    make new event with properties {{summary:"{title}", start date:startD, end date:endD, location:"O-I Kalama Glass Plant"}}
                end tell
            end tell
        '''
        rc, _, err = _osa(create_script, timeout=15)
        if rc == 0:
            added += 1
        else:
            failed += 1
    return {"ok": True, "added": added, "skipped": skipped, "failed": failed,
            "days_window": days_ahead}
