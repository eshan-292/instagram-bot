#!/usr/bin/env python3
"""Publish YouTube Shorts via YouTube Data API v3.

Authentication uses OAuth2 with a stored refresh token (no interactive flow needed).
The user does a one-time auth locally, then stores the refresh token as a secret.

Setup:
  1. Create a Google Cloud project → enable YouTube Data API v3
  2. Create OAuth2 credentials (Desktop app type)
  3. Run `python youtube_publisher.py --auth` locally to get a refresh token
  4. Store YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN as secrets
"""

from __future__ import annotations

import json
import logging
import os
import random
from pathlib import Path
from typing import Any

from persona import get_persona

log = logging.getLogger(__name__)

# Category IDs: 22=People & Blogs, 26=Howto & Style, 24=Entertainment
_CATEGORY_ID = "26"  # Howto & Style — best for fashion content

# Hashtag pool for YouTube Shorts descriptions
def _yt_hashtag_pool():
    return get_persona().get("youtube", {}).get("hashtag_pool", ["Shorts"])

# YouTube-optimized keyword phrases
def _yt_keywords():
    return get_persona().get("youtube", {}).get("keywords", [])


def _build_credentials():
    """Build OAuth2 credentials from environment variables."""
    from google.oauth2.credentials import Credentials

    client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()

    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError(
            "YouTube credentials not configured. Set YOUTUBE_CLIENT_ID, "
            "YOUTUBE_CLIENT_SECRET, and YOUTUBE_REFRESH_TOKEN."
        )

    return Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube",
                "https://www.googleapis.com/auth/youtube.force-ssl"],
    )


def _get_youtube_service():
    """Build authenticated YouTube API service."""
    from googleapiclient.discovery import build

    creds = _build_credentials()
    return build("youtube", "v3", credentials=creds)


def _build_title(topic: str, caption: str) -> str:
    """Build a YouTube Shorts title from the post topic/caption.

    Rules:
      - Under 100 characters
      - Front-loaded keywords
      - Ends with #Shorts
    """
    # Use topic as base (more keyword-rich than caption)
    title = topic.strip()
    if not title:
        # Extract first line from caption
        title = caption.strip().split("\n")[0]

    # Clean up and truncate
    title = title.replace("#", "").strip()

    # Ensure #Shorts fits (max 100 chars total)
    max_len = 100 - len(" #Shorts") - 1
    if len(title) > max_len:
        title = title[:max_len].rsplit(" ", 1)[0]

    return f"{title} #Shorts"


def _build_description(caption: str, topic: str) -> str:
    """Build a YouTube Shorts description optimized for SEO.

    Structure:
      - Caption text (cleaned of Instagram-specific CTAs)
      - Keywords line
      - Hashtags (YouTube uses these for discovery)
    """
    # Clean caption: remove Instagram-specific elements
    desc_lines = []
    for line in caption.split("\n"):
        stripped = line.strip()
        # Skip hashtag blocks and dot separators
        if stripped.startswith("#") and " " not in stripped:
            continue
        if stripped == ".":
            continue
        desc_lines.append(line)

    desc = "\n".join(desc_lines).strip()

    # Add YouTube-specific elements
    yt_kw = _yt_keywords()
    keywords = random.sample(yt_kw, min(2, len(yt_kw)))
    persona = get_persona()
    pool = _yt_hashtag_pool()
    tags = [persona.get("brand_tag", "")] + random.sample(pool, min(4, len(pool)))
    hashtag_line = " ".join(f"#{t}" for t in tags)

    return f"{desc}\n\n{' | '.join(keywords)}\n\n{hashtag_line}"


def _build_tags(topic: str) -> list[str]:
    """Build YouTube video tags for SEO."""
    persona = get_persona()
    base_tags = persona.get("youtube", {}).get("tags_base", ["Shorts"])

    # Add topic-specific tags
    topic_words = [w.strip().title() for w in topic.split() if len(w) > 3][:5]
    all_tags = base_tags + topic_words

    # YouTube allows up to 500 chars of tags
    return all_tags[:15]


