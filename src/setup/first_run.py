"""First-run setup GUI (BUILD_PLAN-adjacent, self-contained).

When the app starts in cloud mode without its provider keys, `app.py` (an
integrator's concern, not this module's) is expected to call
`run_first_run_setup()` instead of exiting. This module then serves a tiny
local web page — GET / renders a form for DEEPGRAM_API_KEY / OPENAI_API_KEY /
CARTESIA_API_KEY (plus an optional demo-login email/password) with a "use
local mode instead" escape hatch. POST /save validates the three keys live
against each provider (2xx = valid; validation is dependency-injected for
tests), and on success merges the submitted values into the .env file at
`env_path` — creating it from .env.example if absent, replacing existing
`VAR=` lines in place, appending any that don't yet exist, and preserving
every other line (comments, blank lines, unrelated vars) byte-for-byte via an
atomic write (temp file + os.replace). POST /local-mode does the same but
just sets PROVIDER_MODE=local.

Either success path calls `src.config.reload_settings()` (only when
`env_path` is the real ".env" — never for a test's temp path), renders a
success page, and stops the setup server (`uvicorn.Server.should_exit`) so
`run_first_run_setup()` returns True and the caller can proceed to boot the
real app. If the server stops any other way (e.g. Ctrl-C) before that,
`run_first_run_setup()` returns False.

Serving pattern (uvicorn.Server(...).serve() awaited as a task rather than
uvicorn.run()) mirrors src/voice/pipeline.py's run_voice_agent(), which
composes uvicorn inside an already-running event loop the same way. Unlike
that module, no custom signal handling is installed here — a Ctrl-C during
setup is expected to fall through to uvicorn's own default handling, which is
enough for a one-time local setup flow; the "did it finish?" contract is just
whether the serve task ends with the save/local-mode outcome flag set.

No key value is ever printed, logged, or echoed anywhere (uvicorn is started
with access_log=False; validation failures surface only the exception class
name or provider HTTP status, never headers or key contents).
"""
from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
from html import escape
from pathlib import Path
from typing import Any, Callable

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from src.config import missing_cloud_keys, reload_settings

CLOUD_KEY_FIELDS: tuple[str, ...] = ("DEEPGRAM_API_KEY", "OPENAI_API_KEY", "CARTESIA_API_KEY")
LOGIN_FIELDS: tuple[str, ...] = ("DEMO_LOGIN_EMAIL", "DEMO_LOGIN_PASSWORD")
FORM_FIELDS: tuple[str, ...] = CLOUD_KEY_FIELDS + LOGIN_FIELDS

# display title + provider console link for each cloud key field, in form order
_PROVIDER_INFO: dict[str, tuple[str, str]] = {
    "DEEPGRAM_API_KEY": ("Deepgram — speech recognition", "https://console.deepgram.com/"),
    "OPENAI_API_KEY": ("OpenAI — language model", "https://platform.openai.com/api-keys"),
    "CARTESIA_API_KEY": ("Cartesia — voice synthesis", "https://play.cartesia.ai/"),
}

# live-validation target per key: (url, header-builder) — 2xx on GET = valid
_PROVIDER_CHECKS: dict[str, tuple[str, Callable[[str], dict[str, str]]]] = {
    "DEEPGRAM_API_KEY": ("https://api.deepgram.com/v1/projects", lambda k: {"Authorization": f"Token {k}"}),
    "OPENAI_API_KEY": ("https://api.openai.com/v1/models", lambda k: {"Authorization": f"Bearer {k}"}),
    "CARTESIA_API_KEY": (
        "https://api.cartesia.ai/voices/",
        lambda k: {"X-API-Key": k, "Cartesia-Version": "2026-03-01"},
    ),
}

_VALIDATE_TIMEOUT_S = 8.0

# .env.example lives at the repo root regardless of what env_path a caller
# passes (tests point env_path at a temp dir); this file is three levels
# above this module (src/setup/first_run.py -> src/setup -> src -> repo root).
_ENV_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / ".env.example"

ValidateFn = Callable[[dict[str, str]], Any]  # dict[str, str], or an Awaitable of one


