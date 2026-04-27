from __future__ import annotations

import json
import re

import httpx

from .config import Settings
from .models import ListingData, Storyboard, VisualScope


def _sanitize_for_voice(text: str) -> str:
    cleaned = text
    # Remove MLS mention patterns that sound awkward in narration.
    cleaned = re.sub(r"\bmls\s*(number|#|no\.?)?\s*[:#-]?\s*[a-z0-9-]+\b", "", cleaned, flags=re.IGNORECASE)
    # Remove explicit Zillow branding mentions.
    cleaned = re.sub(r"\bzillow\b", "", cleaned, flags=re.IGNORECASE)
    # Collapse separators and whitespace artifacts left by removals.
    cleaned = re.sub(r"\s*[\|\-–]\s*", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.-")
    return cleaned


def _clean_listing_for_prompt(listing: ListingData) -> ListingData:
    return ListingData(
        title=_sanitize_for_voice(listing.title),
        description=_sanitize_for_voice(listing.description),
        address=_sanitize_for_voice(listing.address or "") or None,
        image_urls=listing.image_urls,
        source_url=listing.source_url,
        stats=listing.stats,
    )


def _clean_storyboard_text(storyboard: Storyboard) -> Storyboard:
    return Storyboard(
        hook=_sanitize_for_voice(storyboard.hook),
        scenes=[_sanitize_for_voice(scene) for scene in storyboard.scenes],
        cta=_sanitize_for_voice(storyboard.cta),
        full_script=_sanitize_for_voice(storyboard.full_script),
    )


def _fallback_storyboard(listing: ListingData) -> Storyboard:
    scenes = [
        "Start with curb appeal and neighborhood context.",
        "Walk into the main living area and highlight natural light.",
        "Show kitchen details, finishes, and hosting flow.",
        "Feature the primary suite with storage and privacy.",
        "Close on outdoor space and lifestyle fit.",
    ]
    script = (
        f"Welcome to {listing.title}. "
        "This home combines thoughtful design with practical comfort. "
        "As we move through the space, notice the open flow, natural lighting, and refined finishes. "
        "The kitchen anchors daily life with modern functionality, while private bedrooms provide a calm retreat. "
        "Outdoor areas extend living space and support entertaining. "
        "If you're looking for a move-in-ready property with character and efficiency, this one is worth a closer look."
    )
    return Storyboard(
        hook=f"Tour {listing.title} in 60 seconds.",
        scenes=scenes,
        cta="Book a private showing today.",
        full_script=script,
    )


def _build_prompt(
    listing: ListingData,
    voice_style: str,
    include_neighborhood_copy: bool,
    visual_scope: VisualScope,
) -> str:
    stats_line = ""
    if listing.stats and listing.stats.has_any():
        stats_line = f"Key facts (use naturally, do not sound like reading a datasheet): {listing.stats.summary_sentence()}\n"
    scope_line = (
        "Visual focus for this video: only exterior and curb appeal."
        if visual_scope == VisualScope.exterior
        else "Visual focus for this video: only interior living spaces."
        if visual_scope == VisualScope.interior
        else "Visual focus for this video: mix exterior and interior."
    )
    return (
        "You are writing a concise real-estate walkthrough narration.\n"
        "Return strict JSON with keys: hook (string), scenes (array of 5 strings), cta (string), full_script (string).\n"
        "Keep full_script to 120-170 words and natural spoken style.\n"
        f"Voice style: {voice_style}\n"
        f"Include neighborhood context: {include_neighborhood_copy}\n"
        f"{scope_line}\n"
        f"{stats_line}"
        f"Listing title: {listing.title}\n"
        f"Address: {listing.address or 'N/A'}\n"
        f"Description: {listing.description}\n"
    )


async def build_storyboard(
    settings: Settings,
    listing: ListingData,
    voice_style: str,
    include_neighborhood_copy: bool,
    visual_scope: VisualScope = VisualScope.both,
) -> Storyboard:
    cleaned_listing = _clean_listing_for_prompt(listing)
    if settings.use_mock_mode:
        return _clean_storyboard_text(_fallback_storyboard(cleaned_listing))

    prompt = _build_prompt(cleaned_listing, voice_style, include_neighborhood_copy, visual_scope)
    try:
        if settings.script_provider == "anthropic" and settings.anthropic_api_key:
            async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": settings.script_model,
                        "max_tokens": 700,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                response.raise_for_status()
                content = response.json()["content"][0]["text"]
        elif settings.openai_api_key:
            async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.script_model,
                        "response_format": {"type": "json_object"},
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.5,
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
        else:
            return _fallback_storyboard(listing)

        parsed = json.loads(content)
        storyboard = Storyboard(
            hook=parsed["hook"],
            scenes=parsed["scenes"],
            cta=parsed["cta"],
            full_script=parsed["full_script"],
        )
        return _clean_storyboard_text(storyboard)
    except Exception:
        return _clean_storyboard_text(_fallback_storyboard(cleaned_listing))
