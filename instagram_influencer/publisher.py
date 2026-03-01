#!/usr/bin/env python3
"""Publish to Instagram via instagrapi (Reels or photos)."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path

import requests
from instagrapi import Client
from instagrapi.exceptions import ChallengeRequired, LoginRequired
from pydantic import ValidationError

from config import SESSION_FILE, Config
import instagrapi_patch  # noqa: F401 — applies monkey-patches on import

log = logging.getLogger(__name__)


def _challenge_handler(username: str, choice) -> str:
    """Non-interactive challenge handler for CI/cloud environments.

    Instead of blocking on input(), raises an error so the bot
    can skip this run gracefully and retry later with a valid session.
    """
    raise ChallengeRequired(
        f"Instagram challenge for {username} (choice={choice}) — "
        "cannot complete in non-interactive mode. "
        "Re-seed the session from a local login."
    )


def _new_client() -> Client:
    """Create a fresh Client with realistic, up-to-date device settings."""
    cl = Client()
    cl.delay_range = [4, 12]  # human-like delay between API calls
    cl.set_locale("en_IN")
    cl.set_country_code(91)
    cl.set_timezone_offset(19800)  # IST = UTC+5:30

    # Non-interactive challenge handler (avoids input() blocking in CI)
    cl.challenge_code_handler = _challenge_handler

    # Override outdated default app version (269.x) — Instagram blocks old versions
    cl.set_device({
        "app_version": "357.0.0.25.101",
        "android_version": 34,
        "android_release": "14",
        "dpi": "480dpi",
        "resolution": "1080x2340",
        "manufacturer": "Samsung",
        "device": "dm1q",
        "model": "SM-S911B",
        "cpu": "qcom",
        "version_code": "608720130",
    })
    cl.set_user_agent(
        "Instagram 357.0.0.25.101 Android (34/14; 480dpi; 1080x2340; "
        "samsung; SM-S911B; dm1q; qcom; en_IN; 608720130)"
    )
    return cl


def _is_login_required_error(exc: Exception) -> bool:
    """Check if an exception is caused by an expired/invalid session."""
    msg = str(exc).lower()
    return "login_required" in msg or "login required" in msg


def _delete_session() -> None:
    try:
        os.remove(str(SESSION_FILE))
    except OSError:
        pass


def _get_client(cfg: Config) -> Client:
    """Login via saved session or username/password.

    Priority:
      1. Saved session file (preserves device UUIDs, avoids new challenges)
      2. Username/password (creates a proper mobile session)

    Browser session IDs (login_by_sessionid) are NOT used because they
    produce web-origin cookies that work for user_info but get 403 on
    upload endpoints (rupload_igphoto, rupload_igvideo).
    """
    session_path = str(SESSION_FILE)

    # 1. Try saved session file (skip browsing-API validation)
    if os.path.exists(session_path):
        try:
            cl = _new_client()
            cl.load_settings(session_path)
            cl.login(cfg.instagram_username, cfg.instagram_password)
            log.debug("Logged in via saved session")
            cl.dump_settings(session_path)
            return cl
        except (LoginRequired, ChallengeRequired) as exc:
            log.warning("Saved session invalid (%s), deleting", exc)
            _delete_session()
        except Exception as exc:
            log.warning("Saved session error: %s", exc)
            _delete_session()

    # 2. Fresh username/password login (new device UUIDs → proper mobile session)
    if not cfg.instagram_username or not cfg.instagram_password:
        raise RuntimeError(
            "Set INSTAGRAM_USERNAME + INSTAGRAM_PASSWORD in .env"
        )

    _delete_session()
    cl = _new_client()
    cl.login(cfg.instagram_username, cfg.instagram_password)
    log.info("Logged in via username/password")
    cl.dump_settings(session_path)
    return cl


def _resolve_media(url: str) -> tuple[str, bool]:
    """Resolve a media URL to a local file path. Returns (path, is_temp)."""
    if not url.startswith(("http://", "https://")):
        if not os.path.exists(url):
            raise RuntimeError(f"Local file not found: {url}")
        return url, False

    resp = requests.get(url, timeout=120)
    if resp.status_code >= 400:
        raise RuntimeError(f"Failed to download media ({resp.status_code})")
    suffix = ".mp4" if "video" in resp.headers.get("content-type", "") else ".jpg"
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="ig_post_")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(resp.content)
    return path, True


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except Exception:
        pass


# Trending music search queries — expanded for Indian fashion niche variety
# Rotated per upload so the bot never repeats the same audio pattern
_MUSIC_QUERIES = [
    # Bollywood / Indian pop (highest trending potential in India)
    "trending bollywood", "trending hindi", "bollywood 2026",
    "arijit singh trending", "desi pop", "hindi viral",
    "bollywood aesthetic", "bollywood remix trending",
    # Fashion / lifestyle (niche trending audio)
    "fashion vibes", "runway music", "aesthetic music",
    "chill vibes", "confidence anthem", "girl boss energy",
    "stylish beat", "trendy pop", "feel good music",
    # Indian aesthetic / cultural
    "indian aesthetic", "mumbai nights", "desi beats",
    "ethnic fusion music", "indian lo-fi", "desi vibes",
    # Viral / trending general
    "trending reels", "viral audio", "trending sound",
    "lo-fi beats", "trending 2026", "viral reel sound",
]


def _find_trending_track(cl: Client) -> Any | None:
    """Search for a trending track to overlay on the Reel.

    Tries up to 5 different queries with retry delays for 429/500 errors.
    Returns an Instagram music track object or None.
    """
    import random as _rnd
    queries = _rnd.sample(_MUSIC_QUERIES, min(5, len(_MUSIC_QUERIES)))
    last_exc = None
    for attempt, query in enumerate(queries):
        try:
            # Brief delay between attempts to avoid rate limiting
            if attempt > 0:
                time.sleep(_rnd.uniform(3, 8))
            tracks = cl.search_music(query)
            if tracks:
                track = _rnd.choice(tracks[:5])
                log.info("Found trending track: '%s' (query='%s')",
                         getattr(track, "title", "unknown"), query)
                return track
        except Exception as exc:
            last_exc = exc
            err_str = str(exc).lower()
            if "429" in err_str or "500" in err_str or "too many" in err_str:
                # Rate limited or server error — wait longer before retry
                wait = _rnd.uniform(10, 20)
                log.debug("Music search rate limited (query='%s'), waiting %.0fs: %s",
                          query, wait, exc)
                time.sleep(wait)
            else:
                log.debug("Music search '%s' failed: %s", query, exc)
    log.warning("No trending tracks found after %d queries (last error: %s)",
                len(queries), last_exc)
    return None


def publish(cfg: Config, caption: str, image_url: str,
            video_url: str | None = None, is_reel: bool = False,
            carousel_images: list[str] | None = None,
            post_type: str = "reel",
            alt_text: str | None = None,
            first_comment: str | None = None) -> str:
    """Publish to Instagram.

    - carousel: album of 2-10 images via album_upload
    - reel: short video upload (with music)
    - single/photo: standard photo upload

    Falls back to photo if Reel upload fails.
    Retries once with a fresh login if login_required is detected.
    Posts first_comment (extra hashtags) right after publishing.
    """
    try:
        cl = _get_client(cfg)
        post_id = _do_upload(cl, caption, image_url, video_url, is_reel,
                             carousel_images=carousel_images, post_type=post_type,
                             alt_text=alt_text)
    except Exception as exc:
        if not _is_login_required_error(exc):
            raise
        # Session was accepted by login but rejected by upload endpoints.
        # Delete session and retry with a completely fresh login.
        log.warning("Upload got login_required, forcing fresh login and retrying")
        _delete_session()
        cl = _get_client(cfg)
        post_id = _do_upload(cl, caption, image_url, video_url, is_reel,
                             carousel_images=carousel_images, post_type=post_type,
                             alt_text=alt_text)

    # Post first comment with extra hashtags for discovery
    if first_comment and first_comment.strip() and post_id and post_id != "unknown":
        try:
            import time as _time
            _time.sleep(3)  # brief delay before commenting
            cl = _get_client(cfg)
            cl.media_comment(post_id, first_comment.strip())
            log.info("Posted first comment (hashtags) on %s", post_id)
        except Exception as exc:
            log.warning("Failed to post first comment: %s", exc)

    return post_id


def _do_upload(cl: Client, caption: str, image_url: str,
               video_url: str | None, is_reel: bool,
               carousel_images: list[str] | None = None,
               post_type: str = "reel",
               alt_text: str | None = None) -> str:
    # Carousel upload — multiple images as an album
    if post_type == "carousel" and carousel_images:
        valid_paths = [Path(p) for p in carousel_images if os.path.exists(p)]
        if not valid_paths:
            raise RuntimeError(f"No carousel image files found: {carousel_images}")
        try:
            media = cl.album_upload(valid_paths, caption)
            log.info(
                "Published carousel (%d slides): https://www.instagram.com/p/%s/",
                len(valid_paths), media.code,
            )
            return str(media.pk)
        except ValidationError as exc:
            # Uploaded but response parsing failed — carousel is live
            log.warning("Carousel uploaded but response parsing failed: %s", exc)
            return "unknown"
        except Exception as exc:
            if _is_login_required_error(exc):
                raise
            log.warning("Carousel upload failed, falling back to single photo: %s", exc)
            # Fall through to photo upload using first image
            image_url = str(valid_paths[0])

    # Try Reel upload if we have a video
    if is_reel and video_url:
        local_video, is_temp_video = _resolve_media(video_url)
        try:
            # Use original image as thumbnail
            thumbnail = None
            is_temp_thumb = False
            if image_url:
                try:
                    thumbnail, is_temp_thumb = _resolve_media(image_url)
                except Exception:
                    pass

            # Extra data: hide like counts
            extra = {"like_and_view_counts_disabled": "1"}

            # Try uploading with trending music first (boosts reach)
            track = _find_trending_track(cl)
            if track:
                for music_attempt in range(2):
                    try:
                        if music_attempt > 0:
                            log.info("Retrying music upload after delay...")
                            time.sleep(15)
                            # Try a different track on retry
                            retry_track = _find_trending_track(cl)
                            if retry_track:
                                track = retry_track
                        media = cl.clip_upload_as_reel_with_music(
                            Path(local_video),
                            caption,
                            track,
                            extra_data=extra,
                        )
                        log.info("Published Reel with music: https://www.instagram.com/reel/%s/", media.code)
                        return str(media.pk)
                    except Exception as exc:
                        err_str = str(exc).lower()
                        if music_attempt == 0 and ("500" in err_str or "too many" in err_str):
                            log.warning("Music upload got server error, will retry: %s", exc)
                            continue
                        log.warning("Music reel upload failed, trying without music: %s", exc)
                        break

            # Fallback: upload without music
            media = cl.clip_upload(
                Path(local_video),
                caption,
                thumbnail=Path(thumbnail) if thumbnail else None,
                extra_data=extra,
            )
            log.info("Published Reel: https://www.instagram.com/reel/%s/", media.code)
            return str(media.pk)
        except ValidationError as exc:
            # Reel was uploaded successfully but instagrapi failed to parse
            # the response (e.g. audio_filter_infos=None instead of list).
            # Do NOT fall back to photo — the Reel is already live.
            log.warning("Reel uploaded but response parsing failed: %s", exc)
            return "unknown"
        except Exception as exc:
            if _is_login_required_error(exc):
                raise  # let the caller handle login_required
            log.warning("Reel upload failed, falling back to photo: %s", exc)
        finally:
            if is_temp_video:
                _safe_remove(local_video)
            if thumbnail and is_temp_thumb:
                _safe_remove(thumbnail)

    # Fallback: photo upload
    if not image_url:
        raise RuntimeError("No media to publish (no image_url)")

    local_path, is_temp = _resolve_media(image_url)
    try:
        extra = {}
        if alt_text:
            extra["custom_accessibility_caption"] = alt_text
        media = cl.photo_upload(Path(local_path), caption, extra_data=extra)
        log.info("Published photo: https://www.instagram.com/p/%s/", media.code)
        return str(media.pk)
    finally:
        if is_temp:
            _safe_remove(local_path)
