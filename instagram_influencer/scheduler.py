#!/usr/bin/env python3
"""Scheduler — runs the bot with all-day engagement for aggressive growth.

Usage:
    python scheduler.py              # Run continuously (foreground)
    python scheduler.py --install    # Install as macOS LaunchAgent (auto-start)
    python scheduler.py --uninstall  # Remove LaunchAgent

Schedule (all IST):
    7:00 AM  - Morning engagement: light likes + follows (catch early scrollers)
    9:00 AM  - Reply to comments on own posts (algorithm boost)
   10:00 AM  - Story repost (mid-morning)
   11:00 AM  - Hashtag engagement: like/comment/follow/stories
    1:00 PM  - PUBLISH + explore engagement (lunch break)
    2:00 PM  - Story repost (post-lunch)
    3:00 PM  - Hashtag engagement
    5:00 PM  - Maintenance: auto-unfollow + welcome DMs
    6:00 PM  - Story repost (pre-prime time)
    7:00 PM  - PUBLISH + full engagement (prime time — best reach)
    8:30 PM  - Hashtag engagement (still peak hours)
    9:30 PM  - Reply to evening comments
   11:00 PM  - Maintenance: auto-unfollow + welcome DMs
   11:30 PM  - Daily summary report

Total: 14 sessions/day, 2 posts/day, 3 story reposts, ~8 engagement sessions.
This mimics natural human behavior — active throughout the day,
with varied activity types and human-like pauses between sessions.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

VENV_PYTHON = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python"
ORCHESTRATOR = Path(__file__).resolve().parent / "orchestrator.py"
BASE_DIR = Path(__file__).resolve().parent

# IST = UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))

# ----- SCHEDULE -----
# Each entry: (IST hour, IST minute, publish?, session_type)
SCHEDULE = [
    (7,  0,  False, "morning"),      # light likes + follows
    (9,  0,  False, "replies"),      # reply to comments
    (10, 0,  False, "stories"),      # story repost (mid-morning)
    (11, 0,  False, "hashtags"),     # full hashtag engagement
    (13, 0,  True,  "explore"),      # PUBLISH + explore
    (14, 0,  False, "stories"),      # story repost (post-lunch)
    (15, 0,  False, "hashtags"),     # hashtag engagement
    (17, 0,  False, "maintenance"),  # unfollow + DMs
    (18, 0,  False, "stories"),      # story repost (pre-prime time)
    (19, 0,  True,  "full"),         # PUBLISH + full engagement (prime time)
    (20, 30, False, "hashtags"),     # still peak hours
    (21, 30, False, "replies"),      # catch evening comments
    (23, 0,  False, "maintenance"),  # end of day cleanup
    (23, 30, False, "report"),       # daily summary report
]

# How long after scheduled time a session is still valid (minutes)
SESSION_WINDOW = 45


def _ist_now() -> datetime:
    return datetime.now(IST)


def _run(*, publish: bool, session: str) -> None:
    """Run the orchestrator with the given settings."""
    cmd = [str(VENV_PYTHON), str(ORCHESTRATOR)]
    if not publish:
        cmd.append("--no-publish")
    cmd.extend(["--session", session])

    log.info("Running: publish=%s, session=%s", publish, session)
    try:
        result = subprocess.run(
            cmd,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=900,  # 15 min max
        )
        if result.returncode != 0:
            log.error("Failed (exit %d): %s", result.returncode,
                      (result.stderr or "")[-500:])
        else:
            log.info("Session completed successfully")
    except subprocess.TimeoutExpired:
        log.error("Session timed out after 15 minutes")
    except Exception as exc:
        log.error("Session error: %s", exc)


def run_loop() -> None:
    """Main scheduler loop — checks every 10 minutes."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] scheduler: %(message)s",
        datefmt="%H:%M:%S",
    )
    log.info("Scheduler started — %d daily sessions", len(SCHEDULE))
    for h, m, pub, sess in SCHEDULE:
        log.info("  %02d:%02d IST — %s%s", h, m, sess, " + PUBLISH" if pub else "")

    # Track which sessions we've run today: set of (hour, minute, date_str)
    done: set[tuple[int, int, str]] = set()

    while True:
        now = _ist_now()
        today = now.strftime("%Y-%m-%d")

        # Reset at midnight
        done = {(h, m, d) for h, m, d in done if d == today}

        for sched_h, sched_m, publish, session in SCHEDULE:
            key = (sched_h, sched_m, today)
            if key in done:
                continue

            # Check if we're within the session window
            sched_time = now.replace(hour=sched_h, minute=sched_m, second=0, microsecond=0)
            diff = (now - sched_time).total_seconds() / 60
            if 0 <= diff < SESSION_WINDOW:
                log.info("=== Session: %02d:%02d IST — %s%s ===",
                         sched_h, sched_m, session, " + PUBLISH" if publish else "")
                _run(publish=publish, session=session)
                done.add(key)

        # Sleep 10 minutes before checking again
        time.sleep(600)


# ---------------------------------------------------------------------------
# macOS LaunchAgent install/uninstall
# ---------------------------------------------------------------------------

def _plist_name():
    from persona import get_persona
    return get_persona().get("scheduler_plist_name", "com.instagram-bot")

PLIST_NAME = _plist_name()
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_NAME}.plist"


def _install_launchagent() -> None:
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{VENV_PYTHON}</string>
        <string>{Path(__file__).resolve()}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{BASE_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{BASE_DIR / 'scheduler.log'}</string>
    <key>StandardErrorPath</key>
    <string>{BASE_DIR / 'scheduler.log'}</string>
</dict>
</plist>"""
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist)
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
    print(f"Installed and loaded: {PLIST_PATH}")
    print("Bot will now run automatically, even after restart.")
    print(f"Logs: {BASE_DIR / 'scheduler.log'}")


def _uninstall_launchagent() -> None:
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
        PLIST_PATH.unlink()
        print(f"Uninstalled: {PLIST_PATH}")
    else:
        print("Not installed.")


if __name__ == "__main__":
    if "--install" in sys.argv:
        _install_launchagent()
    elif "--uninstall" in sys.argv:
        _uninstall_launchagent()
    else:
        run_loop()
