#!/usr/bin/env python3
"""Engagement automation — like, comment, follow, unfollow, DM, explore, reply.

Aggressive growth mode: maximize every action within safe limits.
"""

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
    can_act,
    daily_summary,
    load_log,
    random_delay,
    record_action,
    save_log,
    session_startup_jitter,
)

log = logging.getLogger(__name__)

# Persistent files
POSTS_PER_HASHTAG = 18          # aggressive — mine more per tag
FOLLOWERS_FILE = BASE_DIR / "followers.json"
UNFOLLOW_DAYS = 2  # unfollow after 2 days (was 3) — faster churn = more room for new follows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_hashtags(raw: str) -> list[str]:
    """Parse comma-separated hashtag string, strip '#' prefixes."""
    return [t.strip().lstrip("#").lower() for t in raw.split(",") if t.strip()]


def _should_skip_post() -> bool:
    """Randomly skip some posts — humans don't engage with everything they see.

    ~12% skip rate: lower than before — we want to maximize engagement actions.
    """
    return random.random() < 0.12


def _randomize_session_size(base: int) -> int:
    """Vary session size by ±30% so no two sessions look identical."""
    lo = max(3, int(base * 0.7))
    hi = int(base * 1.3)
    return random.randint(lo, hi)


def _browse_before_engage(cl: Any, user_id: str) -> None:
    """View a user's profile before engaging — humans check who they're interacting with.

    This adds a realistic delay and a profile view API call.
    """
    try:
        cl.user_info(int(user_id))
        # Short pause like reading their bio
        time.sleep(random.uniform(1.5, 4))
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
        "Be conversational — ask a question or share a specific reaction. "
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
        "Someone commented on your post. Write a warm, short reply (max 15 words). "
        "Be genuine and grateful but stay in character — bold, confident, witty. "
        "Ask them a question back to keep the conversation going (drives algorithm). "
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
        "You are Maya, a 23-year-old girl from Mumbai who posts fashion/style content. "
        "Someone just followed you. Send them a quick casual DM like a real person would — "
        "NOT like a brand or a page. Think of how a college girl would text a new follower.\n\n"
        "Rules:\n"
        "- 1-2 short sentences MAX. Keep it chill.\n"
        "- Sound like you're texting a friend, use lowercase, abbreviations are fine\n"
        "- Do NOT introduce yourself or say 'I'm Maya' or 'I'm a fashion influencer'\n"
        "- Do NOT say 'welcome to my page' or anything that sounds like a page\n"
        "- Do NOT be overly thankful or say 'thanks for the follow'\n"
        "- Just be friendly and maybe react to their profile or ask something casual\n"
        "- Max 1 emoji, no hashtags\n"
        "- Examples of the RIGHT vibe: 'heyy love your feed! that last fit was fire 🔥', "
        "'omg your style tho 😍 where do u shop??', 'ayy thanks for the follow! ur pics go hard'\n\n"
        f"Their username: @{username}\n"
        "Just the message text, nothing else."
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
    """Maybe view a user's stories — humans don't watch every story they see.

    ~75% chance to view stories (up from 65%), ~35% chance to like (up from 25%).
    Story likes are the strongest engagement signal for follow-backs.
    """
    if random.random() > 0.75:
        return  # skip some stories
    try:
        stories = cl.user_stories(int(user_id))
        if stories:
            # View up to 3 stories (not just 1 — shows genuine interest)
            view_count = min(len(stories), random.randint(1, 3))
            story_pks = [stories[i].pk for i in range(view_count)]
            cl.story_seen(story_pks)
            record_action(data, "story_views", user_id)
            stats["story_views"] = stats.get("story_views", 0) + 1
            log.debug("Viewed %d stories of user %s", view_count, user_id)
            # Brief pause like actually watching
            time.sleep(random.uniform(2, 6) * view_count)
            # Like ~35% of stories (strong signal for follow-back)
            if random.random() < 0.35:
                try:
                    cl.story_like(stories[0].pk)
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
    daily_limit = 60  # aggressive unfollow — clear room for new follows (was 40)

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
            random_delay(20, 60)  # faster unfollow pace (was 30-90)
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
    daily_dm_limit = 15  # aggressive DMs — was 8, now 15

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
            random_delay(45, 120)  # slightly faster DM pace (was 60-180)
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
    """Reply to comments on our own recent posts. Returns reply count.

    Aggressive mode: reply to ALL eligible comments within 48h window.
    Every reply is a signal to the algorithm and drives more comments.
    """
    replied = 0
    daily_reply_limit = 50  # aggressive — was 30, now 50

    try:
        my_id = cl.user_id
        # Get our recent media (last 8 posts — wider window than before)
        medias = cl.user_medias(my_id, amount=8)
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

        # Reply to posts from last 48 hours (was 24h — wider window)
        taken_at = getattr(media, "taken_at", None)
        if taken_at:
            age = datetime.now(timezone.utc) - taken_at.replace(tzinfo=timezone.utc)
            if age > timedelta(hours=48):
                continue

        try:
            comments = cl.media_comments(media.pk, amount=30)  # fetch more (was 20)
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

            # Reply to EVERY eligible comment (no random skip — aggressive growth)
            reply = _generate_reply(cfg, my_caption, comment_text)
            if not reply:
                continue

            try:
                cl.media_comment(media.pk, reply, replied_to_comment_id=comment.pk)
                record_action(data, "replies", comment_id)
                replied_set.add(comment_id)
                replied += 1
                log.debug("Replied to comment %s: %s", comment_id, reply[:40])
                random_delay(20, 60)  # faster reply pace (was 30-90)
            except Exception as exc:
                log.warning("Reply failed for comment %s: %s", comment_id, exc)

    if replied:
        log.info("Replied to %d comments on own posts", replied)
    return replied


