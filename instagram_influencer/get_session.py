#!/usr/bin/env python3
"""One-command satellite setup. Builds session from browser cookie, creates .env, sets GitHub secrets.

Usage:
    python get_session.py sat1 username password sessionid gemini_api_key
"""

import base64
import json
import os
import random
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import unquote

os.chdir(Path(__file__).resolve().parent)

REPO = "eshan-292/instagram-bot"


def _random_uuid():
    return str(uuid.uuid4())


def _build_session(session_id: str) -> dict:
    """Build a minimal instagrapi-compatible session dict from a sessionid cookie.
    No API calls needed — the bot will validate on first run."""

    # Extract user_id from sessionid (the number before the first colon)
    user_id = re.search(r"^\d+", session_id).group()

    # Generate realistic device fingerprint
    android_device_id = f"android-{random.randbytes(8).hex()}"

    return {
        "uuids": {
            "phone_id": _random_uuid(),
            "uuid": _random_uuid(),
            "client_session_id": _random_uuid(),
            "advertising_id": _random_uuid(),
            "android_device_id": android_device_id,
            "request_id": _random_uuid(),
            "tray_session_id": _random_uuid(),
        },
        "mid": "",
        "ig_u_rur": None,
        "ig_www_claim": None,
        "authorization_data": {
            "ds_user_id": user_id,
            "sessionid": session_id,
        },
        "cookies": {},
        "last_login": time.time(),
        "device_settings": {
            "android_version": 34,
            "android_release": "14",
            "dpi": "480dpi",
            "resolution": "1080x2340",
            "manufacturer": "Samsung",
            "device": "dm1q",
            "model": "SM-S911B",
            "cpu": "qcom",
            "app_version": "357.0.0.25.101",
            "version_code": "608720130",
        },
        "user_agent": "Instagram 357.0.0.25.101 Android (34/14; 480dpi; 1080x2340; samsung; SM-S911B; dm1q; qcom; en_IN; 608720130)",
        "country": "IN",
        "country_code": 91,
        "locale": "en_IN",
        "timezone_offset": 19800,
    }


def main():
    if len(sys.argv) != 6:
        print("Usage: python get_session.py <persona> <ig_username> <ig_password> <sessionid> <gemini_api_key>")
        print()
        print("Example:")
        print('  python get_session.py sat1 my_username my_password "48259330886%3Axxx..." AIzaSy...')
        print()
        print("How to get sessionid:")
        print("  1. Log in to the account on instagram.com in Chrome")
        print("  2. Press Cmd+Option+I → Application tab → Cookies → instagram.com")
        print("  3. Copy the 'sessionid' value")
        sys.exit(1)

    persona = sys.argv[1]
    ig_username = sys.argv[2]
    ig_password = sys.argv[3]
    raw_session_id = sys.argv[4]
    gemini_key = sys.argv[5]

    # URL-decode the sessionid (Chrome shows %3A instead of :)
    session_id = unquote(raw_session_id)

    # Validate sessionid format
    if not re.match(r"^\d+:", session_id):
        print(f"❌ Invalid sessionid format. Expected something like '48259330886:xxx...'")
        print(f"   Got: {session_id[:50]}...")
        sys.exit(1)

    # ── Step 1: Build session file ──────────────────────────────
    print(f"\n[1/3] Building session for @{ig_username}...")
    settings = _build_session(session_id)

    data_dir = Path("data") / persona
    data_dir.mkdir(parents=True, exist_ok=True)
    session_file = data_dir / ".ig_session.json"
    session_file.write_text(json.dumps(settings))
    session_b64 = base64.b64encode(json.dumps(settings).encode()).decode()
    print(f"  ✅ Session saved to {session_file}")

    # ── Step 2: Create .env ─────────────────────────────────────
    print(f"\n[2/3] Creating .env...")
    dotenv_content = (
        f"PERSONA={persona}\n"
        f"INSTAGRAM_USERNAME={ig_username}\n"
        f"INSTAGRAM_PASSWORD={ig_password}\n"
        f"GEMINI_API_KEY={gemini_key}\n"
        f"GEMINI_MODEL=gemini-2.5-flash\n"
        f"ENGAGEMENT_ENABLED=true\n"
        f"ENGAGEMENT_COMMENT_ENABLED=true\n"
    )
    print(f"  ✅ .env ready")

    # ── Step 3: Set GitHub secrets ──────────────────────────────
    print(f"\n[3/3] Setting GitHub secrets...")
    secret_session = f"INSTAGRAM_SESSION_B64_{persona.upper()}"
    secret_dotenv = f"DOTENV_{persona.upper()}"

    try:
        # Set session secret
        proc = subprocess.run(
            ["gh", "secret", "set", secret_session, "--repo", REPO, "--body", session_b64],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr)
        print(f"  ✅ {secret_session} set")

        # Set dotenv secret
        proc = subprocess.run(
            ["gh", "secret", "set", secret_dotenv, "--repo", REPO, "--body", dotenv_content],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr)
        print(f"  ✅ {secret_dotenv} set")

    except FileNotFoundError:
        print("  ⚠️  'gh' CLI not found. Install it: brew install gh")
        sys.exit(1)
    except Exception as e:
        print(f"  ❌ Failed to set secrets: {e}")
        sys.exit(1)

    # ── Done ────────────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"🎉 {persona.upper()} is fully set up!")
    print(f"{'='*50}")
    print(f"\nTest it: Go to GitHub → Actions → Satellite {persona[-1]}")
    print(f"  → Run workflow → sat_boost → Run workflow")
    print(f"\nIt will auto-run 6 sessions/day on the cron schedule.")


if __name__ == "__main__":
    main()
