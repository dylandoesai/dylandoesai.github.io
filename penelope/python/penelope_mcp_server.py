"""Penelope's own MCP server — exposes every integration as a first-class
tool for her brain (the Claude Code subprocess) to call directly.

Without this, the brain can only Bash-shell into Python which is clumsy
and slow. With this wired in via `claude --mcp-config`, she can call
`mcp__penelope__reminders_create` and it just works.

Tool surface (every method here is a tool the brain can invoke):

  Time / weather:
    current_weather()                          -> Apple Weather first, Open-Meteo fallback
    current_time()
    current_shift_state()

  Reminders:
    reminders_scheduled_today()
    reminders_upcoming(days)
    reminders_all_uncompleted()
    reminders_create(title, list_name?, due_iso?)
    reminders_complete(title)

  Calendar:
    calendar_today_events()
    calendar_create_event(title, start_iso, end_iso?, calendar?, location?, notes?)

  Mail:
    mail_recent_unread(limit?)
    mail_draft_reply(message_id, body)

  Messages / calls:
    imessage_send(recipient, body)
    imessage_recent_threads(limit?)
    phone_call(number)

  Music / video:
    spotify_play(uri_or_url)
    spotify_pause()
    spotify_next_track()
    spotify_fade_out(duration_s?)
    stremio_launch()
    stremio_play(url_or_imdb_id)

  Smart home:
    homekit_list_scenes()
    homekit_run_scene(fragment)

  Revenue / analytics:
    revenue_total()
    analytics_summary()

  Memory:
    transcripts_recent(turns?)

Run as: `python python/penelope_mcp_server.py` (stdio transport — driven
by Claude Code via the `claude --mcp-config config/mcp.json` flag).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_loader
import shift_state
import transcripts
import weather
from integrations import (
    apple_cal,
    apple_mail,
    apple_reminders,
    apple_weather,
    elevenlabs_src,
    gumroad_src,
    home_assistant,
    homekit,
    imessage,
    phone,
    slack_src,
    spotify_ctl,
    stremio,
    upload_post,
)
import brain

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("penelope")


# ---------- Time / weather ----------

@mcp.tool()
def current_time() -> dict:
    """Return current local time, date, and ISO timestamp."""
    now = dt.datetime.now().astimezone()
    return {
        "iso": now.isoformat(timespec="seconds"),
        "time_12h": now.strftime("%I:%M %p").lstrip("0"),
        "date": now.strftime("%A, %B %-d, %Y"),
        "tz": config_loader.system_timezone(),
    }


@mcp.tool()
def current_shift_state() -> dict:
    """Where Dylan is in his rotating 12h shift rotation right now."""
    return shift_state.current(config_loader.load())


@mcp.tool()
async def current_weather() -> dict:
    """Current conditions. Prefers Apple Weather widget data; falls back
    to Open-Meteo at Dylan's location."""
    aw = apple_weather.current()
    if aw and aw.get("temperature_f") is not None:
        return {"source": "Apple Weather", **aw}
    cfg = config_loader.load()
    om = await weather.current(cfg.get("weather_location"))
    return {"source": "Open-Meteo", **(om or {})}


# ---------- Reminders ----------

@mcp.tool()
def reminders_scheduled_today() -> list:
    """Uncompleted reminders due today."""
    return apple_reminders.scheduled_today()


@mcp.tool()
def reminders_upcoming(days: int = 14) -> list:
    """Uncompleted reminders due in the next N days."""
    return apple_reminders.upcoming(days)


@mcp.tool()
def reminders_all_uncompleted() -> list:
    """Every uncompleted reminder across all lists. For when Dylan asks
    'what's on my list' generally."""
    return apple_reminders.all_uncompleted()


@mcp.tool()
def reminders_create(title: str, list_name: str | None = None,
                     due_iso: str | None = None) -> dict:
    """Create a new reminder. due_iso is ISO 8601 (e.g. '2026-05-12T17:00')."""
    due = dt.datetime.fromisoformat(due_iso) if due_iso else None
    ok = apple_reminders.create(title, list_name or "Reminders", due)
    return {"ok": ok, "title": title}


@mcp.tool()
def reminders_complete(title: str) -> dict:
    """Mark a reminder as completed by exact title match."""
    return {"ok": apple_reminders.complete(title), "title": title}


# ---------- Calendar ----------

@mcp.tool()
def calendar_today_events() -> list:
    """Today's events across all non-noise calendars."""
    return apple_cal.today_events()


