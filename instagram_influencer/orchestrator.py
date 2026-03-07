#!/usr/bin/env python3
"""Main pipeline: generate → images → video → promote → publish (IG + YouTube)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from config import (DEFAULT_QUEUE_FILE, GENERATED_IMAGES_DIR, REFERENCE_DIR,
                    SESSION_FILE, Config, load_config, setup_logging)
from engagement import run_engagement, run_session
from generator import generate_content
from image import fill_image_urls
from persona import get_persona
from publisher import publish, _get_client, ChallengeAbort
from video import convert_posts_to_video
from post_queue import (
    find_eligible,
    format_utc,
    parse_scheduled_at,
    publishable_count,
    read_queue,
    status_counts,
    write_queue,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Repost system — reuse old posted images with fresh hooks when queue is empty
# ---------------------------------------------------------------------------

REPOST_MIN_AGE_DAYS = 7  # Don't repost content younger than this


def _find_oldest_repostable(posts: list[dict[str, Any]]) -> tuple[int, dict[str, Any]] | None:
    """Find the oldest posted entry with valid images for reposting.

    Picks the oldest post (by posted_at) that:
      - Has status "posted"
      - Has valid image files still on disk
      - Was posted >= REPOST_MIN_AGE_DAYS ago
      - Is not itself a repost (avoids infinite repost chains)
    """
    now = datetime.now(timezone.utc)
    oldest: tuple[int, dict[str, Any]] | None = None
    oldest_dt: datetime | None = None

    for idx, item in enumerate(posts):
        if str(item.get("status", "")).strip().lower() != "posted":
            continue
        # Skip reposts to avoid chains
        if str(item.get("notes", "")).startswith("repost:"):
            continue
        # Must have images on disk
        carousel_images = item.get("carousel_images") or []
        image_url = str(item.get("image_url", "")).strip()
        has_images = False
        if carousel_images and all(os.path.exists(str(p)) for p in carousel_images):
            has_images = True
        elif image_url and os.path.exists(image_url):
            has_images = True
        if not has_images:
            continue
        # Must be old enough
        posted_at = parse_scheduled_at(item.get("posted_at"))
        if posted_at and (now - posted_at).days < REPOST_MIN_AGE_DAYS:
            continue
        # Track oldest
        if oldest is None or (posted_at and (oldest_dt is None or posted_at < oldest_dt)):
            oldest = (idx, item)
            oldest_dt = posted_at

    return oldest



# ---------------------------------------------------------------------------
# Hardcoded viral repost content — on-screen text + caption per persona.
# Each entry: video_text=[hook, bridge, cta], caption=str
# These are image-agnostic so they work on ANY reposted photo.
# ---------------------------------------------------------------------------
_REPOST_CONTENT: dict[str, list[dict[str, Any]]] = {
    "aryan": [
        {
            "video_text": ["Your gym crush trains like this.", "Would you survive this?", "Send to your gym partner."],
            "caption": "Your gym crush trains like this.\nMost people quit in week 2. Still here.\nCould you keep up?\nSend this to your gym buddy — dare them.",
        },
        {
            "video_text": ["I wasted 2 years on this.", "Nobody warned me.", "Save this. Seriously."],
            "caption": "I wasted 2 years doing this wrong.\nOne fix changed everything.\nWhat's the worst gym advice you got?\nSave this before you make the same mistake.",
        },
        {
            "video_text": ["Rs 100 vs Rs 1000 protein.", "Same results?", "Comment your pick."],
            "caption": "Rs 100 vs Rs 1000 protein.\nI tested both. The results will surprise you.\nWhich do you use?\nSend to the friend who wastes money on supplements.",
        },
        {
            "video_text": ["Your trainer won't show this.", "Free. No equipment.", "Screenshot this now."],
            "caption": "Your trainer won't show you this.\nBecause it's free and it works.\nWhy pay when this exists?\nScreenshot and try tomorrow morning.",
        },
        {
            "video_text": ["Day 1 vs Day 365.", "Same guy. Different beast.", "Tag someone who needs this."],
            "caption": "Day 1 vs Day 365.\nSame mirror. Different person staring back.\nCould you commit for a year?\nTag someone who keeps saying 'Monday se start karunga'.",
        },
        {
            "video_text": ["This exercise is killing your gains.", "Stop immediately.", "Share before it's too late."],
            "caption": "This exercise is destroying your progress.\nI did it for months. Zero results.\nAre you making this mistake?\nSend to your gym partner before they hurt themselves.",
        },
        {
            "video_text": ["5 AM. No alarm needed.", "Discipline hits different.", "Send to your lazy friend."],
            "caption": "5 AM. Eyes open. No alarm.\nWhen discipline becomes habit, motivation becomes irrelevant.\nWhat time do you train?\nSend to the friend who snoozes 10 times.",
        },
        {
            "video_text": ["Skinny to strong in 180 days.", "No steroids. No shortcuts.", "Save this transformation."],
            "caption": "Skinny to strong. 180 days.\nNo steroids. No shortcuts. Just showing up.\nThink you could do it?\nSave this as your daily reminder.",
        },
        {
            "video_text": ["Your push-up is 100% wrong.", "Here's the proof.", "Send to your gym bro."],
            "caption": "Your push-up is completely wrong.\n99% of people make this mistake.\nDid you know this?\nSend to your gym bro — watch them get defensive.",
        },
        {
            "video_text": ["Indian diet. 150g protein.", "No supplements needed.", "Save this meal plan."],
            "caption": "Indian food. 150g protein. Zero supplements.\nDaal, paneer, eggs. That's it.\nStill think you need imported whey?\nSave this — your wallet will thank you.",
        },
        {
            "video_text": ["3 exercises. 15 minutes.", "No gym required.", "Try this tonight."],
            "caption": "3 exercises. 15 minutes. No gym.\nYour excuse just expired.\nWould you try this at home?\nSend to someone who says they don't have time.",
        },
        {
            "video_text": ["Biggest mistake in every gym.", "I see it daily.", "Stop doing this."],
            "caption": "I see this mistake in every gym. Every single day.\nNobody corrects them.\nAre you doing this?\nTag your gym partner — one of you is guilty.",
        },
        {
            "video_text": ["Creatine truth nobody tells you.", "Is it worth it?", "Comment yes or no."],
            "caption": "The creatine truth nobody tells you.\nI spent Rs 3000 to find out.\nDo you take creatine?\nComment YES or NO — let's settle this.",
        },
        {
            "video_text": ["Your legs are embarrassing.", "Skip leg day one more time.", "I dare you."],
            "caption": "Your legs are embarrassing.\nChicken legs and a massive chest is not a physique.\nDo you skip leg day?\nSend this to the friend who only trains arms.",
        },
        {
            "video_text": ["This physique took 6 months.", "Not 6 years.", "Here's how."],
            "caption": "This physique took 6 months. Not 6 years.\nConsistency beats intensity every time.\nWould you trade 6 months of discipline?\nSave this — come back in 180 days.",
        },
    ],
    "maya": [
        {
            "video_text": ["This outfit costs Rs 800.", "You'd never guess.", "Send to your bestie."],
            "caption": "This entire outfit? Rs 800.\nLooking expensive is a skill, not a salary.\nCould you tell it was budget?\nSend to your bestie who says she has nothing to wear.",
        },
        {
            "video_text": ["Delete half your wardrobe.", "You only need 10 pieces.", "Save this list."],
            "caption": "Delete half your wardrobe.\nYou're wearing 20% of it anyway.\nHow many pieces do you actually wear?\nSave this — your closet needs this intervention.",
        },
        {
            "video_text": ["Stop buying Zara basics.", "They fall apart.", "Here's what to buy instead."],
            "caption": "Stop buying Zara basics.\n2 washes and it's done.\nWhere do you shop for basics?\nSend to your friend who buys a new Zara haul every month.",
        },
        {
            "video_text": ["One kurta. Five outfits.", "No new shopping needed.", "Screenshot all 5."],
            "caption": "One kurta. Five completely different vibes.\nYour wardrobe has more potential than you think.\nWhich style is your vibe?\nScreenshot this for your next outfit crisis.",
        },
        {
            "video_text": ["Rs 1500. Full look.", "Looking expensive is free.", "Tag your shopping buddy."],
            "caption": "Rs 1500. Full look. Head to toe.\nExpensive taste doesn't need an expensive budget.\nWould you wear this?\nTag your shopping buddy — you're going this weekend.",
        },
        {
            "video_text": ["Your bestie styled you.", "POV: she snapped.", "Send this to her."],
            "caption": "POV: your bestie finally styled you.\nAnd she absolutely destroyed it.\nWho's your go-to stylist friend?\nSend this to her — she deserves the credit.",
        },
        {
            "video_text": ["This thrift find? Rs 300.", "Colaba magic.", "Comment your best thrift find."],
            "caption": "This entire piece? Rs 300. Colaba Causeway.\nMumbai streets > any mall in this country.\nWhat's your best thrift find?\nComment the price — let's see who won.",
        },
        {
            "video_text": ["3 outfits. 1 suitcase.", "Travel packing hack.", "Save for your next trip."],
            "caption": "3 outfits. 1 suitcase. Zero outfit panics.\nTravel packing is an art form.\nAre you an overpacker?\nSave this for your next trip — thank me later.",
        },
        {
            "video_text": ["Mumbai monsoon outfit.", "Cute AND waterproof.", "Your rainy day saviour."],
            "caption": "Monsoon but make it fashion.\nBecause Mumbai rains don't care about your outfit.\nHow do you dress for monsoon?\nSend to the friend who wears white in July.",
        },
        {
            "video_text": ["Styling mom's old saree.", "2024 version hits different.", "Tag your mom."],
            "caption": "Styled my mom's old saree. Her jaw dropped.\nVintage is not old — it's iconic.\nHave you tried your mom's wardrobe?\nTag your mom — show her this.",
        },
        {
            "video_text": ["This colour is your personality.", "Choose wisely.", "Comment yours."],
            "caption": "Your outfit colour says everything about you.\nBlack = don't talk to me. Yellow = chaos energy.\nWhich colour is YOU?\nComment your go-to colour — let's psychoanalyse you.",
        },
        {
            "video_text": ["College to cafe to date.", "Same outfit. 3 vibes.", "Save this hack."],
            "caption": "College. Cafe. Date night. Same outfit.\n3 vibes, zero wardrobe changes.\nCould you pull this off?\nSave this for those 3-plan days.",
        },
        {
            "video_text": ["5 things to never wear.", "I'm sorry but no.", "Send to that friend."],
            "caption": "5 things I'm begging you to stop wearing.\nNo hate. Just facts.\nAre you guilty of any?\nSend to the friend who needs a gentle intervention.",
        },
        {
            "video_text": ["Airport look under Rs 3000.", "Comfortable AND cute.", "Screenshot this."],
            "caption": "Airport look. Under Rs 3000.\nBecause you never know who's watching at departures.\nWhat's your airport uniform?\nScreenshot this for your next flight.",
        },
        {
            "video_text": ["I wore this to work.", "HR said nothing.", "Would you risk it?"],
            "caption": "Wore this to work. HR said nothing.\nThe line between bold and boardroom is thinner than you think.\nWould you risk this outfit?\nSend to your work bestie — dare her.",
        },
    ],
    "rhea": [
        {
            "video_text": ["Your workout is useless.", "Here's the truth.", "Save this."],
            "caption": "Your workout is useless.\nHarsh? Yes. True? Also yes.\nAre you making this mistake?\nSave this — fix it before your next session.",
        },
        {
            "video_text": ["She's not lucky.", "She's consistent.", "That's the difference."],
            "caption": "She's not lucky. She's consistent.\nConsistency is boring. Results aren't.\nWhat keeps you going when motivation dies?\nScreenshot this for the days you want to quit.",
        },
        {
            "video_text": ["2500 calories. Still lean.", "Your diet is the problem.", "Not the food."],
            "caption": "2500 calories. Still lean.\nIt was never about eating less. It's about eating right.\nHow many calories do you eat?\nSend to the friend who's scared of carbs.",
        },
        {
            "video_text": ["Stop doing 100 squats.", "It's not working.", "Do this instead."],
            "caption": "Stop doing 100 squats.\nMore reps ≠ more results.\nAre you guilty of this?\nSend to your gym friend who does infinite squats.",
        },
        {
            "video_text": ["4 AM. Gym empty.", "This is where it starts.", "No excuses."],
            "caption": "4 AM. Gym is empty. Just me and discipline.\nMost people are still dreaming about the body they want.\nWhat time do you train?\nSend to someone who needs a wake-up call.",
        },
        {
            "video_text": ["Girls don't need pink dumbbells.", "Train heavy.", "I said what I said."],
            "caption": "Girls don't need pink dumbbells.\nHeavy weights won't make you bulky. That's a myth.\nDo you train heavy?\nTag a girl who needs to hear this.",
        },
        {
            "video_text": ["This one exercise changed my body.", "Took 3 months.", "Try it yourself."],
            "caption": "One exercise. Three months. Completely different body.\nSometimes less is more.\nHave you tried this?\nSave this and try it for 90 days — then thank me.",
        },
        {
            "video_text": ["Your glutes need THIS.", "Not what you're doing.", "Screenshot this routine."],
            "caption": "Your glute routine is probably wrong.\nBooty bands alone won't build anything.\nWhat's your go-to glute exercise?\nScreenshot this routine — your glutes will thank you.",
        },
        {
            "video_text": ["Discipline over motivation.", "Every single time.", "This is the way."],
            "caption": "Discipline over motivation. Every single time.\nMotivation is a feeling. Discipline is a decision.\nWhich drives you more?\nSend to someone who only trains when they 'feel like it'.",
        },
        {
            "video_text": ["130g protein. All vegetarian.", "It's possible.", "Save this meal plan."],
            "caption": "130g protein. Fully vegetarian.\nPaneer, dal, curd, soya chunks. Done.\nStill think you need chicken?\nSave this meal plan — vegetarian gains are real.",
        },
        {
            "video_text": ["POV: you stopped making excuses.", "Day 1 to Day 90.", "Your turn."],
            "caption": "POV: you stopped making excuses.\nDay 1 was the hardest. Day 90 was the proudest.\nWhen did you start?\nTag someone who keeps saying 'tomorrow'.",
        },
        {
            "video_text": ["Cardio is killing your gains.", "Stop running.", "Here's why."],
            "caption": "Cardio is killing your gains.\n45 minutes on the treadmill ≠ results.\nDo you do too much cardio?\nSend to the friend who runs for an hour daily.",
        },
        {
            "video_text": ["3 moves. 12 minutes.", "Better than your 1-hour session.", "Prove me wrong."],
            "caption": "3 moves. 12 minutes. Done.\nBetter than your 1-hour session.\nDon't believe me? Try it.\nSend to someone who says they don't have time.",
        },
        {
            "video_text": ["The glow-up nobody talks about.", "It's not what you think.", "This changes everything."],
            "caption": "The real glow-up nobody talks about.\nIt's not the body. It's the discipline behind it.\nWhat changed YOU the most?\nSend to someone going through their glow-up.",
        },
        {
            "video_text": ["Your form is embarrassing.", "Fix it now.", "Send to your gym partner."],
            "caption": "Your form is embarrassing. Sorry not sorry.\nBad form = zero results + injury.\nHave you checked your form lately?\nSend to your gym partner — one of you needs this.",
        },
    ],
    "sofia": [
        {
            "video_text": ["This costs more than your rent.", "Still worth it.", "Send to someone with taste."],
            "caption": "This costs more than your rent.\nAnd I'd buy it again.\nWould you spend this much on one piece?\nSend to someone with expensive taste.",
        },
        {
            "video_text": ["Not everyone's invited.", "That's the point.", "Save this look."],
            "caption": "Not everyone's invited.\nLuxury isn't about showing off. It's about knowing your worth.\nDo you dress for yourself or others?\nSave this — elegance is a lifestyle.",
        },
        {
            "video_text": ["Old money vs new money.", "One screams. One whispers.", "Which are you?"],
            "caption": "Old money whispers. New money screams.\nLogos everywhere? That's not wealth. That's insecurity.\nWhich side are you on?\nSend to someone who needs this lesson.",
        },
        {
            "video_text": ["Rich vs looking rich.", "Know the difference.", "Most people don't."],
            "caption": "Rich vs looking rich.\nOne wears logos. The other wears confidence.\nCan you tell the difference?\nTag someone who gets confused.",
        },
        {
            "video_text": ["Penthouse mornings.", "Mumbai skyline.", "You can look but not touch."],
            "caption": "Penthouse mornings. Mumbai skyline. Coffee.\nThis is not a vacation. This is Tuesday.\nWhat does your morning look like?\nShare this with someone who deserves this life.",
        },
        {
            "video_text": ["She walked in. Everyone stared.", "It's the outfit.", "No. It's the energy."],
            "caption": "She walked in. Everyone stared.\nThey thought it was the outfit. It wasn't.\nIt's never the clothes — it's the woman wearing them.\nSend to the woman who commands every room.",
        },
        {
            "video_text": ["All black. All power.", "No colour needed.", "This is elegance."],
            "caption": "All black. All power.\nWhen you're the statement, you don't need colour.\nCould you pull this off?\nTag someone who only wears black.",
        },
        {
            "video_text": ["From Russia with style.", "Moscow to Mumbai.", "Different city. Same standards."],
            "caption": "From Russia with style.\nMoscow taught me elegance. Mumbai taught me boldness.\nWhich city is more stylish?\nComment — I want to hear this debate.",
        },
        {
            "video_text": ["This is real luxury.", "Not the logo. The quality.", "You either get it or you don't."],
            "caption": "This is real luxury.\nNo logos. No labels. Just quality you can feel.\nDo you know the difference?\nSend to someone who thinks Gucci = luxury.",
        },
        {
            "video_text": ["Rs 5000 looks Rs 50,000.", "The trick is confidence.", "Save this formula."],
            "caption": "Rs 5000 but looks Rs 50,000.\nLuxury isn't a price tag — it's a formula.\nWant to know the secret?\nSave this — your next outfit needs this energy.",
        },
        {
            "video_text": ["Main character energy.", "Every single day.", "Not everyone can handle it."],
            "caption": "Main character energy. Every single day.\nSome people blend in. I was never built for that.\nDo you walk into rooms or disappear in them?\nSend to the main character in your life.",
        },
        {
            "video_text": ["Quiet luxury.", "The ones who know, know.", "If you know, save this."],
            "caption": "Quiet luxury.\nThe ones who know, know. No explanation needed.\nDo you dress loud or quiet?\nSave this — this is the only aesthetic that ages well.",
        },
        {
            "video_text": ["Elegance is non-negotiable.", "Born or learned?", "Comment your take."],
            "caption": "Elegance is non-negotiable.\nSome say you're born with it. I say you choose it daily.\nIs elegance born or learned?\nComment — this debate never ends.",
        },
        {
            "video_text": ["Mumbai at night.", "Heels on. Standards higher.", "This city deserves effort."],
            "caption": "Mumbai at night. Heels on. Standards higher.\nThis city rewards those who show up looking like they mean it.\nWhat's your Mumbai night uniform?\nSend to your going-out partner.",
        },
        {
            "video_text": ["Designer vs dupe.", "Can you tell?", "Comment which is which."],
            "caption": "Designer vs dupe. One costs 50x more.\nCan you actually tell the difference?\nWhich one would you pick?\nComment 1 or 2 — let's see who has the eye.",
        },
    ],
}


def _create_repost(posts: list[dict[str, Any]], source: dict[str, Any],
                   cfg: Config) -> dict[str, Any]:
    """Create a fresh hook-photo reel from an old posted entry's images.

    Reuses original images but generates completely new:
      - video_text (hook/bridge/CTA from hardcoded viral sets)
      - caption (matched to video_text — no Gemini needed)
      - video (re-rendered with new text frames)
    """
    persona = get_persona()
    persona_id = str(persona.get("id", "")).strip().lower()

    # Pick a random hardcoded viral content set for this persona
    content_sets = _REPOST_CONTENT.get(persona_id, [])
    if content_sets:
        chosen_set = random.choice(content_sets)
        video_text = list(chosen_set["video_text"])
        new_caption = str(chosen_set["caption"])
    else:
        # Fallback for personas without hardcoded sets
        content = persona.get("content", {})
        vt_hooks = content.get("video_text_hooks", [])
        hook = random.choice(vt_hooks) if vt_hooks else "Wait for it."
        bridges = [
            "Can you guess?", "Wait. It gets better.", "Which one wins?",
            "Would you try this?", "The secret nobody shares.",
        ]
        ctas = [
            "Send to your bestie.", "Save this. Trust me.",
            "Tag who needs this.", "Screenshot this now.",
        ]
        video_text = [hook, random.choice(bridges), random.choice(ctas)]
        topic = str(source.get("topic", "")).strip()
        new_caption = f"{hook}\n{topic}.\nWould you try this?\nSend to someone who needs to see this."

    # Build repost entry
    from persona import next_post_id
    post_id = next_post_id(posts)
    topic = str(source.get("topic", "")).strip()

    carousel_images = source.get("carousel_images") or []
    image_url = str(source.get("image_url", "")).strip()

    repost: dict[str, Any] = {
        "id": post_id,
        "status": "draft",
        "topic": topic,
        "caption": new_caption,
        "alt_text": str(source.get("alt_text", "")).strip(),
        "youtube_title": "",
        "video_text": video_text,
        "image_url": image_url,
        "video_url": None,
        "is_reel": True,
        "post_type": "reel",
        "reel_format": "hook_photo",
        "scheduled_at": format_utc(datetime.now(timezone.utc)),
        "notes": f"repost:{source.get('id', 'unknown')} | fresh hooks",
    }

    # Reuse images
    if carousel_images:
        valid = [str(p) for p in carousel_images if os.path.exists(str(p))]
        repost["carousel_images"] = valid or [image_url]
        repost["image_url"] = valid[0] if valid else image_url
    elif image_url:
        repost["carousel_images"] = [image_url]

    return repost


def _should_generate(posts: list[dict[str, Any]], cfg: Config) -> bool:
    return publishable_count(posts) < cfg.min_ready_queue


def _promote_drafts(posts: list[dict[str, Any]], cfg: Config) -> int:
    now = datetime.now(timezone.utc)
    interval = timedelta(minutes=cfg.schedule_interval_minutes)
    next_slot = now + timedelta(minutes=cfg.schedule_lead_minutes)

    for item in posts:
        dt = parse_scheduled_at(item.get("scheduled_at"))
        if dt and dt >= next_slot:
            next_slot = dt + interval

    promoted = 0
    for item in posts:
        if str(item.get("status", "")).strip().lower() != "draft":
            continue
        if not item.get("caption"):
            continue
        post_type = str(item.get("post_type", "reel")).lower()
        has_media = (
            (post_type == "carousel" and item.get("carousel_images"))
            or item.get("image_url")
            or item.get("video_url")
        )
        if not has_media:
            continue
        item["status"] = cfg.auto_promote_status
        dt = parse_scheduled_at(item.get("scheduled_at"))
        if dt is None or dt <= now:
            item["scheduled_at"] = format_utc(next_slot)
            next_slot += interval
        promoted += 1
    return promoted


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Hashtag injection — appended to caption at publish time
# ---------------------------------------------------------------------------
# 2026 algorithm: 3-5 targeted hashtags > 30 generic ones.
# Instagram now treats captions as keyword search — front-loaded topic keywords
# carry more reach weight than hashtag spraying.

# Core hashtag pool — pick 3-5 per post for variety without spam signals
def _hashtag_pool():
    """Return broad + medium + niche hashtags as a combined pool."""
    h = get_persona().get("hashtags", {})
    return h.get("broad", []) + h.get("medium", []) + h.get("niche", [])


# Carousel-specific tags (drives saves — the highest-weight signal)
def _carousel_tags():
    return get_persona().get("hashtags", {}).get("carousel", [])


def _keyword_phrases():
    return get_persona().get("hashtags", {}).get("keyword_phrases", [])


# Cross-platform promotion CTAs — drives YouTube subscribers from IG
def _cross_promo_ctas():
    return get_persona().get("cross_promo", {}).get("youtube_ctas", [])


def _get_hashtags():
    h = get_persona().get("hashtags", {})
    return {
        "brand": h.get("brand", []),
        "broad": h.get("broad", []),
        "medium": h.get("medium", []),
        "niche": h.get("niche", []),
        "carousel": h.get("carousel", []),
        "keyword_phrases": h.get("keyword_phrases", []),
    }

def _fetch_trending_hashtags(cfg: Config | None = None) -> list[str]:
    """Return ~20 currently-trending Instagram hashtags via Gemini.

    Results are cached per day in trending_hashtags_cache.json so we only
    make one Gemini call per persona per day.  Falls back to a hardcoded
    list if Gemini is unavailable or returns garbage.
    """
    FALLBACK = [
        "trending", "viral", "explorepage", "foryou", "reels",
        "instagood", "photooftheday", "fyp", "viralpost", "trendingnow",
        "explore", "instagram", "reelsinstagram", "instadaily", "love",
        "aesthetic", "mood", "ootd", "reelsofinstagram", "lifestyle",
    ]

    from persona import persona_data_dir
    cache_path = persona_data_dir() / "trending_hashtags_cache.json"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Check daily cache
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                cached = json.load(f)
            if cached.get("date") == today and isinstance(cached.get("tags"), list):
                log.debug("Using cached trending hashtags (%d tags)", len(cached["tags"]))
                return cached["tags"]
        except (json.JSONDecodeError, OSError):
            pass

    # Need Gemini to fetch fresh trending tags
    if cfg is None or not cfg.gemini_api_key:
        log.debug("No Gemini API key — using fallback trending hashtags")
        return FALLBACK

    from gemini_helper import generate

    prompt = (
        "List exactly 20 currently-trending Instagram hashtags for March 2026. "
        "Include a mix of: viral/general hashtags, lifestyle/aesthetic hashtags, "
        "engagement-bait hashtags (like 'fyp', 'viral'), and broad discovery hashtags. "
        "Return ONLY the hashtags as a comma-separated list WITHOUT the # symbol. "
        "Example format: trending, viral, explorepage, fyp, instagood\n"
        "Do not include any other text, explanations, or numbering."
    )

    try:
        raw = generate(cfg.gemini_api_key, prompt, cfg.gemini_model)
        if not raw:
            raise ValueError("Empty Gemini response")

        # Parse comma-separated tags, strip whitespace and # symbols
        tags = [
            t.strip().lstrip("#").replace(" ", "").lower()
            for t in raw.replace("\n", ",").split(",")
            if t.strip()
        ]
        # Filter out garbage (too long, contains non-alphanum, empty)
        tags = [t for t in tags if t and len(t) <= 30 and t.isalnum()]

        if len(tags) < 5:
            log.warning("Gemini returned too few trending tags (%d), using fallback", len(tags))
            tags = FALLBACK
        else:
            tags = tags[:25]  # cap at 25 in case Gemini over-produces
            log.info("Fetched %d trending hashtags via Gemini", len(tags))

        # Cache for the day
        try:
            with open(cache_path, "w") as f:
                json.dump({"date": today, "tags": tags}, f)
        except OSError as exc:
            log.warning("Failed to cache trending hashtags: %s", exc)

        return tags

    except Exception as exc:
        log.warning("Trending hashtag fetch failed: %s — using fallback", exc)
        return FALLBACK


def _get_series_hashtag(item: dict[str, Any]) -> str | None:
    """Extract series hashtag from post notes if it's a series post."""
    notes = str(item.get("notes", ""))
    if not notes.startswith("series:"):
        return None
    # notes format: "series:Friday Fits | ..."
    # Look up the series name in persona config to find the hashtag
    series_name = notes.split("|")[0].replace("series:", "").strip()
    for s in get_persona().get("content_series", []):
        if s.get("name", "").lower() == series_name.lower():
            return s.get("series_hashtag", "")
    return None


