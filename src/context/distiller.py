"""Product-context distiller (BUILD_PLAN B5).

The "learns about the company as the demo starts" behavior. At startup, fetch a
configured URL (CONTEXT_URL and/or the target app's own visible content), summarize
it with the LLM into a compact product brief, and return it for injection into the
agent's system prompt.

Contract:
    brief = await distill_product_context(url) -> str   # a few hundred words, injected

v1 = single page (httpx fetch -> strip -> LLM summarize). Shallow crawl is T3 stretch.
"""
from __future__ import annotations


async def distill_product_context(url: str) -> str:
    raise NotImplementedError("B5: fetch url, summarize into a product brief for the prompt.")
