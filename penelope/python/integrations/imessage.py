"""iMessage send + recent-thread read via AppleScript.

System Settings -> Privacy & Security -> Automation -> Messages -> enable
the parent app (Terminal / Penelope).

API:
  send(recipient, body)      -> bool   recipient = phone, email, or contact name
  recent_threads(limit=10)   -> [{handle, last_message, last_ts}]
"""

from __future__ import annotations

import subprocess


def send(recipient: str, body: str) -> bool:
    safe_to = recipient.replace('"', '\\"')
    safe_body = body.replace('"', '\\"')
    script = f'''
        tell application "Messages"
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy "{safe_to}" of targetService
            send "{safe_body}" to targetBuddy
        end tell
    '''
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def recent_threads(limit: int = 10):
    """Read recent message threads via the chat.db sqlite store. Read-only."""
    import sqlite3, os, time
    path = os.path.expanduser("~/Library/Messages/chat.db")
    if not os.path.exists(path):
        return []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = conn.execute("""
            SELECT
              h.id,
              m.text,
              (m.date / 1000000000 + 978307200) as ts
            FROM message m
            JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.text IS NOT NULL
            ORDER BY m.date DESC
            LIMIT ?
        """, (limit * 3,)).fetchall()
        conn.close()
    except Exception:
        return []
    seen, out = set(), []
    for handle, text, ts in rows:
        if handle in seen:
            continue
        seen.add(handle)
        out.append({"handle": handle, "last_message": text or "",
                    "last_ts": int(ts) if ts else 0,
                    "when": time.strftime("%b %-d %I:%M %p",
                                          time.localtime(ts)) if ts else ""})
        if len(out) >= limit:
            break
    return out
