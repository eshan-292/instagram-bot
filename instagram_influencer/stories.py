#!/usr/bin/env python3
"""Story reposting + highlight management for growth."""

from __future__ import annotations

import json
import logging
import os
import random
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from config import BASE_DIR, Config

log = logging.getLogger(__name__)

HIGHLIGHTS_FILE = BASE_DIR / "highlights.json"
QUEUE_FILE = BASE_DIR / "content_queue.json"

# Text overlays — randomly picked per story
_OVERLAY_TEXTS = [
    "In case you missed it",
    "Still obsessed",
    "Which vibe?",
    "This look tho",
    "One of my favs",
    "Swipe up for more",
    "Thoughts?",
    "Replay worthy",
    "That girl energy",
    "Would you wear this?",
]

# Poll questions paired with options
_POLL_CHOICES = [
    ("Love this look?", ["Yes", "Absolutely"]),
    ("Vibe check?", ["Fire", "Next level"]),
    ("Would you wear this?", ["100%", "Not my style"]),
    ("Rate this outfit", ["10/10", "Needs work"]),
    ("This or something edgy?", ["This!", "Edgy"]),
]

# Highlight categories with keyword matchers
HIGHLIGHT_CATEGORIES = {
    "OOTD": ["outfit", "ootd", "look", "style", "glam", "dressed", "fashion", "ensemble", "wearing"],
    "Mumbai Style": ["mumbai", "bandra", "colaba", "kala ghoda", "cafe", "brunch", "rooftop", "street"],
    "Ethnic Vibes": ["ethnic", "saree", "kurta", "jhumka", "desi", "indian", "traditional", "fusion"],
    "Tips": ["tip", "hack", "how to", "guide", "styling", "pair"],
    "BTS": ["behind", "shoot", "wind-down", "penthouse", "process", "making"],
    "Glam": ["night", "evening", "gala", "party", "cocktail", "sequin", "club"],
}


# ---------------------------------------------------------------------------
# Text overlay on images
# ---------------------------------------------------------------------------

def _add_text_overlay(image_path: str, text: str) -> str:
    """Add a text overlay bar at the bottom of the image. Returns temp file path."""
    img = Image.open(image_path).convert("RGBA")
    w, h = img.size

    # Semi-transparent overlay bar at bottom (15% of image height)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    bar_h = int(h * 0.12)
    bar_top = h - bar_h
    draw.rectangle([(0, bar_top), (w, h)], fill=(0, 0, 0, 140))

    # Text
    font_size = int(bar_h * 0.45)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except (OSError, IOError):
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (w - text_w) // 2
    text_y = bar_top + (bar_h - text_h) // 2
    draw.text((text_x, text_y), text, fill=(255, 255, 255, 255), font=font)

    result = Image.alpha_composite(img, overlay).convert("RGB")

    fd, tmp_path = tempfile.mkstemp(suffix=".jpg", prefix="story_")
    os.close(fd)
    result.save(tmp_path, "JPEG", quality=95)
    return tmp_path


# ---------------------------------------------------------------------------
# Highlight management
# ---------------------------------------------------------------------------

