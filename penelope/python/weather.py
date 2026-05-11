"""Weather via Open-Meteo (no API key).

Per spec: Open-Meteo + auto-geolocate. We do auto-geolocate by querying
ip-api.com (free, IP-based; good enough for "current city" weather).
If config.json -> weather_location is set explicitly, we use that.
"""

from __future__ import annotations

import asyncio
import json

import requests

WMO = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Rain showers", 81: "Heavy rain showers", 82: "Violent rain showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail",
}


async def current(location=None) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch, location)


def _fetch(location):
    try:
        if location and "lat" in location:
            lat, lon, city = location["lat"], location["lon"], location.get("city", "")
        else:
            geo = requests.get("http://ip-api.com/json/", timeout=4).json()
            lat = geo.get("lat"); lon = geo.get("lon"); city = geo.get("city", "")
        if lat is None: return {}
        url = (f"https://api.open-meteo.com/v1/forecast"
               f"?latitude={lat}&longitude={lon}"
               f"&current=temperature_2m,weather_code,wind_speed_10m"
               f"&temperature_unit=fahrenheit&wind_speed_unit=mph")
        r = requests.get(url, timeout=5).json()
        c = r.get("current") or {}
        return {
            "city": city,
            "temp_f": round(c.get("temperature_2m", 0)),
            "code": c.get("weather_code"),
            "condition": WMO.get(c.get("weather_code"), "Unknown"),
            "wind_mph": round(c.get("wind_speed_10m", 0)),
        }
    except Exception as e:
        return {"error": str(e)}
