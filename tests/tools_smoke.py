"""Smoke test for the B4 browser-tools join (BUILD_PLAN B4) against the local fixture.

Plain asyncio script (no pytest), mirroring tests/browser_smoke.py: exercises
build_actions() directly (bypassing pipecat entirely), then wires
register_browser_tools() against a real pipecat LLMContext + OpenAILLMService to
confirm the pipecat adapter layer holds together -- all without real API keys.

Run: cd demo-agent && .venv/bin/python tests/tools_smoke.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURE = (Path(__file__).parent / "fixture.html").resolve().as_uri()

# Dummy keys so make_llm() never fails on a missing key (constructors are lazy --
# no real network/auth happens just building the service object). DEMO_TARGET_URL
# must be set before src.config is first imported by anything below (settings is a
# module-level singleton read once at import time) so navigate()'s guardrail has a
# real file:// target to compare origins against.
os.environ.setdefault("DEMO_TARGET_URL", FIXTURE)
os.environ.setdefault("DEEPGRAM_API_KEY", "x")
os.environ.setdefault("OPENAI_API_KEY", "x")
os.environ.setdefault("CARTESIA_API_KEY", "x")

from pipecat.processors.aggregators.llm_context import LLMContext  # noqa: E402

from src.agent.tools import build_actions, register_browser_tools  # noqa: E402
from src.browser.controller import BrowserController  # noqa: E402
from src.config import make_llm  # noqa: E402


def find_ref(snapshot: dict, name_contains: str) -> str:
    for el in snapshot["elements"]:
        if name_contains.lower() in el["name"].lower():
            return el["ref"]
    raise AssertionError(f"no element with name containing {name_contains!r} in {snapshot['elements']}")


async def main() -> None:
    controller = BrowserController(headless=True)
    await controller.start()
    actions = build_actions(controller)

    # 1. navigate + read_page shape -------------------------------------------
    snap = await actions["navigate"]({"url": FIXTURE})
    assert "error" not in snap, snap
    assert len(snap["elements"]) >= 6, f"expected >=6 elements, got {len(snap['elements'])}"
    print(f"OK: navigate -> {snap['url']}, {len(snap['elements'])} elements")

    snap2 = await actions["read_page"]({})
    assert snap2["elements"] == snap["elements"], "read_page should match the current page"
    print("OK: read_page -> matches current snapshot")

    # 2. click the DOM-mutating button ----------------------------------------
    mutate_ref = find_ref(snap, "Refresh Metrics")
    snap = await actions["click"]({"ref": mutate_ref})
    assert snap["title"] == "Refreshed - Metric Dashboard", snap["title"]
    print("OK: click -> title is now", repr(snap["title"]))

    # 3. type_text into the search input; select_option on the range dropdown --
    search_ref = find_ref(snap, "Search metrics")
    result = await actions["type_text"]({"ref": search_ref, "text": "revenue"})
    assert "error" not in result, result
    print("OK: type_text -> typed 'revenue' into the search input")

    range_ref = next(el["ref"] for el in result["elements"] if el["role"] == "combobox")
    snap = await actions["select_option"]({"ref": range_ref, "option": "Last 30 days"})
    assert any(
        el["role"] == "combobox" and el["name"] == "Last 30 days" for el in snap["elements"]
    ), snap["elements"]
    print("OK: select_option -> 'Last 30 days' selected (snapshot name updated)")

    # 4. click on a stale/bogus ref -> ControllerError surfaces as {"error": ...}
    result = await actions["click"]({"ref": "e999"})
    assert result == {"error": "no element e999 in current snapshot"}, result
    print("OK: click(e999) ->", result)

    # 5. navigate guardrail: file:// target, cross-origin absolute URL refused --
    result = await actions["navigate"]({"url": "https://evil.example.com"})
    assert "error" in result, result
    print("OK: navigate(https://evil.example.com) refused ->", result)

    # relative navigation within the same (file://) origin should still work
    snap = await actions["navigate"]({"url": "fixture2.html"})
    assert "error" not in snap, snap
    assert "fixture2.html" in snap["url"], snap["url"]
    print("OK: navigate('fixture2.html') resolved + allowed ->", snap["url"])

    await controller.stop()
    print("SMOKE (pure actions) OK")

    # 6. pipecat adapter layer: schemas attach + functions register, no real keys
    llm = make_llm()
    context = LLMContext(messages=[{"role": "system", "content": "test"}])
    register_browser_tools(llm, context, BrowserController(headless=True))

    expected = {"read_page", "click", "type_text", "select_option", "scroll", "navigate"}
    attached = {schema.name for schema in context.tools.standard_tools}
    assert attached == expected, attached
    for name in expected:
        assert llm.has_function(name), f"llm missing registered function {name!r}"
    print(f"OK: register_browser_tools -> {sorted(expected)} attached to context + registered on llm")

    print("\nTOOLS SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
