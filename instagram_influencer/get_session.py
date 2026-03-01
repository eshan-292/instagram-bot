#!/usr/bin/env python3
"""Simple script to get Instagram session and export as base64.

Two modes:
  1. Browser cookie (easiest — no login needed):
     python get_session.py sat1

  2. Username/password (may trigger challenges):
     python get_session.py sat1 username password
"""

import base64
import json
import sys
import os
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)

from instagrapi import Client


def from_browser_cookie(persona: str):
    """Get session using a sessionid cookie from Chrome."""
    print(
        "\n"
        "=== GET YOUR SESSION COOKIE ===\n"
        "\n"
        "1. Open Chrome and go to instagram.com\n"
        "2. Log in to your satellite account (@unknown_abyss2368 etc)\n"
        "3. Press F12 (or Cmd+Option+I) to open DevTools\n"
        "4. Click the 'Application' tab at the top\n"
        "5. In the left sidebar: Cookies → https://www.instagram.com\n"
        "6. Find the row named 'sessionid'\n"
        "7. Double-click the Value cell and copy it\n"
        "\n"
    )
    session_id = input("Paste the sessionid value here: ").strip()

    if not session_id:
        print("❌ No sessionid provided")
        sys.exit(1)

    print(f"\nLogging in with session cookie...")
    cl = Client()
    try:
        cl.login_by_sessionid(session_id)
    except Exception as e:
        print(f"❌ Failed: {e}")
        sys.exit(1)

    print(f"✅ Logged in as @{cl.username}!")
    save_session(cl, persona)


def from_password(persona: str, username: str, password: str):
    """Get session using username/password."""
    cl = Client()

    def challenge_handler(username, choice):
        print(f"\n⚠️  Instagram sent a verification code to your {choice.name.lower()}.")
        code = input("Enter the code here: ").strip()
        return code

    cl.challenge_code_handler = challenge_handler

    print(f"Logging in as @{username}...")
    try:
        cl.login(username, password)
    except Exception as e:
        print(f"\n❌ Login failed: {e}")
        print("\nTry the browser cookie method instead:")
        print(f"  python get_session.py {persona}")
        sys.exit(1)

    print("✅ Logged in successfully!")
    save_session(cl, persona)


def save_session(cl: Client, persona: str):
    """Save session file and print base64."""
    data_dir = Path("data") / persona
    data_dir.mkdir(parents=True, exist_ok=True)
    session_file = data_dir / ".ig_session.json"

    settings = cl.get_settings()
    session_file.write_text(json.dumps(settings))

    b64 = base64.b64encode(json.dumps(settings).encode()).decode()

    print(f"\nSession saved to: {session_file}")
    print(f"\n{'='*60}")
    print(f"INSTAGRAM_SESSION_B64_{persona.upper()}:")
    print(f"{'='*60}")
    print(b64)
    print(f"{'='*60}")
    print(f"\n👆 Copy that entire string and paste it as a GitHub secret named:")
    print(f"   INSTAGRAM_SESSION_B64_{persona.upper()}")


def main():
    if len(sys.argv) == 2:
        # Browser cookie mode (easiest)
        from_browser_cookie(sys.argv[1])
    elif len(sys.argv) == 4:
        # Username/password mode
        from_password(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        print("Usage:")
        print("  python get_session.py sat1                          # browser cookie (easiest)")
        print("  python get_session.py sat1 username password        # username/password")
        sys.exit(1)


if __name__ == "__main__":
    main()
