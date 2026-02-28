#!/usr/bin/env python3
"""Engagement automation — human-like browsing with likes, comments, follows, stories."""

from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from config import Config, BASE_DIR
import instagrapi_patch  # noqa: F401 — applies monkey-patches on import
from publisher import _get_client
from rate_limiter import (
    LOG_FILE,
    action_delay,
    browsing_pause,
    can_act,
    daily_summary,
    load_log,
    maybe_abort_session,
    random_delay,
    record_action,
    reset_session_fatigue,
    save_log,
    session_startup_jitter,
    should_skip_session,
)

log = logging.getLogger(__name__)

# Persistent files
POSTS_PER_HASHTAG = 10          # conservative — casual browsing
UNFOLLOW_DAYS = 3  # unfollow after this many days


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_hashtags(raw: str) -> list[str]:
    """Parse comma-separated hashtag string, strip '#' prefixes."""
    return [t.strip().lstrip("#").lower() for t in raw.split(",") if t.strip()]


def _should_skip_post() -> bool:
    """Randomly skip some posts — humans don't engage with everything.

    ~22% skip rate: scroll past without any action.
    """
    return random.random() < 0.22


def _randomize_session_size(base: int) -> int:
    """Vary session size by ±50% so no two sessions look identical."""
    lo = max(2, int(base * 0.5))
    hi = int(base * 1.5)
    return random.randint(lo, hi)


def _browse_before_engage(cl: Any, user_id: str) -> None:
    """View a user's profile before engaging — humans check who they're interacting with."""
    try:
        cl.user_info(int(user_id))
        # Pause like reading their bio + scrolling their grid
        time.sleep(random.uniform(3, 10))
    except Exception:
        pass


def _simulate_scrolling(cl: Any, count: int = 0) -> None:
    """Simulate passive scrolling — watching content without engaging.

    Real humans spend most of their time just watching, not liking.
    This makes the action density more natural (fewer actions per minute).
    """
    if count <= 0:
        count = random.randint(1, 4)
    for _ in range(count):
        browsing_pause()


def _maybe_save_post(cl: Any, media_pk: Any, data: dict, stats: dict) -> None:
    """Occasionally save a post — strong interest signal, very safe action.

    ~8% of viewed posts get saved. Saves are NOT rate-limited by IG
    and signal genuine interest to the algorithm.
    """
    if random.random() < 0.08:
        try:
            cl.media_save(media_pk)
            stats["saves"] = stats.get("saves", 0) + 1
            log.debug("Saved post %s", media_pk)
        except Exception:
            pass


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


def _mine_targets(cl: Any, hashtags: list[str], amount: int = POSTS_PER_HASHTAG) -> list[Any]:
    """Fetch recent posts from a random hashtag."""
    if not hashtags:
        return []
    tag = random.choice(hashtags)
    log.info("Mining hashtag: #%s", tag)
    try:
        medias = cl.hashtag_medias_recent(tag, amount=amount)
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
    """Maybe view a user's stories — humans don't watch every story.

    ~50% chance to view stories, ~15% chance to like.
    """
    if random.random() > 0.50:
        return  # skip most stories
    try:
        stories = cl.user_stories(int(user_id))
        if stories:
            # Watch 1-2 stories, not all of them
            to_watch = stories[:random.randint(1, min(2, len(stories)))]
            cl.story_seen([s.pk for s in to_watch])
            record_action(data, "story_views", user_id)
            stats["story_views"] = stats.get("story_views", 0) + 1
            log.debug("Viewed %d stories of user %s", len(to_watch), user_id)
            # Pause like actually watching each story
            time.sleep(random.uniform(4, 12))
            # Like ~15% of stories
            if random.random() < 0.15:
                try:
                    cl.story_like(to_watch[0].pk)
                    stats["story_likes"] = stats.get("story_likes", 0) + 1
                except Exception:
                    pass
    except Exception as exc:
        log.debug("Story view failed for %s: %s", user_id, exc)


