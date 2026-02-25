#!/usr/bin/env python3
"""Content generation: Gemini API with template fallback."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from config import Config
from post_queue import format_utc, next_maya_id, read_queue, write_queue

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Draft helpers
# ---------------------------------------------------------------------------

def _coerce_draft(item: dict[str, Any], post_id: str, slot: datetime) -> dict[str, Any]:
    return {
        "id": post_id,
        "status": "draft",
        "topic": str(item.get("topic", "")).strip() or "Mumbai street-luxe confidence fit",
        "caption": str(item.get("caption", "")).strip() or "My standards are not seasonal.",
        "image_url": "",
        "video_url": None,
        "is_reel": False,
        "scheduled_at": format_utc(slot),
        "notes": str(item.get("notes", "")).strip() or "full-body editorial frame",
    }


TEMPLATES = [
    {"topic": "Power blazer with street-luxe edge",
     "caption": "Polite is not my default setting.\nPresence is.",
     "notes": "mid shot, blazer silhouette, clean city lines"},
    {"topic": "Monochrome evening fit in Mumbai",
     "caption": "Soft voice. Sharp boundaries.",
     "notes": "golden hour, full-body frame, confident walk"},
    {"topic": "Minimal makeup, maximal authority look",
     "caption": "You wanted sweet.\nI brought standards.",
     "notes": "close-up, natural skin texture, structured hair"},
]


def _template_drafts(existing: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    drafts: list[dict[str, Any]] = []
    for idx in range(count):
        post_id = next_maya_id(existing + drafts)
        slot = now + timedelta(hours=4 * (idx + 1))
        drafts.append(_coerce_draft(TEMPLATES[idx % len(TEMPLATES)], post_id, slot))
    return drafts


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

GEMINI_PROMPT = (
    "You are generating Instagram draft posts for Maya Varma, a 23-year-old Indian "
    "fashion influencer in Mumbai.\n\n"
    "VOICE: bold, confident, teasing, emotionally intelligent, unapologetic but not rude. "
    "Short punchy lines, sharp hooks, subtle roasts, feminine dominance energy. "
    "Casual human tone — never robotic or generic.\n\n"
    "RULES:\n"
    "- Each caption: 1-3 short lines, no hashtags, no emojis\n"
    "- Topic: a specific fashion/lifestyle scene (not generic)\n"
    "- Notes: photography direction (framing, lighting, mood) for image generation\n"
    "- Every post must feel different — vary settings, moods, outfits\n\n"
    "Return ONLY a JSON array of {count} objects with keys: topic, caption, notes.\n"
    "No markdown, no explanation, just the JSON array."
)


def _extract_json(text: str) -> str:
    """Extract JSON array from response text, stripping markdown fences etc."""
    raw = text.strip()
    # Strip markdown code fences
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()
    start, end = raw.find("["), raw.rfind("]")
    return raw[start : end + 1] if start >= 0 and end > start else raw


def _gemini_generate(cfg: Config, existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate drafts via Gemini API."""
    from google import genai

    client = genai.Client(api_key=cfg.gemini_api_key)
    prompt = GEMINI_PROMPT.replace("{count}", str(cfg.draft_count))

    response = client.models.generate_content(
        model=cfg.gemini_model,
        contents=prompt,
    )

    raw_text = response.text or ""
    parsed = json.loads(_extract_json(raw_text))
    if not isinstance(parsed, list):
        raise ValueError("Gemini did not return a JSON array")

    now = datetime.now(timezone.utc)
    drafts: list[dict[str, Any]] = []
    for idx, item in enumerate(parsed[:cfg.draft_count]):
        if not isinstance(item, dict):
            continue
        post_id = next_maya_id(existing + drafts)
        slot = now + timedelta(hours=4 * (idx + 1))
        drafts.append(_coerce_draft(item, post_id, slot))

    if len(drafts) < cfg.draft_count:
        raise ValueError(f"Gemini produced {len(drafts)}/{cfg.draft_count} valid drafts")
    return drafts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_content(queue_path: str, cfg: Config) -> bool:
    """Generate drafts via Gemini, fall back to templates. Returns True if added."""
    posts = read_queue(queue_path)

    try:
        drafts = _gemini_generate(cfg, posts)
        method = f"gemini:{cfg.gemini_model}"
    except Exception as exc:
        log.warning("Gemini failed, using templates: %s", exc)
        drafts = _template_drafts(posts, cfg.draft_count)
        method = "template"

    for d in drafts:
        d["notes"] = f"{d.get('notes', '')} | generated_by={method}".strip()

    posts.extend(drafts)
    write_queue(queue_path, posts)
    log.info("Added %d drafts via %s", len(drafts), method)
    return True
