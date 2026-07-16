"""Pipecat voice loop over SmallWebRTC (BUILD_PLAN B1).

Contract: build and run a pipecat Pipeline that gives a spoken, interruptible
conversation in the browser, with the LLM able to call browser tools (B4).

Verified pipecat 1.5.0 imports (see docs/pipecat-api.md):

    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.task import PipelineTask, PipelineParams
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
    from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.audio.vad.silero import SileroVADAnalyzer

Pipeline order (fill from the official small-webrtc example — confirm the exact
context-aggregator factory, which is NOT OpenAILLMService.create_context_aggregator
in 1.5.0):

    Pipeline([
        transport.input(), stt, user_aggregator,
        llm, tts, transport.output(), assistant_aggregator,
    ])

TODO(B1): stand up the plain voice loop from the example, verify barge-in via
SileroVADAnalyzer, then hand the `llm` + `LLMContext` to agent.tools for B4.
"""
from __future__ import annotations


async def run_voice_agent(*, register_tools=None, system_prompt: str = "") -> None:
    """Build + run the pipecat pipeline. `register_tools(llm, context)` is the B4 hook."""
    raise NotImplementedError("B1: implement the SmallWebRTC voice loop (see docstring).")
