from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from .config import Settings
from .scraper import fetch_raw_listing_html, listing_research_from_html

logger = logging.getLogger(__name__)


def _safe_listing_url(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    if not (u.startswith("https://") or u.startswith("http://")):
        return None
    lowered = u.lower()
    if "localhost" in lowered or "127.0.0.1" in lowered or ".local" in lowered:
        return None
    try:
        parsed = urlparse(u)
        host = (parsed.hostname or "").lower()
        if host in {"localhost", "0.0.0.0"}:
            return None
        if re.match(r"^(10|127)\.", host):
            return None
        if re.match(r"^192\.168\.", host):
            return None
        if re.match(r"^172\.(1[6-9]|2\d|3[0-1])\.", host):
            return None
    except ValueError:
        return None
    return u


def _listing_blob(
    property_context: dict[str, Any] | None,
) -> tuple[str | None, str | None, str | None]:
    if not property_context:
        return None, None, None
    listing = property_context.get("listing")
    if not isinstance(listing, dict):
        return None, None, None
    url = _safe_listing_url(listing.get("source_url"))
    raw_addr = listing.get("address")
    address = raw_addr.strip() if isinstance(raw_addr, str) and raw_addr.strip() else None
    raw_title = listing.get("title")
    title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else None
    return url, address, title


def _build_search_queries(
    user_message: str,
    address: str | None,
    title: str | None,
) -> list[str]:
    loc = (address or title or "").strip()
    um = user_message.strip()
    if len(um) > 240:
        um = um[:238] + "…"
    primary = f"{um} {loc}".strip()
    queries = [primary] if primary else []
    low = user_message.lower()
    if loc and any(
        k in low
        for k in (
            "compar",
            "similar",
            "comps",
            "neighborhood",
            "area ",
            "market",
            "sold ",
            "nearby",
            "average ",
        )
    ):
        queries.append(f"{loc} real estate comparable homes sale price trends")
    return queries[:2]


def _format_search_results(
    items: list[dict[str, str]],
    settings: Settings,
) -> str:
    lines: list[str] = []
    cap = settings.chat_search_snippet_chars
    for idx, item in enumerate(items[: settings.chat_search_max_results], start=1):
        t = (item.get("title") or "").strip()
        u = (item.get("url") or "").strip()
        s = (item.get("snippet") or "").strip()
        if len(s) > cap:
            s = s[: cap - 1] + "…"
        lines.append(f"{idx}. {t}\n   {u}\n   {s}")
    return "\n".join(lines)


async def _firecrawl_search(query: str, settings: Settings) -> list[dict[str, str]]:
    key = (settings.firecrawl_api_key or "").strip()
    if not key:
        return []
    endpoint = settings.firecrawl_base_url.rstrip("/") + "/search"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {"query": query, "limit": settings.chat_search_max_results}
    async with httpx.AsyncClient(timeout=min(settings.request_timeout_s, 25)) as client:
        response = await client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return []
    out: list[dict[str, str]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        title = str(row.get("title") or row.get("name") or "").strip()
        snippet = str(
            row.get("description") or row.get("snippet") or row.get("markdown") or ""
        ).strip()
        if url:
            out.append({"url": url, "title": title or url, "snippet": snippet})
    return out


def _unwrap_duckduckgo_redirect(href: str) -> str:
    if not href:
        return ""
    u = href.strip()
    if u.startswith("//"):
        u = "https:" + u
    if "uddg=" in u:
        parsed = urlparse(u)
        qs = parse_qs(parsed.query)
        raw_list = qs.get("uddg")
        if raw_list and raw_list[0]:
            return unquote(raw_list[0])
    return u


async def _duckduckgo_html_search(query: str, settings: Settings) -> list[dict[str, str]]:
    """HTML SERP (works on many residential IPs; datacenter IPs may get a bot challenge)."""
    q = quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={q}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://duckduckgo.com/",
    }
    async with httpx.AsyncClient(timeout=min(settings.request_timeout_s, 22), follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        html = response.text
    if "anomaly-modal" in html or "Unfortunately, bots use DuckDuckGo" in html:
        return []
    soup = BeautifulSoup(html, "lxml")
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for div in soup.select(".web-result"):
        link = div.select_one("a.result__a")
        if not link:
            continue
        raw_href = (link.get("href") or "").strip()
        href = _unwrap_duckduckgo_redirect(raw_href)
        if not href.startswith("http"):
            continue
        if href in seen:
            continue
        title = link.get_text(" ", strip=True)
        sn = div.select_one(".result__snippet")
        snippet = sn.get_text(" ", strip=True) if sn else ""
        seen.add(href)
        results.append({"url": href, "title": title or href, "snippet": snippet})
        if len(results) >= settings.chat_search_max_results:
            break
    if not results:
        # Older / alternate markup
        for link in soup.select("a.result__a"):
            raw_href = (link.get("href") or "").strip()
            href = _unwrap_duckduckgo_redirect(raw_href)
            if not href.startswith("http") or href in seen:
                continue
            title = link.get_text(" ", strip=True)
            parent = link.find_parent("div")
            snippet = ""
            if parent:
                sn = parent.select_one(".result__snippet")
                if sn:
                    snippet = sn.get_text(" ", strip=True)
            seen.add(href)
            results.append({"url": href, "title": title or href, "snippet": snippet})
            if len(results) >= settings.chat_search_max_results:
                break
    return results


async def search_web(query: str, settings: Settings) -> list[dict[str, str]]:
    if settings.firecrawl_api_key.strip():
        try:
            found = await _firecrawl_search(query, settings)
            if found:
                return found
        except Exception:
            logger.debug("Firecrawl search failed; falling back to DuckDuckGo", exc_info=True)
    try:
        return await _duckduckgo_html_search(query, settings)
    except Exception:
        logger.debug("DuckDuckGo HTML search failed", exc_info=True)
        return []


async def gather_chat_research(
    settings: Settings,
    user_message: str,
    property_context: dict[str, Any] | None,
) -> str:
    if not settings.chat_web_research:
        return ""

    listing_url, address, title = _listing_blob(property_context)
    sections: list[str] = []

    async def refresh_listing() -> None:
        if not listing_url:
            return
        try:
            html = await asyncio.wait_for(
                fetch_raw_listing_html(listing_url, settings),
                timeout=float(min(22, settings.chat_research_total_timeout_s)),
            )
            excerpt = listing_research_from_html(
                html,
                listing_url,
                max_text=settings.chat_listing_excerpt_chars,
            )
            sections.append(
                "=== Listing URL (refreshed for this question) ===\n"
                + json.dumps(excerpt, indent=2, ensure_ascii=False)
            )
        except TimeoutError:
            sections.append("=== Listing URL refresh timed out ===")
        except Exception as exc:
            logger.info("chat listing refresh failed: %s", exc)
            sections.append(f"=== Listing URL refresh failed: {exc} ===")

    async def run_searches() -> None:
        queries = _build_search_queries(user_message, address, title)
        if not queries and not listing_url:
            return
        if not queries:
            queries = [
                f"{address or title or 'this property'} real estate listing price market",
            ]
        for q in queries:
            try:
                found = await asyncio.wait_for(
                    search_web(q, settings),
                    timeout=float(min(18, settings.chat_research_total_timeout_s)),
                )
                if not found:
                    sections.append(f'=== Web search (no results) query="{q}" ===')
                    continue
                block = _format_search_results(found, settings)
                sections.append(f'=== Web search results query="{q}" ===\n{block}')
            except TimeoutError:
                sections.append(f'=== Web search timed out query="{q}" ===')
            except Exception as exc:
                logger.info("chat web search failed: %s", exc)
                sections.append(f'=== Web search failed query="{q}": {exc} ===')

    async def _gather() -> None:
        await asyncio.gather(
            refresh_listing(),
            run_searches(),
        )

    try:
        await asyncio.wait_for(_gather(), timeout=float(settings.chat_research_total_timeout_s))
    except TimeoutError:
        logger.warning("chat research overall timeout")
        sections.append("=== Research timed out (partial data may be missing) ===")

    blob = "\n\n".join(s for s in sections if s.strip())
    max_c = settings.chat_research_max_chars
    if len(blob) > max_c:
        blob = blob[: max_c - 20] + "\n…(research truncated)"
    return blob
