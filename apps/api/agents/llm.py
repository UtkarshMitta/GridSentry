"""Thin LLM client with JSON-mode structured output.

Uses OpenAI or Anthropic when a key is present. Returns None on any
failure so callers can fall back to the deterministic reasoning engine —
the demo must never break because of a missing key or a flaky API.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx

TIMEOUT = 25.0


def engine() -> str:
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "deterministic"


async def complete_json(system: str, user: str) -> Optional[dict[str, Any]]:
    """Ask the LLM for a JSON object. Returns None if unavailable/failed."""
    which = engine()
    try:
        if which == "openai":
            return await _openai(system, user)
        if which == "anthropic":
            return await _anthropic(system, user)
    except Exception:
        return None
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
                "model": os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
                "max_tokens": 2048,
                "system": system + "\nRespond ONLY with a valid JSON object.",
                "messages": [{"role": "user", "content": user}],
            },
        )
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"]
        start, end = text.find("{"), text.rfind("}")
        return json.loads(text[start : end + 1])
