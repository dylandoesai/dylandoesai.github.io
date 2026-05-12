"""Penelope's Python sidecar.

JSON-RPC over stdio. The Electron main process spawns this script and
communicates one-line JSON per message.

Inbound  (from Electron): {"id": int, "method": str, "params": dict}
Outbound replies:         {"id": int, "result": any} or {"id": int, "error": str}
Server-pushed events:     {"event": str, "data": dict}

Methods exposed:
    start            -- begin hotword listening, webcam loop
    daily_brief      -- run the full morning brief sequence
    ask              -- one-shot text query (devtools / manual)
    set_mode         -- "warm" | "flirty" | "professional"
    reload_config    -- re-read JSON configs and emit data_updated
    sleep            -- go back to hotword-only standby
    shutdown         -- clean exit
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

import config_loader  # noqa: E402
import brain          # noqa: E402
import tts            # noqa: E402
import stt            # noqa: E402
import vad_listener   # noqa: E402
import hotword        # noqa: E402
import weather        # noqa: E402
import face_recog     # noqa: E402
import transcripts    # noqa: E402
import proactive      # noqa: E402
from integrations import upload_post, stripe_src, gumroad_src, adsense_src  # noqa: E402
from integrations import apple_cal, apple_reminders, spotify_ctl  # noqa: E402
from integrations import home_assistant, apple_mail, slack_src    # noqa: E402


STATE = {
    "active": False,        # True when fully awake (post-wake)
    "mode": "warm",         # warm | flirty | professional
    "speaking": False,
    "config": None,
    "loop": None,
}


# ----- JSON-RPC plumbing ----------------------------------------------------

_lock = threading.Lock()

def emit(event: str, data: dict | None = None) -> None:
    """Push an event to Electron."""
    with _lock:
        sys.stdout.write(json.dumps({"event": event, "data": data or {}}) + "\n")
        sys.stdout.flush()


def reply(id_: int, result=None, error: str | None = None) -> None:
    msg = {"id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    with _lock:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()


def log(*args) -> None:
    print(*args, file=sys.stderr, flush=True)


# ----- RPC handlers --------------------------------------------------------

async def handle_start(_params):
    if STATE["active"]:
        return {"ok": True}
    STATE["config"] = config_loader.load()
    log("config loaded")

    # boot proactive scheduler
    proactive.start(STATE, emit)

    # boot webcam + face recognition loop (always on per spec)
    face_recog.start(STATE, on_seen=lambda: emit("face_seen", {}))

    # boot hotword listener in background
    threading.Thread(target=hotword.run,
                     args=(STATE, on_hotword),
                     daemon=True).start()
    emit("log", {"msg": "hotword listening"})
    return {"ok": True}


def on_hotword(phrase: str):
    """Called from the hotword thread.

    phrase = 'papis_home'   -> full activation: song + assembly + brief
    phrase = 'hey_penelope' -> quick wake: fast assembly + short greeting
    """
    if STATE["active"]:
        # Already awake; still acknowledge so the renderer can show a
        # gentle flourish. Don't re-run the full sequence.
        emit("hotword", {"phrase": phrase, "already_active": True})
        return
    STATE["active"] = True
    emit("hotword", {"phrase": phrase, "already_active": False})
    # Renderer drives the boot sequence, then calls daily_brief()
    # (papis_home) or quick_greeting (hey_penelope).


async def handle_daily_brief(_params):
    cfg = STATE["config"]
    name = cfg.get("name", "Papi")
    pet = cfg.get("pet_name", "Papi")
    location = cfg.get("weather_location")

    # Gather everything Penelope needs to riff on
    wx = await weather.current(location)
    cal_events = apple_cal.today_events()
    reminders = apple_reminders.today()
    rev = await brain.gather_revenue()
    analytics = await brain.gather_analytics()

    # Push updates to the panels in case anything changed
    emit("data_updated", {})

    # Build the brief prompt for Claude
    context = {
        "name": name,
        "pet_name": pet,
        "time": time.strftime("%I:%M %p"),
        "date": time.strftime("%A, %B %-d"),
        "weather": wx,
        "calendar_today": cal_events,
        "reminders_today": reminders,
        "revenue": rev,
        "social_analytics": analytics,
        "mode": STATE["mode"],
    }
    text = await brain.daily_brief(context)
    await speak(text)

    # After the brief, transition to listening
    asyncio.create_task(start_listening_loop())
    return {"ok": True}


async def handle_ask(params):
    text = params.get("text", "")
    if not text:
        return {"reply": ""}
    reply_text = await brain.chat(text, STATE)
    await speak(reply_text)
    return {"reply": reply_text}


async def handle_set_mode(params):
    mode = params.get("mode", "warm")
    if mode in ("warm", "flirty", "professional"):
        STATE["mode"] = mode
    return {"mode": STATE["mode"]}


async def handle_reload_config(_params):
    STATE["config"] = config_loader.load()
    emit("data_updated", {})
    return {"ok": True}


async def handle_sleep(_params):
    STATE["active"] = False
    emit("go_sleep", {})
    return {"ok": True}


async def handle_play_wake_song(_params):
    """Play the wake song via Spotify desktop app (AppleScript)."""
    cfg = STATE["config"] or {}
    ws = cfg.get("wake_song") or {}
    uri = ws.get("spotify_uri") or ""
    if not uri:
        emit("log", {"msg": "wake_song.spotify_uri empty in config; skipping"})
        return {"ok": False, "reason": "no_uri"}
    ok = spotify_ctl.play_uri(uri)
    return {"ok": bool(ok)}


async def handle_stop_wake_song(_params):
    """Smoothly fade Spotify down so Penelope's greeting is audible."""
    spotify_ctl.fade_out(duration_s=3.0)
    return {"ok": True}


