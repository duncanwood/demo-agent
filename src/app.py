"""Entry point — wires the whole demo agent together (BUILD_PLAN B4/B0).

Intended flow once implemented:
  1. config.settings -> pick providers (cloud/local)
  2. context.distiller -> distill product brief from CONTEXT_URL / target (B5)
  3. browser.controller -> launch headed Chromium, open DEMO_TARGET_URL, log in (B2)
  4. agent.tools -> register browser actions as LLM function tools (B4)
  5. voice.pipeline -> build the pipecat SmallWebRTC voice loop and run it (B1)
  6. on session end -> enrichment.report writes out/session-<ts>.json (B7)

Currently a stub: `make run` prints where to start.
"""
from __future__ import annotations
import asyncio


async def main() -> None:
    from src.config import settings
    print("demo-agent: not implemented yet.")
    print(f"  provider_mode = {settings.provider_mode}")
    print(f"  target_url    = {settings.target_url or '(unset — edit .env)'}")
    print("  Start with docs/BUILD_PLAN.md → B1 (voice loop) and B2 (browser).")


if __name__ == "__main__":
    asyncio.run(main())
