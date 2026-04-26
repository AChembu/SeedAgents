from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from .config import Settings
from .models import ListingData

logger = logging.getLogger(__name__)


def _zillow_photos_url(url: str) -> str | None:
    """Return Zillow's gallery URL (`.../photos/`) for a homedetails listing, else None."""
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if "zillow.com" not in host:
        return None
    path = parts.path
    if "/homedetails/" not in path.lower():
        return None
    if not path.endswith("/"):
        path = path + "/"
    if path.lower().endswith("/photos/"):
        return None
    return urlunsplit((parts.scheme, parts.netloc, path + "photos/", "", ""))


def _extract_size_from_url(url: str) -> tuple[int, int] | None:
    lowered = url.lower()
    patterns = [
        r"-sc_(\d{2,4})_(\d{2,4})",
        r"_(\d{2,4})_(\d{2,4})\.(?:jpg|jpeg|png|webp)$",
        r"-zillow_web_(\d{2,4})_(\d{2,4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


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
        "tracking",
        "analytics",
        "sprite",
    ]
    if any(token in lowered for token in blocked_tokens):
        return False
    if not (lowered.endswith((".jpg", ".jpeg", ".png", ".webp")) or "image" in lowered or "photo" in lowered):
        return False
    if "zillow_web_" in lowered:
        return False
    size = _extract_size_from_url(lowered)
    if size:
        width, height = size
        if width < 640 or height < 420:
            return False
    return True


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


def _extract_zillow_photo_urls(html: str, max_photos: int) -> list[str]:
    # Zillow frequently stores listing photos in embedded JSON blobs instead of plain <img> tags.
    patterns = [
        r"https://photos\.zillowstatic\.com/fp/[^\s\"'<>\\]+",
        r"https:\\/\\/photos\.zillowstatic\.com\\/fp\\/[^\s\"'<>\\]+",
    ]
    found: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, html):
            url = match.replace("\\/", "/")
            if url not in found and _is_probably_listing_photo(url):
                found.append(url)
            if len(found) >= max_photos * 3:
                break
    return found[: max_photos * 3]


def _extract_jsonld_images(soup: BeautifulSoup) -> list[str]:
    images: list[str] = []
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in scripts:
        text = script.string or script.get_text("", strip=True)
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        candidates: list[str] = []
        if isinstance(payload, dict):
            image_field = payload.get("image")
            if isinstance(image_field, str):
                candidates.append(image_field)
            elif isinstance(image_field, list):
                candidates.extend([item for item in image_field if isinstance(item, str)])
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    image_field = item.get("image")
                    if isinstance(image_field, str):
                        candidates.append(image_field)
                    elif isinstance(image_field, list):
                        candidates.extend([img for img in image_field if isinstance(img, str)])
        for candidate in candidates:
            if candidate not in images and _is_probably_listing_photo(candidate):
                images.append(candidate)
    return images


