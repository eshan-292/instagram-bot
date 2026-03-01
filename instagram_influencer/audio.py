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
            amp = 0.04
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
        bass_parts.append(f"0.06*sin({bass_freq}*2*PI*t)*{window}")

    bass_expr = "+".join(bass_parts)
    bass_input = f"aevalsrc='{bass_expr}':s=44100:d={duration}"

    # Pink noise: vinyl texture — very quiet, band-passed
    noise_input = (
        f"anoisesrc=d={duration}:c=pink:r=44100,"
        f"lowpass=f=800,highpass=f=200,volume=0.04"
    )

    # Lo-fi drum pattern: kick (low thump) + hi-hat (high click)
    # BPM ~75 (lo-fi tempo), kick on 1 & 3, hat on every beat
    bpm = 75
    beat_dur = 60.0 / bpm
    # Kick: low freq burst every 2 beats
    kick_expr = (
        f"0.12*sin(55*2*PI*t)*exp(-8*mod(t,{2 * beat_dur}))"
        f"*if(lt(mod(t,{2 * beat_dur}),0.15),1,0)"
    )
    kick_input = f"aevalsrc='{kick_expr}':s=44100:d={duration}"

    # Hi-hat: filtered white noise — constant gentle shimmer
    # (simpler approach: just very quiet high-freq noise, no gating needed)
    hat_input = (
        f"anoisesrc=d={duration}:c=white:r=44100,"
        f"highpass=f=7000,lowpass=f=14000,"
        f"volume=0.012"
    )

    # Mix all 5 layers with fades
    filter_complex = (
        f"[0:a][1:a][2:a][3:a][4:a]amix=inputs=5:duration=shortest:weights=1 0.8 0.5 0.6 0.3,"
        f"lowpass=f=12000,"  # lo-fi: cut harsh highs
        f"equalizer=f=400:width_type=o:width=2:g=2,"  # warm mid boost
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
    # Main tones + detuned copies for width
    chord_expr = (
        # A3 (root) — with slow volume LFO
        "0.05*(1+0.3*sin(0.4*2*PI*t))*sin(220*2*PI*t)"
        "+0.035*sin(222*2*PI*t)"  # detuned copy for width
        # C4 (minor 3rd)
        "+0.04*(1+0.3*sin(0.5*2*PI*t))*sin(261.6*2*PI*t)"
        "+0.028*sin(263.6*2*PI*t)"
        # E4 (5th)
        "+0.035*(1+0.3*sin(0.6*2*PI*t))*sin(329.6*2*PI*t)"
        "+0.025*sin(331.6*2*PI*t)"
        # G4 (7th) — gentler
        "+0.025*(1+0.3*sin(0.35*2*PI*t))*sin(392*2*PI*t)"
        # Sub-bass: A2 with gentle pulse
        "+0.04*(1+0.2*sin(0.3*2*PI*t))*sin(110*2*PI*t)"
    )
    chord_input = f"aevalsrc='{chord_expr}':s=44100:d={duration}"

    # Pink noise: warm texture
    noise_input = (
        f"anoisesrc=d={duration}:c=pink:r=44100,"
        f"lowpass=f=600,highpass=f=100,volume=0.06"
    )

    filter_complex = (
        f"[0:a][1:a]amix=inputs=2:duration=shortest,"
        f"lowpass=f=10000,"
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
