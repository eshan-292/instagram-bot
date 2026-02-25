#!/usr/bin/env python3
"""Engagement automation — like, comment, follow, unfollow, DM, explore, reply."""

from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from config import Config, BASE_DIR
import instagrapi_patch  # noqa: F401 — applies monkey-patches on import
from publisher import _get_client
from rate_limiter import (
    LOG_FILE,
    can_act,
    daily_summary,
    load_log,
    random_delay,
    record_action,
    save_log,
)

log = logging.getLogger(__name__)

# Persistent files
POSTS_PER_HASHTAG = 10
FOLLOWERS_FILE = BASE_DIR / "followers.json"
UNFOLLOW_DAYS = 3  # unfollow after this many days


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_hashtags(raw: str) -> list[str]:
    """Parse comma-separated hashtag string, strip '#' prefixes."""
    return [t.strip().lstrip("#").lower() for t in raw.split(",") if t.strip()]


def _generate_comment(cfg: Config, caption_text: str) -> str | None:
    """Use Gemini to generate a short, context-aware comment on a post."""
    if not cfg.gemini_api_key:
        return None
    from gemini_helper import generate
    prompt = (
        "You are Maya Varma, a 23-year-old Indian fashion influencer in Mumbai. "
        "Write a short, genuine Instagram comment (1 sentence, max 15 words) on this post. "
        "Be warm, specific to the content, and authentic — NOT generic spam. "
        "No hashtags, no emojis spam (max 1 emoji). No 'nice pic' or 'great post' type comments. "
        "Just the comment text, nothing else.\n\n"
        f"Post caption: {caption_text[:300]}"
    )
    comment = generate(cfg.gemini_api_key, prompt, cfg.gemini_model)
    if comment and 3 < len(comment) < 150:
        return comment
    return None


def _generate_reply(cfg: Config, original_caption: str, their_comment: str) -> str | None:
    """Generate a reply to a comment on our own post."""
    if not cfg.gemini_api_key:
        return None
    from gemini_helper import generate
    prompt = (
        "You are Maya Varma, a 23-year-old Indian fashion influencer in Mumbai. "
        "Someone commented on your post. Write a warm, short reply (max 12 words). "
        "Be genuine and grateful but stay in character — bold, confident, witty. "
        "No hashtags. Max 1 emoji. Just the reply text.\n\n"
        f"Your caption: {original_caption[:200]}\n"
        f"Their comment: {their_comment[:200]}"
    )
    reply = generate(cfg.gemini_api_key, prompt, cfg.gemini_model)
    if reply and 2 < len(reply) < 100:
        return reply
    return None


def _generate_dm(cfg: Config, username: str) -> str | None:
    """Generate a welcome DM for a new follower."""
    if not cfg.gemini_api_key:
        return None
    from gemini_helper import generate
    prompt = (
        "You are Maya Varma, a 23-year-old Indian fashion influencer in Mumbai. "
        "A new person just followed you on Instagram. Write a short, warm welcome DM "
        "(2-3 sentences max). Be genuine, inviting, and casual — not salesy. "
        "Mention you post fashion/style content. End with something engaging "
        "(like asking about their style or what they liked). "
        "No hashtags. Max 1-2 emojis. Just the message text.\n\n"
        f"Their username: @{username}"
    )
    dm = generate(cfg.gemini_api_key, prompt, cfg.gemini_model)
    if dm and 10 < len(dm) < 500:
        return dm
    return None


def _mine_targets(cl: Any, hashtags: list[str], amount: int = POSTS_PER_HASHTAG) -> list[Any]:
    """Fetch recent posts from a random hashtag."""
    if not hashtags:
        return []
    tag = random.choice(hashtags)
    log.info("Mining hashtag: #%s", tag)
    try:
        medias = cl.hashtag_medias_recent(tag, amount=amount)
        # Filter out None items (from extract_media_v1 fallback) and items without .pk
        medias = [m for m in medias if m is not None and getattr(m, "pk", None)]
        log.info("Found %d posts from #%s", len(medias), tag)
        return medias
    except Exception as exc:
        log.warning("Failed to fetch #%s: %s", tag, exc)
        try:
            medias = cl.hashtag_medias_top(tag, amount=amount)
            medias = [m for m in medias if m is not None and getattr(m, "pk", None)]
            log.info("Fallback: found %d top posts from #%s", len(medias), tag)
            return medias
        except Exception as exc2:
            log.warning("Fallback also failed for #%s: %s", tag, exc2)
        return []