def needs_setup() -> bool:
    """True when the active provider mode is cloud and a required key is unset.

    `missing_cloud_keys()` already returns [] outside cloud mode, so local
    mode never needs setup.
    """
    return bool(missing_cloud_keys())


async def _validate_keys_live(keys: dict[str, str]) -> dict[str, str]:
    """Default validator: one live GET per provider key; any 2xx = valid.

    A blank value fails locally as "required" with no network round trip.
    Only the exception class name or HTTP status is ever put in an error
    message — never headers or key contents — so a failure can't leak a
    credential into the rendered page.
    """
    errors: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=_VALIDATE_TIMEOUT_S) as client:
        for var_name, (url, make_headers) in _PROVIDER_CHECKS.items():
            value = keys.get(var_name, "").strip()
            if not value:
                errors[var_name] = "required"
                continue
            try:
                resp = await client.get(url, headers=make_headers(value))
            except httpx.RequestError as e:
                errors[var_name] = f"could not reach provider ({e.__class__.__name__})"
                continue
            if not (200 <= resp.status_code < 300):
                errors[var_name] = f"rejected by provider (HTTP {resp.status_code})"
    return errors


def _merge_env_file(env_path: str, updates: dict[str, str]) -> None:
    """Merge `updates` (VAR -> new value) into the .env file at `env_path`.

    Creates the file from .env.example's content first if `env_path` doesn't
    exist yet. Every line not touched by `updates` — comments, blank lines,
    unrelated vars — passes through byte-for-byte (original line ending
    included); a var with an existing `VAR=...` line gets that line's value
    replaced in place, and any var with no existing line is appended. Write
    is atomic (temp file in the same directory + os.replace) so a crash
    mid-write can never leave a half-written .env behind.
    """
    path = Path(env_path)
    original = path.read_text(encoding="utf-8") if path.exists() else _ENV_TEMPLATE_PATH.read_text(encoding="utf-8")

    remaining = dict(updates)
    out_lines: list[str] = []
    for line in original.splitlines(keepends=True):
        body = line.rstrip("\n").rstrip("\r")
        is_assignment = "=" in body and not body.lstrip().startswith("#")
        var_name = body.split("=", 1)[0].strip() if is_assignment else None
        if var_name is not None and var_name in remaining:
            eol = line[len(body):]  # preserve this line's exact original ending (or none)
            out_lines.append(f"{var_name}={remaining.pop(var_name)}{eol}")
        else:
            out_lines.append(line)

    if remaining:
        if out_lines and not out_lines[-1].endswith("\n"):
            out_lines[-1] += "\n"
        out_lines.extend(f"{var_name}={value}\n" for var_name, value in remaining.items())

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".env.tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("".join(out_lines))
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


# ---- HTML rendering (inline CSS, no frameworks, no JS except the success poll) ----

