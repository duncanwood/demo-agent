"""Entry point — wires the whole demo agent together.

Startup sequence:
  1. First-run gate: if cloud keys are missing, serve the local setup page
     (browser opens to it automatically), which writes .env and hot-reloads
     settings; "use local mode" is the zero-key escape hatch.
  2. Launch headed Chromium, open DEMO_TARGET_URL. Login ladder: saved auth
     state (.auth-state.json) -> .env credentials -> manual login in the
     window (detected automatically, then saved for next time) -> proceed
     without login.
  3. Distill the product brief — from CONTEXT_URL if configured, else from the
     logged-in app page itself (the standalone renderer would only see the
     sign-in page on gated apps).
  4. Run the pipecat SmallWebRTC voice loop; the client UI opens in the
     default browser as soon as the server is actually serving.
  5. On exit (Ctrl-C -> graceful, see voice/pipeline.py), stop the browser and
     write the lead report to out/session-<ts>.json if anything was said.

Everything from step 2 on is wrapped in a try/finally around the browser
controller so no Chromium is ever left orphaned and the report runs even when
the server exits via a signal. AUTO_OPEN=0 disables the self-opening tabs
(used by tests/boot checks).
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime


class _TeeLog:
    """Mirror a stream into the run log, adding per-line timestamps (file only —
    the terminal stays clean). pipecat/uvicorn lines carry their own stamps; the
    demo-agent's own prints get theirs from here."""

    def __init__(self, stream, file) -> None:
        self._s, self._f, self._nl = stream, file, True

    def write(self, text: str) -> int:
        self._s.write(text)
        for part in text.splitlines(keepends=True):
            if self._nl:
                self._f.write(datetime.now().strftime("[%H:%M:%S.%f")[:-3] + "] ")
            self._f.write(part)
            self._nl = part.endswith("\n")
        return len(text)

    def flush(self) -> None:
        self._s.flush()
        self._f.flush()

    def __getattr__(self, name):
        return getattr(self._s, name)