# ---------------------------------------------------------------------------
# Feature: Explore page engagement
# ---------------------------------------------------------------------------

def run_explore_engagement(cl: Any, cfg: Config, data: dict[str, Any]) -> dict[str, int]:
    """Like/comment on posts from the Explore feed — mimics casual scrolling.

    Aggressive mode: larger session sizes, higher comment and follow rates.
    """
    stats: dict[str, int] = {"explore_likes": 0, "explore_comments": 0, "explore_follows": 0}
    explore_limit = _randomize_session_size(24)  # larger sessions (was 18)

    try:
        medias = cl.explore_reels(amount=explore_limit + 10)
        log.info("Fetched %d reels from Explore", len(medias))
    except Exception as exc:
        log.warning("Could not fetch Explore page: %s", exc)
        return stats

    for media in medias[:explore_limit]:
        # Skip some posts — humans scroll past most content
        if _should_skip_post():
            time.sleep(random.uniform(1, 3))  # quick scroll past
            continue

        media_id = str(media.pk)
        user_id = str(media.user.pk) if media.user else None

        # Pause like actually watching the reel
        time.sleep(random.uniform(3, 8))

        # Like
        if can_act(data, "likes", cfg.engagement_daily_likes):
            try:
                cl.media_like(media.pk)
                record_action(data, "likes", media_id)
                stats["explore_likes"] += 1
            except Exception as exc:
                log.debug("Explore like failed: %s", exc)

        # Comment on ~25% of explore posts (was 18%)
        if (cfg.engagement_comment_enabled
                and random.random() < 0.25
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

        # Follow from Explore too — ~30% chance (new: explore follows)
        if (cfg.engagement_follow_enabled
                and user_id
                and random.random() < 0.30
                and can_act(data, "follows", cfg.engagement_daily_follows)):
            _browse_before_engage(cl, user_id)
            try:
                cl.user_follow(int(user_id))
                record_action(data, "follows", user_id)
                stats["explore_follows"] += 1
            except Exception as exc:
                log.debug("Explore follow failed: %s", exc)

        # View stories from explore too
        if user_id and can_act(data, "story_views", 150):
            _view_user_stories(cl, user_id, data, stats)

        save_log(LOG_FILE, data)
        random_delay(12, 35)  # faster scrolling pace (was 15-45)

    if any(v > 0 for v in stats.values()):
        log.info("Explore engagement: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# Core hashtag engagement loop (used by both full and session runs)
# ---------------------------------------------------------------------------

def _run_hashtag_engagement(
    cl: Any, cfg: Config, data: dict[str, Any], stats: dict[str, int],
    max_posts: int = 20,
) -> None:
    """Like/comment/follow from hashtag posts — mimics real browsing behavior.

    Aggressive growth mode:
    - Browse 2-3 hashtags per session (was 1-2)
    - Higher comment rate: 28% (was 20%)
    - Higher follow rate: 55% (was 45%)
    - Faster pace between actions
    - View more stories
    """
    hashtags = _parse_hashtags(cfg.engagement_hashtags)
    if not hashtags:
        return

    like_limit = cfg.engagement_daily_likes
    comment_limit = cfg.engagement_daily_comments
    follow_limit = cfg.engagement_daily_follows
    story_limit = 150  # more story views (was 100)

    if (
        not can_act(data, "likes", like_limit)
        and not can_act(data, "comments", comment_limit)
        and not can_act(data, "follows", follow_limit)
    ):
        log.info("All daily limits reached: %s", daily_summary(data))
        return

    # Browse 2-3 hashtags per session (was 1-2) — more targets
    all_medias: list[Any] = []
    tags_to_try = random.sample(hashtags, min(random.randint(2, 3), len(hashtags)))
    for tag in tags_to_try:
        medias = _mine_targets(cl, [tag])
        all_medias.extend(medias)
        # Small pause between hashtag searches
        time.sleep(random.uniform(2, 5))

    random.shuffle(all_medias)
    seen_pks: set[str] = set()
    medias = []
    for m in all_medias:
        pk = str(m.pk)
        if pk not in seen_pks:
            seen_pks.add(pk)
            medias.append(m)

    # Randomize session size
    actual_max = _randomize_session_size(max_posts)

    for media in medias[:actual_max]:
        # Skip some posts — humans scroll past content they don't vibe with
        if _should_skip_post():
            time.sleep(random.uniform(1, 2))  # quick scroll
            continue

        media_id = str(media.pk)
        user_id = str(media.user.pk) if media.user else None

        # Pause like actually looking at the post
        time.sleep(random.uniform(2, 5))

        # Like (most common action)
        if can_act(data, "likes", like_limit):
            try:
                cl.media_like(media.pk)
                record_action(data, "likes", media_id)
                stats["likes"] = stats.get("likes", 0) + 1
            except Exception as exc:
                log.warning("Like failed for %s: %s", media_id, exc)

        # Comment on ~28% of posts (was 20% — comments drive profile visits)
        if (cfg.engagement_comment_enabled
                and random.random() < 0.28
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

        # Follow ~35% from hashtags (reduced from 55% — warm targeting is higher ROI)
        if (cfg.engagement_follow_enabled
                and user_id
                and random.random() < 0.35
                and can_act(data, "follows", follow_limit)):
            _browse_before_engage(cl, user_id)  # view profile first
            try:
                cl.user_follow(int(user_id))
                record_action(data, "follows", user_id)
                stats["follows"] = stats.get("follows", 0) + 1
            except Exception as exc:
                log.warning("Follow failed for %s: %s", user_id, exc)

        # View stories more aggressively
        if user_id and can_act(data, "story_views", story_limit):
            _view_user_stories(cl, user_id, data, stats)

        save_log(LOG_FILE, data)
        random_delay(15, 45)  # faster pace (was 20-60)

        if (
            not can_act(data, "likes", like_limit)
            and not can_act(data, "comments", comment_limit)
            and not can_act(data, "follows", follow_limit)
        ):
            log.info("Daily limits reached, stopping hashtag engagement")
            break


# ---------------------------------------------------------------------------
# Feature: Warm audience targeting (engage followers of similar accounts)
# ---------------------------------------------------------------------------

def _parse_target_accounts(raw: str) -> list[str]:
    """Parse comma-separated account usernames."""
    return [a.strip().lstrip("@").lower() for a in raw.split(",") if a.strip()]


def run_warm_audience_session(
    cl: Any, cfg: Config, data: dict[str, Any],
) -> dict[str, int]:
    """Engage with followers of similar accounts in the niche.

    Warm audience targeting converts 3-5x better than random follow/unfollow
    because these users already consume similar content.

    Strategy:
      1. Pick a random target account (similar niche influencer)
      2. Get their recent followers
      3. For each: like 2-3 recent posts + leave a genuine comment on one
      4. Optionally follow (~40% — lower than hashtag since quality > quantity)

    This is the highest-ROI engagement strategy in 2026.
    """
    stats: dict[str, int] = {
        "warm_likes": 0, "warm_comments": 0, "warm_follows": 0, "warm_story_views": 0,
    }

    targets = _parse_target_accounts(cfg.engagement_target_accounts)
    if not targets:
        log.info("No target accounts configured for warm audience targeting")
        return stats

    account = random.choice(targets)
    log.info("Warm targeting: engaging followers of @%s", account)

    # Resolve username to user_id
    try:
        target_user = cl.user_info_by_username(account)
        target_id = target_user.pk
    except Exception as exc:
        log.warning("Could not resolve @%s: %s", account, exc)
        return stats

    # Get recent followers of the target account
    try:
        followers = cl.user_followers(target_id, amount=60)
    except Exception as exc:
        log.warning("Could not fetch followers of @%s: %s", account, exc)
        return stats

    follower_ids = list(followers.keys())
    random.shuffle(follower_ids)

    session_size = _randomize_session_size(12)
    log.info("Warm audience: browsing %d followers of @%s", min(session_size, len(follower_ids)), account)

    for uid in follower_ids[:session_size]:
        user_id = str(uid)

        # Skip some — human behavior
        if _should_skip_post():
            time.sleep(random.uniform(1, 3))
            continue

        # Browse profile first (realistic)
        _browse_before_engage(cl, user_id)

        # Like 2-3 recent posts
        try:
            user_medias = cl.user_medias(int(user_id), amount=4)
        except Exception:
            user_medias = []

        like_count = min(random.randint(2, 3), len(user_medias))
        for media in user_medias[:like_count]:
            if can_act(data, "likes", cfg.engagement_daily_likes):
                try:
                    cl.media_like(media.pk)
                    record_action(data, "likes", str(media.pk))
                    stats["warm_likes"] += 1
                except Exception:
                    pass
                time.sleep(random.uniform(2, 5))

        # Comment on the first post (~45% — higher rate for warm targets)
        if (cfg.engagement_comment_enabled
                and user_medias
                and random.random() < 0.45
                and can_act(data, "comments", cfg.engagement_daily_comments)):
            caption_text = str(getattr(user_medias[0], "caption_text", "") or "")
            comment = _generate_comment(cfg, caption_text)
            if comment:
                try:
                    cl.media_comment(user_medias[0].pk, comment)
                    record_action(data, "comments", str(user_medias[0].pk))
                    stats["warm_comments"] += 1
                except Exception as exc:
                    log.debug("Warm comment failed: %s", exc)

        # Follow ~40% (lower than hashtag — quality over quantity)
        if (cfg.engagement_follow_enabled
                and random.random() < 0.40
                and can_act(data, "follows", cfg.engagement_daily_follows)):
            try:
                cl.user_follow(int(user_id))
                record_action(data, "follows", user_id)
                stats["warm_follows"] += 1
            except Exception as exc:
                log.debug("Warm follow failed: %s", exc)

        # View their stories (strong signal)
        if can_act(data, "story_views", 150):
            _view_user_stories(cl, user_id, data, stats)
            stats["warm_story_views"] = stats.get("story_views", 0)

        save_log(LOG_FILE, data)
        random_delay(20, 50)

        # Check daily limits
        if (not can_act(data, "likes", cfg.engagement_daily_likes)
                and not can_act(data, "comments", cfg.engagement_daily_comments)):
            log.info("Daily limits reached during warm targeting")
            break

    if any(v > 0 for v in stats.values()):
        log.info("Warm audience engagement (@%s): %s", account, stats)
    return stats


# ---------------------------------------------------------------------------
# Session-based engagement (for scheduler — short focused bursts)
# ---------------------------------------------------------------------------

# Session types for the scheduler to call throughout the day
SESSION_TYPES = [
    "morning",      # likes + follows from hashtags (catch early risers)
    "replies",      # reply to comments on own posts (algorithm boost)
    "hashtags",     # full hashtag engagement (like/comment/follow/stories)
    "explore",      # explore page engagement
    "warm_audience", # engage followers of similar niche accounts (3-5x better ROI)
    "maintenance",  # unfollow old follows + welcome DMs
    "stories",      # repost past posts as stories + add to highlights
    "report",       # end-of-day summary report
    "full",         # all phases (backward compat)
]


def run_session(cfg: Config, session_type: str = "full") -> dict[str, int]:
    """Run a focused engagement session — designed to mimic human phone checks.

    Each session is short (5-15 min), with randomized startup delay so
    we never run at exact cron times. Session sizes are randomized ±30%.

    Aggressive mode: larger session sizes, always run DMs during maintenance.
    """
    data = load_log(LOG_FILE)
    stats: dict[str, int] = {}

    # Startup jitter — don't run at exact cron times
    if session_type not in ("report",):
        session_startup_jitter()

    cl = _get_client(cfg)
    log.info("Starting engagement session: %s", session_type)

    if session_type == "morning":
        # Morning: aggressive start — hashtags + welcome DMs
        _run_hashtag_engagement(cl, cfg, data, stats, max_posts=20)
        # Also run welcome DMs during morning (catch overnight followers)
        dm_count = run_welcome_dms(cl, cfg)
        stats["dms"] = dm_count

    elif session_type == "replies":
        stats["replies"] = run_reply_to_comments(cl, cfg, data)
        save_log(LOG_FILE, data)

    elif session_type == "hashtags":
        _run_hashtag_engagement(cl, cfg, data, stats, max_posts=25)  # was 20

    elif session_type == "explore":
        explore_stats = run_explore_engagement(cl, cfg, data)
        stats.update(explore_stats)

    elif session_type == "warm_audience":
        warm_stats = run_warm_audience_session(cl, cfg, data)
        stats.update(warm_stats)

    elif session_type == "maintenance":
        stats["unfollows"] = run_auto_unfollow(cl, data)
        save_log(LOG_FILE, data)
        # Always run welcome DMs during maintenance (was separate)
        dm_count = run_welcome_dms(cl, cfg)
        stats["dms"] = dm_count

    elif session_type == "stories":
        from stories import run_story_session
        story_stats = run_story_session(cl, cfg)
        stats.update(story_stats)

    elif session_type == "report":
        from report import run_daily_report
        run_daily_report()
        stats["report"] = 1

    else:  # "full" — all phases (used sparingly, 1x/day max)
        stats["unfollows"] = run_auto_unfollow(cl, data)
        save_log(LOG_FILE, data)
        random_delay(20, 90)  # faster transitions (was 30-120)
        stats["replies"] = run_reply_to_comments(cl, cfg, data)
        save_log(LOG_FILE, data)
        random_delay(20, 90)
        _run_hashtag_engagement(cl, cfg, data, stats, max_posts=30)
        random_delay(20, 90)
        explore_stats = run_explore_engagement(cl, cfg, data)
        stats.update(explore_stats)
        dm_count = run_welcome_dms(cl, cfg)
        stats["dms"] = dm_count

    save_log(LOG_FILE, data)
    log.info("Session '%s' done: %s (daily: %s)", session_type, stats, daily_summary(data))
    return stats


# ---------------------------------------------------------------------------
# Main engagement entry point (backward compat)
# ---------------------------------------------------------------------------

def run_engagement(cfg: Config) -> dict[str, int]:
    """Full engagement loop — runs all phases."""
    return run_session(cfg, "full")