_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>demo-agent setup</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; min-height: 100%; }
  body {
    display: flex; align-items: center; justify-content: center;
    background: #0f1115; color: #e6e8ec;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    padding: 40px 16px;
  }
  .card {
    width: 100%; max-width: 460px;
    background: #171a21; border: 1px solid #2a2e38; border-radius: 12px;
    padding: 34px 36px 38px;
    box-shadow: 0 24px 64px rgba(0, 0, 0, 0.4);
  }
  h1 { font-size: 1.2rem; margin: 0 0 8px; letter-spacing: -0.01em; }
  p.sub { color: #9aa1ac; font-size: 0.875rem; line-height: 1.55; margin: 0 0 26px; }
  .field { margin-bottom: 20px; }
  .field-head {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 7px; gap: 10px;
  }
  .field-title { font-size: 0.85rem; color: #c7cbd4; }
  code.var-tag {
    font-family: "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
    font-size: 0.68rem; color: #7c8493;
    background: #0d0f13; border: 1px solid #2a2e38; border-radius: 4px;
    padding: 2px 6px; white-space: nowrap;
  }
  input[type=password], input[type=text], input[type=email] {
    width: 100%; background: #0d0f13; border: 1px solid #2a2e38; border-radius: 7px;
    padding: 10px 12px; color: #e6e8ec;
    font-family: "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
    font-size: 0.85rem;
  }
  input:focus { outline: none; border-color: #5b8def; }
  input.field-error { border-color: #e5484d; }
  .field-foot {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-top: 6px; font-size: 0.75rem; gap: 10px;
  }
  .field-foot a { color: #5b8def; text-decoration: none; }
  .field-foot a:hover { text-decoration: underline; }
  .field-foot .err {
    color: #e5484d; font-family: "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
    text-align: right;
  }
  .divider { border-top: 1px solid #2a2e38; margin: 22px 0 22px; padding-top: 20px; }
  .section-label {
    font-size: 0.72rem; color: #7c8493; text-transform: uppercase;
    letter-spacing: 0.06em; margin-bottom: 6px;
  }
  .section-note { color: #9aa1ac; font-size: 0.8rem; line-height: 1.5; margin: 0 0 16px; }
  .actions { display: flex; flex-direction: column; gap: 10px; margin-top: 28px; }
  button { font-family: inherit; font-size: 0.9rem; border-radius: 7px; padding: 11px 16px; cursor: pointer; }
  .primary { background: #5b8def; color: #0b0d11; font-weight: 600; border: none; }
  .primary:hover { background: #7aa3f5; }
  .secondary { background: transparent; color: #9aa1ac; border: 1px solid #2a2e38; }
  .secondary:hover { color: #e6e8ec; border-color: #4a505c; }
  .badge {
    width: 40px; height: 40px; border-radius: 50%; background: #1f3a2b; color: #3ecf7e;
    display: flex; align-items: center; justify-content: center; font-size: 1.2rem;
    margin-bottom: 16px;
  }
</style>
</head>
<body>
<div class="card">
__BODY__
</div>
</body>
</html>
"""


def _shell(body: str) -> str:
    return _PAGE_TEMPLATE.replace("__BODY__", body)


def _key_field_html(var_name: str, value: str, error: str) -> str:
    title, link = _PROVIDER_INFO[var_name]
    err_class = " field-error" if error else ""
    return f"""      <div class="field">
        <div class="field-head">
          <span class="field-title">{escape(title)}</span>
          <code class="var-tag">{escape(var_name)}</code>
        </div>
        <input type="password" id="{var_name}" name="{var_name}" value="{escape(value, quote=True)}"
               autocomplete="off" required class="{err_class.strip()}">
        <div class="field-foot">
          <a href="{escape(link)}" target="_blank" rel="noopener">Get your key →</a>
          {f'<span class="err">{escape(error)}</span>' if error else ''}
        </div>
      </div>
"""


def _login_field_html(var_name: str, label: str, input_type: str, value: str) -> str:
    return f"""      <div class="field">
        <div class="field-head">
          <span class="field-title">{escape(label)}</span>
          <code class="var-tag">{escape(var_name)}</code>
        </div>
        <input type="{input_type}" id="{var_name}" name="{var_name}" value="{escape(value, quote=True)}"
               autocomplete="off">
      </div>
"""


def _render_setup_page(values: dict[str, str], errors: dict[str, str]) -> str:
    key_fields = "".join(_key_field_html(name, values.get(name, ""), errors.get(name, "")) for name in CLOUD_KEY_FIELDS)
    login_fields = (
        _login_field_html("DEMO_LOGIN_EMAIL", "App login email", "text", values.get("DEMO_LOGIN_EMAIL", ""))
        + _login_field_html("DEMO_LOGIN_PASSWORD", "App login password", "password", values.get("DEMO_LOGIN_PASSWORD", ""))
    )
    body = f"""    <h1>demo-agent setup</h1>
    <p class="sub">First-run setup: add your provider keys — they're written to .env
      locally and never leave this machine.</p>
    <form method="post" action="/save">
{key_fields}      <div class="divider">
        <div class="section-label">App login — optional</div>
        <p class="section-note">Optional; you can also just log in manually in the
          browser window when it opens.</p>
{login_fields}      </div>
      <div class="actions">
        <button type="submit" class="primary">Save keys and continue</button>
        <button type="submit" formaction="/local-mode" class="secondary">Use local mode instead (no keys)</button>
      </div>
    </form>
"""
    return _shell(body)


def _render_success_page(*, poll: bool) -> str:
    if poll:
        # No redirect to /client/: the app auto-connects the voice client in
        # its own controlled browser — a redirect here would spawn a SECOND
        # client session. This window's job is done.
        body = """    <div class="badge">&#10003;</div>
    <h1>Setup complete</h1>
    <p class="sub">Keys saved. The demo is starting — its own window opens in a
    moment. You can close this one.</p>
"""
    else:
        body = """    <div class="badge">&#10003;</div>
    <h1>Local mode set</h1>
    <p class="sub">Local mode set. The app is starting; see the terminal.</p>
"""
    return _shell(body)


async def run_first_run_setup(
    *,
    host: str = "localhost",
    port: int = 7860,
    env_path: str = ".env",
    validate: ValidateFn | None = None,
) -> bool:
    """Serve the first-run setup page until the user completes it.

    GET / renders the form. POST /save validates the three cloud keys (via
    `validate`, or the real live default when `validate` is None) and on
    success merges the submitted fields into `env_path`; POST /local-mode
    sets PROVIDER_MODE=local the same way. Either success path calls
    `reload_settings()` (only when `env_path == ".env"` — the real default,
    never a test's temp path), stops the server, and this function returns
    True. If the server stops any other way first (e.g. Ctrl-C — no special
    signal handling is installed, so uvicorn's own default takes over), it
    returns False.

    `validate(keys: dict[str, str]) -> dict[str, str]` may be a plain
    function or return an awaitable of one; empty dict means all keys valid,
    otherwise {var_name: error_message} for the fields that failed.
    """
    validate_fn: ValidateFn = validate if validate is not None else _validate_keys_live

    state: dict[str, Any] = {"values": {name: "" for name in FORM_FIELDS}, "errors": {}}
    outcome = {"done": False}

    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(_render_setup_page(state["values"], state["errors"]))

    @app.post("/save", response_class=HTMLResponse)
    async def save(request: Request) -> HTMLResponse:
        form = await request.form()
        values = {name: str(form.get(name) or "").strip() for name in CLOUD_KEY_FIELDS}
        values["DEMO_LOGIN_EMAIL"] = str(form.get("DEMO_LOGIN_EMAIL") or "").strip()
        values["DEMO_LOGIN_PASSWORD"] = str(form.get("DEMO_LOGIN_PASSWORD") or "")
        state["values"] = values

        raw = validate_fn({name: values[name] for name in CLOUD_KEY_FIELDS})
        errors = await raw if inspect.isawaitable(raw) else raw
        state["errors"] = errors
        if errors:
            return HTMLResponse(_render_setup_page(values, errors))

        updates = {name: value for name, value in values.items() if value}
        _merge_env_file(env_path, updates)
        if env_path == ".env":
            reload_settings()

        page = _render_success_page(poll=True)
        outcome["done"] = True
        server.should_exit = True
        return HTMLResponse(page)

    @app.post("/local-mode", response_class=HTMLResponse)
    async def local_mode() -> HTMLResponse:
        _merge_env_file(env_path, {"PROVIDER_MODE": "local"})
        if env_path == ".env":
            reload_settings()

        page = _render_success_page(poll=False)
        outcome["done"] = True
        server.should_exit = True
        return HTMLResponse(page)

    # Same async-native uvicorn pattern as src/voice/pipeline.py:run_voice_agent
    # (Server.serve() awaited as a task, never uvicorn.run()) so this composes
    # inside whatever event loop the caller is already running. No custom
    # signal handling here, unlike that module — a bare Ctrl-C falling through
    # to uvicorn's own default handling is enough for a one-time setup form.
    config = uvicorn.Config(app, host=host, port=port, access_log=False, timeout_graceful_shutdown=3)
    server = uvicorn.Server(config)

    serve_task = asyncio.create_task(server.serve())
    while not server.started and not serve_task.done():
        await asyncio.sleep(0.05)
    if serve_task.done():
        await serve_task  # startup failed (e.g. port already in use) -- surface the error
        return False

    await serve_task
    return outcome["done"]
