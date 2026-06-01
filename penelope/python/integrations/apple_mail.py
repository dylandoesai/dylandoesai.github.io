"""Apple Mail: read recent inbox + draft replies.

System Settings -> Privacy -> Automation -> Mail -> enable Terminal/Penelope.

API:
  recent_unread(limit=10) -> [{from, subject, snippet, id, received_ts}]
  draft_reply(message_id, body)
  read_message(message_id) -> full body
"""

from __future__ import annotations

import subprocess


def _osa(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=8)
    return r.stdout.strip()


def recent_unread(limit: int = 10):
    s = _osa(f'''
        set output to ""
        tell application "Mail"
            set msgs to messages of inbox whose read status is false
            set n to count of msgs
            if n > {limit} then set n to {limit}
            repeat with i from 1 to n
                set m to item i of msgs
                set f to (sender of m) as string
                set s to (subject of m) as string
                set p to (content of m) as string
                if (length of p) > 220 then set p to (text 1 thru 220 of p)
                set output to output & (id of m) & tab & f & tab & s & tab & p & linefeed
            end repeat
        end tell
        return output
    ''')
    out = []
    for line in s.splitlines():
        parts = line.split("\t", 3)
        if len(parts) < 4: continue
        out.append({"id": parts[0], "from": parts[1],
                    "subject": parts[2], "snippet": parts[3]})
    return out


def draft_reply(message_id: str, body: str):
    body = body.replace('"', '\\"')
    _osa(f'''
        tell application "Mail"
            set m to first message of inbox whose id is "{message_id}"
            set r to reply m with opening window
            set content of r to "{body}"
        end tell
    ''')
