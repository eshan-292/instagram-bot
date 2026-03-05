#!/usr/bin/env python3
"""Main pipeline: generate → images → video → promote → publish (IG + YouTube)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from config import (DEFAULT_QUEUE_FILE, GENERATED_IMAGES_DIR, REFERENCE_DIR,
                    SESSION_FILE, Config, load_config, setup_logging)
from engagement import run_engagement, run_session
from generator import generate_content
from image import fill_image_urls
from persona import get_persona
from publisher import publish, _get_client, ChallengeAbort
from video import convert_posts_to_video
from post_queue import (
    find_eligible,
    format_utc,
    parse_scheduled_at,
    publishable_count,
    read_queue,
    status_counts,
    write_queue,
)

log = logging.getLogger(__name__)


def _should_generate(posts: list[dict[str, Any]], cfg: Config) -> bool:
    return publishable_count(posts) < cfg.min_ready_queue


def _promote_drafts(posts: list[dict[str, Any]], cfg: Config) -> int:
    now = datetime.now(timezone.utc)
    interval = timedelta(minutes=cfg.schedule_interval_minutes)
    next_slot = now + timedelta(minutes=cfg.schedule_lead_minutes)

    for item in posts:
        dt = parse_scheduled_at(item.get("scheduled_at"))
        if dt and dt >= next_slot:
            next_slot = dt + interval

    promoted = 0
    for item in posts:
        if str(item.get("status", "")).strip().lower() != "draft":
            continue
        if not item.get("caption"):
            continue
        post_type = str(item.get("post_type", "reel")).lower()
        has_media = (
            (post_type == "carousel" and item.get("carousel_images"))
            or item.get("image_url")
            or item.get("video_url")
        )
        if not has_media:
            continue
        item["status"] = cfg.auto_promote_status
        dt = parse_scheduled_at(item.get("scheduled_at"))
        if dt is None or dt <= now:
            item["scheduled_at"] = format_utc(next_slot)
            next_slot += interval
        promoted += 1
    return promoted


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Hashtag injection — appended to caption at publish time
# ---------------------------------------------------------------------------
# 2026 algorithm: 3-5 targeted hashtags > 30 generic ones.
# Instagram now treats captions as keyword search — front-loaded topic keywords
# carry more reach weight than hashtag spraying.

# Core hashtag pool — pick 3-5 per post for variety without spam signals
def _hashtag_pool():
    """Return broad + medium + niche hashtags as a combined pool."""
    h = get_persona().get("hashtags", {})
    return h.get("broad", []) + h.get("medium", []) + h.get("niche", [])


# Carousel-specific tags (drives saves — the highest-weight signal)
def _carousel_tags():
    return get_persona().get("hashtags", {}).get("carousel", [])


def _keyword_phrases():
    return get_persona().get("hashtags", {}).get("keyword_phrases", [])


# Cross-platform promotion CTAs — drives YouTube subscribers from IG
def _cross_promo_ctas():
    return get_persona().get("cross_promo", {}).get("youtube_ctas", [])


def _get_hashtags():
    h = get_persona().get("hashtags", {})
    return {
        "brand": h.get("brand", []),
        "broad": h.get("broad", []),
        "medium": h.get("medium", []),
        "niche": h.get("niche", []),
        "carousel": h.get("carousel", []),
        "keyword_phrases": h.get("keyword_phrases", []),
    }

def _fetch_trending_hashtags(cfg: Config | None = None) -> list[str]:
    """Return ~20 currently-trending Instagram hashtags via Gemini.

    Results are cached per day in trending_hashtags_cache.json so we only
    make one Gemini call per persona per day.  Falls back to a hardcoded
    list if Gemini is unavailable or returns garbage.
    """
    FALLBACK = [
        "trending", "viral", "explorepage", "foryou", "reels",
        "instagood", "photooftheday", "fyp", "viralpost", "trendingnow",
        "explore", "instagram", "reelsinstagram", "instadaily", "love",
        "aesthetic", "mood", "ootd", "reelsofinstagram", "lifestyle",
    ]

    from persona import persona_data_dir
    cache_path = persona_data_dir() / "trending_hashtags_cache.json"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Check daily cache
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                cached = json.load(f)
            if cached.get("date") == today and isinstance(cached.get("tags"), list):
                log.debug("Using cached trending hashtags (%d tags)", len(cached["tags"]))
                return cached["tags"]
        except (json.JSONDecodeError, OSError):
            pass

    # Need Gemini to fetch fresh trending tags
    if cfg is None or not cfg.gemini_api_key:
        log.debug("No Gemini API key — using fallback trending hashtags")
        return FALLBACK

    from gemini_helper import generate

    prompt = (
        "List exactly 20 currently-trending Instagram hashtags for March 2026. "
        "Include a mix of: viral/general hashtags, lifestyle/aesthetic hashtags, "
        "engagement-bait hashtags (like 'fyp', 'viral'), and broad discovery hashtags. "
        "Return ONLY the hashtags as a comma-separated list WITHOUT the # symbol. "
        "Example format: trending, viral, explorepage, fyp, instagood\n"
        "Do not include any other text, explanations, or numbering."
    )

    try:
        raw = generate(cfg.gemini_api_key, prompt, cfg.gemini_model)
        if not raw:
            raise ValueError("Empty Gemini response")

        # Parse comma-separated tags, strip whitespace and # symbols
        tags = [
            t.strip().lstrip("#").replace(" ", "").lower()
            for t in raw.replace("\n", ",").split(",")
            if t.strip()
        ]
        # Filter out garbage (too long, contains non-alphanum, empty)
        tags = [t for t in tags if t and len(t) <= 30 and t.isalnum()]

        if len(tags) < 5:
            log.warning("Gemini returned too few trending tags (%d), using fallback", len(tags))
            tags = FALLBACK
        else:
            tags = tags[:25]  # cap at 25 in case Gemini over-produces
            log.info("Fetched %d trending hashtags via Gemini", len(tags))

        # Cache for the day
        try:
            with open(cache_path, "w") as f:
                json.dump({"date": today, "tags": tags}, f)
        except OSError as exc:
            log.warning("Failed to cache trending hashtags: %s", exc)

        return tags

    except Exception as exc:
        log.warning("Trending hashtag fetch failed: %s — using fallback", exc)
        return FALLBACK


def _get_series_hashtag(item: dict[str, Any]) -> str | None:
    """Extract series hashtag from post notes if it's a series post."""
    notes = str(item.get("notes", ""))
    if not notes.startswith("series:"):
        return None
    # notes format: "series:Friday Fits | ..."
    # Look up the series name in persona config to find the hashtag
    series_name = notes.split("|")[0].replace("series:", "").strip()
    for s in get_persona().get("content_series", []):
        if s.get("name", "").lower() == series_name.lower():
            return s.get("series_hashtag", "")
    return None


