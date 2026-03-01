#!/usr/bin/env python3
"""One-command satellite setup. Logs in via browser cookie, creates .env, sets GitHub secrets.

Usage:
    python get_session.py sat1 username password sessionid gemini_api_key
"""

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

os.chdir(Path(__file__).resolve().parent)

from instagrapi import Client

REPO = "eshan-292/instagram-bot"


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

    # ── Step 1: Log in with session cookie ──────────────────────
    print(f"\n[1/4] Logging in as @{ig_username} with session cookie...")
    cl = Client()
    try:
        cl.login_by_sessionid(session_id)
    except Exception as e:
        print(f"❌ Login failed: {e}")
        print("\nMake sure you're logged into this account on instagram.com and the sessionid is fresh.")
        sys.exit(1)
    print(f"  ✅ Logged in as @{cl.username}")

    # ── Step 2: Save session file + base64 ──────────────────────
    print(f"\n[2/4] Saving session...")
    data_dir = Path("data") / persona
    data_dir.mkdir(parents=True, exist_ok=True)
    session_file = data_dir / ".ig_session.json"

    settings = cl.get_settings()
    session_file.write_text(json.dumps(settings))
    session_b64 = base64.b64encode(json.dumps(settings).encode()).decode()
    print(f"  ✅ Session saved to {session_file}")

    # ── Step 3: Create .env content ─────────────────────────────
    print(f"\n[3/4] Creating .env...")
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

    # ── Step 4: Set GitHub secrets ──────────────────────────────
    print(f"\n[4/4] Setting GitHub secrets...")
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
        print(f"\n  Manually set these GitHub secrets:")
        print(f"  {secret_session} = {session_b64[:40]}...")
        print(f"  {secret_dotenv} = (the .env content above)")
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
