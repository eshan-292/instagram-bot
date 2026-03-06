# Instagram + YouTube Influencer Bot

Multi-account automated growth pipeline for AI influencers — currently running **6 main accounts** across fashion, fitness, lifestyle, relationships, and engagement niches, plus 3 satellite support accounts.

Posts to **Instagram** (Reels, Carousels, Single) and **YouTube Shorts** simultaneously, with aggressive engagement automation on both platforms.

```
Gemini (captions) -> Image gen (Gemini app) -> ffmpeg (video) -> Publish (IG + YT) -> Engage (both)
```

## Architecture: Multi-Account Persona System

The bot uses a **persona-based architecture** where all account-specific data (identity, voice, templates, hashtags, etc.) lives in JSON files. The codebase is fully shared — each account gets its own persona JSON, state directory, GitHub secrets, and workflow files.

```
personas/
  maya.json          # Maya Varma — fashion influencer (main)
  aryan.json         # Aryan Dhar — fitness influencer (main)
  choosewisely.json  # Choose Wisely — engagement/polls page (main)
  moderntruths.json  # Modern Truths — relationships/psychology page (main)
  sofia.json         # Sofia Petrova — luxury fashion influencer (main)
  rhea.json          # Rhea — fitness creator (main)
  sat1.json          # Satellite support account 1
  sat2.json          # Satellite support account 2
  sat3.json          # Satellite support account 3

data/
  maya/              # Maya's state (queue, engagement log, images, session)
  aryan/             # Aryan's state
  choosewisely/      # Choose Wisely's state
  moderntruths/      # Modern Truths' state
  sofia/             # Sofia's state
  rhea/              # Rhea's state
  sat1/              # Satellite 1 state (lightweight)
  sat2/
  sat3/
```

**Persona selection** is via the `PERSONA` env var (e.g. `PERSONA=aryan`). Each GitHub Actions workflow sets this in its `.env` file.

### Main Accounts (Full Pipeline)
- **Maya Varma** (`@themayavarma`) — 23yo fashion influencer from Mumbai. Bold, teasing, confident voice.
- **Aryan Dhar** (`@aryandharfit`) — 25yo fitness influencer from Delhi. Confident, disciplined, motivating, no-BS.
- **Choose Wisely** (`@choose.wsly`) — Engagement/polls page. Micro-decision content with bold graphics. Provocative, punchy voice.
- **Modern Truths** (`@moderntruths7`) — Relationships/psychology page. Dark moody aesthetic, bold typography. Polarizing, unfiltered voice.
- **Sofia Petrova** (`@sofia.ptrv`) — 24yo Russian luxury fashion influencer in Mumbai. Mysterious, teasing, high-value energy.
- **Rhea** (`@rheatrains`) — 23yo Indian fitness creator from Gurgaon. Disciplined, calm, no-nonsense voice.

All 6 get: content generation, image prompts, video creation, IG publishing, full engagement (warm audience, hashtags, explore, replies, stories). Maya, Aryan, and Rhea also have YouTube Shorts.

### Satellite Accounts (Engagement Support)
3 lightweight accounts that boost engagement signals for both main accounts:
- Like, comment, and save main accounts' posts
- View main accounts' stories
- Do light background engagement to appear human
- Anti-detection: 20% random session skip, extended jitter, low daily limits

### Cross-Promotion (Full Mesh Network)
All 6 main accounts aggressively promote ALL other 5 accounts:
- Each account has `cross_promo.partners: [all other 5]` — full mesh, not just pairs
- Per partner: like + save recent posts, comment (up to 4/day), like comments, reply, view + like stories, share via DM
- Partners shuffled each session so all get equal engagement
- `partner_mention_probability: 0` for ALL accounts — zero @mentions in captions or stories
- Accounts appear completely independent to outside observers
- Satellite accounts engage all 6 main accounts (boost_targets shuffled for fairness)
- Max 4 partner comments/day per partner to stay subtle

## How It Works

1. **Generate captions** -- Gemini creates posts in the persona's voice (auto-rotates models on rate limits)
2. **Generate image prompts** -- Bot creates Gemini-ready prompts and saves to `IMAGE_PROMPTS.md`
3. **You generate images** -- Copy prompts into the Gemini app, save images to `data/{persona}/generated_images/pending/`
4. **Bot picks up images** -- Links images to drafts and promotes them
5. **Convert to video** -- Ken Burns effect (IG silent, YT with royalty-free music)
6. **Publish to both platforms** -- Instagram via instagrapi + YouTube Shorts via YouTube Data API
7. **Engage aggressively** -- Warm audience targeting, hashtag engagement, replies, stories on both platforms

Post lifecycle: `draft` -> `approved` -> `ready` -> `posted` (IG + YT simultaneously)

