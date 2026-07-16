# demo-agent — build plan

Ordered, session-sized tasks for the **T1 + T2** target (see [SPEC.md](SPEC.md) §6).
Each task is scoped to one focused work session with explicit acceptance criteria, so an
orchestrator can dispatch them against the dependency DAG below.

## Dependency DAG

```
B0 setup ──┬──> B1 voice-loop ──┐
           └──> B2 browser ──> B3 cursor ──┴──> B4 agent⇄browser ──┬──> B5 distiller ──┐
                                                                    └──> B6 flow/guards ─┴──> B7 enrichment ──> B8 providers ──> B9 docs/DX
```

`B1` and `B2` are independent and can run in parallel after `B0`. `B4` is the join where
voice + browser + cursor become one agent — it is the project's core and the highest-risk
task. `B7`/`B8`/`B9` are T2 + finish.

---

## B0 — Env & setup bootstrap  *(mostly done)*
**Goal:** one-command setup and run on a clean machine.
**Deliver:** `requirements.txt`/`pyproject`, `.env.example`, `Makefile` (`make setup`,
`make run`), `setup.sh`. `make setup` = create `.venv`, install deps, `playwright install
chromium`, scaffold `.env`.
**Done when:** a fresh clone runs `make setup && make run` and the app launches (agent may be
a stub). **State:** `.venv` already created with pipecat + playwright installed; verified
import paths are in `docs/pipecat-api.md`. Remaining: finalize `Makefile`/`setup.sh` +
`playwright install chromium`.

## B1 — Voice loop (pipecat hello-world)
**Goal:** a spoken back-and-forth in the browser with barge-in, no browser-driving yet.
**Deliver:** `src/voice/pipeline.py` — `SmallWebRTCTransport` + STT + LLM + TTS + Silero VAD,
served by the pipecat dev runner.
**Done when:** you open the local client, speak, the assistant replies by voice, and
interrupting it stops playback.
**Refs:** verified imports in `docs/pipecat-api.md`; official pipecat small-webrtc example.
**Risk:** pin the pipecat API against the *installed* version — do not trust blog snippets.

## B2 — Browser controller (Playwright)
**Goal:** programmatic control of the target app + a DOM snapshot the LLM can act on.
**Deliver:** `src/browser/controller.py` exposing `navigate(url)`, `click(ref)`,
`type(ref, text)`, `scroll(dir)`, `read_page() -> [{ref, role, name, ...}]` (serialized
interactive elements with stable refs, from the accessibility snapshot / DOM).
**Done when:** from a test you drive `metric-master-suite505.apps.rebolt.ai`, get a snapshot
with usable refs, and perform a click by ref.
**Note:** the target app is behind email/password login → support a configured login
(`.env` creds) or a saved Playwright `storage_state`. Headed Chromium (visible).

## B3 — Synthetic cursor overlay
**Goal:** reproduce the visible pointer that glides to each element before acting.
**Deliver:** `src/browser/cursor.js` (injected) + `move_cursor_to(ref)` in the controller;
re-inject on every navigation/load.
**Done when:** a fake cursor animates to an element's center before each click/type, and
persists across page loads. **Depends:** B2.

## B4 — Agent ⇄ browser wiring  *(core — highest risk)*
**Goal:** the LLM narrates by voice while driving the browser via tool calls.
**Deliver:** `src/agent/tools.py` (browser actions as pipecat LLM function tools) +
integration into the B1 pipeline. Feed a fresh `read_page()` summary into the agent context
each turn; the agent decides speech + which tool to call; a tool call triggers
`move_cursor_to` → action.
**Done when:** you say "show me X" and the agent speaks *and* navigates there with the cursor
moving; it stays coherent across several turns. **Depends:** B1, B2, B3.
**Design notes:** keep tool results small (summarized DOM, not raw HTML). Sequence
narration-then-action so speech leads the click. Guard tool-call latency so voice stays
responsive.

## B5 — Context distiller
**Goal:** the "learns about the product as the demo starts" behavior.
**Deliver:** `src/context/distiller.py` — fetch a configured URL (target app and/or a company
landing page), LLM-summarize into a product brief, inject into the agent system prompt at
startup. **Done when:** changing the configured URL visibly changes how the agent frames the
demo. **Depends:** B4.

## B6 — Demo flow + guardrails
**Goal:** the interaction loop feels like a real demo.
**Deliver:** system prompt + flow logic: greet (by name if provided) → ask intent →
steerable narrated tour → grounded Q&A → graceful wrap-up. Guardrails: don't leak the system
prompt, decline off-topic, recover from failed selectors. **Done when:** it matches the loop
in the SPEC and stays interruptible/steerable. **Depends:** B4.

## B7 — Enrichment sink  *(T2)*
**Goal:** capture the demo outcome.
**Deliver:** `src/enrichment/report.py` — on session end, LLM produces a summary + structured
insights (intent, interests, questions asked, suggested next step) → `out/session-<ts>.json`.
Schema mirrors the qualification fields observed in the real product (see brain teardown).
**Done when:** a well-formed JSON report is written after a demo. **Depends:** B4.

## B8 — Providers & config  *(T2)*
**Goal:** cloud-default + keyless local toggle, both documented.
**Deliver:** `src/config.py` provider factory driven by `.env` (`PROVIDER_MODE=cloud|local`);
cloud = Deepgram/OpenAI/Cartesia, local = Whisper/Ollama/Kokoro. **Done when:**
`PROVIDER_MODE=local` runs with no API keys (given Ollama + a local model present).
**Depends:** B1 (factory refactor of the services created there).

## B9 — Docs & DX  *(finish)*
**Goal:** a stranger can run a demo.
**Deliver:** README quickstart (setup, run, `.env` table, how-it-works), troubleshooting,
optional recorded walkthrough. **Done when:** following the README from a clean clone yields a
working demo. **Depends:** B5, B6, B7, B8.

---

### Suggested orchestration
Wave 1: **B1** ∥ **B2** (parallel workers). Wave 2: **B3** (after B2). Wave 3: **B4** (join).
Wave 4: **B5** ∥ **B6** ∥ **B7** (after B4). Wave 5: **B8** then **B9**. Verify each task's
acceptance criteria before advancing (B4 especially — it's where the demo either works or
doesn't).
