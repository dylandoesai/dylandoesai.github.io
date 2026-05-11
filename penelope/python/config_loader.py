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
    return cfg


def system_prompt() -> str:
    p = CONFIG_DIR / "system_prompt.txt"
    if p.exists():
        return p.read_text()
    return "You are Penelope, a warm cyber AI assistant for Papi."