## Viral Content Engine (Gemini Text API → Automatic)

The viral content engine runs **automatically** — no extra setup needed beyond a `GEMINI_API_KEY`. Every time the bot generates new content, it produces algorithm-optimized viral posts.

### How It Works (Zero Manual Effort for Captions)

1. **Bot runs content generation** (via schedule or manually):
   ```bash
   cd instagram_influencer
   python orchestrator.py --persona maya --queue-file data/maya/content_queue.json
   ```

2. **Gemini text API (free)** generates viral-optimized captions automatically:
   - Checks **day of week** → injects today's **recurring series** (e.g., "Friday Fits" on Friday)
   - Rolls for **controversy mode** (30% chance) → injects hot-take topics + controversy hooks
   - Samples **3 random viral formats** from 8 options (before/after, ranking, wait-for-it, this-or-that, POV, curiosity gap, rate 1-10, myth buster)
   - Injects **send engineering** triggers (make viewer think of ONE person to send it to)
   - Applies **viral hook formulas** (contrarian claims, price shocks, FOMO, forbidden knowledge)
   - Builds **curiosity gap architecture** (open loops, delayed payoffs)
   - Generates **video text overlays** (3 lines for on-screen display — 85% watch on mute)

3. **Dual-format companions** — after generating drafts, 30% get a companion post in the alternate format (carousel↔reel) scheduled +24h later. Same topic, double reach.

4. **IMAGE_PROMPTS.md** is created at `data/{persona}/generated_images/IMAGE_PROMPTS.md` with ready-to-paste image prompts for each post.

### Image Generation (Manual — Gemini App)

