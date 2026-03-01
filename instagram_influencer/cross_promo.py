#!/usr/bin/env python3
"""Cross-promotion between main accounts — aggressive mutual engagement.

When two main accounts (e.g., Maya + Aryan) are configured as partners,
this module handles:
  1. Like + save partner's recent posts
  2. Comment on partner's posts (up to 4/day)
  3. Like comments on partner's posts
  4. Reply to comments on partner's posts
  5. View + like partner's stories
  6. Repost partner's latest post to own story
  7. Share partner's post via DM
  8. Add partner mentions to captions (called from orchestrator)
"""

from __future__ import annotations

import logging
import random
import tempfile
from datetime import datetime, timezone
from pathlib import Path
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


def _generate_reply(cfg: Config, comment_text: str, partner_name: str) -> str:
    """Generate a reply to a comment on partner's post."""
    persona = get_persona()
    tone = persona["voice"]["tone"]

    prompt = (
        f"You are a creator ({tone}). Write a SHORT reply (max 10 words) to this comment "
        f"on {partner_name}'s post:\n"
        f'Comment: "{comment_text[:150]}"\n\n'
        "Sound like a real creator casually replying. Max 1 emoji.\n"
        "Return ONLY the reply text."
    )

    try:
        from gemini_helper import generate as ask_gemini
        result = ask_gemini(cfg.gemini_api_key, prompt, cfg.gemini_model)
        if result:
            return result.strip().strip('"')
    except Exception as exc:
        log.warning("Reply gen failed: %s", exc)
    return random.choice(["So true 💯", "Exactly this", "Couldn't agree more", "This right here"])


def run_cross_promo_engagement(cl, cfg: Config, data: dict[str, Any]) -> dict[str, int]:
    """Engage with partner account's recent posts — aggressive cross-promotion.

    Like, save, comment, like comments, reply, view + like stories,
    repost to story, share via DM.
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
    stats = {
        "likes": 0, "comments": 0, "saves": 0, "story_views": 0,
        "comment_likes": 0, "story_likes": 0, "story_reposts": 0,
        "dm_shares": 0, "replies": 0,
    }

    try:
        user_info = cl.user_info_by_username_v1(partner_handle)
        user_id = str(user_info.pk)
    except Exception as exc:
        log.warning("Cannot find partner @%s: %s", partner_handle, exc)
        return stats

    # ── Fetch recent posts ──
    try:
        medias = cl.user_medias_v1(int(user_id), amount=3)
    except Exception:
        medias = []

    # ── Like + Save each post ──
    for media in medias:
        media_id = str(media.pk)

        if can_act(data, "likes"):
            try:
                cl.media_like(media_id)
                record_action(data, "likes", media_id)
                stats["likes"] += 1
            except Exception:
                pass
            random_delay(10, 30)

        # Save partner's posts (strong algorithm signal)
        if can_act(data, "saves"):
            try:
                cl.media_save(media_id)
                record_action(data, "saves", media_id)
                stats["saves"] += 1
                log.debug("Saved %s by @%s", media_id, partner_handle)
            except Exception:
                pass
            random_delay(8, 20)

        # ── Like comments on partner's posts ──
        try:
            comments = cl.media_comments(media_id, amount=5)
            for comment in comments[:3]:
                try:
                    cl.comment_like(comment.pk)
                    record_action(data, "comment_likes", str(comment.pk))
                    stats["comment_likes"] += 1
                except Exception:
                    pass
                random_delay(3, 10)
        except Exception:
            pass

    # ── Comment on latest (max 4 partner comments/day) ──
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    partner_comments_today = sum(
        1 for a in data.get("actions", [])
        if a.get("type") == "partner_comments"
        and str(a.get("at", "")).startswith(today)
    )

    if medias and partner_comments_today < 4:
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
        random_delay(15, 40)

    # ── Reply to a comment on partner's latest post ──
    if medias and partner_comments_today < 4:
        latest = medias[0]
        try:
            comments = cl.media_comments(str(latest.pk), amount=8)
            own_handle = persona.get("instagram_handle", "")
            eligible = [
                c for c in comments
                if hasattr(c, 'user') and getattr(c.user, 'username', '') != own_handle
                and hasattr(c, 'text') and c.text
            ]
            if eligible:
                target_comment = random.choice(eligible[:5])
                reply_text = _generate_reply(cfg, target_comment.text, partner_name)
                try:
                    cl.media_comment(
                        str(latest.pk), reply_text,
                        replied_to_comment_id=target_comment.pk,
                    )
                    record_action(data, "partner_comments", f"reply_{target_comment.pk}")
                    stats["replies"] += 1
                    log.info("Replied to comment on @%s: %s", partner_handle, reply_text[:50])
                except Exception as exc:
                    log.warning("Cross-promo reply failed: %s", exc)
                random_delay(15, 40)
        except Exception:
            pass

    # ── View + Like partner's stories ──
    try:
        stories = cl.user_stories(int(user_id))
        for story in stories[:5]:
            try:
                cl.story_seen([story.pk])
                stats["story_views"] += 1
            except Exception:
                pass
            random_delay(3, 10)

            # Like the story
            try:
                cl.story_like(story.pk)
                stats["story_likes"] += 1
                log.debug("Liked story by @%s", partner_handle)
            except Exception:
                pass
            random_delay(3, 8)
    except Exception:
        pass

    # ── Repost partner's latest to own story (1/day) ──
    story_reposts_today = sum(
        1 for a in data.get("actions", [])
        if a.get("type") == "xp_story_repost"
        and str(a.get("at", "")).startswith(today)
    )
    if medias and story_reposts_today < 1:
        latest = medias[0]
        try:
            media_info = cl.media_info(latest.pk)
            thumb_url = str(media_info.thumbnail_url or "")
            if thumb_url:
                import urllib.request
                tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                urllib.request.urlretrieve(thumb_url, tmp.name)
                cl.photo_upload_to_story(tmp.name)
                record_action(data, "xp_story_repost", str(latest.pk))
                stats["story_reposts"] += 1
                log.info("Reposted @%s's post to story", partner_handle)
                Path(tmp.name).unlink(missing_ok=True)
        except Exception as exc:
            log.debug("Story repost of @%s failed: %s", partner_handle, exc)
        random_delay(10, 30)

    # ── Share partner's post via DM (1/day) ──
    dm_shares_today = sum(
        1 for a in data.get("actions", [])
        if a.get("type") == "xp_dm_share"
        and str(a.get("at", "")).startswith(today)
    )
    if medias and dm_shares_today < 1:
        latest = medias[0]
        media_code = getattr(latest, 'code', '')
        if media_code:
            post_url = f"https://www.instagram.com/p/{media_code}/"
            try:
                cl.direct_send(post_url, user_ids=[int(user_id)])
                record_action(data, "xp_dm_share", str(latest.pk))
                stats["dm_shares"] += 1
                log.info("Shared @%s's post via DM", partner_handle)
            except Exception as exc:
                log.debug("DM share to @%s failed: %s", partner_handle, exc)
            random_delay(10, 25)

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
