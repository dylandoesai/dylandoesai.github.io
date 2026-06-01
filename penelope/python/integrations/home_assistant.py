"""Home Assistant integration.

Config:
  home_assistant:
    base_url: "http://homeassistant.local:8123"
    token: "<long-lived access token from HA profile>"

Exposes:
  list_entities()                 -> list of entity dicts
  call_service(domain, svc, **kwargs)  -> dict response
  toggle(entity_id)               -> convenience for switches/lights
  scene(scene_id)                 -> activate a scene
"""

from __future__ import annotations

import requests


def _conf():
    from config_loader import load
    cfg = load()
    return cfg.get("home_assistant") or {}


def _headers():
    return {"Authorization": f"Bearer {_conf().get('token','')}",
            "Content-Type": "application/json"}


def list_entities():
    c = _conf()
    if not c.get("base_url") or not c.get("token"): return []
    try:
        r = requests.get(f"{c['base_url']}/api/states", headers=_headers(), timeout=5)
        return r.json() if r.ok else []
    except Exception:
        return []


def call_service(domain: str, service: str, **data):
    c = _conf()
    if not c.get("base_url") or not c.get("token"): return None
    try:
        r = requests.post(f"{c['base_url']}/api/services/{domain}/{service}",
                          headers=_headers(), json=data, timeout=8)
        return r.json() if r.ok else None
    except Exception:
        return None


def toggle(entity_id: str):
    domain = entity_id.split(".", 1)[0]
    return call_service(domain, "toggle", entity_id=entity_id)


def scene(scene_id: str):
    return call_service("scene", "turn_on", entity_id=scene_id)
