"""Apple Weather widget read — pull current conditions from the Weather app.

The Apple Weather app exposes its data via AppleScript. We use the user's
primary configured location (the first one in the Weather sidebar).

API:
  current() -> {temperature_f, condition, humidity, feels_like_f,
                wind_mph, location} | None
"""

from __future__ import annotations

import re
import subprocess


_SCRIPT = r'''
tell application "Weather"
    activate
end tell
delay 0.6
tell application "System Events"
    tell process "Weather"
        try
            set windowDesc to description of window 1
        on error
            set windowDesc to ""
        end try
        try
            set buttonNames to name of every button of window 1
        on error
            set buttonNames to {}
        end try
        return windowDesc & linefeed & (buttonNames as string)
    end tell
end tell
'''


def current():
    """Best-effort current conditions. Returns None if Weather isn't
    available or AX permissions weren't granted. The shape is intentionally
    sparse — we lean on Open-Meteo for structured data and use Apple
    Weather as a "what's the system showing right now" cross-check."""
    try:
        r = subprocess.run(["osascript", "-e", _SCRIPT],
                           capture_output=True, text=True, timeout=8)
        text = r.stdout
    except Exception:
        return None
    if not text:
        return None
    # Parse temperature like "72°" / "72°F"
    temp = None
    m = re.search(r"(-?\d+)\s*°", text)
    if m:
        temp = int(m.group(1))
    # Condition keywords
    cond = None
    for k in ("Sunny", "Clear", "Cloudy", "Partly Cloudy", "Rain",
              "Showers", "Snow", "Fog", "Windy", "Thunderstorm"):
        if k.lower() in text.lower():
            cond = k
            break
    return {"temperature_f": temp, "condition": cond, "source": "Apple Weather"}
