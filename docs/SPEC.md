# demo-agent — design spec

**Status:** LOCKED (2026-07-16). Decisions resolved (§6). Ordered tasks in
[BUILD_PLAN.md](BUILD_PLAN.md); start-here handoff in [../HANDOFF.md](../HANDOFF.md).

## 1. Goal

Reproduce the core of an agentic live-demo product as a **local** app. The assessment brief
is the real guideline (verbatim):

> Create your own agent. You can use pipecat to build this solution, no need to write your
> own WebRTC server.
> **Deliverables:** (1) Working demo of `https://metric-master-suite505.apps.rebolt.ai/`,
> (2) brief docs on how to run the project, (3) any environment variables or setup
> instructions.
> **Time:** open-ended — focus on demonstrating skills rather than completing every feature.
> **Extra:** configurable with a landing-page URL; it learns about the company as the demo
> starts. "We value creativity and clean implementation."

There is wide interpretive room. We optimize for a clean, runnable, tasteful slice — not
feature completeness.

## 2. Non-goals (v1)

- No cloud deployment / hosted remote-browser (the real product streams a cloud browser; we
  drive a local one).
- No multi-LLM ensemble (the real product runs several; we run one coherent agent).
- No real CRM integration (enrichment is written to a local JSON file — a mock sink).
- No auth automation beyond a single configured login for the target app.

## 3. Architecture (proposed)

Four components, one process:

```
            ┌─────────────── Pipecat voice pipeline ───────────────┐
  user  ⇄   │  SmallWebRTCTransport → STT → LLM(agent) → TTS        │
 (browser   └───────────────────────────┬──────────────────────────┘
  voice)                                 │ tool calls
                                         ▼
                         ┌── Browser controller (Playwright) ──┐
                         │  navigate / click / type / scroll   │
                         │  read DOM (accessibility snapshot)  │
                         │  synthetic cursor overlay (JS)      │
                         └──────────────┬──────────────────────┘
                                        │ drives
                                 local Chromium → target web app

  Context distiller (startup): fetch config URL → LLM → product brief → agent system prompt
  Enrichment sink (end):       conversation → LLM → summary + structured insights → JSON
```

- **Voice** — Pipecat. Transport is `SmallWebRTCTransport` (serverless peer-to-peer, no
  Daily account, no keys). The agent is the LLM stage of the pipeline, with browser tools
  exposed as function calls. Barge-in via Pipecat's built-in turn handling.
- **Browser control** — Playwright driving a Playwright-managed **headed Chromium** (so
  `playwright install` gets a known-good binary; no dependence on the user's Chrome). The
  agent picks elements from a serialized DOM/accessibility snapshot (element refs), not from
  screenshots — matching the "work in the DOM" approach.
- **Synthetic cursor** — a JS-injected overlay that animates to the target element's
  coordinates before each action, reproducing the visible-pointer effect Duncan observed in
  the real demo (control is DOM-based; the cursor is cosmetic).
- **Context distiller** — at startup, fetch the configured URL, LLM-summarize into a product
  brief, inject into the agent's system prompt (the "learns about the company as the demo
  starts" Extra). v1 = single page; shallow crawl is a stretch.
- **Enrichment sink** — at end, LLM produces a summary + structured fields (lead intent,
  interests, questions asked, suggested next step) written to `out/session-*.json`.

## 4. Interaction loop

Greet → ask intent → distilled-context-aware narrated navigation of the target app (drive
UI + talk) → answer questions grounded in the product brief → offer a wrap-up → emit summary
+ insights. Steerable and interruptible throughout.

## 5. Install & config philosophy

The brief grades on run-docs + env + "clean implementation," so setup ease is a scored
surface:

- One bootstrap (`make setup` or `./setup.sh`): create venv, install deps, `playwright
  install chromium`, scaffold `.env` from `.env.example`.
- One run command that opens the browser and the voice client.
- All provider choices behind a single `.env`; sensible defaults so it runs with minimal
  input.

## 6. Decisions (locked 2026-07-16)

**D1 — Model providers: cloud-default, provider-agnostic, local toggle.** All three stages
(STT/LLM/TTS) are swappable via `.env`. The quickstart default targets **cloud** free-tier
providers for smooth latency — default picks: **Deepgram** STT, **OpenAI** LLM (strong
function-calling), **Cartesia** TTS. A documented one-flag **local** mode (Whisper STT +
Ollama LLM + Kokoro/Piper TTS) runs with zero keys. Transport is `SmallWebRTCTransport` in
both modes (no Daily account, no keys).

**D2 — Scope: ship T1 + T2, T3 as stretch.**
- **T1 — Core loop:** voice + DOM-driven Chromium on the target app + single-URL context
  distill + narrated navigation + synthetic cursor + grounded Q&A.
- **T2 — Enrichment:** post-call summary + structured insight extraction to local JSON.
- **T3 — Stretch:** barge-in tuning, shallow site crawl/RAG, configurable target beyond the
  assessment app, tests, a recorded walkthrough.

No deadline set yet — building to a natural stopping point first.

## 7. Stack summary

Python · Pipecat (`SmallWebRTCTransport`) · Playwright (headed Chromium, DOM-based) ·
pluggable STT/LLM/TTS behind `.env` · local JSON enrichment sink · `make setup` bootstrap.
