#!/usr/bin/env python3
"""Satellite account engagement — aggressive support for main accounts.

Satellite accounts exist to boost engagement signals for main accounts (Maya, Aryan).
They don't create content or publish — they:
  1. Like, comment on, save, and share main accounts' posts
  2. Like comments on main accounts' posts
  3. Reply to comments on main accounts' posts
  4. View and like main accounts' stories
  5. Repost main accounts' posts to their own stories
  6. Share main accounts' posts via DM to other satellites
  7. Run background engagement to look human
"""

from __future__ import annotations

import logging
import random
import tempfile
import time
from pathlib import Path
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
        from gemini_helper import generate as ask_gemini
        result = ask_gemini(cfg.gemini_api_key, prompt, cfg.gemini_model)
        if result:
            return result.strip().strip('"')
    except Exception as exc:
        log.warning("Satellite comment gen failed: %s", exc)
    fallbacks = [
        "This is exactly what I needed to see today",
        "Saving this for later, so good",
        "Okay this actually goes hard",
        "Literally sent this to my friend",
        "The consistency is unmatched",
    ]
    return random.choice(fallbacks)


def _generate_reply(cfg: Config, comment_text: str, target_name: str) -> str:
    """Generate a reply to a comment on a main account's post."""
    persona = get_persona()
    tone = persona.get("voice", {}).get("tone", "friendly and genuine")

    prompt = (
        f"You are a casual Instagram user. Your vibe: {tone}.\n"
        f"Write a SHORT reply (1 sentence, max 10 words) to this comment on {target_name}'s post:\n"
        f'Comment: "{comment_text[:150]}"\n\n'
        "Rules:\n"
        "- Agree with or add to the comment\n"
        "- Sound natural, like a real person replying\n"
        "- Max 1 emoji\n"
        "- Do NOT repeat the comment\n\n"
        "Return ONLY the reply text."
    )

    try:
        from gemini_helper import generate as ask_gemini
        result = ask_gemini(cfg.gemini_api_key, prompt, cfg.gemini_model)
        if result:
            return result.strip().strip('"')
    except Exception as exc:
        log.warning("Reply gen failed: %s", exc)
    fallbacks = [
        "Fr fr 💯",
        "Couldn't agree more",
        "This right here",
        "Exactly what I was thinking",
        "So true",
    ]
    return random.choice(fallbacks)


def _get_other_satellite_user_ids(cl, current_persona_id: str) -> list[int]:
    """Look up Instagram user IDs for the other satellite accounts."""
    user_ids = []
    for sat_id in ["sat1", "sat2", "sat3"]:
        if sat_id == current_persona_id:
            continue
        try:
            sat_persona = load_persona(sat_id)
            handle = sat_persona.get("instagram_handle", "")
            if handle:
                user_info = cl.user_info_by_username_v1(handle)
                user_ids.append(int(user_info.pk))
        except Exception as exc:
            log.debug("Could not find satellite @%s: %s", sat_id, exc)
    return user_ids