def _view_user_stories(cl: Any, user_id: str, data: dict, stats: dict) -> None:
    """View a user's stories — sends them a profile visit notification."""
    try:
        stories = cl.user_stories(int(user_id))
        if stories:
            cl.story_seen([stories[0].pk])
            record_action(data, "story_views", user_id)
            stats["story_views"] = stats.get("story_views", 0) + 1
            log.debug("Viewed story of user %s", user_id)
    except Exception as exc:
        log.debug("Story view failed for %s: %s", user_id, exc)


# ---------------------------------------------------------------------------
# Feature: Auto-unfollow after N days
# ---------------------------------------------------------------------------

def run_auto_unfollow(cl: Any, data: dict[str, Any]) -> int:
    """Unfollow users we followed more than UNFOLLOW_DAYS ago. Returns count."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=UNFOLLOW_DAYS)
    unfollowed = 0
    daily_limit = 30  # conservative unfollow limit per run

    # Find follow actions older than cutoff that haven't been unfollowed yet
    unfollowed_set: set[str] = {
        a["target"] for a in data.get("actions", []) if a.get("type") == "unfollows"
    }

    candidates = []
    for action in data.get("actions", []):
        if action.get("type") != "follows":
            continue
        target = action.get("target", "")
        if not target or target in unfollowed_set:
            continue
        try:
            followed_at = datetime.fromisoformat(
                action["at"].replace("Z", "+00:00")
            )
        except (KeyError, ValueError):
            continue
        if followed_at < cutoff:
            candidates.append(target)

    # Deduplicate
    candidates = list(dict.fromkeys(candidates))
    random.shuffle(candidates)

    for user_id in candidates[:daily_limit]:
        try:
            cl.user_unfollow(int(user_id))
            record_action(data, "unfollows", user_id)
            unfollowed += 1
            log.debug("Unfollowed user %s", user_id)
            random_delay(15, 45)
        except Exception as exc:
            log.warning("Unfollow failed for %s: %s", user_id, exc)

    if unfollowed:
        log.info("Auto-unfollowed %d users (>%d days old)", unfollowed, UNFOLLOW_DAYS)
    return unfollowed


# ---------------------------------------------------------------------------
# Feature: DM welcome to new followers
# ---------------------------------------------------------------------------

def _load_followers(path: Path = FOLLOWERS_FILE) -> set[str]:
    if not path.exists():
        return set()
    try:
        with open(path) as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_followers(ids: set[str], path: Path = FOLLOWERS_FILE) -> None:
    with open(path, "w") as f:
        json.dump(sorted(ids), f)


def run_welcome_dms(cl: Any, cfg: Config) -> int:
    """Send welcome DMs to new followers. Returns count sent."""
    try:
        my_id = cl.user_id
        current = cl.user_followers(my_id, amount=200)
    except Exception as exc:
        log.warning("Could not fetch followers: %s", exc)
        return 0

    current_ids = {str(uid) for uid in current.keys()}
    known = _load_followers()

    # First run: just store current followers, don't DM everyone
    if not known:
        _save_followers(current_ids)
        log.info("Stored %d existing followers (first run, no DMs sent)", len(current_ids))
        return 0

    new_ids = current_ids - known
    if not new_ids:
        log.debug("No new followers detected")
        _save_followers(current_ids | known)
        return 0

    sent = 0
    daily_dm_limit = 10  # conservative to avoid spam flags

    for uid in list(new_ids)[:daily_dm_limit]:
        user = current.get(int(uid))
        username = user.username if user else "friend"
        dm_text = _generate_dm(cfg, username)
        if not dm_text:
            continue
        try:
            cl.direct_send(dm_text, user_ids=[int(uid)])
            sent += 1
            log.info("Welcome DM sent to @%s", username)
            random_delay(30, 60)
        except Exception as exc:
            log.warning("DM failed for @%s: %s", username, exc)

    # Update stored followers
    _save_followers(current_ids | known)
    if sent:
        log.info("Sent %d welcome DMs to new followers", sent)
    return sent


# ---------------------------------------------------------------------------
# Feature: Reply to comments on own recent posts
# ---------------------------------------------------------------------------

def run_reply_to_comments(cl: Any, cfg: Config, data: dict[str, Any]) -> int:
    """Reply to comments on our own recent posts. Returns reply count."""
    replied = 0
    daily_reply_limit = 20

    try:
        my_id = cl.user_id
        # Get our recent media (last 5 posts)
        medias = cl.user_medias(my_id, amount=5)
    except Exception as exc:
        log.warning("Could not fetch own media for replies: %s", exc)
        return 0

    # Track which comments we've already replied to
    replied_set: set[str] = {
        a["target"] for a in data.get("actions", []) if a.get("type") == "replies"
    }

    for media in medias:
        if replied >= daily_reply_limit:
            break

        # Only reply to posts from last 24 hours (first-hour engagement boost)
        taken_at = getattr(media, "taken_at", None)
        if taken_at:
            age = datetime.now(timezone.utc) - taken_at.replace(tzinfo=timezone.utc)
            if age > timedelta(hours=24):
                continue

        try:
            comments = cl.media_comments(media.pk, amount=20)
        except Exception as exc:
            log.debug("Could not fetch comments for %s: %s", media.pk, exc)
            continue

        my_caption = str(getattr(media, "caption_text", "") or "")

        for comment in comments:
            if replied >= daily_reply_limit:
                break
            comment_id = str(comment.pk)
            # Skip our own comments and already-replied ones
            if str(getattr(comment.user, "pk", "")) == str(my_id):
                continue
            if comment_id in replied_set:
                continue

            comment_text = str(getattr(comment, "text", "") or "")
            if len(comment_text) < 3:
                continue

            reply = _generate_reply(cfg, my_caption, comment_text)
            if not reply:
                continue

            try:
                cl.media_comment(media.pk, reply, replied_to_comment_id=comment.pk)
                record_action(data, "replies", comment_id)
                replied_set.add(comment_id)
                replied += 1
                log.debug("Replied to comment %s: %s", comment_id, reply[:40])
                random_delay(20, 50)
            except Exception as exc:
                log.warning("Reply failed for comment %s: %s", comment_id, exc)

    if replied:
        log.info("Replied to %d comments on own posts", replied)
    return replied


# ---------------------------------------------------------------------------
# Feature: Explore page engagement
# ---------------------------------------------------------------------------

def run_explore_engagement(cl: Any, cfg: Config, data: dict[str, Any]) -> dict[str, int]:
    """Like/comment on posts from the Explore feed. Returns action counts."""
    stats: dict[str, int] = {"explore_likes": 0, "explore_comments": 0}
    explore_limit = 15  # posts to engage with from explore

    try:
        # Fetch explore reels (returns List[Media], unlike explore_page which returns raw dict)
        medias = cl.explore_reels(amount=explore_limit)
        log.info("Fetched %d reels from Explore", len(medias))
    except Exception as exc:
        log.warning("Could not fetch Explore page: %s", exc)
        return stats

    for media in medias[:explore_limit]:
        media_id = str(media.pk)

        # Like
        if can_act(data, "likes", cfg.engagement_daily_likes):
            try:
                cl.media_like(media.pk)
                record_action(data, "likes", media_id)
                stats["explore_likes"] += 1
            except Exception as exc:
                log.debug("Explore like failed: %s", exc)

        # Comment on ~30% of explore posts
        if (cfg.engagement_comment_enabled
                and random.random() < 0.3
                and can_act(data, "comments", cfg.engagement_daily_comments)):
            caption_text = str(getattr(media, "caption_text", "") or "")
            comment = _generate_comment(cfg, caption_text)
            if comment:
                try:
                    cl.media_comment(media.pk, comment)
                    record_action(data, "comments", media_id)
                    stats["explore_comments"] += 1
                except Exception as exc:
                    log.debug("Explore comment failed: %s", exc)

        save_log(LOG_FILE, data)
        random_delay(15, 45)

    if stats["explore_likes"] or stats["explore_comments"]:
        log.info("Explore engagement: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# Core hashtag engagement loop (used by both full and session runs)
# ---------------------------------------------------------------------------

def _run_hashtag_engagement(
    cl: Any, cfg: Config, data: dict[str, Any], stats: dict[str, int],
    max_posts: int = 30,
) -> None:
    """Like/comment/follow from hashtag posts. Shared by full and session runs."""
    hashtags = _parse_hashtags(cfg.engagement_hashtags)
    if not hashtags:
        return

    like_limit = cfg.engagement_daily_likes
    comment_limit = cfg.engagement_daily_comments
    follow_limit = cfg.engagement_daily_follows
    story_limit = 80

    if (
        not can_act(data, "likes", like_limit)
        and not can_act(data, "comments", comment_limit)
        and not can_act(data, "follows", follow_limit)
    ):
        log.info("All daily limits reached: %s", daily_summary(data))
        return

    all_medias: list[Any] = []
    tags_to_try = random.sample(hashtags, min(3, len(hashtags)))
    for tag in tags_to_try:
        medias = _mine_targets(cl, [tag])
        all_medias.extend(medias)
    random.shuffle(all_medias)
    seen_pks: set[str] = set()
    medias = []
    for m in all_medias:
        pk = str(m.pk)
        if pk not in seen_pks:
            seen_pks.add(pk)
            medias.append(m)

    for media in medias[:max_posts]:
        media_id = str(media.pk)
        user_id = str(media.user.pk) if media.user else None

        if can_act(data, "likes", like_limit):
            try:
                cl.media_like(media.pk)
                record_action(data, "likes", media_id)
                stats["likes"] = stats.get("likes", 0) + 1
            except Exception as exc:
                log.warning("Like failed for %s: %s", media_id, exc)

        if cfg.engagement_comment_enabled and can_act(data, "comments", comment_limit):
            caption_text = str(media.caption_text or "") if hasattr(media, "caption_text") else ""
            comment = _generate_comment(cfg, caption_text)
            if comment:
                try:
                    cl.media_comment(media.pk, comment)
                    record_action(data, "comments", media_id)
                    stats["comments"] = stats.get("comments", 0) + 1
                except Exception as exc:
                    log.warning("Comment failed for %s: %s", media_id, exc)

        if cfg.engagement_follow_enabled and user_id and can_act(data, "follows", follow_limit):
            try:
                cl.user_follow(int(user_id))
                record_action(data, "follows", user_id)
                stats["follows"] = stats.get("follows", 0) + 1
            except Exception as exc:
                log.warning("Follow failed for %s: %s", user_id, exc)

        if user_id and can_act(data, "story_views", story_limit):
            _view_user_stories(cl, user_id, data, stats)

        save_log(LOG_FILE, data)
        random_delay(30, 90)

        if (
            not can_act(data, "likes", like_limit)
            and not can_act(data, "comments", comment_limit)
            and not can_act(data, "follows", follow_limit)
        ):
            log.info("Daily limits reached, stopping hashtag engagement")
            break


# ---------------------------------------------------------------------------
# Session-based engagement (for scheduler — short focused bursts)
# ---------------------------------------------------------------------------

# Session types for the scheduler to call throughout the day
SESSION_TYPES = [
    "morning",     # likes + follows from hashtags (catch early risers)
    "replies",     # reply to comments on own posts (algorithm boost)
    "hashtags",    # full hashtag engagement (like/comment/follow/stories)
    "explore",     # explore page engagement
    "maintenance", # unfollow old follows + welcome DMs
    "full",        # all phases (backward compat)
]


def run_session(cfg: Config, session_type: str = "full") -> dict[str, int]:
    """Run a focused engagement session. Shorter than full run.

    Session types:
      morning     - Light hashtag likes + follows (10 posts, fast)
      replies     - Reply to comments on own posts
      hashtags    - Full hashtag engagement (like/comment/follow/stories)
      explore     - Explore page engagement
      maintenance - Auto-unfollow + welcome DMs
      full        - All phases (original behavior)
    """
    data = load_log(LOG_FILE)
    stats: dict[str, int] = {}
    cl = _get_client(cfg)

    log.info("Starting engagement session: %s", session_type)

    if session_type == "morning":
        _run_hashtag_engagement(cl, cfg, data, stats, max_posts=10)

    elif session_type == "replies":
        stats["replies"] = run_reply_to_comments(cl, cfg, data)
        save_log(LOG_FILE, data)

    elif session_type == "hashtags":
        _run_hashtag_engagement(cl, cfg, data, stats, max_posts=20)

    elif session_type == "explore":
        explore_stats = run_explore_engagement(cl, cfg, data)
        stats.update(explore_stats)

    elif session_type == "maintenance":
        stats["unfollows"] = run_auto_unfollow(cl, data)
        save_log(LOG_FILE, data)
        stats["dms"] = run_welcome_dms(cl, cfg)

    else:  # "full" — all phases
        stats["unfollows"] = run_auto_unfollow(cl, data)
        save_log(LOG_FILE, data)
        stats["replies"] = run_reply_to_comments(cl, cfg, data)
        save_log(LOG_FILE, data)
        stats["dms"] = run_welcome_dms(cl, cfg)
        _run_hashtag_engagement(cl, cfg, data, stats, max_posts=30)
        explore_stats = run_explore_engagement(cl, cfg, data)
        stats.update(explore_stats)

    save_log(LOG_FILE, data)
    log.info("Session '%s' done: %s (daily: %s)", session_type, stats, daily_summary(data))
    return stats


# ---------------------------------------------------------------------------
# Main engagement entry point (backward compat)
# ---------------------------------------------------------------------------

def run_engagement(cfg: Config) -> dict[str, int]:
    """Full engagement loop — runs all phases."""
    return run_session(cfg, "full")
