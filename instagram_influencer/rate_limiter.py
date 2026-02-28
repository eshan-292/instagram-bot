#!/usr/bin/env python3
"""Rate limiter — human-like timing, action-specific delays, session fatigue."""

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

# Conservative daily limits — quality over quantity.
# Override via Config fields.
DAILY_LIMITS = {
    "likes": 150,
    "comments": 40,
    "follows": 60,
}

# Track how many actions this session has done (for fatigue simulation)
_session_action_count = 0


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
    """Return a multiplier (0.5-1.0) based on account age.

    Ramps limits gradually to avoid action blocks on new accounts:
      Days 1-7:   0.5x
      Days 8-14:  0.7x
      Days 15-21: 0.85x
      Days 22+:   1.0x (full limits)
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
        return 0.5
    if age_days < 14:
        return 0.7
    if age_days < 21:
        return 0.85
    return 1.0


def can_act(data: dict[str, Any], action_type: str, limit: int | None = None) -> bool:
    """Check if we're still under the daily limit for `action_type`."""
    max_count = limit if limit is not None else DAILY_LIMITS.get(action_type, 0)
    if max_count <= 0:
        return False
    effective = int(max_count * warmup_multiplier())
    return actions_today(data, action_type) < effective


def record_action(data: dict[str, Any], action_type: str, target_id: str) -> None:
    """Append an action to the log."""
    global _session_action_count
    _session_action_count += 1
    data.setdefault("actions", []).append({
        "type": action_type,
        "target": target_id,
        "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    })


# ---------------------------------------------------------------------------
# Human-like timing system
# ---------------------------------------------------------------------------

def _is_night_hours() -> bool:
    """Check if it's late night IST (midnight-7am) — should be slower."""
    utc_now = datetime.now(timezone.utc)
    ist_hour = (utc_now.hour + 5) % 24  # rough IST conversion
    if utc_now.minute >= 30:
        ist_hour = (ist_hour + 1) % 24
    return ist_hour < 7 or ist_hour >= 23


def _fatigue_multiplier() -> float:
    """Sessions get slower as more actions are taken — like a real person losing interest.

    First 5 actions: normal speed (1.0x)
    Actions 6-12:    slightly slower (1.2x)
    Actions 13-20:   noticeably slower (1.5x)
    Actions 20+:     tired scrolling (1.8x)
    """
    if _session_action_count < 5:
        return 1.0
    if _session_action_count < 12:
        return 1.2
    if _session_action_count < 20:
        return 1.5
    return 1.8


def random_delay(min_s: int = 25, max_s: int = 75) -> None:
    """Human-like sleep between actions using gaussian distribution + fatigue.

    Behaviour:
    - Gaussian curve centered between min/max (not uniform)
    - 15% chance of micro-break (checking another app, replying to text)
    - Gets slower as session progresses (fatigue)
    - Slower during night hours
    - Occasional very short delays (quick double-tap scroll)
    """
    # Micro-break: simulate getting distracted
    if random.random() < 0.15:
        pause = random.uniform(90, 420)  # 1.5 - 7 minutes
        log.debug("Micro-break: %.0fs (simulating distraction)", pause)
        time.sleep(pause)
        return

    # Occasional quick action (3% — rapid scroll + like)
    if random.random() < 0.03:
        quick = random.uniform(3, 8)
        time.sleep(quick)
        return

    # Gaussian distribution with fatigue
    fatigue = _fatigue_multiplier()
    night_mult = 1.4 if _is_night_hours() else 1.0

    mid = (min_s + max_s) / 2 * fatigue * night_mult
    std = (max_s - min_s) / 3.5
    delay = random.gauss(mid, std)
    delay = max(min_s * 0.7, min(max_s * 2.0, delay))

    # Sub-second human jitter
    delay += random.uniform(0.3, 2.5)

    log.debug("Sleeping %.1fs (fatigue=%.1fx)", delay, fatigue)
    time.sleep(delay)


def action_delay(action_type: str) -> None:
    """Action-specific delays — different actions take different time.

    Likes:      fast (tap + scroll)           8-25s
    Comments:   slow (read, think, type)      40-120s
    Follows:    medium (check profile first)  30-80s
    Story views: fast (swipe through)         5-15s
    Unfollows:  medium                        25-70s
    Default:    moderate                       20-60s
    """
    ranges = {
        "likes":       (8, 25),
        "comments":    (40, 120),
        "follows":     (30, 80),
        "story_views": (5, 15),
        "unfollows":   (25, 70),
        "replies":     (35, 100),
    }
    min_s, max_s = ranges.get(action_type, (20, 60))
    random_delay(min_s, max_s)


def browsing_pause() -> None:
    """Simulate passively watching content — no action, just looking.

    Like a real person scrolling through feed without engaging.
    """
    pause = random.uniform(3, 15)
    log.debug("Browsing pause: %.1fs (just watching)", pause)
    time.sleep(pause)


def session_startup_jitter() -> None:
    """Random delay at session start — real people don't open IG at exact times.

    Wider range than before: 30s to 6 minutes.
    """
    jitter = random.uniform(30, 360)
    log.info("Session startup jitter: %.0fs", jitter)
    time.sleep(jitter)


def maybe_abort_session() -> bool:
    """12% chance to abort the current session early — simulates getting bored,
    phone ringing, switching to another app, etc.

    Call this periodically during engagement loops. Returns True if session
    should be abandoned.
    """
    if random.random() < 0.12:
        log.info("Session abort — simulating distraction/boredom")
        return True
    return False


def should_skip_session() -> bool:
    """20% chance to skip a scheduled session entirely.

    Real people don't check Instagram on a perfect schedule. Sometimes they're
    busy, sleeping, in a meeting, etc. This makes the pattern less predictable.
    """
    if random.random() < 0.20:
        log.info("Skipping this scheduled session (simulating being busy)")
        return True
    return False


def reset_session_fatigue() -> None:
    """Reset the fatigue counter — call at start of each new session."""
    global _session_action_count
    _session_action_count = 0


def daily_summary(data: dict[str, Any]) -> dict[str, int]:
    """Return today's action counts by type."""
    today = _today_str()
    counts: dict[str, int] = {}
    for a in data.get("actions", []):
        if str(a.get("at", "")).startswith(today):
            t = a.get("type", "unknown")
            counts[t] = counts.get(t, 0) + 1
    return counts
