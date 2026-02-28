#!/usr/bin/env python3
"""Content generation: Gemini API with template fallback."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from config import Config
from post_queue import format_utc, read_queue, write_queue
from persona import get_persona, next_post_id

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

    # Video text overlay — 3 short lines for on-screen display (85% watch on mute)
    video_text_raw = item.get("video_text")
    if isinstance(video_text_raw, list):
        video_text = [str(t).strip() for t in video_text_raw if str(t).strip()][:3]
    else:
        video_text = None

    # Auto-generate video_text from caption if Gemini didn't provide it
    if not video_text:
        caption = str(item.get("caption", "")).strip()
        if caption:
            lines = [l.strip() for l in caption.split("\n") if l.strip()]
            video_text = []
            if len(lines) >= 1:
                # Hook: first line, truncated to ~8 words
                hook = " ".join(lines[0].split()[:8])
                video_text.append(hook)
            if len(lines) >= 3:
                # Body: middle question line
                video_text.append(" ".join(lines[len(lines) // 2].split()[:8]))
            if len(lines) >= 2:
                # CTA: last line
                video_text.append(" ".join(lines[-1].split()[:8]))

    draft: dict[str, Any] = {
        "id": post_id,
        "status": "draft",
        "topic": str(item.get("topic", "")).strip() or get_persona().get("content", {}).get("default_topic", "trending content"),
        "caption": str(item.get("caption", "")).strip() or "My standards are not seasonal.",
        "alt_text": str(item.get("alt_text", "")).strip() or "",
        "youtube_title": str(item.get("youtube_title", "")).strip() or "",
        "video_text": video_text or [],
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


def _load_templates():
    """Load templates from persona JSON."""
    persona = get_persona()
    return persona.get("templates", [])

TEMPLATES = None  # loaded lazily

def _get_templates():
    global TEMPLATES
    if TEMPLATES is None:
        TEMPLATES = _load_templates()
    return TEMPLATES


def _template_drafts(existing: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    drafts: list[dict[str, Any]] = []
    templates = _get_templates()
    for idx in range(count):
        post_id = next_post_id(existing + drafts)
        slot = now + timedelta(hours=4 * (idx + 1))
        drafts.append(_coerce_draft(templates[idx % len(templates)], post_id, slot))
    return drafts


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def _build_gemini_prompt() -> str:
    """Build the Gemini prompt from persona data."""
    persona = get_persona()
    voice = persona.get("voice", {})
    content = persona.get("content", {})
    
    identity = voice.get("gemini_identity", "an influencer")
    tone = voice.get("tone", "confident and engaging")
    style = voice.get("style", "")
    content_mix = content.get("content_mix_detail", "- Mix of reels, carousels, and single posts")
    topics = ", ".join(content.get("topic_examples", ["trending content"]))
    hooks = content.get("hook_examples", [])
    hook_examples = "\n".join(f"   - '{h}'" for h in hooks[:6]) if hooks else ""
    
    return (
        f"You are generating Instagram + YouTube Shorts draft posts for {identity}.\n\n"
        f"VOICE: {tone}. {style}\n\n"
        "2026 ALGORITHM RULES (CRITICAL — follow these exactly):\n"
        "1. SENDS = #1 SIGNAL: 'Sends per reach' (DM shares) is weighted 3-5x over likes. "
        "EVERY caption MUST be designed to be SENT to a friend. Use patterns that trigger sharing:\n"
        "   - 'Send this to someone who...' / 'Tag the friend who needs this'\n"
        "   - 'Your bestie needs to see this' / 'POV: showing this to your friends'\n"
        "   - Relatable content people share in DMs (budget finds, outfit debates, hot takes)\n"
        "   - Numbered lists and 'save for later' formats\n"
        "2. HOOK — FIRST 3 WORDS MUST CREATE PATTERN INTERRUPT. Use these PROVEN viral formats:\n"
        f"{hook_examples}\n"
        "   Include a specific NUMBER in at least 50% of hooks (numbers stop scrolls).\n"
        "   NEVER start with 'So today I...' or 'Hey guys' — instant scroll-past.\n"
        "3. Front-load SEARCHABLE KEYWORDS in the first line (Instagram + YouTube are search engines). "
        "Start with the topic keyword, not a pronoun.\n"
        "4. Line 2: relatable pain point or hot take that drives comments\n"
        "5. Middle: ask a QUESTION (drives comments = algorithm signal)\n"
        "6. LAST LINE: MUST be a send/share/save CTA that creates FOMO. Alternate between:\n"
        "   'send this to someone who...', 'screenshot before this gets buried',\n"
        "   'tag your friend who needs this', 'save this for your next shopping trip',\n"
        "   'share this with the one who always asks what to wear'\n"
        "7. Max 1-2 emojis total. NO hashtags in caption.\n\n"
        "CONTENT MIX (spread across {count} posts):\n"
        f"{content_mix}\n\n"
        "TRENDING TOPIC IDEAS (rotate — nothing generic, be SPECIFIC):\n"
        f"{topics}\n\n"
        "For carousel posts, include 'slides': array of 5-6 short scene descriptions "
        "(what each slide should visually show — be specific about clothing, pose, setting).\n\n"
        "Return ONLY a JSON array of {count} objects with these fields:\n"
        "- topic: specific scene (not generic, include location/occasion/price if relevant)\n"
        "- caption: 3-5 lines — scroll-stopping hook first, question in middle, send/share CTA last, "
        "NO hashtags\n"
        "- video_text: array of EXACTLY 3 short text lines (max 8 words each) for ON-SCREEN overlay "
        "in the Reel video. These appear as bold text on the video for viewers watching on mute (85%%). "
        "Line 1 = hook (same energy as caption hook but shorter), "
        "Line 2 = key point or question, Line 3 = CTA. "
        "Examples: ['3 looks. Rs 2000. No compromises.', 'Which one are you wearing?', 'Save this for later']\n"
        "- alt_text: descriptive accessibility text for the image (60-120 chars)\n"
        "- youtube_title: catchy YouTube Shorts title under 70 chars, keyword-rich\n"
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
    prompt = _build_gemini_prompt().replace("{count}", str(cfg.draft_count))

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
        post_id = next_post_id(existing + drafts)
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
