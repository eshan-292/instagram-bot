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
from instagrapi.exceptions import (
    ChallengeRequired,
    ClientForbiddenError,
    LoginRequired,
)
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


class ChallengeAbort(RuntimeError):
    """Raised when Instagram requires a challenge (phone/email verification).

    This is a fatal error — the bot MUST stop all API calls immediately.
    Continuing to hit the API in a challenge state will escalate to a full
    account block.
    """
    pass


def _is_challenge_error(exc: Exception) -> bool:
    """Check if an exception is a challenge/checkpoint error."""
    exc_type = type(exc).__name__
    if exc_type in ("ChallengeRequired", "ChallengeUnknownStep", "ChallengeError"):
        return True
    msg = str(exc).lower()
    return ("challenge_required" in msg or "checkpoint_challenge" in msg
            or "submit_phone" in msg or "challenge" in msg and "resolver" in msg)


def _session_health_check(cl: Client) -> bool:
    """Quick API call to verify the session works for media endpoints.

    A stale/web-origin session can succeed at login but 403 on media
    endpoints.  We catch this early and force a fresh login.

    Raises ChallengeAbort if Instagram demands verification — this is
    FATAL and the bot must stop immediately to avoid account blocks.
    """
    try:
        info = cl.account_info()
        if not info or not getattr(info, "pk", None):
            log.warning("Session health check: account_info returned empty")
            return False
        return True
    except ChallengeRequired as exc:
        log.error(
            "CHALLENGE DETECTED during health check — account needs manual "
            "verification. Aborting ALL API calls to prevent account block. "
            "Error: %s", exc
        )
        raise ChallengeAbort(
            "Instagram challenge required. Log into the Instagram app on your "
            "phone to complete verification, then re-seed the session."
        ) from exc
    except (ClientForbiddenError, LoginRequired) as exc:
        log.warning("Session health check failed (%s): %s", type(exc).__name__, exc)
        return False
    except Exception as exc:
        # Check if this is a challenge error disguised as a generic exception
        if _is_challenge_error(exc):
            log.error(
                "CHALLENGE DETECTED during health check — aborting. Error: %s", exc
            )
            raise ChallengeAbort(
                "Instagram challenge required. Complete verification on "
                "your phone, then re-seed the session."
            ) from exc
        # Check .code attribute (instagrapi sets this on ClientError subclasses)
        code = getattr(exc, "code", None)
        msg = str(exc).lower()
        if code == 403 or "403" in msg or "forbidden" in msg or "login_required" in msg:
            log.warning("Session health check failed (code=%s): %s", code, exc)
            return False
        # Other errors (network, timeout) aren't session issues
        log.debug("Health check non-fatal error: %s", exc)
        return True


