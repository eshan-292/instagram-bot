#!/usr/bin/env python3
"""Convert static images to short MP4 videos with Ken Burns effect + text overlays.

2026 algorithm optimizations:
  - Snap zoom hook (first 0.5s) to grab attention in 1.7 seconds
  - On-screen text captions (85% watch with sound off → +80% completion rate)
  - Ken Burns zoom for cinematic feel
  - Multi-image montage for carousel → Reel conversion (30s = 24% more shares)
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

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

# Montage: per-image duration for carousel → Reel conversion
IG_MONTAGE_PER_IMAGE = 6  # 5 images × 6s = 30s Reel (sweet spot for shares)
YT_MONTAGE_PER_IMAGE = 5  # 5 images × 5s = 25s Short

FPS = 30

# Hook-photo reel: variable frame durations for viral pacing
# Hook = fast snap (grabs attention), photo = hold (let them absorb),
# bridge = quick (curiosity), CTA = linger (drives action)
HOOK_DUR = 1.0       # Hook text: FAST pattern interrupt (was 2s — too slow)
PHOTO_DUR = 2.0      # Photo frames: let the visual land
BRIDGE_DUR = 1.2     # Bridge/curiosity text: quick, keep momentum
CTA_DUR = 2.5        # CTA: longer so viewer registers the action

# Legacy constant for montage calls (used by non-hook reels)
HOOK_REEL_PER_FRAME = 2  # seconds per frame (fallback)

# Font for text overlays — DejaVu is available on Ubuntu (GitHub Actions)
# Falls back to "Sans" if not found (ffmpeg default)
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",  # macOS
]


def _get_ffmpeg() -> str:
    """Get path to ffmpeg binary (bundled with imageio_ffmpeg or system)."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def _find_font() -> str:
    """Find a usable font path for ffmpeg drawtext."""
    for p in _FONT_PATHS:
        if os.path.exists(p):
            return p
    return ""  # ffmpeg will use built-in default


def _escape_drawtext(text: str) -> str:
    """Escape special characters for ffmpeg drawtext filter."""
    # ffmpeg drawtext needs these escaped
    return (text
            .replace("\\", "\\\\")
            .replace("'", "\u2019")  # replace apostrophe with Unicode right single quote
            .replace(":", "\\:")
            .replace("%", "%%"))


def _build_drawtext_filters(
    text_lines: list[str],
    width: int,
    height: int,
    duration: int,
) -> str:
    """Build ffmpeg drawtext filter chain for on-screen text overlays.

    Creates timed text that appears and disappears:
      Line 1 (hook):  bold, large, white — visible 0.3s to 2.5s
      Line 2 (body):  medium, white — visible 3.0s to 5.5s
      Line 3 (CTA):   medium, yellow — visible 5.5s to end

    This is THE single biggest growth lever: 85% watch on mute,
    text overlays increase completion by 80%.
    """
    if not text_lines:
        return ""

    font = _find_font()
    font_arg = f"fontfile='{font}':" if font else ""

    filters = []

    # Calculate time windows based on duration
    if duration <= 5:
        # Short video: compress timing
        windows = [(0.2, 2.0), (2.2, 4.0), (4.0, duration)]
    elif duration <= 8:
        # Standard IG Reel (7s)
        windows = [(0.3, 2.5), (3.0, 5.5), (5.5, duration)]
    else:
        # Longer video (10s+ YouTube)
        windows = [(0.3, 3.5), (4.0, 7.0), (7.0, duration)]

    # Hook line — large, bold, white with black border (grab attention)
    if len(text_lines) >= 1:
        txt = _escape_drawtext(text_lines[0])
        start, end = windows[0]
        hook_size = int(width * 0.05)  # ~54pt at 1080w
        filters.append(
            f"drawtext={font_arg}text='{txt}':"
            f"fontsize={hook_size}:fontcolor=white:"
            f"borderw=4:bordercolor=black@0.85:"
            f"x=(w-text_w)/2:y=h*0.72:"
            f"enable='between(t,{start},{end})'"
        )

    # Body line — medium, white
    if len(text_lines) >= 2:
        txt = _escape_drawtext(text_lines[1])
        start, end = windows[1]
        body_size = int(width * 0.038)  # ~41pt at 1080w
        filters.append(
            f"drawtext={font_arg}text='{txt}':"
            f"fontsize={body_size}:fontcolor=white:"
            f"borderw=3:bordercolor=black@0.85:"
            f"x=(w-text_w)/2:y=h*0.75:"
            f"enable='between(t,{start},{end})'"
        )

    # CTA line — medium, yellow (stands out, drives action)
    if len(text_lines) >= 3:
        txt = _escape_drawtext(text_lines[2])
        start, end = windows[2]
        cta_size = int(width * 0.035)  # ~38pt at 1080w
        filters.append(
            f"drawtext={font_arg}text='{txt}':"
            f"fontsize={cta_size}:fontcolor=#FFD700:"
            f"borderw=3:bordercolor=black@0.85:"
            f"x=(w-text_w)/2:y=h*0.80:"
            f"enable='between(t,{start},{end})'"
        )

    return ",".join(filters)


