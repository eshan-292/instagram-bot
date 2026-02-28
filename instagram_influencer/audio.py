#!/usr/bin/env python3
"""Background music management — Pixabay royalty-free tracks, user-provided, or ambient fallback.

Audio strategy (2026):
  - Instagram Reels: NO baked-in audio — trending music overlaid at publish time via
    publisher._find_trending_track() (Instagram's algorithm favours trending audio)
  - YouTube Shorts: Royalty-free music baked in (Pixabay API → user tracks → ambient fallback)
"""

from __future__ import annotations

import logging
import os
import random
import subprocess
import tempfile
from pathlib import Path

import requests as http_requests

from config import GENERATED_IMAGES_DIR

log = logging.getLogger(__name__)

MUSIC_DIR = GENERATED_IMAGES_DIR / "music"

# Supported audio formats
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"}

# Pixabay Music API — free, no attribution required, huge royalty-free library
_PIXABAY_API_URL = "https://pixabay.com/api/"

# Genre/mood queries for fashion/lifestyle Shorts background music
_PIXABAY_QUERIES = [
    "upbeat fashion", "trendy pop", "chill lo-fi", "aesthetic vibes",
    "indian pop", "modern bollywood", "stylish beat", "confident walk",
    "runway music", "urban lifestyle", "groovy beat", "feel good pop",
]


def _get_ffmpeg() -> str:
    """Get path to ffmpeg binary."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def _fetch_pixabay_track(duration: float) -> str | None:
    """Fetch a royalty-free track from Pixabay Music API.

    Returns path to downloaded audio file (temp), or None on failure.
    """
    api_key = os.getenv("PIXABAY_API_KEY", "").strip()
    if not api_key:
        log.debug("PIXABAY_API_KEY not set, skipping Pixabay audio")
        return None

    query = random.choice(_PIXABAY_QUERIES)
    min_dur = max(5, int(duration) - 5)
    max_dur = int(duration) + 30  # allow slightly longer (we'll trim)

    params = {
        "key": api_key,
        "q": query,
        "audio_type": "music",
        "min_duration": min_dur,
        "max_duration": max_dur,
        "per_page": 10,
        "safesearch": "true",
        "order": "popular",
    }

    try:
        resp = http_requests.get(_PIXABAY_API_URL, params=params, timeout=15)
        if resp.status_code != 200:
            log.debug("Pixabay API returned %d for '%s'", resp.status_code, query)
            return None

        data = resp.json()
        hits = data.get("hits", [])
        if not hits:
            log.debug("No Pixabay results for '%s'", query)
            return None

        # Pick random track from top results
        track = random.choice(hits[:5])
        audio_url = track.get("audio", "") or track.get("previewURL", "")
        if not audio_url:
            return None

        # Download the audio file
        dl = http_requests.get(audio_url, timeout=30)
        if dl.status_code != 200 or len(dl.content) < 5000:
            return None

        suffix = ".mp3" if "mp3" in audio_url else ".wav"
        fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="pixabay_")
        os.close(fd)
        with open(tmp_path, "wb") as f:
            f.write(dl.content)

        log.info("Fetched Pixabay track: '%s' (%d bytes, query='%s')",
                 track.get("title", "unknown"), len(dl.content), query)
        return tmp_path

    except Exception as exc:
        log.debug("Pixabay fetch failed: %s", exc)
        return None


def get_background_track(duration: float) -> str | None:
    """Get a background audio track for video overlay (YouTube Shorts).

    Priority:
      1. Pixabay royalty-free track (trending, fresh, varied)
      2. User-provided track from generated_images/music/
      3. FFmpeg-generated ambient lo-fi pad (last resort)

    Returns path to audio file, or None if everything fails.
    """
    # 1. Try Pixabay royalty-free music
    pixabay_track = _fetch_pixabay_track(duration)
    if pixabay_track:
        return pixabay_track

    # 2. Check for user-provided music files
    if MUSIC_DIR.exists():
        tracks = [
            f for f in MUSIC_DIR.iterdir()
            if f.suffix.lower() in _AUDIO_EXTENSIONS and f.stat().st_size > 1000
        ]
        if tracks:
            chosen = random.choice(tracks)
            log.info("Using user-provided track: %s", chosen.name)
            return str(chosen)

    # 3. Generate ambient audio with ffmpeg (fallback)
    return _generate_ambient(duration)


def _generate_ambient(duration: float) -> str | None:
    """Generate a warm ambient lo-fi pad using ffmpeg.

    Creates a pleasant background by mixing:
      - Pink noise low-passed at 500Hz (warm ambient pad)
      - Gentle sine tones forming a soft Am7 chord (A3, C4, E4, G4)
      - Fade in/out for smooth transitions
    """
    ffmpeg = _get_ffmpeg()
    fd, audio_path = tempfile.mkstemp(suffix=".wav", prefix="ambient_")
    os.close(fd)

    fade_out_start = max(0, duration - 0.8)

    # Pink noise: warm, non-distracting background texture
    noise_input = (
        f"anoisesrc=d={duration}:c=pink:r=44100,"
        f"lowpass=f=500,highpass=f=80,volume=0.10"
    )

    # Am7 chord: A3(220Hz), C4(262Hz), E4(330Hz), G4(392Hz) — dreamy, lo-fi
    chord_expr = (
        "0.05*sin(220*2*PI*t)"
        "+0.04*sin(262*2*PI*t)"
        "+0.035*sin(330*2*PI*t)"
        "+0.025*sin(392*2*PI*t)"
    )
    chord_input = f"aevalsrc='{chord_expr}':s=44100:d={duration}"

    # Mix both inputs with fade in/out
    filter_complex = (
        f"[0:a][1:a]amix=inputs=2:duration=shortest,"
        f"afade=t=in:d=0.6,"
        f"afade=t=out:st={fade_out_start}:d=0.8"
    )

    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", noise_input,
        "-f", "lavfi", "-i", chord_input,
        "-filter_complex", filter_complex,
        "-c:a", "pcm_s16le",
        audio_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            log.warning("Ambient audio generation failed: %s", (result.stderr or "")[-300:])
            _safe_remove(audio_path)
            return None

        log.debug("Generated ambient audio: %s (%d bytes)", audio_path, os.path.getsize(audio_path))
        return audio_path
    except Exception as exc:
        log.warning("Ambient audio generation error: %s", exc)
        _safe_remove(audio_path)
        return None


def trim_audio(audio_path: str, duration: float) -> str | None:
    """Trim an audio file to the specified duration with fade out.

    Returns path to trimmed audio (temp file), or None on failure.
    """
    ffmpeg = _get_ffmpeg()
    fd, trimmed_path = tempfile.mkstemp(suffix=".wav", prefix="trimmed_")
    os.close(fd)

    fade_out_start = max(0, duration - 0.8)

    cmd = [
        ffmpeg, "-y",
        "-i", audio_path,
        "-t", str(duration),
        "-af", f"afade=t=in:d=0.3,afade=t=out:st={fade_out_start}:d=0.8",
        "-c:a", "pcm_s16le",
        "-ar", "44100",
        trimmed_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            _safe_remove(trimmed_path)
            return None
        return trimmed_path
    except Exception:
        _safe_remove(trimmed_path)
        return None


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