The Gemini API free tier does NOT include image generation, so images are generated manually via the [Gemini app](https://gemini.google.com/) (which does support free image gen):

1. **Open `IMAGE_PROMPTS.md`** — lists every post needing images with exact prompts
2. **Paste each prompt** into the Gemini app → download the generated image
3. **Place images** in the correct paths:

   | Post Type | Where to Put It |
   |-----------|----------------|
   | **Reel / Single** | `data/{persona}/generated_images/pending/{post-id}.jpg` |
   | **Carousel** | `data/{persona}/generated_images/pending/{post-id}/1.jpg`, `2.jpg`, `3.jpg`... |

4. **Commit and push** the images:
   ```bash
   git add -f instagram_influencer/data/{persona}/generated_images/pending/
   git commit -m "add images for {post-ids}"
   git push
   ```

5. **Bot handles the rest automatically** on the next scheduled run:
   - Scans `pending/` → finds images → links to drafts
   - **Auto-crops "Made with Google AI" watermark** (bottom 5%)
   - Converts to video (Ken Burns zoom, IG silent + YT with music)
   - Promotes and publishes at the next scheduled slot

### What Gets Generated Automatically vs Manually

| Component | How | Cost |
|-----------|-----|------|
| **Captions** (viral hooks, CTAs, controversy) | Gemini text API | Free |
| **Video text overlays** (3 on-screen lines) | Gemini text API | Free |
| **YouTube titles** (curiosity gap) | Gemini text API | Free |
| **Series detection** (day-of-week matching) | Code logic | Free |
| **Dual-format companions** | Code logic | Free |
| **Trending hashtags** (daily refresh) | Gemini text API | Free |
| **AI comments** (IG + YT engagement) | Gemini text API | Free |
| **Images** | Manual via Gemini app | Free |

## Content Strategy (2026 Algorithm)

| Format | % of Content | Why |
|--------|-------------|-----|
| **Hook-Photo Reels** (8-10 sec) | 60% | THE dominant format. Bold text hooks + 1-2 photos. Highest watch-through, easiest to produce. |
| **Carousels** (5-6 slides) | 20% | High saves — used only when 5+ slides are genuinely needed. |
| **Reels/Shorts** (7-10 sec) | 10% | Single-image Ken Burns reels for simple reveals. |
| **Single images** | 10% | Aesthetic/editorial brand posts. |

**Caption strategy (optimized for "sends" -- the #1 algorithm signal in 2026):**
- Scroll-stopping hook in first 3 words (number, question, or bold statement)
- Front-loaded searchable keywords (Instagram = search engine now)
- Question in every caption (drives comments = algorithm boost)
- Every caption ends with a send/share CTA: "Send this to someone who...", "Tag your bestie"
- `alt_text` on every post (accessibility + Instagram SEO)
- 3-5 hashtags in caption (pyramid: 1 brand + 1 broad + 2 medium + 1 niche)
- **30 total hashtags** (Instagram max) — caption tags + first comment fills remaining slots with ~60% niche/persona + ~40% trending hashtags (fetched daily via Gemini, even if irrelevant — maximum exposure)
- Like counts hidden on all posts (reduces comparison anxiety, boosts engagement)
- No cross-platform mentions in captions (IG and YT kept separate)

### Hook-Photo Reels (2026 Viral Format — 60% of All Content)

The dominant content format — bold text hooks interleaved with 1-2 photos. Maximum impact, minimum production effort:

```
1-photo reel (PREFERRED): [HOOK TEXT] → [Photo] → [BRIDGE TEXT] → [CTA TEXT] = 8s
2-photo reel:              [HOOK TEXT] → [Photo 1] → [BRIDGE] → [Photo 2] → [CTA] = 10s
```

- **Dark background + bold white text** for hook/bridge slides (auto-generated via PIL)
- **2 seconds per frame** — fast-paced, punchy, matches 8-second attention span
- **Snap-zoom effect** on every frame for visual punch
- **Gold CTA text** on final frame drives saves and sends
- Only needs **1-2 photos** per post (vs 5-6 for carousels = much less production work)

**Proven viral hook formulas (2026):**
- Curiosity gap: "This feels illegal to know." / "I probably shouldn't share this, but..."
- Contrarian claim: "Everyone's doing this wrong." / "Stop doing [X]. Do this instead."
- Price shock: "This costs Rs [low number]. No, seriously."
- POV: "POV: you walk in wearing this" / "If you've ever [relatable thing]..."
- Forbidden knowledge: "Your [expert] won't tell you this."
- Bold statement: "This will get me cancelled but..." / "I said what I said."
- Specificity: "3 things. 15 seconds." / "Rs 800. 3 outfits."

To create hook-photo reels: set `post_type: "reel"` + `reel_format: "hook_photo"` in content queue. Include `slides` (1-2 photo descriptions) and `video_text` (hook/bridge/CTA text). Place photos in `pending/{post-id}/1.jpg` (single) or `pending/{post-id}/1.jpg, 2.jpg` (double).

### Smart Unfollow (Non-Followers Only)

The unfollow system now checks the followers API before unfollowing:
- **Only unfollows non-followers** — people who didn't follow back after 2 days
- **Keeps mutual followers** — preserves relationships with people who followed back
- **150/day limit** — aggressive pace to make room for new growth follows
- Refreshes followers list from API + cached file for accuracy

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

### Custom Background Music

Place your own `.mp3` or `.wav` files in `data/{persona}/generated_images/music/` and the bot will use them as background tracks for YouTube Shorts. If no custom music is provided, it fetches royalty-free tracks from Pixabay, or falls back to a generated ambient lo-fi pad.

### Image Notes
- Image filenames must match the post ID exactly (e.g., `maya-042.jpg` for post `maya-042`)
- Supported formats: `.jpg`, `.jpeg`, `.png`, `.webp`
- Minimum file size: 10 KB (smaller files are ignored)
- Carousel posts need at least 2 images in the folder

---

## Daily Schedule (GitHub Actions -- Parallel Multi-Workflow)

### Workflow Architecture

11 independent workflows run in parallel with separate concurrency groups:

| Workflow | Sessions/Day | Concurrency Group | Purpose |
|----------|-------------|-------------------|---------|
| `instagram-bot.yml` | 33 | `instagram-bot-maya` | Maya IG |
| `youtube-bot.yml` | 22 | `youtube-bot` | Maya YT |
| `instagram-bot-aryan.yml` | 33 | `instagram-bot-aryan` | Aryan IG |
| `youtube-bot-aryan.yml` | 22 | `youtube-bot-aryan` | Aryan YT |
| `instagram-bot-choosewisely.yml` | 30 | `instagram-bot-choosewisely` | Choose Wisely IG |
| `instagram-bot-moderntruths.yml` | 30 | `instagram-bot-moderntruths` | Modern Truths IG |
| `instagram-bot-sofia.yml` | 30 | `instagram-bot-sofia` | Sofia IG |
| `instagram-bot-rhea.yml` | 30 | `instagram-bot-rhea` | Rhea IG |
| `youtube-bot-rhea.yml` | 22 | `youtube-bot-rhea` | Rhea YT |
| `satellite-1.yml` | 9 | `satellite-1` | Satellite 1 |
| `satellite-2.yml` | 9 | `satellite-2` | Satellite 2 |
| `satellite-3.yml` | 9 | `satellite-3` | Satellite 3 |

**Total: ~283 sessions/day** across all accounts (12 workflows).

**1 post/day per main account** with 2 publish windows (backup at lunch if evening fails):
- **Primary (7 PM IST):** Maya 19:00, Aryan 19:15, CW 19:33, MT 19:39, Sofia 19:47, Rhea 19:53
- **Backup (12:30 PM IST):** Maya 12:30, Aryan 12:45, CW 12:33, MT 12:39, Sofia 12:47, Rhea 12:53

The orchestrator publishes at most 1 post/day — if the lunch window publishes, the evening one finds nothing eligible and skips.

**New accounts (Choose Wisely, Modern Truths, Sofia, Rhea):** Workflows are disabled until sessions are seeded locally via `seed_session.py`.

**Reliability:** Session routing uses `github.event.schedule` (the exact cron expression) instead of wall-clock time, making it immune to GitHub Actions cron delays (which can be 10-20+ minutes). State commits add each file individually (avoiding failures from missing files), use `git pull --rebase` before push, and retry up to 3 times on push failure to handle parallel workflow race conditions.

### Maya Instagram Schedule (29 sessions)

| IST Time | Session | Notes |
|----------|---------|-------|
| 07:00 | Morning engagement | Wake up, check overnight |
| 07:40 | Explore | Morning scroll |
| 08:15 | Commenter target | Highest-ROI targeting |
| 08:50 | Hashtags | |
| 09:30 | Replies | |
| 10:05 | Stories | |
| 10:40 | Explore | |
| 11:15 | Hashtags | |
| 11:50 | Warm audience | Pre-lunch targeting |
| 12:30 | **BACKUP PUBLISH** + Explore | Lunch fallback if 7 PM fails |
| 13:05 | Hashtags | |
| 13:40 | Replies | |
| 14:15 | Warm audience | Afternoon targeting |
| 14:50 | Commenter target | Afternoon targeting |
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

### YouTube Schedules (22 sessions each — INDEPENDENT PUBLISHING)

Maya, Aryan, and Rhea each get 22 YT sessions/day (alternating engage/replies every 45 min, 6 AM to 10 PM IST). Aryan's are staggered +15 min, Rhea's offset by +10 min. Daily limits: 500 likes, 200 comments, 250 replies. YouTube has no action blocks so engagement is fully maxed out.

**Aryan + Rhea share the same Google Cloud project** (shared 10K quota/day). Maya has her own project. Each persona publishes max 1 Short per publish window.

**YouTube publishing is fully independent of Instagram.** Each YT workflow has **2 publish windows** (lunch + prime time) using `--yt-publish-only`, each publishing 1 Short per window. If Instagram is disabled or broken, YouTube Shorts still get published on schedule.

**YouTube growth optimizations (2026):**
- **Auto-pin creator comment** — After every YT Short publish, a discussion-sparking comment is posted (Gemini-generated, e.g. "Which one was your favorite? Drop a number"). Creator comments show prominently with a badge, driving 30%+ more replies
- **Multi-post per window** — Each publish window uploads up to 2 Shorts (total 4-6/day across 3 windows)
- **Post-publish reply blitz** — Immediately after publishing, the bot checks for early comments and replies within the first 60 minutes (critical algorithm signal for distribution)
- **Hyper-specific comments** — AI comments analyze video titles deeply and reference specific details (technique, product, number) to drive profile visits
- **Hindi + seasonal niche queries** — 35+ queries per account including Hindi-language searches, festival-specific content (Holi, Diwali, Navratri), and seasonal trends

### Satellite Schedules (9 sessions each)

| IST Time | Session | Purpose |
|----------|---------|---------|
| 08:00/08:20/08:40 | sat_boost | Morning boost |
| 10:00/10:20/10:40 | sat_background | Background engagement |
| 12:00/12:20/12:40 | sat_boost | Midday boost |
| 14:00/14:20/14:40 | sat_background | Background engagement |
| 16:00/16:20/16:40 | sat_boost | Afternoon boost |
| 18:00/18:20/18:40 | sat_background | Background engagement |
| 20:00/20:20/20:40 | sat_boost | Post-publish boost |
| 21:00/21:20/21:40 | sat_boost | Prime time boost |
| 22:00/22:20/22:40 | sat_background | Final background pass |

Satellites are staggered (SAT1 at :00, SAT2 at :20, SAT3 at :40) so they don't hit the main accounts simultaneously.

## Anti-Detection & Human-Like Behavior

The bot mimics real human usage patterns to avoid detection:

- **Gaussian delays** -- Pauses cluster around a natural midpoint (not uniform random)
- **Micro-breaks** (1% chance) -- 10-25s pauses simulating switching apps
- **Session startup jitter** -- 3-30s random delay so nothing runs at exact times
- ~~**Skip behavior**~~ -- **Disabled** — engage with everything for maximum growth
- **Profile browsing** -- Views user profile before following
- **Randomized session sizes** -- +/-30% variation per session
- **Multi-story viewing** -- Views 1-3 stories per user (not always just 1)
- **Maximum commenting** -- comment on EVERY post (no probability gating)
- **Maximum following** -- follow EVERY user encountered (no probability gating)
- **Follow circuit breaker** -- Stops follow attempts after 3 consecutive rate limits (avoids wasting time on blocked follows)
- **Gemini cooldown** -- When all 4 AI models are rate-limited, enters 5-min cooldown (skips AI generation instantly instead of retrying)
- **Minimal API delays** -- `delay_range=[1,3]` per API call, 2-8s between engagement actions
- **Satellite jitter** -- 30-90s startup jitter, low daily limits
- **User PK caching** -- Satellite accounts cache Instagram user PKs to avoid rate-limited username lookups (429 errors)
- **Session health check** -- Detects stale/web-origin sessions (403 errors) and forces fresh mobile login
- **Silent session restore** -- Bot restores saved sessions WITHOUT calling login() — avoids triggering Instagram challenges from datacenter IPs
- **Action-block detection** -- Detects Instagram action blocks (consecutive 403s) and aborts sessions early instead of wasting time
- **Private API profile browsing** -- Uses `user_info_v1()` (private API) instead of `user_info()` (public web API) to avoid 429 rate limits that cause multi-minute retries
- **Session cache poisoning protection** -- Only caches sessions after successful bot runs; uses GitHub Actions `cache-matched-key` to distinguish restored cache from stale repo checkout files
- **Local session seeding** -- `seed_session.py` creates sessions from your laptop (your IP/device), avoiding datacenter red flags
- **Retry with exponential backoff** -- API calls retry 3x with increasing wait (15s, 30s, 60s) on rate limits

## Engagement Strategy (2026 Algorithm)

### Big Account Filter (10K+ followers only)

All engagement is **filtered to big pages only** — accounts below 10K followers are skipped entirely. Commenting on big accounts (10K-1M+) means our profile is seen by thousands of their followers. This is the #1 growth driver.

- **Hashtag mining**: Fetches BOTH top posts + recent posts → filtered to 10K+ follower accounts only
- **Explore feed**: Filtered to 10K+ follower accounts only, sorted by reach
- **Post-publish burst**: Only engages big accounts for maximum visibility
- **Warm audience**: Unfiltered (pre-vetted niche followers, always high quality)
- **Configurable thresholds**: `ENGAGEMENT_MIN_FOLLOWERS_HASHTAG` (default 10K), `ENGAGEMENT_MIN_FOLLOWERS_WARM` (default 0)
- **Like count fallback**: When follower count isn't available, uses like count as proxy (500 likes ≈ 10K+ followers)
- **Smart follow**: Only follow micro-influencers (1K-50K followers, active, public) — 20-30% follow-back rate vs 5% for random

### Warm Audience Targeting (high ROI)

Engages followers of similar niche accounts. These users already consume similar content and are 3-5x more likely to follow back.

- **5+ warm sessions/day** per main account
- Target accounts: configurable per persona via `engagement.default_target_accounts` in persona JSON
- Per user: like 2-3 posts + genuine comment + follow (quality targets only)
- Smart quality filtering: skip follow-farms, inactive accounts, private profiles

### Commenter Targeting (highest ROI — NEW)

Follows and engages people who **comment on big niche pages**. Commenters follow back 3-5x more than random followers because they're actively engaged, not passive scrollers.

- **2 commenter_target sessions/day** per account (morning + afternoon)
- Mines commenters from `engagement_target_accounts` posts (same pool as warm audience)
- Triple-touch per commenter: like 1-2 posts + comment + follow + view stories
- Quality-filtered: only 500-100K follower public accounts with 10+ posts
- Expected 30-40% follow-back rate (vs 20% for warm, 5% for random)

### Instant Pod Boost (cross-promo velocity)

Auto-boosts fresh partner posts at the **start of every engagement session**. Instagram's algorithm heavily weights engagement velocity in the first 30 minutes.

- Runs at the top of every session (except report/maintenance/stories)
- Detects partner posts < 3 hours old via `cross_promo.partners` list
- Per fresh post: like + save (strongest signal) + comment
- Tracks via `pod_boost` action to avoid re-boosting
- Result: fresh posts get engagement from 4-5 accounts within minutes of publishing

### Viral Growth Features (2026 Algorithm)

| Feature | Impact | How It Works |
|---------|--------|-------------|
| **Video text overlays** | +80-150% watch completion | Bold on-screen hook/body/CTA on every Reel |
| **Snap zoom hook** | +40-60% 3-sec hold rate | Visual punch in first 0.5s |
| **Post-publish burst** | +50-100% reach per post | Pin CTA comment + instant story reshare (post image + link sticker) + mini engagement burst |
| **Viral auto-boost** | Snowball viral posts | Detects 2x+ avg engagement -> reshare to story + boost |
| **DM replies** | +15-25% retention | AI replies to incoming DMs — contextual, persona-voice, 25/day limit |
| ~~**Comment-to-DM**~~ | ~~5-10x follow-back rate~~ | **Disabled** -- AI DMs sound unnatural and cause unfollows |
| **Trending hashtags** | +30-50% discovery | Gemini fetches 20 trending hashtags daily, fills all 30 slots |
| **Power user targeting** | +20-30% follow-back rate | Prioritize micro-influencers (1K-50K) |
| **Carousel montage** | +24% shares, +19% reach | 5-slide carousel -> 30s Reel with transitions |
| **Viral hook patterns** | Higher scroll-stop rate | Contrarian claims, price shocks, FOMO triggers, curiosity gaps, pattern interrupts |
| **Viral content formats** | +2-3x completion rate | Before/after reveals, ranking/tier lists, "wait for it", this-or-that debates, POV stories |
| **Curiosity gap architecture** | +4-7x impressions | Open loops in every caption — viewers MUST finish to resolve; delayed payoffs |
| **YT auto-pin comment** | +30% replies | Gemini-generated discussion question posted as creator on every Short |
| **YT post-publish blitz** | Critical algo signal | Reply to early comments within 60 minutes of publishing |
| **YT multi-post publishing** | +3.2x sub growth | 1 Short per window × 2 publish windows/day |
| **Hindi + seasonal queries** | +40% engagement pool | 35+ queries including Hindi, festivals (Holi/Diwali/Navratri), seasonal trends |
| **Hyper-specific YT comments** | +2x profile visits | AI analyzes video titles deeply, references specific details, asks follow-up questions |
| **Satellite boost** | +3x early engagement | 3 accounts: like+comment+save+comment-like+reply+story-like+DM-share |
| **Cross-promo** | +20-30% cross-audience reach | Partner: like+save+comment+comment-like+reply+story-like+DM-share |
| **Commenter targeting** | +80-120 followers/day | Follow people who comment on big niche pages (3-5x follow-back rate) |
| **Instant pod boost** | +5-10 followers/day | Auto-boost fresh partner posts at every session start (< 3hr old → like+save+comment) |
| **Recurring series** | +30-50% retention | Named series per persona posted on specific days (e.g. "Friday Fits", "Red Flag Friday") — trains audience to come back |
| **Send engineering** | +40-60% DM shares | Content engineered to trigger "send to a specific friend" impulse — debate posts, checklists, relatable moments |
| **Controversy/hot-take ratio** | +3-5x comments & sends | ~30% of content is polarizing hot takes — splits audience 50/50 for maximum engagement |
| **Dual-format posting** | +2x reach per idea | ~30% of posts get a companion in alternate format (carousel↔reel) scheduled +24h — same topic, double reach |
| **Interactive formats** | +50-100% shares | Rate Your Life, elimination brackets, starter packs, compatibility tests (Choose Wisely) |

### Recurring Content Series

Named series create audience anticipation and train followers to return on specific days. Generator detects day-of-week and injects the matching series into the Gemini prompt. Series posts get a dedicated hashtag in captions.

| Persona | Series | Day | Format |
|---------|--------|-----|--------|
| **Maya** | Friday Fits | Fri | Carousel |
| **Maya** | One Piece 5 Ways | Tue | Carousel |
| **Maya** | Mumbai GRWM | Wed | Reel |
| **Maya** | Style Debate | Sun | Reel |
| **Aryan** | Monday Myth Buster | Mon | Carousel |
| **Aryan** | Full Day of Eating | Fri | Carousel |
| **Aryan** | Form Check Friday | Fri | Reel |
| **Aryan** | No Excuses Workout | Wed | Reel |
| **Choose Wisely** | Would You Rather Wednesday | Wed | Carousel |
| **Choose Wisely** | Only One Can Stay | Mon | Carousel |
| **Choose Wisely** | Rate Your Life | Fri | Carousel |
| **Choose Wisely** | Starter Pack Sunday | Sun | Carousel |
| **Modern Truths** | Red Flag Friday | Fri | Carousel |
| **Modern Truths** | Harsh Truth Tuesday | Tue | Single |
| **Modern Truths** | What X Actually Means | Wed | Carousel |
| **Modern Truths** | Psychology Says | Sun | Carousel |
| **Sofia** | Luxury Lookbook Friday | Fri | Carousel |
| **Sofia** | Old Money Monday | Mon | Single |
| **Sofia** | Mumbai Luxury Guide | Wed | Carousel |
| **Rhea** | Workout Wednesday | Wed | Reel |
| **Rhea** | Meal Prep Monday | Mon | Carousel |
| **Rhea** | 5 AM Club | Fri | Reel |
| **Rhea** | Form Check Friday | Fri | Carousel |

### Instagram Limits (per main account)

| Action | Daily Limit | Notes |
|--------|------------|-------|
| Likes | 500 | Spread across all sessions |
| Comments | 250 | AI-generated (Gemini) with fallback pool when rate-limited |
| Follows | 400 | Smart targeting: only 1K-50K micro-influencers (20-30% follow-back) |
| Story views | 150 | 100% view, 100% like rate |
| Replies | 50 | On own posts (last 48h) -- reply to ALL |
| DM replies | 25 | AI-generated contextual replies to incoming DMs (with fallback pool) |
| Unfollows | 120/run | After 2+ days |
| ~~Welcome DMs~~ | ~~15/day~~ | **Disabled** -- caused unfollows |
| ~~Comment DMs~~ | ~~8/day~~ | **Disabled** -- sounded unnatural |

### Satellite Limits (per satellite account)

| Action | Daily Limit | Notes |
|--------|------------|-------|
| Likes | 150 | Main accounts' posts + background hashtags |
| Comments | 25 | On main accounts' posts (comments + replies) |
| Saves | 25 | Main accounts' posts |
| Story views | 80 | Main accounts + background browsing |
| Comment likes | 60 | Like top comments on main accounts' posts |
| Story likes | 40 | Like main accounts' stories |
| ~~Story reposts~~ | ~~5~~ | **Disabled** -- satellites should not post stories |
| DM shares | 12 | Share main accounts' posts between satellites |

### YouTube Limits (per main account)

| Action | Daily Limit | Notes |
|--------|------------|-------|
| Likes | 500 | Spread across 24 yt_engage sessions (no restrictions on YT) |
| Comments | 200 | AI-generated hyper-specific, 80% comment rate — max engagement |
| Replies | 250 | On own video comments + post-publish blitz — reply to ALL |
| Shorts published | 2 | 2 publish windows × 1 per window (quota-conservative) |
| Creator comments | 2 | Auto-posted on every published Short |

**API quota budget:** Maxed out. 60 videos/session, 4 queries/session, 25 results/query. YouTube has no action blocks like Instagram.

**Warmup multiplier** for new accounts: 0.6x (days 1-3), 0.8x (days 4-7), 1.0x (day 8+).

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

## Session Management

Instagram sessions are created locally on your laptop (where challenges can be completed interactively) and then used by the bot in GitHub Actions.

### Why Local Seeding?

The bot runs on GitHub Actions (US datacenter IPs). If it tries to `login()` from there, Instagram sees a new device from a suspicious location and triggers a **challenge** (email/SMS verification). Since the bot can't complete challenges, the session fails.

**Solution:** Create sessions from your laptop (your real IP + network), export them, and let the bot use them silently — no re-login, no challenges.

### Seeding Sessions

```bash
# Interactive — pick accounts
python seed_session.py

# Seed specific accounts
python seed_session.py maya aryan choosewisely moderntruths sofia rhea

# Seed all 9 + push to GitHub secrets
python seed_session.py --all --push

# Seed one + push
python seed_session.py sat1 --push
```

The script:
1. Logs in from YOUR device (your IP, your network)
2. If Instagram asks for verification, you enter the code interactively
3. Exports the session file
4. Optionally pushes it to GitHub secrets (`--push`)

### When to Re-Seed

- After an account gets **action-blocked** (you'll see 🔴 alerts on Telegram)
- After **changing a password**
- If the bot reports **"ChallengeRequired"** errors
- Sessions typically last **2-4 weeks** before needing refresh



### Per-Session Telegram Alerts

Every engagement session (main accounts + satellites) sends a real-time Telegram alert:
- 🟢 **OK** — session completed with engagement actions
- 🟡 **ZERO ACTIONS** — session ran but no actions completed (rate limit / session issue)
- 🔴 **FAILED** — session crashed with an error

### Daily Report

End-of-day summary at 23:15 IST with engagement stats, posts published, YouTube channel stats, and growth signals.

**Telegram setup:**
1. Create a bot via @BotFather -> get token
2. Send a message to your bot, then get chat ID from `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Add to `.env` (for ALL accounts — main AND satellites):
   ```
   TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxx
   TELEGRAM_CHAT_ID=123456789
   ```
4. **Important:** Ensure these tokens are in EVERY DOTENV secret (DOTENV, DOTENV_ARYAN, DOTENV_CHOOSEWISELY, DOTENV_MODERNTRUTHS, DOTENV_SOFIA, DOTENV_RHEA, DOTENV_SAT1/2/3)

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
| `PERSONA` | Persona ID (`maya`, `aryan`, `choosewisely`, `moderntruths`, `sofia`, `rhea`, `sat1`, `sat2`, `sat3`) |
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
| `ENGAGEMENT_DAILY_LIKES` | `500` | Max likes/day |
| `ENGAGEMENT_DAILY_COMMENTS` | `250` | Max comments/day |
| `ENGAGEMENT_DAILY_FOLLOWS` | `400` | Max follows/day |
| `ENGAGEMENT_COMMENT_ENABLED` | `false` | Enable AI comments on other posts |
| `ENGAGEMENT_FOLLOW_ENABLED` | `false` | Enable auto-follow |
| `ENGAGEMENT_TARGET_ACCOUNTS` | (from persona JSON) | Comma-separated similar accounts for warm targeting |
| `ENGAGEMENT_MIN_FOLLOWERS_HASHTAG` | `10000` | Min followers for hashtag/explore engagement targets |
| `ENGAGEMENT_MIN_FOLLOWERS_WARM` | `0` | Min followers for warm audience targets (0 = unfiltered) |
| `ENGAGEMENT_DM_REPLIES_ENABLED` | `true` | Enable AI DM reply automation |
| `ENGAGEMENT_DAILY_DM_REPLIES` | `25` | Max DM replies/day |

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
| `DOTENV_CHOOSEWISELY` | Choose Wisely's .env (includes `PERSONA=choosewisely`) |
| `INSTAGRAM_SESSION_B64_CHOOSEWISELY` | Choose Wisely's IG session |
| `DOTENV_MODERNTRUTHS` | Modern Truths' .env (includes `PERSONA=moderntruths`) |
| `INSTAGRAM_SESSION_B64_MODERNTRUTHS` | Modern Truths' IG session |
| `DOTENV_SOFIA` | Sofia's .env (includes `PERSONA=sofia`) |
| `INSTAGRAM_SESSION_B64_SOFIA` | Sofia's IG session |
| `DOTENV_RHEA` | Rhea's .env (includes `PERSONA=rhea`) |
| `INSTAGRAM_SESSION_B64_RHEA` | Rhea's IG session |
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
- Add a profile picture, short bio, follow ~20 accounts, post 2-3 photos
- Use each account normally for a day or two before activating the bot

### Step 2: One-Command Setup (per satellite)

For each satellite account:

1. Log in to the satellite account on **instagram.com** in Chrome
2. Press **Cmd+Option+I** → **Application** tab → **Cookies** → `https://www.instagram.com` → copy the **sessionid** value
3. Run:

```bash
cd instagram_influencer
python get_session.py sat1 your_ig_username 'your_ig_password' 'paste_sessionid_here' your_gemini_api_key
```

This single command logs in, creates the .env, and sets both GitHub secrets automatically. Repeat for `sat2` and `sat3`.

### Step 3: Test

Go to GitHub → **Actions** → **Satellite 1** → **Run workflow** → choose `sat_boost` → **Run workflow**. Watch logs to confirm it works. Repeat for Satellite 2 and 3.

After that, satellites auto-run 9 sessions/day each (5 boost + 4 background).

**Troubleshooting:**
- If login fails, re-export the session cookie and re-run `get_session.py`
- Sessions expire after ~90 days — refresh them periodically
- If you see "challenge required", log into the account on your phone, complete verification, then re-run

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
  stories.py             # Story reshare (post image + link sticker) + highlights
  report.py              # Daily report (Telegram + GitHub Actions + YT stats)
  rate_limiter.py        # Action rate limiting + warmup multiplier
  gemini_helper.py       # Gemini API with model rotation (4 models) + 5-min cooldown on rate limits
  post_queue.py          # Queue I/O (content_queue.json)
  instagrapi_patch.py    # Monkey-patches for instagrapi resilience
  scheduler.py           # macOS launchd scheduler

  personas/              # Persona JSON files
    maya.json            # Maya Varma (fashion, main)
    aryan.json           # Aryan Dhar (fitness, main)
    choosewisely.json    # Choose Wisely (engagement/polls, main)
    moderntruths.json    # Modern Truths (relationships, main)
    sofia.json           # Sofia Petrova (luxury fashion, main)
    rhea.json            # Rhea (fitness, main)
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
      (same structure as maya)
    choosewisely/
      (same structure as maya)
    moderntruths/
      (same structure as maya)
    sofia/
      (same structure as maya)
    rhea/
      (same structure as maya)
    sat1/
      engagement_log.json
      .ig_session.json
      followers.json
      user_pk_cache.json   # Cached Instagram user PKs (avoids 429s)
    sat2/
      (same as sat1)
    sat3/
      (same as sat1)
```
