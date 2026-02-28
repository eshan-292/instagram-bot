#!/usr/bin/env python3
"""Persona system — loads account-specific data from JSON config files.

Each persona (maya, aryan, sat1, etc.) has its own JSON file in personas/
and its own state directory in data/{persona_id}/.

Usage:
    from persona import get_persona, persona_data_dir, next_post_id

    persona = get_persona()          # loads from PERSONA env var (default: "maya")
    data_dir = persona_data_dir()    # returns Path to data/{persona_id}/
    post_id = next_post_id(posts)    # generates next {prefix}-NNN ID
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
PERSONAS_DIR = BASE_DIR / "personas"
DATA_DIR = BASE_DIR / "data"

_persona: dict[str, Any] | None = None


def load_persona(name: str | None = None) -> dict[str, Any]:
    """Load a persona JSON file by name. Falls back to PERSONA env var, then 'maya'."""
    name = (name or os.getenv("PERSONA", "maya")).strip().lower()
    path = PERSONAS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Persona file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("id", name)
    log.debug("Loaded persona: %s (%s)", data.get("name", name), path.name)
    return data


def get_persona() -> dict[str, Any]:
    """Return the current persona (singleton, loaded on first call)."""
    global _persona
    if _persona is None:
        _persona = load_persona()
    return _persona


def reset_persona() -> None:
    """Reset the cached persona (for testing)."""
    global _persona
    _persona = None


def persona_data_dir(persona: dict[str, Any] | None = None) -> Path:
    """Return the per-persona state directory: data/{persona_id}/

    Creates the directory tree if it doesn't exist.
    """
    p = persona or get_persona()
    d = DATA_DIR / p["id"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def persona_images_dir(persona: dict[str, Any] | None = None) -> Path:
    """Return the per-persona generated images directory."""
    d = persona_data_dir(persona) / "generated_images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def persona_reference_dir(persona: dict[str, Any] | None = None) -> Path:
    """Return the per-persona reference photos directory."""
    p = persona or get_persona()
    return BASE_DIR / "reference" / p["id"]


def next_post_id(existing: list[dict[str, Any]], offset: int = 1) -> str:
    """Generate the next {prefix}-NNN ID based on existing posts and persona prefix."""
    p = get_persona()
    prefix = p.get("post_id_prefix", p["id"])
    max_num = 0
    for item in existing:
        post_id = str(item.get("id", "")).strip().lower()
        if not post_id.startswith(f"{prefix}-"):
            continue
        tail = post_id[len(prefix) + 1:]
        if tail.isdigit():
            max_num = max(max_num, int(tail))
    return f"{prefix}-{max_num + offset:03d}"


def is_satellite() -> bool:
    """Check if the current persona is a satellite (support) account."""
    return get_persona().get("mode") == "satellite"
