#!/usr/bin/env python3
"""YouTube engagement automation — like, comment, reply on Shorts in the niche.

Follows the same human-like patterns as Instagram engagement:
  - Gaussian delays between actions
  - Micro-breaks (distraction simulation)
  - Session size randomization
  - Skip some content (selective engagement)
  - AI-generated comments via Gemini

API Quota Budget (10,000 units/day default):
  - 1 video upload       = 1,600 units
  - search.list          = 100 units per call
  - commentThreads.list  = 1 unit per call
  - commentThreads.insert = 50 units
  - videos.rate (like)   = 50 units
  - comments.insert      = 50 units

Quota strategy: PUBLISHING FIRST, engagement with what's left.
  - Reserve 1,700 units per remaining publish window (upload + creator comment)
  - Engagement sessions self-limit based on remaining budget
  - Abort immediately on quotaExceeded (no wasted API calls)
"""

from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Any

from config import Config
from persona import get_persona
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

# YouTube daily limits — MAXED OUT (no action blocks on YouTube unlike Instagram)
# YouTube API quota: 10,000 units/day per key. Like=50u, comment=50u, reply=50u, search=100u
YT_DAILY_LIKES = 500
YT_DAILY_COMMENTS = 200
YT_DAILY_REPLIES = 250

# ---------------------------------------------------------------------------
# Quota budget system — publishing always gets priority over engagement
# ---------------------------------------------------------------------------

# Cost per API operation (YouTube Data API v3)
_QUOTA_COST = {
    "upload": 1600,
    "search": 100,
    "like": 50,
    "comment": 50,
    "reply": 50,
    "list_comments": 1,
    "creator_comment": 50,
}

# Reserve this many units per publish window (upload + creator comment + thumbnail)
_PUBLISH_RESERVE = 1700

# Total daily quota per Google Cloud project
_DAILY_QUOTA = int(os.getenv("YOUTUBE_DAILY_QUOTA", "10000"))

# Flag: set to True when we get a quotaExceeded error — skip all further calls
_quota_exhausted = False


