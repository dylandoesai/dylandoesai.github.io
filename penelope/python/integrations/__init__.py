"""Penelope's external integrations.

Each integration module exposes an async `fetch()` (data sources) or
synchronous helpers (controllers like spotify_ctl, home_assistant).

The Python sidecar tries each integration; on failure it falls back to
the JSON in penelope/config/. This means you can ship without keys and
fill them in incrementally.
"""
