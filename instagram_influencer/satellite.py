#!/usr/bin/env python3
"""Satellite account engagement — lightweight support for main accounts.

Satellite accounts exist to boost engagement signals for main accounts (Maya, Aryan).
They don't create content or publish — they only:
  1. Like, comment on, and save main accounts' posts
  2. View main accounts' stories
  3. Run light background engagement to look human

Daily limits are intentionally low to avoid detection.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from config import Config
from persona import get_persona, load_persona
from rate_limiter import (
    can_act, load_log, random_delay, record_action, save_log, session_startup_jitter,
    LOG_FILE,
)

log = logging.getLogger(__name__)


def _get_client(cfg: Config):
    """Get an Instagram client (reuses publisher's client factory)."""
    from publisher import _get_client as pub_get_client
    return pub_get_client(cfg)


def _generate_satellite_comment(cfg: Config, caption: str, target_name: str) -> str:
    """Generate a genuine-sounding comment from the satellite's voice."""
    persona = get_persona()
    tone = persona.get("voice", {}).get("tone", "friendly and genuine")

    prompt = (
        f"You are a casual Instagram user. Your vibe: {tone}.\n"
        f"Write a SHORT genuine comment (1 sentence, max 12 words) on this post by {target_name}.\n"
        f"Post caption: {caption[:200]}\n\n"
        "Rules:\n"
        "- Sound like a real person, not a bot\n"
        "- Be specific to the content (reference something in the caption)\n"
        "- No hashtags, no emojis spam (max 1 emoji)\n"
        "- No 'nice post' or 'great content' generic phrases\n"
        "- Do NOT mention yourself or ask questions about yourself\n\n"
        "Return ONLY the comment text, nothing else."
    )

    try:
        from gemini_helper import ask_gemini
        return ask_gemini(cfg.gemini_api_key, cfg.gemini_model, prompt).strip().strip('"')
    except Exception as exc:
        log.warning("Satellite comment gen failed: %s", exc)
        # Fallback generic comments
        fallbacks = [
            "This is exactly what I needed to see today",
            "Saving this for later, so good",
            "Okay this actually goes hard",
            "Literally sent this to my friend",
            "The consistency is unmatched",
        ]
        return random.choice(fallbacks)


def run_satellite_boost(cl, cfg: Config, data: dict[str, Any]) -> dict[str, int]:
    """Engage with main accounts' recent posts to boost their signals.

    For each boost target:
    - Like their recent posts
    - Comment on their latest post
    - Save their posts (saves = strong algorithm signal)
    - View their stories
    """
    persona = get_persona()
    targets = persona.get("boost_targets", [])
    limits = persona.get("engagement", {}).get("daily_limits", {})

    stats = {"likes": 0, "comments": 0, "saves": 0, "story_views": 0}

    for target_id in targets:
        try:
            target_persona = load_persona(target_id)
        except FileNotFoundError:
            log.warning("Boost target persona not found: %s", target_id)
            continue

        target_handle = target_persona.get("instagram_handle", "")
        target_name = target_persona.get("name", target_id)
        if not target_handle:
            log.warning("No instagram_handle for target %s", target_id)
            continue

        log.info("Boosting target: @%s (%s)", target_handle, target_name)

        try:
            # Find the target user
            user_info = cl.user_info_by_username_v1(target_handle)
            user_id = str(user_info.pk)
        except Exception as exc:
            log.warning("Cannot find user @%s: %s", target_handle, exc)
            continue

        # Fetch their recent posts
        try:
            medias = cl.user_medias_v1(int(user_id), amount=3)
        except Exception as exc:
            log.warning("Cannot fetch posts for @%s: %s", target_handle, exc)
            continue

        for media in medias:
            media_id = str(media.pk)

            # Like (if not already)
            if can_act(data, "likes", limits.get("likes", 40)):
                try:
                    cl.media_like(media_id)
                    record_action(data, "likes", media_id)
                    stats["likes"] += 1
                    log.debug("Liked %s by @%s", media_id, target_handle)
                except Exception:
                    pass
                random_delay(15, 40)

            # Save (strong algorithm signal)
            if can_act(data, "saves", limits.get("saves", 6)):
                try:
                    cl.media_save(media_id)
                    record_action(data, "saves", media_id)
                    stats["saves"] += 1
                    log.debug("Saved %s by @%s", media_id, target_handle)
                except Exception:
                    pass
                random_delay(10, 30)

        # Comment on the LATEST post only (max 1 comment per target per session)
        if medias and can_act(data, "comments", limits.get("comments", 6)):
            latest = medias[0]
            caption = str(getattr(latest, "caption_text", "") or "")
            comment_text = _generate_satellite_comment(cfg, caption, target_name)
            try:
                cl.media_comment(str(latest.pk), comment_text)
                record_action(data, "comments", str(latest.pk))
                stats["comments"] += 1
                log.info("Commented on @%s: %s", target_handle, comment_text[:50])
            except Exception as exc:
                log.warning("Comment failed on @%s: %s", target_handle, exc)
            random_delay(20, 50)

        # View their stories
        try:
            stories = cl.user_stories(int(user_id))
            for story in stories[:3]:
                if can_act(data, "story_views", limits.get("story_views", 20)):
                    try:
                        cl.story_seen([story.pk])
                        record_action(data, "story_views", str(story.pk))
                        stats["story_views"] += 1
                    except Exception:
                        pass
                    random_delay(5, 15)
        except Exception:
            pass

        # Pause between targets
        random_delay(30, 90)

    return stats


def run_satellite_background(cl, cfg: Config, data: dict[str, Any]) -> dict[str, int]:
    """Light background engagement to make the satellite look human.

    Browse explore, view some stories, like a few posts — nothing aggressive.
    """
    persona = get_persona()
    bg_hashtags = persona.get("background_hashtags", ["lifestyle", "motivation"])
    limits = persona.get("engagement", {}).get("daily_limits", {})

    stats = {"likes": 0, "story_views": 0}

    # Browse 1 random hashtag
    tag = random.choice(bg_hashtags)
    try:
        medias = cl.hashtag_medias_recent_v1(tag, amount=5)
        browse_count = random.randint(2, 4)
        for media in medias[:browse_count]:
            if can_act(data, "likes", limits.get("likes", 40)):
                try:
                    cl.media_like(str(media.pk))
                    record_action(data, "likes", str(media.pk))
                    stats["likes"] += 1
                except Exception:
                    pass
                random_delay(15, 45)
    except Exception as exc:
        log.debug("Background hashtag browse failed: %s", exc)

    # View a few timeline stories
    try:
        reels = cl.get_reels_tray_feed()
        if hasattr(reels, 'items'):
            story_items = list(reels.items)[:5]
        else:
            story_items = list(reels)[:5] if reels else []
        view_count = random.randint(2, 4)
        for reel in story_items[:view_count]:
            if can_act(data, "story_views", limits.get("story_views", 20)):
                try:
                    cl.story_seen([reel.pk] if hasattr(reel, 'pk') else [])
                    record_action(data, "story_views", str(getattr(reel, 'pk', 'unknown')))
                    stats["story_views"] += 1
                except Exception:
                    pass
                random_delay(5, 15)
    except Exception as exc:
        log.debug("Background story viewing failed: %s", exc)

    return stats


def run_satellite_session(cfg: Config, session_type: str) -> dict[str, int]:
    """Main entry point for satellite account sessions."""
    persona = get_persona()

    # Random session skip (20% of the time, do nothing — looks more human)
    skip_prob = persona.get("engagement", {}).get("session_skip_probability", 0.20)
    if random.random() < skip_prob:
        log.info("Satellite session skipped (random skip for human-like behavior)")
        return {"skipped": 1}

    # Extended startup jitter for satellites (2-8 minutes)
    jitter_range = persona.get("engagement", {}).get("startup_jitter_range", [120, 480])
    jitter = random.uniform(*jitter_range)
    log.info("Satellite startup jitter: %.0fs", jitter)
    time.sleep(jitter)

    # Load state
    data = load_log(str(LOG_FILE))

    try:
        cl = _get_client(cfg)
    except Exception as exc:
        log.error("Satellite client login failed: %s", exc)
        return {"error": str(exc)}

    try:
        if session_type == "sat_boost":
            stats = run_satellite_boost(cl, cfg, data)
        elif session_type == "sat_background":
            stats = run_satellite_background(cl, cfg, data)
        else:
            log.warning("Unknown satellite session type: %s", session_type)
            stats = {}
    finally:
        save_log(str(LOG_FILE), data)

    log.info("Satellite session '%s' complete: %s", session_type, stats)
    return stats
