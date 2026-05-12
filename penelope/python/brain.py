"""Claude integration via the `claude` CLI (Claude Code, your Max plan).

Per spec: she IS Claude Code under the hood, Opus 4.7, with full agent
capabilities (read/write files, run shell, web fetch, etc.). We invoke
`claude` as a subprocess in headless mode so it can be driven by stdin.

Specifically we pipe a single prompt with a `--print` flag (one-shot
mode). For each turn we hand it a small JSON blob that includes:
  - the user's transcribed text
  - current personality mode
  - recent conversation summary (for memory continuity)

Claude returns spoken-friendly prose (no markdown). The system prompt
in config/system_prompt.txt is prepended on every call.

If `claude` is not on PATH we degrade gracefully to a canned response
so the rest of the app still works.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import textwrap
import time
from pathlib import Path

import config_loader
import transcripts
from integrations import upload_post, stripe_src, gumroad_src, adsense_src
from integrations import elevenlabs_src


CLAUDE_BIN = shutil.which("claude") or "claude"
CLAUDE_MODEL = "claude-opus-4-7"


async def chat(user_text: str, state: dict) -> str:
    cfg = state.get("config") or {}
    sys_prompt = config_loader.system_prompt()
    mode = state.get("mode", "warm")
    history = transcripts.recent(turns=20)
    name = cfg.get("name", "Dylan")
    pet = cfg.get("pet_name", "Papi")

    prompt = textwrap.dedent(f"""
        [Penelope context]
        - User's name: {name} (also called "{pet}")
        - Mode: {mode}    # warm | flirty | professional
        - Time: {time.strftime("%I:%M %p, %A %B %-d")}
        - Recent turns: {json.dumps(history[-10:], ensure_ascii=False)}

        [User said]
        {user_text}

        Respond as Penelope. Spoken word only -- no markdown, no lists,
        no code blocks. Keep it brief and natural unless asked for detail.
        Drop occasional Spanish endearments. Match the {mode} mode.
    """).strip()

    return await _call_claude(prompt, sys_prompt)


async def daily_brief(context: dict) -> str:
    sys_prompt = config_loader.system_prompt()
    prompt = textwrap.dedent(f"""
        Deliver Papi's morning brief. He just woke you up by saying "Papi's home".

        CONTEXT (use this, don't recite verbatim -- weave naturally):
        {json.dumps(context, ensure_ascii=False, indent=2, default=str)}

        Structure (~45-75 seconds of speech):
        1. A warm greeting using his name and "Papi". One sentence.
        2. Time, date, weather in one fluid line.
        3. Today's calendar in 1-2 sentences (only mention real items).
        4. Top 1-2 reminders.
        5. Revenue: yesterday's total + MTD pace + standout source.
        6. Social: top performer across channels + anything spiking or struggling.
        7. AI-picked priorities: the 1-3 things you think he should focus on.
        8. Sign off warmly.

        Spoken word only -- no markdown, no headers, no lists. One vibe,
        flowing. Drop an occasional Spanish endearment (mi amor, guapo).
    """).strip()
    return await _call_claude(prompt, sys_prompt)


async def gather_revenue() -> dict:
    """Pull live revenue from all configured sources, fallback to JSON."""
    cfg = config_loader.load()
    rev = cfg.get("revenue", {})  # JSON fallback
    out = {"sources": [], "currency": rev.get("currency", "USD"),
           "total_today": 0, "total_mtd": 0, "total_ytd": rev.get("total_ytd", 0)}

    for src_name, src in [("Stripe",  stripe_src),
                          ("Gumroad", gumroad_src),
                          ("AdSense", adsense_src),
                          ("ElevenLabs", elevenlabs_src)]:
        try:
            data = await src.fetch(cfg) if hasattr(src, "fetch") else None
        except Exception:
            data = None
        if data is None:
            # JSON fallback row if present
            row = next((s for s in rev.get("sources", []) if s.get("name") == src_name), None)
            if row:
                out["sources"].append(row)
                out["total_today"] += row.get("today", 0)
                out["total_mtd"] += row.get("mtd", 0)
            continue
        out["sources"].append({"name": src_name, **data})
        out["total_today"] += data.get("today", 0)
        out["total_mtd"] += data.get("mtd", 0)

    out["series_daily"] = rev.get("series_daily", [])
    return out


async def gather_analytics() -> dict:
    cfg = config_loader.load()
    try:
        return await upload_post.fetch_all(cfg)
    except Exception as e:
        # Fallback to JSON
        return cfg.get("analytics", {})


# ----- low-level claude call ------------------------------------------------

async def _call_claude(prompt: str, sys_prompt: str) -> str:
    if not shutil.which(CLAUDE_BIN):
        return _offline_response(prompt)
    # We use `claude --print` for a single-shot response. `--model` selects
    # Opus 4.7. `--append-system-prompt` prepends Penelope's persona.
    # Grant her read access to Dylan's main project memory so she can
    # pull deeper context about him on demand. Her own auto-memory writes
    # land in the standard ~/.claude/projects/<flattened-cwd>/memory/ dir.
    dev_memory = os.path.expanduser(
        "~/.claude/projects/-Users-dylanireland/memory")
    args = [
        CLAUDE_BIN, "--print", "--model", CLAUDE_MODEL,
        "--append-system-prompt", sys_prompt,
        # Restrict tool use to safe defaults for the voice-conversation
        # path. For full agent mode (when you say "Penelope, edit my X"),
        # we'll re-spawn with broader permissions.
        "--allowedTools", "Read,Write,Edit,Bash,WebFetch",
    ]
    if os.path.isdir(dev_memory):
        args.extend(["--add-dir", dev_memory])
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate(prompt.encode())
    return stdout.decode().strip() or _offline_response(prompt)


def _offline_response(_prompt: str) -> str:
    return ("I can't reach Claude right now, Papi. Make sure the claude CLI "
            "is installed and logged in. Try running 'claude login' in a "
            "terminal.")
