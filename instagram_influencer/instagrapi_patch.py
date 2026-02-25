#!/usr/bin/env python3
"""Monkey-patch instagrapi's Pydantic models to tolerate Instagram API changes.

Instagram frequently sends None for fields instagrapi expects as required,
or changes field types (dict where str expected, etc.). This module:
1. Makes ALL fields in known-broken models Optional[Any] with None defaults
2. Rebuilds the entire model dependency chain in correct order
3. Wraps extract_media_v1 with a ValidationError safety net

Import this module before using instagrapi's hashtag/media/upload methods.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

_PATCHED = False


def _make_fields_optional(model: Any) -> bool:
    """Make all fields on a Pydantic v2 model Optional[Any] with None default."""
    changed = False
    for name, field in model.model_fields.items():
        field.annotation = Optional[Any]
        if field.default is None and not field.is_required():
            continue
        field.default = None
        changed = True
    return changed


def _patch_models() -> None:
    """Patch all known-broken Pydantic models."""
    try:
        from instagrapi import types as t
    except ImportError:
        return

    # Every model that Instagram's API can break with unexpected None/dict/missing
    models_to_patch = [
        # Clips models (Instagram changes these constantly)
        "ClipsAchievementsInfo",
        "ClipsAdditionalAudioInfo",
        "ClipsAudioRankingInfo",
        "ClipsBrandedContentTagInfo",
        "ClipsContentAppreciationInfo",
        "ClipsMashupInfo",
        "ClipsConsumptionInfo",
        "ClipsFbDownstreamUseXpostMetadata",
        "ClipsIgArtist",
        "ClipsOriginalSoundInfo",
        "ClipsMetadata",
        # Image/video candidates (scans_profile, url, etc. often None)
        "SharedMediaImageCandidate",
        "DirectMessageImageCandidate",
        "VideoVersion",
        # Container models (their child types changed, so they need patching too)
        "ScrubberSpritesheetInfo",
        "ScrubberSpritesheetInfoCandidates",
        "AdditionalCandidates",
        "SharedMediaImageVersions",
        "DirectMessageImageVersions",
        "FallbackUrl",
    ]

    patched = []
    for name in models_to_patch:
        model = getattr(t, name, None)
        if model and hasattr(model, "model_fields"):
            if _make_fields_optional(model):
                patched.append(name)
            try:
                model.model_rebuild(force=True)
            except Exception:
                pass

    # Rebuild top-level models that reference the patched ones
    # These may not need field patches themselves, but their cached schemas
    # still reference the OLD child model schemas
    top_models = [
        "Media", "MediaXma", "Comment", "Track",
        "Story", "DirectMessage", "VisualMedia",
        "Resource",
    ]
    for name in top_models:
        model = getattr(t, name, None)
        if model and hasattr(model, "model_rebuild"):
            try:
                model.model_rebuild(force=True)
            except Exception:
                pass

    if patched:
        log.debug("Patched instagrapi models: %s", ", ".join(patched))


def _patch_extract_media_v1() -> None:
    """Wrap extract_media_v1 to catch ValidationError per-item.

    When Media(**data) fails validation (Instagram changed their schema again),
    fall back to model_construct() which skips validation entirely. This gives
    us a Media object with at minimum .pk, .user, .caption_text — enough for
    engagement actions (like, comment, follow).
    """
    try:
        from instagrapi import extractors
        from instagrapi.types import Media
        from pydantic import ValidationError
    except ImportError:
        return

    _original = extractors.extract_media_v1

    def _resilient_extract(data):
        try:
            return _original(data)
        except (ValidationError, KeyError, TypeError) as exc:
            log.debug("extract_media_v1 validation failed, using fallback: %s", exc)
            try:
                from copy import deepcopy
                media = deepcopy(data)
                # Run the same pre-processing as the original function
                if "video_versions" in media:
                    try:
                        media["video_url"] = sorted(
                            media["video_versions"],
                            key=lambda o: o.get("height", 0) * o.get("width", 0),
                        )[-1]["url"]
                    except (KeyError, IndexError):
                        pass
                if "image_versions2" in media:
                    try:
                        media["thumbnail_url"] = sorted(
                            media["image_versions2"].get("candidates", []),
                            key=lambda o: o.get("height", 0) * o.get("width", 0),
                        )[-1]["url"]
                    except (KeyError, IndexError):
                        pass
                # Extract user as UserShort
                try:
                    from instagrapi.extractors import extract_user_short
                    media["user"] = extract_user_short(media.get("user"))
                except Exception:
                    pass
                caption_text = (media.get("caption") or {}).get("text", "")
                # model_construct skips validation — gives us a partial but usable object
                return Media.model_construct(
                    caption_text=caption_text,
                    **{k: v for k, v in media.items()
                       if k not in ("caption_text",)},
                )
            except Exception as inner_exc:
                log.debug("extract_media_v1 fallback also failed: %s", inner_exc)
                return None

    extractors.extract_media_v1 = _resilient_extract
    log.debug("Patched extract_media_v1 with ValidationError safety net")


def apply_patches() -> None:
    """Apply all patches. Safe to call multiple times (idempotent)."""
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    _patch_models()
    _patch_extract_media_v1()


# Auto-apply on import
apply_patches()