def _build_hashtags(caption: str, topic: str, post_type: str = "reel",
                    youtube_enabled: bool = False,
                    cfg: Config | None = None,
                    item: dict[str, Any] | None = None) -> tuple[str, str]:
    """Append 3-5 hashtags to caption; return (caption, first_comment_hashtags).

    Caption gets 3-5 targeted hashtags (pyramid strategy).
    First comment fills up to 30 TOTAL hashtags (caption + comment) with a
    mix of ~60% niche/persona tags + ~40% trending tags for max discovery.
    """
    h = _get_hashtags()
    # Caption hashtags: 1 brand + 1 broad + 1-2 medium + 1 niche = 3-5 total
    caption_tags = list(h["brand"])  # brand (always)

    # Inject series-specific hashtag if this is a series post
    if item:
        series_tag = _get_series_hashtag(item)
        if series_tag:
            caption_tags.append(series_tag)

    broad, medium, niche = h["broad"], h["medium"], h["niche"]
    carousel = h["carousel"]

    if post_type == "carousel":
        caption_tags.extend(random.sample(carousel, min(3, len(carousel))))
    else:
        if broad: caption_tags.append(random.choice(broad))
        if medium: caption_tags.extend(random.sample(medium, min(2, len(medium))))
        if niche: caption_tags.append(random.choice(niche))

    caption_tags = caption_tags[:5]
    caption_count = len(caption_tags)

    # One keyword phrase (drives search discovery)
    kw = h["keyword_phrases"]
    keyword = random.choice(kw) if kw else ""
    hashtag_block = " ".join(f"#{t}" for t in caption_tags)

    result = f"{caption}\n.\n{keyword}\n.\n{hashtag_block}" if keyword else f"{caption}\n.\n{hashtag_block}"

    # Cross-platform promo on ~40% of posts when YouTube is enabled
    ctas = _cross_promo_ctas()
    if youtube_enabled and ctas and random.random() < 0.40:
        promo = random.choice(ctas)
        result += f"\n.\n{promo}"

    # First comment: fill up to 30 TOTAL hashtags (Instagram limit)
    # Mix ~60% niche/persona tags + ~40% trending for maximum exposure
    MAX_TOTAL = 30
    slots = MAX_TOTAL - caption_count  # how many we can fit in first comment

    # Pool 1: persona niche/medium/broad/carousel tags (not already in caption)
    niche_pool = [t for t in (broad + medium + niche + carousel) if t not in caption_tags]
    random.shuffle(niche_pool)

    # Pool 2: trending hashtags (even if irrelevant — max exposure)
    trending = _fetch_trending_hashtags(cfg)
    # Remove any overlap with caption or niche pool
    used = set(caption_tags) | set(niche_pool)
    trending_pool = [t for t in trending if t not in used]
    random.shuffle(trending_pool)

    # Fill: ~60% niche, ~40% trending
    niche_slots = int(slots * 0.6)
    trending_slots = slots - niche_slots

    picked_niche = niche_pool[:niche_slots]
    picked_trending = trending_pool[:trending_slots]

    # If either pool is short, fill from the other
    combined = picked_niche + picked_trending
    if len(combined) < slots:
        remaining_niche = [t for t in niche_pool if t not in combined]
        remaining_trending = [t for t in trending_pool if t not in combined]
        filler = remaining_niche + remaining_trending
        combined.extend(filler[:slots - len(combined)])

    # Shuffle so niche/trending are interleaved naturally
    random.shuffle(combined)

    first_comment = ""
    if combined:
        first_comment = ".\n" + " ".join(f"#{t}" for t in combined)

    return result, first_comment


