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
from publisher import _get_client, _is_challenge_error, ChallengeAbort
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
from persona import get_persona

log = logging.getLogger(__name__)


def _check_challenge(exc: Exception) -> None:
    """If *exc* is a challenge/checkpoint error, raise ChallengeAbort.

    Call this inside every ``except Exception`` handler that wraps an
    Instagram API call.  It converts silent challenge swallowing into
    an immediate abort, preventing the bot from hammering a blocked
    account and escalating to a full ban.
    """
    if _is_challenge_error(exc):
        log.error("CHALLENGE DETECTED — aborting session: %s", exc)
        raise ChallengeAbort(str(exc)) from exc

# Persistent files
POSTS_PER_HASHTAG = 40          # max growth — mine as many as possible per tag
def _followers_file():
    from persona import persona_data_dir
    return persona_data_dir() / "followers.json"
UNFOLLOW_DAYS = 2  # unfollow after 2 days (was 3) — faster churn = more room for new follows

# Follow circuit breaker — stop trying after N consecutive failures
_FOLLOW_MAX_CONSECUTIVE_FAILS = 3
_follow_consecutive_fails: int = 0
_follow_blocked: bool = False


def _follow_ok() -> bool:
    """Return False if follow circuit breaker has tripped (rate limited)."""
    return not _follow_blocked


def _follow_succeeded() -> None:
    """Reset the follow circuit breaker on success."""
    global _follow_consecutive_fails, _follow_blocked
    _follow_consecutive_fails = 0
    _follow_blocked = False


def _follow_failed(exc: Exception) -> None:
    """Record a follow failure; trip circuit breaker after N consecutive."""
    global _follow_consecutive_fails, _follow_blocked
    exc_str = str(exc).lower()
    if "feedback_required" in exc_str or "please wait" in exc_str:
        _follow_consecutive_fails += 1
        if _follow_consecutive_fails >= _FOLLOW_MAX_CONSECUTIVE_FAILS:
            _follow_blocked = True
            log.warning(
                "Follow circuit breaker TRIPPED after %d consecutive rate limits — skipping follows for this session",
                _follow_consecutive_fails,
            )
    else:
        # Non-rate-limit error — don't count toward breaker
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_hashtags(raw: str) -> list[str]:
    """Parse comma-separated hashtag string, strip '#' prefixes."""
    return [t.strip().lstrip("#").lower() for t in raw.split(",") if t.strip()]


def _should_skip_post() -> bool:
    """Skip disabled — engage with everything to maximize growth."""
    return False


def _randomize_session_size(base: int) -> int:
    """Vary session size by ±30% so no two sessions look identical."""
    lo = max(3, int(base * 0.7))
    hi = int(base * 1.3)
    return random.randint(lo, hi)


def _browse_before_engage(cl: Any, user_id: str) -> Optional[Any]:
    """View a user's profile before engaging — humans check who they're interacting with.

    Returns the UserInfo object for downstream use (power user targeting).
    Uses user_info_v1 (private API) to avoid public API 429 rate limits
    that cause multi-minute retries and session timeouts.
    """
    try:
        user_info = cl.user_info_v1(int(user_id))
        # Short pause like reading their bio
        time.sleep(random.uniform(0.3, 1))
        return user_info
    except Exception:
        return None


def _is_quality_follow_target(user_info: Any) -> bool:
    """Check if a user is a quality follow target (micro-influencer / active creator).

    Micro-influencers (1K-50K followers) follow back 20-30% of the time
    vs 5% for random users. This is the #1 targeting quality improvement.
    """
    if user_info is None:
        return False
    try:
        followers = getattr(user_info, "follower_count", 0) or 0
        following = getattr(user_info, "following_count", 0) or 0
        media_count = getattr(user_info, "media_count", 0) or 0
        is_private = getattr(user_info, "is_private", True)

        # Sweet spot: 1K-50K followers, reasonable ratio, active, public
        if followers < 500 or followers > 100_000:
            return False
        if is_private:
            return False
        if following > 0 and followers / following < 0.3:
            return False  # Likely follow-farm
        if media_count < 10:
            return False  # Inactive
        return True
    except Exception:
        return False


def _sort_by_reach(medias: list[Any]) -> list[Any]:
    """Sort posts so bigger accounts come first — our comments get seen by more people.

    Uses follower_count from the media.user object if available, otherwise
    falls back to like_count as a proxy for reach.
    Priority: accounts with 10K+ followers first, then by engagement.
    """
    def _reach_key(media: Any) -> int:
        # Some media objects carry user follower_count
        user = getattr(media, "user", None)
        if user:
            fc = getattr(user, "follower_count", 0) or 0
            if fc > 0:
                return fc
        # Fallback: like_count as a proxy for post visibility
        return getattr(media, "like_count", 0) or 0

    try:
        return sorted(medias, key=_reach_key, reverse=True)
    except Exception:
        return medias


