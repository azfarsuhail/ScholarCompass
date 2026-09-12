"""Shared Groq client.

Groq is OpenAI-compatible and fast enough that the semantic pass can run while
the student is still reading the deterministic results. Two things this module
guarantees for every caller:

  * A missing API key degrades to None rather than raising. Every AI feature
    here is an enrichment on top of a deterministic result the student already
    has, so losing the LLM must never lose the page.
  * `json_object` responses are parsed defensively. Models occasionally wrap
    JSON in prose or fences even in JSON mode.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from groq import AsyncGroq, GroqError

from .config import settings

log = logging.getLogger(__name__)

_client: AsyncGroq | None = None


def client() -> AsyncGroq | None:
    global _client
    key = settings().groq_api_key
    if not key:
        return None
    if _client is None:
        _client = AsyncGroq(api_key=key, max_retries=2)
    return _client


def _loads(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Strip ```json fences / leading prose, then take the outermost object.
        m = re.search(r"\{.*\}|\[.*\]", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


async def complete_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
) -> Any | None:
    """Ask for a JSON object. Returns None if the LLM is unavailable."""
    c = client()
    if c is None:
        log.info("groq key not configured; skipping enrichment")
        return None
    try:
        resp = await c.chat.completions.create(
            model=model or settings().match_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return _loads(resp.choices[0].message.content or "")
    except (GroqError, json.JSONDecodeError, IndexError) as e:
        log.warning("groq call failed: %s", e)
        return None