def run_satellite_boost(cl, cfg: Config, data: dict[str, Any]) -> dict[str, int]:
    """Engage with main accounts' recent posts to boost their signals.

    For each boost target: like, save, comment, like comments, reply to comments,
    view + like stories, repost to story, share via DM.
    """
    persona = get_persona()
    targets = persona.get("boost_targets", [])
    limits = persona.get("engagement", {}).get("daily_limits", {})

    stats = {
        "likes": 0, "comments": 0, "saves": 0, "story_views": 0,
        "comment_likes": 0, "story_likes": 0, "story_reposts": 0,
        "dm_shares": 0, "replies": 0,
    }

    # Pre-fetch other satellite user IDs for DM sharing (once)
    other_sat_ids = []
    if can_act(data, "dm_shares", limits.get("dm_shares", 6)):
        try:
            other_sat_ids = _get_other_satellite_user_ids(cl, persona["id"])
        except Exception:
            pass

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

        # ── Like + Save each post ──
        for media in medias:
            media_id = str(media.pk)

            if can_act(data, "likes", limits.get("likes", 80)):
                try:
                    cl.media_like(media_id)
                    record_action(data, "likes", media_id)
                    stats["likes"] += 1
                    log.debug("Liked %s by @%s", media_id, target_handle)
                except Exception:
                    pass
                random_delay(10, 30)

            if can_act(data, "saves", limits.get("saves", 12)):
                try:
                    cl.media_save(media_id)
                    record_action(data, "saves", media_id)
                    stats["saves"] += 1
                    log.debug("Saved %s by @%s", media_id, target_handle)
                except Exception:
                    pass
                random_delay(8, 25)

            # ── Like comments on this post ──
            if can_act(data, "comment_likes", limits.get("comment_likes", 30)):
                try:
                    comments = cl.media_comments(media_id, amount=5)
                    for comment in comments[:3]:
                        if can_act(data, "comment_likes", limits.get("comment_likes", 30)):
                            try:
                                cl.comment_like(comment.pk)
                                record_action(data, "comment_likes", str(comment.pk))
                                stats["comment_likes"] += 1
                                log.debug("Liked comment by %s", getattr(comment, 'user', {}).get('username', '?') if isinstance(getattr(comment, 'user', None), dict) else '?')
                            except Exception:
                                pass
                            random_delay(5, 15)
                except Exception as exc:
                    log.debug("Comment fetch failed for %s: %s", media_id, exc)

        # ── Comment on the LATEST post ──
        if medias and can_act(data, "comments", limits.get("comments", 12)):
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
            random_delay(15, 40)

        # ── Reply to a comment on the latest post ──
        if medias and can_act(data, "comments", limits.get("comments", 12)):
            latest = medias[0]
            try:
                comments = cl.media_comments(str(latest.pk), amount=8)
                # Filter out own comments
                own_handle = persona.get("instagram_handle", "")
                eligible = [
                    c for c in comments
                    if hasattr(c, 'user') and getattr(c.user, 'username', '') != own_handle
                    and hasattr(c, 'text') and c.text
                ]
                if eligible:
                    target_comment = random.choice(eligible[:5])
                    reply_text = _generate_reply(cfg, target_comment.text, target_name)
                    try:
                        cl.media_comment(
                            str(latest.pk), reply_text,
                            replied_to_comment_id=target_comment.pk,
                        )
                        record_action(data, "comments", f"reply_{target_comment.pk}")
                        stats["replies"] += 1
                        log.info("Replied to comment on @%s: %s", target_handle, reply_text[:50])
                    except Exception as exc:
                        log.warning("Reply failed on @%s: %s", target_handle, exc)
                    random_delay(15, 40)
            except Exception as exc:
                log.debug("Could not fetch comments for reply: %s", exc)

        # ── View + Like their stories ──
        try:
            stories = cl.user_stories(int(user_id))
            for story in stories[:3]:
                if can_act(data, "story_views", limits.get("story_views", 40)):
                    try:
                        cl.story_seen([story.pk])
                        record_action(data, "story_views", str(story.pk))
                        stats["story_views"] += 1
                    except Exception:
                        pass
                    random_delay(3, 10)

                    # Like the story
                    if can_act(data, "story_likes", limits.get("story_likes", 20)):
                        try:
                            cl.story_like(story.pk)
                            record_action(data, "story_likes", str(story.pk))
                            stats["story_likes"] += 1
                            log.debug("Liked story by @%s", target_handle)
                        except Exception:
                            pass
                        random_delay(3, 8)
        except Exception:
            pass

        # ── Repost latest post to satellite's story ──
        if medias and can_act(data, "story_reposts", limits.get("story_reposts", 2)):
            latest = medias[0]
            try:
                # Download the media thumbnail
                media_info = cl.media_info(latest.pk)
                thumb_url = str(media_info.thumbnail_url or "")
                if not thumb_url and hasattr(media_info, 'image_versions2'):
                    # Try to get from resources
                    resources = getattr(media_info, 'resources', [])
                    if resources:
                        thumb_url = str(getattr(resources[0], 'thumbnail_url', ''))
                if thumb_url:
                    import urllib.request
                    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                    urllib.request.urlretrieve(thumb_url, tmp.name)
                    cl.photo_upload_to_story(tmp.name)
                    record_action(data, "story_reposts", str(latest.pk))
                    stats["story_reposts"] += 1
                    log.info("Reposted @%s's post to story", target_handle)
                    Path(tmp.name).unlink(missing_ok=True)
            except Exception as exc:
                log.debug("Story repost failed for @%s: %s", target_handle, exc)
            random_delay(10, 30)

        # ── Share post via DM to other satellites ──
        if medias and other_sat_ids and can_act(data, "dm_shares", limits.get("dm_shares", 6)):
            latest = medias[0]
            media_code = getattr(latest, 'code', '')
            if media_code:
                post_url = f"https://www.instagram.com/p/{media_code}/"
                for sat_uid in other_sat_ids:
                    if can_act(data, "dm_shares", limits.get("dm_shares", 6)):
                        try:
                            cl.direct_send(post_url, user_ids=[sat_uid])
                            record_action(data, "dm_shares", f"{latest.pk}_{sat_uid}")
                            stats["dm_shares"] += 1
                            log.info("Shared @%s's post via DM to %s", target_handle, sat_uid)
                        except Exception as exc:
                            log.debug("DM share failed: %s", exc)
                        random_delay(10, 25)

        # Pause between targets
        random_delay(20, 60)

    return stats


