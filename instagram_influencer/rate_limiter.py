#!/usr/bin/env python3
"""Rate limiter — tracks engagement actions and enforces daily limits."""

from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

LOG_FILE = Path(__file__).resolve().parent / "engagement_log.json"

# Conservative defaults for new accounts (first 2 weeks).
# Override via Config fields.
DAILY_LIMITS = {
    "likes": 100,
    "comments": 30,
    "follows": 50,
}


def load_log(path: str | Path = LOG_FILE) -> dict[str, Any]:
    """Load engagement log from disk."""
    path = str(path)
    if not os.path.exists(path):
        return {"actions": []}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if not isinstance(data.get("actions"), list):
            return {"actions": []}
        return data
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Corrupt engagement log, resetting: %s", exc)
        return {"actions": []}


def save_log(path: str | Path, data: dict[str, Any]) -> None:
    """Write engagement log to disk."""
    with open(str(path), "w") as f:
        json.dump(data, f, indent=2)


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def actions_today(data: dict[str, Any], action_type: str) -> int:
    """Count how many actions of `action_type` were taken today (UTC)."""
    today = _today_str()
    return sum(
        1
        for a in data.get("actions", [])
        if a.get("type") == action_type and str(a.get("at", "")).startswith(today)
    )


def can_act(data: dict[str, Any], action_type: str, limit: int | None = None) -> bool:
    """Check if we're still under the daily limit for `action_type`."""
    max_count = limit if limit is not None else DAILY_LIMITS.get(action_type, 0)
    if max_count <= 0:
        return False
    return actions_today(data, action_type) < max_count


def record_action(data: dict[str, Any], action_type: str, target_id: str) -> None:
    """Append an action to the log."""
    data.setdefault("actions", []).append({
        "type": action_type,
        "target": target_id,
        "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    })


def random_delay(min_s: int = 30, max_s: int = 90) -> None:
    """Human-like random sleep between actions."""
    delay = random.uniform(min_s, max_s)
    log.debug("Sleeping %.1fs", delay)
    time.sleep(delay)


def daily_summary(data: dict[str, Any]) -> dict[str, int]:
    """Return today's action counts by type."""
    today = _today_str()
    counts: dict[str, int] = {}
    for a in data.get("actions", []):
        if str(a.get("at", "")).startswith(today):
            t = a.get("type", "unknown")
            counts[t] = counts.get(t, 0) + 1
    return counts