def _get_client(cfg: Config) -> Client:
    """Login via saved session or username/password.

    Strategy (in order):
      1. Try silent restore (load_settings only, no login call)
         → fastest, no IP-change risk, works if cookies still valid
      2. If silent fails → try RELOGIN (load_settings + login)
         → uses same device UUIDs so Instagram sees "same device, new IP"
         → this is safe and refreshes the session cookies
      3. If relogin fails → fresh login (ONLY locally, never in CI)
         → creates new device UUIDs = "new device" = challenge risk

    KEY DISTINCTION:
    - Relogin (load_settings + login) = same device UUIDs → usually safe
    - Fresh login (new Client + login) = new device UUIDs → triggers blocks
    """
    session_path = str(SESSION_FILE)
    is_ci = bool(os.getenv("CI") or os.getenv("GITHUB_ACTIONS"))

    # ── 1. Try silent restore (no login() call) ──────────────────────
    if os.path.exists(session_path):
        try:
            cl = _new_client()
            cl.load_settings(session_path)
            cl.challenge_code_handler = _challenge_handler
            log.debug("Restored saved session (silent)")

            if _session_health_check(cl):
                cl.dump_settings(session_path)
                return cl

            log.warning("Silent session restore failed health check — will try relogin")
        except ChallengeAbort:
            raise
        except Exception as exc:
            if _is_challenge_error(exc):
                raise ChallengeAbort(str(exc)) from exc
            log.warning("Silent restore error: %s — will try relogin", exc)

    # ── 2. Relogin with saved session (same device UUIDs) ────────────
    #    This refreshes cookies while keeping the device fingerprint,
    #    so Instagram sees "same device, different IP" = usually OK.
    if os.path.exists(session_path) and cfg.instagram_username and cfg.instagram_password:
        try:
            cl = _new_client()
            cl.load_settings(session_path)
            cl.challenge_code_handler = _challenge_handler
            log.info("Attempting relogin with saved device UUIDs")
            cl.login(cfg.instagram_username, cfg.instagram_password)
            log.info("Relogin successful")
            cl.dump_settings(session_path)
            return cl
        except ChallengeAbort:
            raise
        except (ChallengeRequired,) as exc:
            log.error("Challenge during relogin — account needs manual verification: %s", exc)
            raise ChallengeAbort(
                "Instagram challenge required during relogin. "
                "Complete verification on phone, then re-seed session."
            ) from exc
        except Exception as exc:
            if _is_challenge_error(exc):
                log.error("Challenge detected during relogin: %s", exc)
                raise ChallengeAbort(str(exc)) from exc
            log.warning("Relogin failed: %s", exc)
            if is_ci:
                raise RuntimeError(
                    "Session relogin failed in CI. "
                    "Run seed_session.py locally to create a fresh session."
                ) from exc
            _delete_session()

    # ── 3. Fresh login (ONLY for local dev — never in CI) ────────────
    #    Creates new device UUIDs → Instagram sees "new device" → blocks
    if is_ci:
        raise RuntimeError(
            "No valid session in CI. Fresh login from datacenter IPs "
            "triggers 'new device' blocks. Run seed_session.py locally."
        )

    if not cfg.instagram_username or not cfg.instagram_password:
        raise RuntimeError(
            "No valid session file and no credentials set. "
            "Run seed_session.py locally to create a session, "
            "or set INSTAGRAM_USERNAME + INSTAGRAM_PASSWORD in .env"
        )

    _delete_session()
    cl = _new_client()
    try:
        cl.login(cfg.instagram_username, cfg.instagram_password)
    except ChallengeRequired as exc:
        log.error(
            "Instagram challenge triggered during login — cannot complete in CI. "
            "Run seed_session.py locally to create a valid session."
        )
        raise RuntimeError(
            "ChallengeRequired: Instagram needs verification. "
            "Run `python seed_session.py` on your laptop to create a session."
        ) from exc
    log.info("Logged in via username/password (local dev)")

    # Validate fresh session
    if not _session_health_check(cl):
        log.error(
            "Fresh login gets 403 — account is likely ACTION-BLOCKED. "
            "Log in from the Instagram app to clear the block, "
            "then run seed_session.py to create a new session."
        )
        raise RuntimeError(
            "Account action-blocked: fresh login gets 403 on all endpoints."
        )

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
            if _is_challenge_error(exc):
                raise ChallengeAbort(str(exc)) from exc
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
    except ChallengeAbort:
        raise  # Don't retry on challenge — abort immediately
    except Exception as exc:
        if _is_challenge_error(exc):
            raise ChallengeAbort(str(exc)) from exc
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
    # Use post_type as primary reel indicator (is_reel is legacy boolean)
    want_reel = is_reel or post_type == "reel"

    if want_reel and video_url:
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
            # NEVER silently fall back to photo for reels — this causes
            # reels to publish as photos which kills reach.
            log.error("Reel upload FAILED (NOT falling back to photo): %s", exc)
            raise
        finally:
            if is_temp_video:
                _safe_remove(local_video)
            if thumbnail and is_temp_thumb:
                _safe_remove(thumbnail)

    # If this was supposed to be a reel but no video_url exists, error out
    # instead of silently publishing as a photo
    if want_reel and not video_url:
        log.error("Post is type=reel but has no video_url — cannot publish as reel. "
                   "Run the pipeline again to generate the video first.")
        raise RuntimeError("Reel post has no video_url — cannot publish as photo fallback")

    # Photo upload (only for post_type="single" or "photo")
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
