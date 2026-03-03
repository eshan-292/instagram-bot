#!/usr/bin/env python3
"""Seed Instagram sessions locally — run this on your laptop/phone.

This script logs into Instagram from YOUR device (your IP, your network),
completes any challenges interactively, and exports a session file that
the bot can use in GitHub Actions without triggering new challenges.

Usage:
    python seed_session.py                  # Interactive — pick an account
    python seed_session.py maya             # Seed Maya's session
    python seed_session.py choosewisely moderntruths sofia rhea  # Seed new accounts
    python seed_session.py sat1 sat2 sat3   # Seed multiple satellites
    python seed_session.py --all            # Seed all 9 accounts
    python seed_session.py maya --push      # Seed + push to GitHub secret
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Ensure we can import from instagram_influencer/
SCRIPT_DIR = Path(__file__).resolve().parent
IG_DIR = SCRIPT_DIR / "instagram_influencer"
sys.path.insert(0, str(IG_DIR))

try:
    from instagrapi import Client
    from instagrapi.exceptions import ChallengeRequired
except ImportError:
    print("ERROR: instagrapi not installed. Run: pip install instagrapi")
    sys.exit(1)


# ── Account configs ──────────────────────────────────────────────────────────

ACCOUNTS = {
    "maya": {
        "persona_id": "maya",
        "data_dir": IG_DIR / "data" / "maya",
        "env_file": SCRIPT_DIR / "env-templates" / "maya.env",
        "secret_name": "INSTAGRAM_SESSION_B64",
    },
    "aryan": {
        "persona_id": "aryan",
        "data_dir": IG_DIR / "data" / "aryan",
        "env_file": SCRIPT_DIR / "env-templates" / "aryan.env",
        "secret_name": "INSTAGRAM_SESSION_B64_ARYAN",
    },
    "choosewisely": {
        "persona_id": "choosewisely",
        "data_dir": IG_DIR / "data" / "choosewisely",
        "env_file": SCRIPT_DIR / "env-templates" / "choosewisely.env",
        "secret_name": "INSTAGRAM_SESSION_B64_CHOOSEWISELY",
    },
    "moderntruths": {
        "persona_id": "moderntruths",
        "data_dir": IG_DIR / "data" / "moderntruths",
        "env_file": SCRIPT_DIR / "env-templates" / "moderntruths.env",
        "secret_name": "INSTAGRAM_SESSION_B64_MODERNTRUTHS",
    },
    "sofia": {
        "persona_id": "sofia",
        "data_dir": IG_DIR / "data" / "sofia",
        "env_file": SCRIPT_DIR / "env-templates" / "sofia.env",
        "secret_name": "INSTAGRAM_SESSION_B64_SOFIA",
    },
    "rhea": {
        "persona_id": "rhea",
        "data_dir": IG_DIR / "data" / "rhea",
        "env_file": SCRIPT_DIR / "env-templates" / "rhea.env",
        "secret_name": "INSTAGRAM_SESSION_B64_RHEA",
    },
    "sat1": {
        "persona_id": "sat1",
        "data_dir": IG_DIR / "data" / "sat1",
        "env_file": SCRIPT_DIR / "env-templates" / "sat1.env",
        "secret_name": "INSTAGRAM_SESSION_B64_SAT1",
    },
    "sat2": {
        "persona_id": "sat2",
        "data_dir": IG_DIR / "data" / "sat2",
        "env_file": SCRIPT_DIR / "env-templates" / "sat2.env",
        "secret_name": "INSTAGRAM_SESSION_B64_SAT2",
    },
    "sat3": {
        "persona_id": "sat3",
        "data_dir": IG_DIR / "data" / "sat3",
        "env_file": SCRIPT_DIR / "env-templates" / "sat3.env",
        "secret_name": "INSTAGRAM_SESSION_B64_SAT3",
    },
}


def _load_env(env_file: Path) -> dict[str, str]:
    """Parse a .env file into a dict."""
    env = {}
    if not env_file.exists():
        return env
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def _interactive_challenge_handler(username: str, choice) -> str:
    """Challenge handler that asks the user for the code."""
    print(f"\n{'='*60}")
    print(f"  Instagram challenge for @{username}")
    print(f"  Verification method: {choice}")
    print(f"{'='*60}")
    print(f"\nInstagram sent a verification code via {choice}.")
    print("Check your email/phone and enter the code below.\n")
    code = input("  Enter verification code: ").strip()
    return code


def _create_client() -> Client:
    """Create a Client with realistic Indian device settings."""
    cl = Client()
    cl.delay_range = [2, 6]
    cl.set_locale("en_IN")
    cl.set_country_code(91)
    cl.set_timezone_offset(19800)  # IST = UTC+5:30

    # Interactive challenge handler — lets user complete verification
    cl.challenge_code_handler = _interactive_challenge_handler

    # Realistic device (Samsung Galaxy S24 — common in India)
    # App version must stay current — Instagram blocks old versions with 403.
    cl.set_device({
        "app_version": "418.0.0.51.77",
        "android_version": 34,
        "android_release": "14",
        "dpi": "480dpi",
        "resolution": "1080x2340",
        "manufacturer": "Samsung",
        "device": "dm1q",
        "model": "SM-S911B",
        "cpu": "qcom",
        "version_code": "659489002",
    })
    cl.set_user_agent(
        "Instagram 418.0.0.51.77 Android (34/14; 480dpi; 1080x2340; "
        "samsung; SM-S911B; dm1q; qcom; en_IN; 659489002)"
    )
    return cl


def seed_account(account_key: str, push: bool = False) -> bool:
    """Seed session for one account. Returns True on success."""
    acct = ACCOUNTS.get(account_key)
    if not acct:
        print(f"Unknown account: {account_key}")
        print(f"Available: {', '.join(ACCOUNTS.keys())}")
        return False

    env = _load_env(acct["env_file"])
    username = env.get("INSTAGRAM_USERNAME", "")
    password = env.get("INSTAGRAM_PASSWORD", "")

    if not username or not password:
        print(f"ERROR: No INSTAGRAM_USERNAME/PASSWORD in {acct['env_file']}")
        return False

    print(f"\n{'─'*60}")
    print(f"  Seeding session for: @{username} ({account_key})")
    print(f"{'─'*60}")

    # Check for existing session
    session_path = acct["data_dir"] / ".ig_session.json"
    if session_path.exists():
        print(f"  Found existing session at {session_path}")
        choice = input("  Use existing session? (y/n, default=n): ").strip().lower()
        if choice == "y":
            # Validate existing session
            print("  Validating existing session...")
            cl = Client()
            try:
                cl.load_settings(str(session_path))
                cl.username = username
                cl.password = password
                info = cl.account_info()
                if info and getattr(info, "pk", None):
                    print(f"  Session valid! Logged in as @{info.username} (pk={info.pk})")
                    if push:
                        _push_session(account_key, session_path, acct["secret_name"])
                    return True
            except Exception as exc:
                print(f"  Existing session invalid: {exc}")
                print("  Will create a new session...")

    # Create new session
    print(f"\n  Logging in as @{username}...")
    print("  (If Instagram asks for verification, enter the code when prompted)\n")

    cl = _create_client()

    try:
        cl.login(username, password)
    except ChallengeRequired:
        print("\n  Challenge was triggered but the handler should have been called.")
        print("  If the challenge wasn't completed, try again.")
        return False
    except Exception as exc:
        print(f"\n  Login FAILED: {exc}")
        print("\n  Troubleshooting:")
        print("  1. Check username/password in env-templates/")
        print("  2. Open Instagram app on phone, log in, clear any challenges")
        print("  3. Try again after a few minutes")
        return False

    # Validate
    try:
        info = cl.account_info()
        print(f"\n  Login successful! @{info.username} (pk={info.pk})")
    except Exception as exc:
        print(f"\n  WARNING: Login succeeded but account_info() failed: {exc}")
        print("  The session might still work. Saving it anyway...")

    # Save session
    acct["data_dir"].mkdir(parents=True, exist_ok=True)
    cl.dump_settings(str(session_path))
    print(f"  Session saved to: {session_path}")

    # Small delay to look human
    time.sleep(2)

    if push:
        _push_session(account_key, session_path, acct["secret_name"])

    return True


def _push_session(account_key: str, session_path: Path, secret_name: str):
    """Push session to GitHub secret."""
    print(f"\n  Pushing session to GitHub secret: {secret_name}")
    try:
        session_data = session_path.read_bytes()
        b64 = base64.b64encode(session_data).decode()
        result = subprocess.run(
            ["gh", "secret", "set", secret_name, "--body", b64],
            capture_output=True, text=True, cwd=str(SCRIPT_DIR),
        )
        if result.returncode == 0:
            print(f"  Pushed to {secret_name}")
        else:
            print(f"  FAILED to push: {result.stderr}")
    except FileNotFoundError:
        print("  ERROR: 'gh' CLI not found. Install GitHub CLI: https://cli.github.com/")
        print(f"  Manual push: cat {session_path} | base64 | gh secret set {secret_name}")


def main():
    args = sys.argv[1:]
    push = "--push" in args
    args = [a for a in args if a != "--push"]

    if not args:
        # Interactive mode
        print("\nInstagram Session Seeder")
        print("=" * 40)
        print("\nAvailable accounts:")
        for i, key in enumerate(ACCOUNTS, 1):
            env = _load_env(ACCOUNTS[key]["env_file"])
            handle = env.get("INSTAGRAM_USERNAME", "?")
            print(f"  {i}. {key:6s} (@{handle})")
        print(f"  {len(ACCOUNTS)+1}. ALL accounts")

        choice = input(f"\nSelect account(s) (1-{len(ACCOUNTS)+1}, or name): ").strip()

        if choice.isdigit():
            idx = int(choice)
            if idx == len(ACCOUNTS) + 1:
                args = list(ACCOUNTS.keys())
            elif 1 <= idx <= len(ACCOUNTS):
                args = [list(ACCOUNTS.keys())[idx - 1]]
        elif choice in ACCOUNTS:
            args = [choice]
        elif choice == "all" or choice == "--all":
            args = list(ACCOUNTS.keys())
        else:
            print(f"Invalid choice: {choice}")
            sys.exit(1)

        push_choice = input("\nPush sessions to GitHub secrets? (y/n, default=y): ").strip().lower()
        push = push_choice != "n"

    elif "--all" in args:
        args = list(ACCOUNTS.keys())

    # Seed each account
    results = {}
    for account_key in args:
        if account_key.startswith("--"):
            continue
        ok = seed_account(account_key, push=push)
        results[account_key] = ok

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    for key, ok in results.items():
        status = "OK" if ok else "FAILED"
        print(f"  {key:6s}: {status}")

    failed = [k for k, v in results.items() if not v]
    if failed:
        print(f"\nFailed accounts: {', '.join(failed)}")
        print("Try logging into these accounts from the Instagram app first,")
        print("then run this script again.")
        sys.exit(1)
    else:
        print("\nAll sessions seeded successfully!")
        if push:
            print("Sessions pushed to GitHub secrets — the bot will use them on next run.")
        else:
            print("Run with --push to upload to GitHub secrets.")


if __name__ == "__main__":
    main()
