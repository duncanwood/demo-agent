"""Detached Chromium app windows — the product's own browser for every
user-facing page (setup, post-call report), never the system default.

The window is a separate OS process (start_new_session) so it outlives the
demo-agent process; --test-type suppresses the Chrome-for-Testing infobar
(Playwright passes equivalent switches for windows it launches itself).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def open_chromium_window(exe: str | None, url: str) -> None:
    """Open `url` as a chromeless app window of Playwright's Chromium; fall
    back to the default browser when the executable is unavailable."""
    if exe:
        try:
            os.makedirs("out", exist_ok=True)
            subprocess.Popen(
                [
                    exe,
                    f"--app={url}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--test-type",
                    f"--user-data-dir={Path('out/.app-profile').resolve()}",
                ],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except OSError:
            pass
    import webbrowser

    webbrowser.open(url)


def chromium_path_sync() -> str | None:
    """Playwright's Chromium executable path (sync callers, e.g. the report
    CLI). Returns None if unavailable — callers fall back to webbrowser."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return str(p.chromium.executable_path)
    except Exception:
        return None
