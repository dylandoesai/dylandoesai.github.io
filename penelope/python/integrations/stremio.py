"""Stremio control — launch + play content.

Stremio responds to its custom URL scheme `stremio://`. Anything we can
build into that URL plays directly when opened via `open`.

Useful URL forms:
  stremio://detail/<type>/<id>      -> open detail page (movie/series)
  stremio:///discover/...           -> open Discover
  stremio:///library                -> open library

API:
  launch()                          -> bool
  play(stremio_url_or_imdb_id)      -> bool
  open_imdb(imdb_id, type="movie")  -> bool
"""

from __future__ import annotations

import subprocess


def launch() -> bool:
    try:
        r = subprocess.run(["open", "-a", "Stremio"],
                           capture_output=True, text=True, timeout=8)
        return r.returncode == 0
    except Exception:
        return False


def play(url_or_id: str) -> bool:
    u = url_or_id.strip()
    if not u:
        return False
    if u.startswith("stremio:"):
        target = u
    elif u.startswith("tt"):
        target = f"stremio://detail/movie/{u}"
    else:
        target = u
    try:
        r = subprocess.run(["open", target],
                           capture_output=True, text=True, timeout=8)
        return r.returncode == 0
    except Exception:
        return False


def open_imdb(imdb_id: str, kind: str = "movie") -> bool:
    if kind not in ("movie", "series"):
        kind = "movie"
    return play(f"stremio://detail/{kind}/{imdb_id}")