def _estimate_units_used(data: dict[str, Any]) -> int:
    """Estimate YouTube API quota units consumed today from the action log."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    units = 0
    for a in data.get("actions", []):
        if not str(a.get("at", "")).startswith(today):
            continue
        action_type = a.get("type", "")
        if action_type == "yt_likes":
            units += _QUOTA_COST["like"]
        elif action_type == "yt_comments":
            units += _QUOTA_COST["comment"]
        elif action_type == "yt_replies":
            units += _QUOTA_COST["reply"]
        elif action_type == "yt_search":
            units += _QUOTA_COST["search"]
        elif action_type == "yt_upload":
            units += _QUOTA_COST["upload"]
        elif action_type == "yt_creator_comment":
            units += _QUOTA_COST["creator_comment"]
    return units


def _remaining_publish_windows() -> int:
    """Count how many YT publish windows remain today (UTC).

    Publish windows are at fixed IST hours. We check which haven't fired yet.
    Typically 2 per day: lunch (~13:00 IST) and prime time (~19:00-20:00 IST).
    """
    now_utc = datetime.now(timezone.utc)
    # IST = UTC + 5:30. Publish windows vary by persona but are typically
    # around 13:00 IST (07:30 UTC) and 19:00-20:00 IST (13:30-14:30 UTC)
    # Use conservative estimates — assume 2 windows if before 08:00 UTC,
    # 1 window if before 14:30 UTC, 0 after that.
    hour_utc = now_utc.hour + now_utc.minute / 60.0
    if hour_utc < 8.0:
        return 2  # Both lunch and prime time remain
    elif hour_utc < 14.5:
        return 1  # Only prime time remains
    return 0  # All windows passed


def quota_budget_remaining(data: dict[str, Any]) -> int:
    """Return how many quota units are available for engagement today.

    Subtracts already-used units and reserves for remaining publish windows.
    """
    used = _estimate_units_used(data)
    reserved = _remaining_publish_windows() * _PUBLISH_RESERVE
    remaining = _DAILY_QUOTA - used - reserved
    return max(0, remaining)


def _handle_quota_error(exc: Exception) -> bool:
    """Check if an exception is a YouTube quota error. If so, mark exhausted.

    Returns True if it was a quota error (caller should abort).
    """
    global _quota_exhausted
    err_str = str(exc).lower()
    if "quotaexceeded" in err_str or "quota" in err_str:
        _quota_exhausted = True
        log.warning("YouTube quota EXHAUSTED — skipping all remaining API calls")
        return True
    return False

# Search queries for finding niche Shorts to engage with
def _niche_queries():
    return get_persona().get("youtube", {}).get("niche_queries", ["shorts", "trending"])


def _get_youtube_service():
    """Build authenticated YouTube API service."""
    from youtube_publisher import _build_credentials
    from googleapiclient.discovery import build

    creds = _build_credentials()
    return build("youtube", "v3", credentials=creds)


_YT_FALLBACK_COMMENTS = [
    "okay this was actually fire 🔥",
    "the way this just made my whole day",
    "why doesn't this have more views yet",
    "this deserves to blow up honestly",
    "the energy in this one is unmatched",
    "I keep rewatching this one ngl",
    "this is the kind of content I'm here for",
    "okay wait this actually hits different",
    "saving this for later, too good",
    "you never miss with these fr",
]

_YT_FALLBACK_REPLIES = [
    "appreciate you watching!! means a lot 🙏",
    "glad you vibed with it! more coming soon 🔥",
    "yoo thank you!! that means everything",
    "haha appreciate you noticing that!",
    "thanks for the love! what should I make next?",
]


def _generate_yt_comment(cfg: Config, video_title: str) -> str | None:
    """Generate a hyper-specific, context-aware comment for a YouTube Short.

    Analyzes the video title deeply to produce comments that reference
    specific elements — making them feel genuinely human and driving
    profile visits (curiosity about who left such a specific comment).

    Falls back to pre-written pool when Gemini is rate-limited.
    """
    if not cfg.gemini_api_key:
        return random.choice(_YT_FALLBACK_COMMENTS)
    from gemini_helper import generate

    persona = get_persona()
    niche = persona.get("niche", "lifestyle")

    prompt = (
        f"You are {persona['voice']['gemini_identity']}. "
        f"Your niche: {niche}. "
        "Write a short, HYPER-SPECIFIC YouTube comment (1-2 sentences, max 20 words) on a Short.\n\n"
        "RULES:\n"
        "- Reference a SPECIFIC detail from the title (a technique, product, place, number, etc)\n"
        "- Sound like someone who genuinely relates to the content, not a generic compliment\n"
        "- Use casual Gen-Z/millennial tone — abbreviations, slang, lowercase OK\n"
        "- Ask a follow-up question OR share a quick personal take (drives replies)\n"
        "- Max 1 emoji. No hashtags. No 'nice video' / 'great content' / 'love it'\n"
        "- Don't mention being an influencer or creator\n"
        "Just the comment text, nothing else.\n\n"
        f"Video title: {video_title[:200]}"
    )
    comment = generate(cfg.gemini_api_key, prompt, cfg.gemini_model)
    if comment and 5 < len(comment) < 200:
        return comment
    return random.choice(_YT_FALLBACK_COMMENTS)


def _generate_yt_reply(cfg: Config, video_title: str, their_comment: str) -> str | None:
    """Generate a reply to a comment on our own YouTube video.

    Falls back to pre-written replies when Gemini is rate-limited.
    """
    if not cfg.gemini_api_key:
        return random.choice(_YT_FALLBACK_REPLIES)
    from gemini_helper import generate

    prompt = (
        f"You are {get_persona()['voice']['gemini_identity']}. "
        "Someone commented on your YouTube Short. Write a warm, short reply (max 15 words). "
        "Be genuine and grateful but stay in character — bold, confident, witty. "
        "No hashtags. Max 1 emoji. Just the reply text.\n\n"
        f"Video title: {video_title[:200]}\n"
        f"Their comment: {their_comment[:200]}"
    )
    reply = generate(cfg.gemini_api_key, prompt, cfg.gemini_model)
    if reply and 3 < len(reply) < 150:
        return reply
    return random.choice(_YT_FALLBACK_REPLIES)


def _should_skip() -> bool:
    """Randomly skip content — humans don't engage with everything."""
    return random.random() < 0.10  # 10% skip — engage with almost everything


