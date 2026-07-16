"""Smoke test for BrowserController manual-login detection (is_logged_in / wait_for_login
/ page_text), style-matched to tests/browser_smoke.py. Exercises the credentials-absent
path: the browser opens, a human logs in out-of-band (NOT via controller.login() -- the
point is DETECTING a login the controller didn't itself perform), the controller notices
via polling and saves storage_state -- plus the already-logged-in short-circuit,
page_text() extraction, and the timeout-without-raising path.

Run: cd demo-agent && .venv/bin/python tests/login_wait_smoke.py
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.browser.controller import BrowserController  # noqa: E402

FIXTURE = (Path(__file__).parent / "fixture.html").resolve().as_uri()
FIXTURE2 = (Path(__file__).parent / "fixture2.html").resolve().as_uri()

# Fills + submits the fixture login form directly on the page -- bypassing
# controller.login() entirely, to simulate a human acting out-of-band.
_HUMAN_LOGIN_JS = """() => {
  document.getElementById('email').value = 'human@x.com';
  document.getElementById('password').value = 'hunter2';
  document.querySelector('#login-form button[type=submit]').click();
}"""


async def _simulate_human_login_after(controller: BrowserController, delay_s: float) -> None:
    await asyncio.sleep(delay_s)
    await controller._page.evaluate(_HUMAN_LOGIN_JS)


async def main() -> None:
    auth_path = Path(tempfile.mkdtemp(prefix="login-wait-smoke-")) / "auth.json"
    controller = BrowserController(headless=True, storage_state=str(auth_path))
    await controller.start()

    # 1-2. fresh fixture page -> password field visible -> not logged in ------
    await controller.navigate(FIXTURE)
    assert await controller.is_logged_in() is False, "expected password field to be visible"
    print("OK: is_logged_in() -> False on fresh fixture page (password field visible)")

    # 3-4. poll while a human logs in out-of-band; detect + save auth state ---
    wait_task = asyncio.create_task(controller.wait_for_login(timeout_s=15, poll_s=0.4))
    sim_task = asyncio.create_task(_simulate_human_login_after(controller, 1.2))
    detected = await wait_task
    await sim_task
    assert detected is True, "expected wait_for_login() to detect the out-of-band login"
    assert auth_path.exists(), f"expected auth state file at {auth_path}"
    saved = json.loads(auth_path.read_text())
    assert saved, "expected non-empty auth state JSON"
    print(f"OK: wait_for_login() detected external login, saved non-empty {auth_path.name}")

    # 5. already-logged-in short-circuit on a password-free page ---------------
    await controller.navigate(FIXTURE2)
    assert await controller.is_logged_in() is True, "expected no password field on fixture2"
    buf = io.StringIO()
    t0 = time.monotonic()
    with contextlib.redirect_stdout(buf):
        already = await controller.wait_for_login(timeout_s=5)
    elapsed = time.monotonic() - t0
    assert already is True
    assert "no login configured" not in buf.getvalue(), "should not print the waiting line"
    assert elapsed < 2, f"already-logged-in path should return fast, took {elapsed:.2f}s"
    print(f"OK: wait_for_login() short-circuited already-logged-in in {elapsed:.2f}s, no waiting line printed")

    # 6. page_text() on the current (fixture2) page -----------------------------
    title, text = await controller.page_text()
    assert title == "Fixture Page 2", title
    assert "Fixture 2" in text, text
    print(f"OK: page_text() -> title={title!r}, text contains heading")

    # 7. timeout path: fresh load of fixture.html (per-page-load hide resets) ---
    await controller.navigate(FIXTURE)
    assert await controller.is_logged_in() is False, "expected password field visible again after reload"
    t0 = time.monotonic()
    timed_out = await controller.wait_for_login(timeout_s=2, poll_s=0.4)
    elapsed = time.monotonic() - t0
    assert timed_out is False
    assert elapsed < 6, f"expected timeout around 2s, took {elapsed:.2f}s"
    print(f"OK: wait_for_login() timed out -> False in {elapsed:.2f}s (no exception)")

    await controller.stop()
    print("\nLOGIN-WAIT SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
