#!/usr/bin/env python3
"""Content generation: Gemini API with template fallback."""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from config import Config
from post_queue import format_utc, read_queue, write_queue
from persona import get_persona, next_post_id

log = logging.getLogger(__name__)

# Day-of-week names (lowercase) for series matching
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

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

    # Hook-photo reel format (text hooks interleaved with photos)
    reel_format = str(item.get("reel_format", "")).strip().lower()

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
    # Hook-photo reels: reel with 1-2 photos + text hook slides
    if reel_format == "hook_photo":
        draft["reel_format"] = "hook_photo"
        if slides:
            draft["slides"] = [str(s).strip() for s in slides[:2] if str(s).strip()]
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

def _get_todays_series() -> list[dict[str, Any]]:
    """Return content series matching today's day of the week."""
    persona = get_persona()
    series_list = persona.get("content_series", [])
    if not series_list:
        return []
    today = _DAYS[datetime.now(timezone.utc).weekday()]
    return [s for s in series_list if s.get("day", "").lower() == today]


def _build_gemini_prompt() -> str:
    """Build the Gemini prompt from persona data with viral growth features."""
    persona = get_persona()
    voice = persona.get("voice", {})
    content = persona.get("content", {})

    identity = voice.get("gemini_identity", "an influencer")
    tone = voice.get("tone", "confident and engaging")
    style = voice.get("style", "")
    content_mix = content.get("content_mix_detail", "- Mix of reels, carousels, and single posts")
    topics = ", ".join(content.get("topic_examples", ["trending content"]))
    hooks = content.get("hook_examples", [])
    hook_examples = "\n".join(f"   - '{h}'" for h in hooks[:8]) if hooks else ""

    # --- Viral feature: recurring series ---
    series_block = ""
    todays_series = _get_todays_series()
    if todays_series:
        series_items = []
        for s in todays_series:
            name = s.get("name", "")
            injection = s.get("prompt_injection", "")
            hook_tmpl = ", ".join(f"'{h}'" for h in s.get("hook_templates", [])[:3])
            series_items.append(f"   SERIES: '{name}'\n   {injection}\n   Hook templates: {hook_tmpl}")
        series_block = (
            "\n\nRECURRING SERIES (IMPORTANT — at least 1 of {count} posts MUST be from today's series):\n"
            + "\n".join(series_items)
            + "\n   Mark the series post with the series name at the start of the 'notes' field "
            "(e.g. 'series:Friday Fits | ...').\n"
        )

    # --- Viral feature: send engineering ---
    send_triggers = content.get("send_triggers", [])
    send_block = ""
    if send_triggers:
        triggers_str = "\n".join(f"   - {t}" for t in send_triggers)
        send_block = (
            "\n\nSEND ENGINEERING (critical — sends are 3-5x more valuable than likes):\n"
            "For at least 1 of these {count} posts, use one of these send-trigger formats:\n"
            f"{triggers_str}\n"
            "The goal: make the viewer immediately think of ONE specific person to send this to.\n"
        )

    # --- Viral feature: controversy/hot-take ratio ---
    controversy_ratio = content.get("controversy_ratio", 0)
    controversy_block = ""
    if controversy_ratio > 0 and random.random() < controversy_ratio:
        c_topics = content.get("controversy_topics", [])
        c_hooks = content.get("controversy_hooks", [])
        topics_str = ", ".join(f"'{t}'" for t in random.sample(c_topics, min(3, len(c_topics)))) if c_topics else ""
        hooks_str = ", ".join(f"'{h}'" for h in random.sample(c_hooks, min(3, len(c_hooks)))) if c_hooks else ""
        controversy_block = (
            "\n\nCONTROVERSY MODE (active for this batch):\n"
            "At least 1 of these {count} posts MUST be a HOT TAKE or UNPOPULAR OPINION.\n"
            f"   Controversy hooks to use: {hooks_str}\n"
            f"   Topic ideas: {topics_str}\n"
            "   The goal: split the audience 50/50 so they ARGUE in comments and SEND to friends to debate.\n"
            "   Be genuinely polarizing — not fake controversy. Take a real stance.\n"
        )

    # --- Viral feature: viral content formats (from 2026 research) ---
    viral_formats = random.sample([
        "BEFORE/AFTER REVEAL: Show a dramatic transformation — the 'after' payoff keeps viewers watching to the end",
        "RANKING/TIER LIST: Rank items (outfits, products, looks) S/A/B/C tier — viewers WILL disagree in comments",
        "WAIT FOR IT: Build anticipation with 'wait for the last one' — delayed payoff forces full watch",
        "THIS OR THAT: Present 2 clear options and force viewers to pick — splits the audience 50/50",
        "POV STORY: 'POV: you walk in wearing this' — immersive format viewers insert themselves into",
        "CURIOSITY GAP: Open with incomplete info that viewers MUST finish watching to resolve",
        "RATE 1-10: Ask viewers to rate something — guaranteed comments from every viewer",
        "MYTH BUSTER: 'Stop doing [thing]. Here's why.' — contrarian claims force continued watching",
    ], min(3, 8))
    viral_format_str = "\n".join(f"   - {v}" for v in viral_formats)

    return (
        f"You are generating Instagram + YouTube Shorts draft posts for {identity}.\n\n"
        f"VOICE: {tone}. {style}\n\n"
        "2026 ALGORITHM RULES (CRITICAL — follow these exactly):\n"
        "1. SENDS = #1 SIGNAL: DM shares are THE most important metric (Mosseri confirmed). "
        "EVERY caption MUST be designed to be SENT to a friend. Saves are weighted 3x > likes.\n"
        "   Use these send-trigger patterns:\n"
        "   - 'Send this to someone who...' / 'Tag the friend who needs this'\n"
        "   - 'Your bestie needs to see this' / 'POV: showing this to your friends'\n"
        "   - Relatable content people share in DMs (budget finds, outfit debates, hot takes)\n"
        "   - Numbered lists and 'save for later' formats\n"
        "2. HOOK — FIRST 3 WORDS DECIDE EVERYTHING. Viewers decide in 1.7 seconds.\n"
        "   Use these PROVEN viral hook formulas:\n"
        f"{hook_examples}\n"
        "   VIRAL HOOK FORMULAS (use these):\n"
        "   - Contrarian claim: 'Everything you know about [X] is wrong'\n"
        "   - Price shock: 'This costs Rs [low number]. No, seriously.'\n"
        "   - FOMO trigger: 'Everyone is doing this except you'\n"
        "   - The correction: 'Stop doing [X]. Do this instead.'\n"
        "   - Forbidden knowledge: 'I probably shouldn't share this, but...'\n"
        "   Include a specific NUMBER in at least 60%% of hooks (numbers stop scrolls).\n"
        "   NEVER start with 'So today I...' or 'Hey guys' — instant scroll-past.\n"
        "3. Front-load SEARCHABLE KEYWORDS in the first line (IG + YT are search engines now).\n"
        "4. Line 2: relatable pain point or hot take (drives comments = algorithm signal)\n"
        "5. Middle: ask a QUESTION that splits opinion (viewers who disagree ALWAYS comment)\n"
        "6. LAST LINE: MUST be a send/share/save CTA. Alternate between:\n"
        "   'send this to someone who...', 'screenshot before this gets buried',\n"
        "   'tag your friend who needs this', 'share with the one who always asks what to wear'\n"
        "7. Max 1-2 emojis total. NO hashtags in caption.\n\n"
        "VIRAL CONTENT FORMATS (use at least 1 of these across {count} posts):\n"
        f"{viral_format_str}\n\n"
        "CURIOSITY GAP ARCHITECTURE (critical for watch-through rate):\n"
        "   - Every caption should create an OPEN LOOP — a question, tease, or incomplete info\n"
        "     that viewers NEED to finish watching to resolve.\n"
        "   - Use 'delayed payoff' — promise something in the hook, deliver it at the end.\n"
        "   - The video_text should build tension: Line 1 opens the loop, Line 3 closes it.\n\n"
        f"{series_block}"
        f"{send_block}"
        f"{controversy_block}"
        "CONTENT MIX (spread across {count} posts):\n"
        f"{content_mix}\n\n"
        "TRENDING TOPIC IDEAS (rotate — nothing generic, be SPECIFIC with prices/numbers/places):\n"
        f"{topics}\n\n"
        "For carousel posts, include 'slides': array of 5-6 short scene descriptions "
        "(what each slide should visually show — be specific about clothing, pose, setting).\n\n"
        "HOOK-PHOTO REEL FORMAT (THE PRIMARY FORMAT — use for 60%+ of {count} posts):\n"
        "This is the #1 viral format in 2026. Bold text hooks interleaved with 1-2 photos.\n"
        "Set post_type='reel' AND reel_format='hook_photo'.\n"
        "Include 'slides': array of 1-2 photo descriptions (what each photo should show).\n"
        "The video_text becomes the hook text shown between/around photos:\n"
        "  Line 1 = SCROLL-STOPPING hook text (shown BEFORE first photo on dark screen)\n"
        "  Line 2 = curiosity/bridge text (shown AFTER photo — keeps them watching)\n"
        "  Line 3 = CTA text (shown at the end in gold — drives sends/saves)\n\n"
        "VIRAL HOOK FORMULAS (use these — proven to stop scrolling in 1.7 seconds):\n"
        "  - CURIOSITY GAP: 'This feels illegal to know.' / 'I probably shouldn't share this, but...'\n"
        "  - CONTRARIAN CLAIM: 'Everyone's doing this wrong.' / 'Stop doing [X]. Do this instead.'\n"
        "  - PRICE SHOCK: 'This costs Rs [low number]. No, seriously.'\n"
        "  - TRANSFORMATION: 'Watch what happened after 30 days.' / '3 years in 30 seconds.'\n"
        "  - RELATABLE POV: 'POV: you walk in wearing this' / 'If you've ever [relatable thing]...'\n"
        "  - QUESTION HOOK: 'Stop scrolling if this sounds like you...' / 'Did you know...'\n"
        "  - FORBIDDEN KNOWLEDGE: 'Your [expert] won't tell you this.' / 'Nobody talks about this.'\n"
        "  - BOLD STATEMENT: 'This will get me cancelled but...' / 'I said what I said.'\n"
        "  - SPECIFICITY: '3 things. 15 seconds.' / 'Rs 800. 3 outfits. Wait for #3.'\n"
        "  - FOMO: 'Everyone knows this except you.' / 'This changes everything.'\n\n"
        "1-photo hook reel (PREFERRED — fastest, punchiest): [Hook text] → [Photo] → [Bridge text] → [CTA] = 8s\n"
        "2-photo hook reel: [Hook text] → [Photo 1] → [Bridge] → [Photo 2] → [CTA] = 10s\n"
        "Keep it SHORT. Modern attention span = 8 seconds. 1-2 photos MAX.\n\n"
        "Example: post_type='reel', reel_format='hook_photo', slides=['Full outfit shot in luxury "
        "hotel lobby'], video_text=['This costs Rs 5,000. No, seriously.', "
        "'Can you tell the difference?', 'Send to your fashion friend.']\n\n"
        "Return ONLY a JSON array of {count} objects with these fields:\n"
        "- topic: specific scene (not generic, include location/occasion/PRICE if relevant)\n"
        "- caption: 3-5 lines — scroll-stopping hook first, question in middle, send/share CTA last, "
        "NO hashtags\n"
        "- video_text: array of EXACTLY 3 short text lines (max 8 words each) for ON-SCREEN overlay "
        "in the Reel video. These appear as bold text on the video for viewers watching on mute (85%%). "
        "Line 1 = PATTERN INTERRUPT hook (same energy as caption hook but shorter), "
        "Line 2 = curiosity gap or question (make them NEED to know), "
        "Line 3 = CTA that drives SEND/SAVE action. "
        "Examples: ['Rs 800. 3 outfits. Wait for #3.', 'Which one would you steal?', 'Send to your shopping bestie']\n"
        "- alt_text: descriptive accessibility text for the image (60-120 chars)\n"
        "- youtube_title: catchy YouTube Shorts title under 70 chars — use curiosity gap or number hook\n"
        "- notes: photography direction for image generation (framing, lighting, mood)\n"
        "- post_type: 'reel' | 'carousel' | 'single'\n"
        "- reel_format: 'hook_photo' (ONLY for hook-photo reels, omit for others)\n"
        "- slides: array of 2-3 photo descriptions for hook_photo reels, "
        "or 5-6 scene descriptions for carousels (omit for standard reel/single)\n\n"
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
    """Generate drafts via Gemini API with model rotation."""
    from gemini_helper import generate as gemini_generate

    prompt = _build_gemini_prompt().replace("{count}", str(cfg.draft_count))

    raw_text = gemini_generate(cfg.gemini_api_key, prompt, preferred_model=cfg.gemini_model)
    if not raw_text:
        raise ValueError("All Gemini models rate-limited — cannot generate content")
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

    # --- Viral feature: dual-format companions ---
    # Generate alternate-format versions of some posts (carousel↔reel)
    # scheduled +24h so they publish on different days
    dual_ratio = get_persona().get("content", {}).get("dual_format_ratio", 0)
    if dual_ratio > 0:
        companions: list[dict[str, Any]] = []
        for draft in drafts:
            if random.random() >= dual_ratio:
                continue
            src_type = draft.get("post_type", "reel")
            if src_type == "single":
                continue  # singles don't get companions
            alt_type = "reel" if src_type == "carousel" else "carousel"

            companion = dict(draft)  # shallow copy
            companion_id = next_post_id(existing + drafts + companions)
            companion["id"] = companion_id
            companion["post_type"] = alt_type
            companion["is_reel"] = alt_type == "reel"
            companion["image_url"] = ""
            companion["video_url"] = None

            # Schedule +24h from original (different day)
            src_slot = now + timedelta(hours=4 * (drafts.index(draft) + 1))
            companion["scheduled_at"] = format_utc(src_slot + timedelta(hours=24))

            # Tag as dual-format pair
            src_topic = draft.get("topic", "")[:40]
            companion["notes"] = f"dual_format:{src_type}->{alt_type} | {companion.get('notes', '')}"
            draft["notes"] = f"dual_format:{src_type} | {draft.get('notes', '')}"

            # Carousel companions need slide descriptions
            if alt_type == "carousel" and not companion.get("slides"):
                caption_lines = str(companion.get("caption", "")).split("\n")
                companion["slides"] = [
                    f"Hook slide: {caption_lines[0] if caption_lines else src_topic}",
                    f"Key point: {src_topic}",
                    "Detail or example",
                    "Supporting visual",
                    f"CTA slide: {caption_lines[-1] if caption_lines else 'Save this.'}",
                ]
            # Reel companions drop slides
            if alt_type == "reel":
                companion.pop("slides", None)

            companions.append(companion)

        if companions:
            log.info("Created %d dual-format companions", len(companions))
            drafts.extend(companions)

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
