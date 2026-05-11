"""Spotify control via the Mac desktop app (AppleScript). No API needed.

Penelope can run:
    spotify_ctl.play()
    spotify_ctl.pause()
    spotify_ctl.next_track()
    spotify_ctl.previous_track()
    spotify_ctl.play_uri("spotify:track:...")
    spotify_ctl.now_playing()  -> {title, artist, album, position, duration}
"""

from __future__ import annotations

import subprocess


def _osa(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=5)
    return r.stdout.strip()


def play():            _osa('tell application "Spotify" to play')
def pause():           _osa('tell application "Spotify" to pause')
def next_track():      _osa('tell application "Spotify" to next track')
def previous_track():  _osa('tell application "Spotify" to previous track')


def play_uri(uri: str):
    _osa(f'tell application "Spotify" to play track "{uri}"')


def now_playing():
    s = _osa(r'''
        tell application "Spotify"
            if it is running then
                set t to name of current track
                set a to artist of current track
                set al to album of current track
                set pos to player position
                set dur to (duration of current track) / 1000
                return t & "|" & a & "|" & al & "|" & pos & "|" & dur
            end if
        end tell
    ''')
    if not s: return None
    parts = s.split("|")
    if len(parts) < 5: return None
    try:
        return {
            "title": parts[0], "artist": parts[1], "album": parts[2],
            "position": float(parts[3]), "duration": float(parts[4]),
        }
    except ValueError:
        return None
