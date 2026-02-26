#!/usr/bin/env python3
"""Queue management for the content pipeline."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------

def parse_scheduled_at(value: Any) -> datetime | None:
    """Parse an ISO-8601 datetime string into a UTC-aware datetime."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_utc(dt: datetime) -> str:
    """Format a datetime as an ISO-8601 UTC string."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Queue I/O
# ---------------------------------------------------------------------------

def read_queue(path: str | Path) -> list[dict[str, Any]]:
    """Read posts from the queue JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, dict):
        posts = payload.get("posts", [])
        if not isinstance(posts, list):
            raise ValueError("Queue JSON field 'posts' must be a list")
        return posts
    if isinstance(payload, list):
        return payload
    raise ValueError("Queue file must be a JSON array or an object with 'posts'")


def write_queue(path: str | Path, posts: list[dict[str, Any]]) -> None:
    """Write posts to the queue JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"posts": posts}, f, indent=2, ensure_ascii=True)
        f.write("\n")


# ---------------------------------------------------------------------------
# Queue queries
# ---------------------------------------------------------------------------

def status_counts(posts: list[dict[str, Any]]) -> dict[str, int]:
    """Count posts by status."""
    counts: dict[str, int] = {}
    for item in posts:
        status = str(item.get("status", "unknown")).strip().lower() or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return counts


def publishable_count(posts: list[dict[str, Any]]) -> int:
    """Count posts with status 'ready' or 'approved'."""
    return sum(
        1 for item in posts
        if str(item.get("status", "")).strip().lower() in {"ready", "approved"}
    )


def find_eligible(posts: list[dict[str, Any]]) -> tuple[int, dict[str, Any]] | None:
    """Find the next post eligible for publishing.

    Returns (index, post) or None.
    A post is eligible if:
    - status is 'ready' or 'approved'
    - scheduled_at is in the past (or unset)
    - has a caption
    - has media: carousel_images (for carousel) or image_url/video_url (for reel/single)
    """
    now = datetime.now(timezone.utc)
    for idx, item in enumerate(posts):
        status = str(item.get("status", "")).strip().lower()
        if status not in {"ready", "approved"}:
            continue
        dt = parse_scheduled_at(item.get("scheduled_at"))
        if dt and dt > now:
            continue
        if not str(item.get("caption", "")).strip():
            continue
        post_type = str(item.get("post_type", "reel")).strip().lower()
        if post_type == "carousel":
            if not item.get("carousel_images"):
                continue
        else:
            if not str(item.get("image_url", "")).strip() and not str(item.get("video_url", "")).strip():
                continue
        return idx, item
    return None


def next_maya_id(existing: list[dict[str, Any]], offset: int = 1) -> str:
    """Generate the next maya-NNN ID based on existing posts."""
    max_num = 0
    for item in existing:
        post_id = str(item.get("id", "")).strip().lower()
        if not post_id.startswith("maya-"):
            continue
        tail = post_id[5:]
        if tail.isdigit():
            max_num = max(max_num, int(tail))
    return f"maya-{max_num + offset:03d}"
