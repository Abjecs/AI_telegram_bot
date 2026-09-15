from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from gigachat import GigaChat
from gigachat.models import ChatCompletionRequest, ChatMessage

from config import (
    AI_HISTORY_MESSAGES,
    AI_MAX_CONCURRENT,
    AI_MAX_INPUT_CHARS,
    AI_MAX_OUTPUT_CHARS,
    AI_MAX_RETRIES,
    AI_RATE_LIMIT,
    AI_RATE_WINDOW_SECONDS,
    AI_RETRY_BACKOFF,
    AI_TIMEOUT,
    GIGACHAT_BASE_URL,
    GIGACHAT_CA_BUNDLE_FILE,
    GIGACHAT_CREDENTIALS,
    GIGACHAT_MODEL,
    GIGACHAT_SCOPE,
    GIGACHAT_VERIFY_SSL_CERTS,
)
from services.rate_limit import SlidingWindowRateLimiter

logger = logging.getLogger(__name__)
_semaphore = asyncio.Semaphore(AI_MAX_CONCURRENT)
_rate_limiter = SlidingWindowRateLimiter(AI_RATE_LIMIT, AI_RATE_WINDOW_SECONDS)


def _clean(value: str, limit: int) -> str:
    return (value or "").strip()[:limit]


def _build_messages(
    system_prompt: str,
    user_text: str,
    history: Iterable[dict] | None,
) -> list[ChatMessage]:
    messages = [ChatMessage(role="system", content=_clean(system_prompt, 6000))]
    if history:
        for item in list(history)[-AI_HISTORY_MESSAGES:]:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
                messages.append(ChatMessage(role=role, content=_clean(content, 6000)))
    messages.append(ChatMessage(role="user", content=_clean(user_text, AI_MAX_INPUT_CHARS)))
    return messages


def _extract_text(response: object) -> str | None:
    """Extract text from the current GigaChat 0.2.x completion response."""
    messages = getattr(response, "messages", None) or []
    if messages:
        message = messages[0]
        parts = getattr(message, "content", None) or []
        if isinstance(parts, str):
            return parts
        text_parts = []
        for part in parts:
            text = getattr(part, "text", None)
            if isinstance(text, str) and text:
                text_parts.append(text)
        if text_parts:
            return "".join(text_parts)

    # Compatibility fallback for older response objects.
    choices = getattr(response, "choices", None) or []
    if choices:
        content = getattr(getattr(choices[0], "message", None), "content", None)
        if isinstance(content, str):
            return content
    return None


async def ask_gigachat(
    system_prompt: str,
    user_text: str,
    *,
    history: Iterable[dict] | None = None,
    user_id: int | None = None,
) -> str | None:
    """Call GigaChat safely with bounded input, retries and concurrency control."""
    if not user_text or not user_text.strip():
        return None
    if user_id is not None and not await _rate_limiter.allow(user_id):
        logger.warning("AI rate limit reached for user_id=%s", user_id)
        return None

    request = ChatCompletionRequest(
        model=GIGACHAT_MODEL,
        messages=_build_messages(system_prompt, user_text, history),
    )

    async with _semaphore:
        for attempt in range(AI_MAX_RETRIES + 1):
            try:
                async with GigaChat(
                    base_url=GIGACHAT_BASE_URL,
                    credentials=GIGACHAT_CREDENTIALS,
                    scope=GIGACHAT_SCOPE,
                    verify_ssl_certs=GIGACHAT_VERIFY_SSL_CERTS,
                    ca_bundle_file=GIGACHAT_CA_BUNDLE_FILE or None,
                    model=GIGACHAT_MODEL,
                    timeout=AI_TIMEOUT,
                    max_retries=0,
                ) as giga:
                    response = await asyncio.wait_for(
                        giga.achat.create(request),
                        timeout=AI_TIMEOUT + 5,
                    )

                content = _extract_text(response)
                if not content:
                    logger.error("GigaChat returned an empty completion")
                    return None
                return _clean(content, AI_MAX_OUTPUT_CHARS)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if attempt >= AI_MAX_RETRIES:
                    logger.error(
                        "GigaChat request failed after %s attempts: %s: %s",
                        attempt + 1,
                        type(exc).__name__,
                        str(exc)[:500],
                    )
                    return None
                delay = AI_RETRY_BACKOFF * (2**attempt)
                logger.warning(
                    "GigaChat request failed (%s); retrying in %.1fs",
                    type(exc).__name__,
                    delay,
                )
                await asyncio.sleep(delay)
    return None
