# Instagram + YouTube Influencer Bot

Automated dual-platform growth pipeline for **Maya Varma** — AI fashion influencer from Mumbai.

Posts to **Instagram** (Reels, Carousels, Single) and **YouTube Shorts** simultaneously, with aggressive engagement automation on both platforms.

```
Gemini (captions) → Image gen (Gemini app) → ffmpeg (video + audio) → Publish (IG + YT) → Engage (both)
```

## How It Works

1. **Generate captions** — Gemini 2.5 Flash creates posts in Maya's voice (bold, teasing, confident)
2. **Generate image prompts** — Bot creates Gemini-ready prompts and saves to `IMAGE_PROMPTS.md`
3. **You generate images** — Copy prompts into the Gemini app, save images to `generated_images/pending/`
4. **Bot picks up images** — Links images to drafts and promotes them
5. **Convert to video** — Ken Burns effect with background audio (IG 4:5 + YT 9:16)
6. **Publish to both platforms** — Instagram via instagrapi + YouTube Shorts via YouTube Data API
7. **Engage aggressively** — Automated likes, comments, follows, story views, replies on both platforms

Post lifecycle: `draft` → `approved` → `ready` → `posted` (IG + YT simultaneously)

## Content Strategy (2026 Algorithm)

| Format | % of Content | Why |
|--------|-------------|-----|
| **Reels/Shorts** (7-10 sec) | 40% | 55% of views from non-followers. THE discovery tool. |
| **Carousels** (5-6 slides) | 40% | 3x higher engagement, most saved format. |
| **Single images** | 20% | Aesthetic/editorial brand posts. |

**Caption strategy:**
- Scroll-stopping hook in first 3 words (number, question, or bold statement)
- Question in every caption (drives comments = algorithm boost)
- Save/share CTA on every post with urgency
- Cross-platform promotion (40% of posts mention YouTube channel)
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

# 5. Full pipeline (pick up images + promote + publish to IG + YT)
make run
```

## YouTube Shorts Setup

YouTube is optional but strongly recommended for aggressive growth — same content, 2x the audience.

### Step 1: Google Cloud Project (5 min)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **"Create Project"** → name it `maya-bot` → create
3. In the sidebar: **APIs & Services** → **Library**
4. Search for **"YouTube Data API v3"** → click **Enable**
5. In the sidebar: **APIs & Services** → **Credentials**
6. Click **"+ CREATE CREDENTIALS"** → **OAuth client ID**
7. If prompted, configure the **OAuth consent screen**:
   - User Type: **External** → Create
   - App name: `Maya Bot` (anything works)
   - User support email: your email
   - Developer contact: your email
   - Click **Save and Continue** through all steps
   - Under **Test users**, add your Google email
   - **Publish App** (move from testing to production) — or keep in testing if only you use it
8. Back in Credentials → **+ CREATE CREDENTIALS** → **OAuth client ID**:
   - Application type: **Desktop app**
   - Name: `Maya Bot`
   - Click **Create**
9. **Copy the Client ID and Client Secret** — you'll need them next

### Step 2: Get Refresh Token (2 min)

```bash
# Add to your .env file:
YOUTUBE_CLIENT_ID=your-client-id-here.apps.googleusercontent.com
YOUTUBE_CLIENT_SECRET=your-client-secret-here

# Run the one-time auth flow:
make yt-auth
```

This opens a browser window. Sign in with the Google account that owns the YouTube channel, grant permissions, and the script prints your refresh token.

### Step 3: Enable YouTube in .env

Add these to your `.env` file:
```env
YOUTUBE_ENABLED=true
YOUTUBE_CLIENT_ID=your-client-id.apps.googleusercontent.com
YOUTUBE_CLIENT_SECRET=your-client-secret
YOUTUBE_REFRESH_TOKEN=your-refresh-token-from-step-2
YOUTUBE_ENGAGEMENT_ENABLED=true
```

### Step 4: Update GitHub Secrets

```bash
gh secret set DOTENV --repo your-username/your-repo < instagram_influencer/.env
```

That's it. The bot will now upload every post to YouTube Shorts alongside Instagram.

## Image Generation (Manual via Gemini App)

### Step-by-step workflow

**1. Check what images are needed:**
```bash
# Option A: Look at the committed file on GitHub
# → instagram_influencer/generated_images/IMAGE_PROMPTS.md

# Option B: Generate prompts locally
make generate
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
- Converts to video with background audio (IG 4:5 + YT 9:16)
- Promotes drafts → approved → publishes at the next scheduled slot

### Custom Background Music

Place your own `.mp3` or `.wav` files in `generated_images/music/` and the bot will randomly pick one as the background track for videos. If no custom music is provided, it generates a pleasant ambient lo-fi pad automatically.

