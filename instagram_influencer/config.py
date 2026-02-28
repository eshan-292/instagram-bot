#!/usr/bin/env python3
"""Configuration — loads .env and exposes a simple Config object."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_QUEUE_FILE = BASE_DIR / "content_queue.json"
SESSION_FILE = BASE_DIR / ".ig_session.json"
REFERENCE_DIR = BASE_DIR / "reference" / "maya"
GENERATED_IMAGES_DIR = BASE_DIR / "generated_images"


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
# Maya's character prompt (text-to-image fallback — matches her actual look)
# ---------------------------------------------------------------------------

DEFAULT_IMAGE_STYLE_PROMPT = (
    "Real Instagram photo of a young Indian woman, 23 years old. "
    "FACE: fair light-olive Indian complexion, soft oval face shape, "
    "large doe-like dark brown eyes with natural brows, small slightly rounded nose, "
    "medium-full natural pink lips, gentle soft features, no sharp angles. "
    "HAIR: very long voluminous dark brown-black wavy curly hair past shoulders, "
    "center-parted, thick and flowing. "
    "BUILD: slim petite figure. "
    "EXPRESSION: soft approachable confidence, warm subtle smile, natural look. "
    "MAKEUP: minimal natural makeup, bare skin visible, no heavy contouring. "
    "STYLE: casual chic Indian girl-next-door with quiet confidence. "
    "Shot on iPhone 15 Pro, natural ambient lighting, slight background bokeh, "
    "visible skin texture, natural pores, no airbrushing, 4:5 portrait ratio."
)

DEFAULT_NEGATIVE_PROMPT = (
    "blurry, low quality, distorted face, extra fingers, extra limbs, "
    "disfigured, deformed, ugly, text on image, watermark, logo, signature, "
    "cartoon, anime, illustration, painting, drawing, 3d render, cgi, "
    "overexposed, underexposed, grainy, noisy, cropped head, bad anatomy, "
    "bad hands, bad proportions, duplicate, out of frame, dark skin, "
    "sharp jawline, heavy makeup, fierce expression"
)


@dataclass(frozen=True)
class Config:
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

    status = _str(os.getenv("AUTO_PROMOTE_STATUS"), "approved").lower()
    if status not in {"ready", "approved"}:
        raise ValueError("AUTO_PROMOTE_STATUS must be 'ready' or 'approved'")

    return Config(
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
        image_style_prompt=_str(os.getenv("IMAGE_STYLE_PROMPT"), DEFAULT_IMAGE_STYLE_PROMPT),
        image_negative_prompt=_str(os.getenv("IMAGE_NEGATIVE_PROMPT"), DEFAULT_NEGATIVE_PROMPT),
        image_steps=_int(os.getenv("IMAGE_STEPS"), 4, minimum=1),
        auto_mode=_bool(os.getenv("AUTO_MODE")),
        auto_promote_drafts=_bool(os.getenv("AUTO_PROMOTE_DRAFTS")),
        auto_promote_status=status,
        schedule_interval_minutes=_int(os.getenv("AUTO_SCHEDULE_INTERVAL_MINUTES"), 240, minimum=1),
        schedule_lead_minutes=_int(os.getenv("AUTO_SCHEDULE_LEAD_MINUTES"), 30, minimum=0),
        # Engagement
        engagement_enabled=_bool(os.getenv("ENGAGEMENT_ENABLED")),
        engagement_hashtags=_str(os.getenv("ENGAGEMENT_HASHTAGS"),
            "indianfashion,mumbaifashion,desistyle,indianfashionblogger,mumbailifestyle,"
            "indianstreetstyle,ethnicwear,indiangirlstyle,browngirlmagic,southasianfashion,"
            "mumbailifestyle,desifashion,indianootd,bollywoodfashion,fashionbloggerindia"),
        engagement_daily_likes=_int(os.getenv("ENGAGEMENT_DAILY_LIKES"), 250, minimum=0),
        engagement_daily_comments=_int(os.getenv("ENGAGEMENT_DAILY_COMMENTS"), 60, minimum=0),
        engagement_daily_follows=_int(os.getenv("ENGAGEMENT_DAILY_FOLLOWS"), 80, minimum=0),
        engagement_comment_enabled=_bool(os.getenv("ENGAGEMENT_COMMENT_ENABLED")),
        engagement_follow_enabled=_bool(os.getenv("ENGAGEMENT_FOLLOW_ENABLED")),
        # YouTube
        youtube_enabled=_bool(os.getenv("YOUTUBE_ENABLED")),
        youtube_client_id=_str(os.getenv("YOUTUBE_CLIENT_ID")),
        youtube_client_secret=_str(os.getenv("YOUTUBE_CLIENT_SECRET")),
        youtube_refresh_token=_str(os.getenv("YOUTUBE_REFRESH_TOKEN")),
        youtube_engagement_enabled=_bool(os.getenv("YOUTUBE_ENGAGEMENT_ENABLED")),
    )
