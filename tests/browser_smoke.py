"""Smoke test for BrowserController (BUILD_PLAN B2 + B3) against the local fixture.

Plain asyncio script (no pytest) — exercises the full controller contract end to end
against tests/fixture.html + tests/fixture2.html and prints a sample read_page()
snapshot, which documents the exact wire format for B4 (agent <-> browser tool wiring).

Run: cd demo-agent && .venv/bin/python tests/browser_smoke.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser.controller import BrowserController, ControllerError  # noqa: E402

FIXTURE = (Path(__file__).parent / "fixture.html").resolve().as_uri()


def find_ref(snapshot: dict, name_contains: str) -> str:
    for el in snapshot["elements"]:
        if name_contains.lower() in el["name"].lower():
            return el["ref"]
    raise AssertionError(f"no element with name containing {name_contains!r} in {snapshot['elements']}")


async def main() -> None:
    controller = BrowserController(headless=True)
    await controller.start()

    # 1. navigate + read_page shape --------------------------------------
    snap = await controller.navigate(FIXTURE)
    print("=== sample read_page() snapshot (tests/fixture.html) ===")
    print(json.dumps(snap, indent=2))
    assert len(snap["elements"]) >= 6, f"expected >=6 elements, got {len(snap['elements'])}"
    for el in snap["elements"]:
        assert set(el) == {"ref", "role", "name"}, el
        assert el["ref"].startswith("e"), el
    print(f"\nOK: {len(snap['elements'])} elements, refs/names well-formed")

    # 2. click the DOM-mutating button -----------------------------------
    mutate_ref = find_ref(snap, "Refresh Metrics")
    snap = await controller.click(mutate_ref)
    assert snap["title"] == "Refreshed - Metric Dashboard", snap["title"]
    print("OK: click mutated DOM -> title is now", repr(snap["title"]))

    # 3. type into the text input; select() on the range dropdown ------------
    search_ref = find_ref(snap, "Search metrics")
    snap = await controller.type(search_ref, "revenue")
    print("OK: typed 'revenue' into the search input")
    range_ref = next(el["ref"] for el in snap["elements"] if el["role"] == "combobox")
    snap = await controller.select(range_ref, "Last 30 days")
    assert any(el["role"] == "combobox" and el["name"] == "Last 30 days"
               for el in snap["elements"]), snap["elements"]
    print("OK: select() chose 'Last 30 days' by label (snapshot name updated)")

    # 4. login -------------------------------------------------------------
    snap = await controller.login("demo@x.com", "pw")
    assert "logged in" in snap["h1"].lower(), snap["h1"]
    print("OK: login() -> h1 is now", repr(snap["h1"]))

    # 5. navigate by clicking the nav link + stale-ref check ----------------
    nav_ref = find_ref(snap, "Go to Fixture 2")
    old_refs = [el["ref"] for el in snap["elements"]]
    snap2 = await controller.click(nav_ref)
    assert "fixture2.html" in snap2["url"], snap2["url"]
    print("OK: navigated via nav-link click ->", snap2["url"])

    current = {el["ref"] for el in snap2["elements"]}
    stale_ref = next(r for r in old_refs if r not in current)
    try:
        await controller.click(stale_ref)
        raise AssertionError("expected ControllerError for a stale ref")
    except ControllerError as e:
        print(f"OK: stale ref {stale_ref!r} correctly rejected -> {e}")

    # 6. scroll --------------------------------------------------------------
    await controller.scroll("down")
    await controller.scroll("up")
    print("OK: scroll('down') / scroll('up') completed without error")

    # 7. cursor overlay survives navigation -----------------------------------
    has_cursor = await controller._page.evaluate("() => !!window.__demoCursor")
    assert has_cursor, "cursor overlay missing after navigation"
    print("OK: window.__demoCursor present after navigation (init-script survival)")

    await controller.stop()
    print("\nSMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
