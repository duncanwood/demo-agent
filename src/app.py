"""Entry point — wires the whole demo agent together.

Startup sequence:
  1. config.settings -> pick providers (cloud/local); validate_for_mode() fails
     fast with a friendly message on missing keys, before any service is built (B1)
  2. browser.controller -> launch headed Chromium, open DEMO_TARGET_URL, and log
     in best-effort if credentials are configured (B2/B3)
  3. context.distiller -> render CONTEXT_URL (or the target itself) headlessly and
     distill a product brief for the system prompt (B5)
  4. agent.tools -> register the browser actions as LLM function tools (B4)
  5. voice.pipeline -> run the pipecat SmallWebRTC voice loop until stopped (B1)
  6. on session end -> stop the browser, then write the lead report from the
     conversation to out/session-<ts>.json if anything was said (B7)

Everything from step 2 on is wrapped in a try/finally around the browser
controller so it is always stopped — no Chromium is ever left orphaned — and the
enrichment sink runs even when the server exits via a signal.
"""
from __future__ import annotations

import asyncio

# Re-exported so pipecat's dev runner can auto-discover it on this module: it
# looks for a module-level `bot` on `sys.modules["__main__"]`, which this file
# becomes when run as `python -m src.app` (see voice/pipeline.py docstring).
from src.voice.pipeline import bot  # noqa: F401


def _extract_transcript(context) -> list[dict]:
    """Pull the spoken conversation out of a session's LLMContext: user/assistant
    turns with plain-string content only (system prompt, tool calls with content
    None, and tool-result messages are all filtered out)."""
    turns = []
    for m in context.get_messages():
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) \
                and m["content"].strip():
            turns.append({"role": m["role"], "content": m["content"]})
    return turns


async def main() -> None:
    from src.agent.prompts import build_system_prompt
    from src.agent.tools import register_browser_tools
    from src.browser.controller import BrowserController, ControllerError
    from src.config import settings, validate_for_mode
    from src.context.distiller import distill_product_context
    from src.enrichment.report import write_report
    from src.voice.pipeline import run_voice_agent

    validate_for_mode()

    # Holds the live connection's LLMContext so the enrichment sink can read the
    # conversation after the server stops (one demo session type per process —
    # same assumption as voice/pipeline.py's module state).
    session_contexts: list = []

    controller = BrowserController(headless=False, storage_state=settings.storage_state or None)
    try:
        await controller.start()

        if settings.target_url:
            await controller.navigate(settings.target_url)

        if settings.login_email and settings.login_password:
            try:
                await controller.login(settings.login_email, settings.login_password)
            except ControllerError as e:
                print(f"demo-agent: login skipped ({e})", flush=True)

        brief = ""
        context_source = settings.context_url or settings.target_url
        if context_source:
            print(f"demo-agent: distilling product context from {context_source} ...", flush=True)
            brief = await distill_product_context(context_source)
            print(
                f"demo-agent: product brief ready ({len(brief)} chars)"
                if brief else "demo-agent: no product brief — continuing without",
                flush=True,
            )

        system_prompt = build_system_prompt(product_brief=brief, target_url=settings.target_url)

        def _register(llm, ctx) -> None:
            session_contexts.append(ctx)
            register_browser_tools(llm, ctx, controller)

        print(f"demo-agent: starting voice loop (provider_mode={settings.provider_mode})", flush=True)
        await run_voice_agent(register_tools=_register, system_prompt=system_prompt)
    finally:
        await controller.stop()
        transcript = _extract_transcript(session_contexts[-1]) if session_contexts else []
        if transcript:
            try:
                path = await write_report(transcript)
                print(f"demo-agent: lead report written -> {path}", flush=True)
            except Exception as e:  # a failed report must not mask the real exit reason
                print(f"demo-agent: enrichment failed ({e})", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
