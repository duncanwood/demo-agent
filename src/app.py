"""Entry point — wires the whole demo agent together.

Startup sequence:
  1. First-run gate: if cloud keys are missing, serve the local setup page
     (browser opens to it automatically), which writes .env and hot-reloads
     settings; "use local mode" is the zero-key escape hatch.
  2. Launch headed Chromium, open DEMO_TARGET_URL. Login ladder: saved auth
     state (.auth-state.json) -> .env credentials -> manual login in the
     window (detected automatically, then saved for next time) -> proceed
     without login.
  3. Distill the product brief — from CONTEXT_URL if configured, else from the
     logged-in app page itself (the standalone renderer would only see the
     sign-in page on gated apps).
  4. Run the pipecat SmallWebRTC voice loop; the client UI opens in the
     default browser as soon as the server is actually serving.
  5. On exit (Ctrl-C -> graceful, see voice/pipeline.py), stop the browser and
     write the lead report to out/session-<ts>.json if anything was said.

Everything from step 2 on is wrapped in a try/finally around the browser
controller so no Chromium is ever left orphaned and the report runs even when
the server exits via a signal. AUTO_OPEN=0 disables the self-opening tabs
(used by tests/boot checks).
"""
from __future__ import annotations

import asyncio
import os

# Pipecat's dev runner auto-discovers a module-level `bot` on
# `sys.modules["__main__"]` — which this file becomes when run as
# `python -m src.app` (see voice/pipeline.py docstring). This thin wrapper
# keeps that contract WITHOUT importing the heavy pipecat stack at module
# import time: on a cold venv those imports take 10-20s, which would delay
# the first-run setup page (served before any pipecat code is needed).
async def bot(runner_args):  # noqa: ANN001 — signature owned by pipecat's runner
    from src.voice.pipeline import bot as _bot
    return await _bot(runner_args)

_BASE_URL = "http://localhost:7860"


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


async def _open_browser_when_up(url: str, *, timeout_s: float = 60.0) -> None:
    """Open `url` in the default browser once it answers 200 (AUTO_OPEN=0 disables)."""
    if os.getenv("AUTO_OPEN", "1") == "0":
        return
    import webbrowser

    import httpx

    deadline = asyncio.get_event_loop().time() + timeout_s
    async with httpx.AsyncClient() as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                if (await client.get(url, timeout=2)).status_code == 200:
                    webbrowser.open(url)
                    return
            except Exception:
                pass
            await asyncio.sleep(0.5)


async def _ensure_logged_in(controller, settings) -> None:
    """Login ladder: restored session -> .env credentials -> manual login with
    auto-detection -> proceed without login (never blocks the demo forever)."""
    from src.browser.controller import ControllerError

    if await controller.is_logged_in():
        print("demo-agent: already logged in (saved session restored).", flush=True)
        return
    if settings.login_email and settings.login_password:
        try:
            await controller.login(settings.login_email, settings.login_password)
            print("demo-agent: logged in with .env credentials.", flush=True)
            return
        except ControllerError as e:
            print(f"demo-agent: credential login failed ({e}) — falling back to manual login.",
                  flush=True)
    if not await controller.wait_for_login():
        print("demo-agent: no login detected — proceeding with whatever is accessible.",
              flush=True)


async def _build_product_brief(controller, settings) -> str:
    """CONTEXT_URL (marketing page, unauthenticated render) if configured; else
    the text of the page the controller is actually on — post-login, so gated
    apps distill from the real product, not the sign-in screen."""
    from src.browser.controller import ControllerError
    from src.context.distiller import distill_product_context, summarize_page_text

    if settings.context_url:
        print(f"demo-agent: distilling product context from {settings.context_url} ...", flush=True)
        return await distill_product_context(settings.context_url)
    if settings.target_url:
        print("demo-agent: distilling product context from the live app page ...", flush=True)
        try:
            title, text = await controller.page_text()
        except ControllerError as e:
            print(f"demo-agent: could not read app page for context ({e})", flush=True)
            return ""
        return await summarize_page_text(title, "", text)
    return ""


async def main() -> None:
    from src.agent.prompts import build_system_prompt
    from src.agent.tools import register_browser_tools
    from src.browser.controller import BrowserController
    from src.config import settings, validate_for_mode
    from src.enrichment.report import write_report
    from src.setup.first_run import needs_setup, run_first_run_setup
    from src.voice.pipeline import run_voice_agent

    setup_ran = False
    if needs_setup():
        print(f"demo-agent: first-run setup — opening {_BASE_URL}/ (add your keys there).",
              flush=True)
        opener = asyncio.create_task(_open_browser_when_up(f"{_BASE_URL}/"))
        completed = await run_first_run_setup()
        opener.cancel()
        if not completed:
            print("demo-agent: setup not completed — exiting.", flush=True)
            return
        setup_ran = True

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
            await _ensure_logged_in(controller, settings)

        brief = await _build_product_brief(controller, settings)
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
        # After first-run setup, the setup page's own success screen already
        # redirects its tab to the client — don't open a duplicate.
        client_opener = None
        if not setup_ran:
            client_opener = asyncio.create_task(_open_browser_when_up(f"{_BASE_URL}/client/"))
        try:
            await run_voice_agent(register_tools=_register, system_prompt=system_prompt)
        finally:
            if client_opener is not None:
                client_opener.cancel()
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