# ---------------------------------------------------------------------------
# YouTube Shorts publishing
# ---------------------------------------------------------------------------

def _publish_to_youtube(cfg: Config, item: dict[str, Any], idx: int,
                        posts: list[dict[str, Any]], queue_file: str) -> None:
    """Publish a post to YouTube Shorts alongside Instagram.

    Uses the YouTube-optimized 9:16 video if available, otherwise falls back
    to the Instagram 4:5 video.
    """
    if not cfg.youtube_enabled:
        return

    from youtube_publisher import publish_short, post_creator_comment, generate_pin_comment

    # Prefer YouTube-format video, fall back to Instagram video
    yt_video = str(item.get("youtube_video_url") or "").strip()
    ig_video = str(item.get("video_url") or "").strip()
    video_path = yt_video or ig_video

    if not video_path:
        log.debug("No video for YouTube upload of %s", item.get("id"))
        return

    topic = str(item.get("topic", ""))
    caption = str(item.get("caption", ""))
    youtube_title = str(item.get("youtube_title", "")).strip() or None
    thumbnail = str(item.get("image_url", "")) or None

    try:
        yt_id = publish_short(video_path, topic, caption,
                              thumbnail_path=thumbnail,
                              custom_title=youtube_title)
        if yt_id:
            posts[idx]["youtube_video_id"] = yt_id
            posts[idx]["youtube_posted_at"] = _utc_now_iso()
            write_queue(queue_file, posts)
            log.info("Published to YouTube: %s → https://youtube.com/shorts/%s",
                     item.get("id"), yt_id)

            # Auto-pin a discussion-sparking creator comment (drives 30%+ more replies)
            try:
                pin_text = generate_pin_comment(topic, caption)
                pin_id = post_creator_comment(yt_id, pin_text)
                if pin_id:
                    posts[idx]["youtube_pin_comment_id"] = pin_id
                    write_queue(queue_file, posts)
            except Exception as pin_exc:
                log.debug("Pin comment failed (non-fatal): %s", pin_exc)

        else:
            log.warning("YouTube upload returned no ID for %s", item.get("id"))
    except Exception as exc:
        log.error("YouTube publish failed for %s: %s", item.get("id"), exc)


