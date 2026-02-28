#!/usr/bin/env python3
"""Configuration — loads .env and exposes a simple Config object."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# These are now dynamically resolved via persona.persona_data_dir().
# Legacy constants point to maya's data dir for backward compatibility.
# Import persona lazily to avoid circular imports.
def _persona_data_dir():
    from persona import persona_data_dir
    return persona_data_dir()

def _persona_images_dir():
    from persona import persona_images_dir
    return persona_images_dir()

def _persona_reference_dir():
    from persona import persona_reference_dir
    return persona_reference_dir()

# Lazy properties — modules that import these at module level still work
class _LazyPath:
    """Defers path resolution until first access (avoids import-time persona load)."""
    def __init__(self, resolver):
        self._resolver = resolver
        self._path = None
    def __fspath__(self):
        if self._path is None: self._path = self._resolver()
        return str(self._path)
    def __str__(self):
        return self.__fspath__()
    def __truediv__(self, other):
        return Path(self.__fspath__()) / other
    def __repr__(self):
        return f"LazyPath({self.__fspath__()})"

DEFAULT_QUEUE_FILE = _LazyPath(lambda: _persona_data_dir() / "content_queue.json")
SESSION_FILE = _LazyPath(lambda: _persona_data_dir() / ".ig_session.json")
REFERENCE_DIR = _LazyPath(_persona_reference_dir)
GENERATED_IMAGES_DIR = _LazyPath(_persona_images_dir)


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _int(val: str | None, default: int, *, minimum: int | None = None) -> int:
    result = default if (val is None or not val.strip()) else int(val)
    return max(result, minimum) if minimum is not None else result


def _str(val: str | None, default: str = "") -> str:
    return default if val is None else (val.strip() or default)


# ---------------------------------------------------------------------------
# Image prompts — loaded from persona JSON (no more hardcoded character data)
# ---------------------------------------------------------------------------

def _persona_image_prompt():
    from persona import get_persona
    return get_persona().get("image_style_prompt", "")

def _persona_negative_prompt():
    from persona import get_persona
    return get_persona().get("image_negative_prompt", "")


@dataclass(frozen=True)
class Config:
    # Persona identifier
    persona_id: str

    # Instagram credentials
    instagram_username: str
    instagram_password: str
    instagram_session_id: str

    # Gemini (content generation)
    gemini_api_key: str
    gemini_model: str

    # Content queue
    draft_count: int
    min_ready_queue: int

    # Image generation — Replicate Kontext (primary) + BFL Kontext + HF Schnell (fallback)
    replicate_api_token: str
    bfl_api_key: str
    hf_token: str
    hf_image_model: str
    image_style_prompt: str
    image_negative_prompt: str
    image_steps: int

    # Automation
    auto_mode: bool
    auto_promote_drafts: bool
    auto_promote_status: str
    schedule_interval_minutes: int
    schedule_lead_minutes: int

    # Engagement automation
    engagement_enabled: bool
    engagement_hashtags: str
    engagement_daily_likes: int
    engagement_daily_comments: int
    engagement_daily_follows: int
    engagement_comment_enabled: bool
    engagement_follow_enabled: bool
    engagement_target_accounts: str  # comma-separated similar niche accounts for warm targeting

    # YouTube Shorts
    youtube_enabled: bool
    youtube_client_id: str
    youtube_client_secret: str
    youtube_refresh_token: str
    youtube_engagement_enabled: bool


def load_config() -> Config:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ModuleNotFoundError:
        pass

    # Load persona (initializes data dirs, provides defaults)
    from persona import get_persona
    persona = get_persona()

    status = _str(os.getenv("AUTO_PROMOTE_STATUS"), "approved").lower()
    if status not in {"ready", "approved"}:
        raise ValueError("AUTO_PROMOTE_STATUS must be 'ready' or 'approved'")

    # Persona-aware defaults for engagement
    eng = persona.get("engagement", {})
    default_hashtags = eng.get("default_hashtags", "")
    default_targets = eng.get("default_target_accounts", "")

    return Config(
        persona_id=persona["id"],
        instagram_username=_str(os.getenv("INSTAGRAM_USERNAME")),
        instagram_password=_str(os.getenv("INSTAGRAM_PASSWORD")),
        instagram_session_id=_str(os.getenv("INSTAGRAM_SESSION_ID")),
        gemini_api_key=_str(os.getenv("GEMINI_API_KEY")),
        gemini_model=_str(os.getenv("GEMINI_MODEL"), "gemini-2.5-flash"),
        draft_count=_int(os.getenv("DRAFT_COUNT"), 3, minimum=1),
        min_ready_queue=_int(os.getenv("MIN_READY_QUEUE"), 5, minimum=1),
        replicate_api_token=_str(os.getenv("REPLICATE_API_TOKEN")),
        bfl_api_key=_str(os.getenv("BFL_API_KEY")),
        hf_token=_str(os.getenv("HF_TOKEN")),
        hf_image_model=_str(os.getenv("HF_IMAGE_MODEL"), "black-forest-labs/FLUX.1-schnell"),
        image_style_prompt=_str(os.getenv("IMAGE_STYLE_PROMPT"), _persona_image_prompt()),
        image_negative_prompt=_str(os.getenv("IMAGE_NEGATIVE_PROMPT"), _persona_negative_prompt()),
        image_steps=_int(os.getenv("IMAGE_STEPS"), 4, minimum=1),
        auto_mode=_bool(os.getenv("AUTO_MODE")),
        auto_promote_drafts=_bool(os.getenv("AUTO_PROMOTE_DRAFTS")),
        auto_promote_status=status,
        schedule_interval_minutes=_int(os.getenv("AUTO_SCHEDULE_INTERVAL_MINUTES"), 240, minimum=1),
        schedule_lead_minutes=_int(os.getenv("AUTO_SCHEDULE_LEAD_MINUTES"), 30, minimum=0),
        # Engagement — defaults from persona JSON
        engagement_enabled=_bool(os.getenv("ENGAGEMENT_ENABLED")),
        engagement_hashtags=_str(os.getenv("ENGAGEMENT_HASHTAGS"), default_hashtags),
        engagement_daily_likes=_int(os.getenv("ENGAGEMENT_DAILY_LIKES"), 250, minimum=0),
        engagement_daily_comments=_int(os.getenv("ENGAGEMENT_DAILY_COMMENTS"), 60, minimum=0),
        engagement_daily_follows=_int(os.getenv("ENGAGEMENT_DAILY_FOLLOWS"), 80, minimum=0),
        engagement_comment_enabled=_bool(os.getenv("ENGAGEMENT_COMMENT_ENABLED")),
        engagement_follow_enabled=_bool(os.getenv("ENGAGEMENT_FOLLOW_ENABLED")),
        engagement_target_accounts=_str(os.getenv("ENGAGEMENT_TARGET_ACCOUNTS"), default_targets),
        # YouTube
        youtube_enabled=_bool(os.getenv("YOUTUBE_ENABLED")),
        youtube_client_id=_str(os.getenv("YOUTUBE_CLIENT_ID")),
        youtube_client_secret=_str(os.getenv("YOUTUBE_CLIENT_SECRET")),
        youtube_refresh_token=_str(os.getenv("YOUTUBE_REFRESH_TOKEN")),
        youtube_engagement_enabled=_bool(os.getenv("YOUTUBE_ENGAGEMENT_ENABLED")),
    )