def _build_hashtags(caption: str, topic: str, post_type: str = "reel",
                    youtube_enabled: bool = False,
                    cfg: Config | None = None,
                    item: dict[str, Any] | None = None) -> tuple[str, str]:
    """Append 3-5 hashtags to caption; return (caption, first_comment_hashtags).

    Caption gets 3-5 targeted hashtags (pyramid strategy).
    First comment fills up to 30 TOTAL hashtags (caption + comment) with a
    mix of ~60% niche/persona tags + ~40% trending tags for max discovery.
    """
    h = _get_hashtags()
    # Caption hashtags: 1 brand + 1 broad + 1-2 medium + 1 niche = 3-5 total
    caption_tags = list(h["brand"])  # brand (always)

    # Inject series-specific hashtag if this is a series post
    if item:
        series_tag = _get_series_hashtag(item)
        if series_tag:
            caption_tags.append(series_tag)

    broad, medium, niche = h["broad"], h["medium"], h["niche"]
    carousel = h["carousel"]

    if post_type == "carousel":
        caption_tags.extend(random.sample(carousel, min(3, len(carousel))))
    else:
        if broad: caption_tags.append(random.choice(broad))
        if medium: caption_tags.extend(random.sample(medium, min(2, len(medium))))
        if niche: caption_tags.append(random.choice(niche))

    caption_tags = caption_tags[:5]
    caption_count = len(caption_tags)

    # One keyword phrase (drives search discovery)
    kw = h["keyword_phrases"]
    keyword = random.choice(kw) if kw else ""
    hashtag_block = " ".join(f"#{t}" for t in caption_tags)

    result = f"{caption}\n.\n{keyword}\n.\n{hashtag_block}" if keyword else f"{caption}\n.\n{hashtag_block}"

    # Cross-platform promo on ~40% of posts when YouTube is enabled
    ctas = _cross_promo_ctas()
    if youtube_enabled and ctas and random.random() < 0.40:
        promo = random.choice(ctas)
        result += f"\n.\n{promo}"

    # First comment: fill up to 30 TOTAL hashtags (Instagram limit)
    # Mix ~60% niche/persona tags + ~40% trending for maximum exposure
    MAX_TOTAL = 30
    slots = MAX_TOTAL - caption_count  # how many we can fit in first comment

    # Pool 1: persona niche/medium/broad/carousel tags (not already in caption)
    niche_pool = [t for t in (broad + medium + niche + carousel) if t not in caption_tags]
    random.shuffle(niche_pool)

    # Pool 2: trending hashtags (even if irrelevant — max exposure)
    trending = _fetch_trending_hashtags(cfg)
    # Remove any overlap with caption or niche pool
    used = set(caption_tags) | set(niche_pool)
    trending_pool = [t for t in trending if t not in used]
    random.shuffle(trending_pool)

    # Fill: ~60% niche, ~40% trending
    niche_slots = int(slots * 0.6)
    trending_slots = slots - niche_slots

    picked_niche = niche_pool[:niche_slots]
    picked_trending = trending_pool[:trending_slots]

    # If either pool is short, fill from the other
    combined = picked_niche + picked_trending
    if len(combined) < slots:
        remaining_niche = [t for t in niche_pool if t not in combined]
        remaining_trending = [t for t in trending_pool if t not in combined]
        filler = remaining_niche + remaining_trending
        combined.extend(filler[:slots - len(combined)])

    # Shuffle so niche/trending are interleaved naturally
    random.shuffle(combined)

    first_comment = ""
    if combined:
        first_comment = ".\n" + " ".join(f"#{t}" for t in combined)

    return result, first_comment