def _install_run_log(path: str = "out/agent.log") -> None:
    """Tee stdout+stderr into a persistent timestamped log so any run can be
    diagnosed after the fact (terminal scrollback is not a log)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a", buffering=1)
    f.write(f"\n===== run {datetime.now().isoformat(timespec='seconds')} =====\n")
    sys.stdout = _TeeLog(sys.stdout, f)
    sys.stderr = _TeeLog(sys.stderr, f)

# Pipecat's dev runner auto-discovers a module-level `bot` on
# `sys.modules["__main__"]` — which this file becomes when run as
# `python -m src.app` (see voice/pipeline.py docstring). This thin wrapper
# keeps that contract WITHOUT importing the heavy pipecat stack at module
# import time: on a cold venv those imports take 10-20s, which would delay
# the first-run setup page (served before any pipecat code is needed).
async def bot(runner_args):  # noqa: ANN001 — signature owned by pipecat's runner
    from src.voice.pipeline import bot as _bot
    return await _bot(runner_args)

_BASE_URL = "http://localhost:7860"


def _extract_transcript(context) -> list[dict]:
    """Pull the spoken conversation out of a session's LLMContext: user/assistant
    turns with plain-string content only (system prompt, tool calls with content
    None, and tool-result messages are all filtered out)."""
    turns = []
    for m in context.get_messages():
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) \
                and m["content"].strip():
            turns.append({"role": m["role"], "content": m["content"]})
    return turns


async def _when_up(url: str, *, timeout_s: float = 60.0) -> bool:
    """Poll `url` until it answers 200. Returns False on timeout."""
    import httpx

    deadline = asyncio.get_event_loop().time() + timeout_s
    async with httpx.AsyncClient() as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                if (await client.get(url, timeout=2)).status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return False


async def _open_browser_when_up(url: str) -> None:
    """Open `url` in the default browser once it serves (AUTO_OPEN=0 disables)."""
    if os.getenv("AUTO_OPEN", "1") == "0":
        return
    import webbrowser

    if await _when_up(url):
        webbrowser.open(url)


async def _connect_client_when_up(controller, url: str) -> None:
    """Once the server serves, open the voice client in the controlled browser
    with mic permission granted and Connect clicked — zero manual steps.
    (AUTO_OPEN=0 disables; failures degrade to a printed open-it-yourself hint.)

    Drives the guided-UX status panel through the connect handoff: on success
    the demo tab (not the pipecat client tab) gets focus back and the panel
    goes "live"; on failure it flags the error with a pointer at the client URL.
    """
    if os.getenv("AUTO_OPEN", "1") == "0":
        return
    if await _when_up(url):
        await controller.panel("phase", "Connecting audio", "working")
        await controller.panel(
            "hint", "First connection can take ~30 seconds while models warm up."
        )
        if await controller.open_client_tab(url):
            await controller.front_demo()
            tracks = await controller.set_mic_enabled(True)
            print(
                f"demo-agent: mic stream live ({tracks} audio track(s))" if tracks
                else "demo-agent: warning — no local mic stream detected (sidebar mute won't work)",
                flush=True,
            )
            await controller.panel("phase", "Live — say hello", "live")
            await controller.panel(
                "hint",
                "The agent hears you continuously; just talk. Ctrl-C in the "
                "terminal ends the demo and writes the report.",
            )
        else:
            await controller.panel("phase", "Audio not connected", "error")
            await controller.panel("hint", f"Open {url} and click Connect.")


async def _panel_command_watcher(controller) -> None:
    """Poll the demo page for sidebar commands: 'end' triggers the same
    graceful shutdown as Ctrl-C; 'mute-toggle' flips the live mic tracks in
    the client tab; 'front-client' brings the live audio panel forward."""
    from src.voice.pipeline import request_shutdown

    mic_on = True
    while True:
        cmd = await controller.poll_panel_command()
        if cmd == "end":
            print("demo-agent: end requested from the demo page — shutting down.", flush=True)
            request_shutdown()
            return
        if cmd == "mute-toggle":
            mic_on = not mic_on
            tracks = await controller.set_mic_enabled(mic_on)
            if not tracks:
                mic_on = True  # nothing switched — stay in the live state
                await controller.panel("act", "Mute failed — no live mic stream")
            else:
                await controller.panel("act", "Mic unmuted" if mic_on else "Mic muted")
            await controller.panel("micState", "live" if mic_on else "muted")
        elif cmd == "front-client":
            if not await controller.front_client():
                await controller.panel("act", "Audio panel tab is gone")
        await asyncio.sleep(1.2)


async def _ensure_logged_in(controller, settings) -> None:
    """Login ladder: restored session -> .env credentials -> manual login with
    auto-detection -> proceed without login (never blocks the demo forever)."""
    from src.browser.controller import ControllerError

    if await controller.is_logged_in():
        print("demo-agent: already logged in (saved session restored).", flush=True)
        return
    if settings.login_email and settings.login_password:
        try:
            await controller.login(settings.login_email, settings.login_password)
            print("demo-agent: logged in with .env credentials.", flush=True)
            return
        except ControllerError as e:
            print(f"demo-agent: credential login failed ({e}) — falling back to manual login.",
                  flush=True)
    # Unconditional: the only way to know the manual-login path has been
    # reached is to be about to call wait_for_login() itself.
    await controller.panel("hint", "Log in in this window — I'll notice.")
    if not await controller.wait_for_login():
        print("demo-agent: no login detected — proceeding with whatever is accessible.",
              flush=True)


async def _build_product_brief(controller, settings) -> str:
    """CONTEXT_URL (marketing page, unauthenticated render) if configured; else
    the text of the page the controller is actually on — post-login, so gated
    apps distill from the real product, not the sign-in screen."""
    from src.browser.controller import ControllerError
    from src.context.distiller import distill_product_context, summarize_page_text

    if settings.context_url:
        print(f"demo-agent: distilling product context from {settings.context_url} ...", flush=True)
        return await distill_product_context(settings.context_url)
    if settings.target_url:
        print("demo-agent: distilling product context from the live app page ...", flush=True)
        try:
            title, text = await controller.page_text()
        except ControllerError as e:
            print(f"demo-agent: could not read app page for context ({e})", flush=True)
            return ""
        return await summarize_page_text(title, "", text)
    return ""


def _port_in_use(port: int = 7860) -> bool:
    import socket

    with socket.socket() as s:
        try:
            s.bind(("localhost", port))
            return False
        except OSError:
            return True


async def main() -> None:
    # Installed before the heavy imports so loguru (pipecat) binds the teed
    # stderr and every line of the run lands in out/agent.log too.
    _install_run_log()

    from src.agent.prompts import build_system_prompt
    from src.agent.tools import register_browser_tools
    from src.browser.controller import BrowserController
    from src.config import settings, validate_for_mode
    from src.enrichment.report import write_report
    from src.setup.first_run import needs_setup, run_first_run_setup
    from src.voice.pipeline import run_voice_agent

    # Fail fast and loud on a busy port — otherwise the browser/login/distill
    # startup runs for ~20s and THEN dies on bind, while a stale server keeps
    # serving a mismatched client UI (a confusing "audio won't connect" state).
    if _port_in_use():
        print(
            "demo-agent: port 7860 is already in use — another demo-agent (or a "
            "leftover one) is running. Stop it first:  lsof -ti :7860 | xargs kill",
            flush=True,
        )
        raise SystemExit(1)

    if needs_setup():
        print(f"demo-agent: first-run setup — opening {_BASE_URL}/ (add your keys there).",
              flush=True)
        opener = asyncio.create_task(_open_browser_when_up(f"{_BASE_URL}/"))
        completed = await run_first_run_setup()
        opener.cancel()
        if not completed:
            print("demo-agent: setup not completed — exiting.", flush=True)
            return

    validate_for_mode()

    # Holds the live connection's LLMContext so the enrichment sink can read the
    # conversation after the server stops (one demo session type per process —
    # same assumption as voice/pipeline.py's module state).
    session_contexts: list = []

    controller = BrowserController(headless=False, storage_state=settings.storage_state or None)
    try:
        await controller.start()
        # Startup takes tens of seconds with nothing else on screen — show a
        # phase checklist immediately so the user knows what's happening and
        # when (if ever) they need to act. Phases before the target navigation
        # land on this splash card; navigate() below replaces it with the real
        # app, where panel.js's sidebar takes over the same phase/hint API.
        await controller.show_splash()

        if settings.target_url:
            await controller.panel("phase", "Opening the app", "working")
            await controller.navigate(settings.target_url)
            await controller.panel("phase", "Signing in", "working")
            await _ensure_logged_in(controller, settings)
            # SPAs keep rendering long after navigation "completes" — don't
            # read context (or start the demo) off a half-painted skeleton.
            if not await controller.wait_for_content():
                print("demo-agent: page content still thin after 10s — continuing anyway.",
                      flush=True)

        await controller.panel("phase", "Reading the product", "working")
        brief = await _build_product_brief(controller, settings)
        print(
            f"demo-agent: product brief ready ({len(brief)} chars): {brief[:120]}..."
            if brief else "demo-agent: no product brief — continuing without",
            flush=True,
        )

        system_prompt = build_system_prompt(product_brief=brief, target_url=settings.target_url)

        def _register(llm, ctx) -> None:
            session_contexts.append(ctx)
            register_browser_tools(llm, ctx, controller)

        print(f"demo-agent: starting voice loop (provider_mode={settings.provider_mode})", flush=True)
        # The voice client opens as a second tab of the controlled browser with
        # mic permission pre-granted and Connect auto-clicked. (After first-run
        # setup, the setup page also redirects its own tab there — harmless.)
        client_opener = asyncio.create_task(
            _connect_client_when_up(controller, f"{_BASE_URL}/client/")
        )
        command_watcher = asyncio.create_task(_panel_command_watcher(controller))
        await controller.panel("phase", "Starting voice server", "working")
        try:
            await run_voice_agent(register_tools=_register, system_prompt=system_prompt)
        finally:
            client_opener.cancel()
            command_watcher.cancel()
    finally:
        # The lead report FIRST — it needs only the captured context, and a
        # terminal Ctrl-C delivers SIGINT to the whole process group, so the
        # browser may already be dead and its teardown must not cost us the
        # report (it did once: CancelledError, session lost).
        transcript = _extract_transcript(session_contexts[-1]) if session_contexts else []
        if transcript:
            try:
                path = await write_report(transcript)
                print(f"demo-agent: lead report written -> {path}", flush=True)
                from pathlib import Path as _Path

                from src.enrichment.view import render
                html_path = render(_Path(path))
                print(f"demo-agent: post-call page -> {html_path}", flush=True)
                if os.getenv("AUTO_OPEN", "1") != "0":
                    import webbrowser
                    webbrowser.open(html_path.resolve().as_uri())
            except Exception as e:  # a failed report must not mask the real exit reason
                print(f"demo-agent: enrichment failed ({e})", flush=True)
        try:
            await asyncio.wait_for(controller.stop(), timeout=8)
        except Exception:
            pass  # browser may have died with the process group — nothing to clean


if __name__ == "__main__":
    asyncio.run(main())
