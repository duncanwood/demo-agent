# Pipecat 1.5.0 — verified API reference

Import paths **verified against the installed `pipecat-ai 1.5.0`** in this repo's `.venv`
(Python 3.12) on 2026-07-16. The framework moves fast — trust this over blogs/LLM output,
and re-verify with `.venv/bin/python -c "import ..."` if you bump the version.

## Install
```bash
# cloud default — [runner] is REQUIRED for the dev server (fastapi/uvicorn/prebuilt client UI)
pip install "pipecat-ai[webrtc,runner,openai,deepgram,cartesia,silero]"
playwright install chromium
# local mode extras (B8)
pip install "pipecat-ai[whisper,kokoro]"   # + run Ollama separately
```

## Verified imports (OK)
```python
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker   # live names (see gotchas)
from pipecat.workers.runner import WorkerRunner
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.runner.types import SmallWebRTCRunnerArguments
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.processors.aggregators.llm_context import (
    LLMContext, LLMContextMessage, LLMContextToolChoice,
)
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair, LLMUserAggregatorParams,
)
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
```

## Changed / gotchas
- **`PipelineTask` / `PipelineRunner` are deprecation shims** (since 1.3.0, removed in
  2.0.0): `pipecat.pipeline.task` / `pipecat.pipeline.runner` just subclass the live
  `PipelineWorker` / `WorkerRunner` (imports above). Also: pass workers via
  `runner.add_workers(worker)` then `runner.run()` — `run(worker)` is separately deprecated.
- **VAD moved off the transport:** `TransportParams` has no `vad_analyzer` field. Wire VAD
  as `LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())` → `user_params=` of
  `LLMContextAggregatorPair`. Interruptions (barge-in) default ON once VAD is wired.
- **Aggregator pair:** `user, assistant = LLMContextAggregatorPair(context, user_params=…)`
  (tuple-unpacks; or `.user()` / `.assistant()`). `create_context_aggregator` does not exist.
- **Old transport path is gone:** `pipecat.transports.network.small_webrtc` → MISS. Use
  `pipecat.transports.smallwebrtc.{transport,connection}`.
- **Context class moved:** `openai_llm_context.OpenAILLMContext` → MISS. Use `LLMContext`.
- **Whisper needs its extra:** `WhisperSTTService` import fails until `pipecat-ai[whisper]`
  (pulls `faster_whisper`) is installed.
- Harmless startup noise: an `av`/`cv2` duplicate-dylib objc warning; ignore.

## Dev runner (resolved — how src/voice/pipeline.py serves the client)
- Entrypoint contract: define `async def bot(runner_args: SmallWebRTCRunnerArguments)` at
  module level; the runner discovers it via `sys.modules["__main__"].bot` (src/app.py
  re-exports it). Called once per WebRTC connection; build the transport yourself:
  `SmallWebRTCTransport(webrtc_connection=runner_args.webrtc_connection, params=TransportParams(...))`.
- `pipecat.runner.run.main()` blocks (calls `uvicorn.run` → `asyncio.run`) — unusable inside
  a running loop. `run_voice_agent` instead calls `_configure_server_app(args)` (same route
  setup) and awaits `uvicorn.Server(Config(app,…)).serve()`. Pinned to ==1.5.0 since
  `_configure_server_app` is private-by-convention.
- Client UI: `http://localhost:7860/client/` (`/` 307-redirects there). Defaults
  `RUNNER_HOST`/`RUNNER_PORT` = localhost:7860. `/status` lists mounted transports.
- The server also mounts non-WebRTC routes (`/ws` etc.) by default; `bot()` guards with an
  `isinstance` check and ignores non-SmallWebRTC connections.

## Function calling (browser tools — B4)
- `OpenAILLMService` has **`register_function`** (verified): register a handler per tool name.
- Define schemas with `FunctionSchema` / `ToolsSchema` from `pipecat.adapters.schemas.*`,
  attach to the `LLMContext`. B4: verify the exact attach point (constructor arg vs setter)
  and the handler signature (`FunctionCallParams`: `.arguments`, `await .result_callback(...)`)
  against installed source before wiring.

## Local services available (verified in `pipecat.services`)
`whisper`, `moonshine` (local STT) · `ollama` (local LLM) · `kokoro`, `piper` (local TTS) —
alongside `deepgram`, `openai`, `cartesia`, `anthropic`, `groq`, `elevenlabs`, and ~50 others.