# ---------------------------------------------------------------------------
# YouTube Shorts publishing
# ---------------------------------------------------------------------------

def _publish_to_youtube(cfg: Config, item: dict[str, Any], idx: int,
                        posts: list[dict[str, Any]], queue_file: str) -> None:
    """Publish a post to YouTube Shorts alongside Instagram.

    Uses the YouTube-optimized 9:16 video if available, otherwise falls back
    to the Instagram 4:5 video.
    """
    if not cfg.youtube_enabled:
        return

    from youtube_publisher import publish_short

    # Prefer YouTube-format video, fall back to Instagram video
    yt_video = str(item.get("youtube_video_url") or "").strip()
    ig_video = str(item.get("video_url") or "").strip()
    video_path = yt_video or ig_video

    if not video_path:
        log.debug("No video for YouTube upload of %s", item.get("id"))
        return

    topic = str(item.get("topic", ""))
    caption = str(item.get("caption", ""))
    youtube_title = str(item.get("youtube_title", "")).strip() or None
    thumbnail = str(item.get("image_url", "")) or None

    try:
        yt_id = publish_short(video_path, topic, caption,
                              thumbnail_path=thumbnail,
                              custom_title=youtube_title)
        if yt_id:
            posts[idx]["youtube_video_id"] = yt_id
            posts[idx]["youtube_posted_at"] = _utc_now_iso()
            write_queue(queue_file, posts)
            log.info("Published to YouTube: %s → https://youtube.com/shorts/%s",
                     item.get("id"), yt_id)
        else:
            log.warning("YouTube upload returned no ID for %s", item.get("id"))
    except Exception as exc:
        log.error("YouTube publish failed for %s: %s", item.get("id"), exc)


def _yt_only_publish(cfg: Config, posts: list[dict[str, Any]],
                     queue_file: str) -> None:
    """Publish to YouTube Shorts independently — no Instagram required.

    Finds the next eligible post (ready/approved with a video) and publishes
    it to YouTube only.  Does NOT change the post status (so the IG workflow
    can still publish it to Instagram later).
    """
    if not cfg.youtube_enabled:
        log.info("YouTube disabled, skipping yt-publish-only")
        return

    # Find next post eligible for YouTube (has video, not yet on YT)
    for idx, item in enumerate(posts):
        status = str(item.get("status", ""))
        if status not in ("ready", "approved", "posted"):
            continue
        # Skip if already published to YouTube
        if item.get("youtube_video_id"):
            continue
        # Need a video file
        yt_video = str(item.get("youtube_video_url") or "").strip()
        ig_video = str(item.get("video_url") or "").strip()
        if not yt_video and not ig_video:
            continue

        log.info("YT-only publish: found eligible post %s (status=%s)", item.get("id"), status)
        _publish_to_youtube(cfg, item, idx, posts, queue_file)
        return

    log.info("No eligible posts for YouTube-only publishing")


