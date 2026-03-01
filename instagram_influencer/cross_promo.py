#!/usr/bin/env python3
"""Cross-promotion between main accounts — subtle mutual engagement.

When two main accounts (e.g., Maya + Aryan) are configured as partners,
this module handles:
  1. Engaging with partner's recent posts (like, comment)
  2. Viewing partner's stories
  3. Adding partner mentions to captions (called from orchestrator)

This is designed to be SUBTLE — max 2 comments/day on partner,
natural-looking engagement, not overtly connected.
"""

from __future__ import annotations

import logging
import random
from typing import Any

from config import Config
from persona import get_persona, load_persona
from rate_limiter import (
    can_act, load_log, random_delay, record_action, save_log, LOG_FILE,
)

log = logging.getLogger(__name__)


def _generate_partner_comment(cfg: Config, caption: str, partner_name: str) -> str:
    """Generate a genuine comment on partner's post in current persona's voice."""
    persona = get_persona()
    identity = persona["voice"]["gemini_identity"]
    tone = persona["voice"]["tone"]

    prompt = (
        f"You are {identity}. Your vibe: {tone}.\n"
        f"Write a SHORT genuine comment (1 sentence, max 15 words) on this post by {partner_name}.\n"
        f"Post caption: {caption[:200]}\n\n"
        "Rules:\n"
        "- Sound like a real friend/acquaintance commenting, not a fan\n"
        "- Be specific to the content\n"
        "- No hashtags, max 1 emoji\n"
        "- No generic phrases like 'great post' or 'love this'\n"
        "- You can be playful, competitive, or supportive\n\n"
        "Return ONLY the comment text."
    )

    try:
        from gemini_helper import generate as ask_gemini
        result = ask_gemini(cfg.gemini_api_key, prompt, cfg.gemini_model)
        if result:
            return result.strip().strip('"')
    except Exception as exc:
        log.warning("Partner comment gen failed: %s", exc)
        fallbacks = [
            "Okay this is fire ngl",
            "The energy in this one though",
            "You're not letting anyone breathe with these posts",
            "Saving this immediately",
        ]
        return random.choice(fallbacks)


def run_cross_promo_engagement(cl, cfg: Config, data: dict[str, Any]) -> dict[str, int]:
    """Engage with partner account's recent posts.

    Max 2 comments/day on partner to stay subtle.
    Like their recent posts, view their stories.
    """
    persona = get_persona()
    cross_promo = persona.get("cross_promo", {})
    partner_id = cross_promo.get("partner")

    if not partner_id:
        log.info("No cross-promo partner configured")
        return {}

    try:
        partner_persona = load_persona(partner_id)
    except FileNotFoundError:
        log.warning("Partner persona not found: %s", partner_id)
        return {}

    partner_handle = partner_persona.get("instagram_handle", "")
    partner_name = partner_persona.get("name", partner_id)

    if not partner_handle:
        log.warning("No instagram_handle for partner %s", partner_id)
        return {}

    log.info("Cross-promo engagement with @%s (%s)", partner_handle, partner_name)
    stats = {"likes": 0, "comments": 0, "story_views": 0}

    try:
        user_info = cl.user_info_by_username_v1(partner_handle)
        user_id = str(user_info.pk)
    except Exception as exc:
        log.warning("Cannot find partner @%s: %s", partner_handle, exc)
        return stats

    # Like their last 3 posts
    try:
        medias = cl.user_medias_v1(int(user_id), amount=3)
    except Exception:
        medias = []

    for media in medias:
        media_id = str(media.pk)
        if can_act(data, "likes"):
            try:
                cl.media_like(media_id)
                record_action(data, "likes", media_id)
                stats["likes"] += 1
            except Exception:
                pass
            random_delay(15, 40)

    # Comment on latest (max 2 partner comments/day)
    partner_comments_today = sum(
        1 for a in data.get("actions", [])
        if a.get("type") == "partner_comments"
        and str(a.get("at", "")).startswith(
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
        )
    )

    if medias and partner_comments_today < 2:
        latest = medias[0]
        caption = str(getattr(latest, "caption_text", "") or "")
        comment = _generate_partner_comment(cfg, caption, partner_name)
        try:
            cl.media_comment(str(latest.pk), comment)
            record_action(data, "partner_comments", str(latest.pk))
            stats["comments"] += 1
            log.info("Cross-promo comment on @%s: %s", partner_handle, comment[:50])
        except Exception as exc:
            log.warning("Cross-promo comment failed: %s", exc)
        random_delay(20, 60)

    # View partner's stories
    try:
        stories = cl.user_stories(int(user_id))
        for story in stories[:3]:
            try:
                cl.story_seen([story.pk])
                stats["story_views"] += 1
            except Exception:
                pass
            random_delay(5, 15)
    except Exception:
        pass

    return stats


def maybe_add_partner_mention(caption: str) -> str:
    """Randomly append a subtle partner mention to a caption.

    Called from orchestrator._build_hashtags() at publish time.
    Returns the caption with or without the mention.
    """
    persona = get_persona()
    cross_promo = persona.get("cross_promo", {})
    partner_id = cross_promo.get("partner")
    probability = cross_promo.get("partner_mention_probability", 0.12)
    templates = cross_promo.get("partner_mention_templates", [])

    if not partner_id or not templates or random.random() > probability:
        return caption

    try:
        partner_persona = load_persona(partner_id)
        partner_handle = partner_persona.get("instagram_handle", "")
        if not partner_handle:
            return caption

        mention = random.choice(templates).replace("{partner_handle}", partner_handle)
        return f"{caption}\n.\n{mention}"
    except Exception:
        return caption