def _walk_for_image_urls(node: object, out: list[str]) -> None:
    if isinstance(node, dict):
        for _, value in node.items():
            _walk_for_image_urls(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk_for_image_urls(item, out)
    elif isinstance(node, str):
        if "http" in node and _is_probably_listing_photo(node):
            if node not in out:
                out.append(node)


def _extract_embedded_json_images(soup: BeautifulSoup) -> list[str]:
    images: list[str] = []
    for script in soup.find_all("script"):
        script_text = script.string or script.get_text()
        if not script_text:
            continue

        if script.get("id") == "__NEXT_DATA__":
            try:
                payload = json.loads(script_text)
            except json.JSONDecodeError:
                continue
            _walk_for_image_urls(payload, images)
            continue

        if "zillowstatic.com/fp/" in script_text:
            for match in _extract_zillow_photo_urls(script_text, max_photos=100):
                if match not in images:
                    images.append(match)
    return images


def _zillow_photo_key(url: str) -> str:
    match = re.search(r"/fp/([a-zA-Z0-9]+)", url)
    if match:
        return match.group(1)
    return url


def _zillow_quality_score(url: str) -> int:
    lowered = url.lower()
    score = 0
    if "-p_f" in lowered:
        score += 2000
    cc_match = re.search(r"-cc_ft_(\d+)", lowered)
    if cc_match:
        score += int(cc_match.group(1))
    sc_match = re.search(r"-sc_(\d{2,4})_(\d{2,4})", lowered)
    if sc_match:
        score += int(sc_match.group(1)) * int(sc_match.group(2)) // 500
    web_match = re.search(r"_(\d{2,4})_(\d{2,4})\.(?:jpg|jpeg|png|webp)$", lowered)
    if web_match:
        score += int(web_match.group(1)) * int(web_match.group(2)) // 2000
    if "zillow_web_" in lowered:
        score -= 1500
    return score


def _choose_best_zillow_variants(urls: Iterable[str]) -> list[str]:
    best_for_key: dict[str, tuple[str, int]] = {}
    for url in urls:
        if "photos.zillowstatic.com/fp/" not in url:
            continue
        key = _zillow_photo_key(url)
        score = _zillow_quality_score(url)
        current = best_for_key.get(key)
        if current is None or score > current[1]:
            best_for_key[key] = (url, score)
    # Keep deterministic order but sorted by quality descending.
    ordered = sorted((value for value in best_for_key.values()), key=lambda item: item[1], reverse=True)
    return [url for url, _ in ordered]


def _extract_title_and_description(soup: BeautifulSoup) -> tuple[str, str]:
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
    return title, description


def _extract_tag_image_urls(soup: BeautifulSoup, page_url: str) -> list[str]:
    images: list[str] = []
    for tag in soup.select("img[src], img[data-src], img[data-lazy-src], source[srcset]"):
        src = tag.get("src") or tag.get("data-src") or tag.get("data-lazy-src")
        if not src and tag.get("srcset"):
            src = str(tag.get("srcset")).split(",")[0].strip().split(" ")[0]
        if not src:
            continue
        full = _to_abs_url(page_url, src.strip())
        if full.lower().endswith((".svg", ".gif")):
            continue
        if not _is_probably_listing_photo(full):
            continue
        if full not in images:
            images.append(full)
    return images


async def _fetch_direct_html(url: str, timeout_s: int) -> tuple[str, int]:
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
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.get(url, follow_redirects=True, headers=headers)
    response.raise_for_status()
    return response.text, response.status_code


async def _fetch_firecrawl_html(url: str, settings: Settings) -> str | None:
    if not settings.use_firecrawl or not settings.firecrawl_api_key:
        return None
    endpoint = settings.firecrawl_base_url.rstrip("/") + "/scrape"
    payload = {
        "url": url,
        "formats": ["html", "markdown"],
    }
    headers = {
        "Authorization": f"Bearer {settings.firecrawl_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
    except Exception:
        return None

    data = body.get("data", {}) if isinstance(body, dict) else {}
    html = data.get("html")
    if isinstance(html, str) and html.strip():
        return html
    markdown = data.get("markdown")
    if isinstance(markdown, str) and markdown.strip():
        # If HTML is unavailable, at least preserve text extraction path.
        return f"<html><body><p>{markdown}</p></body></html>"
    return None


async def scrape_listing(
    url: str,
    max_photos: int = 8,
    settings: Settings | None = None,
    force_firecrawl: bool = False,
) -> ListingData:
    cfg = settings or Settings()
    html: str
    if force_firecrawl:
        fallback_html = await _fetch_firecrawl_html(url, cfg)
        if fallback_html:
            html = fallback_html
        else:
            html, _ = await _fetch_direct_html(url, timeout_s=cfg.request_timeout_s)
    else:
        try:
            html, _ = await _fetch_direct_html(url, timeout_s=cfg.request_timeout_s)
        except Exception:
            fallback_html = await _fetch_firecrawl_html(url, cfg)
            if not fallback_html:
                raise
            html = fallback_html

    soup = BeautifulSoup(html, "lxml")
    title, description = _extract_title_and_description(soup)

    image_pool: list[str] = []
    for source_images in (
        _extract_tag_image_urls(soup, url),
        _extract_jsonld_images(soup),
        _extract_embedded_json_images(soup),
    ):
        for image_url in source_images:
            if image_url not in image_pool:
                image_pool.append(image_url)

    if "zillow.com" in url.lower():
        zillow = _extract_zillow_photo_urls(html, max_photos=max_photos * 4)
        best = _choose_best_zillow_variants(zillow)
        for image_url in best:
            if image_url not in image_pool:
                image_pool.append(image_url)

        # Second pass: Zillow's `/photos/` gallery page often inlines the full manifest
        # (including lazy-loaded images) inside __NEXT_DATA__. Fetch it and merge.
        photos_url = _zillow_photos_url(url)
        if photos_url:
            try:
                photos_html, _ = await _fetch_direct_html(photos_url, timeout_s=cfg.request_timeout_s)
                photos_soup = BeautifulSoup(photos_html, "lxml")
                gallery_candidates: list[str] = []
                gallery_candidates.extend(_extract_zillow_photo_urls(photos_html, max_photos=max_photos * 8))
                gallery_candidates.extend(_extract_embedded_json_images(photos_soup))
                gallery_candidates.extend(_extract_jsonld_images(photos_soup))
                added = 0
                for image_url in gallery_candidates:
                    if image_url not in image_pool:
                        image_pool.append(image_url)
                        added += 1
                logger.info("zillow gallery pass added=%s url=%s", added, photos_url)
            except Exception:
                logger.exception("zillow gallery pass failed url=%s", photos_url)

        # Canonicalize across all collected Zillow variants and keep highest quality per photo id.
        canonical_zillow = _choose_best_zillow_variants(image_pool)
        non_zillow = [item for item in image_pool if "photos.zillowstatic.com/fp/" not in item]
        image_pool = canonical_zillow + non_zillow

    images = [item for item in image_pool if _is_probably_listing_photo(item)]
    if len(images) < 1:
        images = _stock_property_images(max_photos=1)

    return ListingData(
        title=title,
        description=description,
        image_urls=images[:max_photos],
        source_url=url,
    )


def listing_from_address(address: str, max_photos: int = 8) -> ListingData:
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