def _is_big_enough(media: Any, min_followers: int) -> bool:
    """Check if a media's author has at least *min_followers*.

    Returns True when the threshold is met or cannot be determined (fail-open
    using like_count as proxy: 500 likes ≈ 10K+ followers).
    """
    if min_followers <= 0:
        return True
    user = getattr(media, "user", None)
    if not user:
        return False
    fc = getattr(user, "follower_count", 0) or 0
    if fc > 0:
        return fc >= min_followers
    # API sometimes omits follower_count — use like_count as proxy
    return (getattr(media, "like_count", 0) or 0) >= max(500, min_followers // 20)


# Fallback comment pools — used when Gemini is rate-limited so we never skip engagement
_FALLBACK_COMMENTS = [
    "this is so good, saving this rn",
    "the vibe of this whole thing 🔥",
    "okay wait this actually hits different",
    "needed to see this today honestly",
    "why does this go so hard tho",
    "the energy in this one >>",
    "obsessed with this whole aesthetic",
    "this deserves way more attention fr",
    "screenshotting this immediately",
    "how do you keep coming up with this stuff",
    "can't stop coming back to this one",
    "the details in this are insane",
    "this is the content I'm here for",
    "you never miss honestly",
    "okay this one's going in the saved folder",
    "the effort that went into this tho 👏",
    "giving everything it needs to give",
    "this just made my whole scroll worth it",
    "I stg your content always hits",
    "okay yeah you understood the assignment",
]

_FALLBACK_REPLIES = [
    "ahh thank you so much!! means a lot 🙏",
    "you're too kind honestly, appreciate it",
    "glad you vibed with it! 🔥",
    "that means everything, thank you",
    "yoo appreciate you noticing that!",
    "thank you!! what's your fav part?",
    "means a lot coming from you 💯",
    "ahhh this made my day fr",
    "you always show love, appreciate you",
    "glad someone feels the same way haha",
]

_FALLBACK_DMS = [
    "heyy thanks for the follow! love your vibe ✨",
    "ayy appreciate the follow! your page goes hard 🔥",
    "thanks for connecting! love the energy on your page",
    "heyy! noticed you followed, your content is fire",
    "appreciate the follow! what made you find me?",
]


def _generate_comment(cfg: Config, caption_text: str) -> str | None:
    """Use Gemini to generate a short, context-aware comment on a post.

    Falls back to a pre-written pool when Gemini is rate-limited,
    so engagement never stops.
    """
    if not cfg.gemini_api_key:
        return random.choice(_FALLBACK_COMMENTS)
    from gemini_helper import generate
    prompt = (
        f"You are {get_persona()["voice"]["gemini_identity"]}. "
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
    # Gemini failed/rate-limited — use fallback instead of skipping
    return random.choice(_FALLBACK_COMMENTS)


def _generate_reply(cfg: Config, original_caption: str, their_comment: str) -> str | None:
    """Generate a reply to a comment on our own post.

    Falls back to pre-written replies when Gemini is rate-limited.
    """
    if not cfg.gemini_api_key:
        return random.choice(_FALLBACK_REPLIES)
    from gemini_helper import generate
    prompt = (
        f"You are {get_persona()["voice"]["gemini_identity"]}. "
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
    return random.choice(_FALLBACK_REPLIES)


def _generate_dm(cfg: Config, username: str) -> str | None:
    """Generate a welcome DM for a new follower.

    Falls back to pre-written DMs when Gemini is rate-limited.
    """
    if not cfg.gemini_api_key:
        return random.choice(_FALLBACK_DMS)
    from gemini_helper import generate
    prompt = (
        f"You are {get_persona()["voice"]["dm_persona"]} "
        "Someone just followed you. Send them a quick casual DM like a real person would — "
        "NOT like a brand or a page. Think of how a college girl would text a new follower.\n\n"
        "Rules:\n"
        "- 1-2 short sentences MAX. Keep it chill.\n"
        "- Sound like you're texting a friend, use lowercase, abbreviations are fine\n"
        f"- {get_persona()['voice'].get('dm_dont', 'Do NOT introduce yourself.')}\n"
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
    return random.choice(_FALLBACK_DMS)


def _mine_targets(cl: Any, hashtags: list[str], amount: int = POSTS_PER_HASHTAG) -> list[Any]:
    """Fetch top + recent posts from a random hashtag.

    Top posts come from bigger accounts → our comments get more visibility.
    We fetch BOTH top and recent, merging them with top posts first.
    """
    if not hashtags:
        return []
    tag = random.choice(hashtags)
    log.info("Mining hashtag: #%s", tag)
    all_medias: list[Any] = []

    # Fetch top posts first — these are from bigger accounts
    try:
        top = cl.hashtag_medias_top(tag, amount=min(amount, 9))
        top = [m for m in top if m is not None and getattr(m, "pk", None)]
        all_medias.extend(top)
        log.info("Found %d top posts from #%s", len(top), tag)
    except Exception as exc:
        _check_challenge(exc)
        log.debug("Top posts failed for #%s: %s", tag, exc)

    # Then fill with recent posts
    try:
        recent = cl.hashtag_medias_recent(tag, amount=amount)
        recent = [m for m in recent if m is not None and getattr(m, "pk", None)]
        all_medias.extend(recent)
        log.info("Found %d recent posts from #%s", len(recent), tag)
    except Exception as exc:
        _check_challenge(exc)
        log.warning("Recent posts failed for #%s: %s", tag, exc)

    if not all_medias:
        log.warning("No posts found for #%s", tag)
    return all_medias


def _view_user_stories(cl: Any, user_id: str, data: dict, stats: dict) -> None:
    """View a user's stories and like them — maximum engagement signals.

    Always view stories and always like — strongest signal for follow-backs.
    """
    # Always view stories — no skipping
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
            time.sleep(random.uniform(0.5, 1.5) * view_count)
            # Always like stories (strong signal for follow-back)
            if True:
                try:
                    cl.story_like(stories[0].pk)
                    stats["story_likes"] = stats.get("story_likes", 0) + 1
                except Exception:
                    pass
    except Exception as exc:
        _check_challenge(exc)
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
            random_delay(4, 12)  # fast unfollow pace
        except Exception as exc:
            _check_challenge(exc)
            log.warning("Unfollow failed for %s: %s", user_id, exc)

    if unfollowed:
        log.info("Auto-unfollowed %d users (>%d days old)", unfollowed, UNFOLLOW_DAYS)
    return unfollowed


# ---------------------------------------------------------------------------
# Feature: DM welcome to new followers
# ---------------------------------------------------------------------------

def _load_followers(path: Path | None = None) -> set[str]:
    if path is None:
        path = _followers_file()
    if not path.exists():
        return set()
    try:
        with open(path) as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_followers(ids: set[str], path: Path | None = None) -> None:
    if path is None:
        path = _followers_file()
    with open(path, "w") as f:
        json.dump(sorted(ids), f)


def run_welcome_dms(cl: Any, cfg: Config) -> int:
    """Send welcome DMs to new followers. Returns count sent."""
    try:
        my_id = cl.user_id
        current = cl.user_followers(my_id, amount=200)
    except Exception as exc:
        _check_challenge(exc)
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
            random_delay(8, 20)  # fast DM pace
        except Exception as exc:
            _check_challenge(exc)
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
        _check_challenge(exc)
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
            _check_challenge(exc)
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
                random_delay(4, 12)  # fast reply pace
            except Exception as exc:
                _check_challenge(exc)
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
    explore_limit = _randomize_session_size(60)  # aggressive growth

    try:
        raw_medias = cl.explore_reels(amount=explore_limit + 10)
        log.info("Fetched %d reels from Explore", len(raw_medias))
    except Exception as exc:
        _check_challenge(exc)
        log.warning("Could not fetch Explore page: %s", exc)
        return stats

    # Sort by reach: engage with big accounts first for maximum visibility
    medias = _sort_by_reach(raw_medias)

    # Filter: ONLY engage with big pages (configurable threshold)
    min_f = cfg.engagement_min_followers_hashtag
    if min_f > 0:
        before = len(medias)
        medias = [m for m in medias if _is_big_enough(m, min_f)]
        log.info("Explore big-page filter: %d/%d posts pass %d+ threshold",
                 len(medias), before, min_f)

    for media in medias[:explore_limit]:
        # Skip some posts — humans scroll past most content
        if _should_skip_post():
            time.sleep(random.uniform(0.5, 1.5))
            continue

        media_id = str(media.pk)
        user_id = str(media.user.pk) if media.user else None

        # Pause like actually watching the reel
        time.sleep(random.uniform(0.5, 2))

        # Like — big accounts first for visibility
        if can_act(data, "likes", cfg.engagement_daily_likes):
            try:
                cl.media_like(media.pk)
                record_action(data, "likes", media_id)
                stats["explore_likes"] += 1
            except Exception as exc:
                _check_challenge(exc)
                log.debug("Explore like failed: %s", exc)

        # Comment on big accounts — our comment visible to their audience
        if (cfg.engagement_comment_enabled
                and can_act(data, "comments", cfg.engagement_daily_comments)):
            caption_text = str(getattr(media, "caption_text", "") or "")
            comment = _generate_comment(cfg, caption_text)
            if comment:
                try:
                    cl.media_comment(media.pk, comment)
                    record_action(data, "comments", media_id)
                    stats["explore_comments"] += 1
                except Exception as exc:
                    _check_challenge(exc)
                    log.debug("Explore comment failed: %s", exc)

        # Smart follow — only quality targets (1K-50K, active, public)
        if (cfg.engagement_follow_enabled
                and _follow_ok()
                and user_id
                and can_act(data, "follows", cfg.engagement_daily_follows)):
            user_info = _browse_before_engage(cl, user_id)
            if _is_quality_follow_target(user_info):
                try:
                    cl.user_follow(int(user_id))
                    record_action(data, "follows", user_id)
                    stats["explore_follows"] += 1
                    _follow_succeeded()
                except Exception as exc:
                    _check_challenge(exc)
                    _follow_failed(exc)
                    log.debug("Explore follow failed: %s", exc)

        # View stories from explore too
        if user_id and can_act(data, "story_views", 150):
            _view_user_stories(cl, user_id, data, stats)

        save_log(LOG_FILE, data)
        random_delay(2, 8)  # fast pace

    if any(v > 0 for v in stats.values()):
        log.info("Explore engagement: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# Core hashtag engagement loop (used by both full and session runs)
# ---------------------------------------------------------------------------

def _run_hashtag_engagement(
    cl: Any, cfg: Config, data: dict[str, Any], stats: dict[str, int],
    max_posts: int = 50,
) -> None:
    """Like/comment/follow from hashtag posts — highly aggressive growth.

    Aggressive growth mode:
    - Browse 2-3 hashtags per session (50 posts per session)
    - Higher comment rate: 45%
    - Higher follow rate: 55% (was 45%)
    - Faster pace between actions (8-25s delays)
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
        time.sleep(random.uniform(1, 3))

    # Deduplicate
    seen_pks: set[str] = set()
    unique_medias = []
    for m in all_medias:
        pk = str(m.pk)
        if pk not in seen_pks:
            seen_pks.add(pk)
            unique_medias.append(m)

    # Sort by reach: big accounts first — our comments get seen by more people
    medias = _sort_by_reach(unique_medias)

    # Filter: ONLY engage with big pages (configurable threshold)
    min_f = cfg.engagement_min_followers_hashtag
    if min_f > 0:
        before = len(medias)
        medias = [m for m in medias if _is_big_enough(m, min_f)]
        log.info("Hashtag big-page filter: %d/%d posts pass %d+ threshold",
                 len(medias), before, min_f)

    # Randomize session size
    actual_max = _randomize_session_size(max_posts)

    for media in medias[:actual_max]:
        # Skip some posts — humans scroll past content they don't vibe with
        if _should_skip_post():
            time.sleep(random.uniform(0.5, 1))
            continue

        media_id = str(media.pk)
        user_id = str(media.user.pk) if media.user else None

        # Pause like actually looking at the post
        time.sleep(random.uniform(0.5, 2))

        # Like (most common action) — prioritize big accounts for visibility
        if can_act(data, "likes", like_limit):
            try:
                cl.media_like(media.pk)
                record_action(data, "likes", media_id)
                stats["likes"] = stats.get("likes", 0) + 1
            except Exception as exc:
                _check_challenge(exc)
                log.warning("Like failed for %s: %s", media_id, exc)

        # Comment on big accounts' posts — our comment visible to their audience
        if (cfg.engagement_comment_enabled
                and can_act(data, "comments", comment_limit)):
            caption_text = str(media.caption_text or "") if hasattr(media, "caption_text") else ""
            comment = _generate_comment(cfg, caption_text)
            if comment:
                try:
                    cl.media_comment(media.pk, comment)
                    record_action(data, "comments", media_id)
                    stats["comments"] = stats.get("comments", 0) + 1
                except Exception as exc:
                    _check_challenge(exc)
                    log.warning("Comment failed for %s: %s", media_id, exc)

        # Smart follow — only follow quality targets (1K-50K followers, active, public)
        # We like/comment on big accounts for visibility, but only FOLLOW accounts
        # likely to follow back (micro-influencers).
        if (cfg.engagement_follow_enabled
                and _follow_ok()
                and user_id
                and can_act(data, "follows", follow_limit)):
            user_info = _browse_before_engage(cl, user_id)  # view profile first
            if _is_quality_follow_target(user_info):
                try:
                    cl.user_follow(int(user_id))
                    record_action(data, "follows", user_id)
                    stats["follows"] = stats.get("follows", 0) + 1
                    _follow_succeeded()
                    log.debug("Followed %s from hashtag (quality target)", user_id)
                except Exception as exc:
                    _check_challenge(exc)
                    _follow_failed(exc)
                    log.warning("Follow failed for %s: %s", user_id, exc)
            else:
                log.debug("Skipped follow for %s — not a quality target", user_id)

        # View stories more aggressively
        if user_id and can_act(data, "story_views", story_limit):
            _view_user_stories(cl, user_id, data, stats)

        save_log(LOG_FILE, data)
        random_delay(2, 8)  # fast pace

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

    # Shuffle targets so we try a random one first, but fall through to others
    random.shuffle(targets)
    target_id = None
    account = None
    for candidate in targets:
        log.info("Warm targeting: trying @%s", candidate)
        try:
            target_user = cl.user_info_by_username(candidate)
            target_id = target_user.pk
            account = candidate
            log.info("Warm targeting: resolved @%s → %s", candidate, target_id)
            break
        except Exception as exc:
            _check_challenge(exc)
            log.warning("Could not resolve @%s: %s — trying next target", candidate, exc)
            random_delay(2, 5)
            continue

    if target_id is None:
        log.warning("Warm targeting: could not resolve ANY target account — aborting")
        return stats

    # Get recent followers of the target account
    # user_followers tries GraphQL first (often returns empty), fall back to v1
    try:
        followers = cl.user_followers(target_id, amount=80)
        if not followers:
            log.info("Warm targeting: GQL returned 0 followers for @%s, trying private API", account)
            follower_list = cl.user_followers_v1(str(target_id), amount=80)
            followers = {u.pk: u for u in follower_list}
    except Exception as exc:
        _check_challenge(exc)
        log.warning("Could not fetch followers of @%s: %s", account, exc)
        return stats

    if not followers:
        log.info("Warm targeting: @%s returned 0 followers — skipping", account)
        return stats

    follower_ids = list(followers.keys())
    random.shuffle(follower_ids)

    session_size = _randomize_session_size(45)  # max growth — engage more warm targets
    log.info("Warm audience: browsing %d followers of @%s", min(session_size, len(follower_ids)), account)

    for uid in follower_ids[:session_size]:
        user_id = str(uid)

        # Skip some — human behavior
        if _should_skip_post():
            time.sleep(random.uniform(0.5, 1.5))
            continue

        # Browse profile first (realistic)
        _browse_before_engage(cl, user_id)

        # Like 2-3 recent posts
        try:
            user_medias = cl.user_medias(int(user_id), amount=4)
        except Exception as exc:
            _check_challenge(exc)
            user_medias = []

        like_count = min(random.randint(2, 3), len(user_medias))
        for media in user_medias[:like_count]:
            if can_act(data, "likes", cfg.engagement_daily_likes):
                try:
                    cl.media_like(media.pk)
                    record_action(data, "likes", str(media.pk))
                    stats["warm_likes"] += 1
                except Exception as exc:
                    _check_challenge(exc)
                time.sleep(random.uniform(0.5, 1.5))

        # Always comment on warm targets
        if (cfg.engagement_comment_enabled
                and user_medias
                and can_act(data, "comments", cfg.engagement_daily_comments)):
            caption_text = str(getattr(user_medias[0], "caption_text", "") or "")
            comment = _generate_comment(cfg, caption_text)
            if comment:
                try:
                    cl.media_comment(user_medias[0].pk, comment)
                    record_action(data, "comments", str(user_medias[0].pk))
                    stats["warm_comments"] += 1
                except Exception as exc:
                    _check_challenge(exc)
                    log.debug("Warm comment failed: %s", exc)

        # Always follow warm targets — maximum growth
        if (cfg.engagement_follow_enabled
                and _follow_ok()
                and can_act(data, "follows", cfg.engagement_daily_follows)):
            try:
                cl.user_follow(int(user_id))
                record_action(data, "follows", user_id)
                stats["warm_follows"] += 1
                _follow_succeeded()
            except Exception as exc:
                _check_challenge(exc)
                _follow_failed(exc)
                log.debug("Warm follow failed: %s", exc)

        # View their stories (strong signal)
        if can_act(data, "story_views", 150):
            _view_user_stories(cl, user_id, data, stats)
            stats["warm_story_views"] = stats.get("story_views", 0)

        save_log(LOG_FILE, data)
        random_delay(3, 10)  # fast pace

        # Check daily limits
        if (not can_act(data, "likes", cfg.engagement_daily_likes)
                and not can_act(data, "comments", cfg.engagement_daily_comments)):
            log.info("Daily limits reached during warm targeting")
            break

    if any(v > 0 for v in stats.values()):
        log.info("Warm audience engagement (@%s): %s", account, stats)
    return stats


# ---------------------------------------------------------------------------
# Feature: Post-publish engagement burst (first 30 min = algorithmic fate)
# ---------------------------------------------------------------------------

_FALLBACK_PIN_COMMENTS = [
    "Which one are you picking? Be honest 👇",
    "Drop a 🔥 if you agree with this one",
    "Thoughts? I wanna hear your take",
    "Save this for later, you'll thank me",
    "Tag someone who needs to see this",
    "1, 2, or 3? Drop your pick below 👇",
    "Real ones know. Are you one of them?",
    "Agree or disagree? Let's debate 💬",
]


def _generate_pin_comment(cfg: Config, caption: str, topic: str) -> str | None:
    """Generate a comment-driving pin comment for own post.

    Falls back to pre-written CTA comments when Gemini is rate-limited.
    """
    if not cfg.gemini_api_key:
        return random.choice(_FALLBACK_PIN_COMMENTS)
    from gemini_helper import generate
    prompt = (
        f"You are {get_persona()["voice"]["gemini_identity"]}. "
        "Generate a SHORT pinning comment for your own Instagram post (max 12 words). "
        "Ask a specific question that makes people reply in comments. "
        "NOT generic. Relate to the specific topic. Be playful and bold.\n"
        "Examples: 'Which look are you stealing? Be honest.', "
        "'Drop a number — 1, 2 or 3?', "
        "'Would you wear this to work? Be real.'\n"
        "Just the comment text, nothing else.\n\n"
        f"Post topic: {topic[:100]}\n"
        f"Caption: {caption[:200]}"
    )
    comment = generate(cfg.gemini_api_key, prompt, cfg.gemini_model)
    if comment and 3 < len(comment) < 100:
        return comment.strip('"').strip("'")
    return random.choice(_FALLBACK_PIN_COMMENTS)


def run_post_publish_burst(
    cl: Any, cfg: Config, post_id: str, post: dict[str, Any],
) -> dict[str, int]:
    """Run an immediate engagement burst after publishing a post.

    The first 30 minutes after publishing determine whether Instagram
    pushes a post to Explore or buries it. This function:
      1. Pins a CTA comment on the new post (drives conversation)
      2. Immediately reposts as a story (drives views back to post)
      3. Runs a mini engagement burst on hashtag content (natural activity)

    Expected impact: +50-100% reach per post.
    """
    stats: dict[str, int] = {"pin_comment": 0, "burst_story": 0, "burst_likes": 0}

    # 1. Pin a CTA comment on the new post
    pin_text = _generate_pin_comment(
        cfg, str(post.get("caption", "")), str(post.get("topic", ""))
    )
    if pin_text and post_id and post_id != "unknown":
        try:
            comment_obj = cl.media_comment(int(post_id), pin_text)
            # Try to pin the comment (drives more replies)
            try:
                cl.private_request(
                    f"media/{post_id}/comment/{comment_obj.pk}/pin/",
                    data={"_uuid": cl.uuid},
                )
                log.info("Pinned comment on %s: %s", post_id, pin_text[:40])
            except Exception as exc:
                log.debug("Pin failed (still posted comment): %s", exc)
            stats["pin_comment"] = 1
        except Exception as exc:
            log.warning("Self-comment failed on %s: %s", post_id, exc)

    random_delay(3, 8)

    # 2. Reshare post to story (native post card with link sticker)
    if post_id and post_id != "unknown":
        try:
            from stories import reshare_post_to_story
            reshare_post_to_story(cl, int(post_id), int(cl.user_id))
            stats["burst_story"] = 1
            log.info("Post-publish story reshare for %s", post.get("id"))
        except Exception as exc:
            log.debug("Post-publish story failed: %s", exc)

    random_delay(3, 10)

    # 3. Mini engagement burst — 8-12 likes on hashtag content (natural activity)
    data = load_log(LOG_FILE)
    hashtags = _parse_hashtags(cfg.engagement_hashtags)
    targets = _mine_targets(cl, hashtags, amount=12)
    # Big page filter — only engage with large accounts during burst too
    min_f = cfg.engagement_min_followers_hashtag
    if min_f > 0:
        targets = [m for m in targets if _is_big_enough(m, min_f)]
    burst_count = 0
    for media in targets[:10]:
        if burst_count >= 8:
            break
        if _should_skip_post():
            continue
        media_id = str(media.pk)
        if can_act(data, "likes", cfg.engagement_daily_likes):
            try:
                cl.media_like(media.pk)
                record_action(data, "likes", media_id)
                burst_count += 1
            except Exception:
                pass
            time.sleep(random.uniform(1, 4))
    stats["burst_likes"] = burst_count
    save_log(LOG_FILE, data)

    log.info("Post-publish burst done: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# Feature: Viral post detection + auto-boost
# ---------------------------------------------------------------------------

def run_viral_detection(
    cl: Any, cfg: Config, data: dict[str, Any],
) -> dict[str, int]:
    """Detect posts that are outperforming and boost them.

    Checks recent posts for abnormally high engagement (2x+ average).
    For viral posts: re-story, pin engagement comment, burst engagement.

    Expected impact: locks viral posts into the algorithm snowball.
    """
    stats: dict[str, int] = {"viral_detected": 0, "boost_stories": 0, "boost_comments": 0}

    try:
        my_id = cl.user_id
        recent_medias = cl.user_medias(my_id, amount=8)
    except Exception as exc:
        log.warning("Could not fetch own medias for viral detection: %s", exc)
        return stats

    if len(recent_medias) < 3:
        return stats

    # Calculate average engagement across recent posts
    engagement_scores = []
    for media in recent_medias:
        try:
            info = cl.media_info(media.pk)
            likes = getattr(info, "like_count", 0) or 0
            comments = getattr(info, "comment_count", 0) or 0
            score = likes + (comments * 3)  # weight comments higher
            engagement_scores.append((media, info, score))
        except Exception:
            pass

    if not engagement_scores:
        return stats

    avg_score = sum(s for _, _, s in engagement_scores) / len(engagement_scores)
    if avg_score == 0:
        return stats

    # Find posts from last 24h that are 2x+ above average
    now = datetime.now(timezone.utc)
    for media, info, score in engagement_scores:
        taken_at = getattr(info, "taken_at", None)
        if not taken_at:
            continue

        # Only boost posts from last 24 hours
        if hasattr(taken_at, "tzinfo") and taken_at.tzinfo is None:
            taken_at = taken_at.replace(tzinfo=timezone.utc)
        age_hours = (now - taken_at).total_seconds() / 3600
        if age_hours > 24:
            continue

        # Check if viral (2x+ average engagement)
        if score < avg_score * 2:
            continue

        log.info("VIRAL POST DETECTED: %s (score=%d, avg=%d, %.0fx)",
                 media.pk, score, avg_score, score / avg_score)
        stats["viral_detected"] += 1

        # Boost: reshare to story (post image + link sticker)
        try:
            from stories import reshare_post_to_story
            reshare_post_to_story(cl, int(media.pk), int(cl.user_id))
            stats["boost_stories"] += 1
        except Exception as exc:
            log.debug("Viral boost story failed: %s", exc)

        # Boost: pin a new engagement comment
        pin_text = _generate_pin_comment(
            cfg,
            str(getattr(info, "caption_text", "")),
            str(getattr(info, "caption_text", ""))[:50],
        )
        if pin_text:
            try:
                cl.media_comment(media.pk, pin_text)
                stats["boost_comments"] += 1
            except Exception:
                pass

        random_delay(5, 15)

    if stats["viral_detected"]:
        log.info("Viral detection results: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# Feature: Comment-to-DM follow-up (5-10x follow-back rate from commenters)
# ---------------------------------------------------------------------------

_FALLBACK_COMMENT_DMS = [
    "heyy saw your comment! loved your take on it 🔥",
    "your comment was so real, had to reach out! what's your vibe?",
    "ayy appreciate the love on my post! your page is fire btw",
    "saw what you said on my post and I'm curious — what got you into this?",
    "your comment made my day fr, had to say hey ✨",
]


def _generate_comment_followup_dm(
    cfg: Config, username: str, their_comment: str, post_topic: str,
) -> str | None:
    """Generate a personalized DM referencing their comment on our post.

    Falls back to pre-written DMs when Gemini is rate-limited.
    """
    if not cfg.gemini_api_key:
        return random.choice(_FALLBACK_COMMENT_DMS)
    from gemini_helper import generate
    prompt = (
        f"You are {get_persona()['voice']['dm_persona']} "
        "Someone just commented on your post. Send them a casual DM that:\n"
        "1. References their specific comment (shows you read it)\n"
        "2. Asks a follow-up question about their style\n"
        "3. Sounds like a real person texting, not a brand\n\n"
        "Rules: 1-2 short sentences. Lowercase ok. Max 1 emoji. "
        "NOT 'thanks for commenting'. Be genuine and curious.\n\n"
        f"Their username: @{username}\n"
        f"Their comment: {their_comment[:150]}\n"
        f"Post topic: {post_topic[:100]}\n"
        "Just the DM text:"
    )
    dm = generate(cfg.gemini_api_key, prompt, cfg.gemini_model)
    if dm and 10 < len(dm) < 300:
        return dm
    return random.choice(_FALLBACK_COMMENT_DMS)


def run_comment_followup_dms(
    cl: Any, cfg: Config, data: dict[str, Any],
) -> int:
    """DM people who commented on our posts — 5-10x follow-back rate.

    Commenters have already shown high intent. A personalized DM
    referencing their comment converts massively better than cold follows.

    Max 8 comment-follow-up DMs per day (separate from welcome DMs).
    """
    MAX_COMMENT_DMS = 8
    dm_count = 0

    # Track already-DM'd users
    already_dmd = {
        str(a["target"]) for a in data.get("actions", [])
        if a.get("type") == "comment_dms"
    }

    try:
        my_id = str(cl.user_id)
        recent_medias = cl.user_medias(int(my_id), amount=5)
    except Exception as exc:
        log.warning("Could not fetch medias for comment DMs: %s", exc)
        return 0

    for media in recent_medias:
        if dm_count >= MAX_COMMENT_DMS:
            break

        # Get post topic for personalization
        caption_text = str(getattr(media, "caption_text", "") or "")
        topic = caption_text[:50] if caption_text else "fashion"

        try:
            comments = cl.media_comments(media.pk, amount=20)
        except Exception:
            continue

        for comment in comments:
            if dm_count >= MAX_COMMENT_DMS:
                break

            user_id = str(getattr(comment.user, "pk", ""))
            username = str(getattr(comment.user, "username", ""))

            # Skip own comments, already DM'd, empty
            if user_id == my_id or user_id in already_dmd or not user_id:
                continue

            comment_text = str(getattr(comment, "text", "")).strip()
            if len(comment_text) < 5:
                continue  # Skip very short comments (emoji-only etc.)

            # Generate personalized DM
            dm_text = _generate_comment_followup_dm(cfg, username, comment_text, topic)
            if not dm_text:
                continue

            try:
                cl.direct_send(dm_text, user_ids=[int(user_id)])
                record_action(data, "comment_dms", user_id)
                already_dmd.add(user_id)
                dm_count += 1
                log.info("Comment follow-up DM to @%s: %s", username, dm_text[:40])
            except Exception as exc:
                log.debug("Comment DM to @%s failed: %s", username, exc)

            # Also follow if not already following
            if cfg.engagement_follow_enabled and _follow_ok() and can_act(data, "follows", cfg.engagement_daily_follows):
                try:
                    cl.user_follow(int(user_id))
                    record_action(data, "follows", user_id)
                    _follow_succeeded()
                except Exception as exc:
                    _follow_failed(exc)

            random_delay(5, 15)  # DM pace

    if dm_count:
        log.info("Comment follow-up DMs sent: %d", dm_count)
    return dm_count


# ---------------------------------------------------------------------------
# DM Replies — read incoming threads and reply with AI-generated responses
# ---------------------------------------------------------------------------

_FALLBACK_DM_REPLIES = [
    "haha love that! tell me more 😄",
    "omg yesss exactly what I was thinking!",
    "appreciate that so much!! 🔥",
    "haha you get it! what else are you into?",
    "no way that's so cool! love your energy",
    "aww that's sweet of you to say ✨",
    "haha facts! you're so right about that",
    "that's such a vibe honestly 💯",
]


def _generate_dm_reply(cfg: Config, conversation_context: str, their_latest: str, username: str) -> str | None:
    """Generate a contextual reply to an incoming DM using conversation history.

    Falls back to pre-written replies when Gemini is rate-limited.
    """
    if not cfg.gemini_api_key:
        return random.choice(_FALLBACK_DM_REPLIES)
    from gemini_helper import generate
    persona = get_persona()
    dm_persona = persona["voice"].get("dm_persona") or persona["voice"].get("gemini_identity", "a friendly person")
    dm_dont = persona["voice"].get("dm_dont", "Do NOT introduce yourself.")
    prompt = (
        f"You are {dm_persona}. "
        "Someone sent you a DM on Instagram. Reply casually like a real person texting back.\n\n"
        "Rules:\n"
        "- 1-2 short sentences MAX. Keep it natural.\n"
        "- Sound like you're texting a friend — lowercase ok, abbreviations fine\n"
        f"- {dm_dont}\n"
        "- Be genuine and responsive to what they said\n"
        "- If they ask a question, answer it naturally\n"
        "- If they compliment you, be grateful but chill\n"
        "- Keep the conversation going — ask something back or react\n"
        "- Max 1 emoji, no hashtags\n"
        "- Do NOT sound like a bot or a brand page\n"
        "- Do NOT say anything about being busy or DMs\n\n"
        f"Their username: @{username}\n"
        f"Recent conversation:\n{conversation_context[-500:]}\n\n"
        f"Their latest message: {their_latest[:200]}\n"
        "Your reply (just the text, nothing else):"
    )
    reply = generate(cfg.gemini_api_key, prompt, cfg.gemini_model)
    if reply and 2 < len(reply) < 300:
        return reply
    return random.choice(_FALLBACK_DM_REPLIES)


def run_dm_replies(cl: Any, cfg: Config, data: dict[str, Any]) -> int:
    """Read incoming DM threads and reply with AI-generated responses.

    Strategy:
      1. Fetch recent DM threads
      2. For threads where the last message is FROM them (not us) and < 24h old
      3. Generate a contextual reply using conversation history
      4. Send the reply
      5. Rate-limit to engagement_daily_dm_replies per day
    """
    if not cfg.engagement_dm_replies_enabled:
        return 0

    dm_limit = cfg.engagement_daily_dm_replies
    replied = 0

    # Track threads we already replied to today
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    already_replied = {
        str(a["target"]) for a in data.get("actions", [])
        if a.get("type") == "dm_replies"
        and str(a.get("at", "")).startswith(today_str)
    }

    try:
        my_id = str(cl.user_id)
        threads = cl.direct_threads(amount=20)
    except Exception as exc:
        _check_challenge(exc)
        log.warning("Could not fetch DM threads: %s", exc)
        return 0

    for thread in threads:
        if replied >= dm_limit or not can_act(data, "dm_replies", dm_limit):
            break

        thread_id = str(thread.id)
        if thread_id in already_replied:
            continue

        # Get messages in this thread
        try:
            messages = thread.messages or []
        except Exception:
            continue
        if not messages:
            continue

        # Latest message — must be FROM them (not us)
        latest = messages[0]
        sender_id = str(getattr(latest, "user_id", ""))
        if sender_id == my_id:
            continue  # We sent the last message — don't double-reply

        # Skip old messages (>24h)
        msg_timestamp = getattr(latest, "timestamp", None)
        if msg_timestamp:
            try:
                if hasattr(msg_timestamp, "tzinfo") and msg_timestamp.tzinfo is None:
                    msg_timestamp = msg_timestamp.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - msg_timestamp
                if age > timedelta(hours=24):
                    continue
            except Exception:
                pass

        # Get text of the latest message
        their_text = str(getattr(latest, "text", "") or "").strip()
        if not their_text or len(their_text) < 2:
            continue  # Skip media-only messages, reactions, etc.

        # Build conversation context (last 5 messages, newest→oldest reversed)
        context_lines = []
        for msg in messages[:5]:
            msg_user_id = str(getattr(msg, "user_id", ""))
            msg_text = str(getattr(msg, "text", "") or "").strip()
            if msg_text:
                sender = "You" if msg_user_id == my_id else "Them"
                context_lines.append(f"{sender}: {msg_text}")
        conversation_context = "\n".join(reversed(context_lines))

        # Get the other user's username
        other_users = [u for u in (thread.users or []) if str(u.pk) != my_id]
        username = other_users[0].username if other_users else "friend"

        # Generate reply
        reply_text = _generate_dm_reply(cfg, conversation_context, their_text, username)
        if not reply_text:
            continue

        # Send reply
        try:
            cl.direct_send(reply_text, thread_ids=[int(thread_id)])
            record_action(data, "dm_replies", thread_id)
            replied += 1
            log.info("DM reply to @%s: %s", username, reply_text[:50])
        except Exception as exc:
            _check_challenge(exc)
            log.warning("DM reply failed for thread %s: %s", thread_id, exc)

        random_delay(5, 15)

    if replied:
        log.info("Replied to %d incoming DMs", replied)
    return replied


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
    "boost",        # viral post detection + auto-boost
    "dm_replies",   # reply to incoming DMs (AI-generated contextual replies)
    "maintenance",  # unfollow old follows + welcome DMs + comment DMs
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
        # Morning: max growth start — hashtags
        _run_hashtag_engagement(cl, cfg, data, stats, max_posts=50)

    elif session_type == "replies":
        stats["replies"] = run_reply_to_comments(cl, cfg, data)
        save_log(LOG_FILE, data)

    elif session_type == "hashtags":
        _run_hashtag_engagement(cl, cfg, data, stats, max_posts=45)  # max growth

    elif session_type == "explore":
        explore_stats = run_explore_engagement(cl, cfg, data)
        stats.update(explore_stats)

    elif session_type == "warm_audience":
        warm_stats = run_warm_audience_session(cl, cfg, data)
        stats.update(warm_stats)

    elif session_type == "boost":
        # Viral post detection + auto-boost (run ~1hr after publish)
        viral_stats = run_viral_detection(cl, cfg, data)
        stats.update(viral_stats)

    elif session_type == "dm_replies":
        stats["dm_replies"] = run_dm_replies(cl, cfg, data)
        save_log(LOG_FILE, data)

    elif session_type == "maintenance":
        stats["unfollows"] = run_auto_unfollow(cl, data)
        save_log(LOG_FILE, data)
        # Reply to incoming DMs (rate-limited)
        stats["dm_replies"] = run_dm_replies(cl, cfg, data)
        save_log(LOG_FILE, data)

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
        random_delay(3, 10)
        stats["dm_replies"] = run_dm_replies(cl, cfg, data)
        save_log(LOG_FILE, data)
        random_delay(3, 10)
        stats["replies"] = run_reply_to_comments(cl, cfg, data)
        save_log(LOG_FILE, data)
        random_delay(3, 10)
        _run_hashtag_engagement(cl, cfg, data, stats, max_posts=50)
        random_delay(3, 10)
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
