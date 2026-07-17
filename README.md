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

Prerequisites: `make` and `curl` — nothing else. Setup provisions its own
pinned Python 3.12 via [uv](https://docs.astral.sh/uv/) (installing uv first if
missing), so the install is identical on every machine regardless of system
Python. Disk: ~1.1 GB total (~750 MB venv — mostly pipecat's media stack — plus
one ~330 MB Chromium build).

```bash
make setup          # venv + deps + Chromium + scaffolds .env
make run            # everything else is guided
```

On a first run with no keys, a **setup page opens in your browser**: paste your
three provider keys (all have free tiers; each is validated live), optionally the
target app's login. Keys are written to your local `.env` — you can also just
edit `.env` by hand and skip the page entirely.

Then everything opens itself and tells you where it is: the Chromium window
starts on a **splash checklist** (opening the app → signing in → reading the
product → voice server → connecting audio), the voice client connects in a
background tab with the mic pre-granted, and you land on the demo page with the
agent greeting you — the voice client lives in a **background tab you never
see**. The **status sidebar** on the demo page is the whole cockpit: live
phase, what the agent is doing ("Clicking 'Dashboard'…"), a **running
transcript**, **mic picker**, **bot volume**, **Mute mic**, and **End demo**;
the **Audio panel** button fronts the live client tab (same session) for
anything deeper. Interrupt the agent any time — it stops and listens.

**Logging into the target app** happens on a ladder, whichever rung works first:
a saved session from a previous run (`.auth-state.json`) → credentials from
`.env` → **just log in yourself** in the Chromium window — the agent detects it,
saves the session for next time, and continues. `make reset-auth` forgets the
saved session.

**After the call:** the demo ends three ways — **the agent closes it itself**
at a natural endpoint (you say goodbye, it says goodbye back and hangs up),
the sidebar's **End demo** button, or Ctrl-C. All three end gracefully and
write
`out/session-<timestamp>.json` (structured lead report + full transcript), and
opens a **post-call report page** — lead status, prospect profile, pain points,
the questions asked with answers given, a suggested next step, and the
transcript. `make report` reopens the newest one; every run also logs to
`out/agent.log` with timestamps.

## Configuration (`.env`)

| Variable | Required | Purpose |
|---|---|---|
| `DEEPGRAM_API_KEY` | cloud mode | Speech-to-text |
| `OPENAI_API_KEY` | cloud mode | The demo agent (LLM, function calling) |
| `CARTESIA_API_KEY` | cloud mode | Text-to-speech |
| `DEMO_TARGET_URL` | yes | The app to demo (default: the assessment app) |
| `DEMO_LOGIN_EMAIL` / `DEMO_LOGIN_PASSWORD` | no | App login — omit to log in manually instead (auto-detected) |
| `CONTEXT_URL` | no | Landing page to distill product context from (default: the logged-in app page itself) |
| `STORAGE_STATE` | no | Saved auth state path (default `.auth-state.json`, gitignored) |
| `AUTO_OPEN` | no | `0` disables the self-opening browser tabs |
| `OPENAI_MODEL`, `CARTESIA_VOICE_ID` | no | Provider tuning (voice defaults to a sensible pick) |

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
- **Providers sit behind one seam.** STT/LLM/TTS are built by a small factory
  (`src/config.py`), so swapping any stage is a one-function change.
- **Context comes from behind the login.** For gated apps an unauthenticated
  fetch sees only the sign-in screen, so by default the brief is distilled from
  the page the agent is actually logged into; `CONTEXT_URL` overrides with a
  public page when you want marketing-site framing.
- **Setup is part of the product.** Missing keys produce a local setup page
  (validated live, written to `.env`, never leaving the machine), not a stack
  trace; a missing login becomes "log in yourself, I'll notice" rather than a
  crash. Ctrl-C is a graceful path: the browser closes and the report writes.

## Tests

Four self-contained smoke suites run against a bundled fixture page — no API keys
and no network needed:

```bash
for t in browser tools distiller report login_wait setup panel; do .venv/bin/python tests/${t}_smoke.py; done
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

- **Setup can't find or fetch Python** — `make setup` uses uv, which downloads
  a managed CPython 3.12; if your network blocks it, install uv or Python 3.12
  yourself and rerun.
- **Login page still showing** — the target app is self-serve signup; create an
  account, then either log in in the Chromium window (auto-detected) or put the
  credentials in `.env`.
- **Wrong account / stale session** — `make reset-auth`, then run again.
- **Login detection on SSO/magic-link apps** — detection watches for the password
  field to disappear, so password-less flows may be marked logged-in early; use
  `.env` credentials or `STORAGE_STATE` for those.
- **Port 7860 busy** — stop the other process; the client URL is fixed to 7860.
- **Stopping** — one Ctrl-C ends gracefully (writes the report); a second one
  force-exits.
- **A `libav`/objc duplicate-class warning at startup** — harmless, from a
  transitive audio dependency.