def _randomize_size(base: int) -> int:
    """Vary session size by ±40%."""
    lo = max(2, int(base * 0.6))
    hi = int(base * 1.4)
    return random.randint(lo, hi)


# ---------------------------------------------------------------------------
# Feature: Search & engage with niche Shorts
# ---------------------------------------------------------------------------

def run_yt_niche_engagement(cfg: Config, data: dict[str, Any]) -> dict[str, int]:
    """Like and comment on trending Shorts in the fashion niche.

    Mimics a real person browsing YouTube Shorts: scroll, watch some,
    like a few, comment on ones that genuinely resonate.

    Respects quota budget — reserves units for publishing first.
    """
    global _quota_exhausted
    stats: dict[str, int] = {"yt_likes": 0, "yt_comments": 0}

    # Check quota budget before starting
    budget = quota_budget_remaining(data)
    if budget < 200 or _quota_exhausted:
        log.info("YouTube quota budget too low for engagement (%d units left, "
                 "%d reserved for publishing) — skipping", budget,
                 _remaining_publish_windows() * _PUBLISH_RESERVE)
        return stats

    try:
        youtube = _get_youtube_service()
    except Exception as exc:
        log.warning("YouTube auth failed (skipping engagement): %s", exc)
        return stats

    # Pick 2-3 search queries (reduced from 4 to save quota — each costs 100 units)
    nq = _niche_queries()
    max_queries = min(3, max(1, budget // 1500))  # fewer queries when budget tight
    queries = random.sample(nq, min(max_queries, len(nq)))
    all_videos: list[dict] = []
    units_spent = 0

    for query in queries:
        if _quota_exhausted:
            break
        try:
            response = youtube.search().list(
                part="snippet",
                q=query,
                type="video",
                videoDuration="short",  # Shorts only
                order="date",  # recent first
                maxResults=25,
                relevanceLanguage="en",
                regionCode="IN",
            ).execute()
            units_spent += _QUOTA_COST["search"]
            record_action(data, "yt_search", query)

            for item in response.get("items", []):
                video_id = item.get("id", {}).get("videoId", "")
                title = item.get("snippet", {}).get("title", "")
                channel_id = item.get("snippet", {}).get("channelId", "")
                if video_id and title:
                    all_videos.append({
                        "video_id": video_id,
                        "title": title,
                        "channel_id": channel_id,
                    })
        except Exception as exc:
            if _handle_quota_error(exc):
                break
            log.debug("YouTube search '%s' failed: %s", query, exc)

        time.sleep(random.uniform(1, 3))

    if _quota_exhausted:
        save_log(LOG_FILE, data)
        return stats

    # Deduplicate and shuffle
    seen_ids: set[str] = set()
    videos: list[dict] = []
    for v in all_videos:
        if v["video_id"] not in seen_ids:
            seen_ids.add(v["video_id"])
            videos.append(v)
    random.shuffle(videos)

    # Cap session size based on remaining budget (each video = ~100 units: like+comment)
    budget_after_search = budget - units_spent
    max_by_budget = max(5, budget_after_search // 100)
    session_size = min(_randomize_size(60), max_by_budget)
    log.info("YouTube niche engagement: %d videos (budget: %d units, %d reserved for publishing)",
             min(session_size, len(videos)), budget_after_search,
             _remaining_publish_windows() * _PUBLISH_RESERVE)

    for video in videos[:session_size]:
        if _quota_exhausted:
            break
        if _should_skip():
            time.sleep(random.uniform(0.5, 1.5))
            continue

        video_id = video["video_id"]

        # Pause like watching the Short
        time.sleep(random.uniform(0.3, 1))

        # Like
        if can_act(data, "yt_likes", YT_DAILY_LIKES):
            try:
                youtube.videos().rate(id=video_id, rating="like").execute()
                record_action(data, "yt_likes", video_id)
                stats["yt_likes"] += 1
                log.debug("Liked YT Short: %s", video["title"][:50])
            except Exception as exc:
                if _handle_quota_error(exc):
                    break
                log.debug("YT like failed: %s", exc)

        # Comment on ~80% (quality comments drive subscribers — no restrictions on YT)
        if (not _quota_exhausted
                and random.random() < 0.80
                and can_act(data, "yt_comments", YT_DAILY_COMMENTS)):
            comment = _generate_yt_comment(cfg, video["title"])
            if comment:
                try:
                    youtube.commentThreads().insert(
                        part="snippet",
                        body={
                            "snippet": {
                                "videoId": video_id,
                                "topLevelComment": {
                                    "snippet": {
                                        "textOriginal": comment,
                                    }
                                },
                            }
                        },
                    ).execute()
                    record_action(data, "yt_comments", video_id)
                    stats["yt_comments"] += 1
                    log.debug("Commented on YT Short: %s", comment[:40])
                except Exception as exc:
                    if _handle_quota_error(exc):
                        break
                    log.debug("YT comment failed: %s", exc)

        save_log(LOG_FILE, data)
        random_delay(1, 3)  # blitz pace — YouTube has no action blocks

    if stats["yt_likes"] or stats["yt_comments"]:
        log.info("YouTube niche engagement: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# Feature: Reply to comments on own YouTube videos
# ---------------------------------------------------------------------------

def run_yt_reply_to_comments(cfg: Config, data: dict[str, Any]) -> int:
    """Reply to comments on our own recent YouTube videos. Returns reply count.

    Respects quota budget — reserves units for publishing first.
    """
    global _quota_exhausted
    replied = 0

    # Check quota budget
    budget = quota_budget_remaining(data)
    if budget < 100 or _quota_exhausted:
        log.info("YouTube quota budget too low for replies (%d units left) — skipping", budget)
        return 0

    try:
        youtube = _get_youtube_service()
    except Exception as exc:
        log.warning("YouTube auth failed (skipping replies): %s", exc)
        return 0

    # Get recent videos — check more videos for comments
    from youtube_publisher import get_recent_videos
    videos = get_recent_videos(max_results=10)

    if not videos:
        log.info("No recent YouTube videos to check for comments")
        return 0

    # Cap replies by budget (each reply = 50 units)
    max_replies_by_budget = max(2, budget // _QUOTA_COST["reply"])
    reply_limit = min(YT_DAILY_REPLIES, max_replies_by_budget)

    log.info("yt_replies: checking %d recent videos (budget: %d units, max %d replies)",
             len(videos), budget, reply_limit)

    # Track which comments we've already replied to
    replied_set: set[str] = {
        a["target"] for a in data.get("actions", []) if a.get("type") == "yt_replies"
    }

    for video in videos:
        if replied >= reply_limit or _quota_exhausted:
            break

        video_id = video.get("video_id", "")
        video_title = video.get("title", "")
        if not video_id:
            continue

        # Fetch comments
        try:
            response = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=50,
                order="time",  # newest first
            ).execute()
        except Exception as exc:
            if _handle_quota_error(exc):
                break
            log.info("Could not fetch comments for %s: %s", video_id, exc)
            continue

        comment_count = len(response.get("items", []))
        if comment_count == 0:
            log.info("yt_replies: video %s (%s) has no comments", video_id, video_title[:40])
        else:
            log.info("yt_replies: video %s (%s) has %d comments", video_id, video_title[:40], comment_count)

        for item in response.get("items", []):
            if replied >= reply_limit or _quota_exhausted:
                break

            comment_id = item.get("id", "")
            snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            comment_text = snippet.get("textOriginal", "")

            if not comment_id or not comment_text:
                continue
            if comment_id in replied_set:
                continue
            if len(comment_text) < 3:
                continue

            # Reply to ALL eligible comments — every reply drives algorithm signal
            reply = _generate_yt_reply(cfg, video_title, comment_text)
            if not reply:
                continue

            try:
                youtube.comments().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "parentId": comment_id,
                            "textOriginal": reply,
                        }
                    },
                ).execute()
                record_action(data, "yt_replies", comment_id)
                replied_set.add(comment_id)
                replied += 1
                log.debug("Replied to YT comment: %s → %s", comment_text[:30], reply[:30])
                random_delay(1, 4)  # blitz — YouTube has no action blocks
            except Exception as exc:
                if _handle_quota_error(exc):
                    break
                log.warning("YT reply failed for %s: %s", comment_id, exc)

    if replied:
        log.info("Replied to %d YouTube comments", replied)
    return replied


# ---------------------------------------------------------------------------
# Session dispatcher (called from orchestrator/engagement)
# ---------------------------------------------------------------------------

def run_yt_post_publish_replies(cfg: Config, video_ids: list[str]) -> int:
    """Immediately reply to comments on just-published videos.

    Called right after publishing to YouTube.  Replying within the first
    60 minutes is a critical algorithm signal — it shows the creator is
    active and sparks conversations that boost the video's distribution.

    This is NOT budget-capped since it's part of the publish cycle
    (publish quota was already reserved and spent).

    Args:
        video_ids: List of YouTube video IDs that were just published.

    Returns count of replies sent.
    """
    global _quota_exhausted
    if not video_ids:
        return 0

    replied = 0
    data = load_log(LOG_FILE)

    try:
        youtube = _get_youtube_service()
    except Exception as exc:
        log.warning("YouTube auth failed (skipping post-publish replies): %s", exc)
        return 0

    replied_set: set[str] = {
        a["target"] for a in data.get("actions", []) if a.get("type") == "yt_replies"
    }

    for video_id in video_ids:
        if _quota_exhausted:
            break
        log.info("Post-publish reply blitz: checking comments on %s", video_id)

        try:
            response = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=50,
                order="time",
            ).execute()
        except Exception as exc:
            if _handle_quota_error(exc):
                break
            log.info("Could not fetch comments for %s: %s", video_id, exc)
            continue

        for item in response.get("items", []):
            if _quota_exhausted:
                break
            comment_id = item.get("id", "")
            snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            comment_text = snippet.get("textOriginal", "")

            if not comment_id or not comment_text or len(comment_text) < 3:
                continue
            if comment_id in replied_set:
                continue

            reply = _generate_yt_reply(cfg, f"Just published Short ({video_id})", comment_text)
            if not reply:
                continue

            try:
                youtube.comments().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "parentId": comment_id,
                            "textOriginal": reply,
                        }
                    },
                ).execute()
                record_action(data, "yt_replies", comment_id)
                replied_set.add(comment_id)
                replied += 1
                log.debug("Post-publish reply: %s → %s", comment_text[:30], reply[:30])
                random_delay(1, 3)
            except Exception as exc:
                if _handle_quota_error(exc):
                    break
                log.warning("Post-publish reply failed: %s", exc)

    save_log(LOG_FILE, data)
    if replied:
        log.info("Post-publish reply blitz: sent %d replies", replied)
    return replied


