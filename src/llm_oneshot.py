"""One-shot LLM completion helper (context distiller + lead report).

The realtime pipeline speaks through pipecat services; for plain prompt->text
jobs (context distillation at startup, the post-demo report) we call the same
configured provider directly via the OpenAI client — already installed as a
pipecat[openai] dependency.
"""
from __future__ import annotations

import os

from openai import AsyncOpenAI

from src.config import settings


async def complete(system: str, user: str, *, max_tokens: int = 1200) -> str:
    """One prompt -> one text response on the configured provider."""
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()
