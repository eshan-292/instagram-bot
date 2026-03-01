#!/usr/bin/env python3
"""Main pipeline: generate → images → video → promote → publish (IG + YouTube)."""

from __future__ import annotations

import argparse
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from config import DEFAULT_QUEUE_FILE, Config, load_config, setup_logging
from engagement import run_engagement, run_session
from generator import generate_content
from image import fill_image_urls
from publisher import publish, _get_client
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

# Hashtag pyramid strategy (2026):
# 1 brand + 1 broad + 1-2 medium + 1 niche = 4-5 total (categorization, not discovery)
# All loaded from persona JSON at runtime.

def _get_hashtags():
    from persona import get_persona
    h = get_persona().get("hashtags", {})
    return {
        "brand": h.get("brand", []),
        "broad": h.get("broad", []),
        "medium": h.get("medium", []),
        "niche": h.get("niche", []),
        "carousel": h.get("carousel", []),
        "keyword_phrases": h.get("keyword_phrases", []),
    }

def _build_hashtags(caption: str, topic: str, post_type: str = "reel",
                    youtube_enabled: bool = False) -> tuple[str, str]:
    """Append 3-5 hashtags to caption; return (caption, first_comment_hashtags).

    Caption gets 3-5 targeted hashtags (pyramid strategy).
    First comment gets 15-20 extra hashtags for maximum discovery.
    No YouTube mentions or partner @mentions in captions.
    """
    h = _get_hashtags()
    # Caption hashtags: 1 brand + 1 broad + 1-2 medium + 1 niche = 3-5 total
    caption_tags = list(h["brand"])  # brand (always)

    broad, medium, niche = h["broad"], h["medium"], h["niche"]
    carousel = h["carousel"]

    if post_type == "carousel":
        caption_tags.extend(random.sample(carousel, min(3, len(carousel))))
    else:
        if broad: caption_tags.append(random.choice(broad))
        if medium: caption_tags.extend(random.sample(medium, min(2, len(medium))))
        if niche: caption_tags.append(random.choice(niche))

    caption_tags = caption_tags[:5]

    # One keyword phrase (drives search discovery)
    kw = h["keyword_phrases"]
    keyword = random.choice(kw) if kw else ""
    hashtag_block = " ".join(f"#{t}" for t in caption_tags)

    result = f"{caption}\n.\n{keyword}\n.\n{hashtag_block}" if keyword else f"{caption}\n.\n{hashtag_block}"

    # First comment: 15-20 extra hashtags for maximum reach
    # Mix from all pools, excluding the ones already in caption
    extra_tags = []
    all_pools = broad + medium + niche + carousel
    remaining = [t for t in all_pools if t not in caption_tags]
    random.shuffle(remaining)
    extra_tags = remaining[:18]

    first_comment = ""
    if extra_tags:
        first_comment = ".\n" + " ".join(f"#{t}" for t in extra_tags)

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


def main() -> int:
    # Load .env FIRST so PERSONA is available before any lazy path resolution
    # (argparse defaults trigger str(DEFAULT_QUEUE_FILE) which needs PERSONA)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ModuleNotFoundError:
        pass

    parser = argparse.ArgumentParser(description="Instagram + YouTube bot pipeline")
    parser.add_argument("--queue-file", default=str(DEFAULT_QUEUE_FILE))
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--no-generate", action="store_true")
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--no-engage", action="store_true")
    parser.add_argument("--session", type=str, default=None,
                        help="Run a specific session type (morning/replies/hashtags/explore/"
                             "maintenance/stories/report/yt_engage/yt_replies/yt_full/"
                             "cross_promo/sat_boost/sat_background)")
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

        # Steps 1-4: content generation pipeline (skipped with --no-generate)
        if not args.no_generate:
            # 1. Generate content if queue is low
            if _should_generate(posts, cfg):
                generate_content(args.queue_file, cfg)
                posts = read_queue(args.queue_file)
                log.info("Post-generation: %s", status_counts(posts))

            # 2. Fill image URLs
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

        # 5. Publish next eligible post (Instagram + YouTube)
        if not args.no_publish:
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
            # YouTube-specific sessions
            if args.session.startswith("yt_"):
                if cfg.youtube_enabled and cfg.youtube_engagement_enabled:
                    from youtube_engagement import run_yt_session
                    yt_stats = run_yt_session(cfg, args.session)
                    log.info("YouTube session '%s': %s", args.session, yt_stats)
                else:
                    log.info("YouTube engagement disabled, skipping %s", args.session)
            elif args.session == "cross_promo":
                from cross_promo import run_cross_promo_engagement
                from publisher import _get_client as get_cl
                from rate_limiter import load_log, save_log, LOG_FILE
                data = load_log(str(LOG_FILE))
                xp_cl = get_cl(cfg)
                xp_stats = run_cross_promo_engagement(xp_cl, cfg, data)
                save_log(str(LOG_FILE), data)
                log.info("Cross-promo session: %s", xp_stats)
            else:
                # Instagram session
                engagement_stats = run_session(cfg, args.session)
                log.info("Session '%s': %s", args.session, engagement_stats)
        elif not args.no_engage and cfg.engagement_enabled:
            engagement_stats = run_engagement(cfg)
            log.info("Engagement: %s", engagement_stats)

        return 0
    except Exception as exc:
        log.error("Pipeline failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