def main() -> int:
    # Load .env FIRST so PERSONA is available before any lazy path resolution
    # (argparse defaults trigger str(DEFAULT_QUEUE_FILE) which needs PERSONA)
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ModuleNotFoundError:
        pass

    # CRITICAL: Reset the persona singleton AND lazy paths so they re-read
    # the PERSONA env var from .env.  Module imports may have triggered
    # get_persona() BEFORE load_dotenv(), caching the wrong persona
    # (defaulting to "maya").
    from persona import reset_persona
    reset_persona()
    # Also reset lazy path caches that may have resolved to the wrong persona dir
    DEFAULT_QUEUE_FILE.reset()
    SESSION_FILE.reset()
    REFERENCE_DIR.reset()
    GENERATED_IMAGES_DIR.reset()

    parser = argparse.ArgumentParser(description="Instagram + YouTube bot pipeline")
    parser.add_argument("--queue-file", default=str(DEFAULT_QUEUE_FILE))
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--no-generate", action="store_true")
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--yt-publish-only", action="store_true",
                        help="Publish to YouTube only (skip Instagram)")
    parser.add_argument("--no-engage", action="store_true")
    parser.add_argument("--session", type=str, default=None,
                        help="Run a specific session type (morning/replies/hashtags/explore/"
                             "maintenance/stories/report/yt_engage/yt_replies/yt_full/"
                             "commenter_target/cross_promo/sat_boost/sat_background)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        cfg = load_config()

        # Satellite accounts have a simplified pipeline — engagement only
        # (no content queue, no publishing, no generation)
        # Check BEFORE reading queue since satellites don't have content_queue.json
        from persona import is_satellite
        if is_satellite():
            if args.session:
                from satellite import run_satellite_session
                sat_stats = run_satellite_session(cfg, args.session)
                log.info("Satellite session '%s': %s", args.session, sat_stats)
            else:
                log.info("Satellite mode — no session specified, nothing to do")
            return 0

        posts = read_queue(args.queue_file)
        log.info("Queue: %s", status_counts(posts))

        if args.dry_run:
            chosen = find_eligible(posts)
            if chosen:
                print(json.dumps({k: chosen[1].get(k) for k in
                    ("id", "status", "post_type", "scheduled_at", "caption",
                     "image_url", "carousel_images", "youtube_video_url")}, ensure_ascii=True))
            else:
                print("No eligible posts")
            return 0

        # Step 1: content generation (skipped with --no-generate)
        if not args.no_generate:
            if _should_generate(posts, cfg):
                generate_content(args.queue_file, cfg)
                posts = read_queue(args.queue_file)
                log.info("Post-generation: %s", status_counts(posts))

        # Steps 2-4 always run — they process existing images/drafts
        # even when content generation is skipped.

        # 2. Fill image URLs (scans pending/ for user-placed images)
        updated = fill_image_urls(posts, cfg)
        if updated:
            write_queue(args.queue_file, posts)
            log.info("Filled %d image URLs", updated)

        # 3. Convert images to video (IG Reels + YouTube Shorts)
        video_count = convert_posts_to_video(posts, youtube=cfg.youtube_enabled)
        if video_count:
            write_queue(args.queue_file, posts)
            log.info("Converted %d posts to video", video_count)

        # 4. Promote drafts
        if cfg.auto_promote_drafts:
            promoted = _promote_drafts(posts, cfg)
            if promoted:
                write_queue(args.queue_file, posts)
                log.info("Promoted %d drafts", promoted)

        # 5. Publish next eligible post
        if not args.no_publish:
            if args.yt_publish_only:
                # YouTube-only publishing — independent of Instagram
                _yt_only_publish(cfg, posts, args.queue_file)
            else:
                # Normal flow: Instagram + YouTube
                chosen = find_eligible(posts)
                if chosen is None:
                    log.info("No eligible posts to publish")
                else:
                    idx, item = chosen
                    caption = str(item.get("caption", ""))
                    image_url = str(item.get("image_url", ""))
                    video_url = str(item.get("video_url") or "").strip() or None
                    is_reel = bool(item.get("is_reel", False))
                    post_type = str(item.get("post_type", "reel")).strip().lower()
                    carousel_images = item.get("carousel_images") or None

                    has_media = (
                        (post_type == "carousel" and carousel_images)
                        or image_url
                        or video_url
                    )
                    if not has_media:
                        log.warning("Post %s has no media, skipping", item.get("id"))
                    else:
                        # Inject hashtags (caption + first comment for extra reach)
                        full_caption, first_comment_hashtags = _build_hashtags(
                            caption, str(item.get("topic", "")), post_type,
                            youtube_enabled=cfg.youtube_enabled,
                            cfg=cfg,
                            item=item,
                        )

                        # Publish to Instagram (with alt_text for SEO + accessibility)
                        alt_text = str(item.get("alt_text", "")).strip() or None
                        try:
                            post_id = publish(cfg, full_caption, image_url,
                                              video_url=video_url, is_reel=is_reel,
                                              carousel_images=carousel_images,
                                              post_type=post_type,
                                              alt_text=alt_text,
                                              first_comment=first_comment_hashtags)
                            posts[idx]["status"] = "posted"
                            posts[idx]["posted_at"] = _utc_now_iso()
                            posts[idx]["platform_post_id"] = post_id
                            posts[idx]["publish_error"] = None
                            log.info("Published %s → %s", item.get("id"), post_id)
                        except ChallengeAbort:
                            raise  # Don't catch — abort immediately
                        except Exception as exc:
                            posts[idx]["status"] = "failed"
                            posts[idx]["publish_error"] = str(exc)
                            log.error("Publish failed for %s: %s", item.get("id"), exc)

                        write_queue(args.queue_file, posts)

                        # Publish to YouTube Shorts (non-blocking — IG publish is primary)
                        if posts[idx].get("status") == "posted":
                            _publish_to_youtube(cfg, posts[idx], idx, posts, args.queue_file)

                            # Post-publish engagement burst (first 30 min = algorithmic fate)
                            # Pin CTA comment + story repost + mini engagement burst
                            if cfg.engagement_enabled:
                                try:
                                    from engagement import run_post_publish_burst
                                    pub_cl = _get_client(cfg)
                                    burst_stats = run_post_publish_burst(
                                        pub_cl, cfg,
                                        str(posts[idx].get("platform_post_id", "")),
                                        posts[idx],
                                    )
                                    log.info("Post-publish burst: %s", burst_stats)
                                except Exception as exc:
                                    log.warning("Post-publish burst failed: %s", exc)

        # 6. Engagement (Instagram + YouTube sessions)
        if args.session:
            session_stats = {}
            session_error = None
            try:
                # YouTube-specific sessions
                if args.session.startswith("yt_"):
                    if cfg.youtube_enabled and cfg.youtube_engagement_enabled:
                        from youtube_engagement import run_yt_session
                        session_stats = run_yt_session(cfg, args.session)
                        log.info("YouTube session '%s': %s", args.session, session_stats)
                    else:
                        log.info("YouTube engagement disabled, skipping %s", args.session)
                elif args.session == "cross_promo":
                    from cross_promo import run_cross_promo_engagement
                    from publisher import _get_client as get_cl
                    from rate_limiter import load_log, save_log, LOG_FILE
                    data = load_log(str(LOG_FILE))
                    xp_cl = get_cl(cfg)
                    session_stats = run_cross_promo_engagement(xp_cl, cfg, data)
                    save_log(str(LOG_FILE), data)
                    log.info("Cross-promo session: %s", session_stats)
                else:
                    # Instagram session
                    session_stats = run_session(cfg, args.session)
                    log.info("Session '%s': %s", args.session, session_stats)
            except ChallengeAbort:
                raise  # Don't catch — abort immediately
            except Exception as exc:
                session_error = str(exc)
                log.error("Session '%s' failed: %s", args.session, exc)

            # Send Telegram alert for every session (not just daily report)
            try:
                from report import send_session_alert
                pid = get_persona().get("id", "unknown")
                send_session_alert(pid, args.session, session_stats or {},
                                   error=session_error)
            except Exception:
                pass

        elif not args.no_engage and cfg.engagement_enabled:
            engagement_stats = run_engagement(cfg)
            log.info("Engagement: %s", engagement_stats)

        return 0
    except ChallengeAbort as exc:
        log.error(
            "CHALLENGE ABORT: Instagram requires verification — ALL API calls stopped. "
            "Log into Instagram on your phone to resolve, then re-seed session. "
            "Error: %s", exc
        )
        # Send alert for challenge abort
        try:
            from report import send_session_alert
            persona_id = os.getenv("PERSONA", "unknown")
            send_session_alert(
                persona_id, args.session or "pipeline", {},
                error=f"⚠️ CHALLENGE ABORT: {exc}",
            )
        except Exception:
            pass
        return 1
    except Exception as exc:
        log.error("Pipeline failed: %s", exc)
        # Send alert for pipeline crash
        try:
            from report import send_session_alert
            persona_id = os.getenv("PERSONA", "unknown")
            send_session_alert(persona_id, "pipeline", {},
                               error=str(exc))
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
