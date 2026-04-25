from __future__ import annotations

from pathlib import Path
from typing import Iterable

import httpx
import imageio.v2 as imageio
import numpy as np
from moviepy import AudioFileClip, ImageClip, VideoFileClip, concatenate_videoclips, vfx
from PIL import Image, ImageOps


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
    size: tuple[int, int] = (1280, 720),
) -> Path:
    writer = imageio.get_writer(str(out_path), fps=fps, codec="libx264")
    frames_per_image = max(1, int(seconds_per_image * fps))
    try:
        for path in image_paths:
            with Image.open(path) as img:
                frame = ImageOps.fit(img.convert("RGB"), size, method=Image.Resampling.LANCZOS)
            arr = np.array(frame)
            for _ in range(frames_per_image):
                writer.append_data(arr)
    finally:
        writer.close()
    return out_path


def compose_from_images(
    image_paths: Iterable[Path],
    audio_path: Path | None,
    out_path: Path,
    seconds_per_image: float = 4.0,
) -> Path:
    has_audio = bool(audio_path and audio_path.exists() and audio_path.stat().st_size > 0)
    if not has_audio:
        # Fast path for mock/no-audio runs; avoids long MoviePy render times.
        return _compose_silent_fast(image_paths, out_path, seconds_per_image, fps=24)

    clips = [
        ImageClip(str(path))
        .with_duration(seconds_per_image)
        .with_effects([vfx.FadeIn(0.4), vfx.FadeOut(0.4)])
        for path in image_paths
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
) -> Path:
    clips = [VideoFileClip(str(path)) for path in clip_paths]
    timeline = concatenate_videoclips(clips, method="compose")
    if audio_path and audio_path.exists() and audio_path.stat().st_size > 0:
        narration = AudioFileClip(str(audio_path))
        if narration.duration > timeline.duration:
            narration = narration.subclipped(0, timeline.duration)
        timeline = timeline.with_audio(narration)
    timeline.write_videofile(str(out_path), fps=24, codec="libx264", audio_codec="aac", logger=None, preset="ultrafast")
    return out_path
