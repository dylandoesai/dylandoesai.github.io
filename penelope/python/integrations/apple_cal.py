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


# EventKit-backed read — AppleScript hit 60s timeout across 12 calendars
# on Dylan's machine. EventKit returns the same data in <100ms.
_event_store = None
_event_store_lock = None


def _get_event_store():
    global _event_store, _event_store_lock
    if _event_store_lock is None:
        import threading
        _event_store_lock = threading.Lock()
    with _event_store_lock:
        if _event_store is not None:
            return _event_store
        try:
            import EventKit
            import Foundation
        except ImportError:
            return None
        s = EventKit.EKEventStore.alloc().init()
        done = [False]; ok = [False]

        def cb(granted, err):
            ok[0] = bool(granted); done[0] = True

        if hasattr(s, "requestFullAccessToEventsWithCompletion_"):
            s.requestFullAccessToEventsWithCompletion_(cb)
        else:
            # 0 = EKEntityTypeEvent
            s.requestAccessToEntityType_completion_(0, cb)
        loop = Foundation.NSRunLoop.currentRunLoop()
        deadline = time.time() + 10
        while not done[0] and time.time() < deadline:
            loop.runUntilDate_(
                Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.05))
        if not ok[0]:
            return None
        _event_store = s
        return _event_store


def today_events():
    s = _get_event_store()
    if s is None:
        return []
    import Foundation
    today = dt.date.today()
    start = dt.datetime.combine(today, dt.time.min).astimezone()
    end = start + dt.timedelta(days=1)
    ns_start = Foundation.NSDate.dateWithTimeIntervalSince1970_(start.timestamp())
    ns_end = Foundation.NSDate.dateWithTimeIntervalSince1970_(end.timestamp())
    pred = s.predicateForEventsWithStartDate_endDate_calendars_(
        ns_start, ns_end, None)
    events = s.eventsMatchingPredicate_(pred) or []
    out = []
    for e in events:
        cal_name = e.calendar().title() if e.calendar() else ""
        if cal_name in _SKIP_CALENDARS:
            continue
        sd = e.startDate()
        ts = int(sd.timeIntervalSince1970()) if sd else None
        tstr = time.strftime("%I:%M %p",
                             time.localtime(ts)).lstrip("0") if ts else ""
        out.append({
            "start_ts": ts,
            "time": tstr,
            "title": str(e.title() or ""),
            "where": str(e.location() or ""),
            "calendar": cal_name,
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
    """Create an event via AppleScript with an unambiguous date format.

    Uses 'M/D/YYYY at h:MM:SS AM/PM' — AppleScript's date() parser
    handles this reliably. (24-hour 'M/D/YYYY HH:MM' silently created
    all-day events on first push — bug fixed here.)"""
    if end is None:
        end = start + dt.timedelta(hours=1)
    safe_t = title.replace('"', '\\"').replace('\\', '\\\\')
    safe_l = (location or "").replace('"', '\\"').replace('\\', '\\\\')
    safe_n = (notes or "").replace('"', '\\"').replace('\\', '\\\\')
    safe_c = calendar.replace('"', '\\"')

    def fmt(d: dt.datetime) -> str:
        return d.strftime("%-m/%-d/%Y %-I:%M:%S %p")

    s_str = fmt(start)
    e_str = fmt(end)
    script = f'''
        tell application "Calendar"
            tell calendar "{safe_c}"
                set startD to date "{s_str}"
                set endD to date "{e_str}"
                make new event with properties {{summary:"{safe_t}", start date:startD, end date:endD, location:"{safe_l}", description:"{safe_n}"}}
            end tell
        end tell
    '''
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def _purge_calendar(calendar_name: str, days_window: int = 60) -> int:
    """Delete every event on `calendar_name` within ±days_window via
    AppleScript. EventKit write needs explicit Events permission that
    we don't reliably have; AppleScript Automation is already granted."""
    safe = calendar_name.replace('"', '\\"')
    script = f'''
        tell application "Calendar"
            tell calendar "{safe}"
                set N to count of events
                delete every event
                return N
            end tell
        end tell
    '''
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            try: return int(r.stdout.strip())
            except ValueError: return 0
    except Exception:
        pass
    return 0


def push_shift_schedule(cfg: dict, days_ahead: int = 30,
                        wipe_existing: bool = True) -> dict:
    """Push the next `days_ahead` work days from work_schedule.json into the
    Penelope · Work calendar — including shift events themselves AND the
    wake-up + leave-for-work events (5:00 AM/5:25 AM for days,
    5:00 PM/5:25 PM for nights).

    wipe_existing=True deletes existing Penelope · Work events first so
    re-runs always reflect the latest work_schedule.json + routine config.

    Uses EventKit for reliable date handling (AppleScript's `date "5/13/2026
    18:45"` parser silently created all-day events on the first push)."""
    import shift_state
    if not ensure_work_calendar():
        return {"ok": False, "reason": "could not create calendar"}
    if wipe_existing:
        _purge_calendar(WORK_CAL, days_window=max(days_ahead + 5, 60))

    ws = cfg.get("work_schedule") or {}
    times = ws.get("shift_times") or {
        "day":   {"start": "06:45", "end": "18:45"},
        "night": {"start": "18:45", "end": "06:45"},
    }
    routine = ws.get("routine") or {
        "wake_for_day":    "05:00",
        "leave_for_day":   "05:25",
        "wake_for_night":  "17:00",
        "leave_for_night": "17:25",
    }

    def hhmm(s: str) -> dt.time:
        h, m = s.split(":")
        return dt.time(int(h), int(m))

    today = dt.date.today()
    added = 0
    failed = 0
    for n in range(days_ahead):
        d = today + dt.timedelta(days=n)
        letter = shift_state.letter_for_date({"work_schedule": ws}, d)
        if letter not in ("D", "N"):
            continue
        kind = "day" if letter == "D" else "night"
        title = f"O-I Kalama — {'Day' if kind == 'day' else 'Night'} shift"

        start_t = hhmm(times[kind]["start"])
        end_t = hhmm(times[kind]["end"])
        start_dt = dt.datetime.combine(d, start_t)
        end_dt = dt.datetime.combine(
            d + (dt.timedelta(days=1) if kind == "night" else dt.timedelta()),
            end_t,
        )

        # 1. Shift event itself
        if create_event(title, start_dt, end_dt,
                        calendar=WORK_CAL,
                        location="O-I Kalama Glass Plant",
                        notes="Auto-created by Penelope from work_schedule.json"):
            added += 1
        else:
            failed += 1

        # 2. Wake-up event
        wake_t = hhmm(routine[f"wake_for_{kind}"])
        wake_dt = dt.datetime.combine(d, wake_t)
        if create_event(f"Wake up for {kind} shift", wake_dt,
                        wake_dt + dt.timedelta(minutes=15),
                        calendar=WORK_CAL,
                        notes="Penelope will start gently waking you up around now."):
            added += 1
        else:
            failed += 1

        # 3. Leave-for-work event
        leave_t = hhmm(routine[f"leave_for_{kind}"])
        leave_dt = dt.datetime.combine(d, leave_t)
        if create_event(f"Leave for {kind} shift", leave_dt,
                        leave_dt + dt.timedelta(minutes=10),
                        calendar=WORK_CAL,
                        notes="Penelope will nudge you out the door."):
            added += 1
        else:
            failed += 1

    return {"ok": True, "added": added, "failed": failed,
            "days_window": days_ahead}
