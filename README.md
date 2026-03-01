# Instagram + YouTube Influencer Bot

Multi-account automated growth pipeline for AI influencers — currently running **Maya Varma** (fashion) and **Aryan Dhar** (fitness), with 3 satellite support accounts.

Posts to **Instagram** (Reels, Carousels, Single) and **YouTube Shorts** simultaneously, with aggressive engagement automation on both platforms.

```
Gemini (captions) -> Image gen (Gemini app) -> ffmpeg (video) -> Publish (IG + YT) -> Engage (both)
```

## Architecture: Multi-Account Persona System

The bot uses a **persona-based architecture** where all account-specific data (identity, voice, templates, hashtags, etc.) lives in JSON files. The codebase is fully shared — each account gets its own persona JSON, state directory, GitHub secrets, and workflow files.

```
personas/
  maya.json       # Maya Varma — fashion influencer (main)
  aryan.json      # Aryan Dhar — fitness influencer (main)
  sat1.json       # Satellite support account 1
  sat2.json       # Satellite support account 2
  sat3.json       # Satellite support account 3

data/
  maya/           # Maya's state (queue, engagement log, images, session)
  aryan/          # Aryan's state
  sat1/           # Satellite 1 state (lightweight)
  sat2/
  sat3/
```

**Persona selection** is via the `PERSONA` env var (e.g. `PERSONA=aryan`). Each GitHub Actions workflow sets this in its `.env` file.

### Main Accounts (Full Pipeline)
- **Maya Varma** — 23yo fashion influencer from Mumbai. Bold, teasing, confident voice.
- **Aryan Dhar** — 25yo fitness influencer from Delhi. Confident, disciplined, motivating, no-BS.

Both get: content generation, image prompts, video creation, IG + YT publishing, full engagement (warm audience, hashtags, explore, replies, stories), cross-promotion with each other.

### Satellite Accounts (Engagement Support)
3 lightweight accounts that boost engagement signals for both main accounts:
- Like, comment, and save main accounts' posts
- View main accounts' stories
- Do light background engagement to appear human
- Anti-detection: 20% random session skip, extended jitter, low daily limits

