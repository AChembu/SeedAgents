from __future__ import annotations

import json

import httpx

from .config import Settings
from .models import ListingData, Storyboard


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


def _build_prompt(listing: ListingData, voice_style: str, include_neighborhood_copy: bool) -> str:
    return (
        "You are writing a concise real-estate walkthrough narration.\n"
        "Return strict JSON with keys: hook (string), scenes (array of 5 strings), cta (string), full_script (string).\n"
        "Keep full_script to 120-170 words and natural spoken style.\n"
        f"Voice style: {voice_style}\n"
        f"Include neighborhood context: {include_neighborhood_copy}\n"
        f"Listing title: {listing.title}\n"
        f"Address: {listing.address or 'N/A'}\n"
        f"Description: {listing.description}\n"
    )


async def build_storyboard(
    settings: Settings,
    listing: ListingData,
    voice_style: str,
    include_neighborhood_copy: bool,
) -> Storyboard:
    if settings.use_mock_mode:
        return _fallback_storyboard(listing)

    prompt = _build_prompt(listing, voice_style, include_neighborhood_copy)
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
        return Storyboard(
            hook=parsed["hook"],
            scenes=parsed["scenes"],
            cta=parsed["cta"],
            full_script=parsed["full_script"],
        )
    except Exception:
        return _fallback_storyboard(listing)