async def handle_quick_greeting(_params):
    """Quick wake variant ('Hey Penelope'). No song, no brief.
    She just says a short greeting and starts listening."""
    import random
    cfg = STATE["config"] or {}
    mode = STATE["mode"]
    if mode == "professional":
        lines = ["Yes, Papi?", "Yes Dylan?", "What do you need?",
                 "I'm here, what's up?"]
    else:
        lines = ["Yes, dear?", "Yes, daddy?", "What can I do for you?",
                 "I'm right here, mi amor.", "Hi, Papi. What is it?"]
    text = random.choice(lines)
    await speak(text)
    asyncio.create_task(start_listening_loop())
    return {"ok": True}


async def handle_shutdown(_params):
    log("shutdown")
    sys.exit(0)


async def handle_get_panel_data(_params):
    """Return fresh data for the renderer's three side panels in one call.

    Revenue is the aggregate from brain.gather_revenue (Stripe + Gumroad
    + AdSense + ElevenLabs). Analytics is the per-platform upload-post
    summary. Schedule is today's Apple Calendar + Reminders, formatted
    for the schedule-panel renderer.

    Everything runs in parallel — total time = max of the slowest source."""
    loop = asyncio.get_running_loop()
    rev_task = asyncio.create_task(brain.gather_revenue())
    an_task = asyncio.create_task(brain.gather_analytics())
    cal_task = loop.run_in_executor(None, apple_cal.today_events)
    rem_task = loop.run_in_executor(None, apple_reminders.scheduled_today)
    rev = await rev_task
    analytics = await an_task
    try:
        cal_events = await cal_task
    except Exception:
        cal_events = []
    try:
        reminders = await rem_task
    except Exception:
        reminders = []
    schedule = {"events": [
        {"time": e.get("time", ""),
         "title": e.get("title", ""),
         "where": e.get("where", "")}
        for e in cal_events
    ]}
    todos = {"items": [
        {"text": r.get("title", ""), "done": False, "priority": "med"}
        for r in reminders
    ]}
    return {
        "revenue": rev,
        "analytics": analytics,
        "schedule": schedule,
        "todos": todos,
    }


HANDLERS = {
    "start": handle_start,
    "daily_brief": handle_daily_brief,
    "quick_greeting": handle_quick_greeting,
    "play_wake_song": handle_play_wake_song,
    "stop_wake_song": handle_stop_wake_song,
    "ask": handle_ask,
    "set_mode": handle_set_mode,
    "reload_config": handle_reload_config,
    "sleep": handle_sleep,
    "shutdown": handle_shutdown,
    "get_panel_data": handle_get_panel_data,
}


# ----- Conversation loop ---------------------------------------------------

async def speak(text: str):
    """Synthesize + push audio + visemes to renderer."""
    emit("assistant_text", {"text": text})
    STATE["speaking"] = True
    try:
        audio_url, visemes = await tts.synthesize(text, STATE["config"])
        emit("assistant_audio", {"url": audio_url, "visemes": visemes})
        # estimate duration so we know when to resume listening
        dur = visemes[-1]["t"] if visemes else max(1.5, len(text) * 0.06)
        await asyncio.sleep(dur)
    finally:
        STATE["speaking"] = False
        emit("assistant_idle", {})
        transcripts.append("penelope", text)


async def start_listening_loop():
    """Always-on VAD loop after activation. Cancellable on barge-in."""
    while STATE["active"]:
        emit("assistant_idle", {})
        # Block on VAD for the next utterance
        wav = await vad_listener.next_utterance(STATE)
        if not STATE["active"]:
            break
        if wav is None:
            continue
        # Transcribe
        text = await stt.transcribe(wav)
        if not text or len(text.strip()) < 2:
            continue
        transcripts.append("dylan", text)
        emit("user_transcript", {"text": text})

        # Detect mode-switch + sleep commands
        low = text.lower()
        if any(p in low for p in ("sleep penelope", "penelope sleep",
                                   "good night penelope", "goodnight penelope")):
            await speak("Sleeping, Papi. Just say my name and I'm right here.")
            STATE["active"] = False
            emit("go_sleep", {})
            break
        if "professional mode" in low or "business mode" in low:
            STATE["mode"] = "professional"
        elif "flirt mode" in low:
            STATE["mode"] = "flirty"
        elif "normal mode" in low or "warm mode" in low:
            STATE["mode"] = "warm"

        # Hand to Claude
        emit("assistant_thinking", {})
        # filler hum while Claude thinks (per user spec)
        filler_task = asyncio.create_task(maybe_filler())
        try:
            answer = await brain.chat(text, STATE)
        finally:
            filler_task.cancel()
        if answer:
            await speak(answer)


async def maybe_filler():
    """If Claude takes >1.8s, drop a soft 'mmh, Papi…' so silence doesn't drag."""
    try:
        await asyncio.sleep(1.8)
        await speak("Mm, give me a second Papi…")
    except asyncio.CancelledError:
        pass


# ----- Main loop -----------------------------------------------------------

async def stdin_reader():
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    while True:
        line = await reader.readline()
        if not line:
            await asyncio.sleep(0.1)
            continue
        try:
            msg = json.loads(line.decode().strip())
        except Exception:
            continue
        id_ = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        handler = HANDLERS.get(method)
        if handler is None:
            reply(id_, error=f"unknown method: {method}")
            continue
        try:
            result = await handler(params)
            reply(id_, result=result)
        except Exception as e:
            log("handler error:\n" + traceback.format_exc())
            reply(id_, error=str(e))


async def main():
    STATE["loop"] = asyncio.get_running_loop()
    try:
        await stdin_reader()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
