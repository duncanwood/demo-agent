# HANDOFF — start here

This repo is a **local voice + browser live-demo agent**, built for a technical assessment.
Point it at a web app; it joins a voice call and gives a live, personalized, spoken demo,
driving the app's UI in real time. Full context: [`docs/SPEC.md`](docs/SPEC.md).

## Decisions locked (2026-07-16)
- **Cloud-default, provider-agnostic, local toggle** — Deepgram STT / OpenAI LLM / Cartesia
  TTS by default; `PROVIDER_MODE=local` → Whisper / Ollama / Kokoro, zero keys. Transport is
  `SmallWebRTCTransport` (no Daily, no keys) in both modes.
- **Scope: ship T1 (core demo loop) + T2 (enrichment JSON); T3 is stretch.**
- **Local only** — no cloud deployment, drive a local headed Chromium (Playwright-managed).
- No deadline set yet.

## Current state
- **Spec + build plan written**, decisions locked. Tasks: [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md).
- **`.venv` created** with `pipecat-ai 1.5.0 [webrtc,openai,deepgram,cartesia,silero]` +
  `playwright` installed. Verified import paths for pipecat 1.5.0 are in
  [`docs/pipecat-api.md`](docs/pipecat-api.md) — **trust that file over any blog/LLM snippet.**
- **No application code yet.** `src/` is stubs. B0 (setup) is nearly done — finish the
  `Makefile`/`setup.sh` and `playwright install chromium`.
- **Research** (transcript + teardown of the real product) lives in `_research/` (gitignored)
  and canonically in the brain at `assistant/data/notes/karumi/`. **Do not ship `_research/`.**

## Where to start
`docs/BUILD_PLAN.md`, Wave 1: **B1 (voice loop)** and **B2 (browser controller)** in
parallel, then **B3** (cursor), then **B4** (agent ⇄ browser — the core join). Verify each
task's acceptance criteria before advancing; B4 is where the demo works or doesn't.

## Constraints & risks
- **Verify the pipecat API against the installed 1.5.0**, not from memory — the framework
  moves fast. Start B1 from the official small-webrtc example.
- **Target app is gated** (`metric-master-suite505.apps.rebolt.ai`, email/password with
  self-serve signup) — B2 needs a configured login or a saved Playwright `storage_state`.
- **Control is DOM-based** (accessibility snapshot → element refs), *not* vision. The visible
  cursor is a cosmetic overlay (B3).
- **API keys are the developer's own** (free tiers) — this repo is unrelated to the brain's
  no-API-credits rule; that rule governs the assistant, not this project.
- Keep the voice loop responsive: summarize DOM into small tool results, sequence
  narration-before-action, preserve barge-in.

## Running the env (once B0 is finished)
```bash
make setup   # .venv + deps + playwright install chromium + scaffold .env
# edit .env with keys (cloud) or set PROVIDER_MODE=local
make run
```

## Note for the brain
This is a **separate git repo** from the assistant. Session/project memories still go in the
assistant's memory system (already logged: M0003098 job-search state, M0003099 project +
teardown). `mlx-whisper` was added to the brain conda env for transcription — log it in
`setup_requirements.md` at `/fin`.
