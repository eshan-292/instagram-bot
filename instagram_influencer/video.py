#!/usr/bin/env python3
"""Convert static images to short MP4 videos with Ken Burns effect + background audio."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from audio import get_background_track, trim_audio, _safe_remove as _audio_safe_remove

log = logging.getLogger(__name__)

# Instagram Reels: 4:5 portrait — 7s for better watch-time metrics (was 5s)
IG_WIDTH = 1080
IG_HEIGHT = 1350
IG_DURATION = 7  # 7s = sweet spot for single-image Reels (short enough to loop)

# YouTube Shorts: 9:16 portrait — 10s for better retention on YouTube
YT_WIDTH = 1080
YT_HEIGHT = 1920
YT_DURATION = 10  # slightly longer for YouTube's retention-based algorithm

FPS = 30


def _get_ffmpeg() -> str:
    """Get path to ffmpeg binary (bundled with imageio_ffmpeg or system)."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def image_to_video(
    image_path: str,
    output_path: str | None = None,
    width: int = IG_WIDTH,
    height: int = IG_HEIGHT,
    duration: int = IG_DURATION,
    add_audio: bool = True,
) -> str:
    """Convert a static image to MP4 with Ken Burns zoom effect + background audio.

    Returns path to the generated MP4 file.
    """
    if output_path is None:
        output_path = str(Path(image_path).with_suffix(".mp4"))

    ffmpeg = _get_ffmpeg()
    total_frames = duration * FPS

    # Ken Burns: slow zoom 1.0x → 1.2x with slight rightward pan
    # Scale up 2x first so zoompan has room to zoom without pixelation
    zoom_expr = f"1+0.2*on/{total_frames}"
    pan_x = f"iw/2-(iw/zoom/2)+10*on/{total_frames}"
    pan_y = "ih/2-(ih/zoom/2)"

    # Cover-mode scale: ensure image is at least 2x target in BOTH dimensions,
    # then center-crop to exact 2x size. This handles any aspect ratio source →
    # any target ratio (e.g., 4:5 source → 9:16 YT output).
    vf = (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        f"zoompan=z='{zoom_expr}':x='{pan_x}':y='{pan_y}':"
        f"d={total_frames}:s={width}x{height}:fps={FPS},"
        f"format=yuv420p"
    )

    # Try to get background audio
    audio_path = None
    audio_is_temp = False
    if add_audio:
        raw_audio = get_background_track(duration)
        if raw_audio:
            # If it's a user-provided track, trim it to match video duration
            if not raw_audio.startswith(tempfile.gettempdir()):
                trimmed = trim_audio(raw_audio, duration)
                if trimmed:
                    audio_path = trimmed
                    audio_is_temp = True
                else:
                    audio_path = raw_audio
                    audio_is_temp = False
            else:
                # Generated ambient audio — already correct duration
                audio_path = raw_audio
                audio_is_temp = True

    if audio_path:
        # Video with audio
        cmd = [
            ffmpeg, "-y",
            "-loop", "1",
            "-i", image_path,
            "-i", audio_path,
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-t", str(duration),
            "-map", "0:v",
            "-map", "1:a",
            output_path,
        ]
    else:
        # Fallback: silent video (if audio generation completely fails)
        log.warning("No audio available, creating silent video")
        cmd = [
            ffmpeg, "-y",
            "-loop", "1",
            "-i", image_path,
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-t", str(duration),
            "-an",
            output_path,
        ]

    log.debug("ffmpeg: %s", " ".join(cmd[:6]) + " ...")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            log.error("ffmpeg stderr: %s", (result.stderr or "")[-500:])
            raise RuntimeError(f"ffmpeg failed (exit {result.returncode})")

        if not os.path.exists(output_path):
            raise RuntimeError(f"ffmpeg produced no output: {output_path}")

        file_size = os.path.getsize(output_path)
        has_audio = "with audio" if audio_path else "silent"
        log.info("Video: %s (%d bytes, %ds, %s)", output_path, file_size, duration, has_audio)
        return output_path
    finally:
        # Clean up temp audio
        if audio_is_temp and audio_path:
            _audio_safe_remove(audio_path)


def image_to_youtube_short(image_path: str, output_path: str | None = None) -> str:
    """Convert a static image to YouTube Shorts format (9:16, 1080x1920, 8s).

    Returns path to the generated MP4 file.
    """
    if output_path is None:
        stem = Path(image_path).stem
        output_path = str(Path(image_path).parent / f"{stem}_yt.mp4")

    return image_to_video(
        image_path,
        output_path=output_path,
        width=YT_WIDTH,
        height=YT_HEIGHT,
        duration=YT_DURATION,
        add_audio=True,
    )


def convert_posts_to_video(posts: list[dict[str, Any]], youtube: bool = False) -> int:
    """Convert images to videos for posts that need it. Returns count converted.

    Audio strategy (2026 algorithm):
      - Instagram Reels: SILENT video — trending music is overlaid at publish time
        via publisher._find_trending_track() (Instagram algorithm boosts trending audio)
      - YouTube Shorts: WITH audio — royalty-free music baked in (Pixabay/user/ambient)
    """
    converted = 0
    for post in posts:
        status = str(post.get("status", "")).strip().lower()
        if status in {"posted", "failed"}:
            continue

        # Need an existing image to convert
        image_url = str(post.get("image_url", "")).strip()
        if not image_url or not os.path.exists(image_url):
            continue

        # Instagram video (4:5) — SILENT: trending audio added at publish time
        video_url = str(post.get("video_url") or "").strip()
        if not video_url or not os.path.exists(video_url):
            try:
                video_path = image_to_video(image_url, add_audio=False)
                post["video_url"] = video_path
                post["is_reel"] = True
                converted += 1
            except Exception as exc:
                log.warning("IG video conversion failed for %s: %s", post.get("id"), exc)

        # YouTube Shorts video (9:16) — WITH audio: royalty-free music baked in
        if youtube:
            yt_video = str(post.get("youtube_video_url") or "").strip()
            if not yt_video or not os.path.exists(yt_video):
                try:
                    yt_path = image_to_youtube_short(image_url)
                    post["youtube_video_url"] = yt_path
                except Exception as exc:
                    log.warning("YT video conversion failed for %s: %s", post.get("id"), exc)

    return converted
