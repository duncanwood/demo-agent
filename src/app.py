"""Entry point — wires the whole demo agent together (BUILD_PLAN B4/B0).

Intended flow once implemented:
  1. config.settings -> pick providers (cloud/local); validate_for_mode() fails
     fast with a friendly message on missing keys, before any service is built (B1)
  2. context.distiller -> distill product brief from CONTEXT_URL / target (B5)
  3. browser.controller -> launch headed Chromium, open DEMO_TARGET_URL, log in (B2)
  4. agent.tools -> register browser actions as LLM function tools (B4)
  5. voice.pipeline -> build the pipecat SmallWebRTC voice loop and run it (B1)
  6. on session end -> enrichment.report writes out/session-<ts>.json (B7)

B1 (steps 1 and 5) is implemented: this starts the pipecat dev server (SmallWebRTC
signaling + prebuilt client UI) and blocks until it's stopped. Steps 2-4/6 are still
stubs -- `run_voice_agent`'s `register_tools` hook is where B4 will attach browser
tools once B2-B4 land.
"""
from __future__ import annotations
import asyncio

# Re-exported so pipecat's dev runner can auto-discover it on this module: it
# looks for a module-level `bot` on `sys.modules["__main__"]`, which this file
# becomes when run as `python -m src.app` (see voice/pipeline.py docstring).
from src.voice.pipeline import bot  # noqa: F401


async def main() -> None:
    from src.config import settings, validate_for_mode
    from src.voice.pipeline import run_voice_agent

    validate_for_mode()

    print(f"demo-agent: starting voice loop (provider_mode={settings.provider_mode})", flush=True)
    await run_voice_agent()


if __name__ == "__main__":
    asyncio.run(main())
