#!/usr/bin/env python3
"""Image management: manual image lookup + prompt generation for user reference.

Since the Replicate/BFL API quota is exhausted, images are now generated manually
using the Gemini app. This module:
  1. Generates descriptive prompts for each post and saves them for the user.
  2. Scans the generated_images/pending/ directory for user-placed images.
  3. Links found images back to draft posts in the queue.

Directory structure:
  data/{persona}/generated_images/
    pending/
      maya-042.jpg             ← single image / reel (user places this)
      maya-043/
        1.jpg                  ← carousel slide 1
        2.jpg                  ← carousel slide 2
        ...
    prompts/
      maya-042.txt             ← Gemini prompt for reference
    IMAGE_PROMPTS.md           ← master summary (easy to read at a glance)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from config import Config
from persona import get_persona, persona_images_dir

log = logging.getLogger(__name__)


def _pending_dir():
    return persona_images_dir() / "pending"


def _prompts_dir():
    return persona_images_dir() / "prompts"


# ---------------------------------------------------------------------------
# Character appearance — loaded from persona config
# ---------------------------------------------------------------------------

def _character_description():
    return get_persona().get("physical_description", "")


_PHOTO_STYLE = (
    "Photography style: shot on iPhone 15 Pro, natural ambient lighting, "
    "candid real-photo feel, visible skin texture, warm natural color grading, "
    "slight bokeh background. No airbrushing, no heavy filters, portrait 3:4 ratio."
)

# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_single_prompt(post: dict[str, Any]) -> str:
    """Build a Gemini image prompt for a single-image or reel post."""
    topic = str(post.get("topic", "")).strip()
    notes = str(post.get("notes", "")).strip().split("| generated_by=")[0].strip()

    parts = [_character_description(), f"Scene: {topic}.", _PHOTO_STYLE]
    if notes:
        parts.append(f"Framing/mood: {notes}.")
    return " ".join(parts)


def _build_carousel_prompts(post: dict[str, Any]) -> list[str]:
    """Build per-slide prompts for a carousel post (5-6 slides)."""
    topic = str(post.get("topic", "")).strip()
    slides = post.get("slides", [])

    if not slides:
        # Default slide structure for fashion carousels
        slides = [
            f"Hook/hero shot — {topic}. Strong first impression, camera-facing.",
            f"Detail close-up — fabric, accessories, or styling element of {topic}.",
            f"Full-body reveal — complete outfit for {topic}, confident pose.",
            f"Lifestyle/in-action shot — candid moment, {topic}.",
            f"Alternate angle or close-up face shot for {topic}.",
            f"Final pose — CTA energy, looking at camera, {topic}.",
        ]

    prompts = []
    for i, slide_desc in enumerate(slides[:6], 1):
        parts = [
            _character_description(),
            f"(Slide {i} of a carousel post.)",
            f"Scene: {slide_desc}",
            _PHOTO_STYLE,
        ]
        prompts.append(" ".join(parts))
    return prompts


# ---------------------------------------------------------------------------
# Prompt saving
# ---------------------------------------------------------------------------

def _save_post_prompts(post: dict[str, Any]) -> None:
    """Save image prompts for a post to prompts/ directory."""
    prompts_dir = _prompts_dir()
    prompts_dir.mkdir(parents=True, exist_ok=True)
    post_id = str(post.get("id", "unknown"))
    post_type = str(post.get("post_type", "reel")).lower()

    lines = [
        f"=== {post_id} | {post_type.upper()} ===",
        f"Topic: {post.get('topic', '')}",
        f"Caption: {post.get('caption', '')}",
        "",
    ]

    if post_type == "carousel":
        prompts = _build_carousel_prompts(post)
        lines.append(f"CAROUSEL — {len(prompts)} slides")
        lines.append(f"Place in: generated_images/pending/{post_id}/1.jpg, 2.jpg, ...")
        lines.append("")
        for i, prompt in enumerate(prompts, 1):
            lines.append(f"--- Slide {i} ---")
            lines.append(prompt)
            lines.append("")
    else:
        prompt = _build_single_prompt(post)
        lines.append(f"Place at: generated_images/pending/{post_id}.jpg")
        lines.append("")
        lines.append("--- Prompt ---")
        lines.append(prompt)
        lines.append("")

    prompt_file = prompts_dir / f"{post_id}.txt"
    prompt_file.write_text("\n".join(lines), encoding="utf-8")
    log.debug("Saved prompt for %s → %s", post_id, prompt_file.name)


def write_prompts_summary(posts: list[dict[str, Any]]) -> None:
    """Write IMAGE_PROMPTS.md — a readable summary of all posts needing images."""
    images_dir = persona_images_dir()
    images_dir.mkdir(parents=True, exist_ok=True)

    pending = [
        p for p in posts
        if str(p.get("status", "")).lower() in {"draft", "approved"}
        and not _has_images(p)
    ]

    if not pending:
        return

    persona_name = get_persona()['name']
    lines = [
        f"# {persona_name} — Image Prompts",
        "",
        "Generate these images in the Gemini app and place them at the paths shown.",
        "",
        "---",
        "",
    ]

    for post in pending:
        post_id = str(post.get("id", "unknown"))
        post_type = str(post.get("post_type", "reel")).lower()
        topic = str(post.get("topic", ""))

        lines += [
            f"## {post_id} — {post_type.upper()}",
            f"**Topic:** {topic}",
            f"**Caption:** {post.get('caption', '')}",
            "",
        ]

        if post_type == "carousel":
            prompts = _build_carousel_prompts(post)
            lines.append(
                f"**Place {len(prompts)} images in:** "
                f"`generated_images/pending/{post_id}/1.jpg`, `2.jpg`, ..."
            )
            lines.append("")
            for i, prompt in enumerate(prompts, 1):
                lines.append(f"**Slide {i}:** {prompt}")
                lines.append("")
        else:
            prompt = _build_single_prompt(post)
            lines.append(f"**Place image at:** `generated_images/pending/{post_id}.jpg`")
            lines.append("")
            lines.append(f"**Prompt:**")
            lines.append(f"> {prompt}")
            lines.append("")

        lines += ["---", ""]

    summary = images_dir / "IMAGE_PROMPTS.md"
    summary.write_text("\n".join(lines), encoding="utf-8")
    log.info("Updated IMAGE_PROMPTS.md — %d posts need images", len(pending))


# ---------------------------------------------------------------------------
# Pending image discovery
# ---------------------------------------------------------------------------

def _has_images(post: dict[str, Any]) -> bool:
    """Check if a post already has valid images linked."""
    post_type = str(post.get("post_type", "reel")).lower()
    if post_type == "carousel":
        images = post.get("carousel_images", [])
        return bool(images) and all(os.path.exists(p) for p in images)
    image = str(post.get("image_url", "")).strip()
    return bool(image) and os.path.exists(image)


def _find_pending_single(post_id: str) -> str | None:
    """Look for user-placed image at pending/{post_id}.(jpg|png|webp)."""
    pending_dir = _pending_dir()
    if not pending_dir.is_dir():
        return None
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        path = pending_dir / f"{post_id}{ext}"
        if path.exists() and path.stat().st_size > 10_000:
            return str(path)
    return None


def _find_pending_carousel(post_id: str) -> list[str]:
    """Look for carousel images in pending/{post_id}/ directory."""
    carousel_dir = _pending_dir() / post_id
    if not carousel_dir.is_dir():
        return []
    images = sorted(
        [
            str(f) for f in carousel_dir.iterdir()
            if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            and f.stat().st_size > 10_000
        ],
        key=lambda p: Path(p).stem,  # sort by 1, 2, 3, ...
    )
    return images


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fill_image_urls(posts: list[dict[str, Any]], cfg: Config) -> int:
    """Scan pending/ for user-placed images and link them to draft posts.

    Also saves/updates image prompts for any post that still needs images.
    Returns count of posts updated.
    """
    pending_dir = _pending_dir()
    prompts_dir = _prompts_dir()
    pending_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    updated = 0

    for post in posts:
        status = str(post.get("status", "")).strip().lower()
        if status in {"posted", "failed"}:
            continue

        post_id = str(post.get("id", "")).strip()
        if not post_id:
            continue

        post_type = str(post.get("post_type", "reel")).strip().lower()

        # Always refresh prompts for posts that still need images
        if not _has_images(post):
            _save_post_prompts(post)

        if post_type == "carousel":
            if _has_images(post):
                continue
            images = _find_pending_carousel(post_id)
            if images and len(images) >= 2:
                post["carousel_images"] = images
                post["image_url"] = images[0]  # thumbnail fallback
                post["is_reel"] = False
                updated += 1
                log.info("Linked carousel for %s: %d slides", post_id, len(images))
        else:
            if _has_images(post):
                continue
            image_path = _find_pending_single(post_id)
            if image_path:
                post["image_url"] = image_path
                post["is_reel"] = post_type == "reel"
                updated += 1
                log.info("Linked image for %s (%s): %s", post_id, post_type, image_path)

    # Write the master summary for the user
    write_prompts_summary(posts)

    if updated == 0 and not any(_has_images(p) for p in posts
                                if str(p.get("status", "")).lower() in {"draft", "approved"}):
        log.info(
            "No images found in pending/. See generated_images/IMAGE_PROMPTS.md for prompts."
        )

    return updated