def _load_highlights() -> dict[str, str]:
    """Load highlight PKs from file: {category: highlight_pk}."""
    if not HIGHLIGHTS_FILE.exists():
        return {}
    try:
        with open(HIGHLIGHTS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_highlights(data: dict[str, str]) -> None:
    with open(HIGHLIGHTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _categorize_post(post: dict[str, Any]) -> str:
    """Determine highlight category from post topic/notes."""
    text = f"{post.get('topic', '')} {post.get('notes', '')}".lower()
    best_cat = "OOTD"  # default
    best_score = 0
    for cat, keywords in HIGHLIGHT_CATEGORIES.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_cat = cat
    return best_cat


def ensure_highlights(cl: Any) -> dict[str, str]:
    """Create highlights if they don't exist. Returns {category: highlight_pk}."""
    existing = _load_highlights()
    if len(existing) >= len(HIGHLIGHT_CATEGORIES):
        return existing

    # Check what highlights already exist on the profile
    try:
        my_highlights = cl.user_highlights(cl.user_id)
        for hl in my_highlights:
            title = str(getattr(hl, "title", ""))
            for cat in HIGHLIGHT_CATEGORIES:
                if cat.lower() == title.lower() and cat not in existing:
                    existing[cat] = str(hl.pk)
    except Exception as exc:
        log.debug("Could not fetch existing highlights: %s", exc)

    _save_highlights(existing)
    return existing


def add_story_to_highlight(cl: Any, story_pk: str, category: str) -> bool:
    """Add a story to the appropriate highlight. Creates highlight if needed."""
    highlights = ensure_highlights(cl)

    if category in highlights:
        try:
            cl.highlight_add_stories(highlights[category], [story_pk])
            log.info("Added story to highlight '%s'", category)
            return True
        except Exception as exc:
            log.warning("Failed to add to highlight '%s': %s", category, exc)
            return False
    else:
        # Create new highlight with this story
        try:
            hl = cl.highlight_create(title=category, story_ids=[story_pk])
            highlights[category] = str(hl.pk)
            _save_highlights(highlights)
            log.info("Created highlight '%s' with story", category)
            return True
        except Exception as exc:
            log.warning("Failed to create highlight '%s': %s", category, exc)
            return False


# ---------------------------------------------------------------------------
# Story reposting
# ---------------------------------------------------------------------------

def _build_story_stickers(post: dict[str, Any]) -> dict[str, list]:
    """Build stickers for a story upload."""
    from instagrapi.types import Hashtag, StoryHashtag, StoryPoll

    sticker_args: dict[str, list] = {}

    # Hashtag sticker
    try:
        tag_name = "mayavarma"
        sticker_args["hashtags"] = [StoryHashtag(
            hashtag=Hashtag(id="0", name=tag_name),
            x=0.5, y=0.15, width=0.3, height=0.05, rotation=0.0,
        )]
    except Exception as exc:
        log.debug("Could not create hashtag sticker: %s", exc)

    # Poll sticker (~50% of stories)
    if random.random() < 0.5:
        try:
            question, options = random.choice(_POLL_CHOICES)
            sticker_args["polls"] = [StoryPoll(
                x=0.5, y=0.75, width=0.6, height=0.15, rotation=0.0,
                question=question, options=options,
            )]
        except Exception as exc:
            log.debug("Could not create poll sticker: %s", exc)

    return sticker_args


def repost_to_story(cl: Any, post: dict[str, Any]) -> str | None:
    """Repost a published post as a story with text overlay + stickers.

    Returns the story PK or None on failure.
    """
    # Find the media file (prefer image for stories — cleaner with overlay)
    image_url = str(post.get("image_url", "")).strip()
    video_url = str(post.get("video_url", "")).strip()

    media_path = None
    is_video = False
    if image_url and os.path.exists(image_url):
        media_path = image_url
    elif video_url and os.path.exists(video_url):
        media_path = video_url
        is_video = True
    else:
        log.debug("No local media for story repost of %s", post.get("id"))
        return None

    # Add text overlay (only for images)
    overlay_path = None
    upload_path = media_path
    if not is_video:
        try:
            text = random.choice(_OVERLAY_TEXTS)
            overlay_path = _add_text_overlay(media_path, text)
            upload_path = overlay_path
        except Exception as exc:
            log.warning("Text overlay failed, using original: %s", exc)

    # Build stickers
    sticker_args = _build_story_stickers(post)

    # Upload story
    try:
        if is_video:
            story = cl.video_upload_to_story(
                Path(upload_path),
                caption=str(post.get("caption", ""))[:100],
                **sticker_args,
            )
        else:
            story = cl.photo_upload_to_story(
                Path(upload_path),
                caption=str(post.get("caption", ""))[:100],
                **sticker_args,
            )
        log.info("Reposted %s as story (pk=%s)", post.get("id"), story.pk)
        return str(story.pk)
    except Exception as exc:
        log.warning("Story upload failed for %s: %s", post.get("id"), exc)
        return None
    finally:
        # Clean up overlay temp file
        if overlay_path and os.path.exists(overlay_path):
            try:
                os.remove(overlay_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Story session — called from engagement.py
# ---------------------------------------------------------------------------

def run_story_session(cl: Any, cfg: Config) -> dict[str, int]:
    """Repost 2-3 past posts as stories with overlays + stickers + highlights."""
    stats: dict[str, int] = {"stories_posted": 0, "highlights_added": 0}

    # Load queue to find posted items
    try:
        with open(QUEUE_FILE) as f:
            queue = json.load(f)
    except (json.JSONDecodeError, OSError):
        log.warning("Could not load content queue for story session")
        return stats

    posts = queue.get("posts", [])
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Find candidates: posted items not storied in last 7 days
    candidates = []
    for post in posts:
        if str(post.get("status", "")).lower() != "posted":
            continue
        # Check last_storied_at
        last_storied = post.get("last_storied_at")
        if last_storied:
            try:
                dt = datetime.fromisoformat(last_storied.replace("Z", "+00:00"))
                if dt > week_ago:
                    continue
            except (ValueError, TypeError):
                pass
        candidates.append(post)

    if not candidates:
        log.info("No eligible posts for story reposting")
        return stats

    # Pick 2-3 random posts
    pick_count = min(random.randint(2, 3), len(candidates))
    chosen = random.sample(candidates, pick_count)

    from rate_limiter import random_delay

    for post in chosen:
        story_pk = repost_to_story(cl, post)
        if story_pk:
            stats["stories_posted"] += 1
            # Mark as storied
            post["last_storied_at"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")

            # Add to highlight
            category = _categorize_post(post)
            if add_story_to_highlight(cl, story_pk, category):
                stats["highlights_added"] += 1

            random_delay(30, 90)

    # Save updated queue with last_storied_at timestamps
    try:
        with open(QUEUE_FILE, "w") as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        log.warning("Could not save queue after story session: %s", exc)

    log.info("Story session done: %s", stats)
    return stats
