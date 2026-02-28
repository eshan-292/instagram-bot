#!/usr/bin/env python3
"""YouTube engagement automation — like, comment, reply on Shorts in the niche.

Follows the same human-like patterns as Instagram engagement:
  - Gaussian delays between actions
  - Micro-breaks (distraction simulation)
  - Session size randomization
  - Skip some content (selective engagement)
  - AI-generated comments via Gemini

API Quota Budget (10,000 units/day default):
  - 1 video upload = 1,600 units
  - search.list = 100 units per call
  - commentThreads.list = 1 unit
  - commentThreads.insert = 50 units
  - videos.rate (like) = 50 units
  Budget: 1 upload + 6×engage(12 searches + 50 likes + 20 comments)
          + 6×replies(30 list + 30 replies) ≈ 7,330 units (73% of quota)
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any

from config import Config
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

# YouTube daily limits (aggressive — 12 parallel sessions/day, spread over 15 hours)
# Budget: 1 upload + 6×engage + 6×replies ≈ 7,330 of 10,000 API quota units
YT_DAILY_LIKES = 50
YT_DAILY_COMMENTS = 20
YT_DAILY_REPLIES = 30

# Search queries for finding niche Shorts to engage with
_NICHE_QUERIES = [
    "indian fashion shorts", "mumbai style tips", "desi outfit ideas",
    "indian street style", "ethnic wear styling", "budget fashion india",
    "indian girl style", "bollywood fashion", "mumbai fashion influencer",
    "saree styling tips", "kurti styling ideas", "indian wedding outfit",
    "desi fashion 2026", "indo western outfit", "college outfit india",
]


def _get_youtube_service():
    """Build authenticated YouTube API service."""
    from youtube_publisher import _build_credentials
    from googleapiclient.discovery import build

    creds = _build_credentials()
    return build("youtube", "v3", credentials=creds)


def _generate_yt_comment(cfg: Config, video_title: str) -> str | None:
    """Generate a genuine, context-aware comment for a YouTube Short."""
    if not cfg.gemini_api_key:
        return None
    from gemini_helper import generate

    prompt = (
        "You are Maya Varma, a 23-year-old Indian fashion influencer from Mumbai. "
        "Write a short, genuine YouTube comment (1-2 sentences, max 20 words) on a Short. "
        "Be warm, specific to the content, and authentic — NOT generic spam. "
        "No hashtags, max 1 emoji. Sound like a real viewer. "
        "Avoid: 'nice video', 'great content', 'love it'. "
        "Instead be specific about what you liked. "
        "Just the comment text, nothing else.\n\n"
        f"Video title: {video_title[:200]}"
    )
    comment = generate(cfg.gemini_api_key, prompt, cfg.gemini_model)
    if comment and 5 < len(comment) < 200:
        return comment
    return None


def _generate_yt_reply(cfg: Config, video_title: str, their_comment: str) -> str | None:
    """Generate a reply to a comment on our own YouTube video."""
    if not cfg.gemini_api_key:
        return None
    from gemini_helper import generate

    prompt = (
        "You are Maya Varma, a 23-year-old Indian fashion influencer from Mumbai. "
        "Someone commented on your YouTube Short. Write a warm, short reply (max 15 words). "
        "Be genuine and grateful but stay in character — bold, confident, witty. "
        "No hashtags. Max 1 emoji. Just the reply text.\n\n"
        f"Video title: {video_title[:200]}\n"
        f"Their comment: {their_comment[:200]}"
    )
    reply = generate(cfg.gemini_api_key, prompt, cfg.gemini_model)
    if reply and 3 < len(reply) < 150:
        return reply
    return None


def _should_skip() -> bool:
    """Randomly skip content — humans don't engage with everything."""
    return random.random() < 0.20


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
    """
    stats: dict[str, int] = {"yt_likes": 0, "yt_comments": 0}

    try:
        youtube = _get_youtube_service()
    except Exception as exc:
        log.warning("YouTube auth failed (skipping engagement): %s", exc)
        return stats

    # Pick 1-2 search queries (humans search one topic at a time)
    queries = random.sample(_NICHE_QUERIES, min(2, len(_NICHE_QUERIES)))
    all_videos: list[dict] = []

    for query in queries:
        try:
            response = youtube.search().list(
                part="snippet",
                q=query,
                type="video",
                videoDuration="short",  # Shorts only
                order="date",  # recent first
                maxResults=15,
                relevanceLanguage="en",
                regionCode="IN",
            ).execute()

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
            log.debug("YouTube search '%s' failed: %s", query, exc)

        time.sleep(random.uniform(2, 5))

    # Deduplicate and shuffle
    seen_ids: set[str] = set()
    videos: list[dict] = []
    for v in all_videos:
        if v["video_id"] not in seen_ids:
            seen_ids.add(v["video_id"])
            videos.append(v)
    random.shuffle(videos)

    session_size = _randomize_size(12)
    log.info("YouTube niche engagement: %d videos to browse", min(session_size, len(videos)))

    for video in videos[:session_size]:
        if _should_skip():
            time.sleep(random.uniform(1, 3))
            continue

        video_id = video["video_id"]

        # Pause like watching the Short
        time.sleep(random.uniform(3, 10))

        # Like
        if can_act(data, "yt_likes", YT_DAILY_LIKES):
            try:
                youtube.videos().rate(id=video_id, rating="like").execute()
                record_action(data, "yt_likes", video_id)
                stats["yt_likes"] += 1
                log.debug("Liked YT Short: %s", video["title"][:50])
            except Exception as exc:
                log.debug("YT like failed: %s", exc)

        # Comment on ~25% (quality comments drive subscribers)
        if (random.random() < 0.25
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
                    log.debug("YT comment failed: %s", exc)

        save_log(LOG_FILE, data)
        random_delay(15, 45)

    if stats["yt_likes"] or stats["yt_comments"]:
        log.info("YouTube niche engagement: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# Feature: Reply to comments on own YouTube videos
# ---------------------------------------------------------------------------

def run_yt_reply_to_comments(cfg: Config, data: dict[str, Any]) -> int:
    """Reply to comments on our own recent YouTube videos. Returns reply count."""
    replied = 0

    try:
        youtube = _get_youtube_service()
    except Exception as exc:
        log.warning("YouTube auth failed (skipping replies): %s", exc)
        return 0

    # Get recent videos
    from youtube_publisher import get_recent_videos
    videos = get_recent_videos(max_results=5)

    if not videos:
        log.debug("No recent YouTube videos to check for comments")
        return 0

    # Track which comments we've already replied to
    replied_set: set[str] = {
        a["target"] for a in data.get("actions", []) if a.get("type") == "yt_replies"
    }

    for video in videos:
        if replied >= YT_DAILY_REPLIES:
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
                maxResults=20,
                order="time",  # newest first
            ).execute()
        except Exception as exc:
            log.debug("Could not fetch comments for %s: %s", video_id, exc)
            continue

        for item in response.get("items", []):
            if replied >= YT_DAILY_REPLIES:
                break

            comment_id = item.get("id", "")
            snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            comment_text = snippet.get("textOriginal", "")
            author_channel = snippet.get("authorChannelId", {}).get("value", "")

            if not comment_id or not comment_text:
                continue
            if comment_id in replied_set:
                continue
            if len(comment_text) < 3:
                continue

            # Skip our own comments
            # (We'd need our channel ID to check, but most won't match)

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
                random_delay(20, 60)
            except Exception as exc:
                log.warning("YT reply failed for %s: %s", comment_id, exc)

    if replied:
        log.info("Replied to %d YouTube comments", replied)
    return replied


# ---------------------------------------------------------------------------
# Session dispatcher (called from orchestrator/engagement)
# ---------------------------------------------------------------------------

def run_yt_session(cfg: Config, session_type: str = "yt_engage") -> dict[str, int]:
    """Run a YouTube engagement session.

    Session types:
      yt_engage   - Like + comment on niche Shorts
      yt_replies  - Reply to comments on own videos
      yt_full     - Both engagement and replies
    """
    data = load_log(LOG_FILE)
    stats: dict[str, int] = {}

    session_startup_jitter()

    log.info("Starting YouTube session: %s", session_type)

    if session_type == "yt_engage":
        engage_stats = run_yt_niche_engagement(cfg, data)
        stats.update(engage_stats)

    elif session_type == "yt_replies":
        stats["yt_replies"] = run_yt_reply_to_comments(cfg, data)

    elif session_type == "yt_full":
        engage_stats = run_yt_niche_engagement(cfg, data)
        stats.update(engage_stats)
        random_delay(30, 90)
        stats["yt_replies"] = run_yt_reply_to_comments(cfg, data)

    save_log(LOG_FILE, data)
    log.info("YouTube session '%s' done: %s (daily: %s)", session_type, stats, daily_summary(data))
    return stats
