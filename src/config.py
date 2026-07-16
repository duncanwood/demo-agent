"""Central config + provider factory (BUILD_PLAN B8).

Reads .env and constructs the STT / LLM / TTS services for the pipecat pipeline,
switching on PROVIDER_MODE (cloud | local). Imports are done lazily inside the
factories so `cloud` mode never requires the local extras and vice-versa.

`settings` is a single mutable instance shared by every importer. The first-run
setup GUI can write new values into .env while the process is running, then call
`reload_settings()` — fields are refreshed IN PLACE so references captured via
`from src.config import settings` see the new values too.

Verified pipecat 1.5.0 import paths live in docs/pipecat-api.md.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# Saved browser auth state (written after a successful login, skips login on
# later runs). Overridable via STORAGE_STATE; gitignored.
DEFAULT_STORAGE_STATE = ".auth-state.json"


@dataclass
class Settings:
    provider_mode: str = "cloud"
    target_url: str = ""
    context_url: str = ""
    login_email: str = ""
    login_password: str = ""
    storage_state: str = DEFAULT_STORAGE_STATE
    openai_model: str = "gpt-4o"
    ollama_model: str = "llama3.1"
    ollama_base_url: str = "http://localhost:11434/v1"
    cartesia_voice_id: str = ""

    def refresh_from_env(self) -> None:
        self.provider_mode = os.getenv("PROVIDER_MODE", "cloud").strip()
        self.target_url = os.getenv("DEMO_TARGET_URL", "").strip()
        self.context_url = os.getenv("CONTEXT_URL", "").strip()
        self.login_email = os.getenv("DEMO_LOGIN_EMAIL", "").strip()
        self.login_password = os.getenv("DEMO_LOGIN_PASSWORD", "")
        self.storage_state = os.getenv("STORAGE_STATE", "").strip() or DEFAULT_STORAGE_STATE
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o").strip()
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1").strip()
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").strip()
        self.cartesia_voice_id = os.getenv("CARTESIA_VOICE_ID", "").strip()


settings = Settings()
settings.refresh_from_env()


def reload_settings() -> None:
    """Re-read .env (override) and refresh the shared `settings` in place."""
    load_dotenv(override=True)
    settings.refresh_from_env()


def missing_cloud_keys() -> list[str]:
    """Names of required-but-unset env keys for the active provider mode."""
    if settings.provider_mode != "cloud":
        return []
    required = ("DEEPGRAM_API_KEY", "OPENAI_API_KEY", "CARTESIA_API_KEY")
    return [k for k in required if not os.getenv(k)]


def validate_for_mode() -> None:
    """Fail fast with one friendly line if required keys are missing for the active mode.

    Call this before constructing any pipecat service so a misconfigured .env
    produces a clean message instead of a KeyError traceback.
    """
    labels = {
        "DEEPGRAM_API_KEY": "Deepgram STT",
        "OPENAI_API_KEY": "OpenAI LLM",
        "CARTESIA_API_KEY": "Cartesia TTS",
    }
    missing = missing_cloud_keys()
    if missing:
        print(
            "demo-agent: missing required environment variable(s): "
            + ", ".join(f"{k} ({labels[k]})" for k in missing)
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
        # An empty voice_id fails at synthesis time, so default to a catalog
        # voice ("Blake", conversational male) when none is configured.
        voice_id=settings.cartesia_voice_id or "a167e0f3-df7e-4d52-a9c3-f949145efdab",
    )