def image_to_video(
    image_path: str,
    output_path: str | None = None,
    width: int = IG_WIDTH,
    height: int = IG_HEIGHT,
    duration: int = IG_DURATION,
    add_audio: bool = True,
    text_lines: list[str] | None = None,
) -> str:
    """Convert a static image to MP4 with snap zoom hook + Ken Burns + text overlays.

    2026 algorithm optimizations:
      - Snap zoom in first 0.5s (attention grab in 1.7s decision window)
      - On-screen text overlays (85% watch on mute)
      - Ken Burns cinematic zoom

    Returns path to the generated MP4 file.
    """
    if output_path is None:
        output_path = str(Path(image_path).with_suffix(".mp4"))

    ffmpeg = _get_ffmpeg()
    total_frames = duration * FPS
    half_fps = FPS // 2  # frames in 0.5s

    # Snap Zoom Hook + Ken Burns (2026 algorithm — grab attention in 1.7s):
    #   Frames 0-15 (0-0.5s):   Quick zoom 1.0x → 1.3x (visual punch)
    #   Frames 15-30 (0.5-1.0s): Ease back to 1.1x (settle)
    #   Frames 30-end:           Gentle 1.1x → 1.2x (classic Ken Burns)
    zoom_expr = (
        f"if(lt(on,{half_fps}),"
        f"1+0.6*on/{half_fps},"                          # 1.0 → 1.3 (snap in)
        f"if(lt(on,{FPS}),"
        f"1.3-0.2*(on-{half_fps})/{half_fps},"           # 1.3 → 1.1 (ease back)
        f"1.1+0.1*(on-{FPS})/({total_frames}-{FPS})))"   # 1.1 → 1.2 (Ken Burns)
    )
    pan_x = f"iw/2-(iw/zoom/2)+10*on/{total_frames}"
    pan_y = "ih/2-(ih/zoom/2)"

    # Fit-with-blur: Show the FULL image (no cropping) with a blurred version
    # of itself filling any empty space. This preserves all content regardless
    # of source vs target aspect ratio differences.
    #   1. split → background (cover-scale + blur) + foreground (fit-scale)
    #   2. overlay foreground centered on blurred background
    #   3. zoompan for the zoom animation
    #   4. fade=in AFTER zoompan (zoompan reads only frame 0)
    tw, th = width * 2, height * 2  # 2x target for zoompan headroom

    def _build_vf(use_text: bool = True) -> str:
        base = (
            f"split[bg][fg];"
            f"[bg]scale={tw}:{th}:force_original_aspect_ratio=increase,"
            f"crop={tw}:{th},gblur=sigma=40[bgblur];"
            f"[fg]scale={tw}:{th}:force_original_aspect_ratio=decrease[fgfit];"
            f"[bgblur][fgfit]overlay=(W-w)/2:(H-h)/2,"
            f"zoompan=z='{zoom_expr}':x='{pan_x}':y='{pan_y}':"
            f"d={total_frames}:s={width}x{height}:fps={FPS},"
            f"fade=in:0:5,"
            f"format=yuv420p"
        )
        if use_text and text_lines:
            drawtext = _build_drawtext_filters(text_lines, width, height, duration)
            if drawtext and base.endswith("format=yuv420p"):
                base = base[:-len("format=yuv420p")] + drawtext + ",format=yuv420p"
        return base

    # Text overlays are now baked into Gemini-generated images — skip drawtext
    vf = _build_vf(use_text=False)

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

    def _build_cmd(filter_str: str) -> list[str]:
        if audio_path:
            return [
                ffmpeg, "-y",
                "-loop", "1",
                "-i", image_path,
                "-i", audio_path,
                "-vf", filter_str,
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
            # Add a silent audio track (Instagram rejects video-only MP4
            # for Reel uploads with music overlay)
            return [
                ffmpeg, "-y",
                "-loop", "1",
                "-i", image_path,
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-vf", filter_str,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "32k",
                "-t", str(duration),
                "-map", "0:v",
                "-map", "1:a",
                "-shortest",
                output_path,
            ]

    cmd = _build_cmd(vf)
    log.debug("ffmpeg: %s", " ".join(cmd[:6]) + " ...")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        # If ffmpeg fails and we used text overlays, retry without them
        # (drawtext filter requires libfreetype which may not be compiled in)
        if result.returncode != 0 and text_lines:
            log.warning("ffmpeg failed with text overlays, retrying without: %s",
                        (result.stderr or "")[-200:])
            vf_plain = _build_vf(use_text=False)
            cmd = _build_cmd(vf_plain)
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


def image_to_youtube_short(
    image_path: str,
    output_path: str | None = None,
    text_lines: list[str] | None = None,
) -> str:
    """Convert a static image to YouTube Shorts format (9:16, 1080x1920, 10s).

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
        text_lines=text_lines,
    )


def images_to_montage(
    image_paths: list[str],
    output_path: str,
    width: int = IG_WIDTH,
    height: int = IG_HEIGHT,
    duration_per_image: int = IG_MONTAGE_PER_IMAGE,
    add_audio: bool = False,
    text_lines: list[str] | None = None,
) -> str:
    """Create a multi-image montage video with transitions.

    Converts a carousel's images into a single continuous Reel with:
      - Ken Burns zoom per image segment
      - Cross-dissolve transitions between images
      - Text overlay on first and last segments
      - Total duration = len(images) × duration_per_image

    2026 algorithm: 60-90s Reels get 24% more shares, 19% more reach.
    A 5-image carousel → 30s montage Reel hits the sweet spot.
    """
    if len(image_paths) < 2:
        # Fall back to single-image video
        return image_to_video(
            image_paths[0], output_path, width, height,
            duration_per_image, add_audio, text_lines,
        )

    ffmpeg = _get_ffmpeg()
    temp_clips: list[str] = []

    audio_path = None
    audio_is_temp = False

    try:
        # Generate individual Ken Burns clips per image
        for i, img_path in enumerate(image_paths):
            clip_path = os.path.join(
                tempfile.gettempdir(), f"montage_clip_{i}_{os.getpid()}.mp4"
            )

            # Text overlay: hook on first clip, CTA on last clip
            clip_text: list[str] | None = None
            if text_lines:
                if i == 0 and len(text_lines) >= 1:
                    clip_text = [text_lines[0]]  # hook on first slide
                elif i == len(image_paths) - 1 and len(text_lines) >= 3:
                    clip_text = [text_lines[2]]  # CTA on last slide

            image_to_video(
                img_path, clip_path, width, height,
                duration_per_image, add_audio=False, text_lines=clip_text,
            )
            temp_clips.append(clip_path)

        # Create concat list file for ffmpeg
        list_path = os.path.join(
            tempfile.gettempdir(), f"montage_list_{os.getpid()}.txt"
        )
        with open(list_path, "w") as f:
            for clip in temp_clips:
                f.write(f"file '{clip}'\n")

        # Concatenate clips — use concat demuxer (reliable, fast)
        total_duration = len(image_paths) * duration_per_image

        # Get audio for the full montage if needed
        if add_audio:
            raw_audio = get_background_track(total_duration)
            if raw_audio:
                if not raw_audio.startswith(tempfile.gettempdir()):
                    trimmed = trim_audio(raw_audio, total_duration)
                    if trimmed:
                        audio_path = trimmed
                        audio_is_temp = True
                    else:
                        audio_path = raw_audio
                else:
                    audio_path = raw_audio
                    audio_is_temp = True

        if audio_path:
            cmd = [
                ffmpeg, "-y",
                "-f", "concat", "-safe", "0", "-i", list_path,
                "-i", audio_path,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-t", str(total_duration),
                "-map", "0:v", "-map", "1:a",
                output_path,
            ]
        else:
            cmd = [
                ffmpeg, "-y",
                "-f", "concat", "-safe", "0", "-i", list_path,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-t", str(total_duration),
                "-an",
                output_path,
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            log.error("Montage ffmpeg stderr: %s", (result.stderr or "")[-500:])
            raise RuntimeError(f"Montage ffmpeg failed (exit {result.returncode})")

        file_size = os.path.getsize(output_path)
        log.info("Montage: %s (%d bytes, %ds, %d clips)",
                 output_path, file_size, total_duration, len(image_paths))
        return output_path

    finally:
        # Clean up temp clips
        for clip in temp_clips:
            _audio_safe_remove(clip)
        list_file = os.path.join(
            tempfile.gettempdir(), f"montage_list_{os.getpid()}.txt"
        )
        _audio_safe_remove(list_file)
        if audio_is_temp and audio_path:
            _audio_safe_remove(audio_path)


# ---------------------------------------------------------------------------
# Hook-photo reel: interleaved text hooks + photos (2026 viral format)
# ---------------------------------------------------------------------------

def _create_text_frame(
    text: str,
    width: int = 1080,
    height: int = 1920,
    bg_color: tuple = (13, 13, 13),
    text_color: tuple = (255, 255, 255),
    frame_type: str = "hook",
) -> str:
    """Create a visually striking text frame for hook-photo reels.

    2026 viral optimization:
      - Dark gradient background (not flat) with vignette edges
      - Large bold text with glow effect (stands out on mute)
      - Color-coded: hook=white, bridge=white, CTA=gold
      - Accent line above text for visual polish

    Args:
        frame_type: "hook", "bridge", or "cta" — affects font size and styling

    Returns path to a temporary JPEG file.
    """
    import random as _rnd

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # --- Gradient background with vignette ---
    # Radial gradient: lighter center → darker edges (depth effect)
    cx, cy = width // 2, height // 2
    max_dist = (cx ** 2 + cy ** 2) ** 0.5
    # Draw vertical gradient strips (faster than pixel-by-pixel)
    for y_pos in range(0, height, 4):
        # Vertical gradient: slightly lighter center band
        dist_y = abs(y_pos - cy) / cy  # 0 at center, 1 at edges
        # Darken edges: center=bg_color, edges=darker
        factor = 1.0 - 0.4 * (dist_y ** 1.5)
        r = max(0, min(255, int(bg_color[0] * factor)))
        g = max(0, min(255, int(bg_color[1] * factor)))
        b = max(0, min(255, int(bg_color[2] * factor)))
        draw.rectangle([(0, y_pos), (width, y_pos + 4)], fill=(r, g, b))

    # --- Font sizing by frame type ---
    if frame_type == "hook":
        font_size = width // 8  # ~135px — HUGE hook text
    elif frame_type == "cta":
        font_size = width // 9  # ~120px — large but slightly smaller
    else:
        font_size = width // 10  # ~108px — bridge text

    font = None
    for path in _FONT_PATHS:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, font_size)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    # Word-wrap: keep text within 78% of frame width
    max_w = int(width * 0.78)
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_w and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)

    full_text = "\n".join(lines)

    # Center text vertically and horizontally
    bbox = draw.multiline_textbbox((0, 0), full_text, font=font, align="center")
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) / 2
    y = (height - text_h) / 2

    # --- Glow effect: draw text multiple times with decreasing opacity ---
    # Outer glow (subtle color halo)
    glow_color = (80, 80, 120) if frame_type != "cta" else (120, 100, 30)
    for offset in [6, 4]:
        try:
            draw.multiline_text(
                (x, y), full_text, font=font, fill=glow_color,
                align="center", stroke_width=offset + 4, stroke_fill=glow_color,
            )
        except TypeError:
            pass

    # Main text with thick black outline
    try:
        draw.multiline_text(
            (x, y), full_text, font=font, fill=text_color,
            align="center", stroke_width=5, stroke_fill=(0, 0, 0),
        )
    except TypeError:
        draw.multiline_text(
            (x, y), full_text, font=font, fill=text_color, align="center",
        )

    # --- Accent line above text (visual polish) ---
    accent_color = text_color if frame_type != "cta" else (255, 215, 0)
    line_w = min(text_w, int(width * 0.3))
    line_x = (width - line_w) // 2
    line_y = int(y - font_size * 0.5)
    if line_y > 50:
        draw.rectangle(
            [(line_x, line_y), (line_x + line_w, line_y + 3)],
            fill=accent_color,
        )

    temp_path = os.path.join(
        tempfile.gettempdir(), f"hooktext_{abs(hash(text))}_{os.getpid()}.jpg"
    )
    img.save(temp_path, quality=95)
    return temp_path


def _text_frame_to_clip(
    image_path: str,
    output_path: str,
    width: int,
    height: int,
    duration: float,
    frame_type: str = "hook",
) -> str:
    """Convert a text frame image to a short MP4 clip with zoom + fade.

    Specialized for text frames — simpler and faster than full image_to_video():
      - Gentle zoom-in (1.0x → 1.06x) gives subtle "approaching" motion
      - Quick fade-in (0.15s) for smooth entry
      - No Ken Burns or snap zoom — those fight with text readability

    Args:
        frame_type: "hook" gets slightly faster zoom, "cta" gets gentle pulse feel

    Returns path to the generated MP4 clip.
    """
    ffmpeg = _get_ffmpeg()
    dur_int = max(1, int(duration + 0.5))
    total_frames = int(dur_int * FPS)

    # Zoom: gentle push-in — text feels like it's coming at you
    if frame_type == "hook":
        # Hook: slightly faster zoom for urgency (1.0 → 1.08)
        zoom_expr = f"1+0.08*on/{total_frames}"
    elif frame_type == "cta":
        # CTA: gentle zoom-in (1.0 → 1.04) — calm, authoritative
        zoom_expr = f"1+0.04*on/{total_frames}"
    else:
        # Bridge: medium zoom (1.0 → 1.06)
        zoom_expr = f"1+0.06*on/{total_frames}"

    pan_x = "iw/2-(iw/zoom/2)"
    pan_y = "ih/2-(ih/zoom/2)"

    # Simple pipeline: scale → zoompan → fade → format
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"zoompan=z='{zoom_expr}':x='{pan_x}':y='{pan_y}':"
        f"d={total_frames}:s={width}x{height}:fps={FPS},"
        f"fade=in:0:4,"  # 4 frames = ~0.13s fade-in
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
        "-t", f"{duration:.2f}",
        "-an",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        log.warning("Text frame clip failed, falling back to image_to_video: %s",
                     (result.stderr or "")[-200:])
        # Fallback: use full pipeline
        image_to_video(image_path, output_path, width, height,
                       duration=dur_int, add_audio=False)
    return output_path


def create_hook_photo_reel(
    photo_paths: list[str],
    output_path: str,
    width: int = IG_WIDTH,
    height: int = YT_HEIGHT,
    text_lines: list[str] | None = None,
    add_audio: bool = False,
) -> str:
    """Create a hook-photo reel: bold text slides interleaved with photos.

    The #1 viral reel format in 2026 — variable-paced text hooks between photos:
      [Hook 1.0s] → [Photo 2.0s] → [Bridge 1.2s] → [Photo 2.0s] → [CTA 2.5s]

    2026 viral pacing: hook is FAST (pattern interrupt), photos HOLD (visual),
    bridge QUICK (curiosity), CTA LINGERS (drives action).

    Returns path to the generated MP4 file.
    """
    if not text_lines or len(text_lines) < 2 or len(photo_paths) < 1:
        # Fall back to regular montage if not enough content
        return images_to_montage(
            photo_paths, output_path, width, height,
            HOOK_REEL_PER_FRAME, add_audio, text_lines,
        )

    ffmpeg = _get_ffmpeg()
    text_frames: list[str] = []
    temp_clips: list[str] = []
    audio_path = None
    audio_is_temp = False

    try:
        # Build interleaved frame sequence with per-frame durations
        frame_specs: list[tuple[str, float]] = []  # (image_path, duration_seconds)

        # 1. Hook text frame — FAST snap (pattern interrupt)
        hook = _create_text_frame(text_lines[0], width, height, frame_type="hook")
        text_frames.append(hook)
        frame_specs.append((hook, HOOK_DUR))

        for i, photo in enumerate(photo_paths):
            # 2. Photo frame — HOLD (let visual land)
            frame_specs.append((photo, PHOTO_DUR))

            # 3. Bridge text between photos (not after last photo)
            if i < len(photo_paths) - 1 and len(text_lines) > 1:
                bridge = _create_text_frame(text_lines[1], width, height, frame_type="bridge")
                text_frames.append(bridge)
                frame_specs.append((bridge, BRIDGE_DUR))

        # 4. Bridge text after last photo (if no CTA, or as setup for CTA)
        if len(text_lines) > 1 and len(photo_paths) == 1:
            bridge = _create_text_frame(text_lines[1], width, height, frame_type="bridge")
            text_frames.append(bridge)
            frame_specs.append((bridge, BRIDGE_DUR))

        # 5. CTA text frame — LINGER (drives saves/sends)
        if len(text_lines) >= 3:
            cta = _create_text_frame(
                text_lines[2], width, height,
                text_color=(255, 215, 0),  # gold — stands out
                frame_type="cta",
            )
            text_frames.append(cta)
            frame_specs.append((cta, CTA_DUR))

        total_dur = sum(d for _, d in frame_specs)
        log.info(
            "Hook-photo reel: %d photos + %d text frames = %d total (%.1fs) "
            "[hook=%.1fs photo=%.1fs bridge=%.1fs cta=%.1fs]",
            len(photo_paths), len(text_frames), len(frame_specs), total_dur,
            HOOK_DUR, PHOTO_DUR, BRIDGE_DUR, CTA_DUR,
        )

        # Generate individual clips with per-frame durations
        # Text frames → _text_frame_to_clip (zoom + fade, fast)
        # Photo frames → image_to_video (Ken Burns + snap zoom, full pipeline)
        for i, (img_path, dur) in enumerate(frame_specs):
            clip_path = os.path.join(
                tempfile.gettempdir(), f"hook_clip_{i}_{os.getpid()}.mp4"
            )

            is_text_frame = img_path in text_frames
            if is_text_frame:
                # Determine frame type from position
                if i == 0:
                    ft = "hook"
                elif i == len(frame_specs) - 1:
                    ft = "cta"
                else:
                    ft = "bridge"
                _text_frame_to_clip(img_path, clip_path, width, height, dur, ft)
                temp_clips.append(clip_path)
            else:
                # Photo frame: full Ken Burns pipeline, then trim
                image_to_video(
                    img_path, clip_path, width, height,
                    duration=max(1, int(dur + 0.5)),
                    add_audio=False,
                )
                # Trim to exact float duration
                trimmed_path = os.path.join(
                    tempfile.gettempdir(), f"hook_trim_{i}_{os.getpid()}.mp4"
                )
                trim_cmd = [
                    ffmpeg, "-y", "-i", clip_path,
                    "-t", f"{dur:.2f}",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-an", trimmed_path,
                ]
                result = subprocess.run(trim_cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    temp_clips.append(trimmed_path)
                    _audio_safe_remove(clip_path)
                else:
                    temp_clips.append(clip_path)

        # Concatenate all clips
        list_path = os.path.join(
            tempfile.gettempdir(), f"hook_list_{os.getpid()}.txt"
        )
        with open(list_path, "w") as f:
            for clip in temp_clips:
                f.write(f"file '{clip}'\n")

        # Get audio if needed (YouTube)
        if add_audio:
            raw_audio = get_background_track(total_dur)
            if raw_audio:
                if not raw_audio.startswith(tempfile.gettempdir()):
                    trimmed = trim_audio(raw_audio, total_dur)
                    if trimmed:
                        audio_path = trimmed
                        audio_is_temp = True
                    else:
                        audio_path = raw_audio
                else:
                    audio_path = raw_audio
                    audio_is_temp = True

        if audio_path:
            cmd = [
                ffmpeg, "-y",
                "-f", "concat", "-safe", "0", "-i", list_path,
                "-i", audio_path,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-t", f"{total_dur:.2f}",
                "-map", "0:v", "-map", "1:a",
                output_path,
            ]
        else:
            # Silent audio track (Instagram needs audio stream for music overlay)
            cmd = [
                ffmpeg, "-y",
                "-f", "concat", "-safe", "0", "-i", list_path,
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "32k",
                "-t", f"{total_dur:.2f}",
                "-map", "0:v", "-map", "1:a",
                "-shortest",
                output_path,
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            log.error("Hook reel ffmpeg stderr: %s", (result.stderr or "")[-500:])
            raise RuntimeError(f"Hook reel ffmpeg failed (exit {result.returncode})")

        file_size = os.path.getsize(output_path)
        log.info("Hook-photo reel: %s (%d bytes, %.1fs, %s audio)",
                 output_path, file_size, total_dur,
                 "with" if audio_path else "silent")
        return output_path

    finally:
        # Clean up temp files
        for tf in text_frames:
            try:
                os.remove(tf)
            except OSError:
                pass
        for tc in temp_clips:
            _audio_safe_remove(tc)
        _audio_safe_remove(os.path.join(
            tempfile.gettempdir(), f"hook_list_{os.getpid()}.txt"
        ))
        if audio_is_temp and audio_path:
            _audio_safe_remove(audio_path)


def convert_posts_to_video(posts: list[dict[str, Any]], youtube: bool = False) -> int:
    """Convert images to videos for posts that need it. Returns count converted.

    Audio strategy (2026 algorithm):
      - Instagram Reels: SILENT video — trending music is overlaid at publish time
        via publisher._find_trending_track() (Instagram algorithm boosts trending audio)
      - YouTube Shorts: WITH audio — royalty-free music baked in (Pixabay/user/ambient)

    Text overlay strategy (2026 — 85% watch on mute):
      - On-screen text captions from post's 'video_text' field
      - Hook → Body → CTA timed to appear sequentially
    """
    converted = 0
    for post in posts:
        status = str(post.get("status", "")).strip().lower()
        if status == "failed":
            continue
        # "posted" posts already published to IG — only process for YT videos
        is_posted = (status == "posted")
        if is_posted:
            # Skip if YouTube is off or post already has a YT video
            if not youtube or post.get("youtube_video_id"):
                continue

        # Single/photo posts publish as photos — no video needed
        post_type = str(post.get("post_type", "reel")).strip().lower()
        if post_type in ("single", "photo"):
            continue

        # Need an existing image to convert
        image_url = str(post.get("image_url", "")).strip()
        if not image_url or not os.path.exists(image_url):
            continue

        # Extract text overlay lines from post
        video_text = post.get("video_text")
        if isinstance(video_text, list):
            text_lines = [str(t).strip() for t in video_text if str(t).strip()][:3]
        else:
            text_lines = None

        # Hook-photo reel format: text hooks interleaved with photos
        # Detect: reel_format == "hook_photo" with 2+ carousel_images
        reel_format = str(post.get("reel_format", "")).strip().lower()
        if reel_format == "hook_photo" and not is_posted:
            carousel_images = post.get("carousel_images") or []
            valid_hook = (
                isinstance(carousel_images, list)
                and len(carousel_images) >= 1
                and all(os.path.exists(str(p)) for p in carousel_images)
            )
            if valid_hook and text_lines:
                video_url = str(post.get("video_url") or "").strip()
                if not video_url or not os.path.exists(video_url):
                    try:
                        hook_path = str(Path(image_url).with_name(
                            Path(image_url).stem + ".mp4"
                        ))
                        video_path = create_hook_photo_reel(
                            [str(p) for p in carousel_images],
                            hook_path,
                            width=IG_WIDTH,
                            height=YT_HEIGHT,  # 9:16 for reels
                            text_lines=text_lines,
                            add_audio=False,  # trending audio at publish
                        )
                        post["video_url"] = video_path
                        post["is_reel"] = True
                        converted += 1
                        log.info("Hook-photo reel created for %s", post.get("id"))
                    except Exception as exc:
                        log.warning("Hook-photo reel failed for %s: %s", post.get("id"), exc)

                # Also create YT version if youtube enabled
                if youtube:
                    yt_video = str(post.get("youtube_video_url") or "").strip()
                    if not yt_video or not os.path.exists(yt_video):
                        try:
                            yt_path = str(Path(image_url).with_name(
                                Path(image_url).stem + "_yt.mp4"
                            ))
                            create_hook_photo_reel(
                                [str(p) for p in carousel_images],
                                yt_path,
                                width=YT_WIDTH,
                                height=YT_HEIGHT,
                                text_lines=text_lines,
                                add_audio=True,  # baked audio for YT
                            )
                            post["youtube_video_url"] = yt_path
                        except Exception as exc:
                            log.warning("Hook-photo YT reel failed for %s: %s", post.get("id"), exc)
                continue  # hook-photo reel done — skip normal processing

        # Instagram video (4:5) — SILENT: trending audio added at publish time
        # Carousels publish as swipeable albums on IG — no video needed.
        # The montage video is created below for YouTube Shorts only.
        # Skip IG video for already-posted posts (already published to IG).
        if is_posted or post_type == "carousel":
            pass  # Skip IG video — either already posted or carousel (album)
        else:
            video_url = str(post.get("video_url") or "").strip()
            if not video_url or not os.path.exists(video_url):
                try:
                    video_path = image_to_video(
                        image_url, add_audio=False, text_lines=text_lines,
                    )
                    post["video_url"] = video_path
                    post["is_reel"] = True
                    converted += 1
                except Exception as exc:
                    log.warning("IG video conversion failed for %s: %s", post.get("id"), exc)

        # YouTube Shorts video (9:16) — WITH audio: royalty-free music baked in
        # For carousels: montage all slides into one Short (not just 1st image)
        if youtube:
            yt_video = str(post.get("youtube_video_url") or "").strip()
            if not yt_video or not os.path.exists(yt_video):
                try:
                    # Carousel → montage all slides into one YT Short
                    carousel_images = post.get("carousel_images") or []
                    valid_carousel = (
                        post_type == "carousel"
                        and isinstance(carousel_images, list)
                        and len(carousel_images) >= 3
                        and all(os.path.exists(str(p)) for p in carousel_images)
                    )

                    if valid_carousel:
                        yt_montage_path = str(Path(image_url).with_name(
                            Path(image_url).stem + "_yt.mp4"
                        ))
                        yt_path = images_to_montage(
                            [str(p) for p in carousel_images],
                            yt_montage_path,
                            YT_WIDTH, YT_HEIGHT, YT_MONTAGE_PER_IMAGE,
                            add_audio=True, text_lines=text_lines,
                        )
                    else:
                        yt_path = image_to_youtube_short(
                            image_url, text_lines=text_lines,
                        )
                    post["youtube_video_url"] = yt_path
                except Exception as exc:
                    log.warning("YT video conversion failed for %s: %s", post.get("id"), exc)

    return converted
