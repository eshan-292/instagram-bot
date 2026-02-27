# Instagram Influencer Bot

Automated Instagram growth pipeline for **Maya Varma** — AI fashion influencer from Mumbai.

```
Gemini (captions + prompts) → Manual image gen (Gemini app) → instagrapi (publish)
```

## How It Works

1. **Generate captions** — Gemini 2.5 Flash creates posts in Maya's voice (bold, teasing, confident)
2. **Generate image prompts** — Bot creates Gemini-ready prompts and saves to `IMAGE_PROMPTS.md`
3. **You generate images** — Copy prompts into the Gemini app, save images to `generated_images/pending/`
4. **Bot picks up images** — On next run, links images to drafts and promotes them
5. **Publish** — Posts to Instagram via instagrapi (reels, carousels, or single photos)
6. **Engage** — Automated likes, comments, follows, story views, replies throughout the day

Post lifecycle: `draft` → `approved` → `ready` → `posted`

## Content Strategy (2026 Algorithm)

| Format | % of Content | Why |
|--------|-------------|-----|
| **Reels** (7-15 sec) | 40% | 55% of views from non-followers. THE discovery tool. |
| **Carousels** (5-6 slides) | 40% | 3x higher engagement, most saved format. |
| **Single images** | 20% | Aesthetic/editorial brand posts. |

**Caption strategy:**
- Front-loaded keywords (Instagram is a search engine now)
- Save/share CTAs on every post ("save this", "send to your bestie")
- Only 3-5 targeted hashtags (quality > quantity)

## Quick Start

```bash
# 1. Setup
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp instagram_influencer/.env.example .env

# 2. Add your keys to .env
#    INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD
#    GEMINI_API_KEY

# 3. Generate captions + image prompts
make generate

# 4. Check IMAGE_PROMPTS.md, generate images in Gemini app,
#    place them in generated_images/pending/

# 5. Full pipeline (pick up images + promote + publish)
make run
```

## Image Generation (Manual via Gemini App)

Since the Replicate API quota is exhausted, images are generated manually via the Gemini app.

### Step-by-step workflow

**1. Check what images are needed:**
```bash
# Option A: Look at the committed file on GitHub
# → instagram_influencer/generated_images/IMAGE_PROMPTS.md

# Option B: Generate prompts locally
make generate
# → Creates instagram_influencer/generated_images/IMAGE_PROMPTS.md
```

