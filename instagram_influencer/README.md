# Instagram Influencer Pipeline

## Modules

- `config.py` — Configuration (loads `.env`, ~20 settings)
- `post_queue.py` — Queue I/O (`content_queue.json`)
- `generator.py` — Caption generation (Gemini API + template fallback)
- `image.py` — Image generation (Replicate FLUX Kontext → BFL Kontext → HF Schnell fallback)
- `publisher.py` — Instagram publishing (instagrapi)
- `orchestrator.py` — Pipeline CLI (single entry point)

## Flow

1. Generate captions if queue is low (Gemini → template fallback)
2. Generate images using Maya's reference photos (Replicate Kontext → BFL Kontext → HF Schnell)
3. Promote drafts to approved with scheduling (4 hours apart)
4. Publish next eligible post via instagrapi

## Key Files

- `content_queue.json` — post queue (draft → approved → posted)
- `brand_profile_maya_varma.md` — persona/voice rules
- `reference/maya/` — reference photos for face consistency
- `generated_images/` — generated images (gitignored)
- `.ig_session.json` — instagrapi login session (gitignored)
