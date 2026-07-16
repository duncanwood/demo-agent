"""Browser actions as LLM function tools (BUILD_PLAN B4 — the core join).

Two layers, kept deliberately separate so tests can exercise the action surface
without pipecat in the loop at all:

1. `build_actions(controller)` — a pure `dict[str, Action]` of
   `async def f(args: dict) -> dict` actions over a `BrowserController`. Each
   action returns the controller's compact snapshot dict, or `{"error": ...}` on
   a `ControllerError` — it never raises, so a bad tool call can't crash the demo.
2. `register_browser_tools(llm, context, controller)` — the pipecat adapter:
   builds a `FunctionSchema` per action, assembles a `ToolsSchema`, attaches it to
   the `LLMContext`, and wires each schema to its action via `llm.register_function`.

Resolved against installed pipecat 1.5.0 source (see docs/pipecat-api.md, B4
section, which flagged these as the two unknowns to verify before wiring):

- Tools attach to `LLMContext` via the `set_tools(tools: ToolsSchema | list[...])`
  setter (`pipecat/processors/aggregators/llm_context.py`). `tools=` is also a
  constructor kwarg, but `voice/pipeline.py`'s `bot()` builds the `LLMContext`
  before calling `register_tools(llm, context)`, so the setter is the one that
  applies here — there's no way to reach the constructor from this hook.
- `FunctionCallParams` (`pipecat/services/llm_service.py`) is a dataclass:
  `function_name: str`, `tool_call_id: str`, `arguments: Mapping[str, Any]`,
  `llm`, `pipeline_worker`, `context`, `result_callback: FunctionCallResultCallback`,
  `app_resources: Any = None`. A handler takes one `FunctionCallParams` and
  returns `None`, delivering its result via `await params.result_callback(result)`.
- `LLMService.register_function(function_name, handler, *, cancel_on_interruption=None,
  timeout_secs=None)` — defaults suit these fast, synchronous browser actions.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from urllib.parse import urljoin, urlsplit

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.llm_service import FunctionCallParams

from src.browser.controller import BrowserController, ControllerError
from src.config import settings

Action = Callable[[dict], Awaitable[dict]]


def _guard_navigation(url: str) -> str | None:
    """Resolve `url` against `settings.target_url` and keep navigation on that
    origin. Returns the resolved absolute URL, or None to refuse the navigation.

    Relative URLs (paths, fragments) resolve via urljoin against the target.
    Absolute URLs are allowed only when they share the target's (scheme, netloc).
    `file://` URLs carry no netloc, so for a file:// target (the local fixture)
    this degrades to a scheme match only — any local file counts as "same
    origin". That's an accepted simplification for the fixture case, not a real
    security boundary; it only matters for http(s) targets, where it's exact.
    """
    target = settings.target_url
    if not target:
        return url  # no configured target — nothing to guard against (e.g. ad hoc runs)
    resolved = urljoin(target, url)
    t, r = urlsplit(target), urlsplit(resolved)
    if (t.scheme, t.netloc) != (r.scheme, r.netloc):
        return None
    return resolved


async def _run(call: Awaitable[dict]) -> dict:
    """Await a controller call, converting ControllerError into the LLM-readable
    {"error": ...} shape every action returns instead of raising."""
    try:
        return await call
    except ControllerError as e:
        return {"error": str(e)}


def build_actions(controller: BrowserController) -> dict[str, Action]:
    """Pure async action map over `controller`. Each action takes the tool-call
    arguments dict and returns the controller's compact snapshot dict (or an
    `{"error": ...}` dict) — no pipecat types involved, so this is directly
    testable without a pipeline.
    """

    async def read_page(args: dict) -> dict:
        return await _run(controller.read_page())

    async def click(args: dict) -> dict:
        return await _run(controller.click(args["ref"]))

    async def type_text(args: dict) -> dict:
        return await _run(controller.type(args["ref"], args["text"]))

    async def select_option(args: dict) -> dict:
        return await _run(controller.select(args["ref"], args["option"]))

    async def scroll(args: dict) -> dict:
        return await _run(controller.scroll(args["direction"]))

    async def navigate(args: dict) -> dict:
        resolved = _guard_navigation(args["url"])
        if resolved is None:
            return {"error": "navigation outside the demo app is not allowed"}
        return await _run(controller.navigate(resolved))

    return {
        "read_page": read_page,
        "click": click,
        "type_text": type_text,
        "select_option": select_option,
        "scroll": scroll,
        "navigate": navigate,
    }


# (name, description, properties, required) — tight, demo-flavored descriptions;
# the LLM sees exactly these strings, so they're written as tool docs, not code comments.
_TOOL_SPECS: list[tuple[str, str, dict[str, Any], list[str]]] = [
    (
        "read_page",
        "Read the current browser page: URL, title, main heading, and the visible "
        "interactive elements (each with a ref) you can act on. Call this to see "
        "what's on screen before acting, and any time something unexpected happens.",
        {},
        [],
    ),
    (
        "click",
        "Click an element by its ref from the most recent snapshot.",
        {
            "ref": {
                "type": "string",
                "description": "Element ref (e.g. 'e3') from the most recent snapshot.",
            }
        },
        ["ref"],
    ),
    (
        "type_text",
        "Type text into an input or textarea by its ref, replacing any existing value.",
        {
            "ref": {
                "type": "string",
                "description": "Element ref (e.g. 'e3') from the most recent snapshot.",
            },
            "text": {"type": "string", "description": "Text to type into the field."},
        },
        ["ref", "text"],
    ),
    (
        "select_option",
        "Choose an option in a dropdown by its ref, matching the option's visible label.",
        {
            "ref": {
                "type": "string",
                "description": "Element ref (e.g. 'e3') from the most recent snapshot.",
            },
            "option": {
                "type": "string",
                "description": "Visible label of the option to select.",
            },
        },
        ["ref", "option"],
    ),
    (
        "scroll",
        "Scroll the page to reveal more content.",
        {
            "direction": {
                "type": "string",
                "enum": ["up", "down"],
                "description": "Direction to scroll.",
            }
        },
        ["direction"],
    ),
    (
        "navigate",
        "Navigate to a URL within the demo app. Relative paths resolve against the "
        "demo app's base URL; links outside the demo app are refused.",
        {
            "url": {
                "type": "string",
                "description": "Absolute URL or path within the demo app.",
            }
        },
        ["url"],
    ),
]


def _make_handler(action: Action) -> Callable[[FunctionCallParams], Awaitable[None]]:
    """Adapt a pure action into a pipecat function-call handler: parse the tool
    call's arguments, await the action, deliver its result."""

    async def handler(params: FunctionCallParams) -> None:
        try:
            result = await action(dict(params.arguments))
        except Exception as e:  # last resort: malformed args or a tool bug must not
            # crash a live demo — surface it to the LLM like any other tool error.
            result = {"error": f"{type(e).__name__}: {e}"}
        await params.result_callback(result)

    return handler


def register_browser_tools(llm: Any, context: LLMContext, controller: BrowserController) -> None:
    """Wire the BrowserController as pipecat function tools on one connection's
    `llm` + `context`: build the schemas, attach them to `context`
    (`LLMContext.set_tools`), and register a handler per tool name on `llm`.
    """
    actions = build_actions(controller)
    schemas = [
        FunctionSchema(name=name, description=description, properties=properties, required=required)
        for name, description, properties, required in _TOOL_SPECS
    ]
    context.set_tools(ToolsSchema(standard_tools=schemas))
    for name, _, _, _ in _TOOL_SPECS:
        llm.register_function(name, _make_handler(actions[name]))
