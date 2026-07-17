"""Central config + provider factory.

Reads .env and constructs the STT / LLM / TTS services for the pipecat
pipeline. Providers sit behind one small factory seam (make_stt/make_llm/
make_tts) so they stay swappable; this build ships the cloud set —
Deepgram / OpenAI / Cartesia.

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


def _normalize_url(url: str) -> str:
    """People type bare domains ("duncanwood.net"); Chromium calls that an
    invalid URL. Default to https:// when no scheme is given."""
    url = url.strip()
    if url and "://" not in url:
        return f"https://{url}"
    return url


@dataclass
class Settings:
    target_url: str = ""
    context_url: str = ""
    login_email: str = ""
    login_password: str = ""
    storage_state: str = DEFAULT_STORAGE_STATE
    openai_model: str = "gpt-4o"
    cartesia_voice_id: str = ""

    def refresh_from_env(self) -> None:
        self.target_url = _normalize_url(os.getenv("DEMO_TARGET_URL", ""))
        self.context_url = _normalize_url(os.getenv("CONTEXT_URL", ""))
        self.login_email = os.getenv("DEMO_LOGIN_EMAIL", "").strip()
        self.login_password = os.getenv("DEMO_LOGIN_PASSWORD", "")
        self.storage_state = os.getenv("STORAGE_STATE", "").strip() or DEFAULT_STORAGE_STATE
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o").strip()
        self.cartesia_voice_id = os.getenv("CARTESIA_VOICE_ID", "").strip()


settings = Settings()
settings.refresh_from_env()


def reload_settings() -> None:
    """Re-read .env (override) and refresh the shared `settings` in place."""
    load_dotenv(override=True)
    settings.refresh_from_env()


def missing_cloud_keys() -> list[str]:
    """Names of required-but-unset provider keys."""
    required = ("DEEPGRAM_API_KEY", "OPENAI_API_KEY", "CARTESIA_API_KEY")
    return [k for k in required if not os.getenv(k)]


def validate_for_mode() -> None:
    """Fail fast with one friendly line if required keys are missing.

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
            + " -- set them in .env (see .env.example), or rerun make run to use the setup page."
        )
        sys.exit(1)


def make_stt():
    from pipecat.services.deepgram.stt import DeepgramSTTService
    return DeepgramSTTService(api_key=os.environ["DEEPGRAM_API_KEY"])


def make_llm():
    """Return an LLM service that supports function calling (register_function)."""
    from pipecat.services.openai.llm import OpenAILLMService
    return OpenAILLMService(api_key=os.environ["OPENAI_API_KEY"], model=settings.openai_model)


def make_tts():
    from pipecat.services.cartesia.tts import CartesiaTTSService
    return CartesiaTTSService(
        api_key=os.environ["CARTESIA_API_KEY"],
        # An empty voice_id fails at synthesis time, so default to a catalog
        # voice ("Blake", conversational male) when none is configured.
        voice_id=settings.cartesia_voice_id or "a167e0f3-df7e-4d52-a9c3-f949145efdab",
    )
