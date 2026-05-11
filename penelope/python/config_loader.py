"""Read JSON configs in penelope/config/ with sane defaults."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def _read(name: str, default):
    p = CONFIG_DIR / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def load() -> dict:
    cfg = _read("config.json", {})
    cfg["revenue"] = _read("revenue.json", {})
    cfg["analytics"] = _read("analytics.json", {})
    cfg["schedule"] = _read("schedule.json", {})
    cfg["todos"] = _read("todos.json", {})
    cfg["channels"] = _read("channels.json", {"channels": []})
    cfg["work_schedule"] = _read("work_schedule.json", {})
    return cfg


def system_prompt() -> str:
    p = CONFIG_DIR / "system_prompt.txt"
    base = p.read_text() if p.exists() else \
        "You are Penelope, a warm cyber AI assistant for Papi."

    # Append the durable "About Dylan" context (always in the prompt
    # so she never has to re-learn who he is).
    about = CONFIG_DIR / "about_dylan.md"
    if about.exists():
        base += "\n\n# About Dylan (durable personal context)\n\n" + about.read_text()
    return base


def knowledge_paths() -> list[str]:
    """Folders/files on Dylan's Mac that Penelope is allowed to read on
    demand via her Claude-Code Read tool. She doesn't preload these
    (they could be large) -- she fetches when relevant."""
    return list((_read("config.json", {}) or {}).get("knowledge_paths") or [])
