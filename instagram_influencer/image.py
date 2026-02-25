#!/usr/bin/env python3
"""Image generation: Replicate/BFL FLUX Kontext (reference-based)."""

from __future__ import annotations

import base64
import logging
import os
import random
import time
from typing import Any

import requests as http_requests

from config import Config, GENERATED_IMAGES_DIR, REFERENCE_DIR

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reference image helpers
# ---------------------------------------------------------------------------

def _pick_reference_image() -> str | None:
    """Pick a random Maya reference photo (only real photos, not text-only)."""
    if not REFERENCE_DIR.is_dir():
        return None
    photos = [
        f for f in sorted(REFERENCE_DIR.iterdir())
        if f.suffix.lower() in {".jpg", ".jpeg", ".png"}
        and f.stat().st_size > 50_000  # skip tiny/text-only images
    ]
    return str(random.choice(photos)) if photos else None


def _image_to_base64(path: str) -> str:
    """Read an image file and return base64 string."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# Replicate FLUX Kontext (reference-image-based — preserves Maya's face)
# ---------------------------------------------------------------------------

def _generate_via_replicate(post: dict[str, Any], cfg: Config) -> str:
    """Generate image via Replicate FLUX Kontext Pro using Maya's reference photo."""
    import replicate
    import os as _os

    # Set token for replicate SDK
    _os.environ["REPLICATE_API_TOKEN"] = cfg.replicate_api_token

    ref_path = _pick_reference_image()
    if not ref_path:
        raise RuntimeError("No reference images found in reference/maya/")

    post_id = str(post.get("id", "unknown")).strip()
    output_path = str(GENERATED_IMAGES_DIR / f"{post_id}.png")
    prompt = _build_kontext_prompt(post)

    log.debug("Replicate Kontext for %s (ref: %s): %s", post_id, os.path.basename(ref_path), prompt[:120])

    output = replicate.run(
        "black-forest-labs/flux-kontext-pro",
        input={
            "prompt": prompt,
            "input_image": open(ref_path, "rb"),
            "aspect_ratio": "3:4",
        },
    )

    # output is a FileOutput or list of FileOutput — download and save
    file_output = output[0] if isinstance(output, list) else output
    with open(output_path, "wb") as f:
        f.write(file_output.read())

    file_size = os.path.getsize(output_path)
    log.info("Replicate Kontext image: %s (%d bytes)", output_path, file_size)
    return output_path


# ---------------------------------------------------------------------------
# BFL FLUX Kontext (reference-image-based — preserves Maya's face)
# ---------------------------------------------------------------------------

BFL_API_URL = "https://api.bfl.ai/v1/flux-kontext-pro"
BFL_POLL_INTERVAL = 1.5
BFL_MAX_POLLS = 60  # ~90 seconds max wait


def _build_kontext_prompt(post: dict[str, Any]) -> str:
    """Build editing prompt for Kontext — hyper-realistic Instagram photography."""
    topic = str(post.get("topic", "")).strip() or "stylish casual outfit"
    notes = str(post.get("notes", "")).strip()

    parts = [
        "Keep this exact same woman — same face, same features, same skin tone, same hair.",
        f"Scene: {topic[:200]}.",
        "Shot on iPhone 15 Pro, natural ambient lighting, slight bokeh background.",
        "Raw unedited photo feel — visible skin texture, natural pores, tiny flyaway hairs.",
        "No airbrushing, no plastic skin, no symmetrical perfection.",
        "Candid relaxed pose, genuine expression, like a real Instagram selfie or friend-took-this photo.",
        "Warm natural color grading, slight golden hour tones, no oversaturation.",
    ]
    if notes:
        clean = notes.split("| generated_by=")[0].strip()
        if clean:
            parts.append(f"Mood: {clean[:150]}.")
    return " ".join(parts)


