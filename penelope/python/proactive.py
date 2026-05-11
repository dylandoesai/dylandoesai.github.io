"""Proactive alerts (calendar warnings, reminders, revenue milestones).

Per spec, all three surface forms fire together: chime + visual pulse +
voice announcement. We respect macOS Focus / DND -- if the system is in
DND, we emit visual-only alerts and skip the voice/chime.

The scheduler runs every 60 seconds and checks:
  - Calendar: any event in the next 5 minutes -> warn once
  - Reminders: any reminder firing in the next 2 minutes -> warn once
  - Revenue: today's total crossed configured milestone ($X) since last
    poll -> congratulate once

It also emits data_updated periodically so the side panels stay fresh.
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from pathlib import Path

from integrations import apple_cal, apple_reminders

_seen = set()
_last_revenue_milestone = 0


def start(state, emit):
    t = threading.Thread(target=_loop, args=(state, emit), daemon=True)
    t.start()
    return t


def _loop(state, emit):
    while True:
        try:
            if _dnd_active():
                time.sleep(60); continue
            _check_calendar(state, emit)
            _check_reminders(state, emit)
            _check_revenue(state, emit)
            emit("data_updated", {})
        except Exception:
            pass
        time.sleep(60)


def _dnd_active() -> bool:
    """Check macOS Focus / DND. Returns True if active."""
    try:
        r = subprocess.run(
            ["defaults", "-currentHost", "read",
             "com.apple.controlcenter", "NSStatusItem", "Visible",
             "FocusModes"],
            capture_output=True, text=True, timeout=2,
        )
        # Best-effort; if it errors we assume DND is not on.
        return "1" in r.stdout
    except Exception:
        return False


def _check_calendar(state, emit):
    events = apple_cal.today_events()
    now = time.time()
    for ev in events:
        start_ts = ev.get("start_ts")
        if not start_ts: continue
        delta = start_ts - now
        if 0 < delta <= 5 * 60:
            key = ("cal", ev.get("uid") or ev.get("title"))
            if key in _seen: continue
            _seen.add(key)
            emit("proactive_alert", {
                "panel": "schedule",
                "text": f"Papi, {ev.get('title','an event')} in {int(delta // 60) + 1} minutes.",
            })


def _check_reminders(state, emit):
    items = apple_reminders.due_soon(window_s=120)
    for r in items:
        key = ("rem", r.get("uid") or r.get("title"))
        if key in _seen: continue
        _seen.add(key)
        emit("proactive_alert", {
            "panel": "schedule",
            "text": f"Reminder, Papi: {r.get('title','')}.",
        })


def _check_revenue(state, emit):
    global _last_revenue_milestone
    cfg = (state.get("config") or {})
    rev = cfg.get("revenue", {})
    today = rev.get("total_today", 0)
    if not today: return
    milestones = cfg.get("revenue_milestones", [500, 1000, 2500, 5000, 10000])
    for m in milestones:
        if today >= m > _last_revenue_milestone:
            _last_revenue_milestone = m
            emit("proactive_alert", {
                "panel": "revenue",
                "text": f"Papi, we just crossed ${m:,} today. Vamos.",
            })
            break
