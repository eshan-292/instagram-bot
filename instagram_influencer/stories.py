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

import requests as http_requests
from PIL import Image, ImageDraw, ImageFont

from config import BASE_DIR, Config
from persona import get_persona, persona_data_dir
from publisher import _is_challenge_error, ChallengeAbort

log = logging.getLogger(__name__)

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
    ("Casual or dressy?", ["Casual", "Dressy"]),
    ("Ethnic or western?", ["Ethnic", "Western"]),
    ("Day look or night?", ["Day", "Night"]),
]


# ---------------------------------------------------------------------------
# Persona-aware accessors (replace hardcoded constants)
# ---------------------------------------------------------------------------

def _highlights_file():
    return persona_data_dir() / "highlights.json"


def _question_prompts():
    return get_persona().get("stories", {}).get("question_prompts", ["What's on your mind?"])


def _quiz_choices():
    return get_persona().get("stories", {}).get("quiz_choices", [])


def _highlight_categories():
    return get_persona().get("stories", {}).get("highlight_categories", {})


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
    hl_file = _highlights_file()
    if not hl_file.exists():
        return {}
    try:
        with open(hl_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_highlights(data: dict[str, str]) -> None:
    hl_file = _highlights_file()
    hl_file.parent.mkdir(parents=True, exist_ok=True)
    with open(hl_file, "w") as f:
        json.dump(data, f, indent=2)


def _categorize_post(post: dict[str, Any]) -> str:
    """Determine highlight category from post topic/notes."""
    text = f"{post.get('topic', '')} {post.get('notes', '')}".lower()
    categories = _highlight_categories()
    best_cat = "OOTD"  # default
    best_score = 0
    for cat, keywords in categories.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_cat = cat
    return best_cat


def ensure_highlights(cl: Any) -> dict[str, str]:
    """Create highlights if they don't exist. Returns {category: highlight_pk}."""
    existing = _load_highlights()
    categories = _highlight_categories()
    if len(existing) >= len(categories):
        return existing

    # Check what highlights already exist on the profile
    try:
        my_highlights = cl.user_highlights(cl.user_id)
        for hl in my_highlights:
            title = str(getattr(hl, "title", ""))
            for cat in categories:
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
            # highlight_create/create_reel API is unstable — log quietly
            log.debug("Highlight create failed for '%s': %s", category, exc)
            return False


# ---------------------------------------------------------------------------
# Story reposting
# ---------------------------------------------------------------------------

def _build_story_stickers(post: dict[str, Any]) -> dict[str, list]:
    """Build stickers for a story upload.

    Always adds a hashtag sticker. Then picks ONE interactive sticker type
    based on weighted probability:
      35% poll  — quick binary choice, great for engagement
      30% question box — drives DMs and saves
      20% quiz  — educational, shareable
      15% none  — keep some stories clean

    Only one interactive sticker per story to avoid visual clutter.
    """
    sticker_args: dict[str, list] = {}

    # Hashtag sticker (always)
    try:
        from instagrapi.types import Hashtag, StoryHashtag
        persona = get_persona()
        hashtag_name = persona.get("stories", {}).get(
            "hashtag_sticker_name", persona.get("brand_tag", ""))
        sticker_args["hashtags"] = [StoryHashtag(
            hashtag=Hashtag(id="0", name=hashtag_name),
            x=0.5, y=0.12, width=0.3, height=0.05, rotation=0.0,
        )]
    except Exception as exc:
        log.warning("Could not create hashtag sticker: %s", exc)

    # Pick one interactive sticker (weighted)
    roll = random.random()

    if roll < 0.35:
        # Poll sticker
        try:
            from instagrapi.types import StoryPoll
            question, options = random.choice(_POLL_CHOICES)
            sticker_args["polls"] = [StoryPoll(
                x=0.5, y=0.75, width=0.6, height=0.15, rotation=0.0,
                question=question, options=options,
            )]
        except Exception as exc:
            log.warning("Could not create poll sticker: %s", exc)

    elif roll < 0.65:
        # Question box sticker (AMA — high DM driver)
        try:
            from instagrapi.types import StoryQuestion
            prompt = random.choice(_question_prompts())
            sticker_args["questions"] = [StoryQuestion(
                x=0.5, y=0.75, width=0.8, height=0.18, rotation=0.0,
                question=prompt,
                type="text",
            )]
        except Exception as exc:
            log.warning("Could not create question sticker: %s", exc)

    elif roll < 0.85:
        # Quiz sticker (shareable, educational)
        try:
            from instagrapi.types import StoryQuiz
            quiz_list = _quiz_choices()
            if quiz_list:
                quiz = random.choice(quiz_list)
                question = quiz["question"]
                options = quiz["options"]
                correct_idx = quiz["correct"]
            else:
                question = "Which fabric wins for Mumbai heat?"
                options = ["Silk", "Linen", "Polyester", "Denim"]
                correct_idx = 1
            sticker_args["quizs"] = [StoryQuiz(
                x=0.5, y=0.75, width=0.8, height=0.22, rotation=0.0,
                question=question,
                options=options,
                correct_answer=correct_idx,
            )]
        except Exception as exc:
            log.warning("Could not create quiz sticker: %s", exc)

    # else: no interactive sticker (clean story — 15% of the time)

    return sticker_args


def _download_media_from_ig(cl: Any, post: dict[str, Any]) -> tuple[str | None, bool, bool]:
    """Download post media from Instagram when local files don't exist.

    Returns (path, is_video, is_temp). Caller must clean up temp files.
    """
    post_pk = post.get("platform_post_id")
    if not post_pk or str(post_pk) == "unknown":
        return None, False, False

    try:
        media_info = cl.media_info(int(post_pk))
    except Exception as exc:
        log.debug("Could not fetch media_info for %s: %s", post.get("id"), exc)
        return None, False, False

    # Prefer image (cleaner for story overlay)
    thumb = getattr(media_info, "thumbnail_url", None)
    if thumb:
        try:
            resp = http_requests.get(str(thumb), timeout=30)
            if resp.status_code == 200 and len(resp.content) > 5000:
                fd, tmp = tempfile.mkstemp(suffix=".jpg", prefix="story_dl_")
                os.close(fd)
                with open(tmp, "wb") as f:
                    f.write(resp.content)
                log.debug("Downloaded thumbnail for story: %s (%d bytes)", post.get("id"), len(resp.content))
                return tmp, False, True
        except Exception as exc:
            log.debug("Thumbnail download failed for %s: %s", post.get("id"), exc)

    # Fallback to video
    vid = getattr(media_info, "video_url", None)
    if vid:
        try:
            resp = http_requests.get(str(vid), timeout=60)
            if resp.status_code == 200 and len(resp.content) > 10000:
                fd, tmp = tempfile.mkstemp(suffix=".mp4", prefix="story_dl_")
                os.close(fd)
                with open(tmp, "wb") as f:
                    f.write(resp.content)
                log.debug("Downloaded video for story: %s (%d bytes)", post.get("id"), len(resp.content))
                return tmp, True, True
        except Exception as exc:
            log.debug("Video download failed for %s: %s", post.get("id"), exc)

    return None, False, False


def repost_to_story(cl: Any, post: dict[str, Any]) -> str | None:
    """Repost a published post as a story with text overlay + stickers.

    If local media files don't exist (typical in CI/GitHub Actions since
    generated_images/ is gitignored), downloads media from Instagram
    using the platform_post_id.

    Returns the story PK or None on failure.
    """
    # Find the media file (prefer image for stories — cleaner with overlay)
    image_url = str(post.get("image_url", "")).strip()
    video_url = str(post.get("video_url", "")).strip()

    media_path = None
    is_video = False
    downloaded_temp = False

    # Resolve paths relative to BASE_DIR (content_queue.json stores relative paths
    # like "generated_images/maya-005.png" which only work if cwd is instagram_influencer/)
    def _resolve(p: str) -> str | None:
        if not p:
            return None
        if os.path.isabs(p) and os.path.exists(p):
            return p
        # Try relative to BASE_DIR first (most common in CI)
        resolved = str(BASE_DIR / p)
        if os.path.exists(resolved):
            return resolved
        # Try as-is (works when cwd is already instagram_influencer/)
        if os.path.exists(p):
            return p
        return None

    # Try local files first
    resolved_image = _resolve(image_url)
    resolved_video = _resolve(video_url)

    if resolved_image:
        media_path = resolved_image
    elif resolved_video:
        media_path = resolved_video
        is_video = True
    else:
        # Download from Instagram (local files don't exist in CI)
        media_path, is_video, downloaded_temp = _download_media_from_ig(cl, post)
        if not media_path:
            log.debug("No media available for story repost of %s (local missing, IG download failed)", post.get("id"))
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
        if _is_challenge_error(exc):
            raise ChallengeAbort(str(exc)) from exc
        log.error("Story upload failed for %s: %s", post.get("id"), exc)
        return None
    finally:
        # Clean up overlay temp file
        if overlay_path and os.path.exists(overlay_path):
            try:
                os.remove(overlay_path)
            except OSError:
                pass
        # Clean up downloaded media temp file
        if downloaded_temp and media_path and os.path.exists(media_path):
            try:
                os.remove(media_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Native post-to-story reshare (Instagram's "Add post to your story")
# ---------------------------------------------------------------------------

def _create_blank_story_bg() -> str:
    """Create a 1080x1920 gradient background for the story.

    Instagram requires an image even when using StoryMedia sticker.
    Uses a subtle gradient matching common story aesthetics.
    """
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)

    # Random gradient from persona-appropriate colors
    gradients = [
        ((25, 25, 35), (45, 25, 60)),       # dark purple
        ((15, 15, 25), (35, 45, 65)),        # dark blue
        ((30, 20, 20), (50, 30, 40)),        # dark rose
        ((20, 25, 20), (35, 50, 45)),        # dark teal
        ((25, 20, 30), (55, 35, 50)),        # dark mauve
    ]
    top_color, bot_color = random.choice(gradients)

    for y in range(h):
        ratio = y / h
        r = int(top_color[0] + (bot_color[0] - top_color[0]) * ratio)
        g = int(top_color[1] + (bot_color[1] - top_color[1]) * ratio)
        b = int(top_color[2] + (bot_color[2] - top_color[2]) * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    fd, tmp_path = tempfile.mkstemp(suffix=".jpg", prefix="story_bg_")
    os.close(fd)
    img.save(tmp_path, "JPEG", quality=85)
    return tmp_path


def reshare_post_to_story(cl: Any, media_pk: int, user_pk: int) -> str | None:
    """Share a feed post to story using Instagram's native reshare.

    Creates the clickable "See Post" card that drives traffic back to the
    original post. This is how the Instagram app's "Add post to your story"
    button works under the hood.

    Returns the story PK or None on failure.
    """
    try:
        from instagrapi.types import StoryMedia
    except ImportError:
        log.error("StoryMedia not available in this instagrapi version")
        return None

    bg_path = None
    try:
        bg_path = _create_blank_story_bg()

        # StoryMedia creates the native post-card sticker
        media_sticker = StoryMedia(
            media_pk=int(media_pk),
            user_id=int(user_pk),
            x=0.5,
            y=0.5,
            width=0.8,
            height=0.6,
            rotation=0.0,
        )

        story = cl.photo_upload_to_story(
            Path(bg_path),
            caption="",
            medias=[media_sticker],
        )
        log.info("Reshared post %s to story (story pk=%s)", media_pk, story.pk)
        return str(story.pk)

    except Exception as exc:
        if _is_challenge_error(exc):
            raise ChallengeAbort(str(exc)) from exc
        log.error("Native story reshare failed for post %s: %s", media_pk, exc)
        return None
    finally:
        if bg_path and os.path.exists(bg_path):
            try:
                os.remove(bg_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Story session — called from engagement.py
# ---------------------------------------------------------------------------

def _get_recent_posts_from_ig(cl: Any, amount: int = 20) -> list[dict[str, Any]]:
    """Fetch recent posts directly from Instagram API.

    This is the primary source — works even without content_queue.json.
    Returns list of dicts with media_pk and user_pk.
    """
    try:
        user_id = cl.user_id
        medias = cl.user_medias(user_id, amount=amount)
        posts = []
        for m in medias:
            posts.append({
                "media_pk": m.pk,
                "user_pk": user_id,
                "caption": getattr(m, "caption_text", "") or "",
                "taken_at": getattr(m, "taken_at", None),
            })
        log.info("Fetched %d recent posts from Instagram for story reshare", len(posts))
        return posts
    except Exception as exc:
        if _is_challenge_error(exc):
            raise ChallengeAbort(str(exc)) from exc
        log.warning("Could not fetch recent posts from IG: %s", exc)
        return []


def _get_storied_pks(data_dir: Path) -> set[str]:
    """Load PKs of posts already shared to story recently."""
    storied_file = data_dir / "storied_posts.json"
    if not storied_file.exists():
        return set()
    try:
        with open(storied_file) as f:
            records = json.load(f)
        # Only count posts storied in the last 7 days
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent = set()
        for r in records:
            try:
                dt = datetime.fromisoformat(r["date"].replace("Z", "+00:00"))
                if dt > week_ago:
                    recent.add(str(r["media_pk"]))
            except (KeyError, ValueError, TypeError):
                pass
        return recent
    except (json.JSONDecodeError, OSError):
        return set()


def _save_storied_pk(data_dir: Path, media_pk: int) -> None:
    """Record that a post was shared to story."""
    storied_file = data_dir / "storied_posts.json"
    records = []
    if storied_file.exists():
        try:
            with open(storied_file) as f:
                records = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    records.append({
        "media_pk": str(media_pk),
        "date": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    })
    # Keep only last 60 days of records
    cutoff = datetime.now(timezone.utc) - timedelta(days=60)
    records = [r for r in records if _parse_date(r.get("date")) > cutoff]
    storied_file.parent.mkdir(parents=True, exist_ok=True)
    with open(storied_file, "w") as f:
        json.dump(records, f, indent=2)


def _parse_date(s: str | None) -> datetime:
    """Parse ISO date string, returning epoch on failure."""
    if not s:
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime(2000, 1, 1, tzinfo=timezone.utc)


def run_story_session(cl: Any, cfg: Config) -> dict[str, int]:
    """Share 1-2 past posts to story using Instagram's native reshare.

    Uses the native "Add post to your story" mechanism — creates a story
    with the post embedded as a clickable card with "See Post" link.
    This drives traffic back to the original post and boosts engagement.
    """
    stats: dict[str, int] = {"stories_posted": 0, "highlights_added": 0}
    data_dir = persona_data_dir()

    # 1. Try content_queue.json first (has post metadata)
    candidates_from_queue = []
    try:
        with open(QUEUE_FILE) as f:
            queue = json.load(f)
        for post in queue.get("posts", []):
            if str(post.get("status", "")).lower() == "posted":
                ppk = post.get("platform_post_id")
                if ppk and str(ppk) != "unknown":
                    candidates_from_queue.append({
                        "media_pk": int(ppk),
                        "user_pk": int(cl.user_id),
                        "caption": str(post.get("caption", ""))[:50],
                    })
    except (json.JSONDecodeError, OSError):
        pass

    # 2. Fallback: fetch posts directly from Instagram API
    if not candidates_from_queue:
        candidates_from_queue = _get_recent_posts_from_ig(cl, amount=20)

    if not candidates_from_queue:
        log.warning("No posts available for story reshare (no queue, no IG posts)")
        return stats

    # 3. Filter out recently storied posts
    storied = _get_storied_pks(data_dir)
    candidates = [c for c in candidates_from_queue if str(c["media_pk"]) not in storied]

    if not candidates:
        log.info("All %d posts already storied in last 7 days", len(candidates_from_queue))
        return stats

    log.info("Story candidates: %d eligible out of %d total", len(candidates), len(candidates_from_queue))

    # 4. Pick 1-2 posts (conservative — stories should feel organic)
    pick_count = min(random.randint(1, 2), len(candidates))
    chosen = random.sample(candidates, pick_count)

    from rate_limiter import random_delay

    for post in chosen:
        media_pk = post["media_pk"]
        user_pk = post["user_pk"]

        story_pk = reshare_post_to_story(cl, media_pk, user_pk)
        if story_pk:
            stats["stories_posted"] += 1
            _save_storied_pk(data_dir, media_pk)

            # Add to highlight
            category = _categorize_post(post)
            if add_story_to_highlight(cl, story_pk, category):
                stats["highlights_added"] += 1

            random_delay(30, 90)

    log.info("Story session: %d/%d posted, %d highlights (candidates: %d)",
             stats["stories_posted"], pick_count, stats["highlights_added"], len(candidates))
    return stats