@mcp.tool()
def calendar_create_event(title: str, start_iso: str,
                          end_iso: str | None = None,
                          calendar: str = "Calendar",
                          location: str = "",
                          notes: str = "") -> dict:
    """Create a calendar event. start_iso/end_iso are ISO 8601."""
    start = dt.datetime.fromisoformat(start_iso)
    end = dt.datetime.fromisoformat(end_iso) if end_iso else None
    ok = apple_cal.create_event(title, start, end, calendar, location, notes)
    return {"ok": ok, "title": title, "start": start_iso}


# ---------- Mail ----------

@mcp.tool()
def mail_recent_unread(limit: int = 10) -> list:
    """Recent unread messages in Apple Mail inbox."""
    return apple_mail.recent_unread(limit=limit)


@mcp.tool()
def mail_draft_reply(message_id: str, body: str) -> dict:
    """Draft a reply to a specific Mail message (does NOT send)."""
    apple_mail.draft_reply(message_id, body)
    return {"ok": True}


# ---------- Messages / calls ----------

@mcp.tool()
def imessage_send(recipient: str, body: str) -> dict:
    """Send an iMessage to a phone number, email, or contact name."""
    return {"ok": imessage.send(recipient, body)}


@mcp.tool()
def imessage_recent_threads(limit: int = 10) -> list:
    """Recent iMessage threads (read-only from chat.db)."""
    return imessage.recent_threads(limit=limit)


@mcp.tool()
def phone_call(number: str) -> dict:
    """Place a phone call through Dylan's paired iPhone via Continuity."""
    return {"ok": phone.call(number), "number": number}


# ---------- Music / video ----------

@mcp.tool()
def spotify_play(uri_or_url: str) -> dict:
    """Play a track / album / playlist on Spotify desktop (URI or URL)."""
    return {"ok": bool(spotify_ctl.play_uri(uri_or_url))}


@mcp.tool()
def spotify_pause() -> dict:
    spotify_ctl.pause(); return {"ok": True}


@mcp.tool()
def spotify_next_track() -> dict:
    spotify_ctl.next_track(); return {"ok": True}


@mcp.tool()
def spotify_fade_out(duration_s: float = 3.0) -> dict:
    spotify_ctl.fade_out(duration_s=duration_s); return {"ok": True}


@mcp.tool()
def stremio_launch() -> dict:
    """Open Stremio app."""
    return {"ok": stremio.launch()}


@mcp.tool()
def stremio_play(url_or_imdb_id: str) -> dict:
    """Play in Stremio. Accepts stremio:// URL or IMDB id like tt1234567."""
    return {"ok": stremio.play(url_or_imdb_id)}


# ---------- Smart home ----------

@mcp.tool()
def homekit_list_scenes() -> list:
    """List Shortcuts prefixed `Penelope:` that drive HomeKit accessories."""
    return homekit.list_scenes()


@mcp.tool()
def homekit_run_scene(fragment: str) -> dict:
    """Fire a Penelope: shortcut by fuzzy fragment match (e.g. 'bedroom off')."""
    return {"ok": homekit.run_scene(fragment), "match": fragment}


# ---------- Slack ----------

@mcp.tool()
def slack_send(channel: str, text: str) -> dict:
    """Post to a Slack channel. Requires slack.user_token in config."""
    if hasattr(slack_src, "send"):
        return {"ok": slack_src.send(channel, text)}
    return {"ok": False, "reason": "slack_src.send not implemented"}


# ---------- Home Assistant ----------

@mcp.tool()
def home_assistant_call_service(domain: str, service: str,
                                entity_id: str | None = None) -> dict:
    """Call a Home Assistant service (e.g. domain='light', service='turn_on')."""
    if hasattr(home_assistant, "call_service"):
        return {"ok": home_assistant.call_service(domain, service, entity_id)}
    return {"ok": False, "reason": "home_assistant.call_service not implemented"}


# ---------- Revenue / analytics ----------

@mcp.tool()
async def revenue_total() -> dict:
    """All revenue sources aggregated (Stripe / Gumroad / AdSense /
    ElevenLabs voice library), today + month-to-date."""
    return await brain.gather_revenue()


@mcp.tool()
async def analytics_summary() -> dict:
    """All 7 channels × 5 platforms via upload-post API."""
    return await brain.gather_analytics()


# ---------- Memory / transcripts ----------

@mcp.tool()
def transcripts_recent(turns: int = 20) -> list:
    """Penelope's own recent conversation history (decrypted)."""
    try:
        return transcripts.recent(turns=turns)
    except Exception as e:
        return [{"error": str(e)}]


if __name__ == "__main__":
    mcp.run()
