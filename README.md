# demo-agent

A local agent that gives **live, spoken product demos** of a web app. It learns the
product from a URL as it starts, joins a voice call in your browser, and walks you
through the real UI — talking, answering questions, and driving a visible Chromium
with an on-screen cursor. After the session it writes a structured lead report.

Everything runs on one machine: the voice pipeline is
[Pipecat](https://github.com/pipecat-ai/pipecat) over serverless WebRTC (no
accounts, no signaling infrastructure), and the browser is a Playwright-managed
Chromium driven through the DOM.

## Quickstart

Prerequisites: Python **3.11+**, `make`. (Uses ~2 GB disk for the venv + Chromium.)

```bash
make setup          # venv + deps + Chromium + scaffolds .env
$EDITOR .env        # add the three API keys (all have free tiers) + app login
make run            # starts the browser + voice server
```

Then open **http://localhost:7860/client/**, click Connect, and start talking.
The agent greets you, asks what you care about, and gives a tailored tour of the
target app while you watch it drive. Interrupt it any time — it stops and listens.

When the server stops (Ctrl-C after the conversation), the lead report is written
to `out/session-<timestamp>.json`.

## Configuration (`.env`)

| Variable | Required | Purpose |
|---|---|---|
| `DEEPGRAM_API_KEY` | cloud mode | Speech-to-text |
| `OPENAI_API_KEY` | cloud mode | The demo agent (LLM, function calling) |
| `CARTESIA_API_KEY` | cloud mode | Text-to-speech |
| `DEMO_TARGET_URL` | yes | The app to demo (default: the assessment app) |
| `DEMO_LOGIN_EMAIL` / `DEMO_LOGIN_PASSWORD` | if app is gated | Best-effort login at startup |
| `CONTEXT_URL` | no | Landing page to distill product context from (falls back to the target itself) |
| `STORAGE_STATE` | no | Path for saved auth state — skips login on later runs |
| `PROVIDER_MODE` | no | `cloud` (default) or `local` (zero keys, see below) |
| `OPENAI_MODEL`, `CARTESIA_VOICE_ID`, `OLLAMA_*` | no | Provider tuning |

## Local mode (no API keys)

All three stages can run locally: Whisper STT (in-process), an
[Ollama](https://ollama.com) model, and Kokoro TTS (in-process).

```bash
make local-setup                  # installs Whisper + Kokoro extras
ollama pull llama3.1              # any tool-calling model works; set OLLAMA_MODEL
# set PROVIDER_MODE=local in .env, then:
make run
```

First run downloads the Whisper model; expect a delay. Cloud mode is the smoother
demo (latency, voice quality); local mode is the no-keys fallback.

## How it works

```
            you (voice, browser client at /client/)
                          ⇅  WebRTC audio
   Pipecat pipeline:  STT → LLM agent → TTS      (barge-in via VAD)
                          │
                          │  function calls: read_page / click / type_text /
                          │                  select_option / scroll / navigate
                          ▼
   BrowserController (Playwright, headed Chromium) → the target web app
                          ▲
   startup: context distiller renders CONTEXT_URL headlessly → product brief
   shutdown: enrichment sink → out/session-<ts>.json (lead report + transcript)
```

Design choices worth knowing:

- **DOM control, not vision.** The agent sees a compact snapshot of interactive
  elements (`{ref, role, name}`, capped and deduplicated) and acts by ref. Every
  action returns a fresh snapshot, so the model always acts on current state; a
  stale ref returns a readable error the agent recovers from.
- **The cursor is real to the viewer, synthetic to the machine.** A JS overlay
  glides to each element before the action lands, so the demo reads like a person
  driving — while control stays deterministic in the DOM.
- **Speech leads the click.** The system prompt sequences narration before
  action, keeps turns short and speakable, and grounds answers in the distilled
  product brief plus what's actually on screen.
- **The demo can't be steered off the product.** The `navigate` tool refuses
  URLs outside the target app's origin; tool errors return to the model as
  `{"error": ...}` strings — nothing a tool does can crash the session.
- **Providers are swappable.** STT/LLM/TTS are built by a small factory switched
  on `PROVIDER_MODE`; the one-shot calls (distiller, report) ride the same switch.

## Tests

Four self-contained smoke suites run against a bundled fixture page — no API keys
and no network needed:

```bash
for t in browser tools distiller report; do .venv/bin/python tests/${t}_smoke.py; done
```

## Layout

```
src/app.py            entry point — full session lifecycle
src/voice/            Pipecat pipeline + dev server (SmallWebRTC)
src/browser/          Playwright controller + cursor overlay
src/agent/            tool schemas/handlers + demo-flow system prompt
src/context/          startup product-context distiller
src/enrichment/       post-session lead report
docs/SPEC.md          design spec and decisions
docs/BUILD_PLAN.md    task breakdown as built
docs/pipecat-api.md   pipecat 1.5.0 API facts, verified against the installed package
tests/                fixture page + smoke suites
```

## Troubleshooting

- **`Python 3.11+ required`** — rerun as `make setup PYTHON=/path/to/python3.11+`.
- **`missing required environment variable(s)`** — fill the keys in `.env`, or set
  `PROVIDER_MODE=local`.
- **Login page still showing** — the target app is self-serve signup; create an
  account first and put the credentials in `.env`.
- **Port 7860 busy** — stop the other process; the client URL is fixed to 7860.
- **A `libav`/objc duplicate-class warning at startup** — harmless, from a
  transitive audio dependency.
