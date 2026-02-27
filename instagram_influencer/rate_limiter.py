#!/usr/bin/env python3
"""Rate limiter — tracks engagement actions and enforces daily limits."""

from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

LOG_FILE = Path(__file__).resolve().parent / "engagement_log.json"

# Aggressive growth defaults — warmup multiplier keeps these safe for new accounts.
# Override via Config fields.
DAILY_LIMITS = {
    "likes": 200,
    "comments": 60,
    "follows": 100,
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


def warmup_multiplier() -> float:
    """Return a multiplier (0.6-1.0) based on account age.

    Ramps limits gradually to avoid action blocks on new accounts:
      Days 1-7:   0.6x
      Days 8-14:  0.8x
      Days 15+:   1.0x (full limits)
    """
    created = os.getenv("ACCOUNT_CREATED_DATE", "").strip()
    if not created:
        return 1.0
    try:
        created_dt = datetime.strptime(created, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return 1.0
    age_days = (datetime.now(timezone.utc) - created_dt).days
    if age_days < 7:
        return 0.6
    if age_days < 14:
        return 0.8
    return 1.0


def can_act(data: dict[str, Any], action_type: str, limit: int | None = None) -> bool:
    """Check if we're still under the daily limit for `action_type`.

    Applies warmup multiplier for new accounts.
    """
    max_count = limit if limit is not None else DAILY_LIMITS.get(action_type, 0)
    if max_count <= 0:
        return False
    effective = int(max_count * warmup_multiplier())
    return actions_today(data, action_type) < effective


def record_action(data: dict[str, Any], action_type: str, target_id: str) -> None:
    """Append an action to the log."""
    data.setdefault("actions", []).append({
        "type": action_type,
        "target": target_id,
        "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    })


def random_delay(min_s: int = 30, max_s: int = 90) -> None:
    """Human-like sleep between actions using gaussian distribution.

    Instead of uniform random (which bots use), this uses a gaussian curve
    centered between min and max, so most delays cluster near the middle
    with occasional short or long waits — like a real person scrolling.

    15% chance of a 'micro-break' (90-300s) — simulates getting distracted,
    checking another app, replying to a text, etc.
    """
    # Micro-break: simulate getting distracted (checking texts, switching apps)
    if random.random() < 0.15:
        pause = random.uniform(90, 300)
        log.debug("Micro-break: %.0fs (simulating distraction)", pause)
        time.sleep(pause)
        return

    # Gaussian distribution: most delays cluster around the midpoint
    mid = (min_s + max_s) / 2
    std = (max_s - min_s) / 4  # ~95% of values within min-max range
    delay = random.gauss(mid, std)
    delay = max(min_s * 0.8, min(max_s * 1.3, delay))  # soft clamp

    # Add small sub-second jitter (humans aren't precise)
    delay += random.uniform(0.2, 1.8)

    log.debug("Sleeping %.1fs", delay)
    time.sleep(delay)


def session_startup_jitter() -> None:
    """Random delay at session start to avoid running at exact cron times.

    Real people don't open Instagram at exactly :00 or :30. This adds
    0-4 minutes of jitter so sessions start at varied times.
    """
    jitter = random.uniform(10, 240)  # 10s to 4 minutes
    log.info("Session startup jitter: %.0fs", jitter)
    time.sleep(jitter)


def daily_summary(data: dict[str, Any]) -> dict[str, int]:
    """Return today's action counts by type."""
    today = _today_str()
    counts: dict[str, int] = {}
    for a in data.get("actions", []):
        if str(a.get("at", "")).startswith(today):
            t = a.get("type", "unknown")
            counts[t] = counts.get(t, 0) + 1
    return counts
