"""Penelope pre-launch deterministic test.

Verifies every integration in isolation BEFORE ./scripts/run.sh tries to
boot her. Exit code 0 = ready to ship. Non-zero = list of failures.

Each test prints `PASS` / `FAIL` / `SKIP` with a one-line reason. Tests
are organized so a fail in one doesn't cascade.

Run:  python scripts/preflight.py
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))


RESULTS = []   # (status, label, detail)


def report(status: str, label: str, detail: str = ""):
    RESULTS.append((status, label, detail))
    icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "·", "WARN": "!"}.get(status, "?")
    print(f"  {icon} [{status}] {label}" + (f"  — {detail}" if detail else ""), flush=True)


def section(name: str):
    print(f"\n=== {name} ===", flush=True)


# ---------- 1. Deps + binaries ----------

def check_python_deps():
    section("Python deps")
    REQUIRED = [
        ("edge_tts", "Edge TTS"),
        ("faster_whisper", "STT"),
        ("face_recognition", "Owner face match"),
        ("mediapipe", "Face mesh extractor"),
        ("sounddevice", "Mic capture"),
        ("webrtcvad", "VAD"),
        ("cryptography", "Transcript encryption"),
        ("keyring", "Keychain bridge"),
        ("requests", "HTTP integrations"),
        ("stripe", "Stripe SDK"),
        ("resemblyzer", "Voice ID"),
        ("EventKit", "Calendar/Reminders native"),
        ("Foundation", "PyObjC core"),
        ("openwakeword", "Hotword tier 2"),
    ]
    for mod, what in REQUIRED:
        try:
            importlib.import_module(mod)
            report("PASS", f"{mod}", what)
        except ImportError as e:
            report("FAIL", f"{mod}", f"missing — {what}: {e}")


def check_binaries():
    section("Binaries on PATH")
    for cmd, what in [
        ("claude", "Claude Code CLI"),
        ("node", "Node.js"),
        ("npm", "npm"),
        ("ffmpeg", "ffmpeg"),
        ("osascript", "AppleScript runner"),
        ("dns-sd", "Bonjour discovery"),
    ]:
        if shutil.which(cmd):
            report("PASS", cmd, what)
        else:
            report("FAIL", cmd, f"not on PATH — {what}")


# ---------- 2. Assets / config ----------

def check_assets():
    section("Assets / config files")
    for rel, label in [
        ("assets/face-mesh.json", "Penelope Cruz face geometry"),
        ("assets/owner_voice.npy", "Owner voice embedding"),
        ("assets/owner_voice_meta.json", "Voice ID metadata"),
        ("config/config.json", "Main config"),
        ("config/channels.json", "7-channel registry"),
        ("config/system_prompt.txt", "Persona"),
        ("config/about_dylan.md", "Dylan baseline"),
        ("config/work_schedule.json", "Shift rotation"),
        ("config/mcp.json", "MCP server config"),
        ("CLAUDE.md", "Project orientation"),
        ("renderer/vendor/three.module.js", "Three.js vendored"),
    ]:
        p = ROOT / rel
        if p.exists() and p.stat().st_size > 0:
            report("PASS", rel)
        else:
            report("FAIL", rel, f"missing/empty: {label}")
    own_faces = list((ROOT / "assets/owner_faces").glob("*"))
    if len(own_faces) >= 5:
        report("PASS", "assets/owner_faces/", f"{len(own_faces)} photos")
    else:
        report("WARN", "assets/owner_faces/", f"only {len(own_faces)} photos (≥5 recommended)")


# ---------- 3. Claude / brain ----------

def check_claude_cli():
    section("Claude Code CLI")
    if not shutil.which("claude"):
        report("FAIL", "claude bin", "not installed")
        return
    try:
        r = subprocess.run(["claude", "--version"],
                           capture_output=True, text=True, timeout=10)
        v = r.stdout.strip()
        report("PASS", "claude --version", v)
    except Exception as e:
        report("FAIL", "claude --version", str(e))


# ---------- 4. Apple integrations ----------

def check_apple_perms():
    section("Apple permissions (functional probes)")
    try:
        r = subprocess.run(["osascript", "-e",
                            'tell application "Calendar" to count of calendars'],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip().isdigit():
            report("PASS", "Calendar AppleScript",
                   f"{r.stdout.strip()} calendars")
        else:
            report("FAIL", "Calendar AppleScript", r.stderr.strip()[:80])
    except Exception as e:
        report("FAIL", "Calendar AppleScript", str(e))

    try:
        r = subprocess.run(["osascript", "-e",
                            'tell application "Reminders" to count of lists'],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip().isdigit():
            report("PASS", "Reminders AppleScript",
                   f"{r.stdout.strip()} lists")
        else:
            report("FAIL", "Reminders AppleScript", r.stderr.strip()[:80])
    except Exception as e:
        report("FAIL", "Reminders AppleScript", str(e))

    try:
        r = subprocess.run(["osascript", "-e",
                            'tell application "Mail" to count of mailboxes of inbox'],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            report("PASS", "Mail AppleScript",
                   f"{r.stdout.strip() or '0'} mailboxes")
        else:
            report("FAIL", "Mail AppleScript", r.stderr.strip()[:80])
    except Exception as e:
        report("FAIL", "Mail AppleScript", str(e))

    try:
        r = subprocess.run(["osascript", "-e",
                            'tell application "Spotify" to player state'],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            report("PASS", "Spotify AppleScript", r.stdout.strip())
        else:
            report("WARN", "Spotify AppleScript",
                   "needs Spotify running for wake song")
    except Exception as e:
        report("WARN", "Spotify AppleScript", str(e))


def check_reminders_eventkit():
    section("Reminders via EventKit")
    try:
        from integrations import apple_reminders
        t0 = time.time()
        r = apple_reminders.upcoming(30)
        report("PASS" if r else "WARN",
               "apple_reminders.upcoming(30)",
               f"{len(r)} items / {time.time()-t0:.1f}s")
    except Exception as e:
        report("FAIL", "apple_reminders.upcoming", str(e)[:80])


def check_calendar_pushed():
    section("Calendar — Penelope · Work shifts")
    try:
        r = subprocess.run(
            ["osascript", "-e",
             'tell application "Calendar" to tell calendar "Penelope · Work" to return count of events'],
            capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip().isdigit():
            n = int(r.stdout.strip())
            if n > 100:
                report("PASS", "shift events", f"{n} events on calendar")
            else:
                report("WARN", "shift events",
                       f"only {n} — run apple_cal.push_shift_schedule")
        else:
            report("FAIL", "Penelope · Work calendar",
                   r.stderr.strip()[:80] or "missing")
    except Exception as e:
        report("FAIL", "Penelope · Work calendar", str(e))


# ---------- 5. Revenue / analytics ----------

def check_live_data():
    section("Live data fetches")
    try:
        import config_loader
        cfg = config_loader.load()

        from integrations import gumroad_src, elevenlabs_src, upload_post
        async def go():
            g = await gumroad_src.fetch(cfg)
            e = await elevenlabs_src.fetch(cfg)
            u = await upload_post.fetch_all(cfg)
            return g, e, u
        t0 = time.time()
        g, e, u = asyncio.run(go())
        report("PASS", "Gumroad API",
               f"today=${g.get('today',0)} mtd=${g.get('mtd',0)}")
        report("PASS", "ElevenLabs",
               f"mtd=${e.get('mtd',0)} clones={e.get('cloned_by_count','?')}")
        platforms = {p: len(u.get(p, {}).get("channels", [])) for p in
                     ("youtube", "tiktok", "instagram", "facebook", "x")}
        report("PASS", "upload-post analytics",
               f"channels {platforms} in {time.time()-t0:.1f}s")
    except Exception as ex:
        report("FAIL", "live data", str(ex)[:120])


# ---------- 6. MCP server ----------

def check_mcp_server():
    section("Penelope MCP server")
    try:
        import penelope_mcp_server as m
        n = len(m.mcp._tool_manager._tools)
        report("PASS", "MCP server imports", f"{n} tools registered")
        if n < 25:
            report("WARN", "tool count", f"expected ≥28, got {n}")
    except Exception as ex:
        report("FAIL", "MCP server", str(ex)[:120])


# ---------- 7. Voice ID ----------

def check_voice_id():
    section("Voice ID")
    try:
        import voice_id
        if voice_id.owner_enrolled():
            meta = json.loads(
                (ROOT / "assets/owner_voice_meta.json").read_text())
            report("PASS", "owner enrolled",
                   f"threshold={meta.get('threshold')} samples={meta.get('n_samples')}")
        else:
            report("WARN", "owner enrolled",
                   "no owner_voice.npy — run python/enroll_voice.py")
    except Exception as ex:
        report("FAIL", "voice_id", str(ex)[:80])


# ---------- 8. Renderer artifacts ----------

def check_renderer():
    section("Renderer")
    for rel in [
        "renderer/index.html",
        "renderer/app.js",
        "renderer/styles.css",
        "renderer/visualizer/penelope-face.js",
        "renderer/visualizer/face-landmarks.js",
        "renderer/visualizer/audio-analyzer.js",
        "renderer/visualizer/boot-sequence.js",
        "renderer/panels/revenue-panel.js",
        "renderer/panels/analytics-panel.js",
        "renderer/panels/schedule-panel.js",
    ]:
        p = ROOT / rel
        if p.exists() and p.stat().st_size > 0:
            report("PASS", rel)
        else:
            report("FAIL", rel, "missing or empty")
    nm = ROOT / "node_modules" / ".bin" / "electron"
    if nm.exists():
        report("PASS", "electron installed", "node_modules/.bin/electron")
    else:
        report("FAIL", "electron", "missing — run npm install")


# ---------- main ----------

def main() -> int:
    print("Penelope pre-launch check\n" + "=" * 60, flush=True)
    check_binaries()
    check_python_deps()
    check_assets()
    check_claude_cli()
    check_apple_perms()
    check_reminders_eventkit()
    check_calendar_pushed()
    check_live_data()
    check_mcp_server()
    check_voice_id()
    check_renderer()

    print("\n" + "=" * 60)
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    warns = [r for r in RESULTS if r[0] == "WARN"]
    passes = [r for r in RESULTS if r[0] == "PASS"]
    print(f"  {len(passes)} PASS  {len(warns)} WARN  {len(fails)} FAIL")
    if fails:
        print("\nFAILURES:")
        for _, lbl, det in fails:
            print(f"  ✗ {lbl}: {det}")
        return 1
    if warns:
        print("\nWarnings (non-blocking):")
        for _, lbl, det in warns:
            print(f"  ! {lbl}: {det}")
    print("\nReady to ship. Fire ./scripts/run.sh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