def run_yt_session(cfg: Config, session_type: str = "yt_engage") -> dict[str, int]:
    """Run a YouTube engagement session.

    Session types:
      yt_engage   - Like + comment on niche Shorts
      yt_replies  - Reply to comments on own videos
      yt_full     - Both engagement and replies

    All engagement respects the quota budget — publishing always gets
    priority over engagement. Sessions self-limit when budget is low.
    """
    global _quota_exhausted
    _quota_exhausted = False  # Reset per session (quota resets daily)

    data = load_log(LOG_FILE)
    stats: dict[str, int] = {}

    session_startup_jitter()

    budget = quota_budget_remaining(data)
    used = _estimate_units_used(data)
    pub_windows = _remaining_publish_windows()
    log.info("YouTube session: %s | quota: %d/%d used, %d available for engagement "
             "(%d reserved for %d publish window(s))",
             session_type, used, _DAILY_QUOTA, budget,
             pub_windows * _PUBLISH_RESERVE, pub_windows)

    if session_type == "yt_engage":
        engage_stats = run_yt_niche_engagement(cfg, data)
        stats.update(engage_stats)

    elif session_type == "yt_replies":
        stats["yt_replies"] = run_yt_reply_to_comments(cfg, data)

    elif session_type == "yt_full":
        engage_stats = run_yt_niche_engagement(cfg, data)
        stats.update(engage_stats)
        if not _quota_exhausted:
            random_delay(3, 10)
            stats["yt_replies"] = run_yt_reply_to_comments(cfg, data)

    save_log(LOG_FILE, data)
    log.info("YouTube session '%s' done: %s (daily: %s)", session_type, stats, daily_summary(data))
    return stats
