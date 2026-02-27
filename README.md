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

## What You Need To Do (Image Generation)

The bot generates captions and prompts automatically. **You just need to generate the images and push them.** Here's the exact workflow:

### Step 1: Check what images are needed
```bash
# Look at the committed file on GitHub:
# → instagram_influencer/generated_images/IMAGE_PROMPTS.md
# Or generate prompts locally:
make generate
```

### Step 2: Generate images in Gemini app
1. Open [gemini.google.com](https://gemini.google.com/)
2. Copy each prompt from `IMAGE_PROMPTS.md`
3. Paste into Gemini → download the generated image

### Step 3: Place images in the right folder
```
instagram_influencer/generated_images/pending/
├── maya-042.jpg              ← single/reel (filename = post ID)
├── maya-043/                 ← carousel (folder = post ID)
│   ├── 1.jpg
│   ├── 2.jpg
│   └── 3.jpg
```

### Step 4: Push to GitHub
```bash
cd instagram_influencer
git add -f generated_images/pending/
git commit -m "add images for maya-042, maya-043"
git push
```

The bot automatically picks up the images at 19:00 IST and publishes them.

**Notes:** Filenames must match post IDs exactly. Formats: `.jpg`, `.jpeg`, `.png`, `.webp`. Min 10 KB. Carousels need 2+ images.

---

## Daily Schedule (GitHub Actions)

The bot runs **37 sessions per day — 24-hour coverage**. **1 post per day** at prime time (19:00 IST). Each session has 0-4 min random startup jitter.

### Night sessions (midnight–7am IST)
| IST Time | Session |
|----------|---------|
| 00:00 | Explore (night owl) |
| 00:45 | Hashtags |
| 01:30 | Explore |
| 02:30 | Hashtags (deep night) |
| 03:30 | Explore |
| 04:30 | Hashtags |
| 05:30 | Explore (early bird) |
| 06:15 | Hashtags |

### Day sessions (7am–midnight IST)
| IST Time | Session | Publishes? |
|----------|---------|------------|
| 07:00 | Morning engagement (~15 posts) | No |
| 07:45 | Explore (morning scroll) | No |
| 08:30 | Hashtags | No |
| 09:00 | Reply to comments | No |
| 09:45 | Story repost | No |
| 10:30 | Hashtags | No |
| 11:00 | Explore | No |
| 11:30 | Hashtags | No |
| 12:00 | Explore (lunch break) | No |
| 12:30 | Hashtags | No |
| 13:00 | Explore | No |
| 13:30 | Hashtags | No |
| 14:00 | Story repost | No |
| 14:45 | Explore | No |
| 15:30 | Hashtags | No |
| 16:00 | Reply to comments | No |
| 16:45 | Hashtags | No |
| 17:30 | Explore | No |
| 18:00 | Story repost | No |
| 18:30 | Hashtags | No |
| **19:00** | **PUBLISH** + hashtags (prime time) | **Yes** |
| 19:30 | Explore | No |
| 20:00 | Hashtags | No |
| 20:45 | Reply to comments | No |
| 21:30 | Explore (evening wind-down) | No |
| 22:00 | Maintenance (auto-unfollow) | No |
| 22:30 | Hashtags (late night) | No |
| 23:00 | Maintenance | No |
| 23:30 | Daily report | No |

## What Each Session Does

There are 7 session types that run throughout the day. Here's exactly what each one does:

---

### 🌅 `morning` — Warm-up engagement (07:00 IST)
Runs once at the start of the day. Browses 1-2 hashtags and likes + follows users from fresh posts. Slightly larger session (~15 posts) to kick off the day's engagement early before the main audience is active.

---

### #️⃣ `hashtags` — Core follower growth engine (runs ~15x/day)
The main growth driver. Each session:
1. Picks 1-2 hashtags from your niche list (`indianfashion`, `mumbaifashion`, etc.)
2. Fetches ~12 recent posts from those hashtags
3. For each post: **likes** it, **comments** on ~20% (AI-generated by Gemini), **follows** the user (~45% chance, after viewing their profile first)
4. Views their **stories** (~65% chance) and likes ~25% of them

> **Why this gets followers:** Following someone + liking their post + viewing their story = they get 3 notifications from you. Most people check who it is, visit your profile, and follow back if they like what they see.

---

### 🔍 `explore` — Reach new audiences (runs ~12x/day)
Browses the Instagram Explore/Reels feed — the same content Instagram shows to non-followers. Likes posts and comments on ~18%. This gets Maya's activity seen by Instagram's algorithm, which helps push her content to new audiences. Also fills in the night hours when hashtag engagement is lighter.

---

### 💬 `replies` — Reply to comments on own posts (4x/day)
Fetches comments on Maya's own posts from the **last 24 hours** and replies to each one using a Gemini-generated response in Maya's voice. Replying within 24 hours sends a strong signal to Instagram's algorithm that the post is actively engaging, which boosts its reach. Also makes followers feel seen.

---

### 📖 `stories` — Repost content as stories (3x/day: 09:45, 14:00, 18:00)
Picks 2-3 already-published posts and reposts them as stories with:
- A text overlay ("In case you missed it", "Still obsessed", etc.)
- An interactive sticker: **poll** (35%), **question box/AMA** (30%), **quiz** (20%), or clean (15%)
- Auto-adds the story to the right **highlight** (OOTD, Mumbai Style, Ethnic Vibes, Tips, BTS, or Glam)

Stories expire after 24h but the highlights stay permanently. Polls and question boxes drive DMs and replies, which are strong engagement signals.

---

### 🧹 `maintenance` — Clean up follows (2x/day: 22:00, 23:00)
Unfollows users that were followed **3+ days ago** and didn't follow back. This keeps the following count low so Instagram doesn't flag the account for following too many people, and frees up room to follow new targets. Does up to 40 unfollows per run with long delays between each.

---

### 📊 `report` — Daily summary (23:30 IST)
Runs once at the end of the day. Generates a summary of everything that happened: posts published, total likes given, comments, follows, unfollows, story views, replies. Sends it to Telegram (if configured) and saves it as `daily_report.md` in the repo.

---

## Anti-Detection & Human-Like Behavior

The bot mimics real human Instagram usage patterns:

- **Gaussian delays** — Pauses cluster around a natural midpoint (not uniform random)
- **Micro-breaks** (10% chance) — 60-180s pauses simulating checking texts, switching apps
- **Session startup jitter** — 10s-4min random delay so nothing runs at exact times
- **Skip behavior** — ~18% of posts are scrolled past without engaging
- **Profile browsing** — Views user profile before following
- **Randomized session sizes** — ±40% variation per session
- **Selective commenting** — ~20% of posts get comments (genuine, not spammy)
- **Selective following** — ~45% of users get followed (with profile browse first)
- **Story viewing** — ~65% chance to view stories, ~25% to like

## Engagement Limits (Maximized)

| Action | Daily Limit | Notes |
|--------|------------|-------|
| Likes | 250 | Spread across 37 sessions (~7/session) |
| Comments | 55 | AI-generated, ~20% of seen posts |
| Follows | 80 | With profile browse before follow (~45% rate) |
| Story views | 100 | ~65% chance per user, ~25% like rate |
| Replies | 30 | On own posts (last 24h) |
| Unfollows | 40/run | After 3+ days |
| Welcome DMs | 8/day | 60-180s gaps between DMs |

**Warmup multiplier** for new accounts: 0.6x (days 1-7), 0.8x (days 8-14), 1.0x (day 15+).

**Delays:** 20-60s between hashtag actions, 15-45s explore, 30-90s replies — with gaussian distribution + micro-breaks.

## Stories

- **3 story sessions/day** (09:45, 14:00, 18:00 IST)
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
| `ENGAGEMENT_DAILY_LIKES` | `250` | Max likes/day |
| `ENGAGEMENT_DAILY_COMMENTS` | `55` | Max comments/day |
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