### Notes
- Image filenames must match the post ID exactly (e.g., `maya-042.jpg` for post `maya-042`)
- Supported formats: `.jpg`, `.jpeg`, `.png`, `.webp`
- Minimum file size: 10 KB (smaller files are ignored)
- Carousel posts need at least 2 images in the folder

---

## Daily Schedule (GitHub Actions)

The bot runs **35 sessions per day** — 29 Instagram + 6 YouTube — mimicking real phone-check patterns. **1 post/day** published to both platforms at prime time (19:00 IST).

| IST Time | Session | Platform | Publishes? |
|----------|---------|----------|------------|
| 07:00 | Morning engagement + welcome DMs | IG | No |
| 07:45 | Explore (morning scroll) | IG | No |
| 08:30 | Hashtags | IG | No |
| 09:00 | Reply to comments | IG | No |
| 09:45 | Story repost | IG | No |
| 10:30 | **YT niche engagement** | **YT** | No |
| 11:00 | Explore | IG | No |
| 11:30 | Hashtags | IG | No |
| 12:00 | Explore (lunch break) | IG | No |
| 12:30 | Hashtags | IG | No |
| 13:00 | **YT reply to comments** | **YT** | No |
| 13:30 | Hashtags | IG | No |
| 14:00 | Story repost | IG | No |
| 14:45 | Explore | IG | No |
| 15:30 | Hashtags | IG | No |
| 16:00 | Reply to comments | IG | No |
| 16:45 | **YT niche engagement** | **YT** | No |
| 17:30 | Explore | IG | No |
| 18:00 | Story repost | IG | No |
| 18:30 | Hashtags | IG | No |
| **19:00** | **PUBLISH + hashtags** | **IG + YT** | **Yes** |
| 19:30 | Explore | IG | No |
| 20:00 | **YT niche engagement** | **YT** | No |
| 20:45 | Reply to comments | IG | No |
| 21:30 | Explore (evening wind-down) | IG | No |
| 22:00 | Maintenance (unfollow + DMs) | IG | No |
| 22:30 | **YT reply to comments** | **YT** | No |
| 23:00 | Maintenance | IG | No |
| 23:30 | Daily report | Both | No |

## Anti-Detection & Human-Like Behavior

The bot mimics real human usage patterns to avoid detection:

- **Gaussian delays** — Pauses cluster around a natural midpoint (not uniform random)
- **Micro-breaks** (10% chance) — 60-180s pauses simulating checking texts, switching apps
- **Session startup jitter** — 10s-4min random delay so nothing runs at exact times
- **Skip behavior** — ~12% of posts are scrolled past without engaging
- **Profile browsing** — Views user profile before following
- **Randomized session sizes** — ±30% variation per session
- **Multi-story viewing** — Views 1-3 stories per user (not always just 1)
- **Selective commenting** — ~28% of hashtag posts, ~25% of explore posts
- **Selective following** — ~55% of hashtag users, ~30% of explore users

## Engagement Limits (Aggressive Growth)

### Instagram

| Action | Daily Limit | Notes |
|--------|------------|-------|
| Likes | 250 | Spread across 29 sessions |
| Comments | 60 | AI-generated, ~28% of seen posts |
| Follows | 80 | With profile browse before follow (~55% rate) |
| Story views | 150 | ~75% chance per user, ~35% like rate |
| Replies | 50 | On own posts (last 48h) — reply to ALL |
| Unfollows | 60/run | After 2+ days (fast churn) |
| Welcome DMs | 15/day | Run during morning + maintenance |

### YouTube

| Action | Daily Limit | Notes |
|--------|------------|-------|
| Likes | 30 | On trending niche Shorts |
| Comments | 10 | AI-generated, quality comments only |
| Replies | 15 | On own video comments |

**Warmup multiplier** for new accounts: 0.6x (days 1-7), 0.8x (days 8-14), 1.0x (day 15+).

## Video & Audio

- **Instagram Reels:** 1080x1350 (4:5), 7 seconds, Ken Burns zoom effect
- **YouTube Shorts:** 1080x1920 (9:16), 10 seconds, Ken Burns zoom effect
- **Audio:** Background music baked into every video
  - Priority 1: Custom tracks from `generated_images/music/`
  - Priority 2: Auto-generated ambient lo-fi pad (pink noise + Am7 chord)
- **Instagram also tries:** Trending music overlay via API (bonus reach)

## Stories

- **3 story sessions/day** (09:45, 14:00, 18:00 IST)
- Reposts 2-3 past posts with text overlays
- **Auto-downloads media from Instagram** if local files don't exist (works in CI)
- Interactive stickers: 35% poll, 30% question box (AMA), 20% quiz, 15% clean
- Auto-categorized into highlights (OOTD, Mumbai Style, Ethnic Vibes, Tips, BTS, Glam)

