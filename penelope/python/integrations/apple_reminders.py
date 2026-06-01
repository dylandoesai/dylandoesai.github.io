"""Apple Reminders via EventKit (PyObjC, native — fast).

System Settings -> Privacy & Security -> Reminders -> grant access to
Terminal / Penelope. On first call EventKit also prompts via NSAlert.

Why EventKit instead of AppleScript:
  - Dylan has ~3,900 reminders. AppleScript `every reminder of l whose
    completed is false` iterates the whole list in process and hits the
    45s timeout reliably. EventKit returns the same set in ~100ms.

API:
  scheduled_today()      uncompleted with due date today
  upcoming(days=14)      uncompleted in next N days
  all_uncompleted()      every uncompleted (~3,900 cap)
  due_soon(window_s)     uncompleted due in next window seconds
  create(title, list_name=None, due=None)
  complete(title)
"""

from __future__ import annotations

import datetime as dt
import threading
import time


_store = None
_store_lock = threading.Lock()


def _get_store():
    global _store
    with _store_lock:
        if _store is not None:
            return _store
        try:
            import EventKit
            import Foundation
        except ImportError:
            return None
        s = EventKit.EKEventStore.alloc().init()
        done = [False]
        ok = [False]

        def cb(granted, err):
            ok[0] = bool(granted)
            done[0] = True

        if hasattr(s, "requestFullAccessToRemindersWithCompletion_"):
            s.requestFullAccessToRemindersWithCompletion_(cb)
        else:
            s.requestAccessToEntityType_completion_(1, cb)  # 1 = EKEntityTypeReminder

        loop = Foundation.NSRunLoop.currentRunLoop()
        deadline = time.time() + 10
        while not done[0] and time.time() < deadline:
            loop.runUntilDate_(
                Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.05))
        if not ok[0]:
            return None
        _store = s
        return _store


def _fetch_incomplete(start: dt.datetime | None = None,
                      end: dt.datetime | None = None):
    s = _get_store()
    if s is None:
        return []
    import Foundation
    ns_start = Foundation.NSDate.dateWithTimeIntervalSince1970_(
        start.timestamp()) if start else None
    ns_end = Foundation.NSDate.dateWithTimeIntervalSince1970_(
        end.timestamp()) if end else None
    pred = s.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
        ns_start, ns_end, None)
    out = []
    done = [False]

    def cb(arr):
        if arr is not None:
            out.extend(arr)
        done[0] = True

    s.fetchRemindersMatchingPredicate_completion_(pred, cb)
    loop = Foundation.NSRunLoop.currentRunLoop()
    deadline = time.time() + 8
    while not done[0] and time.time() < deadline:
        loop.runUntilDate_(
            Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.05))
    return out


def _shape(reminders, want_no_date: bool = False):
    out = []
    for r in reminders:
        title = r.title() or ""
        if not title:
            continue
        due = r.dueDateComponents()
        if due is None:
            if want_no_date:
                out.append({"due_key": "0", "title": str(title),
                            "list": r.calendar().title() if r.calendar() else ""})
            continue
        y = due.year() or 1970
        m = due.month() or 1
        d = due.day() or 1
        h = due.hour() if due.hour() != Foundation_NSDateComponentUndefined else 0
        mi = due.minute() if due.minute() != Foundation_NSDateComponentUndefined else 0
        out.append({
            "due_key": f"{y:04d}{m:02d}{d:02d}{h:02d}{mi:02d}",
            "title": str(title),
            "list": r.calendar().title() if r.calendar() else "",
        })
    return out


# Foundation defines NSDateComponentUndefined = LONG_MAX
try:
    import Foundation as _F
    Foundation_NSDateComponentUndefined = _F.NSDateComponentUndefined
except Exception:
    Foundation_NSDateComponentUndefined = 9223372036854775807


def scheduled_today():
    """Uncompleted reminders with a due date sometime today."""
    today = dt.date.today()
    start = dt.datetime.combine(today, dt.time.min).astimezone()
    end = start + dt.timedelta(days=1)
    rs = _fetch_incomplete(start, end)
    return _shape(rs)


