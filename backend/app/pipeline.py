from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

from .config import Settings
from .home_matcher import HomeConsistencyModel
from .llm import build_storyboard
from .media import compose_from_clips, compose_from_images, download_image, download_video, normalize_jpeg
from .models import GenerateRequest, JobStatus
from .scraper import listing_from_address, scrape_listing
from .seed_clients import SeedSpeechClient, SeedanceClient, SeedreamClient

logger = logging.getLogger(__name__)


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _download_and_select_raw_frames(
    listing_image_urls: list[str],
    raw_dir: Path,
    matcher: HomeConsistencyModel,
    max_photos: int,
) -> tuple[list[Path], list[Path]]:
    raw_paths: list[Path] = []
    for idx, image_url in enumerate(listing_image_urls, start=1):
        raw_path = raw_dir / f"photo_{idx}.jpg"
        await download_image(str(image_url), raw_path)
        await asyncio.to_thread(normalize_jpeg, raw_path)
        raw_paths.append(raw_path)

    selected_raw_paths = await asyncio.to_thread(matcher.select_consistent_images, raw_paths, max_photos)
    if not selected_raw_paths:
        selected_raw_paths = raw_paths[:1]
    return raw_paths, selected_raw_paths


async def run_generation_job(
    settings: Settings,
    request: GenerateRequest,
    job_id: str,
    set_state,
) -> dict[str, Any]:
    def set_progress(message: str) -> None:
        set_state(progress=message)
        logger.info("job=%s step=%s", job_id, message)

    work_dir = _ensure_dir(settings.output_dir / job_id)
    raw_dir = _ensure_dir(work_dir / "raw")
    polished_dir = _ensure_dir(work_dir / "polished")
    clips_dir = _ensure_dir(work_dir / "clips")

    set_state(status=JobStatus.running, progress="Reading listing data")
    logger.info("job=%s started max_photos=%s", job_id, request.max_photos)
    if request.listing_url:
        try:
            listing = await scrape_listing(str(request.listing_url), max_photos=request.max_photos, settings=settings)
        except Exception:
            # Many listing sites (e.g., Zillow) block bot-like scraping; degrade gracefully.
            logger.exception("job=%s scrape failed, using address fallback", job_id)
            fallback_address = request.address or "Requested property listing"
            listing = listing_from_address(fallback_address, max_photos=request.max_photos)
            listing.source_url = request.listing_url
            set_progress("Listing site blocked scraping; using address fallback data")
    elif request.address:
        listing = listing_from_address(request.address, max_photos=request.max_photos)
    else:
        raise ValueError("Either listing_url or address must be provided.")

    set_progress("Writing narration and scene plan")
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

    set_progress("Downloading listing photos")
    raw_paths, selected_raw_paths = await _download_and_select_raw_frames(
        [str(url) for url in listing.image_urls],
        raw_dir,
        matcher,
        request.max_photos,
    )
    logger.info("job=%s downloaded_raw=%s", job_id, len(raw_paths))

    set_progress("Validating photos match the same property")
    selected_unique_count = len(selected_raw_paths)
    logger.info("job=%s selected_consistent=%s", job_id, selected_unique_count)

    # If extraction quality is poor and Firecrawl is configured, re-scrape with rendered content.
    if (
        request.listing_url
        and selected_unique_count < settings.min_unique_story_frames
        and settings.use_firecrawl
        and settings.firecrawl_api_key
    ):
        try:
            set_progress("Low frame diversity detected, retrying scrape with Firecrawl")
            better_listing = await scrape_listing(
                str(request.listing_url),
                max_photos=request.max_photos * 3,
                settings=settings,
                force_firecrawl=True,
            )
            better_raw_paths, better_selected = await _download_and_select_raw_frames(
                [str(url) for url in better_listing.image_urls],
                raw_dir,
                matcher,
                request.max_photos,
            )
            if len(better_selected) > selected_unique_count:
                listing = better_listing
                raw_paths = better_raw_paths
                selected_raw_paths = better_selected
                selected_unique_count = len(selected_raw_paths)
                logger.info("job=%s firecrawl_retry_improved selected=%s", job_id, selected_unique_count)
        except Exception:
            # Keep original scrape result when Firecrawl retry fails.
            logger.exception("job=%s firecrawl retry failed; keeping original scrape", job_id)
            pass

    # Never duplicate photos. Use up to user max or available unique photos.
    target_count = min(request.max_photos, len(raw_paths))
    if len(selected_raw_paths) < target_count:
        selected_set = set(selected_raw_paths)
        for raw in raw_paths:
            if raw not in selected_set:
                selected_raw_paths.append(raw)
                selected_set.add(raw)
            if len(selected_raw_paths) >= target_count:
                break
    selected_raw_paths = selected_raw_paths[:target_count]
    logger.info(
        "job=%s final_frame_selection target=%s selected=%s",
        job_id,
        target_count,
        len(selected_raw_paths),
    )

    set_progress("Polishing keyframe photos")
    polished_paths: list[Path] = []
    for idx, raw_path in enumerate(selected_raw_paths, start=1):
        scene_index = (idx - 1) % len(storyboard.scenes)

        polish_prompt = (
            f"Polished real-estate keyframe, bright and realistic lighting, "
            f"premium architectural photography style. Scene note: {storyboard.scenes[scene_index]}"
        )
        polished_path = polished_dir / f"keyframe_{idx}.jpg"
        try:
            await seedream.polish_keyframe(raw_path, polish_prompt, polished_path)
        except Exception as exc:
            # If image model/API is unavailable, keep pipeline moving with original frame.
            logger.warning(
                "job=%s keyframe_polish_failed idx=%s fallback=raw_copy err=%s",
                job_id,
                idx,
                exc,
            )
            shutil.copy2(raw_path, polished_path)
        polished_paths.append(polished_path)

    set_progress("Generating voice narration")
    narration_path = work_dir / "narration.mp3"
    try:
        await speech.synthesize(storyboard.full_script, narration_path)
        logger.info("job=%s narration_ready bytes=%s", job_id, narration_path.stat().st_size if narration_path.exists() else 0)
    except Exception as exc:
        # Keep output renderable when TTS endpoint/network is unavailable.
        logger.warning("job=%s narration_failed continuing_without_audio err=%s", job_id, exc)
        narration_path.write_bytes(b"")
        set_progress("Voice API unavailable, continuing without narration")

    set_progress("Generating Seedance walkthrough clips")
    clip_paths: list[Path] = []
    for idx, polished in enumerate(polished_paths, start=1):
        motion_prompt = (
            "Cinematic real-estate walkthrough motion, smooth dolly-in and gentle pan, "
            f"ultra realistic details. Scene: {storyboard.scenes[(idx - 1) % len(storyboard.scenes)]}"
        )
        try:
            clip_url = await seedance.image_to_video(polished, motion_prompt)
        except Exception as exc:
            # Fall back to image-based compose if video generation fails.
            logger.warning("job=%s seedance_failed idx=%s; skipping clip err=%s", job_id, idx, exc)
            continue
        if clip_url.startswith("mock://"):
            logger.info("job=%s seedance_mock_clip idx=%s", job_id, idx)
            continue
        clip_path = clips_dir / f"clip_{idx}.mp4"
        await download_video(clip_url, clip_path)
        clip_paths.append(clip_path)
        logger.info("job=%s clip_downloaded idx=%s path=%s", job_id, idx, clip_path.name)

    set_progress("Composing final narrated walkthrough video")
    final_video_path = work_dir / "walkthrough.mp4"
    if clip_paths:
        logger.info("job=%s compose_mode=clips clip_count=%s", job_id, len(clip_paths))
        await asyncio.to_thread(compose_from_clips, clip_paths, narration_path, final_video_path)
    else:
        logger.info("job=%s compose_mode=images image_count=%s", job_id, len(polished_paths))
        await asyncio.to_thread(
            compose_from_images,
            polished_paths,
            narration_path,
            final_video_path,
            4.0,
            settings.use_mock_mode,
        )
    logger.info("job=%s complete output=%s", job_id, final_video_path)

    return {
        "listing": listing.model_dump(mode="json"),
        "requested_max_photos": request.max_photos,
        "raw_photo_count": len(raw_paths),
        "selected_photo_count": len(selected_raw_paths),
        "selected_unique_photo_count": selected_unique_count,
        "selected_photos": [path.name for path in selected_raw_paths],
        "selected_source_urls": [str(url) for url in listing.image_urls],
        "storyboard": storyboard.model_dump(mode="json"),
        "narration_file": str(narration_path),
        "video_file": str(final_video_path),
        "video_rel_path": f"{job_id}/walkthrough.mp4",
        "work_dir": str(work_dir),
    }
