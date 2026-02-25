# Instagram Influencer Bot

Automated Instagram pipeline for **Maya Varma** (AI fashion influencer).

```
Gemini (captions) → Replicate FLUX Kontext (images with face consistency) → instagrapi (publish)
```

## Quick Start

```bash
# 1. Setup
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp instagram_influencer/.env.example .env

# 2. Add your API keys to .env
#    INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD
#    GEMINI_API_KEY, REPLICATE_API_TOKEN

# 3. Generate content + images (no publishing)
make generate

# 4. Check the generated images in instagram_influencer/generated_images/

# 5. Full pipeline (generate + images + promote + publish)
make run
```

## Get Free API Keys

| Provider | What it does | Link |
|----------|-------------|------|
| **Gemini** | Caption generation | https://aistudio.google.com/apikey |
| **Replicate** | Image generation (FLUX Kontext, preserves Maya's face) | https://replicate.com/account/api-tokens |
| **Hugging Face** | Fallback image generation (text-to-image) | https://huggingface.co/settings/tokens |

All free, no credit card needed.

## Make Commands

| Command | What it does |
|---------|-------------|
| `make generate` | Generate captions + images, no publishing |
| `make run` | Full pipeline: generate → images → promote → publish |
| `make dry-run` | Preview next post that would be published |
| `make publish` | Publish next eligible post only |
| `make check` | Syntax check all Python files |
| `make deps` | Install dependencies |

## How It Works

1. **Generate captions** — Gemini 2.5 Flash creates posts in Maya's voice (bold, teasing, confident)
2. **Generate images** — Replicate FLUX Kontext takes Maya's reference photos and generates new images preserving her exact face
3. **Promote drafts** — drafts with caption + image get scheduled 4 hours apart
4. **Publish** — posts to Instagram via instagrapi when scheduled time arrives

Post lifecycle: `draft` → `approved` → `posted`

## Image Generation

Three providers, automatic fallback:
1. **Replicate FLUX Kontext** (primary) — reference-image-based, preserves Maya's face
2. **BFL FLUX Kontext** (backup) — same model, different API
3. **HF FLUX Schnell** (last resort) — text-to-image, no face consistency

Reference photos live in `instagram_influencer/reference/maya/`.

## Automation (cron)

```bash
# Run every hour
0 * * * * cd "/path/to/project" && bash -lc 'source .venv/bin/activate && make run >> bot.log 2>&1'
```

Set `AUTO_MODE=true` and `AUTO_PROMOTE_DRAFTS=true` in `.env` for full automation.

## Files

```
instagram_influencer/
├── config.py          # Configuration (~20 env vars)
├── post_queue.py      # Queue I/O (content_queue.json)
├── generator.py       # Caption generation (Gemini + template fallback)
├── image.py           # Image generation (Replicate Kontext → BFL → HF Schnell)
├── publisher.py       # Instagram publishing (instagrapi)
├── orchestrator.py    # Pipeline CLI (single entry point)
├── reference/maya/    # Maya's reference photos for face consistency
├── generated_images/  # Generated images (gitignored)
└── content_queue.json # Post queue (draft → approved → posted)
```