def run_satellite_background(cl, cfg: Config, data: dict[str, Any]) -> dict[str, int]:
    """Background engagement to make the satellite look human.

    Browse hashtags, view stories, like posts.
    """
    persona = get_persona()
    bg_hashtags = persona.get("background_hashtags", ["lifestyle", "motivation"])
    limits = persona.get("engagement", {}).get("daily_limits", {})

    stats = {"likes": 0, "story_views": 0, "comment_likes": 0}

    # Browse 2 random hashtags (more aggressive)
    for _ in range(2):
        tag = random.choice(bg_hashtags)
        try:
            medias = cl.hashtag_medias_recent_v1(tag, amount=8)
            browse_count = random.randint(3, 6)
            for media in medias[:browse_count]:
                if can_act(data, "likes", limits.get("likes", 80)):
                    try:
                        cl.media_like(str(media.pk))
                        record_action(data, "likes", str(media.pk))
                        stats["likes"] += 1
                    except Exception:
                        pass
                    random_delay(10, 30)

                # Like a comment on ~30% of posts
                if random.random() < 0.3 and can_act(data, "comment_likes", limits.get("comment_likes", 30)):
                    try:
                        comments = cl.media_comments(str(media.pk), amount=3)
                        if comments:
                            cl.comment_like(comments[0].pk)
                            record_action(data, "comment_likes", str(comments[0].pk))
                            stats["comment_likes"] += 1
                    except Exception:
                        pass
                    random_delay(5, 15)
        except Exception as exc:
            log.debug("Background hashtag browse failed: %s", exc)

    # View timeline stories
    try:
        reels = cl.get_reels_tray_feed()
        if hasattr(reels, 'items'):
            story_items = list(reels.items)[:8]
        else:
            story_items = list(reels)[:8] if reels else []
        view_count = random.randint(3, 6)
        for reel in story_items[:view_count]:
            if can_act(data, "story_views", limits.get("story_views", 40)):
                try:
                    cl.story_seen([reel.pk] if hasattr(reel, 'pk') else [])
                    record_action(data, "story_views", str(getattr(reel, 'pk', 'unknown')))
                    stats["story_views"] += 1
                except Exception:
                    pass
                random_delay(5, 12)
    except Exception as exc:
        log.debug("Background story viewing failed: %s", exc)

    return stats


def run_satellite_session(cfg: Config, session_type: str) -> dict[str, int]:
    """Main entry point for satellite account sessions."""
    persona = get_persona()

    # Brief startup jitter (30-90s) so sessions don't start at exact cron time
    jitter = random.uniform(30, 90)
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