**2. Generate images in the Gemini app:**
- Open the [Gemini app](https://gemini.google.com/)
- Copy each prompt from `IMAGE_PROMPTS.md` and paste it into Gemini
- Download the generated image

**3. Place images in the right directory:**

```
instagram_influencer/generated_images/pending/
├── maya-042.jpg                  ← single image or reel (match the post ID)
├── maya-043/                     ← carousel (create a folder named by post ID)
│   ├── 1.jpg                    ← slide 1
│   ├── 2.jpg                    ← slide 2
│   ├── 3.jpg                    ← slide 3
│   ├── 4.jpg                    ← slide 4
│   └── 5.jpg                    ← slide 5 (up to 6)
```

**4. Commit and push the images:**
```bash
cd instagram_influencer
git add -f generated_images/pending/
git commit -m "add images for maya-042, maya-043"
git push
```

**5. The bot handles the rest automatically:**
- Next publish session picks up the images
- Links them to the matching drafts
- Promotes drafts → approved → publishes at the next scheduled slot

### Notes
- Image filenames must match the post ID exactly (e.g., `maya-042.jpg` for post `maya-042`)
- Supported formats: `.jpg`, `.jpeg`, `.png`, `.webp`
- Minimum file size: 10 KB (smaller files are ignored)
- Carousel posts need at least 2 images in the folder
- Individual prompts are also saved to `generated_images/prompts/{post_id}.txt`
- The `IMAGE_PROMPTS.md` file is auto-committed to the repo after each generation run

## Daily Schedule (GitHub Actions)

The bot runs **16 sessions per day** via GitHub Actions cron, with **3 publish slots** and engagement throughout.

| IST Time | UTC Cron | Session | Publishes? |
|----------|----------|---------|------------|
| 07:00 | `30 1 * * *` | Morning engagement (likes + follows, 25 posts) | No |
| 09:00 | `30 3 * * *` | Reply to comments on own posts | No |
| 10:00 | `30 4 * * *` | Story repost (2-3 stories + highlights) | No |
| 11:00 | `30 5 * * *` | Hashtag engagement (50 posts) | No |
| **11:30** | `0 6 * * *` | **PUBLISH** + hashtag engagement | **Yes** |
| **13:00** | `30 7 * * *` | **PUBLISH** + explore engagement | **Yes** |
| 14:00 | `30 8 * * *` | Story repost | No |
| 15:00 | `30 9 * * *` | Hashtag engagement (50 posts) | No |
| 16:00 | `30 10 * * *` | Explore engagement (40 posts) | No |
| 17:00 | `30 11 * * *` | Maintenance (auto-unfollow) | No |
| 18:00 | `30 12 * * *` | Story repost | No |
| **19:00** | `30 13 * * *` | **PUBLISH** + full engagement | **Yes** |
| 20:30 | `0 15 * * *` | Hashtag engagement (50 posts) | No |
| 21:30 | `0 16 * * *` | Reply to comments | No |
| 23:00 | `30 17 * * *` | Maintenance (auto-unfollow) | No |
| 23:30 | `0 18 * * *` | Daily report (Telegram + Actions summary) | No |

## Engagement Limits

| Action | Daily Limit | Per Session |
|--------|------------|-------------|
| ❤️ Likes | 200 | 25-60 posts depending on session |
| 💬 Comments | 60 | AI-generated, context-aware |
| ➕ Follows | 80 | From hashtag + explore targets |
| 👀 Story views | 120 | + like ~30% for stronger signal |
| 💬 Replies | 35 | On own posts (last 24h) |
| ➖ Unfollows | 50/run | After 3+ days |

**Warmup multiplier** for new accounts: 0.6x (days 1-7), 0.8x (days 8-14), 1.0x (day 15+).

**Delays:** 15-45s between hashtag actions, 8-20s explore, 15-40s replies (human-like pacing).

## Stories

- **3 story sessions/day** (10:00, 14:00, 18:00 IST)
- Reposts 2-3 past posts with text overlays
- **Auto-downloads media from Instagram** if local files don't exist (works seamlessly in CI)
- Interactive stickers: 35% poll, 30% question box (AMA), 20% quiz, 15% clean
- Auto-categorized into highlights (OOTD, Mumbai Style, Ethnic Vibes, Tips, BTS, Glam)

## Daily Reports

End-of-day summary at 23:30 IST with engagement stats, posts published, and growth signals.

**Telegram setup:**
1. Create a bot via @BotFather → get token
2. Send a message to your bot, then get chat ID from `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxx
   TELEGRAM_CHAT_ID=123456789
   ```
4. Update secret: `gh secret set DOTENV --repo eshan-292/instagram-bot < .env`

## Make Commands

| Command | What it does |
|---------|-------------|
| `make generate` | Generate captions + image prompts (no publishing) |
| `make run` | Full pipeline: generate → pick up images → promote → publish → engage |
| `make dry-run` | Preview next post that would be published |
| `make publish` | Publish next eligible post only |
| `make engage` | Run engagement only (skip generation/publishing) |
| `make check` | Syntax check all Python files |
| `make deps` | Install dependencies |

## Environment Variables

**Required:**
| Variable | Description |
|----------|-------------|
| `INSTAGRAM_USERNAME` | Instagram account username |
| `INSTAGRAM_PASSWORD` | Instagram account password |
| `GEMINI_API_KEY` | Google AI Studio API key ([free](https://aistudio.google.com/apikey)) |

**Optional:**
| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model for caption generation |
| `DRAFT_COUNT` | `3` | Posts to generate per run |
| `MIN_READY_QUEUE` | `5` | Min ready posts before generating more |
| `AUTO_MODE` | `false` | Enable auto publishing |
| `AUTO_PROMOTE_DRAFTS` | `false` | Auto-promote drafts to approved |
| `ENGAGEMENT_ENABLED` | `false` | Enable engagement automation |
| `ENGAGEMENT_DAILY_LIKES` | `200` | Max likes/day |
| `ENGAGEMENT_DAILY_COMMENTS` | `60` | Max comments/day |
| `ENGAGEMENT_DAILY_FOLLOWS` | `80` | Max follows/day |
| `ENGAGEMENT_COMMENT_ENABLED` | `false` | Enable AI comments on other posts |
| `ENGAGEMENT_FOLLOW_ENABLED` | `false` | Enable auto-follow |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token for daily reports |
| `TELEGRAM_CHAT_ID` | — | Telegram chat ID for daily reports |
| `ACCOUNT_CREATED_DATE` | — | `YYYY-MM-DD` for warmup multiplier |

## Files

```
instagram_influencer/
├── config.py              # Configuration (~25 env vars)
├── orchestrator.py        # Pipeline CLI (single entry point)
├── generator.py           # Caption generation (Gemini + template fallback)
├── image.py               # Manual image system (prompts + pending/ lookup)
├── publisher.py           # Instagram publishing (reels, carousels, photos)
├── video.py               # Ken Burns effect (image → 5s MP4 for reels)
├── engagement.py          # Engagement automation (like/comment/follow/reply)
├── stories.py             # Story reposting + highlights + interactive stickers
├── report.py              # Daily report (Telegram + GitHub Actions summary)
├── rate_limiter.py        # Action rate limiting + warmup multiplier
├── gemini_helper.py       # Gemini API with model rotation (5 models, 100+ RPM)
├── post_queue.py          # Queue I/O (content_queue.json)
├── instagrapi_patch.py    # Monkey-patches for instagrapi resilience
├── reference/maya/        # Maya's reference photos
├── generated_images/
│   ├── pending/           # Place your generated images here
│   ├── prompts/           # Auto-generated per-post prompts
│   └── IMAGE_PROMPTS.md   # Master prompt summary (committed to repo)
├── content_queue.json     # Post queue state
├── engagement_log.json    # Action history
├── followers.json         # Tracked follower IDs
└── highlights.json        # Highlight PKs
```