### Cross-Promotion
Main accounts subtly support each other without being overtly linked:
- Daily cross-promo engagement sessions (like + comment + story views on partner's posts)
- Timed ~2hrs after partner publishes for natural engagement signal
- No @mentions in captions — accounts appear independent publicly
- Satellite accounts engage both main accounts for additional signal boost
- Max 2 partner comments/day to stay subtle

## How It Works

1. **Generate captions** -- Gemini creates posts in the persona's voice (auto-rotates models on rate limits)
2. **Generate image prompts** -- Bot creates Gemini-ready prompts and saves to `IMAGE_PROMPTS.md`
3. **You generate images** -- Copy prompts into the Gemini app, save images to `data/{persona}/generated_images/pending/`
4. **Bot picks up images** -- Links images to drafts and promotes them
5. **Convert to video** -- Ken Burns effect (IG silent, YT with royalty-free music)
6. **Publish to both platforms** -- Instagram via instagrapi + YouTube Shorts via YouTube Data API
7. **Engage aggressively** -- Warm audience targeting, hashtag engagement, replies, stories on both platforms

Post lifecycle: `draft` -> `approved` -> `ready` -> `posted` (IG + YT simultaneously)

## Content Strategy (2026 Algorithm)

| Format | % of Content | Why |
|--------|-------------|-----|
| **Reels/Shorts** (7-10 sec) | 40% | 55% of views from non-followers. THE discovery tool. |
| **Carousels** (5-6 slides) | 40% | 3x higher engagement, most saved+shared format. |
| **Single images** | 20% | Aesthetic/editorial brand posts. |

**Caption strategy (optimized for "sends" -- the #1 algorithm signal in 2026):**
- Scroll-stopping hook in first 3 words (number, question, or bold statement)
- Front-loaded searchable keywords (Instagram = search engine now)
- Question in every caption (drives comments = algorithm boost)
- Every caption ends with a send/share CTA: "Send this to someone who...", "Tag your bestie"
- `alt_text` on every post (accessibility + Instagram SEO)
- 3-5 hashtags in caption (pyramid: 1 brand + 1 broad + 2 medium + 1 niche)
- 15-20 extra hashtags posted as **first comment** for maximum discovery
- Like counts hidden on all posts (reduces comparison anxiety, boosts engagement)
- No cross-platform mentions in captions (IG and YT kept separate)

## Audio Strategy (2026)

- **Instagram Reels:** SILENT videos -- trending music overlaid at publish time via Instagram's music API
  - 30+ trending music search queries (Bollywood, Indian pop, fashion, viral)
  - Auto-retry with backoff on 429/500 server errors
  - Falls back to no-music upload if trending audio unavailable
- **YouTube Shorts:** Background music baked into video
  - Priority 1: Pixabay royalty-free tracks (needs API key)
  - Priority 2: User-provided tracks from `generated_images/music/`
  - Priority 3: Lo-fi beat generator (chord progressions + bass + drums + vinyl noise)
    - 4 random chord progressions for variety (classic, emotional, uplifting, jazzy)
    - Sub-bass following root notes, lo-fi kick pattern, hi-hat shimmer
    - Warm mixing with mid-boost and high-cut for lo-fi feel

## Quick Start

```bash
# 1. Setup
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp instagram_influencer/.env.example .env

# 2. Add your keys to .env
#    INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD
#    GEMINI_API_KEY
#    PERSONA=maya  (or aryan, sat1, etc.)

# 3. Generate captions + image prompts
make generate

# 4. Check IMAGE_PROMPTS.md, generate images in Gemini app,
#    place them in data/{persona}/generated_images/pending/

# 5. Full pipeline (pick up images + promote + publish to IG + YT)
make run
```

## YouTube Shorts Setup

YouTube is optional but strongly recommended for aggressive growth -- same content, 2x the audience.

### Step 1: Google Cloud Project (5 min)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **"Create Project"** -> name it `maya-bot` -> create
3. In the sidebar: **APIs & Services** -> **Library**
4. Search for **"YouTube Data API v3"** -> click **Enable**
5. In the sidebar: **APIs & Services** -> **Credentials**
6. Click **"+ CREATE CREDENTIALS"** -> **OAuth client ID**
7. If prompted, configure the **OAuth consent screen**:
   - User Type: **External** -> Create
   - App name: `Maya Bot` (anything works)
   - User support email: your email
   - Developer contact: your email
   - Click **Save and Continue** through all steps
   - Under **Test users**, add your Google email
   - **Publish App** (move from testing to production) -- or keep in testing if only you use it
8. Back in Credentials -> **+ CREATE CREDENTIALS** -> **OAuth client ID**:
   - Application type: **Desktop app**
   - Name: `Maya Bot`
   - Click **Create**
9. **Copy the Client ID and Client Secret** -- you'll need them next

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
# -> data/{persona}/generated_images/IMAGE_PROMPTS.md

# Option B: Generate prompts locally
make generate
```

**2. Generate images in the Gemini app:**
- Open the [Gemini app](https://gemini.google.com/)
- Copy each prompt from `IMAGE_PROMPTS.md` and paste it into Gemini
- Download the generated image

**3. Place images in the right directory:**

```
data/{persona}/generated_images/pending/
  maya-042.jpg                  <- single image or reel (match the post ID)
  maya-043/                     <- carousel (create a folder named by post ID)
    1.jpg                       <- slide 1
    2.jpg                       <- slide 2
    3.jpg                       <- slide 3
    4.jpg                       <- slide 4
    5.jpg                       <- slide 5 (up to 6)
```

**4. Commit and push the images:**
```bash
git add -f instagram_influencer/data/maya/generated_images/pending/
git commit -m "add images for maya-042, maya-043"
git push
```

**5. The bot handles the rest automatically:**
- Next publish session picks up the images
- Links them to the matching drafts
- Converts to video (IG silent + YT with music)
- Promotes drafts -> approved -> publishes at the next scheduled slot

### Custom Background Music

Place your own `.mp3` or `.wav` files in `data/{persona}/generated_images/music/` and the bot will use them as background tracks for YouTube Shorts. If no custom music is provided, it fetches royalty-free tracks from Pixabay, or falls back to a generated ambient lo-fi pad.

### Notes
- Image filenames must match the post ID exactly (e.g., `maya-042.jpg` for post `maya-042`)
- Supported formats: `.jpg`, `.jpeg`, `.png`, `.webp`
- Minimum file size: 10 KB (smaller files are ignored)
- Carousel posts need at least 2 images in the folder

---

## Daily Schedule (GitHub Actions -- Parallel Multi-Workflow)

### Workflow Architecture

7 independent workflows run in parallel with separate concurrency groups:

| Workflow | Sessions/Day | Concurrency Group | Purpose |
|----------|-------------|-------------------|---------|
| `instagram-bot.yml` | 33 | `instagram-bot-maya` | Maya IG |
| `youtube-bot.yml` | 12 | `youtube-bot` | Maya YT |
| `instagram-bot-aryan.yml` | 33 | `instagram-bot-aryan` | Aryan IG |
| `youtube-bot-aryan.yml` | 12 | `youtube-bot-aryan` | Aryan YT |
| `satellite-1.yml` | 6 | `satellite-1` | Satellite 1 |
| `satellite-2.yml` | 6 | `satellite-2` | Satellite 2 |
| `satellite-3.yml` | 6 | `satellite-3` | Satellite 3 |

**Total: ~108 sessions/day** across all accounts (including 5 overnight sessions per main account).

**1 post/day per main account** at prime time (Maya 19:00 IST, Aryan 19:15 IST).

**Reliability:** Session routing uses `github.event.schedule` (the exact cron expression) instead of wall-clock time, making it immune to GitHub Actions cron delays (which can be 10-20+ minutes). State commits add each file individually (avoiding failures from missing files), use `git pull --rebase` before push, and retry up to 3 times on push failure to handle parallel workflow race conditions.

### Maya Instagram Schedule (29 sessions)

| IST Time | Session | Notes |
|----------|---------|-------|
| 07:00 | Morning engagement | Wake up, check overnight |
| 07:40 | Explore | Morning scroll |
| 08:15 | Warm audience | High-ROI targeting |
| 08:50 | Hashtags | |
| 09:30 | Replies | |
| 10:05 | Stories | |
| 10:40 | Explore | |
| 11:15 | Hashtags | |
| 11:50 | Warm audience | Pre-lunch targeting |
| 12:30 | Explore | Lunch scroll |
| 13:05 | Hashtags | |
| 13:40 | Replies | |
| 14:15 | Warm audience | Afternoon targeting |
| 14:50 | Explore | |
| 15:30 | Hashtags | |
| 16:10 | Stories | |
| 16:45 | Explore | |
| 17:20 | Warm audience | |
| 18:00 | Hashtags | |
| 18:35 | Stories | |
| **19:00** | **PUBLISH + explore** | **PRIME TIME** |
| 19:40 | Hashtags | Post-publish engagement boost |
| **20:00** | **Boost** | **Viral detection -- auto-boost** |
| 20:15 | Replies | |
| 20:50 | Explore | Evening wind-down |
| **21:00** | **Cross-promo** | **Engage partner's latest post** |
| 21:30 | Warm audience | |
| 22:05 | Maintenance | Unfollow (DMs disabled) |
| 22:45 | Maintenance | Second pass |
| 23:15 | Daily report | |

### Aryan Instagram Schedule (29 sessions)

Same session pattern as Maya, staggered +15 minutes. Publishes at **19:15 IST**. Cross-promo at **20:45 IST** (1.75hrs after Maya publishes).

### YouTube Schedules (12 sessions each)

Maya and Aryan each get 12 YT sessions/day (alternating engage/replies). Aryan's are staggered +15 min.

### Satellite Schedules (6 sessions each)

| IST Time | Session | Purpose |
|----------|---------|---------|
| 08:00/08:20/08:40 | sat_background | Light explore + stories |
| 11:00/11:20/11:40 | sat_boost | Like + comment + save main accounts' posts |
| 14:00/14:20/14:40 | sat_background | Background engagement |
| 17:00/17:20/17:40 | sat_boost | Second boost pass |
| 20:00/20:20/20:40 | sat_boost | Critical post-publish boost |
| 22:00/22:20/22:40 | sat_background | Final background pass |

Satellites are staggered so they don't hit the main accounts simultaneously.

## Anti-Detection & Human-Like Behavior

The bot mimics real human usage patterns to avoid detection:

- **Gaussian delays** -- Pauses cluster around a natural midpoint (not uniform random)
- **Micro-breaks** (10% chance) -- 60-180s pauses simulating checking texts, switching apps
- **Session startup jitter** -- 10s-4min random delay so nothing runs at exact times
- **Skip behavior** -- ~12% of posts are scrolled past without engaging
- **Profile browsing** -- Views user profile before following
- **Randomized session sizes** -- +/-30% variation per session
- **Multi-story viewing** -- Views 1-3 stories per user (not always just 1)
- **Selective commenting** -- ~28% of hashtag posts, ~25% of explore, ~45% of warm targets
- **Selective following** -- ~35% from hashtags, ~40% from warm audience, ~30% from explore
- **Satellite anti-detection** -- 20% random session skip, 2-8 min startup jitter, low daily limits

## Engagement Strategy (2026 Algorithm)

### Warm Audience Targeting (highest ROI)

Instead of follow/unfollow churn, the bot engages followers of similar niche accounts. These users already consume similar content and are 3-5x more likely to follow back.

- **5 warm sessions/day** per main account
- Target accounts: configurable per persona via `engagement.default_target_accounts` in persona JSON
- Per user: like 2-3 posts + genuine comment + optional follow (~40%)
- Smart follow targeting: micro-influencers (1K-50K followers) followed at 70% rate, others at 20%

### Viral Growth Features (2026 Algorithm)

| Feature | Impact | How It Works |
|---------|--------|-------------|
| **Video text overlays** | +80-150% watch completion | Bold on-screen hook/body/CTA on every Reel |
| **Snap zoom hook** | +40-60% 3-sec hold rate | Visual punch in first 0.5s |
| **Post-publish burst** | +50-100% reach per post | Pin CTA comment + instant story + mini engagement burst |
| **Viral auto-boost** | Snowball viral posts | Detects 2x+ avg engagement -> re-story + boost |
| ~~**Comment-to-DM**~~ | ~~5-10x follow-back rate~~ | **Disabled** -- AI DMs sound unnatural and cause unfollows |
| **Power user targeting** | +20-30% follow-back rate | Prioritize micro-influencers (1K-50K) |
| **Carousel montage** | +24% shares, +19% reach | 5-slide carousel -> 30s Reel with transitions |
| **Viral hook patterns** | Higher scroll-stop rate | POV:, numbers, curiosity gaps |
| **Satellite boost** | +3x early engagement | 3 accounts like+comment+save within 1hr of publish |
| **Cross-promo** | +20-30% cross-audience reach | Partner mentions + mutual engagement |

### Instagram Limits (per main account)

| Action | Daily Limit | Notes |
|--------|------------|-------|
| Likes | 400 | Spread across all sessions |
| Comments | 100 | AI-generated, context-aware |
| Follows | 120 | Smart targeting: 70% micro-influencers, 20% others |
| Story views | 150 | ~75% chance per user, ~35% like rate |
| Replies | 50 | On own posts (last 48h) -- reply to ALL |
| Unfollows | 60/run | After 2+ days |
| ~~Welcome DMs~~ | ~~15/day~~ | **Disabled** -- caused unfollows |
| ~~Comment DMs~~ | ~~8/day~~ | **Disabled** -- sounded unnatural |

### Satellite Limits (per satellite account)

| Action | Daily Limit | Notes |
|--------|------------|-------|
| Likes | 40 | Mostly on main accounts' posts |
| Comments | 6 | Only on main accounts' posts |
| Saves | 6 | Main accounts' posts only |
| Story views | 20 | Main accounts + light browsing |

### YouTube Limits (per main account)

| Action | Daily Limit | Notes |
|--------|------------|-------|
| Likes | 50 | Spread across 6 yt_engage sessions |
| Comments | 20 | AI-generated, quality comments only |
| Replies | 30 | On own video comments -- reply to ALL |

**API quota budget:** ~7,330 of 10,000 units/day (73% utilization -- safe margin).

**Warmup multiplier** for new accounts: 0.6x (days 1-7), 0.8x (days 8-14), 1.0x (day 15+).

## Video & Audio

- **Instagram Reels:** 1080x1350 (4:5), 7 seconds, Ken Burns zoom effect, SILENT (trending audio added at publish)
- **YouTube Shorts:** 1080x1920 (9:16), 10 seconds, Ken Burns zoom effect, WITH audio
- **YouTube audio priority:**
  1. Pixabay royalty-free tracks (if `PIXABAY_API_KEY` set)
  2. Custom tracks from `data/{persona}/generated_images/music/`
  3. Auto-generated ambient lo-fi pad (pink noise + Am7 chord)
- **Instagram audio:** Trending music overlay via Instagram music search API (30+ queries)

## Stories

- **3 story sessions/day** per main account
- Reposts 2-3 past posts with text overlays
- **Auto-downloads media from Instagram** if local files don't exist (works in CI)
- Interactive stickers: 35% poll, 30% question box (AMA), 20% quiz, 15% clean
- Auto-categorized into highlights (persona-specific categories)

## Daily Reports

End-of-day summary with engagement stats, posts published, YouTube channel stats, and growth signals.

**Telegram setup:**
1. Create a bot via @BotFather -> get token
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
| `make run` | Full pipeline: generate -> video -> publish (IG + YT) -> engage |
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
| `PERSONA` | Persona ID (`maya`, `aryan`, `sat1`, `sat2`, `sat3`) |
| `INSTAGRAM_USERNAME` | Instagram account username |
| `INSTAGRAM_PASSWORD` | Instagram account password |
| `GEMINI_API_KEY` | Google AI Studio API key ([free](https://aistudio.google.com/apikey)) |

**YouTube (optional but recommended for main accounts):**
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
| `ENGAGEMENT_TARGET_ACCOUNTS` | (from persona JSON) | Comma-separated similar accounts for warm targeting |

**Audio:**
| Variable | Default | Description |
|----------|---------|-------------|
| `PIXABAY_API_KEY` | -- | Pixabay API key for royalty-free YouTube audio ([free](https://pixabay.com/api/docs/)) |

**Other:**
| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_MODEL` | `gemini-2.5-flash` | Preferred Gemini model (auto-falls back to 4 others on rate limits) |
| `DRAFT_COUNT` | `3` | Posts to generate per run |
| `MIN_READY_QUEUE` | `5` | Min ready posts before generating more |
| `AUTO_MODE` | `false` | Enable auto publishing |
| `AUTO_PROMOTE_DRAFTS` | `false` | Auto-promote drafts to approved |
| `TELEGRAM_BOT_TOKEN` | -- | Telegram bot token for daily reports |
| `TELEGRAM_CHAT_ID` | -- | Telegram chat ID for daily reports |
| `ACCOUNT_CREATED_DATE` | -- | `YYYY-MM-DD` for warmup multiplier |

## GitHub Secrets Setup

Each account needs its own secrets:

| Secret | Purpose |
|--------|---------|
| `DOTENV` | Maya's .env (includes `PERSONA=maya`) |
| `INSTAGRAM_SESSION_B64` | Maya's IG session (base64-encoded) |
| `DOTENV_ARYAN` | Aryan's .env (includes `PERSONA=aryan`) |
| `INSTAGRAM_SESSION_B64_ARYAN` | Aryan's IG session |
| `DOTENV_SAT1` | Satellite 1's .env (includes `PERSONA=sat1`) |
| `INSTAGRAM_SESSION_B64_SAT1` | Satellite 1's IG session |
| `DOTENV_SAT2` | Satellite 2's .env |
| `INSTAGRAM_SESSION_B64_SAT2` | Satellite 2's IG session |
| `DOTENV_SAT3` | Satellite 3's .env |
| `INSTAGRAM_SESSION_B64_SAT3` | Satellite 3's IG session |

Shared API keys (GEMINI_API_KEY, PIXABAY_API_KEY) go in every account's .env file.

## Satellite Account Setup (Step-by-Step)

Satellites are lightweight Instagram accounts that boost engagement signals for your main accounts. They like, comment, save, and view stories on Maya's and Aryan's posts — acting like an organic engagement pod.

### Step 1: Create 3 Instagram Accounts

Create 3 new Instagram accounts. They don't need to look polished — just real enough:
- Add a profile picture (anything — a landscape, pet, food)
- Add a short bio (1 line, casual)
- Follow 20-30 random accounts (mix of interests)
- Post 2-3 photos (anything — food, scenery, random)
- Use each account normally for a day or two before activating the bot (Instagram flags brand-new accounts that immediately start engaging heavily)

**Tip:** Use different email addresses for each account. If you create them on the same phone, space them out over a few days.

### Step 2: Get Session Cookies

For each satellite account, you need to export the Instagram session cookie as base64. Run this **locally** (not in CI):

```bash
cd instagram_influencer

# For satellite 1:
PERSONA=sat1 INSTAGRAM_USERNAME=sat1_username INSTAGRAM_PASSWORD=sat1_password \
  python -c "
from publisher import _get_client
from config import load_config
import json, base64, os
os.environ['PERSONA'] = 'sat1'
os.environ['ENGAGEMENT_ENABLED'] = 'true'
cfg = load_config()
cl = _get_client(cfg)
settings = cl.get_settings()
b64 = base64.b64encode(json.dumps(settings).encode()).decode()
print(b64)
"
```

This prints a base64 string — that's your `INSTAGRAM_SESSION_B64_SAT1`.

Repeat for sat2 and sat3 with the appropriate usernames/passwords.

**Alternative (manual):** If the above doesn't work, you can log in via the bot once, then find the session file at `data/sat1/.ig_session.json` and encode it:

```bash
base64 -i instagram_influencer/data/sat1/.ig_session.json
```

### Step 3: Create .env Files for Each Satellite

Each satellite needs a minimal `.env` file. Create one per satellite:

**Satellite 1 `.env`:**
```env
PERSONA=sat1
INSTAGRAM_USERNAME=your_sat1_username
INSTAGRAM_PASSWORD=your_sat1_password
GEMINI_API_KEY=your_gemini_api_key
ENGAGEMENT_ENABLED=true
ENGAGEMENT_COMMENT_ENABLED=true
```

**Satellite 2 and 3:** Same format, just change `PERSONA=sat2`/`sat3` and the Instagram credentials.

**Notes:**
- Satellites don't need YouTube keys, Replicate/BFL/HF tokens, Pixabay keys, or Telegram keys
- They DO need `GEMINI_API_KEY` (for generating comments)
- They DO need `ENGAGEMENT_ENABLED=true` and `ENGAGEMENT_COMMENT_ENABLED=true`

### Step 4: Add GitHub Secrets

Go to your repo → Settings → Secrets and variables → Actions → New repository secret.

Add these 6 secrets (2 per satellite):

| Secret Name | Value |
|------------|-------|
| `DOTENV_SAT1` | Paste the entire contents of satellite 1's `.env` file |
| `INSTAGRAM_SESSION_B64_SAT1` | The base64 string from Step 2 |
| `DOTENV_SAT2` | Satellite 2's `.env` contents |
| `INSTAGRAM_SESSION_B64_SAT2` | Satellite 2's base64 session |
| `DOTENV_SAT3` | Satellite 3's `.env` contents |
| `INSTAGRAM_SESSION_B64_SAT3` | Satellite 3's base64 session |

### Step 5: Test with Manual Dispatch

Before waiting for the cron schedule, test each satellite manually:

1. Go to **Actions** tab in your GitHub repo
2. Click **Satellite 1** in the left sidebar
3. Click **Run workflow** → choose `sat_boost` → click **Run workflow**
4. Watch the logs to confirm it logs in, finds Maya's and Aryan's posts, and engages

Repeat for Satellite 2 and Satellite 3.

### Step 6: Done!

The satellites will now run automatically on their cron schedules (6 sessions/day each). They'll:
- Boost both Maya's and Aryan's posts 3x/day (`sat_boost`)
- Do light background browsing 3x/day (`sat_background`)
- Skip ~20% of sessions randomly (anti-detection)
- Wait 2-8 minutes before starting each session (jitter)

**Troubleshooting:**
- If a satellite fails to log in, re-export the session cookie (Step 2) and update the `INSTAGRAM_SESSION_B64_SATx` secret
- Instagram sessions expire after ~90 days — you'll need to refresh them periodically
- If you see "challenge required" errors, log into the account manually on your phone, complete any verification, then re-export the session

## Files

```
instagram_influencer/
  config.py              # Configuration (~35 env vars, persona-aware)
  persona.py             # Persona loader (JSON -> runtime config)
  orchestrator.py        # Pipeline CLI (single entry point, multi-account)
  generator.py           # Caption generation (Gemini + template fallback)
  image.py               # Manual image system (prompts + pending/ lookup)
  audio.py               # Background music (Pixabay + user tracks + ambient)
  video.py               # Ken Burns effect (IG silent + YT with audio)
  publisher.py           # Instagram publishing (reels, carousels, photos)
  youtube_publisher.py   # YouTube Shorts publishing (OAuth2 + Data API v3)
  youtube_engagement.py  # YouTube engagement (like, comment, reply on Shorts)
  engagement.py          # Instagram engagement (warm targeting/hashtags/explore/replies)
  satellite.py           # Satellite account engagement (boost main accounts)
  cross_promo.py         # Cross-promotion between main accounts
  stories.py             # Story reposting + highlights + interactive stickers
  report.py              # Daily report (Telegram + GitHub Actions + YT stats)
  rate_limiter.py        # Action rate limiting + warmup multiplier
  gemini_helper.py       # Gemini API with model rotation (5 models, 100+ RPM)
  post_queue.py          # Queue I/O (content_queue.json)
  instagrapi_patch.py    # Monkey-patches for instagrapi resilience
  scheduler.py           # macOS launchd scheduler

  personas/              # Persona JSON files
    maya.json            # Maya Varma (fashion, main)
    aryan.json           # Aryan Dhar (fitness, main)
    sat1.json            # Satellite 1
    sat2.json            # Satellite 2
    sat3.json            # Satellite 3

  reference/             # Reference photos per persona
    maya/
    aryan/

  data/                  # Per-persona state directories
    maya/
      content_queue.json
      engagement_log.json
      followers.json
      highlights.json
      .ig_session.json
      daily_report.md
      generated_images/
        pending/         # Place generated images here
        prompts/
        music/           # Custom background music
        IMAGE_PROMPTS.md # Master prompt summary
    aryan/
      (same structure)
    sat1/
      engagement_log.json
      .ig_session.json
      followers.json
    sat2/
      (same as sat1)
    sat3/
      (same as sat1)
```
