"""Detached Chromium app windows — the product's own browser for every
user-facing page (setup, post-call report), never the system default.

`open_chromium_window(url)` spawns THIS module as a detached helper process;
the helper opens `url` as a chromeless --app window through Playwright's own
launcher, inheriting its full default switch set — which is what suppresses
the Chrome-for-Testing infobar and the macOS keychain ("Safe Storage") prompt
(--use-mock-keychain) that a raw Chromium launch triggers. The helper lives
exactly as long as the window and dies when the user closes it; a throwaway
profile dir under out/ is removed on exit. Fallback: system default browser.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def open_chromium_window(url: str) -> None:
    """Open `url` in a detached product-Chromium app window (never blocks)."""
    try:
        subprocess.Popen(
            [sys.executable, "-m", "src.chromium_window", url],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=_REPO_ROOT,
        )
        return
    except OSError:
        pass
    import webbrowser

    webbrowser.open(url)


def _serve_window(url: str) -> None:
    """Helper-process body: hold the window open until the user closes it."""
    import shutil

    from playwright.sync_api import sync_playwright

    out_dir = _REPO_ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    profile = tempfile.mkdtemp(prefix=".appwin-", dir=out_dir)
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=profile,
                headless=False,
                no_viewport=True,
                args=[f"--app={url}"],
            )
            try:
                while context.pages:
                    context.pages[0].wait_for_event("close", timeout=0)
            except Exception:
                pass  # window/browser closed — that's the exit signal
            finally:
                try:
                    context.close()
                except Exception:
                    pass
    finally:
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            _serve_window(sys.argv[1])
        except Exception:
            import webbrowser

            webbrowser.open(sys.argv[1])
