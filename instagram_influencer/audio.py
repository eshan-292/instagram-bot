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

# External music API support — set MUSIC_API_URL env var to a self-hosted
# CC0 music endpoint (JSON or direct MP3). Falls back to generated lo-fi.


def _get_ffmpeg() -> str:
    """Get path to ffmpeg binary."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def _fetch_external_track(duration: float) -> str | None:
    """Fetch a royalty-free track from an external music API.

    Checks for MUSIC_API_URL env var (e.g., a self-hosted library of CC0 tracks).
    Returns path to downloaded audio file (temp), or None if not configured.

    To use: Set MUSIC_API_URL to a URL that returns an MP3 file.
    Example: A JSON endpoint that returns {"url": "https://..."} or a direct MP3 link.
    """
    api_url = os.getenv("MUSIC_API_URL", "").strip()
    if not api_url:
        return None

    try:
        resp = http_requests.get(api_url, timeout=15)
        if resp.status_code != 200:
            return None

        # Check if response is JSON (returns a download URL) or direct audio
        content_type = resp.headers.get("content-type", "")
        if "json" in content_type:
            data = resp.json()
            audio_url = data.get("url") or data.get("download_url") or ""
            if not audio_url:
                return None
            dl = http_requests.get(audio_url, timeout=30)
            content = dl.content
        elif "audio" in content_type or "mpeg" in content_type:
            content = resp.content
        else:
            return None

        if len(content) < 5000:
            return None

        fd, tmp_path = tempfile.mkstemp(suffix=".mp3", prefix="ext_music_")
        os.close(fd)
        with open(tmp_path, "wb") as f:
            f.write(content)

        log.info("Fetched external music track: %d bytes", len(content))
        return tmp_path
    except Exception as exc:
        log.debug("External music fetch failed: %s", exc)
        return None


def get_background_track(duration: float) -> str | None:
    """Get a background audio track for video overlay (YouTube Shorts).

    Priority:
      1. User-provided track from generated_images/music/ (best quality)
      2. Pixabay CC0 royalty-free track (downloaded from CDN)
      3. FFmpeg-generated lo-fi beat (synthesized, always available)

    Returns path to audio file, or None if everything fails.
    """
    # 1. Check for user-provided music files (highest priority — curated quality)
    if MUSIC_DIR.exists():
        tracks = [
            f for f in MUSIC_DIR.iterdir()
            if f.suffix.lower() in _AUDIO_EXTENSIONS and f.stat().st_size > 1000
        ]
        if tracks:
            chosen = random.choice(tracks)
            log.info("YT audio: user-provided track '%s'", chosen.name)
            return str(chosen)

    # 2. Try external music API (if configured via MUSIC_API_URL env var)
    ext_track = _fetch_external_track(duration)
    if ext_track:
        log.info("YT audio: external music API track")
        return ext_track

    # 3. Generate lo-fi beat with ffmpeg (always available — no API needed)
    log.info("YT audio: generating lo-fi beat (%.0fs)", duration)
    return _generate_ambient(duration)


def _generate_ambient(duration: float) -> str | None:
    """Generate a lo-fi beat with chord progression using ffmpeg.

    Creates professional-sounding background music by mixing:
      - Chord progression (4 chords, cycling) with detuned oscillators for warmth
      - Sub-bass following chord root notes
      - Filtered pink noise for vinyl/tape texture
      - Lo-fi drum pattern (kick + hi-hat from filtered noise)
      - Fade in/out for smooth transitions

    Randomly selects from multiple chord progressions for variety.
    """
    ffmpeg = _get_ffmpeg()
    fd, audio_path = tempfile.mkstemp(suffix=".wav", prefix="lofi_")
    os.close(fd)

    fade_out_start = max(0, duration - 1.2)

    # Chord progressions — each is 4 chords, each chord = list of freqs (Hz)
    # Cycle through the 4 chords over the duration
    _PROGRESSIONS = [
        # i - VI - III - VII (Am - F - C - G) — lo-fi classic
        {
            "name": "lofi_classic",
            "chords": [
                [220.0, 261.6, 329.6],     # Am (A3, C4, E4)
                [174.6, 220.0, 261.6],     # F (F3, A3, C4)
                [130.8, 164.8, 196.0],     # C (C3, E3, G3)
                [196.0, 246.9, 293.7],     # G (G3, B3, D4)
            ],
            "bass": [110.0, 87.3, 65.4, 98.0],  # root notes one octave down
        },
        # i - iv - VI - V (Am - Dm - F - E) — emotional
        {
            "name": "emotional",
            "chords": [
                [220.0, 261.6, 329.6],     # Am
                [146.8, 174.6, 220.0],     # Dm (D3, F3, A3)
                [174.6, 220.0, 261.6],     # F
                [164.8, 207.7, 246.9],     # E (E3, G#3, B3)
            ],
            "bass": [110.0, 73.4, 87.3, 82.4],
        },
        # I - vi - IV - V (C - Am - F - G) — uplifting pop
        {
            "name": "uplifting",
            "chords": [
                [261.6, 329.6, 392.0],     # C (C4, E4, G4)
                [220.0, 261.6, 329.6],     # Am
                [174.6, 220.0, 261.6],     # F
                [196.0, 246.9, 293.7],     # G
            ],
            "bass": [130.8, 110.0, 87.3, 98.0],
        },
        # ii - V - I - vi (Dm - G - C - Am) — jazzy
        {
            "name": "jazzy",
            "chords": [
                [146.8, 174.6, 220.0],     # Dm
                [196.0, 246.9, 293.7],     # G
                [261.6, 329.6, 392.0],     # C
                [220.0, 261.6, 329.6],     # Am
            ],
            "bass": [73.4, 98.0, 130.8, 110.0],
        },
    ]

    prog = random.choice(_PROGRESSIONS)
    chords = prog["chords"]
    bass_notes = prog["bass"]
    n_chords = len(chords)

    # Each chord lasts ~2.5 seconds, cycling through the progression
    chord_dur = 2.5

    # Build chord pad expression: detuned oscillators for warmth
    # Each note gets a main + slightly detuned copy (±2Hz) for chorus effect
    # Volume: loud enough to be clearly audible as background music
    chord_parts = []
    for i, chord_freqs in enumerate(chords):
        t_start = i * chord_dur
        t_end = t_start + chord_dur
        # Window function: smooth in/out per chord (avoids clicks)
        window = (
            f"if(between(t-floor(t/{n_chords * chord_dur})*{n_chords * chord_dur},"
            f"{t_start},{t_end}),1,0)"
        )
        for freq in chord_freqs:
            amp = 0.10  # 2.5x louder than before (was 0.04)
            detune = 1.5  # Hz detune for chorus width
            chord_parts.append(
                f"{amp}*sin({freq}*2*PI*t)*{window}"
                f"+{amp * 0.7}*sin({freq + detune}*2*PI*t)*{window}"
                f"+{amp * 0.5}*sin({freq * 2}*2*PI*t)*{window}"  # octave up (shimmer)
            )

    chord_expr = "+".join(chord_parts)
    chord_input = f"aevalsrc='{chord_expr}':s=44100:d={duration}"

    # Sub-bass: follows chord root, smooth sine wave
    bass_parts = []
    for i, bass_freq in enumerate(bass_notes):
        t_start = i * chord_dur
        t_end = t_start + chord_dur
        window = (
            f"if(between(t-floor(t/{n_chords * chord_dur})*{n_chords * chord_dur},"
            f"{t_start},{t_end}),1,0)"
        )
        bass_parts.append(f"0.14*sin({bass_freq}*2*PI*t)*{window}")  # 2x louder bass

    bass_expr = "+".join(bass_parts)
    bass_input = f"aevalsrc='{bass_expr}':s=44100:d={duration}"

    # Pink noise: vinyl texture — audible warmth
    noise_input = (
        f"anoisesrc=d={duration}:c=pink:r=44100,"
        f"lowpass=f=800,highpass=f=200,volume=0.07"
    )

    # Lo-fi drum pattern: kick (low thump) + hi-hat (high click)
    # BPM ~75 (lo-fi tempo), kick on 1 & 3, hat on every beat
    bpm = 75
    beat_dur = 60.0 / bpm
    # Kick: punchy low freq burst every 2 beats
    kick_expr = (
        f"0.22*sin(55*2*PI*t)*exp(-8*mod(t,{2 * beat_dur}))"
        f"*if(lt(mod(t,{2 * beat_dur}),0.15),1,0)"
    )
    kick_input = f"aevalsrc='{kick_expr}':s=44100:d={duration}"

    # Hi-hat: filtered white noise shimmer — audible rhythm
    hat_input = (
        f"anoisesrc=d={duration}:c=white:r=44100,"
        f"highpass=f=7000,lowpass=f=14000,"
        f"volume=0.025"
    )

    # Mix all 5 layers with fades + loudness normalization
    filter_complex = (
        f"[0:a][1:a][2:a][3:a][4:a]amix=inputs=5:duration=shortest:weights=1 0.8 0.5 0.7 0.4,"
        f"lowpass=f=12000,"  # lo-fi: cut harsh highs
        f"equalizer=f=400:width_type=o:width=2:g=3,"  # warm mid boost
        f"loudnorm=I=-16:TP=-1.5:LRA=11,"  # broadcast loudness normalization
        f"afade=t=in:d=0.8,"
        f"afade=t=out:st={fade_out_start}:d=1.2"
    )

    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", chord_input,
        "-f", "lavfi", "-i", bass_input,
        "-f", "lavfi", "-i", noise_input,
        "-f", "lavfi", "-i", kick_input,
        "-f", "lavfi", "-i", hat_input,
        "-filter_complex", filter_complex,
        "-c:a", "pcm_s16le",
        audio_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            log.warning("Lo-fi beat generation failed: %s", (result.stderr or "")[-500:])
            _safe_remove(audio_path)
            # Fall back to simple ambient if complex generation fails
            return _generate_simple_ambient(duration)

        file_size = os.path.getsize(audio_path)
        log.info("Generated lo-fi beat (%s): %d bytes, %.1fs",
                 prog["name"], file_size, duration)
        return audio_path
    except Exception as exc:
        log.warning("Lo-fi beat generation error: %s", exc)
        _safe_remove(audio_path)
        return _generate_simple_ambient(duration)


def _generate_simple_ambient(duration: float) -> str | None:
    """Simple ambient fallback — warm pad with gentle movement.

    Used when the full lo-fi beat generation fails (e.g., old ffmpeg version).
    Still much better than the original static chord.
    """
    ffmpeg = _get_ffmpeg()
    fd, audio_path = tempfile.mkstemp(suffix=".wav", prefix="ambient_")
    os.close(fd)

    fade_out_start = max(0, duration - 0.8)

    # Warm evolving pad: Am7 chord with slow LFO modulation for movement
    # Main tones + detuned copies for width — loud enough to be clearly audible
    chord_expr = (
        # A3 (root) — with slow volume LFO
        "0.12*(1+0.3*sin(0.4*2*PI*t))*sin(220*2*PI*t)"
        "+0.08*sin(222*2*PI*t)"  # detuned copy for width
        # C4 (minor 3rd)
        "+0.10*(1+0.3*sin(0.5*2*PI*t))*sin(261.6*2*PI*t)"
        "+0.07*sin(263.6*2*PI*t)"
        # E4 (5th)
        "+0.09*(1+0.3*sin(0.6*2*PI*t))*sin(329.6*2*PI*t)"
        "+0.06*sin(331.6*2*PI*t)"
        # G4 (7th) — gentler
        "+0.06*(1+0.3*sin(0.35*2*PI*t))*sin(392*2*PI*t)"
        # Sub-bass: A2 with gentle pulse
        "+0.10*(1+0.2*sin(0.3*2*PI*t))*sin(110*2*PI*t)"
    )
    chord_input = f"aevalsrc='{chord_expr}':s=44100:d={duration}"

    # Pink noise: warm texture
    noise_input = (
        f"anoisesrc=d={duration}:c=pink:r=44100,"
        f"lowpass=f=600,highpass=f=100,volume=0.08"
    )

    filter_complex = (
        f"[0:a][1:a]amix=inputs=2:duration=shortest,"
        f"lowpass=f=10000,"
        f"loudnorm=I=-16:TP=-1.5:LRA=11,"  # broadcast loudness normalization
        f"afade=t=in:d=0.6,"
        f"afade=t=out:st={fade_out_start}:d=0.8"
    )

    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", chord_input,
        "-f", "lavfi", "-i", noise_input,
        "-filter_complex", filter_complex,
        "-c:a", "pcm_s16le",
        audio_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            log.warning("Simple ambient generation failed: %s", (result.stderr or "")[-300:])
            _safe_remove(audio_path)
            return None

        log.debug("Generated simple ambient: %s (%d bytes)", audio_path, os.path.getsize(audio_path))
        return audio_path
    except Exception as exc:
        log.warning("Simple ambient error: %s", exc)
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
