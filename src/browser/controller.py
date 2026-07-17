"""Playwright browser controller (BUILD_PLAN B2 + B3).

Drives a local headed Chromium and exposes a small, LLM-friendly action surface.
Control is DOM/accessibility-based (element refs), NOT vision. A synthetic cursor
(cursor.js) animates to each element before acting (B3).

Contract: start() / stop(); navigate(url), click(ref), type(ref, text), select(ref,
option), scroll(dir), login(email, pw) each return a fresh read_page() snapshot;
move_cursor_to(ref) just animates the pointer (B3, no return):
    {"url": str, "title": str, "h1": str,
     "elements": [{"ref": "e1", "role": "button", "name": "Sign in"}, ...]}
Elements are capped (~60), deduped by (role, name), numbered fresh e1..eN every snapshot.
Any action/navigate() invalidates the previous refs; a superseded ref raises
ControllerError("stale ref — call read_page again").

- read_page() is a COMPACT interactive-element list (internal dict ref -> ElementHandle);
  never dumps raw HTML into the LLM.
- cursor.js is installed via context.add_init_script so it survives every navigation;
  _ensure_cursor() re-injects it defensively if ever missing.
- Every Playwright call carries an explicit timeout; "settle" never raises on timeout —
  a live voice demo must not hang.
- panel.js (guided-UX status sidebar/pill) is installed the same way; _ensure_panel()
  mirrors _ensure_cursor(). show_splash() replaces the page with a startup card before
  any navigation — its own inline script defines a duck-typed window.__demoPanel (same
  phase/hint/act/collapse API) since page.set_content() does not run context init
  scripts (verified empirically); a real navigate() then installs panel.js's sidebar
  fresh on the new document. panel(kind, text, state) is a guarded, never-raising
  dispatch into window.__demoPanel[kind](text, state); click/type/select/navigate/
  scroll each push one human-readable line to the activity feed via panel("act", ...)
  before acting.
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Literal

from playwright.async_api import (
    Browser,
    BrowserContext,
    ElementHandle,
    Error as PlaywrightError,
    Page,
    Playwright,
    async_playwright,
)

CURSOR_JS = (Path(__file__).parent / "cursor.js").read_text()
PANEL_JS = (Path(__file__).parent / "panel.js").read_text()

_TIMEOUT_MS = 8000
_SETTLE_TIMEOUT_MS = 4000
_MAX_ELEMENTS = 60
_PAGE_TEXT_MAX_CHARS = 8000  # matches context/distiller.py's _MAX_CHARS cap

# Curated interactive-element sweep — visible elements only, per BUILD_PLAN B2.
_SNAPSHOT_SELECTOR = (
    "a, button, input, select, textarea, "
    "[role=button], [role=link], [role=tab], [role=menuitem], "
    "[role=checkbox], [role=combobox], [contenteditable]"
)

# Runs per-element inside the page: visibility check + {role, name} extraction.
# name priority: aria-label > visible text > placeholder > value > title.
# Playwright's selector engine pierces open shadow roots by default, so
# query_selector_all(_SNAPSHOT_SELECTOR) would otherwise also match panel.js's own
# Collapse button / Audio settings link — guided-UX chrome, not part of the target
# app. Exclude anything rooted in our panel's shadow tree before the visibility
# check so the LLM-facing snapshot never sees (or can click) our own overlay.
_EXTRACT_JS = r"""
(el) => {
  const root = el.getRootNode();
  if (root && root.host && root.host.id === '__demo-panel-host') return { visible: false };
  const rect = el.getBoundingClientRect(), cs = getComputedStyle(el);
  const visible = rect.width > 0 && rect.height > 0 &&
    cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0';
  if (!visible) return { visible: false };
  const tag = el.tagName.toLowerCase(), type = (el.getAttribute('type') || '').toLowerCase();
  const roleByTag = { a: 'link', button: 'button', select: 'combobox', textarea: 'textbox' };
  const roleByType = { checkbox: 'checkbox', radio: 'radio', submit: 'button', button: 'button' };
  const role = el.getAttribute('role') || roleByTag[tag] ||
    (tag === 'input' ? roleByType[type] || 'textbox' : el.isContentEditable ? 'textbox' : tag);
  const text = tag === 'select'
    ? (el.options[el.selectedIndex] ? el.options[el.selectedIndex].text.trim() : '')
    : (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');
  const name = el.getAttribute('aria-label') || text || el.getAttribute('placeholder') ||
    el.value || el.getAttribute('title') || '';
  return { visible: true, role, name: String(name).trim().slice(0, 60) };
}
"""

# Tried in order (not a single combined selector — a comma-selector returns the first
# DOM-order match across *all* alternatives, which would defeat the priority order).
_EMAIL_SELECTORS = ["input[type=email]", 'input[name*="email" i]', "input[type=text]"]
_PASSWORD_SELECTOR = "input[type=password]"
_SUBMIT_SELECTORS = ["button[type=submit]", "input[type=submit]", "form button", "button"]

# Startup splash (show_splash()): a minimal centered card rendered via page.set_content()
# before any navigation. Its inline <script> defines its OWN small window.__demoPanel
# (phase/hint/act/collapse — same method names panel.js exposes) that drives a phase
# checklist instead of the sidebar; set_content() does not run context init scripts
# (verified empirically), so panel.js never installs on this document — no collision.
# Phase strings are the EXACT strings app.py passes to controller.panel("phase", ...);
# PHASE_TO_ROW maps the ones that occur before the real target navigation to a row here.
# Unknown phase names (everything after navigation, once panel.js's sidebar has taken
# over) simply update the status line on THAT document instead — this file is inert by
# then. hint()/act()/collapse() are safe no-ops here; nothing in the real flow calls
# hint() before navigation, but the same-API contract must hold regardless.
_SPLASH_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>demo-agent</title>
<style>
  html, body { height: 100%; margin: 0; }
  body {
    display: flex; align-items: center; justify-content: center;
    background: #0b0c0e; color: #e6e7ea;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  .card {
    width: 380px; padding: 28px 30px; border-radius: 14px;
    background: #17181c; border: 1px solid rgba(255,255,255,.08);
    box-shadow: 0 20px 60px rgba(0,0,0,.45);
  }
  .title { font-size: 15px; font-weight: 600; margin-bottom: 18px; }
  .title .brand { color: #6ea8fe; }
  .status { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; background: #6b7280; }
  .dot.working { background: #f0a93b; animation: pulse 1.6s ease-in-out infinite; }
  .dot.live { background: #34c77b; }
  .dot.error { background: #ff5c5c; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .45; } }
  #statusLine { font-size: 13px; color: #c3c6cd; }
  .rows { display: flex; flex-direction: column; gap: 9px; }
  .row { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #6b7280; }
  .row .mark { width: 14px; text-align: center; flex: none; font-size: 12px; }
  .row.done { color: #9aa0ab; }
  .row.done .mark { color: #34c77b; }
  .row.active { color: #e6e7ea; }
  .row.active .mark { color: #f0a93b; animation: pulse 1.6s ease-in-out infinite; }
  #hintLine { font-size: 11.5px; color: #8b8d97; margin-top: 14px; }
</style></head>
<body>
  <div class="card">
    <div class="title"><span class="brand">demo-agent</span> — starting your live demo</div>
    <div class="status"><span class="dot working" id="statusDot"></span><span id="statusLine">Starting…</span></div>
    <div class="rows">
      <div class="row done"><span class="mark">✓</span><span>Browser</span></div>
      <div class="row" data-row="Opening the app"><span class="mark">•</span><span>Opening the app</span></div>
      <div class="row" data-row="Signing in"><span class="mark">•</span><span>Signing in</span></div>
      <div class="row" data-row="Reading the product"><span class="mark">•</span><span>Reading the product</span></div>
      <div class="row" data-row="Voice server"><span class="mark">•</span><span>Voice server</span></div>
      <div class="row" data-row="Connecting audio"><span class="mark">•</span><span>Connecting audio</span></div>
    </div>
    <div id="hintLine" hidden></div>
  </div>
<script>
(function () {
  var ROWS = ["Opening the app", "Signing in", "Reading the product", "Voice server", "Connecting audio"];
  var PHASE_TO_ROW = {
    "Opening the app": "Opening the app",
    "Signing in": "Signing in",
    "Reading the product": "Reading the product",
    "Starting voice server": "Voice server",
    "Connecting audio": "Connecting audio"
  };
  var rowEls = {};
  ROWS.forEach(function (label) {
    rowEls[label] = document.querySelector('[data-row="' + label + '"]');
  });
  var statusEl = document.getElementById("statusLine");
  var dotEl = document.getElementById("statusDot");
  var hintEl = document.getElementById("hintLine");

  function setRow(label, cls) {
    var el = rowEls[label];
    if (!el) return;
    el.classList.remove("done", "active");
    if (cls) el.classList.add(cls);
    var mark = el.querySelector(".mark");
    if (mark) mark.textContent = cls === "done" ? "✓" : "•";
  }

  window.__demoPanel = {
    phase: function (text, state) {
      if (statusEl) statusEl.textContent = text || "";
      if (dotEl) dotEl.className = "dot " + (state || "working");
      var idx = ROWS.indexOf(PHASE_TO_ROW[text]);
      if (idx === -1) return;
      ROWS.forEach(function (label, i) {
        setRow(label, i < idx ? "done" : i === idx ? "active" : "");
      });
    },
    hint: function (text) {
      if (!hintEl) return;
      hintEl.textContent = text || "";
      hintEl.hidden = !text;
    },
    act: function () {},
    collapse: function () {}
  };
})();
</script>
</body></html>"""


class ControllerError(Exception):
    """Raised for any browser-action failure; message is meant to be read (and acted on)
    by the LLM mid-demo, e.g. "no element e7 in current snapshot"."""


class BrowserController:
    def __init__(self, *, headless: bool = False, storage_state: str | None = None) -> None:
        self.headless = headless
        self.storage_state = storage_state
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._refs: dict[str, ElementHandle] = {}
        self._ref_names: dict[str, str] = {}
        self._seen_refs: set[str] = set()
        self._generation = 0

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless, timeout=_TIMEOUT_MS)
        state = self.storage_state if self.storage_state and Path(self.storage_state).exists() else None
        # no_viewport: track the real window size — Playwright's fixed default
        # viewport (1280x720) leaves dead white space when the user resizes.
        self._context = await self._browser.new_context(storage_state=state, no_viewport=True)
        await self._context.add_init_script(CURSOR_JS)
        await self._context.add_init_script(PANEL_JS)
        self._page = await self._context.new_page()
        await self._ensure_cursor()
        await self._ensure_panel()

    async def stop(self) -> None:
        for closer in (
            self._context.close if self._context else None,
            self._browser.close if self._browser else None,
            self._pw.stop if self._pw else None,
        ):
            if closer is None:
                continue
            try:
                await closer()
            except Exception:
                # A terminal Ctrl-C hits the whole process group, so the
                # browser may already be gone — teardown never raises.
                pass
        self._pw = self._browser = self._context = self._page = None
        self._refs, self._ref_names, self._seen_refs = {}, {}, set()

    def _require_page(self) -> Page:
        if self._page is None:
            raise ControllerError("controller not started — call start() first")
        return self._page

    async def _ensure_cursor(self) -> None:
        page = self._require_page()
        try:
            has_cursor = await page.evaluate("() => !!window.__demoCursor")
            if not has_cursor:
                await page.evaluate(CURSOR_JS)
        except PlaywrightError:
            pass  # cosmetic only — never block the demo on the cursor overlay

    async def _ensure_panel(self) -> None:
        page = self._require_page()
        try:
            has_panel = await page.evaluate("() => !!window.__demoPanel")
            if not has_panel:
                await page.evaluate(PANEL_JS)
        except PlaywrightError:
            pass  # cosmetic only — never block the demo on the status panel

    async def show_splash(self) -> None:
        """Render a minimal startup card before any navigation happens. Phase/hint
        pushes against this document hit the small window.__demoPanel defined inline
        in _SPLASH_HTML (NOT panel.js — page.set_content() does not run context init
        scripts, verified empirically, so the two never collide); once navigate()
        performs a real page load, panel.js's sidebar installs fresh on the new
        document and subsequent panel() calls land there instead."""
        page = self._require_page()
        try:
            await page.set_content(_SPLASH_HTML, timeout=_TIMEOUT_MS)
        except PlaywrightError:
            pass  # cosmetic only — a failed splash must never block startup

    async def panel(self, kind: str, text: str, state: str = "working") -> None:
        """Best-effort call into window.__demoPanel[kind](text, state) on the current
        page — same call shape whether the current document is the splash (its own
        small window.__demoPanel) or a real page (panel.js's sidebar/pill). Never
        raises and no-ops if the page or panel isn't available: a cosmetic status
        update must never interrupt the demo."""
        if self._page is None:
            return
        try:
            await self._ensure_panel()
            await self._page.evaluate(
                "([kind, text, state]) => window.__demoPanel && window.__demoPanel[kind] "
                "&& window.__demoPanel[kind](text, state)",
                [kind, text, state],
            )
        except PlaywrightError:
            pass

    async def poll_panel_command(self) -> str | None:
        """Read-and-clear the sidebar's pending command (e.g. "end" from the
        End-demo button — app.py polls this). Never raises."""
        if self._page is None:
            return None
        try:
            return await self._page.evaluate(
                "() => { const c = window.__demoPanelCmd || null; "
                "window.__demoPanelCmd = null; return c; }"
            )
        except PlaywrightError:
            return None

    async def front_demo(self) -> None:
        """Bring the demo tab back to the foreground. The pipecat voice client
        connects in its own tab (open_client_tab), which briefly steals focus —
        the user should be looking at the demo app, not the audio-plumbing tab."""
        if self._page is None:
            return
        try:
            await self._page.bring_to_front()
        except PlaywrightError:
            pass

    async def _settle(self) -> None:
        try:
            await self._require_page().wait_for_load_state("domcontentloaded", timeout=_SETTLE_TIMEOUT_MS)
        except PlaywrightError:
            pass  # demos must not hang waiting for a page that never fully settles

    # -- snapshot -----------------------------------------------------------

    async def read_page(self) -> dict:
        return await self._snapshot()

    async def wait_for_content(self, *, min_chars: int = 150, timeout_s: float = 10.0) -> bool:
        """Wait until the page shows real content (body text >= min_chars).

        SPAs render well after domcontentloaded — with a restored auth session
        the app may still be painting its skeleton when we'd otherwise read it
        (which once produced a 'page content is insufficient' product brief).
        Returns False on timeout; never raises."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                text = await self._require_page().evaluate(
                    "() => (document.body && document.body.innerText || '').trim().length"
                )
                if text >= min_chars:
                    return True
            except (PlaywrightError, ControllerError):
                pass
            await asyncio.sleep(0.4)
        return False

    async def _snapshot(self) -> dict:
        snap = await self._snapshot_once()
        if not snap["elements"]:
            # Mid-transition SPA frame (view swap, lazy render): give it a beat
            # and look again rather than telling the LLM the page is empty.
            await asyncio.sleep(1.0)
            snap = await self._snapshot_once()
        return snap

    async def _snapshot_once(self) -> dict:
        page = self._require_page()
        await self._ensure_cursor()
        await self._ensure_panel()
        self._seen_refs |= self._refs.keys()
        self._generation += 1
        self._refs = {}
        self._ref_names = {}

        elements: list[dict] = []
        seen_keys: set[tuple[str, str]] = set()
        handles = await page.query_selector_all(_SNAPSHOT_SELECTOR)
        for handle in handles:
            if len(elements) >= _MAX_ELEMENTS:
                break
            try:
                data = await handle.evaluate(_EXTRACT_JS)
            except PlaywrightError:
                continue
            if not data or not data.get("visible"):
                continue
            key = (data["role"], data["name"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            ref = f"e{len(elements) + 1}"
            elements.append({"ref": ref, "role": data["role"], "name": data["name"]})
            self._refs[ref] = handle
            self._ref_names[ref] = data["name"] or ref
        self._seen_refs |= self._refs.keys()

        h1 = ""
        h1_handle = await page.query_selector("h1")
        if h1_handle is not None:
            try:
                h1 = (await h1_handle.inner_text()).strip()
            except PlaywrightError:
                h1 = ""
        return {"url": page.url, "title": await page.title(), "h1": h1, "elements": elements}

    def _resolve(self, ref: str) -> ElementHandle:
        handle = self._refs.get(ref)
        if handle is not None:
            return handle
        if ref in self._seen_refs:
            raise ControllerError("stale ref — call read_page again")
        raise ControllerError(f"no element {ref} in current snapshot")

    async def _glide(self, handle: ElementHandle) -> None:
        """Scroll the element into view and animate the synthetic cursor to its center."""
        page = self._require_page()
        try:
            await handle.scroll_into_view_if_needed(timeout=_TIMEOUT_MS)
            box = await handle.bounding_box()
        except PlaywrightError as e:
            raise ControllerError(f"could not locate element on screen: {e}") from e
        if box is None:
            raise ControllerError("element has no visible position (bounding box unavailable)")
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        await self._ensure_cursor()
        await page.evaluate("([x, y]) => window.__demoCursor.moveTo(x, y)", [x, y])

    # -- navigation / actions ------------------------------------------------

    async def navigate(self, url: str) -> dict:
        await self.panel("act", f"Opening {url}")
        page = self._require_page()
        try:
            await page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
        except PlaywrightError as e:
            raise ControllerError(f"navigation to {url} failed: {e}") from e
        await self._settle()
        return await self._snapshot()

    async def move_cursor_to(self, ref: str) -> None:
        await self._glide(self._resolve(ref))

    async def click(self, ref: str) -> dict:
        handle = self._resolve(ref)
        await self.panel("act", f'Clicking "{self._ref_names.get(ref, ref)}"')
        await self._glide(handle)
        try:
            await handle.click(timeout=_TIMEOUT_MS)
        except PlaywrightError as e:
            raise ControllerError(f"click on {ref} failed: {e}") from e
        await self._settle()
        return await self._snapshot()

    async def type(self, ref: str, text: str) -> dict:
        handle = self._resolve(ref)
        await self.panel("act", f'Typing into "{self._ref_names.get(ref, ref)}"')
        await self._glide(handle)
        try:
            await handle.fill(text, timeout=_TIMEOUT_MS)
        except PlaywrightError as e:
            raise ControllerError(f"type into {ref} failed: {e}") from e
        await self._settle()
        return await self._snapshot()

    async def select(self, ref: str, option: str) -> dict:
        """Choose an option in a <select> by visible label, falling back to value
        (Playwright's fill() rejects <select>; this is the dedicated path)."""
        handle = self._resolve(ref)
        await self.panel("act", f'Choosing "{option}"')
        await self._glide(handle)
        try:
            await handle.select_option(label=option, timeout=_TIMEOUT_MS)
        except PlaywrightError:
            try:
                await handle.select_option(value=option, timeout=_TIMEOUT_MS)
            except PlaywrightError as e:
                raise ControllerError(f"select on {ref} failed — no option {option!r}: {e}") from e
        await self._settle()
        return await self._snapshot()

    async def scroll(self, direction: Literal["up", "down"]) -> dict:
        if direction not in ("up", "down"):
            raise ControllerError(f"invalid scroll direction {direction!r} (use 'up' or 'down')")
        await self.panel("act", f"Scrolling {direction}")
        page = self._require_page()
        viewport = page.viewport_size or {"height": 800}
        delta = int(viewport["height"] * 0.7)
        try:
            await page.mouse.wheel(0, -delta if direction == "up" else delta)
        except PlaywrightError as e:
            raise ControllerError(f"scroll failed: {e}") from e
        await self._settle()
        return await self._snapshot()

    async def open_client_tab(self, url: str) -> bool:
        """Open the voice-client UI in a second tab of the controlled browser,
        grant it microphone permission (no browser prompt), and click Connect.

        Keeps the whole demo in one window and removes the manual click — the
        default-browser flow left users waiting for a connection that needed a
        Connect click they didn't know about. Returns False (with a printed
        hint) on any failure; never raises."""
        if self._context is None:
            return False
        try:
            origin = url.split("/client")[0]
            await self._context.grant_permissions(["microphone"], origin=origin)
            page = await self._context.new_page()
            await page.goto(url, timeout=_TIMEOUT_MS, wait_until="load")
            # exact=True everywhere: get_by_role's default substring matching
            # would make "Connect" also match "Disconnect".
            connect = page.get_by_role("button", name="Connect", exact=True)
            disconnect = page.get_by_role("button", name="Disconnect", exact=True)
            # Let the client app actually wire its handlers before clicking.
            await connect.first.wait_for(state="visible", timeout=15000)
            await asyncio.sleep(0.5)
            await connect.first.click(timeout=8000)
            # First connection pays the whole cold start (VAD model load,
            # provider websockets, ICE) — observed ~40s. Poll for the connected
            # state and only re-click if the button actually returned to idle
            # (a blind retry mid-negotiation can spawn a second session).
            hinted = False
            deadline = time.monotonic() + 45.0
            while time.monotonic() < deadline:
                try:
                    if await disconnect.count() and await disconnect.first.is_visible():
                        print("demo-agent: voice client connected — say hello.", flush=True)
                        return True
                    if await connect.count() and await connect.first.is_visible():
                        await connect.first.click(timeout=4000)
                except PlaywrightError:
                    pass
                if not hinted and time.monotonic() > deadline - 33.0:
                    print(
                        "demo-agent: still connecting (cold start can take ~30s) — if "
                        "macOS is asking to allow the microphone for Chromium, click Allow.",
                        flush=True,
                    )
                    hinted = True
                await asyncio.sleep(1.0)
            print(
                f"demo-agent: could not auto-connect the voice client — open {url} "
                "and click Connect (check the macOS microphone permission for Chromium).",
                flush=True,
            )
            return False
        except PlaywrightError as e:
            print(
                f"demo-agent: could not auto-connect the voice client ({e}) — "
                f"open {url} and click Connect.",
                flush=True,
            )
            return False

    async def login(self, email: str, password: str) -> dict:
        """Best-effort generic login on the CURRENT page: finds an email/text input and a
        password input via common selectors, fills both (cursor glide first), then submits
        via a submit-ish button or Enter. If self.storage_state is set, saves the
        authenticated context to that path so later runs can skip login entirely.

        Verified against the local test fixture (tests/fixture.html) only — the real
        target app is gated behind self-serve signup and has no credentials configured;
        this method has not been exercised against it.
        """
        page = self._require_page()
        email_handle = None
        for selector in _EMAIL_SELECTORS:
            email_handle = await page.query_selector(selector)
            if email_handle is not None:
                break
        password_handle = await page.query_selector(_PASSWORD_SELECTOR)
        if email_handle is None or password_handle is None:
            raise ControllerError("login: could not find email/password inputs on current page")

        try:
            await self._glide(email_handle)
            await email_handle.fill(email, timeout=_TIMEOUT_MS)
            await self._glide(password_handle)
            await password_handle.fill(password, timeout=_TIMEOUT_MS)
        except PlaywrightError as e:
            raise ControllerError(f"login: failed to fill credentials: {e}") from e

        submit_handle = None
        for selector in _SUBMIT_SELECTORS:
            submit_handle = await page.query_selector(selector)
            if submit_handle is not None:
                break
        try:
            if submit_handle is not None:
                await self._glide(submit_handle)
                await submit_handle.click(timeout=_TIMEOUT_MS)
            else:
                await password_handle.press("Enter", timeout=_TIMEOUT_MS)
        except PlaywrightError as e:
            raise ControllerError(f"login: submit failed: {e}") from e

        # Auth is often an async round-trip well past domcontentloaded — a blind
        # settle here once captured the sign-in page as "logged in" (and saved a
        # pre-auth storage state that could never restore). Verify for real.
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            if await self.is_logged_in():
                break
            await asyncio.sleep(0.5)
        else:
            raise ControllerError(
                "login: still on a sign-in page after 12s — check the credentials"
            )
        await self._settle()
        result = await self._snapshot()
        await self._save_auth_state()
        return result

    # -- manual login / auth state -------------------------------------------

    async def is_logged_in(self) -> bool:
        """Heuristic: True iff the current page has no visible password input.
        Limits: an app whose logged-out state has no password field (SSO-only,
        magic-link) will false-positive as logged in; a page mid-navigation,
        blank, or erroring counts as NOT logged in — any exception is swallowed
        and returns False rather than raised, so callers can poll this safely.
        """
        if self._page is None:
            return False
        try:
            for handle in await self._page.query_selector_all(_PASSWORD_SELECTOR):
                data = await handle.evaluate(_EXTRACT_JS)
                if data and data.get("visible"):
                    return False
            return True
        except PlaywrightError:
            return False

    async def _save_auth_state(self) -> None:
        """Persist the current context's storage state to self.storage_state, if
        configured, so later runs can skip login. Best-effort: any failure is
        caught and printed as a single warning line, never raised.
        """
        if not self.storage_state or self._context is None:
            return
        try:
            Path(self.storage_state).parent.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=self.storage_state)
        except (PlaywrightError, OSError) as e:
            print(f"demo-agent: could not save auth state to {self.storage_state}: {e}")

    async def wait_for_login(self, *, timeout_s: float = 300.0, poll_s: float = 2.0) -> bool:
        """Wait for a human to log in manually on the CURRENT page (no credentials
        configured). Returns True immediately if already logged in — covers a
        restored storage_state — saving auth state either way. Otherwise prints
        one waiting line and polls is_logged_in() every poll_s until it flips
        true; returns False on timeout without raising — the caller decides
        whether to proceed anyway.
        """
        if await self.is_logged_in():
            await self._save_auth_state()
            return True

        print(
            "demo-agent: no login configured — log in manually in the browser "
            f"window (waiting up to {int(timeout_s)}s)..."
        )
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            await asyncio.sleep(poll_s)
            if await self.is_logged_in():
                await self._settle()
                print("demo-agent: login detected — continuing.")
                await self._save_auth_state()
                return True
        return False

    async def page_text(self) -> tuple[str, str]:
        """Return (title, visible body text) of the CURRENT page, whitespace-
        collapsed and capped at _PAGE_TEXT_MAX_CHARS — same normalization as
        context/distiller.py's _normalize — for post-login context distillation.
        """
        page = self._require_page()
        try:
            title = await page.title()
            text = await page.evaluate("() => document.body.innerText")
        except PlaywrightError as e:
            raise ControllerError(f"page_text failed: {e}") from e
        return title.strip(), re.sub(r"\s+", " ", text or "").strip()[:_PAGE_TEXT_MAX_CHARS]
