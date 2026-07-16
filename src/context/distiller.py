"""Product-context distiller (BUILD_PLAN B5, revision R1).

The "learns about the company as the demo starts" behavior. At startup, render a
configured URL headlessly with its own short-lived Playwright Chromium (SPAs need
real rendering — a raw httpx fetch was dropped per R1), extract the visible text,
and summarize it with the LLM into a compact product brief for injection into
`src.agent.prompts.build_system_prompt`.

Contract:
    brief = await distill_product_context(url) -> str   # a few hundred words, injected

`complete` is dependency-injected (defaults to `src.llm_oneshot.complete`) so tests
can stub the LLM call instead of monkeypatching it. FAILURE POLICY: any failure at
any stage (browser launch, navigation timeout, LLM error) is caught, logged as a
single warning line, and turned into "" — the demo must always start, and
prompts.py already falls back to a generic framing when the brief is empty. This
function never raises.
"""
from __future__ import annotations

import re

from playwright.async_api import Error as PlaywrightError, async_playwright

from src.llm_oneshot import complete as _default_complete

_NAV_TIMEOUT_MS = 15000
_SETTLE_TIMEOUT_MS = 3000
_MAX_CHARS = 8000  # cap page text fed to the LLM; the first ~8k chars carry the signal

_SYSTEM_PROMPT = (
    "You prep a sales engineer for a live product demo. From the page text, write a "
    "compact product brief: what the product is, who it's for, the key features and "
    "value propositions, and any pricing/plan signals. Plain prose, no markdown, under "
    "250 words. If the text is thin, say what IS known without inventing anything. "
    "IMPORTANT: the page <title> is often platform boilerplate (e.g. 'X Generated "
    "App', a site-builder's name) — identify the product's ACTUAL name from the page "
    "content itself (brand in the navigation, headings, or hero text) and use that "
    "name throughout the brief."
)


async def distill_product_context(url: str, *, complete=None) -> str:
    """Render `url`, extract its visible text, and summarize it into a product brief."""
    try:
        title, description, text = await _render(url)
    except Exception as e:  # deliberately broad — any failure here must not block demo startup
        print(f"distiller: could not build product brief for {url!r}: {e}")
        return ""
    return await summarize_page_text(title, description, text, complete=complete)


async def summarize_page_text(title: str, description: str, text: str, *, complete=None) -> str:
    """Summarize already-extracted page text into a product brief.

    Used directly by app startup with the LOGGED-IN app page's text (the
    standalone `_render` above can only see what an unauthenticated visitor
    sees — for gated apps that's just the sign-in page)."""
    complete = complete or _default_complete
    if len((text or "").strip()) < 150:
        # Don't ask the LLM to summarize a skeleton — it narrates its own
        # confusion ("the page content is insufficient...") straight into the
        # agent's product context. An empty brief has a safe fallback; use it.
        print(f"distiller: page text too thin to summarize ({len((text or '').strip())} chars)")
        return ""
    try:
        user = f"Page title: {title}\nMeta description: {description}\nPage text:\n{text}"
        return await complete(_SYSTEM_PROMPT, user, max_tokens=400)
    except Exception as e:  # same failure policy: an LLM error must not block startup
        print(f"distiller: could not build product brief: {e}")
        return ""


async def _render(url: str) -> tuple[str, str, str]:
    """Launch a standalone headless Chromium and pull title / meta-description / body text.

    Deliberately independent of BrowserController (B2) — this runs before, and
    outside of, the demo browser session.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
            try:
                await page.wait_for_load_state("networkidle", timeout=_SETTLE_TIMEOUT_MS)
            except PlaywrightError:
                pass  # SPAs may never go fully idle — a short settle is best-effort
            title = (await page.title()).strip()
            description = await page.evaluate(
                "() => document.querySelector('meta[name=description]')?.content || ''"
            )
            text = await page.evaluate("() => document.body.innerText")
            return title, description.strip(), _normalize(text)
        finally:
            await browser.close()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:_MAX_CHARS]
