from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any, Iterable

import httpx
import imageio.v2 as imageio
import imageio_ffmpeg
import numpy as np
from moviepy import AudioFileClip, ImageClip, VideoFileClip, concatenate_videoclips, vfx
from PIL import Image, ImageDraw, ImageFont, ImageOps

# Final encode size; sidebar layout matches this aspect.
OUTPUT_W = 1280
OUTPUT_H = 720
SIDEBAR_WIDTH_RATIO = 0.27


async def download_image(url: str, out_path: Path) -> Path:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(str(url), follow_redirects=True)
        response.raise_for_status()
    out_path.write_bytes(response.content)
    return out_path


async def download_video(url: str, out_path: Path) -> Path:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.get(str(url), follow_redirects=True)
        response.raise_for_status()
    out_path.write_bytes(response.content)
    return out_path


def _load_stats_overlay_font(size: int = 20):
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_title_lines(text: str, font: ImageFont.ImageFont, draw: ImageDraw.ImageDraw, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) >= 3:
            break
    if current and len(lines) < 3:
        lines.append(current)
    return lines


def apply_stats_sidebar_to_frame(frame: np.ndarray, sidebar: dict[str, Any] | None) -> np.ndarray:
    """
    Place video on the left (~73%) and a vertical stats panel on the right.
    `sidebar`: { "title": str, "rows": [ {"label": str, "value": str}, ... ] }
    """
    if not sidebar or not sidebar.get("rows"):
        return frame

    rows_raw = sidebar["rows"]
    rows: list[tuple[str, str]] = []
    for item in rows_raw:
        if isinstance(item, dict) and "label" in item and "value" in item:
            rows.append((str(item["label"]), str(item["value"])))
    if not rows:
        return frame

    title = str(sidebar.get("title") or "Listing").strip() or "Listing"

    h_in, w_in = frame.shape[0], frame.shape[1]
    if h_in < 2 or w_in < 2:
        return frame

    out_w, out_h = OUTPUT_W, OUTPUT_H
    sidebar_w = int(round(out_w * SIDEBAR_WIDTH_RATIO))
    video_w = out_w - sidebar_w

    source = Image.fromarray(np.asarray(frame, dtype=np.uint8).clip(0, 255))
    if source.mode != "RGB":
        source = source.convert("RGB")
    fitted = ImageOps.fit(source, (video_w, out_h), method=Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (out_w, out_h), (14, 16, 18))
    canvas.paste(fitted, (0, 0))

    draw = ImageDraw.Draw(canvas, "RGBA")
    sx = video_w
    # Panel background
    draw.rectangle((sx, 0, out_w, out_h), fill=(22, 26, 30, 250))
    # Accent stripe
    draw.rectangle((sx, 0, sx + 5, out_h), fill=(110, 130, 75, 255))

    font_title = _load_stats_overlay_font(16)
    font_label = _load_stats_overlay_font(12)
    font_value = _load_stats_overlay_font(21)
    inner_left = sx + 16
    inner_w = out_w - inner_left - 14
    y = 18

    for line in _wrap_title_lines(title, font_title, draw, inner_w):
        draw.text((inner_left, y), line, fill=(235, 232, 220), font=font_title)
        bbox = draw.textbbox((inner_left, y), line, font=font_title)
        y = bbox[3] + 10
    y += 6
    draw.line((inner_left, y, out_w - 14, y), fill=(70, 78, 68), width=1)
    y += 14

    for label, value in rows:
        draw.text((inner_left, y), label.upper(), fill=(160, 168, 150), font=font_label)
        bbox = draw.textbbox((inner_left, y), label.upper(), font=font_label)
        y = bbox[3] + 4
        draw.text((inner_left, y), value, fill=(255, 255, 255), font=font_value)
        bbox = draw.textbbox((inner_left, y), value, font=font_value)
        y = bbox[3] + 18

    return np.asarray(canvas, dtype=np.uint8)


def normalize_jpeg(path: Path) -> Path:
    # Convert any source format to a clean RGB JPEG and cap size for faster encoding.
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        rgb.thumbnail((1920, 1080), Image.Resampling.LANCZOS)
        rgb.save(path, "JPEG", quality=90)
    return path