# ---------------------------------------------------------------------------
# Feature: Auto-unfollow after N days
# ---------------------------------------------------------------------------

def run_auto_unfollow(cl: Any, data: dict[str, Any]) -> int:
    """Unfollow users we followed more than UNFOLLOW_DAYS ago. Returns count."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=UNFOLLOW_DAYS)
    unfollowed = 0
    daily_limit = 30  # conservative — unfollows are monitored

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

    candidates = list(dict.fromkeys(candidates))
    random.shuffle(candidates)

    for user_id in candidates[:daily_limit]:
        if maybe_abort_session():
            break
        try:
            cl.user_unfollow(int(user_id))
            record_action(data, "unfollows", user_id)
            unfollowed += 1
            log.debug("Unfollowed user %s", user_id)
            action_delay("unfollows")
        except Exception as exc:
            log.warning("Unfollow failed for %s: %s", user_id, exc)

    if unfollowed:
        log.info("Auto-unfollowed %d users (>%d days old)", unfollowed, UNFOLLOW_DAYS)
    return unfollowed


# ---------------------------------------------------------------------------
# Feature: Track followers
# ---------------------------------------------------------------------------

def _load_followers(path: Path = BASE_DIR / "followers.json") -> set[str]:
    if not path.exists():
        return set()
    try:
        with open(path) as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_followers(ids: set[str], path: Path = BASE_DIR / "followers.json") -> None:
    with open(path, "w") as f:
        json.dump(sorted(ids), f)


# ---------------------------------------------------------------------------
# Feature: Reply to comments on own recent posts
# ---------------------------------------------------------------------------

def run_reply_to_comments(cl: Any, cfg: Config, data: dict[str, Any]) -> int:
    """Reply to comments on our own recent posts. Returns reply count."""
    replied = 0
    daily_reply_limit = 25  # replies on own posts are safe

    try:
        my_id = cl.user_id
        medias = cl.user_medias(my_id, amount=5)
    except Exception as exc:
        log.warning("Could not fetch own media for replies: %s", exc)
        return 0

    replied_set: set[str] = {
        a["target"] for a in data.get("actions", []) if a.get("type") == "replies"
    }

    for media in medias:
        if replied >= daily_reply_limit:
            break
        if maybe_abort_session():
            break

        taken_at = getattr(media, "taken_at", None)
        if taken_at:
            age = datetime.now(timezone.utc) - taken_at.replace(tzinfo=timezone.utc)
            if age > timedelta(hours=48):
                continue

        try:
            comments = cl.media_comments(media.pk, amount=15)
        except Exception as exc:
            log.debug("Could not fetch comments for %s: %s", media.pk, exc)
            continue

        my_caption = str(getattr(media, "caption_text", "") or "")

        for comment in comments:
            if replied >= daily_reply_limit:
                break
            comment_id = str(comment.pk)
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
                action_delay("replies")
            except Exception as exc:
                log.warning("Reply failed for comment %s: %s", comment_id, exc)

    if replied:
        log.info("Replied to %d comments on own posts", replied)
    return replied


# ---------------------------------------------------------------------------
# Feature: Explore page engagement
# ---------------------------------------------------------------------------

def run_explore_engagement(cl: Any, cfg: Config, data: dict[str, Any]) -> dict[str, int]:
    """Like/comment on Explore feed — mimics casual scrolling.

    Key pattern: mostly just watching, occasional like, rare comment.
    """
    stats: dict[str, int] = {"explore_likes": 0, "explore_comments": 0}
    explore_limit = _randomize_session_size(12)  # casual browsing

    try:
        medias = cl.explore_reels(amount=explore_limit + 8)
        log.info("Fetched %d reels from Explore", len(medias))
    except Exception as exc:
        log.warning("Could not fetch Explore page: %s", exc)
        return stats

    # Session warmup: first 2-3 items, just watch (no engagement)
    warmup_count = random.randint(2, 4)

    for i, media in enumerate(medias[:explore_limit]):
        if maybe_abort_session():
            log.info("Aborting explore session early (boredom)")
            break

        # Skip some posts
        if _should_skip_post():
            time.sleep(random.uniform(1, 5))
            continue

        media_id = str(media.pk)

        # Watch the reel/post (variable time based on content)
        time.sleep(random.uniform(4, 18))

        # Warmup phase — just watch, no actions
        if i < warmup_count:
            _simulate_scrolling(cl, random.randint(0, 2))
            continue

        # Like (~65% of non-skipped posts)
        if random.random() < 0.65 and can_act(data, "likes", cfg.engagement_daily_likes):
            try:
                cl.media_like(media.pk)
                record_action(data, "likes", media_id)
                stats["explore_likes"] += 1
            except Exception as exc:
                log.debug("Explore like failed: %s", exc)

        # Maybe save
        _maybe_save_post(cl, media.pk, data, stats)

        # Comment rarely (~8% — explore is more passive)
        if (cfg.engagement_comment_enabled
                and random.random() < 0.08
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

        # Simulate natural scrolling pace
        if random.random() < 0.3:
            _simulate_scrolling(cl, random.randint(1, 3))
        action_delay("likes")

    if stats["explore_likes"] or stats["explore_comments"]:
        log.info("Explore engagement: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# Core hashtag engagement loop
# ---------------------------------------------------------------------------

def _run_hashtag_engagement(
    cl: Any, cfg: Config, data: dict[str, Any], stats: dict[str, int],
    max_posts: int = 12,
) -> None:
    """Like/comment/follow from hashtag posts — mimics real browsing.

    Human-like patterns:
    - Browse only 1 hashtag per session (focused searching)
    - Skip ~22% of posts
    - View profiles before following
    - Comment rarely (~10%) — only posts that resonate
    - Follow selectively (~20%) — check profile first
    - Vary session sizes ±50%
    - Session warmup: first few posts, just look
    - Random early exit (got bored)
    """
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

    # Browse just 1 hashtag — humans search one topic at a time
    tag = random.choice(hashtags)
    medias = _mine_targets(cl, [tag])

    random.shuffle(medias)
    seen_pks: set[str] = set()
    unique_medias = []
    for m in medias:
        pk = str(m.pk)
        if pk not in seen_pks:
            seen_pks.add(pk)
            unique_medias.append(m)

    actual_max = _randomize_session_size(max_posts)
    warmup_count = random.randint(1, 3)

    for i, media in enumerate(unique_medias[:actual_max]):
        if maybe_abort_session():
            log.info("Aborting hashtag session early (distraction)")
            break

        # Skip some posts
        if _should_skip_post():
            time.sleep(random.uniform(1, 4))
            continue

        media_id = str(media.pk)
        user_id = str(media.user.pk) if media.user else None

        # Pause like actually looking at the post
        time.sleep(random.uniform(3, 12))

        # Warmup phase — just browse, no actions
        if i < warmup_count:
            _simulate_scrolling(cl, random.randint(0, 1))
            continue

        # Like (most common action — ~70% of non-skipped, non-warmup posts)
        if random.random() < 0.70 and can_act(data, "likes", like_limit):
            try:
                cl.media_like(media.pk)
                record_action(data, "likes", media_id)
                stats["likes"] = stats.get("likes", 0) + 1
            except Exception as exc:
                log.warning("Like failed for %s: %s", media_id, exc)

        # Maybe save
        _maybe_save_post(cl, media.pk, data, stats)

        # Comment on ~10% of posts
        if (cfg.engagement_comment_enabled
                and random.random() < 0.10
                and can_act(data, "comments", comment_limit)):
            caption_text = str(media.caption_text or "") if hasattr(media, "caption_text") else ""
            comment = _generate_comment(cfg, caption_text)
            if comment:
                try:
                    cl.media_comment(media.pk, comment)
                    record_action(data, "comments", media_id)
                    stats["comments"] = stats.get("comments", 0) + 1
                except Exception as exc:
                    log.warning("Comment failed for %s: %s", media_id, exc)

        # Follow ~20% of users (browse profile first)
        if (cfg.engagement_follow_enabled
                and user_id
                and random.random() < 0.20
                and can_act(data, "follows", follow_limit)):
            _browse_before_engage(cl, user_id)
            try:
                cl.user_follow(int(user_id))
                record_action(data, "follows", user_id)
                stats["follows"] = stats.get("follows", 0) + 1
            except Exception as exc:
                log.warning("Follow failed for %s: %s", user_id, exc)

        # View stories sometimes
        if user_id and can_act(data, "story_views", story_limit):
            _view_user_stories(cl, user_id, data, stats)

        save_log(LOG_FILE, data)

        # Variable-pace scrolling between posts
        if random.random() < 0.25:
            _simulate_scrolling(cl, random.randint(1, 2))

        action_delay("likes")

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

SESSION_TYPES = [
    "morning",     # likes + follows from hashtags (catch early risers)
    "replies",     # reply to comments on own posts (algorithm boost)
    "hashtags",    # hashtag engagement (like/comment/follow/stories)
    "explore",     # explore page engagement
    "maintenance", # unfollow old follows
    "stories",     # repost past posts as stories + add to highlights
    "report",      # end-of-day summary report
    "full",        # all phases (backward compat)
]


def run_session(cfg: Config, session_type: str = "full") -> dict[str, int]:
    """Run a focused engagement session — designed to mimic human phone checks.

    Each session is short (5-15 min), with randomized startup delay.
    20% of sessions are randomly skipped (simulating being busy).
    12% chance of aborting mid-session (getting bored/distracted).

    Session types:
      morning     - Light hashtag likes + follows (~8 posts)
      replies     - Reply to comments on own posts
      hashtags    - Hashtag engagement (like/comment/follow/stories)
      explore     - Explore page casual scrolling
      maintenance - Auto-unfollow non-followers
      stories     - Repost past posts as stories
      report      - Daily report
      full        - All phases (used sparingly)
    """
    # Reset fatigue for new session
    reset_session_fatigue()

    # Random session skip — simulates being busy/away
    if session_type not in ("report", "maintenance") and should_skip_session():
        log.info("Session '%s' skipped (simulating being busy)", session_type)
        return {}

    data = load_log(LOG_FILE)
    stats: dict[str, int] = {}

    # Startup jitter — don't run at exact cron times
    if session_type not in ("report",):
        session_startup_jitter()

    cl = _get_client(cfg)
    log.info("Starting engagement session: %s", session_type)

    if session_type == "morning":
        # Morning: lighter session
        _run_hashtag_engagement(cl, cfg, data, stats, max_posts=8)

    elif session_type == "replies":
        stats["replies"] = run_reply_to_comments(cl, cfg, data)
        save_log(LOG_FILE, data)

    elif session_type == "hashtags":
        _run_hashtag_engagement(cl, cfg, data, stats, max_posts=12)

    elif session_type == "explore":
        explore_stats = run_explore_engagement(cl, cfg, data)
        stats.update(explore_stats)

    elif session_type == "maintenance":
        stats["unfollows"] = run_auto_unfollow(cl, data)
        save_log(LOG_FILE, data)

    elif session_type == "stories":
        from stories import run_story_session
        story_stats = run_story_session(cl, cfg)
        stats.update(story_stats)

    elif session_type == "report":
        from report import run_daily_report
        run_daily_report()
        stats["report"] = 1

    else:  # "full" — all phases
        stats["unfollows"] = run_auto_unfollow(cl, data)
        save_log(LOG_FILE, data)
        random_delay(60, 180)
        stats["replies"] = run_reply_to_comments(cl, cfg, data)
        save_log(LOG_FILE, data)
        random_delay(60, 180)
        _run_hashtag_engagement(cl, cfg, data, stats, max_posts=15)
        random_delay(60, 180)
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