def _yt_only_publish(cfg: Config, posts: list[dict[str, Any]],
                     queue_file: str, max_posts: int = 1) -> list[str]:
    """Publish to YouTube Shorts independently — no Instagram required.

    Finds the next eligible post(s) (ready/approved with a video) and publishes
    them to YouTube only.  Does NOT change the post status (so the IG workflow
    can still publish it to Instagram later).

    Args:
        max_posts: How many posts to publish in this window (default 1).
                   Research says 2-3 Shorts/day = 3.2x faster subscriber growth.

    Returns list of published YouTube video IDs (for post-publish reply blitz).
    """
    published_yt_ids: list[str] = []

    if not cfg.youtube_enabled:
        log.info("YouTube disabled, skipping yt-publish-only")
        return published_yt_ids

    published = 0
    # Find eligible posts for YouTube (has video, not yet on YT)
    for idx, item in enumerate(posts):
        if published >= max_posts:
            break

        status = str(item.get("status", ""))
        if status not in ("ready", "approved", "posted"):
            continue
        # Skip if already published to YouTube
        if item.get("youtube_video_id"):
            continue
        # Need a video file
        yt_video = str(item.get("youtube_video_url") or "").strip()
        ig_video = str(item.get("video_url") or "").strip()
        if not yt_video and not ig_video:
            continue

        log.info("YT-only publish: found eligible post %s (status=%s)", item.get("id"), status)
        _publish_to_youtube(cfg, item, idx, posts, queue_file)

        # Track published video IDs for post-publish reply blitz
        yt_id = posts[idx].get("youtube_video_id")
        if yt_id:
            published_yt_ids.append(yt_id)
            published += 1

            # Brief pause between uploads (don't spam the API)
            if published < max_posts:
                import time
                time.sleep(random.uniform(5, 15))

    if not published:
        log.info("No eligible posts for YouTube-only publishing")

    return published_yt_ids


