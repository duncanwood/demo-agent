"""Smoke test for the B5 product-context distiller (BUILD_PLAN B5, revision R1).

Plain asyncio script (no pytest, no real LLM/API calls) — injects a stub `complete`
and exercises distill_product_context() against the local fixture (happy path: real
Playwright render + extraction feeding the stub) and an unreachable URL (failure
path: bounded by timeouts, returns "", never touches the LLM).

Run: cd demo-agent && .venv/bin/python tests/distiller_smoke.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.context.distiller import distill_product_context  # noqa: E402

FIXTURE = (Path(__file__).parent / "fixture.html").resolve().as_uri()
UNREACHABLE = "http://localhost:1/none"


async def main() -> None:
    calls: list[dict] = []

    async def stub_complete(system: str, user: str, *, max_tokens: int = 1200) -> str:
        calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        return "CANNED BRIEF"

    # 1. happy path — real render + extraction against the local fixture, stubbed LLM
    brief = await distill_product_context(FIXTURE, complete=stub_complete)
    assert brief == "CANNED BRIEF", repr(brief)
    assert len(calls) == 1, calls
    user_arg = calls[0]["user"]
    assert "Metric Dashboard" in user_arg, user_arg
    print(f"OK: happy path -> brief={brief!r}")
    print(f"OK: stub received system={len(calls[0]['system'])} chars, user={len(user_arg)} chars")
    print(f"OK: 'Metric Dashboard' found in extracted user content (real render confirmed)")
    print("--- sample of extracted user content (first 300 chars) ---")
    print(user_arg[:300])

    # 2. failure path — unreachable URL must be swallowed and bounded by timeouts
    calls.clear()
    start = time.monotonic()
    brief = await distill_product_context(UNREACHABLE, complete=stub_complete)
    elapsed = time.monotonic() - start
    assert brief == "", repr(brief)
    assert calls == [], calls
    assert elapsed < 20, f"took {elapsed:.1f}s, expected well under 20s (timeouts should bound it)"
    print(f"OK: failure path -> returned '' in {elapsed:.1f}s, LLM never called")

    print("\nDISTILLER SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
