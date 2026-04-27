from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .chat_research import gather_chat_research
from .config import Settings
from .models import ChatMessage

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 14_000
GEMINI_GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _strip_leading_assistant_for_gemini(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Gemini multi-turn should start with a user turn; the UI may prepend an assistant welcome."""
    out = list(messages)
    while out and out[0].role == "assistant":
        out.pop(0)
    return out


async def _chat_gemini(
    settings: Settings,
    system: str,
    messages: list[ChatMessage],
) -> str:
    model = settings.gemini_chat_model.strip() or "gemini-2.0-flash"
    url = f"{GEMINI_GENERATE_URL}/{model}:generateContent"
    for_turns = _strip_leading_assistant_for_gemini(messages)
    if not for_turns or for_turns[-1].role != "user":
        raise ValueError("Gemini: expected at least one user message after stripping welcome.")
    contents: list[dict[str, Any]] = []
    for m in for_turns:
        role = "user" if m.role == "user" else "model"
        contents.append(
            {
                "role": role,
                "parts": [{"text": m.content}],
            }
        )
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.45,
            "maxOutputTokens": 1200,
        },
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
        response = await client.post(
            url,
            params={"key": settings.gemini_api_key},
            json=body,
        )
    response.raise_for_status()
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        reason = data.get("promptFeedback", {})
        raise ValueError(f"Gemini returned no response: {reason}")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    if not parts or "text" not in parts[0]:
        raise ValueError("Gemini response had no text content.")
    return str(parts[0]["text"]).strip()


def _system_prompt(
    property_context: dict[str, Any] | None,
    research_notes: str = "",
    research_cap: int = 14_000,
) -> str:
    base = (
        "You are SeedEstate Field Guide, a knowledgeable, concise real estate assistant.\n"
        "Rules:\n"
        "- You may receive (1) saved property context from an earlier pipeline run and "
        "(2) live research: a refreshed copy of the listing page plus web search snippets. "
        "Prefer live research for current listing facts (e.g. price, status) when it conflicts with older context.\n"
        "- Only state numbers, prices, taxes, comps, or neighborhood claims that appear in context or live research. "
        "If research is missing, failed, or ambiguous, say so—do not invent.\n"
        "- Web search snippets are third-party blurbs; they can be wrong or stale. Attribute uncertainty when needed.\n"
        "- You may discuss general real estate topics (buying, selling, offers, inspections, staging) "
        "in educational, neutral language.\n"
        "- Do not give legal, tax, or investment advice; suggest consulting qualified professionals when appropriate.\n"
    )
    parts = [base]
    if research_notes.strip():
        rn = research_notes.strip()
        if len(rn) > research_cap:
            rn = rn[:research_cap] + "\n…(truncated)"
        parts.append("--- Live research (listing refresh + web search for this message) ---\n" + rn)
    if property_context:
        blob = json.dumps(property_context, indent=2, ensure_ascii=False)
        if len(blob) > MAX_CONTEXT_CHARS:
            blob = blob[:MAX_CONTEXT_CHARS] + "\n…(truncated)"
        parts.append("--- Saved property context (pipeline / UI) ---\n" + blob)
    else:
        parts.append("No saved listing context is loaded; use live research and general knowledge boundaries above.")
    return "\n".join(parts)


def _mock_reply(user_text: str) -> str:
    preview = (user_text[:300] + "…") if len(user_text) > 300 else user_text
    return (
        "[Mock mode] Add GEMINI_API_KEY, or OPENAI_API_KEY / ANTHROPIC_API_KEY, to the backend "
        "environment to enable live chat.\n\n"
        f"You asked: {preview}"
    )


async def run_property_chat(
    settings: Settings,
    messages: list[ChatMessage],
    property_context: dict[str, Any] | None,
) -> str:
    if not messages or messages[-1].role != "user":
        raise ValueError("Last message must be from the user.")

    has_gemini = bool((settings.gemini_api_key or "").strip())
    has_openai = bool(settings.openai_api_key)
    has_anthropic = bool(settings.anthropic_api_key)
    if settings.use_mock_mode and not (has_gemini or has_openai or has_anthropic):
        return _mock_reply(messages[-1].content)

    if not (has_gemini or has_openai or has_anthropic):
        return _mock_reply(messages[-1].content)

    research_notes = ""
    if settings.chat_web_research:
        try:
            research_notes = await gather_chat_research(
                settings,
                messages[-1].content,
                property_context,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("chat research skipped: %s", exc)

    system = _system_prompt(
        property_context,
        research_notes=research_notes,
        research_cap=settings.chat_research_max_chars,
    )
    timeout = settings.request_timeout_s
    model = settings.script_model

    if has_gemini:
        try:
            return await _chat_gemini(settings, system, messages)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            # Gracefully fall through to other providers when Gemini is throttled/unavailable.
            if (has_openai or has_anthropic) and status in (429, 500, 502, 503, 504):
                pass
            elif status == 429:
                raise ValueError(
                    "Gemini rate limit reached right now. Please retry in a minute."
                ) from exc
            else:
                raise ValueError(f"Gemini request failed (HTTP {status}).") from exc
        except Exception as exc:  # noqa: BLE001
            if not (has_openai or has_anthropic):
                raise ValueError("Gemini request failed. Please try again.") from exc

    if settings.script_provider == "anthropic" and has_anthropic:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "max_tokens": 1200,
                        "system": system,
                        "messages": [{"role": m.role, "content": m.content} for m in messages],
                    },
                )
                response.raise_for_status()
                return response.json()["content"][0]["text"].strip()
        except httpx.HTTPStatusError as exc:
            if has_openai and exc.response.status_code in (429, 500, 502, 503, 504):
                pass
            else:
                raise ValueError(
                    f"Anthropic chat failed (HTTP {exc.response.status_code})."
                ) from exc

    if has_openai:
        openai_messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        for m in messages:
            openai_messages.append({"role": m.role, "content": m.content})
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": openai_messages,
                        "temperature": 0.45,
                        "max_tokens": 1200,
                    },
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as exc:
            raise ValueError(
                f"OpenAI chat failed (HTTP {exc.response.status_code})."
            ) from exc

    return _mock_reply(messages[-1].content)
