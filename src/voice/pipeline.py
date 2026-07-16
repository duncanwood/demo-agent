"""Pipecat voice loop over SmallWebRTC (BUILD_PLAN B1).

Contract: build and run a pipecat Pipeline that gives a spoken, interruptible
conversation in the browser, with the LLM able to call browser tools (B4).

Resolved against the installed pipecat 1.5.0 (see docs/pipecat-api.md and the two
"critical unknowns" it flags — both confirmed by reading the installed source,
not memory):

Context aggregator pair
    ``OpenAILLMService.create_context_aggregator`` does not exist in 1.5.0. The
    real factory is ``LLMContextAggregatorPair`` in
    ``pipecat.processors.aggregators.llm_response_universal``: construct it with
    the shared ``LLMContext``, then unpack ``user, assistant =
    LLMContextAggregatorPair(context, ...)`` (it supports tuple-unpacking, or
    ``.user()`` / ``.assistant()``).

VAD / barge-in moved off the transport
    ``TransportParams`` has no ``vad_analyzer`` field in this version. VAD is
    wired via ``LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())``,
    passed as ``user_params=`` to ``LLMContextAggregatorPair``. Interruptions
    are on by default once VAD is wired
    (``BaseUserTurnStartStrategy.enable_interruptions`` defaults to ``True``) —
    there is no separate "enable interruptions" flag on ``PipelineParams`` in
    this version (checked: it isn't a field).

Dev runner (serves the SmallWebRTC prebuilt client UI + signaling)
    ``pipecat.runner.run`` provides a FastAPI app (module-level singleton
    ``app``) plus a CLI ``main()`` that parses argv, configures routes, and
    blocks on ``uvicorn.run(app, ...)``. It expects a module-level
    ``bot(runner_args)`` coroutine, discovered via ``sys.modules["__main__"]``.
    Calling ``main()`` directly from here doesn't work:

    1. ``run_voice_agent`` must stay ``async def`` (the fixed B4 hook
       signature), so by the time its body runs we're already inside a
       running event loop. ``main()`` ends in ``uvicorn.run(...)``, which
       calls ``asyncio.run()`` internally — that raises ("cannot be called
       from a running event loop") regardless of how ``run_voice_agent``
       itself was invoked; this is a hard asyncio constraint, not a design
       choice pipecat could have avoided for us.
    2. ``main()`` is the whole program (argv parsing + bot dispatch), not a
       reusable "just configure and give me the app" step.

    Adaptation: this module defines the ``bot(runner_args)`` coroutine the
    runner discovers, built the same way ``pipecat.runner.utils.create_transport``
    builds one for ``SmallWebRTCRunnerArguments`` (``SmallWebRTCTransport(
    webrtc_connection=runner_args.webrtc_connection, params=TransportParams(...))``).
    ``app.py`` re-exports ``bot`` (``from src.voice.pipeline import bot``) so it
    lands on ``sys.modules["__main__"]`` when run as ``python -m src.app`` — that
    satisfies the runner's ``_get_bot_module()`` discovery with no monkeypatching.
    ``run_voice_agent`` stays the public, awaitable API: it stashes
    ``register_tools`` / ``system_prompt`` in module state for ``bot()`` to read
    per connection (the runner calls ``bot(runner_args)`` with no way to pass
    extra arguments), then starts the *same* FastAPI app ``main()`` would —
    calling ``pipecat.runner.run._configure_server_app(args)``, the exact routine
    ``main()`` calls before ``uvicorn.run`` (there's no public non-blocking
    equivalent in 1.5.0) — and serves it the async-native way
    (``uvicorn.Server(config).serve()``, awaited directly instead of calling
    ``uvicorn.run()``) so it composes inside our own event loop instead of
    fighting it for one. Default host/port (localhost:7860) match the runner's
    own defaults (``RUNNER_HOST`` / ``RUNNER_PORT``); the client UI is mounted at
    ``/client`` (``_setup_frontend_routes``).

``PipelineTask`` / ``PipelineRunner`` are soft-deprecated in 1.5.0
    Verified by reading the installed source (not in docs.md's verified-imports
    list, found while resolving the aggregator/runner unknowns above):
    ``pipecat.pipeline.task`` and ``pipecat.pipeline.runner`` are both compat
    shims since 1.3.0, removed in 2.0.0 — literally ``class
    PipelineTask(PipelineWorker): pass`` and ``class
    PipelineRunner(WorkerRunner): pass``, and passing a worker to
    ``WorkerRunner.run()`` is separately deprecated too (register it via
    ``add_workers()`` first). This module uses the live names directly
    (``PipelineWorker`` from ``pipecat.pipeline.worker``, ``WorkerRunner`` from
    ``pipecat.workers.runner``, ``runner.add_workers(worker)`` then
    ``runner.run()``) — identical behavior, no deprecation warnings, not
    scheduled for removal. ``PipelineParams`` (undecorated, also in
    ``pipecat.pipeline.worker``) is unaffected either way.

Pipeline order (confirmed against the aggregator pair's intended use):

    Pipeline([
        transport.input(), stt, user_aggregator,
        llm, tts, transport.output(), assistant_aggregator,
    ])
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any, Callable

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import SmallWebRTCRunnerArguments
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from src.config import make_llm, make_stt, make_tts

DEFAULT_SYSTEM_PROMPT = (
    "You are a friendly, concise voice assistant having a live spoken "
    "conversation. Keep replies short and natural."
)

# Runner-driven `bot()` is invoked per WebRTC connection with no way to pass
# extra arguments, so `run_voice_agent` stashes its kwargs here before the
# server starts accepting connections. One demo session type per process (no
# concurrent multi-tenant use), so process-global state is sufficient.
_session: dict[str, Any] = {
    "register_tools": None,
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
}


async def bot(runner_args: SmallWebRTCRunnerArguments) -> None:
    """Pipecat dev-runner entrypoint — discovered via `sys.modules["__main__"]`.

    Builds the transport from the connection the runner already negotiated
    (mirrors `pipecat.runner.utils.create_transport`'s SmallWebRTC branch),
    then wires stt/llm/tts + context + aggregators + pipeline and runs it to
    completion for this one session.
    """
    # The dev server also mounts non-WebRTC routes (e.g. /ws) by default; only
    # the SmallWebRTC browser client is supported here — refuse others cleanly.
    if not isinstance(runner_args, SmallWebRTCRunnerArguments):
        print(f"demo-agent: unsupported transport connection {type(runner_args).__name__}; ignoring.")
        return

    transport = SmallWebRTCTransport(
        webrtc_connection=runner_args.webrtc_connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )

    context = LLMContext(messages=[{"role": "system", "content": _session["system_prompt"]}])
    stt = make_stt()
    llm = make_llm()
    tts = make_tts()

    register_tools: Callable[[Any, LLMContext], None] | None = _session["register_tools"]
    if register_tools is not None:
        register_tools(llm, context)

    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        # VAD lives on the user aggregator in 1.5.0, not on TransportParams
        # (see module docstring) — this is what gives barge-in.
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(pipeline, params=PipelineParams())

    @transport.event_handler("on_client_connected")
    async def _on_client_connected(_transport, _connection) -> None:
        # The demo agent speaks first: kick one LLM turn off the system prompt.
        # Without this the pipeline generates nothing until the user speaks.
        await worker.queue_frames([LLMRunFrame()])

    # handle_sigint=False: this coroutine runs as a FastAPI background task
    # inside the dev server's own process/loop (see run_voice_agent) — the
    # server owns SIGINT: a per-connection runner shouldn't compete for it.
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()


def _dev_runner_args(*, host: str = "localhost", port: int = 7860) -> argparse.Namespace:
    """The defaults `pipecat.runner.run.main()`'s argparse would produce for an
    empty argv (multi-transport enabled — this demo only drives the webrtc
    routes, but leaving the others mounted costs nothing since only the
    browser client ever connects).

    `main()` always parses `sys.argv` and blocks on `uvicorn.run`, so there's no
    public function that just returns the parsed defaults; this reconstructs
    them so `_configure_server_app` (the same route setup `main()` uses) can run
    without a real CLI invocation.
    """
    return argparse.Namespace(
        host=host,
        port=port,
        transport=None,
        proxy=None,
        direct=False,
        folder=None,
        runner_body=None,
        verbose=0,
        dialin=True,
        esp32=False,
        whatsapp=False,
        ws_auth="none",
        allowed_origins=[],
    )


async def run_voice_agent(*, register_tools=None, system_prompt: str = "") -> None:
    """Build + run the pipecat pipeline. `register_tools(llm, context)` is the B4 hook.

    Starts the pipecat SmallWebRTC dev server (prebuilt client UI + signaling)
    and serves it until cancelled. `register_tools` / `system_prompt` are
    stashed for `bot()` (see module docstring) since the runner drives
    connections and calls `bot(runner_args)` with no way to pass extra
    arguments.
    """
    _session["register_tools"] = register_tools
    _session["system_prompt"] = system_prompt or DEFAULT_SYSTEM_PROMPT

    # Imported here, not at module top: importing pipecat.runner.run has
    # import-time side effects (constructs the FastAPI() singleton, calls
    # load_dotenv(override=True)) that should only happen when we're actually
    # about to serve, not merely when something imports this module.
    import uvicorn
    from pipecat.runner.run import _configure_server_app
    from pipecat.runner.run import app as runner_app

    args = _dev_runner_args()
    _configure_server_app(args)  # same route setup main() does before uvicorn.run

    # uvicorn.run() (what main() calls) calls asyncio.run() internally, which
    # raises when — as here — we're already inside a running loop.
    # Server.serve() is the awaitable form, so this composes inside our loop
    # instead of fighting it for one.
    server = uvicorn.Server(
        uvicorn.Config(runner_app, host=args.host, port=args.port, timeout_graceful_shutdown=3)
    )

    # uvicorn's own signal capture re-raises the signal after shutdown, which
    # kills the process before this coroutine ever resumes — everything after
    # this await (browser stop, the lead report) would be dead code on the
    # Ctrl-C/SIGTERM path (verified empirically with a sentinel). So: let serve()
    # start and install its handlers, then override them with loop-level ones
    # that request a graceful stop, making serve() RETURN instead. A second
    # signal force-exits.
    import signal

    serve_task = asyncio.create_task(server.serve())
    while not server.started and not serve_task.done():
        await asyncio.sleep(0.05)
    if serve_task.done():
        await serve_task  # startup failed (e.g. port in use) — surface its error
        return

    def _request_stop() -> None:
        if server.should_exit:
            server.force_exit = True
        server.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _request_stop)

    # Printed only now: the server is actually accepting connections and a
    # Ctrl-C from here on takes the graceful path (a Ctrl-C during startup
    # still hard-exits via uvicorn — nothing to clean up that early).
    print(
        f"Voice agent ready. Open http://{args.host}:{args.port}/client/ in your browser. "
        "Ctrl-C to end the session (writes the lead report).",
        flush=True,
    )
    try:
        await serve_task
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
