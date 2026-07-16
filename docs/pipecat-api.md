# Pipecat 1.5.0 — verified API reference

Import paths **verified against the installed `pipecat-ai 1.5.0`** in this repo's `.venv`
(Python 3.12) on 2026-07-16. The framework moves fast — trust this over blogs/LLM output,
and re-verify with `.venv/bin/python -c "import ..."` if you bump the version.

## Install
```bash
# cloud default (what B1 uses)
pip install "pipecat-ai[webrtc,openai,deepgram,cartesia,silero]"
playwright install chromium
# local mode extras (B8)
pip install "pipecat-ai[whisper,kokoro]"   # + run Ollama separately
```

## Verified imports (OK)
```python
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.processors.aggregators.llm_context import (
    LLMContext, LLMContextMessage, LLMContextToolChoice,
)
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
```

## Changed / gotchas
- **Old transport path is gone:** `pipecat.transports.network.small_webrtc` → MISS. Use
  `pipecat.transports.smallwebrtc.{transport,connection}`.
- **Context class moved:** `pipecat.processors.aggregators.openai_llm_context.OpenAILLMContext`
  → MISS. Use the universal `LLMContext` (above).
- **Whisper needs its extra:** `WhisperSTTService` import fails until `pipecat-ai[whisper]`
  (pulls `faster_whisper`) is installed.
- Harmless startup noise: an `av`/`cv2` duplicate-dylib objc warning; ignore.

## Function calling (browser tools — B4)
- `OpenAILLMService` has **`register_function`** (verified): register a handler per tool name.
- Define schemas with `FunctionSchema` / `ToolsSchema` from `pipecat.adapters.schemas.*`,
  attach to the `LLMContext`.

## Resolve from the official small-webrtc example (do this at the start of B1)
Two symbols weren't nailed down by introspection — copy them from the current example rather
than guessing:
1. **Context aggregator pair** — `OpenAILLMService.create_context_aggregator` does **not**
   exist in 1.5.0; the universal-context aggregator factory lives elsewhere (see
   `pipecat.processors.aggregators.llm_response_universal` / `llm_context`). Confirm the exact
   call the example uses to get user/assistant aggregators around the `LLMContext`.
2. **Dev runner / signaling** — `pipecat.runner` provides the SmallWebRTC development runner
   (`run`, `types`, `utils` submodules) that serves the web client and handles WebRTC
   signaling. Confirm the entrypoint + how `TransportParams` (VAD, audio in/out) are passed.

Official example to mirror: pipecat-ai/pipecat `examples/` → the SmallWebRTC / foundational
voice-bot sample for 1.5.x.

## Local services available (verified in `pipecat.services`)
`whisper`, `moonshine` (local STT) · `ollama` (local LLM) · `kokoro`, `piper` (local TTS) —
alongside `deepgram`, `openai`, `cartesia`, `anthropic`, `groq`, `elevenlabs`, and ~50 others.
