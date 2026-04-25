from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .config import Settings
from .home_matcher import HomeConsistencyModel
from .llm import build_storyboard
from .media import compose_from_clips, compose_from_images, download_image, download_video, normalize_jpeg
from .models import GenerateRequest, JobStatus
from .scraper import listing_from_address, scrape_listing
from .seed_clients import SeedSpeechClient, SeedanceClient, SeedreamClient


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cycle_to_count(items: list[Path], target_count: int) -> list[Path]:
    if not items:
        return []
    if len(items) >= target_count:
        return items[:target_count]
    out = list(items)
    idx = 0
    while len(out) < target_count:
        out.append(items[idx % len(items)])
        idx += 1
    return out


async def run_generation_job(
    settings: Settings,
    request: GenerateRequest,
    job_id: str,
    set_state,
) -> dict[str, Any]:
    work_dir = _ensure_dir(settings.output_dir / job_id)
    raw_dir = _ensure_dir(work_dir / "raw")
    polished_dir = _ensure_dir(work_dir / "polished")
    clips_dir = _ensure_dir(work_dir / "clips")

    set_state(status=JobStatus.running, progress="Reading listing data")
    if request.listing_url:
        try:
            listing = await scrape_listing(str(request.listing_url), max_photos=request.max_photos)
        except Exception:
            # Many listing sites (e.g., Zillow) block bot-like scraping; degrade gracefully.
            fallback_address = request.address or "Requested property listing"
            listing = listing_from_address(fallback_address, max_photos=request.max_photos)
            listing.source_url = request.listing_url
            set_state(progress="Listing site blocked scraping; using address fallback data")
    elif request.address:
        listing = listing_from_address(request.address, max_photos=request.max_photos)
    else:
        raise ValueError("Either listing_url or address must be provided.")

    set_state(progress="Writing narration and scene plan")
    storyboard = await build_storyboard(
        settings,
        listing,
        request.voice_style,
        request.include_neighborhood_copy,
    )

    seedream = SeedreamClient(settings)
    seedance = SeedanceClient(settings)
    speech = SeedSpeechClient(settings)
    matcher = HomeConsistencyModel()

    set_state(progress="Downloading listing photos")
    raw_paths: list[Path] = []
    for idx, image_url in enumerate(listing.image_urls, start=1):
        raw_path = raw_dir / f"photo_{idx}.jpg"
        await download_image(str(image_url), raw_path)
        await asyncio.to_thread(normalize_jpeg, raw_path)
        raw_paths.append(raw_path)

    set_state(progress="Validating photos match the same property")
    selected_raw_paths = await asyncio.to_thread(matcher.select_consistent_images, raw_paths, request.max_photos)
    if not selected_raw_paths:
        selected_raw_paths = raw_paths[:1]
    selected_raw_paths = _cycle_to_count(selected_raw_paths, request.max_photos)

    set_state(progress="Polishing keyframe photos")
    polished_paths: list[Path] = []
    for idx, raw_path in enumerate(selected_raw_paths, start=1):
        scene_index = (idx - 1) % len(storyboard.scenes)

        polish_prompt = (
            f"Polished real-estate keyframe, bright and realistic lighting, "
            f"premium architectural photography style. Scene note: {storyboard.scenes[scene_index]}"
        )
        polished_path = polished_dir / f"keyframe_{idx}.jpg"
        await seedream.polish_keyframe(raw_path, polish_prompt, polished_path)
        polished_paths.append(polished_path)

    set_state(progress="Generating voice narration")
    narration_path = work_dir / "narration.mp3"
    await speech.synthesize(storyboard.full_script, narration_path)

    set_state(progress="Generating Seedance walkthrough clips")
    clip_paths: list[Path] = []
    for idx, polished in enumerate(polished_paths, start=1):
        motion_prompt = (
            "Cinematic real-estate walkthrough motion, smooth dolly-in and gentle pan, "
            f"ultra realistic details. Scene: {storyboard.scenes[(idx - 1) % len(storyboard.scenes)]}"
        )
        clip_url = await seedance.image_to_video(polished, motion_prompt)
        if clip_url.startswith("mock://"):
            continue
        clip_path = clips_dir / f"clip_{idx}.mp4"
        await download_video(clip_url, clip_path)
        clip_paths.append(clip_path)

    set_state(progress="Composing final narrated walkthrough video")
    final_video_path = work_dir / "walkthrough.mp4"
    if clip_paths:
        await asyncio.to_thread(compose_from_clips, clip_paths, narration_path, final_video_path)
    else:
        await asyncio.to_thread(
            compose_from_images,
            polished_paths,
            narration_path,
            final_video_path,
            4.0,
        )

    return {
        "listing": listing.model_dump(mode="json"),
        "selected_photo_count": len(selected_raw_paths),
        "storyboard": storyboard.model_dump(mode="json"),
        "narration_file": str(narration_path),
        "video_file": str(final_video_path),
        "video_rel_path": f"{job_id}/walkthrough.mp4",
        "work_dir": str(work_dir),
    }