def publish_short(
    video_path: str,
    topic: str,
    caption: str,
    thumbnail_path: str | None = None,
    custom_title: str | None = None,
) -> str | None:
    """Upload a video as a YouTube Short.

    Args:
        custom_title: Gemini-generated SEO title. Falls back to _build_title() if empty.

    Returns the YouTube video ID on success, None on failure.
    """
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError

    if not os.path.exists(video_path):
        log.error("Video file not found: %s", video_path)
        return None

    try:
        youtube = _get_youtube_service()
    except Exception as exc:
        log.warning("YouTube auth failed (skipping upload): %s", exc)
        return None

    # Use Gemini-generated title if available, otherwise build from topic
    if custom_title:
        # Ensure #Shorts is appended and title fits under 100 chars
        if "#Shorts" not in custom_title:
            max_len = 100 - len(" #Shorts") - 1
            title = custom_title[:max_len].strip() + " #Shorts"
        else:
            title = custom_title[:100]
    else:
        title = _build_title(topic, caption)
    description = _build_description(caption, topic)
    tags = _build_tags(topic)

    body: dict[str, Any] = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": _CATEGORY_ID,
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
        },
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10MB chunks
    )

    try:
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.debug("YouTube upload %d%% complete", int(status.progress() * 100))

        video_id = response.get("id", "")
        log.info(
            "Published YouTube Short: https://youtube.com/shorts/%s (title: %s)",
            video_id, title,
        )

        # Set thumbnail if available
        if thumbnail_path and os.path.exists(thumbnail_path):
            _set_thumbnail(youtube, video_id, thumbnail_path)

        return video_id

    except HttpError as exc:
        error_detail = ""
        if exc.resp and exc.content:
            try:
                err = json.loads(exc.content)
                error_detail = err.get("error", {}).get("message", "")
            except Exception:
                pass
        log.error("YouTube upload failed: %s %s", exc, error_detail)
        return None
    except Exception as exc:
        log.error("YouTube upload error: %s", exc)
        return None


def _set_thumbnail(youtube, video_id: str, thumbnail_path: str) -> None:
    """Set a custom thumbnail for a YouTube video."""
    from googleapiclient.http import MediaFileUpload

    try:
        media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=media,
        ).execute()
        log.debug("Set thumbnail for %s", video_id)
    except Exception as exc:
        log.debug("Thumbnail upload failed (non-fatal): %s", exc)


def get_channel_stats() -> dict[str, Any] | None:
    """Fetch basic channel statistics (subscribers, views, video count)."""
    try:
        youtube = _get_youtube_service()
        response = youtube.channels().list(
            part="statistics,snippet",
            mine=True,
        ).execute()

        items = response.get("items", [])
        if not items:
            return None

        stats = items[0].get("statistics", {})
        snippet = items[0].get("snippet", {})
        return {
            "channel_title": snippet.get("title", ""),
            "subscribers": int(stats.get("subscriberCount", 0)),
            "total_views": int(stats.get("viewCount", 0)),
            "video_count": int(stats.get("videoCount", 0)),
        }
    except Exception as exc:
        log.debug("Could not fetch channel stats: %s", exc)
        return None


def get_recent_videos(max_results: int = 10) -> list[dict[str, Any]]:
    """List recent uploaded videos for engagement (reply to comments)."""
    try:
        youtube = _get_youtube_service()

        # Get uploads playlist
        channels = youtube.channels().list(
            part="contentDetails",
            mine=True,
        ).execute()

        items = channels.get("items", [])
        if not items:
            return []

        uploads_id = (
            items[0]
            .get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads", "")
        )
        if not uploads_id:
            return []

        # List recent videos
        playlist = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_id,
            maxResults=max_results,
        ).execute()

        videos = []
        for item in playlist.get("items", []):
            snippet = item.get("snippet", {})
            videos.append({
                "video_id": snippet.get("resourceId", {}).get("videoId", ""),
                "title": snippet.get("title", ""),
                "published_at": snippet.get("publishedAt", ""),
            })

        return videos
    except Exception as exc:
        log.debug("Could not fetch recent videos: %s", exc)
        return []


# ---------------------------------------------------------------------------
# One-time auth flow (run locally: python youtube_publisher.py --auth)
# ---------------------------------------------------------------------------

def _interactive_auth() -> None:
    """Run the interactive OAuth2 flow to obtain a refresh token.

    Usage: python youtube_publisher.py --auth
    Requires YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        print("ERROR: Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env first")
        return

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(
        client_config,
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube",
            "https://www.googleapis.com/auth/youtube.force-ssl",
        ],
    )

    credentials = flow.run_local_server(port=8080, prompt="consent")

    print("\n=== YouTube Auth Complete ===")
    print(f"Refresh Token: {credentials.refresh_token}")
    print("\nAdd this to your .env / GitHub secrets as YOUTUBE_REFRESH_TOKEN")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--auth", action="store_true", help="Run interactive OAuth2 flow")
    args = parser.parse_args()

    if args.auth:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        _interactive_auth()
    else:
        print("Usage: python youtube_publisher.py --auth")
