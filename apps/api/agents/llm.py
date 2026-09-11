"""Thin LLM client with JSON-mode structured output.

Uses OpenAI or Anthropic when a key is present. Returns None on any
failure so callers can fall back to the deterministic reasoning engine —
the demo must never break because of a missing key or a flaky API.
"""
from __future__ import annotations

import contextvars
import json
import os
from typing import Any, Optional

import httpx

TIMEOUT = 25.0

# Whether any LLM call succeeded in the current pipeline run. Each run is its
# own asyncio task, so a ContextVar keeps concurrent runs separate.
_succeeded: contextvars.ContextVar[bool] = contextvars.ContextVar("llm_succeeded", default=False)


def engine() -> str:
    """The configured provider (a key is present), not necessarily one that answered."""
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "deterministic"


def begin_run() -> None:
    _succeeded.set(False)


def mark_success() -> None:
    _succeeded.set(True)


def engine_used() -> str:
    """Engine label for the report: only claim an LLM if one actually answered."""
    configured = engine()
    if configured == "deterministic" or _succeeded.get():
        return configured
    return f"deterministic ({configured} unavailable)"


async def complete_json(system: str, user: str) -> Optional[dict[str, Any]]:
    """Ask the LLM for a JSON object. Returns None if unavailable/failed."""
    which = engine()
    try:
        if which == "openai":
            result = await _openai(system, user)
        elif which == "anthropic":
            result = await _anthropic(system, user)
        else:
            return None
    except Exception:
        return None
    if isinstance(result, dict):
        mark_success()
        return result
    return None


async def _openai(system: str, user: str) -> Optional[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={
                "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                "temperature": 0.4,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        return json.loads(resp.json()["choices"][0]["message"]["content"])


async def _anthropic(system: str, user: str) -> Optional[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5"),
                "max_tokens": 2048,
                "system": system + "\nRespond ONLY with a valid JSON object.",
                "messages": [{"role": "user", "content": user}],
            },
        )
        resp.raise_for_status()
        text = next(b["text"] for b in resp.json()["content"] if b.get("type") == "text")
        start, end = text.find("{"), text.rfind("}")
        return json.loads(text[start : end + 1])
