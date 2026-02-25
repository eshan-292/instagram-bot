#!/usr/bin/env python3
"""Convert static images to short MP4 videos with Ken Burns effect for Reels."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Output settings
VIDEO_DURATION = 5  # seconds (matches Instagram's photo-to-Reel default)
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1350  # 4:5 portrait (Instagram Reels)
FPS = 30


def _get_ffmpeg() -> str:
    """Get path to ffmpeg binary (bundled with imageio_ffmpeg or system)."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def image_to_video(image_path: str, output_path: str | None = None) -> str:
    """Convert a static image to MP4 with Ken Burns zoom effect.

    Returns path to the generated MP4 file.
    """
    if output_path is None:
        output_path = str(Path(image_path).with_suffix(".mp4"))

    ffmpeg = _get_ffmpeg()
    total_frames = VIDEO_DURATION * FPS

    # Ken Burns: slow zoom 1.0x → 1.2x with slight rightward pan
    # Scale up 2x first so zoompan has room to zoom without pixelation
    zoom_expr = f"1+0.2*on/{total_frames}"
    pan_x = f"iw/2-(iw/zoom/2)+10*on/{total_frames}"
    pan_y = "ih/2-(ih/zoom/2)"

    vf = (
        f"scale={OUTPUT_WIDTH * 2}:-1,"
        f"crop={OUTPUT_WIDTH * 2}:{OUTPUT_HEIGHT * 2},"
        f"zoompan=z='{zoom_expr}':x='{pan_x}':y='{pan_y}':"
        f"d={total_frames}:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:fps={FPS},"
        f"format=yuv420p"
    )

    cmd = [
        ffmpeg, "-y",
        "-loop", "1",
        "-i", image_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-t", str(VIDEO_DURATION),
        "-an",
        output_path,
    ]

    log.debug("ffmpeg: %s", " ".join(cmd[:6]) + " ...")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        log.error("ffmpeg stderr: %s", (result.stderr or "")[-500:])
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode})")

    if not os.path.exists(output_path):
        raise RuntimeError(f"ffmpeg produced no output: {output_path}")

    file_size = os.path.getsize(output_path)
    log.info("Video: %s (%d bytes, %ds)", output_path, file_size, VIDEO_DURATION)
    return output_path


def convert_posts_to_video(posts: list[dict[str, Any]]) -> int:
    """Convert images to videos for posts that need it. Returns count converted."""
    converted = 0
    for post in posts:
        status = str(post.get("status", "")).strip().lower()
        if status in {"posted", "failed"}:
            continue

        # Skip if already has a video file
        video_url = str(post.get("video_url") or "").strip()
        if video_url and os.path.exists(video_url):
            continue

        # Need an existing image to convert
        image_url = str(post.get("image_url", "")).strip()
        if not image_url or not os.path.exists(image_url):
            continue

        try:
            video_path = image_to_video(image_url)
            post["video_url"] = video_path
            post["is_reel"] = True
            converted += 1
        except Exception as exc:
            log.warning("Video conversion failed for %s, will post as photo: %s",
                        post.get("id"), exc)

    return converted
