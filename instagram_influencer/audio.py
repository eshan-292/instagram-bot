#!/usr/bin/env python3
"""Background music management — user-provided tracks or ffmpeg-generated ambient audio."""

from __future__ import annotations

import logging
import os
import random
import subprocess
import tempfile
from pathlib import Path

from config import GENERATED_IMAGES_DIR

log = logging.getLogger(__name__)

MUSIC_DIR = GENERATED_IMAGES_DIR / "music"

# Supported audio formats
_AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"}


def _get_ffmpeg() -> str:
    """Get path to ffmpeg binary."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def get_background_track(duration: float) -> str | None:
    """Get a background audio track for video overlay.

    Priority:
      1. Random user-provided track from generated_images/music/
      2. FFmpeg-generated ambient lo-fi pad (warm pink noise + gentle chord)

    Returns path to audio file, or None if generation fails.
    """
    # 1. Check for user-provided music files
    if MUSIC_DIR.exists():
        tracks = [
            f for f in MUSIC_DIR.iterdir()
            if f.suffix.lower() in _AUDIO_EXTENSIONS and f.stat().st_size > 1000
        ]
        if tracks:
            chosen = random.choice(tracks)
            log.info("Using user-provided track: %s", chosen.name)
            return str(chosen)

    # 2. Generate ambient audio with ffmpeg
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