def _generate_via_bfl(post: dict[str, Any], cfg: Config) -> str:
    """Generate image via BFL FLUX Kontext Pro using Maya's reference photo."""
    ref_path = _pick_reference_image()
    if not ref_path:
        raise RuntimeError("No reference images found in reference/maya/")

    post_id = str(post.get("id", "unknown")).strip()
    output_path = str(GENERATED_IMAGES_DIR / f"{post_id}.png")
    prompt = _build_kontext_prompt(post)
    ref_b64 = _image_to_base64(ref_path)

    log.debug("BFL Kontext for %s (ref: %s): %s", post_id, os.path.basename(ref_path), prompt[:120])

    # Submit generation request
    resp = http_requests.post(
        BFL_API_URL,
        headers={
            "accept": "application/json",
            "x-key": cfg.bfl_api_key,
            "Content-Type": "application/json",
        },
        json={
            "prompt": prompt,
            "input_image": ref_b64,
            "aspect_ratio": "3:4",
        },
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"BFL submit failed ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    polling_url = data.get("polling_url")
    if not polling_url:
        raise RuntimeError(f"BFL did not return polling_url: {data}")

    # Poll for result
    for _ in range(BFL_MAX_POLLS):
        time.sleep(BFL_POLL_INTERVAL)
        poll = http_requests.get(
            polling_url,
            headers={"accept": "application/json", "x-key": cfg.bfl_api_key},
            timeout=15,
        ).json()

        status = poll.get("status", "")
        if status == "Ready":
            image_url = poll.get("result", {}).get("sample", "")
            if not image_url:
                raise RuntimeError(f"BFL Ready but no image URL: {poll}")
            # Download the image
            img_resp = http_requests.get(image_url, timeout=60)
            if img_resp.status_code >= 400:
                raise RuntimeError(f"Failed to download BFL image ({img_resp.status_code})")
            with open(output_path, "wb") as f:
                f.write(img_resp.content)
            log.info("BFL Kontext image: %s (%d bytes)", output_path, len(img_resp.content))
            return output_path
        elif status in {"Error", "Failed", "Request Moderated"}:
            raise RuntimeError(f"BFL generation failed: {poll}")

    raise RuntimeError("BFL polling timed out")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _is_placeholder(url: str) -> bool:
    value = url.strip().lower()
    if not value:
        return True
    if "example.com" in value or "pollinations.ai" in value:
        return True
    if not value.startswith(("http://", "https://")) and not os.path.exists(value):
        return True
    return False


def fill_image_urls(posts: list[dict[str, Any]], cfg: Config) -> int:
    """Generate images for posts missing them. Returns count updated.

    Priority: Replicate Kontext → BFL Kontext. Errors if both fail.
    """
    has_replicate = bool(cfg.replicate_api_token)
    has_bfl = bool(cfg.bfl_api_key)

    if not has_replicate and not has_bfl:
        log.warning("No image API keys set (need REPLICATE_API_TOKEN or BFL_API_KEY)")
        return 0

    GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    updated = 0

    for post in posts:
        status = str(post.get("status", "")).strip().lower()
        if status in {"posted", "failed"}:
            continue

        image = str(post.get("image_url", "")).strip()
        video = str(post.get("video_url", "")).strip()
        if video and not _is_placeholder(video):
            continue
        if image and not _is_placeholder(image):
            continue

        # Fallback chain: Replicate → BFL → HF
        local_path = None

        if local_path is None and has_replicate:
            try:
                local_path = _generate_via_replicate(post, cfg)
            except Exception as exc:
                log.warning("Replicate Kontext failed for %s: %s", post.get("id"), exc)

        if local_path is None and has_bfl:
            try:
                local_path = _generate_via_bfl(post, cfg)
            except Exception as exc:
                log.warning("BFL Kontext failed for %s: %s", post.get("id"), exc)

        if local_path is None:
            log.error("All image providers failed for %s — no fallback available", post.get("id"))

        if local_path:
            post["image_url"] = local_path
            post["video_url"] = None
            post["is_reel"] = False
            updated += 1

    return updated
