"""Playwright browser controller (BUILD_PLAN B2 + B3).

Drives a local headed Chromium and exposes a small, LLM-friendly action surface.
Control is DOM/accessibility-based (element refs), NOT vision. A synthetic cursor
(cursor.js) animates to each element before acting (B3).

Contract:
    await controller.start()                     # launch Chromium, inject cursor.js
    await controller.navigate(url)
    snapshot = await controller.read_page()      # -> [{ref, role, name, value?}]  (small!)
    await controller.move_cursor_to(ref)         # animate the fake pointer (B3)
    await controller.click(ref)
    await controller.type(ref, text)
    await controller.scroll(direction)
    await controller.login(email, password)      # target app is gated (B2 note)

Notes:
- read_page() must return a COMPACT list of interactive elements with stable refs
  (map ref -> Playwright locator internally); do not dump raw HTML into the LLM.
- Re-inject cursor.js on every 'load'/'framenavigated' so the pointer survives navigation.
- Prefer accessibility snapshot / get_by_role for robust refs.
"""
from __future__ import annotations
from pathlib import Path

CURSOR_JS = (Path(__file__).parent / "cursor.js").read_text()


class BrowserController:
    def __init__(self, *, headless: bool = False, storage_state: str | None = None) -> None:
        self.headless = headless
        self.storage_state = storage_state
        # TODO(B2): hold Playwright, browser, context, page; ref->locator map.

    async def start(self) -> None:
        raise NotImplementedError("B2: launch Chromium (headed), new context, inject CURSOR_JS.")

    async def read_page(self) -> list[dict]:
        raise NotImplementedError("B2: return compact interactive-element list with refs.")

    async def move_cursor_to(self, ref: str) -> None:
        raise NotImplementedError("B3: animate the synthetic cursor to the element center.")

    # navigate / click / type / scroll / login — TODO(B2)