def main() -> int:
    # Load .env FIRST so PERSONA is available before any lazy path resolution
    # (argparse defaults trigger str(DEFAULT_QUEUE_FILE) which needs PERSONA)
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ModuleNotFoundError:
        pass

    # CRITICAL: Reset the persona singleton AND lazy paths so they re-read
    # the PERSONA env var from .env.  Module imports may have triggered
    # get_persona() BEFORE load_dotenv(), caching the wrong persona
    # (defaulting to "maya").
    from persona import reset_persona
    reset_persona()
    # Also reset lazy path caches that may have resolved to the wrong persona dir
    DEFAULT_QUEUE_FILE.reset()
    SESSION_FILE.reset()
    REFERENCE_DIR.reset()
    GENERATED_IMAGES_DIR.reset()

    parser = argparse.ArgumentParser(description="Instagram + YouTube bot pipeline")
    parser.add_argument("--queue-file", default=str(DEFAULT_QUEUE_FILE))
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--no-generate", action="store_true")
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--yt-publish-only", action="store_true",
                        help="Publish to YouTube only (skip Instagram)")
    parser.add_argument("--no-engage", action="store_true")
    parser.add_argument("--session", type=str, default=None,
                        help="Run a specific session type (morning/replies/hashtags/explore/"
                             "maintenance/stories/report/yt_engage/yt_replies/yt_full/"
                             "commenter_target/cross_promo/sat_boost/sat_background)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        cfg = load_config()

        # Satellite accounts have a simplified pipeline — engagement only
        # (no content queue, no publishing, no generation)
        # Check BEFORE reading queue since satellites don't have content_queue.json
        from persona import is_satellite
        if is_satellite():
            if args.session:
                from satellite import run_satellite_session
                sat_stats = run_satellite_session(cfg, args.session)
                log.info("Satellite session '%s': %s", args.session, sat_stats)
            else:
                log.info("Satellite mode — no session specified, nothing to do")
            return 0

        posts = read_queue(args.queue_file)
        log.info("Queue: %s", status_counts(posts))

        if args.dry_run:
            chosen = find_eligible(posts)
            if chosen:
                print(json.dumps({k: chosen[1].get(k) for k in
                    ("id", "status", "post_type", "scheduled_at", "caption",
                     "image_url", "carousel_images", "youtube_video_url")}, ensure_ascii=True))
            else:
                print("No eligible posts")
            return 0

        # Step 1: content generation (skipped with --no-generate)
        if not args.no_generate:
            if _should_generate(posts, cfg):
                generate_content(args.queue_file, cfg)
                posts = read_queue(args.queue_file)
                log.info("Post-generation: %s", status_counts(posts))

        # Steps 2-4 always run — they process existing images/drafts
        # even when content generation is skipped.

        # 2. Fill image URLs (scans pending/ for user-placed images)
        updated = fill_image_urls(posts, cfg)
        if updated:
            write_queue(args.queue_file, posts)
            log.info("Filled %d image URLs", updated)

        # 3. Convert images to video (IG Reels + YouTube Shorts)
        video_count = convert_posts_to_video(posts, youtube=cfg.youtube_enabled)
        if video_count:
            write_queue(args.queue_file, posts)
            log.info("Converted %d posts to video", video_count)

        # 4. Promote drafts
        if cfg.auto_promote_drafts:
            promoted = _promote_drafts(posts, cfg)
            if promoted:
                write_queue(args.queue_file, posts)
                log.info("Promoted %d drafts", promoted)

        # 5. Publish next eligible post
        if not args.no_publish:
            if args.yt_publish_only:
                # YouTube-only publishing — independent of Instagram
                # Publish 1 Short per window (conservative — shared quota across personas)
                yt_published_ids = _yt_only_publish(cfg, posts, args.queue_file, max_posts=1)

                # Post-publish reply blitz — reply to early comments within 60 min
                # (critical algorithm signal for YT Shorts distribution)
                if yt_published_ids and cfg.youtube_engagement_enabled:
                    try:
                        from youtube_engagement import run_yt_post_publish_replies
                        blitz_count = run_yt_post_publish_replies(cfg, yt_published_ids)
                        log.info("YT post-publish reply blitz: %d replies", blitz_count)
                    except Exception as blitz_exc:
                        log.debug("Post-publish reply blitz failed (non-fatal): %s", blitz_exc)
            else:
                # Normal flow: Instagram + YouTube
                chosen = find_eligible(posts)
                if chosen is None:
                    # --- Repost fallback: recycle oldest posted images with fresh hooks ---
                    log.info("No eligible posts — checking for repostable content")
                    repostable = _find_oldest_repostable(posts)
                    if repostable:
                        _, source = repostable
                        repost = _create_repost(posts, source, cfg)
                        posts.append(repost)
                        # Convert to video immediately
                        convert_posts_to_video(posts, youtube=cfg.youtube_enabled)
                        # Promote to ready so it publishes this run
                        repost["status"] = cfg.auto_promote_status
                        write_queue(args.queue_file, posts)
                        log.info("Created repost %s from %s with fresh hooks",
                                 repost["id"], source.get("id"))
                        # Re-find — should now pick up the repost
                        chosen = find_eligible(posts)
                    else:
                        log.info("No repostable content found either")

                if chosen is None:
                    log.info("No eligible posts to publish")
                else:
                    idx, item = chosen
                    caption = str(item.get("caption", ""))
                    image_url = str(item.get("image_url", ""))
                    video_url = str(item.get("video_url") or "").strip() or None
                    is_reel = bool(item.get("is_reel", False))
                    post_type = str(item.get("post_type", "reel")).strip().lower()
                    carousel_images = item.get("carousel_images") or None

                    has_media = (
                        (post_type == "carousel" and carousel_images)
                        or image_url
                        or video_url
                    )
                    if not has_media:
                        log.warning("Post %s has no media, skipping", item.get("id"))
                    else:
                        # Inject hashtags (caption + first comment for extra reach)
                        full_caption, first_comment_hashtags = _build_hashtags(
                            caption, str(item.get("topic", "")), post_type,
                            youtube_enabled=cfg.youtube_enabled,
                            cfg=cfg,
                            item=item,
                        )

                        # Publish to Instagram (with alt_text for SEO + accessibility)
                        alt_text = str(item.get("alt_text", "")).strip() or None
                        try:
                            post_id = publish(cfg, full_caption, image_url,
                                              video_url=video_url, is_reel=is_reel,
                                              carousel_images=carousel_images,
                                              post_type=post_type,
                                              alt_text=alt_text,
                                              first_comment=first_comment_hashtags)
                            posts[idx]["status"] = "posted"
                            posts[idx]["posted_at"] = _utc_now_iso()
                            posts[idx]["platform_post_id"] = post_id
                            posts[idx]["publish_error"] = None
                            log.info("Published %s → %s", item.get("id"), post_id)
                        except ChallengeAbort:
                            raise  # Don't catch — abort immediately
                        except Exception as exc:
                            posts[idx]["status"] = "failed"
                            posts[idx]["publish_error"] = str(exc)
                            log.error("Publish failed for %s: %s", item.get("id"), exc)

                        write_queue(args.queue_file, posts)

                        # Publish to YouTube Shorts (non-blocking — IG publish is primary)
                        if posts[idx].get("status") == "posted":
                            _publish_to_youtube(cfg, posts[idx], idx, posts, args.queue_file)

                            # Post-publish engagement burst (first 30 min = algorithmic fate)
                            # Pin CTA comment + story repost + mini engagement burst
                            if cfg.engagement_enabled:
                                try:
                                    from engagement import run_post_publish_burst
                                    pub_cl = _get_client(cfg)
                                    burst_stats = run_post_publish_burst(
                                        pub_cl, cfg,
                                        str(posts[idx].get("platform_post_id", "")),
                                        posts[idx],
                                    )
                                    log.info("Post-publish burst: %s", burst_stats)
                                except Exception as exc:
                                    log.warning("Post-publish burst failed: %s", exc)

        # 6. Engagement (Instagram + YouTube sessions)
        if args.session:
            session_stats = {}
            session_error = None
            try:
                # YouTube-specific sessions
                if args.session.startswith("yt_"):
                    if cfg.youtube_enabled and cfg.youtube_engagement_enabled:
                        from youtube_engagement import run_yt_session
                        session_stats = run_yt_session(cfg, args.session)
                        log.info("YouTube session '%s': %s", args.session, session_stats)
                    else:
                        log.info("YouTube engagement disabled, skipping %s", args.session)
                elif args.session == "cross_promo":
                    from cross_promo import run_cross_promo_engagement
                    from publisher import _get_client as get_cl
                    from rate_limiter import load_log, save_log, LOG_FILE
                    data = load_log(str(LOG_FILE))
                    xp_cl = get_cl(cfg)
                    session_stats = run_cross_promo_engagement(xp_cl, cfg, data)
                    save_log(str(LOG_FILE), data)
                    log.info("Cross-promo session: %s", session_stats)
                else:
                    # Instagram session
                    session_stats = run_session(cfg, args.session)
                    log.info("Session '%s': %s", args.session, session_stats)
            except ChallengeAbort:
                raise  # Don't catch — abort immediately
            except Exception as exc:
                session_error = str(exc)
                log.error("Session '%s' failed: %s", args.session, exc)

            # Send Telegram alert for every session (not just daily report)
            try:
                from report import send_session_alert
                pid = get_persona().get("id", "unknown")
                send_session_alert(pid, args.session, session_stats or {},
                                   error=session_error)
            except Exception:
                pass

        elif not args.no_engage and cfg.engagement_enabled:
            engagement_stats = run_engagement(cfg)
            log.info("Engagement: %s", engagement_stats)

        return 0
    except ChallengeAbort as exc:
        log.error(
            "CHALLENGE ABORT: Instagram requires verification — ALL API calls stopped. "
            "Log into Instagram on your phone to resolve, then re-seed session. "
            "Error: %s", exc
        )
        # Send alert for challenge abort
        try:
            from report import send_session_alert
            persona_id = os.getenv("PERSONA", "unknown")
            send_session_alert(
                persona_id, args.session or "pipeline", {},
                error=f"⚠️ CHALLENGE ABORT: {exc}",
            )
        except Exception:
            pass
        return 1
    except Exception as exc:
        log.error("Pipeline failed: %s", exc)
        # Send alert for pipeline crash
        try:
            from report import send_session_alert
            persona_id = os.getenv("PERSONA", "unknown")
            send_session_alert(persona_id, "pipeline", {},
                               error=str(exc))
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
