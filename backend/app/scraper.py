from __future__ import annotations

from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .models import ListingData


def _to_abs_url(base: str, src: str) -> str:
    if src.startswith("http://") or src.startswith("https://"):
        return src
    return urljoin(base, src)


def _is_probably_listing_photo(url: str) -> bool:
    lowered = url.lower()
    blocked_tokens = [
        "logo",
        "icon",
        "sprite",
        "avatar",
        "favicon",
        "badge",
        "mls",
    ]
    if any(token in lowered for token in blocked_tokens):
        return False
    return lowered.endswith((".jpg", ".jpeg", ".png", ".webp")) or "image" in lowered or "photo" in lowered


def _stock_property_images(max_photos: int) -> list[str]:
    return [
        "https://images.unsplash.com/photo-1560185127-6ed189bf02f4",
        "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c",
        "https://images.unsplash.com/photo-1600566753190-17f0baa2a6c3",
        "https://images.unsplash.com/photo-1600047509807-ba8f99d2cdde",
        "https://images.unsplash.com/photo-1600573472550-8090b5e0745e",
        "https://images.unsplash.com/photo-1600607687644-c7171b42498f",
        "https://images.unsplash.com/photo-1564013799919-ab600027ffc6",
        "https://images.unsplash.com/photo-1600585154340-be6161a56a0c",
    ][:max_photos]


async def scrape_listing(url: str, max_photos: int = 6) -> ListingData:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, follow_redirects=True, headers=headers)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        og_title = soup.find("meta", attrs={"property": "og:title"})
        title = (og_title.get("content", "") if og_title else "").strip() or "Property Listing"

    og_desc = soup.find("meta", attrs={"property": "og:description"})
    description = (og_desc.get("content", "") if og_desc else "").strip()
    if not description:
        paragraphs = [p.get_text(" ", strip=True) for p in soup.select("p")]
        description = " ".join([p for p in paragraphs if len(p) > 40])[:1200]
    if not description:
        description = "Beautiful property with thoughtful design and comfortable living spaces."

    images: list[str] = []
    for tag in soup.select("img[src], img[data-src], img[data-lazy-src]"):
        src = tag.get("src") or tag.get("data-src") or tag.get("data-lazy-src")
        if not src:
            continue
        full = _to_abs_url(url, src.strip())
        if full.lower().endswith((".svg", ".gif")):
            continue
        if not _is_probably_listing_photo(full):
            continue
        if full not in images:
            images.append(full)
        if len(images) >= max_photos:
            break

    # Hackathon fallback: if listing site is sparse/blocked, pad with stock photos
    # so the final video still feels like a walkthrough.
    if len(images) < max_photos:
        for stock in _stock_property_images(max_photos):
            if stock not in images:
                images.append(stock)
            if len(images) >= max_photos:
                break

    return ListingData(
        title=title,
        description=description,
        image_urls=images[:max_photos],
        source_url=url,
    )


def listing_from_address(address: str, max_photos: int = 6) -> ListingData:
    # For MVP speed we synthesize a listing shell from an address if no URL is provided.
    stock_images = _stock_property_images(max_photos)
    return ListingData(
        title=f"Showcase for {address}",
        address=address,
        description=(
            "A polished residential listing with bright interiors, flexible living space, "
            "and strong curb appeal. The walkthrough emphasizes comfort, layout, and lifestyle fit."
        ),
        image_urls=stock_images,
    )
