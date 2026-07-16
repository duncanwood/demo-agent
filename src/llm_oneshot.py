"""One-shot LLM completion helper (shared by B5 distiller + B7 enrichment).

The realtime pipeline speaks through pipecat services; for plain prompt->text
jobs (context distillation at startup, the post-demo report) we call the same
configured provider directly via the OpenAI client — already installed as a
pipecat[openai] dependency. PROVIDER_MODE switches between api.openai.com and
Ollama's OpenAI-compatible endpoint, so both modes work with no extra config.
"""
from __future__ import annotations

import os

from openai import AsyncOpenAI

from src.config import settings


def _client() -> AsyncOpenAI:
    if settings.provider_mode == "local":
        return AsyncOpenAI(base_url=settings.ollama_base_url, api_key="ollama")
    return AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])


def _model() -> str:
    return settings.ollama_model if settings.provider_mode == "local" else settings.openai_model


async def complete(system: str, user: str, *, max_tokens: int = 1200) -> str:
    """One prompt -> one text response on the configured provider."""
    resp = await _client().chat.completions.create(
        model=_model(),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()
