"""Central config + provider factory (BUILD_PLAN B8).

Reads .env and constructs the STT / LLM / TTS services for the pipecat pipeline,
switching on PROVIDER_MODE (cloud | local). Imports are done lazily inside the
factories so `cloud` mode never requires the local extras and vice-versa.

Verified pipecat 1.5.0 import paths live in docs/pipecat-api.md. Constructor kwargs
below follow the standard pipecat service pattern — verify against the installed
version when wiring B1/B8 (e.g. `.venv/bin/python -c "from pipecat.services.cartesia.tts import CartesiaTTSService; help(CartesiaTTSService.__init__)"`).
"""
from __future__ import annotations
import os
import sys
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    provider_mode: str = os.getenv("PROVIDER_MODE", "cloud")
    target_url: str = os.getenv("DEMO_TARGET_URL", "")
    context_url: str = os.getenv("CONTEXT_URL", "")
    login_email: str = os.getenv("DEMO_LOGIN_EMAIL", "")
    login_password: str = os.getenv("DEMO_LOGIN_PASSWORD", "")
    storage_state: str = os.getenv("STORAGE_STATE", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.1")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")


settings = Settings()


def validate_for_mode() -> None:
    """Fail fast with one friendly line if required keys are missing for the active mode.

    Cloud mode needs the three keys make_stt/make_llm/make_tts read in their cloud
    branches; local mode needs none. Call this before constructing any pipecat
    service so a misconfigured .env produces a clean message instead of a
    KeyError traceback from inside make_stt/make_llm/make_tts.
    """
    if settings.provider_mode != "cloud":
        return
    required = {
        "DEEPGRAM_API_KEY": "Deepgram STT",
        "OPENAI_API_KEY": "OpenAI LLM",
        "CARTESIA_API_KEY": "Cartesia TTS",
    }
    missing = [f"{key} ({label})" for key, label in required.items() if not os.getenv(key)]
    if missing:
        print(
            "demo-agent: missing required environment variable(s): "
            + ", ".join(missing)
            + " -- set them in .env (see .env.example), or set PROVIDER_MODE=local to run without cloud keys."
        )
        sys.exit(1)


def make_stt():
    if settings.provider_mode == "local":
        import platform

        # needs [whisper] extra; on Apple Silicon also [mlx-whisper] (see
        # requirements-local.txt) — and there the Metal-accelerated MLX backend
        # is the better realtime choice. Models auto-download on first use.
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            from pipecat.services.whisper.stt import WhisperSTTServiceMLX
            return WhisperSTTServiceMLX()
        from pipecat.services.whisper.stt import WhisperSTTService
        return WhisperSTTService()
    from pipecat.services.deepgram.stt import DeepgramSTTService
    return DeepgramSTTService(api_key=os.environ["DEEPGRAM_API_KEY"])


def make_llm():
    """Return an LLM service that supports function calling (register_function)."""
    if settings.provider_mode == "local":
        from pipecat.services.ollama.llm import OLLamaLLMService
        return OLLamaLLMService(model=settings.ollama_model, base_url=settings.ollama_base_url)
    from pipecat.services.openai.llm import OpenAILLMService
    return OpenAILLMService(api_key=os.environ["OPENAI_API_KEY"], model=settings.openai_model)


def make_tts():
    if settings.provider_mode == "local":
        from pipecat.services.kokoro.tts import KokoroTTSService  # needs [kokoro] extra
        return KokoroTTSService()
    from pipecat.services.cartesia.tts import CartesiaTTSService
    return CartesiaTTSService(
        api_key=os.environ["CARTESIA_API_KEY"],
        voice_id=os.getenv("CARTESIA_VOICE_ID", ""),
    )
