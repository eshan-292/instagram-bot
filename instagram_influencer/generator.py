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
    post_type = str(item.get("post_type", "reel")).strip().lower()
    if post_type not in ("reel", "carousel", "single"):
        post_type = "reel"

    slides = item.get("slides", [])
    if not isinstance(slides, list):
        slides = []

    draft: dict[str, Any] = {
        "id": post_id,
        "status": "draft",
        "topic": str(item.get("topic", "")).strip() or "Mumbai street-luxe confidence fit",
        "caption": str(item.get("caption", "")).strip() or "My standards are not seasonal.",
        "image_url": "",
        "video_url": None,
        "is_reel": post_type == "reel",
        "post_type": post_type,
        "scheduled_at": format_utc(slot),
        "notes": str(item.get("notes", "")).strip() or "full-body editorial frame",
    }
    if post_type == "carousel" and slides:
        draft["slides"] = [str(s).strip() for s in slides[:6] if str(s).strip()]
    return draft


TEMPLATES = [
    {
        "topic": "3 budget looks under ₹2000 — Mumbai street style",
        "caption": "Mumbai street style under ₹2000.\nThree looks. One rule: don't look broke.\nSave this for your next shopping trip.",
        "notes": "full-body frame, bright Mumbai street background",
        "post_type": "carousel",
        "slides": [
            "Hook slide: Maya holding up 3 fingers, playful confident expression, text overlay '₹2000. 3 outfits. No compromises.'",
            "Look 1: casual chic — white linen coord set, gold hoops, kolhapuri chappals",
            "Look 2: street glam — floral co-ord in rust tones, minimal jewelry, white sneakers",
            "Look 3: indo-western fusion — cropped kurta with wide-leg jeans, block print dupatta",
            "Outfit detail close-up — accessories and fabric texture",
            "Final pose: all three outfits side by side, confidence energy",
        ],
    },
    {
        "topic": "Power blazer with street-luxe edge",
        "caption": "Mumbai streets hit different in a blazer.\nPolite is not my default setting. Presence is.",
        "notes": "mid shot, blazer silhouette, clean city background",
        "post_type": "reel",
    },
    {
        "topic": "One kurta, 5 ways — ethnic modern fusion",
        "caption": "One kurta. Five personalities. Which one are you?\nSave this — you'll need it.",
        "notes": "clean studio-style background, full-body each look",
        "post_type": "carousel",
        "slides": [
            "Hook: Maya with kurta on hanger, caption '1 piece. 5 vibes.'",
            "Style 1: classic — kurta with palazzo and kolhapuris",
            "Style 2: fusion — kurta belted with straight jeans and boots",
            "Style 3: street — kurta knotted, denim shorts, sneakers",
            "Style 4: evening — kurta with statement earrings, heels, minimal clutch",
            "Style 5: lounge — oversized kurta as a dress, slides",
        ],
    },
    {
        "topic": "Minimal makeup, maximal authority look",
        "caption": "You wanted sweet.\nI brought standards.",
        "notes": "close-up, natural skin texture, structured hair",
        "post_type": "single",
    },
    {
        "topic": "GRWM for a Bandra house party",
        "caption": "Getting ready for a Bandra house party — my way.\nSend this to the one who always asks what to wear.",
        "notes": "bedroom/vanity setting, warm lighting, candid getting-ready vibe",
        "post_type": "reel",
    },
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
    "Short punchy lines, sharp hooks, subtle wit, feminine dominance energy. "
    "Casual human tone — never robotic or generic.\n\n"
    "2026 ALGORITHM RULES:\n"
    "- Front-load keywords (Instagram is a search engine now): start with the topic, "
    "not 'Hey guys'. E.g. 'Mumbai street style under ₹2000' not 'So today I...'\n"
    "- Drives saves and shares > likes. Last line MUST be a CTA that drives saves or "
    "shares: 'save this', 'send this to your bestie', 'which one would you wear?'\n"
    "- Max 1-2 emojis total\n\n"
    "CONTENT MIX (spread across {count} posts):\n"
    "- 40% carousels: '3 looks', 'one piece 5 ways', styling tips, before/after, budget fits\n"
    "- 40% reels: outfit transitions, GRWM for Indian occasions (haldi, sangeet, party), "
    "before/after thrift transformations\n"
    "- 20% single: aesthetic/editorial, minimal-caption power shots\n\n"
    "TOPIC IDEAS (rotate — nothing generic):\n"
    "Budget styling (₹1500-₹2000 Indian rupees), GRWM for Indian events, one piece N ways, "
    "ethnic+modern fusion, Mumbai-specific looks (Bandra, Colaba, Kala Ghoda), monsoon fashion, "
    "office-to-party transitions, thrift-to-chic, Indo-western street style.\n\n"
    "For carousel posts, include 'slides': array of 5-6 short scene descriptions "
    "(what each slide should visually show — be specific about clothing, pose, setting).\n\n"
    "Return ONLY a JSON array of {count} objects:\n"
    "- topic: specific scene (not generic, include location/occasion/price if relevant)\n"
    "- caption: 2-4 lines, front-loaded keyword, ends with save/share CTA, no hashtags\n"
    "- notes: photography direction for image generation (framing, lighting, mood)\n"
    "- post_type: 'reel' | 'carousel' | 'single'\n"
    "- slides: array of 5-6 scene descriptions (only for carousel, omit for reel/single)\n\n"
    "No markdown, no explanation, just the JSON array."
)


def _extract_json(text: str) -> str:
    """Extract JSON array from response text, stripping markdown fences etc."""
    raw = text.strip()
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
    log.info("Added %d drafts via %s (types: %s)",
             len(drafts), method,
             [d.get("post_type", "reel") for d in drafts])
    return True