## Daily Reports

End-of-day summary at 23:30 IST with engagement stats, posts published, YouTube channel stats, and growth signals.

**Telegram setup:**
1. Create a bot via @BotFather → get token
2. Send a message to your bot, then get chat ID from `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxx
   TELEGRAM_CHAT_ID=123456789
   ```

## Make Commands

| Command | What it does |
|---------|-------------|
| `make generate` | Generate captions + image prompts (no publishing) |
| `make run` | Full pipeline: generate → video → publish (IG + YT) → engage |
| `make dry-run` | Preview next post that would be published |
| `make publish` | Publish next eligible post only |
| `make engage` | Run IG engagement only (skip generation/publishing) |
| `make yt-auth` | One-time YouTube OAuth2 setup (run locally) |
| `make yt-engage` | Run YouTube engagement only |
| `make check` | Syntax check all Python files |
| `make deps` | Install dependencies |

## Environment Variables

**Required:**
| Variable | Description |
|----------|-------------|
| `INSTAGRAM_USERNAME` | Instagram account username |
| `INSTAGRAM_PASSWORD` | Instagram account password |
| `GEMINI_API_KEY` | Google AI Studio API key ([free](https://aistudio.google.com/apikey)) |

**YouTube (optional but recommended):**
| Variable | Description |
|----------|-------------|
| `YOUTUBE_ENABLED` | `true` to enable YouTube Shorts publishing |
| `YOUTUBE_CLIENT_ID` | Google OAuth2 client ID |
| `YOUTUBE_CLIENT_SECRET` | Google OAuth2 client secret |
| `YOUTUBE_REFRESH_TOKEN` | OAuth2 refresh token (from `make yt-auth`) |
| `YOUTUBE_ENGAGEMENT_ENABLED` | `true` to enable YouTube engagement automation |

**Engagement:**
| Variable | Default | Description |
|----------|---------|-------------|
| `ENGAGEMENT_ENABLED` | `false` | Enable Instagram engagement automation |
| `ENGAGEMENT_DAILY_LIKES` | `250` | Max likes/day |
| `ENGAGEMENT_DAILY_COMMENTS` | `60` | Max comments/day |
| `ENGAGEMENT_DAILY_FOLLOWS` | `80` | Max follows/day |
| `ENGAGEMENT_COMMENT_ENABLED` | `false` | Enable AI comments on other posts |
| `ENGAGEMENT_FOLLOW_ENABLED` | `false` | Enable auto-follow |

**Other:**
| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model for caption generation |
| `DRAFT_COUNT` | `3` | Posts to generate per run |
| `MIN_READY_QUEUE` | `5` | Min ready posts before generating more |
| `AUTO_MODE` | `false` | Enable auto publishing |
| `AUTO_PROMOTE_DRAFTS` | `false` | Auto-promote drafts to approved |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token for daily reports |
| `TELEGRAM_CHAT_ID` | — | Telegram chat ID for daily reports |
| `ACCOUNT_CREATED_DATE` | — | `YYYY-MM-DD` for warmup multiplier |

## Files

```
instagram_influencer/
├── config.py              # Configuration (~30 env vars)
├── orchestrator.py        # Pipeline CLI (single entry point, dual-platform)
├── generator.py           # Caption generation (Gemini + template fallback)
├── image.py               # Manual image system (prompts + pending/ lookup)
├── audio.py               # Background music (user tracks + ffmpeg generation)
├── video.py               # Ken Burns effect (IG 4:5 + YT 9:16 with audio)
├── publisher.py           # Instagram publishing (reels, carousels, photos)
├── youtube_publisher.py   # YouTube Shorts publishing (OAuth2 + Data API v3)
├── youtube_engagement.py  # YouTube engagement (like, comment, reply on Shorts)
├── engagement.py          # Instagram engagement (like/comment/follow/reply)
├── stories.py             # Story reposting + highlights + interactive stickers
├── report.py              # Daily report (Telegram + GitHub Actions + YT stats)
├── rate_limiter.py        # Action rate limiting + warmup multiplier
├── gemini_helper.py       # Gemini API with model rotation (5 models, 100+ RPM)
├── post_queue.py          # Queue I/O (content_queue.json)
├── instagrapi_patch.py    # Monkey-patches for instagrapi resilience
├── reference/maya/        # Maya's reference photos
├── generated_images/
│   ├── pending/           # Place your generated images here
│   ├── prompts/           # Auto-generated per-post prompts
│   ├── music/             # Place custom background music (.mp3/.wav) here
│   └── IMAGE_PROMPTS.md   # Master prompt summary (committed to repo)
├── content_queue.json     # Post queue state
├── engagement_log.json    # Action history (IG + YT)
├── followers.json         # Tracked follower IDs
└── highlights.json        # Highlight PKs
```
