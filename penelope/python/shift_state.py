"""Compute Dylan's current shift state from config/work_schedule.json.

Returns a dict like:

    {
      "shift": "day" | "night" | "off",
      "phase": "pre" | "mid" | "post" | "rest",
      "minutes_to_start": int | None,
      "minutes_into_shift": int | None,
      "today_letter": "D" | "N" | "O",
      "tomorrow_letter": "D" | "N" | "O",
      "greeting_key": "pre_day"|"mid_day"|"pre_night"|"mid_night"|"post_night"|"rest_day",
      "default_mode": "warm" | "flirty" | "professional",
    }

This is what brain.py drops into Penelope's per-turn context so she can
greet him appropriately and pick the right personality mode without
having to think about it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import config_loader

LETTER_TO_SHIFT = {"D": "day", "N": "night", "O": "off"}


def _hhmm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


def letter_for_date(cfg: dict, date: dt.date) -> str | None:
    """Letter for crew D on the given date. Calendar overrides win;
    otherwise we fall through to the 28-day pattern."""
    ws = cfg.get("work_schedule") or _load_ws()
    mode = ws.get("mode") or "pattern"

    # Calendar mode (or one-off override list in pattern mode): explicit
    # entries always win over the pattern.
    for entry in (ws.get("days") or []):
        if not isinstance(entry, dict):
            continue
        try:
            d = dt.date.fromisoformat(entry["date"])
        except (KeyError, ValueError):
            continue
        if d == date:
            return (entry.get("shift") or "O")[0].upper()
    if mode == "calendar":
        return None  # calendar-only mode and no entry => off by default

    # Pattern mode
    p = ws.get("pattern") or {}
    seq = p.get("sequence") or []
    anchor = p.get("anchor_date") or ""
    if not seq or not anchor:
        return None
    try:
        a = dt.date.fromisoformat(anchor)
    except ValueError:
        return None
    n = len(seq)
    diff = (date - a).days
    idx = diff % n
    return (seq[idx] or "O")[0].upper()


def _load_ws():
    import json
    p = Path(__file__).resolve().parent.parent / "config" / "work_schedule.json"
    if not p.exists(): return {}
    try: return json.loads(p.read_text())
    except Exception: return {}


def current(cfg: dict, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now()
    ws = cfg.get("work_schedule") or _load_ws()
    times = ws.get("shift_times") or {
        "day":   {"start": "06:00", "end": "18:00"},
        "night": {"start": "18:00", "end": "06:00"},
    }

    today = letter_for_date({"work_schedule": ws}, now.date()) or "O"
    tomorrow = letter_for_date({"work_schedule": ws},
                                now.date() + dt.timedelta(days=1)) or "O"
    yesterday = letter_for_date({"work_schedule": ws},
                                 now.date() - dt.timedelta(days=1)) or "O"

    out = {
        "today_letter": today,
        "tomorrow_letter": tomorrow,
        "yesterday_letter": yesterday,
        "shift": LETTER_TO_SHIFT.get(today, "off"),
    }

    def _spans(letter):
        if letter == "D":
            s = _hhmm(times["day"]["start"])
            e = _hhmm(times["day"]["end"])
            start = dt.datetime.combine(now.date(), s)
            end = dt.datetime.combine(now.date(), e)
            return start, end
        if letter == "N":
            s = _hhmm(times["night"]["start"])
            e = _hhmm(times["night"]["end"])
            start = dt.datetime.combine(now.date(), s)
            # night shift crosses midnight
            end = dt.datetime.combine(now.date() + dt.timedelta(days=1), e)
            return start, end
        return None, None

    start, end = _spans(today)
    out["phase"] = "rest"
    out["greeting_key"] = "rest_day"
    out["default_mode"] = "warm"
    out["minutes_to_start"] = None
    out["minutes_into_shift"] = None

    if today in ("D", "N") and start is not None:
        if now < start:
            out["phase"] = "pre"
            out["minutes_to_start"] = int((start - now).total_seconds() / 60)
            out["greeting_key"] = "pre_day" if today == "D" else "pre_night"
            out["default_mode"] = "warm"
        elif start <= now <= end:
            out["phase"] = "mid"
            out["minutes_into_shift"] = int((now - start).total_seconds() / 60)
            out["greeting_key"] = "mid_day" if today == "D" else "mid_night"
            out["default_mode"] = "professional"
        else:
            out["phase"] = "post"
            out["greeting_key"] = "post_night" if today == "N" else "rest_day"
            out["default_mode"] = "flirty" if today == "N" else "warm"
    elif yesterday == "N":
        # Came off a night shift this morning, today is "off"
        out["greeting_key"] = "post_night"
        out["default_mode"] = "flirty"

    return out
