#!/bin/bash
# Deploy Instagram bot to GitHub Actions (free, runs 24/7)
#
# This script:
# 1. Initializes a git repo
# 2. Creates a GitHub repo (public for free unlimited minutes)
# 3. Pushes the code
# 4. Sets up the DOTENV secret from your .env file
# 5. The bot starts running automatically on schedule!
#
# Prerequisites: gh CLI (brew install gh) + logged in (gh auth login)

set -euo pipefail

REPO_NAME="instagram-bot"
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"

echo "=== Instagram Bot Cloud Deployment ==="
echo ""

# Check prerequisites
if ! command -v gh &>/dev/null; then
    echo "ERROR: GitHub CLI not found. Install with: brew install gh"
    exit 1
fi
if ! gh auth status &>/dev/null; then
    echo "ERROR: Not logged into GitHub. Run: gh auth login"
    exit 1
fi

GITHUB_USER=$(gh api user -q .login)
echo "GitHub user: $GITHUB_USER"
echo ""

# Check if .env exists
if [ ! -f "instagram_influencer/.env" ]; then
    echo "ERROR: instagram_influencer/.env not found. Create it first."
    exit 1
fi

# Init git repo
if [ ! -d ".git" ]; then
    echo "Initializing git repo..."
    git init
    git add .
    git commit -m "Initial commit: Instagram influencer bot"
fi

# Create GitHub repo
echo ""
echo "Creating GitHub repo: $REPO_NAME"
echo "(Public repo = unlimited free GitHub Actions minutes)"
echo ""

if gh repo view "$GITHUB_USER/$REPO_NAME" &>/dev/null; then
    echo "Repo already exists: $GITHUB_USER/$REPO_NAME"
else
    gh repo create "$REPO_NAME" --public --source=. --push \
        --description "Instagram influencer bot with automated engagement"
fi

# Set remote if not already
if ! git remote get-url origin &>/dev/null; then
    git remote add origin "https://github.com/$GITHUB_USER/$REPO_NAME.git"
fi

# Push code
echo ""
echo "Pushing code to GitHub..."
git push -u origin main 2>/dev/null || git push -u origin master

# Set up DOTENV secret
echo ""
echo "Setting up secrets..."
gh secret set DOTENV < instagram_influencer/.env

echo ""
echo "=== Deployment Complete! ==="
echo ""
echo "Your bot is now deployed at:"
echo "  https://github.com/$GITHUB_USER/$REPO_NAME"
echo ""
echo "It will run automatically on this schedule (IST):"
echo "  07:00 — Morning engagement (likes + follows)"
echo "  09:00 — Reply to comments"
echo "  11:00 — Hashtag engagement"
echo "  13:00 — PUBLISH + explore engagement"
echo "  15:00 — Hashtag engagement"
echo "  17:00 — Maintenance (unfollow + DMs)"
echo "  19:00 — PUBLISH + full engagement"
echo "  20:30 — Hashtag engagement"
echo "  21:30 — Reply to comments"
echo "  23:00 — Maintenance"
echo ""
echo "To manually trigger a run:"
echo "  gh workflow run bot.yml -f session=full -f publish=true"
echo ""
echo "To check latest run status:"
echo "  gh run list --workflow=bot.yml --limit=5"
echo ""
echo "To see run logs:"
echo "  gh run view --log"
echo ""
echo "To update the bot code, just push changes:"
echo "  git add . && git commit -m 'update' && git push"
echo ""
echo "To update .env secrets:"
echo "  gh secret set DOTENV < instagram_influencer/.env"
