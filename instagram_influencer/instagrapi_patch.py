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


def _patch_reels_timeline_media() -> None:
    """Fix broken pagination in reels_timeline_media (explore_reels).

    Bug: instagrapi sets next_max_id = paging_info["more_available"] which is
    a boolean (True), causing every subsequent request to send ?max_id=True
    instead of the real cursor. Instagram returns 200 but with no parseable
    items, creating an infinite loop that burns through rate limits.

    Fix: Use paging_info["max_id"] for the cursor, and break on empty pages.
    """
    try:
        from instagrapi import Client
        from instagrapi.extractors import extract_media_v1
    except ImportError:
        return

    def _fixed_reels_timeline_media(self, collection_pk, amount=10, last_media_pk=0):
        if collection_pk == "reels":
            endpoint = "clips/connected/"
        elif collection_pk == "explore_reels":
            endpoint = "clips/discover/"
        else:
            endpoint = "clips/discover/"

        last_media_pk = last_media_pk and int(last_media_pk)
        total_items = []
        next_max_id = ""
        empty_pages = 0

        while True:
            if len(total_items) >= amount:
                return total_items[:amount]

            try:
                result = self.private_request(
                    endpoint,
                    data=" ",
                    params={"max_id": next_max_id},
                )
            except Exception as e:
                self.logger.exception(e)
                return total_items

            # Instagram moved reels from "items" to "items_with_ads" (2025+)
            items = result.get("items", [])
            if not items:
                items = result.get("items_with_ads", [])
                if items:
                    log.info("explore_reels: using items_with_ads (%d items)", len(items))

            if not items:
                empty_pages += 1
                if empty_pages >= 3:
                    log.info("explore_reels: %d consecutive empty pages — stopping", empty_pages)
                    return total_items
            else:
                empty_pages = 0

            parsed_count = 0
            for item in items:
                media_data = item.get("media")
                if not media_data:
                    continue
                if last_media_pk and last_media_pk == media_data.get("pk"):
                    return total_items
                parsed = extract_media_v1(media_data)
                if parsed is not None:
                    total_items.append(parsed)
                    parsed_count += 1

            if items:
                log.info("explore_reels: page had %d items, parsed %d", len(items), parsed_count)

            paging = result.get("paging_info", {})
            if not paging.get("more_available"):
                return total_items

            # FIX: use max_id cursor, not the boolean more_available
            cursor = paging.get("max_id")
            if not cursor or cursor == next_max_id:
                log.info("explore_reels: no new cursor in paging_info — stopping")
                return total_items
            next_max_id = str(cursor)

        return total_items

    Client.reels_timeline_media = _fixed_reels_timeline_media
    log.debug("Patched reels_timeline_media with fixed pagination")


def _patch_search_music() -> None:
    """Fix search_music to handle None items in Instagram's music API response.

    Instagram's music/audio_global_search/ endpoint sometimes returns items
    where the "track" field is None (instead of a dict). The original
    search_music does:
        [extract_track(item["track"]) for item in result["items"]]
    which crashes with 'NoneType' object has no attribute 'get' when
    item["track"] is None.

    Fix: Filter out None tracks and wrap extract_track in try/except.
    """
    try:
        from instagrapi import Client
        from instagrapi.extractors import extract_track
    except ImportError:
        return

    _original_search = getattr(Client, "search_music", None)
    if not _original_search:
        return

    def _resilient_search_music(self, query: str):
        params = {
            "query": query,
            "browse_session_id": self.generate_uuid(),
        }
        result = self.private_request("music/audio_global_search/", params=params)

        items = result.get("items") or []
        tracks = []
        for item in items:
            if not isinstance(item, dict):
                continue
            track_data = item.get("track")
            if not track_data or not isinstance(track_data, dict):
                continue
            # dash_manifest is required for extract_track — skip if missing
            if not track_data.get("dash_manifest"):
                continue
            try:
                track = extract_track(track_data)
                if track:
                    tracks.append(track)
            except Exception as exc:
                log.debug("extract_track failed for '%s': %s",
                          track_data.get("title", "?"), exc)
                continue

        if tracks:
            log.debug("search_music: %d/%d items parsed for query='%s'",
                      len(tracks), len(items), query)
        return tracks

    Client.search_music = _resilient_search_music
    log.debug("Patched search_music with None-safe item filtering")


def apply_patches() -> None:
    """Apply all patches. Safe to call multiple times (idempotent)."""
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    _patch_models()
    _patch_extract_media_v1()
    _patch_reels_timeline_media()
    _patch_search_music()


# Auto-apply on import
apply_patches()
