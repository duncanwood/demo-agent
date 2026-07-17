"""Smoke test for the guided-UX status panel (splash + sidebar/pill), style-matched to
tests/browser_smoke.py. Exercises show_splash()'s own inline window.__demoPanel, the
panel() dispatch, activity-feed wiring on click(), collapse, and host click-isolation —
all against the local fixture, headless.

Run: cd demo-agent && .venv/bin/python tests/panel_smoke.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser.controller import BrowserController  # noqa: E402

FIXTURE = (Path(__file__).parent / "fixture.html").resolve().as_uri()

_HOST_SEL = "document.getElementById('__demo-panel-host')"


def find_ref(snapshot: dict, name_contains: str) -> str:
    for el in snapshot["elements"]:
        if name_contains.lower() in el["name"].lower():
            return el["ref"]
    raise AssertionError(f"no element with name containing {name_contains!r} in {snapshot['elements']}")


async def main() -> None:
    controller = BrowserController(headless=True)
    await controller.start()

    # 1. splash: its own inline window.__demoPanel; phase() runs clean ---------
    await controller.show_splash()
    has_panel = await controller._page.evaluate("() => !!window.__demoPanel")
    assert has_panel, "expected window.__demoPanel on the splash document"
    await controller.panel("phase", "Opening the app", "working")  # must not raise
    print("OK: show_splash() -> window.__demoPanel present, phase() ran clean")

    # 2. real navigation: panel.js's sidebar installs fresh on the new document -
    snap = await controller.navigate(FIXTURE)
    has_panel = await controller._page.evaluate("() => !!window.__demoPanel")
    assert has_panel, "expected window.__demoPanel to survive navigation (init-script)"
    await controller.panel("phase", "Live — say hello", "live")  # must not raise
    print("OK: navigate() -> panel.js sidebar installed on the new document")

    # 3. activity feed: click() pushes a human-readable act() line before acting -
    mutate_ref = find_ref(snap, "Refresh Metrics")
    await controller.click(mutate_ref)
    act_count = await controller._page.evaluate(
        f"() => {_HOST_SEL}.shadowRoot.getElementById('activity').children.length"
    )
    assert act_count >= 1, f"expected >=1 activity-feed entries, got {act_count}"
    first_line = await controller._page.evaluate(
        f"() => {_HOST_SEL}.shadowRoot.getElementById('activity').children[0].textContent"
    )
    assert "Clicking" in first_line, first_line
    print(f"OK: click() -> {act_count} activity entries, newest: {first_line!r}")

    # 4. collapse API callable, toggles sidebar <-> pill ------------------------
    await controller._page.evaluate("() => window.__demoPanel.collapse(true)")
    sidebar_hidden = await controller._page.evaluate(
        f"() => {_HOST_SEL}.shadowRoot.getElementById('sidebar').hidden"
    )
    pill_hidden = await controller._page.evaluate(
        f"() => {_HOST_SEL}.shadowRoot.getElementById('pill').hidden"
    )
    assert sidebar_hidden is True and pill_hidden is False, (sidebar_hidden, pill_hidden)
    await controller._page.evaluate("() => window.__demoPanel.collapse(false)")
    sidebar_hidden = await controller._page.evaluate(
        f"() => {_HOST_SEL}.shadowRoot.getElementById('sidebar').hidden"
    )
    assert sidebar_hidden is False, "expected sidebar visible again after collapse(false)"
    print("OK: collapse(true)/collapse(false) toggle sidebar <-> pill")

    # 4b. lane reservation: expanded sidebar reserves html margin; pill frees it -
    margin = await controller._page.evaluate("() => document.documentElement.style.marginRight")
    assert margin == "280px", f"expected reserved 280px lane while expanded, got {margin!r}"
    await controller._page.evaluate("() => window.__demoPanel.collapse(true)")
    margin = await controller._page.evaluate("() => document.documentElement.style.marginRight")
    assert margin in ("", None), f"expected no reserved lane while collapsed, got {margin!r}"
    await controller._page.evaluate("() => window.__demoPanel.collapse(false)")
    print("OK: sidebar reserves its 280px lane on <html>; pill releases it")

    # 5. the host must not intercept clicks in the page's content lane ----------
    # (no_viewport=True -> viewport_size is None; measure the real window, and
    # test the center of the CONTENT area left of the reserved 280px lane.)
    size = await controller._page.evaluate("() => [window.innerWidth, window.innerHeight]")
    cx, cy = (size[0] - 280) // 2, size[1] // 2
    center_is_host = await controller._page.evaluate(
        "([x, y]) => { const el = document.elementFromPoint(x, y); "
        "return !!el && el.id === '__demo-panel-host'; }",
        [cx, cy],
    )
    assert center_is_host is False, "panel host must not cover the viewport center"
    print("OK: panel host does not cover the page center (elementFromPoint check)")

    # 6. control buttons -> command queue (drained in order, exactly once) ------
    await controller._page.evaluate(
        f"() => {{ {_HOST_SEL}.shadowRoot.getElementById('muteBtn').click(); "
        f"{_HOST_SEL}.shadowRoot.getElementById('endBtn').click(); }}"
    )
    cmds = await controller.poll_panel_commands()
    assert cmds == ["mute-toggle", "end"], f"expected queued commands, got {cmds!r}"
    assert await controller.poll_panel_commands() == [], "queue must clear after drain"
    print("OK: sidebar buttons -> poll_panel_commands() drains ['mute-toggle', 'end'] once")

    # 7. transcript + mic-device APIs render ------------------------------------
    await controller.panel("turn", "hi there, what does this app do?", "user")
    await controller.panel("turn", "This is the dashboard.", "assistant")
    t_count = await controller._page.evaluate(
        f"() => {_HOST_SEL}.shadowRoot.getElementById('transcript').children.length"
    )
    assert t_count == 2, f"expected 2 transcript rows, got {t_count}"
    await controller.panel("micDevices", '[{"id":"a","label":"Mic A"},{"id":"b","label":"Mic B"}]')
    opts = await controller._page.evaluate(
        f"() => Array.from({_HOST_SEL}.shadowRoot.getElementById('micSel').options)"
        ".map(o => o.textContent)"
    )
    assert opts == ["Mic A", "Mic B"], opts
    print("OK: transcript rows render; mic-device list populates the picker")

    await controller.stop()
    print("\nPANEL SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
