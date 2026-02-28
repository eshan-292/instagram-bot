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
        "topic": str(item.get("topic", "")).strip() or "Mumbai street-luxe confidence fit",
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


TEMPLATES = [
    {
        "topic": "3 budget looks under ₹2000 — Mumbai street style",
        "caption": "3 Mumbai street looks under ₹2000.\nThree outfits. One rule: don't look broke.\nWhich one are you wearing first?\nSend this to your shopping bestie.",
        "alt_text": "Young Indian woman showcasing three budget-friendly street style outfits on a Mumbai street",
        "youtube_title": "3 Budget Outfits Under ₹2000 That Look Expensive",
        "video_text": ["3 looks. ₹2000. Zero compromises.", "Which one are you stealing?", "Send to your shopping bestie"],
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
        "caption": "Blazer on Mumbai streets.\nPolite is not my default setting. Presence is.\nWould you rock this?\nSend to someone who needs this energy.",
        "alt_text": "Indian woman in a structured blazer walking confidently on a Mumbai city street",
        "youtube_title": "Power Blazer Street Style That Commands Attention",
        "video_text": ["Blazer. Mumbai streets. Main character.", "Would you rock this?", "Send to someone who needs this"],
        "notes": "mid shot, blazer silhouette, clean city background",
        "post_type": "reel",
    },
    {
        "topic": "One kurta, 5 ways — ethnic modern fusion",
        "caption": "One kurta. Five personalities.\nWhich one are you?\nSave this — your wardrobe will thank you.\nTag your friend who needs this hack.",
        "alt_text": "Young Indian woman styling a single kurta five different ways from casual to evening",
        "youtube_title": "1 Kurta Styled 5 Ways - Ethnic to Street",
        "video_text": ["1 kurta. 5 completely different vibes.", "Which style is you?", "Save this for your next outfit crisis"],
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
        "caption": "Minimal makeup authority look.\nYou wanted sweet — I brought standards.\nCould you pull this off?\nScreenshot this for your next power moment.",
        "alt_text": "Close-up portrait of Indian woman with minimal natural makeup and structured hair",
        "youtube_title": "Minimal Makeup Maximum Confidence - Natural Look",
        "video_text": ["Minimal makeup. Maximum authority.", "Could you pull this off?", "Screenshot this for your next moment"],
        "notes": "close-up, natural skin texture, structured hair",
        "post_type": "single",
    },
    {
        "topic": "GRWM for a Bandra house party",
        "caption": "GRWM for a Bandra house party.\nThat 'what do I wear' panic? Been there.\nWhat's your go-to party outfit?\nSend this to the one who always asks what to wear.",
        "alt_text": "Young Indian woman getting ready for a party in her bedroom with warm lighting",
        "youtube_title": "Get Ready With Me - Bandra House Party Edition",
        "video_text": ["POV: getting ready for Bandra party", "That outfit panic? Been there.", "Send to your always-late bestie"],
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
    "You are generating Instagram + YouTube Shorts draft posts for Maya Varma, a 23-year-old "
    "Indian fashion influencer in Mumbai.\n\n"
    "VOICE: bold, confident, teasing, emotionally intelligent, unapologetic but not rude. "
    "Short punchy lines, sharp hooks, subtle wit, feminine dominance energy. "
    "Casual human tone — never robotic or generic.\n\n"
    "2026 ALGORITHM RULES (CRITICAL — follow these exactly):\n"
    "1. SENDS = #1 SIGNAL: 'Sends per reach' (DM shares) is weighted 3-5x over likes. "
    "EVERY caption MUST be designed to be SENT to a friend. Use patterns that trigger sharing:\n"
    "   - 'Send this to someone who...' / 'Tag the friend who needs this'\n"
    "   - 'Your bestie needs to see this' / 'POV: showing this to your friends'\n"
    "   - Relatable content people share in DMs (budget finds, outfit debates, hot takes)\n"
    "   - Numbered lists and 'save for later' formats\n"
    "2. HOOK — FIRST 3 WORDS MUST CREATE PATTERN INTERRUPT. Use these PROVEN viral formats:\n"
    "   - Numbers stop scrolls: '3 outfits.', '5 ways to...', '₹2000. Zero compromises.'\n"
    "   - POV format: 'POV: your bestie styled you', 'POV: Mumbai streets at 7am'\n"
    "   - Bold claims: 'This outfit costs ₹800.', 'Stop buying basics.'\n"
    "   - Curiosity gaps: 'Wait for the last one.', 'Nobody talks about this.'\n"
    "   - Direct commands: 'Stop scrolling if you...', 'Save this before it gets buried.'\n"
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
    "- 40% carousels: '3 looks', 'one piece 5 ways', styling tips, before/after, budget fits, "
    "'what I ordered vs what I got', wardrobe hacks — carousels get highest saves+sends\n"
    "- 40% reels: outfit transitions, GRWM for Indian occasions (haldi, sangeet, party), "
    "before/after thrift transformations, 'style this with me', POV fashion moments\n"
    "- 20% single: aesthetic/editorial, minimal-caption power shots, quote overlays\n\n"
    "TRENDING TOPIC IDEAS (rotate — nothing generic, be SPECIFIC):\n"
    "Budget styling (₹1500-₹2000 Indian rupees), GRWM for Indian events, one piece N ways, "
    "ethnic+modern fusion, Mumbai-specific looks (Bandra, Colaba, Kala Ghoda), monsoon fashion, "
    "office-to-party transitions, thrift-to-chic, Indo-western street style, "
    "Zara vs thrift challenge, airport look under ₹3000, date night 3 ways, "
    "'what I'd wear to [trending event]', recreating celebrity looks on a budget, "
    "capsule wardrobe India, minimalist Indian fashion, college outfit rotation, "
    "wedding season prep on a budget, styling my mom's old clothes\n\n"
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
    "Examples: ['3 looks. ₹2000. No compromises.', 'Which one are you wearing?', 'Save this for later'], "
    "['POV: Bandra party. Zero budget.', 'That outfit panic? Been there.', 'Send to your always-late bestie']\n"
    "- alt_text: descriptive accessibility text for the image (60-120 chars). Describe what's "
    "visually shown for screen readers + Instagram SEO. E.g. 'Young Indian woman in a rust "
    "linen coord set walking through Bandra street market'\n"
    "- youtube_title: catchy YouTube Shorts title under 70 chars, keyword-rich, hooks viewer. "
    "E.g. '3 Budget Outfits Under ₹2000 That Look Expensive' — do NOT include #Shorts\n"
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
