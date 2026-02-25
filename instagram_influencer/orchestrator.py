#!/usr/bin/env python3
"""Main pipeline: generate → images → video → promote → publish."""

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
from publisher import publish
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
        if not item.get("caption") or (not item.get("image_url") and not item.get("video_url")):
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

# Brand / personal (always included)
_BRAND_TAGS = ["mayavarma", "mayastyle"]

# Niche pools — pick a random subset each time to avoid shadow bans
_NICHE_POOLS = {
    "indian_fashion": [
        "indianfashion", "desifashion", "indianstreetstyle", "desistyle",
        "indianfashionblogger", "bollywoodfashion", "lehengalove",
        "indianwear", "ethnicwear", "fusionwear", "desivibes",
    ],
    "mumbai": [
        "mumbai", "mumbailifestyle", "mumbaifashion", "mumbaigirl",
        "mumbaiblogger", "mumbailife", "bandradiaries",
    ],
    "style": [
        "ootd", "styleinspo", "fashionreels", "outfitoftheday",
        "fashiongram", "stylediaries", "lookoftheday", "whatiwore",
        "fashioninfluencer", "styleblogger",
    ],
    "reels": [
        "reelsinstagram", "reelsindia", "trendingreels", "viralreels",
        "explorepage", "reelitfeelit", "instareels",
    ],
    "lifestyle": [
        "girlboss", "confidentwomen", "luxurylifestyle", "aestheticfeed",
        "browngirlmagic", "southasianstyle", "desigirl",
    ],
}


_KEYWORD_PHRASES = [
    "Mumbai fashion", "Indian street style", "Outfit inspiration",
    "Desi fashion diaries", "Style tips India", "Fashion influencer Mumbai",
    "Ethnic modern fusion", "Indian girl style", "Bollywood fashion vibes",
]


def _build_hashtags(caption: str, topic: str) -> str:
    """Append keyword phrases + hashtags to the caption for algorithm reach."""
    tags = list(_BRAND_TAGS)

    # Pick from each pool
    for pool_name, pool_tags in _NICHE_POOLS.items():
        pick = min(4, len(pool_tags))
        tags.extend(random.sample(pool_tags, pick))

    # Dedupe, shuffle, cap at 30
    seen: set[str] = set()
    unique: list[str] = []
    for t in tags:
        low = t.lower()
        if low not in seen:
            seen.add(low)
            unique.append(low)
    random.shuffle(unique)
    unique = unique[:30]

    # Keywords (2-3 phrases, separated by pipes) — drives 30% more reach than hashtags alone
    keywords = " | ".join(random.sample(_KEYWORD_PHRASES, min(3, len(_KEYWORD_PHRASES))))
    hashtag_block = " ".join(f"#{t}" for t in unique)
    return f"{caption}\n.\n{keywords}\n.\n{hashtag_block}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Instagram bot pipeline")
    parser.add_argument("--queue-file", default=str(DEFAULT_QUEUE_FILE))
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--no-generate", action="store_true")
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--no-engage", action="store_true")
    parser.add_argument("--session", type=str, default=None,
                        help="Run a specific engagement session type (morning/replies/hashtags/explore/maintenance)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        cfg = load_config()
        posts = read_queue(args.queue_file)
        log.info("Queue: %s", status_counts(posts))

        if args.dry_run:
            chosen = find_eligible(posts)
            if chosen:
                print(json.dumps({k: chosen[1].get(k) for k in
                    ("id", "status", "scheduled_at", "caption", "image_url")}, ensure_ascii=True))
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

            # 3. Convert images to video (for Reels — 2.25x more reach)
            video_count = convert_posts_to_video(posts)
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
            chosen = find_eligible(posts)
            if chosen is None:
                log.info("No eligible posts to publish")
            else:
                idx, item = chosen
                caption = str(item.get("caption", ""))
                image_url = str(item.get("image_url", ""))
                video_url = str(item.get("video_url") or "").strip() or None
                is_reel = bool(item.get("is_reel", False))

                if not image_url and not video_url:
                    log.warning("Post %s has no media, skipping", item.get("id"))
                else:
                    # Inject hashtags for discoverability
                    full_caption = _build_hashtags(caption, str(item.get("topic", "")))

                    try:
                        post_id = publish(cfg, full_caption, image_url,
                                          video_url=video_url, is_reel=is_reel)
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

        # 6. Engagement (like/comment/follow on niche posts)
        if args.session:
            # Session-only mode: skip publishing, just run engagement session
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
