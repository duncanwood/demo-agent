"""Browser actions as LLM function tools (BUILD_PLAN B4 — the core join).

Registers the BrowserController surface as pipecat function tools so the agent can
drive the app while narrating. Each tool call should: move the synthetic cursor to
the target, perform the action, then return a COMPACT result (e.g. the new page
snapshot) for the next turn.

Verified pipecat 1.5.0 (see docs/pipecat-api.md):
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    # OpenAILLMService.register_function(name, handler) exists.

Suggested tools: navigate(url), click(ref), type(ref, text), scroll(direction),
read_page().  Keep the schema tight and results small so voice stays responsive.

TODO(B4): build ToolsSchema from FunctionSchema list, attach to the LLMContext,
and llm.register_function(name, handler) for each, where handlers call the
BrowserController.
"""
from __future__ import annotations


def register_browser_tools(llm, context, controller) -> None:
    raise NotImplementedError("B4: define FunctionSchemas + register_function handlers.")
