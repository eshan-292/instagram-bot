#!/usr/bin/env python3
"""Daily report — generates an end-of-day summary of bot activity.

Sends report to Telegram (if configured) and GitHub Actions step summary.
"""

from __future__ import annotations

import json
import logging
import os
import requests as req
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

LOG_FILE = Path(__file__).resolve().parent / "engagement_log.json"
QUEUE_FILE = Path(__file__).resolve().parent / "content_queue.json"
REPORT_FILE = Path(__file__).resolve().parent / "daily_report.md"

IST = timezone(timedelta(hours=5, minutes=30))


def _load_log() -> dict[str, Any]:
    if not LOG_FILE.exists():
        return {"actions": []}
    try:
        with open(LOG_FILE) as f:
            return json.load(f)
    except Exception:
        return {"actions": []}


def _load_queue() -> list[dict]:
    if not QUEUE_FILE.exists():
        return []
    try:
        with open(QUEUE_FILE) as f:
            data = json.load(f)
        return data.get("posts", [])
    except Exception:
        return []


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def generate_report() -> str:
    """Generate a markdown daily report. Returns the report text."""
    today = _today_str()
    now_ist = datetime.now(IST)
    data = _load_log()
    queue = _load_queue()

    # Count today's actions by type
    counts: dict[str, int] = {}
    for a in data.get("actions", []):
        ts = str(a.get("at", ""))
        if ts.startswith(today):
            t = a.get("type", "unknown")
            counts[t] = counts.get(t, 0) + 1

    # Queue stats
    status_counts: dict[str, int] = {}
    for p in queue:
        s = p.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    # Posts published today
    published_today = []
    for p in queue:
        posted_at = str(p.get("posted_at", ""))
        if posted_at.startswith(today) and p.get("status") == "posted":
            published_today.append(p)

    # Build report
    lines = []
    lines.append(f"# 📊 Daily Report — {now_ist.strftime('%B %d, %Y')}")
    lines.append("")
    lines.append(f"*Generated at {now_ist.strftime('%I:%M %p IST')}*")
    lines.append("")

    # Engagement summary
    lines.append("## Engagement")
    lines.append("")
    lines.append("| Action | Count |")
    lines.append("|--------|-------|")

    action_labels = {
        "likes": "❤️ Likes",
        "comments": "💬 Comments",
        "follows": "➕ Follows",
        "unfollows": "➖ Unfollows",
        "story_views": "👁️ Story Views",
        "story_likes": "⭐ Story Likes",
        "replies": "↩️ Comment Replies",
        "dms": "✉️ Welcome DMs",
        "comment_dms": "💬✉️ Comment Follow-up DMs",
        "stories_posted": "📸 Stories Posted",
        "yt_likes": "▶️ YT Likes",
        "yt_comments": "▶️ YT Comments",
        "yt_replies": "▶️ YT Replies",
    }

    total_actions = 0
    for key, label in action_labels.items():
        count = counts.get(key, 0)
        if count > 0:
            lines.append(f"| {label} | {count} |")
            total_actions += count

    if total_actions == 0:
        lines.append("| (no actions today) | — |")

    lines.append(f"| **Total** | **{total_actions}** |")
    lines.append("")

    # Posts published
    lines.append("## Posts Published Today")
    lines.append("")
    if published_today:
        for p in published_today:
            pid = p.get("id", "?")
            topic = p.get("topic", "")[:60]
            post_id = p.get("platform_post_id", "")
            yt_id = p.get("youtube_video_id", "")
            lines.append(f"- **{pid}**: {topic}")
            if post_id:
                lines.append(f"  - IG: https://instagram.com/p/{post_id}/")
            if yt_id:
                lines.append(f"  - YT: https://youtube.com/shorts/{yt_id}")
    else:
        lines.append("*No posts published today*")
    lines.append("")

    # YouTube channel stats
    try:
        from youtube_publisher import get_channel_stats
        yt_stats = get_channel_stats()
        if yt_stats:
            lines.append("## YouTube Channel")
            lines.append("")
            lines.append(f"- Subscribers: **{yt_stats['subscribers']}**")
            lines.append(f"- Total views: **{yt_stats['total_views']}**")
            lines.append(f"- Videos: **{yt_stats['video_count']}**")
            lines.append("")
    except Exception:
        pass

    # Content pipeline
    lines.append("## Content Pipeline")
    lines.append("")
    lines.append(f"- Draft: {status_counts.get('draft', 0)}")
    lines.append(f"- Approved: {status_counts.get('approved', 0)}")
    lines.append(f"- Posted: {status_counts.get('posted', 0)}")
    lines.append("")

    # Growth estimate
    net_follows = counts.get("follows", 0) - counts.get("unfollows", 0)
    lines.append("## Growth Signals")
    lines.append("")
    lines.append(f"- Net follows sent today: **{net_follows}**")
    lines.append(f"- Engagement actions: **{total_actions}**")

    # Account age
    created = os.getenv("ACCOUNT_CREATED_DATE", "").strip()
    if created:
        try:
            from rate_limiter import warmup_multiplier
            created_dt = datetime.strptime(created, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - created_dt).days
            mult = warmup_multiplier()
            lines.append(f"- Account age: **{age_days} days**")
            lines.append(f"- Warmup multiplier: **{mult}x**")
        except Exception:
            pass

    lines.append("")
    lines.append("---")
    lines.append("*🤖 Generated by Maya Bot*")

    report = "\n".join(lines)
    return report


def _send_telegram(text: str) -> bool:
    """Send a message to Telegram. Returns True on success."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        log.debug("Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    # Telegram has a 4096 char limit per message — split if needed
    chunks = []
    if len(text) <= 4096:
        chunks = [text]
    else:
        # Split at line boundaries
        lines = text.split("\n")
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 4000:
                chunks.append(chunk)
                chunk = line + "\n"
            else:
                chunk += line + "\n"
        if chunk:
            chunks.append(chunk)

    sent = False
    for chunk in chunks:
        try:
            resp = req.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }, timeout=10)
            if resp.status_code == 200:
                sent = True
            else:
                log.warning("Telegram API returned %d: %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            log.warning("Telegram send failed: %s", exc)

    if sent:
        log.info("Report sent to Telegram")
    return sent


def run_daily_report() -> str:
    """Generate and save the daily report. Returns the report text."""
    report = generate_report()

    # Save to file
    try:
        with open(REPORT_FILE, "w") as f:
            f.write(report)
        log.info("Daily report saved to %s", REPORT_FILE)
    except Exception as exc:
        log.warning("Could not save report file: %s", exc)

    # Send to Telegram
    _send_telegram(report)

    # Write to GitHub Actions step summary if available
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a") as f:
                f.write(report + "\n")
            log.info("Report written to GitHub Actions step summary")
        except Exception as exc:
            log.debug("Could not write step summary: %s", exc)

    # Log the report
    log.info("=== DAILY REPORT ===\n%s", report)

    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_daily_report())
