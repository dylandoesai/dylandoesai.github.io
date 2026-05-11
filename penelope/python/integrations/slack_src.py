"""Slack read + reply.

Config:
  slack:
    user_token: "xoxp-..."     # user token, scopes: channels:history,
                               # groups:history, im:history, chat:write,
                               # users:read

API:
  recent_dms(limit=10)
  unread_mentions(limit=10)
  post_message(channel, text)
"""

from __future__ import annotations

import requests


def _conf():
    from config_loader import load
    return (load().get("slack") or {})


def _token(): return _conf().get("user_token")


def _api(method: str, **params):
    t = _token()
    if not t: return None
    r = requests.post(f"https://slack.com/api/{method}",
                       headers={"Authorization": f"Bearer {t}"},
                       data=params, timeout=8)
    return r.json() if r.ok else None


def recent_dms(limit: int = 10):
    out = []
    lst = _api("conversations.list", types="im", limit=50)
    if not lst or not lst.get("ok"): return out
    for ch in lst.get("channels", []):
        h = _api("conversations.history", channel=ch["id"], limit=3)
        if not h or not h.get("ok"): continue
        for m in h.get("messages", []):
            out.append({"channel": ch["id"], "user": m.get("user"),
                        "text": m.get("text"), "ts": m.get("ts")})
    out.sort(key=lambda m: float(m.get("ts") or 0), reverse=True)
    return out[:limit]


def post_message(channel: str, text: str):
    return _api("chat.postMessage", channel=channel, text=text)
