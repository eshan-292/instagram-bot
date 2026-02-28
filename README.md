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

The bot runs **19 scheduled sessions/day** — matching real human phone usage patterns. ~20% of sessions are randomly skipped (simulating being busy), so effective sessions are **~15/day**. **1 post per day** at prime time (13:30 UTC / 19:00 IST). Each session has 30s-6min random startup jitter.

### Schedule

| IST Time | Session | Notes |
|----------|---------|-------|
| 01:30 | Explore | Late night / can't sleep |
| 05:30 | Hashtags | Early bird |
| 07:00 | Morning engagement | Wake up scroll |
| 08:30 | Hashtags | Commute scroll |
| 10:00 | **Stories** | Morning stories |
| 11:00 | Replies | Reply to comments |
| 12:00 | Hashtags | Lunch break |
| **13:30** | **PUBLISH + Hashtags** | **Prime time** |
| 14:00 | **Stories** | Post-publish stories |
| 14:45 | Explore | Afternoon |
| 16:00 | **Stories** | Afternoon stories |
| 17:30 | Hashtags | Evening prime |
| 18:00 | **Stories** | Evening stories |
| 19:00 | Hashtags | Evening engagement |
| 20:30 | Replies | Reply to comments |
| 21:30 | Explore | Winding down |
| 22:00 | Maintenance | Auto-unfollow |
| 22:30 | **Stories** | Late night stories |
| 23:30 | Report | Daily summary |

## What Each Session Does

There are 7 session types that run throughout the day. Here's exactly what each one does:

---

### 🌅 `morning` — Warm-up engagement (07:00 IST)
Runs once at the start of the day. Browses 1 hashtag and likes + follows users from fresh posts. Light session (~8 posts) with a warm-up phase (first few posts: just look, no actions).

---

### #️⃣ `hashtags` — Core follower growth engine (runs ~6x/day)
The main growth driver. Each session:
1. Picks 1 hashtag from your niche list (`indianfashion`, `mumbaifashion`, etc.)
2. Fetches ~10 recent posts
3. Warms up: first 1-3 posts, just browses (no actions)
4. For each remaining post: **likes** ~70%, **comments** on ~10% (AI-generated by Gemini), **follows** ~20% (after viewing their profile first)
5. Views their **stories** (~50% chance) and likes ~15% of them
6. Occasionally saves posts (~8%) — strong interest signal

> **Why this gets followers:** Following someone + liking their post + viewing their story = 3 notifications. They check your profile and follow back if they like what they see. Lower rates per session, but smarter targeting.

---

### 🔍 `explore` — Reach new audiences (runs ~5x/day)
Browses the Instagram Explore/Reels feed — the content Instagram shows to non-followers. Mostly passive (simulates casual scrolling), likes some posts, comments on ~8%. Session starts with 2-4 posts of just watching (warmup). Occasionally saves posts. This gets Maya's activity seen by Instagram's algorithm.

---

### 💬 `replies` — Reply to comments on own posts (2x/day)
Fetches comments on Maya's own posts from the **last 48 hours** and replies using Gemini-generated responses in Maya's voice. Replying signals to Instagram's algorithm that the post is actively engaging. Also makes followers feel seen.

---

### 📖 `stories` — Repost content as stories (5x/day: 10:00, 14:00, 16:00, 18:00, 22:30)
Picks 2-3 already-published posts and reposts them as stories with:
- A text overlay ("In case you missed it", "Still obsessed", etc.)
- An interactive sticker: **poll** (35%), **question box/AMA** (30%), **quiz** (20%), or clean (15%)
- Auto-adds the story to the right **highlight** (OOTD, Mumbai Style, Ethnic Vibes, Tips, BTS, or Glam)

Stories expire after 24h but the highlights stay permanently.

---

### 🧹 `maintenance` — Clean up follows (1x/day at 22:00)
Unfollows users followed **3+ days ago** that didn't follow back. Keeps following count low. Does up to 30 unfollows per run with long delays between each.

---

### 📊 `report` — Daily summary (23:30 IST)
Runs once at the end of the day. Generates a summary of engagement stats, posts published, and growth signals.

---

## Anti-Detection & Human-Like Behavior

The bot uses multiple layers of human simulation to avoid detection:

### Timing
- **Gaussian delays** — Pauses cluster around a natural midpoint (not uniform random like bots)
- **Action-specific delays** — Likes are fast (8-25s), comments are slow (40-120s), follows medium (30-80s)
- **Session fatigue** — Actions get slower as session progresses (1.0x → 1.2x → 1.5x → 1.8x)
- **Micro-breaks** (15% chance) — 1.5-7 min pauses (checking another app, replying to texts)
- **Night slowdown** — 1.4x slower during late night hours (IST 11pm-7am)
- **Session startup jitter** — 30s-6min random delay so nothing runs at exact cron times

### Behavior
- **Session warmup** — First 1-4 posts in each session, just browse (no actions)
- **Scrolling simulation** — Passive watching between actions (like real browsing)
- **Skip behavior** — ~22% of posts are scrolled past without engaging
- **Random session skip** — 20% of scheduled sessions don't run (simulating being busy)
- **Random session abort** — 12% chance of stopping mid-session (got bored/distracted)
- **Profile browsing** — Views user profile before following
- **Post saves** — ~8% save rate (safe signal, shows genuine interest)

### Rates (conservative)
- **Selective commenting** — ~10% of hashtag posts, ~8% of explore posts
- **Selective following** — ~20% of users (with profile browse first)
- **Story viewing** — ~50% chance to view, ~15% to like

## Engagement Limits

| Action | Daily Limit | Notes |
|--------|------------|-------|
| Likes | 150 | Spread across ~14 effective sessions |
| Comments | 30 | AI-generated, ~10% of seen posts |
| Follows | 40 | With profile browse before follow (~20% rate) |
| Story views | 80 | ~50% chance per user, ~15% like rate |
| Replies | 25 | On own posts (last 48h) |
| Unfollows | 30/run | After 3+ days |
| Saves | Unlimited | ~8% of viewed posts |

**Warmup multiplier** for new accounts: 0.5x (days 1-7), 0.7x (days 8-14), 0.85x (days 15-21), 1.0x (day 22+).

## Stories

- **5 story sessions/day** (10:00, 14:00, 16:00, 18:00, 22:30 IST)
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
| `ENGAGEMENT_DAILY_LIKES` | `150` | Max likes/day |
| `ENGAGEMENT_DAILY_COMMENTS` | `30` | Max comments/day |
| `ENGAGEMENT_DAILY_FOLLOWS` | `40` | Max follows/day |
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
├── rate_limiter.py        # Action rate limiting + human-like timing
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