def _compose_silent_fast(
    image_paths: Iterable[Path],
    out_path: Path,
    seconds_per_image: float,
    fps: int = 24,
    size: tuple[int, int] = (OUTPUT_W, OUTPUT_H),
    stats_sidebar: dict[str, Any] | None = None,
) -> Path:
    writer = imageio.get_writer(str(out_path), fps=fps, codec="libx264")
    frames_per_image = max(1, int(seconds_per_image * fps))
    try:
        for path in image_paths:
            with Image.open(path) as img:
                frame = ImageOps.fit(img.convert("RGB"), size, method=Image.Resampling.LANCZOS)
            arr = np.array(frame)
            if stats_sidebar:
                arr = apply_stats_sidebar_to_frame(arr, stats_sidebar)
            for _ in range(frames_per_image):
                writer.append_data(arr)
    finally:
        writer.close()
    return out_path


def _mux_audio_fast(video_path: Path, audio_path: Path, out_path: Path) -> Path:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_path


def compose_from_images(
    image_paths: Iterable[Path],
    audio_path: Path | None,
    out_path: Path,
    seconds_per_image: float = 4.0,
    fast_mode: bool = False,
    stats_sidebar: dict[str, Any] | None = None,
) -> Path:
    images = list(image_paths)
    if not images:
        raise ValueError("No images provided for compose_from_images.")

    has_audio = bool(audio_path and audio_path.exists() and audio_path.stat().st_size > 0)
    if not has_audio:
        # Fast path for mock/no-audio runs; avoids long MoviePy render times.
        return _compose_silent_fast(
            images,
            out_path,
            seconds_per_image,
            fps=24,
            stats_sidebar=stats_sidebar,
        )

    # Ensure video is long enough for full narration + small tail, avoiding abrupt audio cutoff.
    assert audio_path is not None
    try:
        narration = AudioFileClip(str(audio_path))
        required_total_duration = max(0.0, float(narration.duration)) + 0.45
        narration.close()
    except Exception:
        required_total_duration = 0.0
    if required_total_duration > 0:
        seconds_per_image = max(seconds_per_image, required_total_duration / max(len(images), 1))

    if fast_mode and audio_path is not None:
        # Mock/preview mode: render frames fast and mux narration.
        temp_video = out_path.with_name(f"{out_path.stem}.video_only.mp4")
        try:
            _compose_silent_fast(
                images,
                temp_video,
                seconds_per_image,
                fps=24,
                stats_sidebar=stats_sidebar,
            )
            return _mux_audio_fast(temp_video, audio_path, out_path)
        except Exception:
            # Fall back to the heavier MoviePy path if ffmpeg mux fails.
            pass
        finally:
            if temp_video.exists():
                temp_video.unlink()

    sidebar = stats_sidebar

    def _maybe_sidebar(arr: np.ndarray) -> np.ndarray:
        return apply_stats_sidebar_to_frame(arr, sidebar) if sidebar else arr

    clips = [
        ImageClip(str(path))
        .with_duration(seconds_per_image)
        .with_effects([vfx.FadeIn(0.4), vfx.FadeOut(0.4)])
        .image_transform(_maybe_sidebar)
        for path in images
    ]
    timeline = concatenate_videoclips(clips, method="compose")
    if has_audio:
        narration = AudioFileClip(str(audio_path))
        timeline = timeline.with_audio(narration)
    timeline.write_videofile(str(out_path), fps=24, codec="libx264", audio_codec="aac", logger=None, preset="ultrafast")
    return out_path


def compose_from_clips(
    clip_paths: Iterable[Path],
    audio_path: Path | None,
    out_path: Path,
    stats_sidebar: dict[str, Any] | None = None,
) -> Path:
    clips = [VideoFileClip(str(path)) for path in clip_paths]
    timeline = concatenate_videoclips(clips, method="compose")
    if stats_sidebar:

        def _sidebar_frame(arr: np.ndarray) -> np.ndarray:
            return apply_stats_sidebar_to_frame(arr, stats_sidebar)

        timeline = timeline.image_transform(_sidebar_frame)
    if audio_path and audio_path.exists() and audio_path.stat().st_size > 0:
        narration = AudioFileClip(str(audio_path))
        if narration.duration > timeline.duration:
            narration = narration.subclipped(0, timeline.duration)
        timeline = timeline.with_audio(narration)
    timeline.write_videofile(str(out_path), fps=24, codec="libx264", audio_codec="aac", logger=None, preset="ultrafast")
    return out_path