def today():
    """Back-compat alias used by penelope_server.handle_daily_brief."""
    return scheduled_today()


def upcoming(days: int = 14):
    today_d = dt.date.today()
    start = dt.datetime.combine(today_d, dt.time.min).astimezone()
    end = start + dt.timedelta(days=days)
    return _shape(_fetch_incomplete(start, end))


def all_uncompleted(per_list: int = 0):
    """Every uncompleted reminder (with or without due date). Slow on huge
    lists because we have to iterate everything — use sparingly."""
    rs = _fetch_incomplete(None, None)  # all incomplete with any due date
    out = _shape(rs, want_no_date=True)
    # Also pull no-due-date items via separate predicate
    s = _get_store()
    if s is None:
        return out
    pred = s.predicateForRemindersInCalendars_(None)
    extra = []
    done = [False]

    def cb(arr):
        if arr is not None:
            extra.extend(arr)
        done[0] = True

    import Foundation
    s.fetchRemindersMatchingPredicate_completion_(pred, cb)
    loop = Foundation.NSRunLoop.currentRunLoop()
    deadline = time.time() + 8
    while not done[0] and time.time() < deadline:
        loop.runUntilDate_(
            Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.05))
    seen = {r["title"] for r in out}
    for r in extra:
        # Skip completed — try both PyObjC property accessor variants
        done_flag = False
        for attr in ("isCompleted", "completed"):
            if hasattr(r, attr):
                try:
                    done_flag = bool(getattr(r, attr)())
                    break
                except Exception:
                    pass
        if done_flag:
            continue
        title = str(r.title() or "")
        if not title or title in seen:
            continue
        if r.dueDateComponents() is not None:
            continue  # already in out
        seen.add(title)
        out.append({"due_key": "0", "title": title,
                    "list": r.calendar().title() if r.calendar() else ""})
    if per_list and per_list > 0:
        return out[:per_list]
    return out


def due_soon(window_s: int = 7200):
    now_ts = time.time()
    out = []
    for r in scheduled_today():
        k = r.get("due_key", "0")
        if k == "0":
            continue
        try:
            t = time.strptime(k[:12], "%Y%m%d%H%M")
            ts = time.mktime(t)
        except ValueError:
            continue
        if 0 < ts - now_ts <= window_s:
            out.append(r)
    return out


def create(title: str, list_name: str | None = None,
           due: dt.datetime | None = None) -> bool:
    s = _get_store()
    if s is None or not title:
        return False
    try:
        import EventKit
        import Foundation
    except ImportError:
        return False
    r = EventKit.EKReminder.reminderWithEventStore_(s)
    r.setTitle_(title)
    # pick the named calendar, else default
    target = None
    for c in s.calendarsForEntityType_(1):
        if list_name and c.title() == list_name:
            target = c
            break
    if target is None:
        target = s.defaultCalendarForNewReminders()
    r.setCalendar_(target)
    if due is not None:
        cal_unit_all = (
            (1 << 1) | (1 << 2) | (1 << 3)
            | (1 << 4) | (1 << 5))  # year/month/day/hour/minute
        comp = Foundation.NSCalendar.currentCalendar() \
            .components_fromDate_(cal_unit_all,
                                  Foundation.NSDate.dateWithTimeIntervalSince1970_(
                                      due.timestamp()))
        r.setDueDateComponents_(comp)
    err = [None]
    ok = s.saveReminder_commit_error_(r, True, err)
    return bool(ok)


def complete(title: str) -> bool:
    s = _get_store()
    if s is None or not title:
        return False
    target_title = title.strip().lower()
    rs = _fetch_incomplete(None, None)
    for r in rs:
        if str(r.title() or "").strip().lower() == target_title:
            r.setCompleted_(True)
            err = [None]
            s.saveReminder_commit_error_(r, True, err)
            return True
    return False
