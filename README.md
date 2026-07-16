# demo-agent

A local, open-source agent that delivers **live, voice-driven, personalized product
demos** of a web app. It reads a target product, joins a voice call, and walks a
prospect through the live UI — talking, answering questions, and driving the browser in
real time (moving a visible cursor, clicking, scrolling, navigating).

Built to run entirely on one machine with a one-command setup — no cloud deployment
required.

> Status: **spec/scaffold**. See [`docs/SPEC.md`](docs/SPEC.md). Two design decisions are
> open (model-provider default; scope tier).

## What it does

1. **Learns the product** — point it at a URL; it distills product context before/at the
   start of the demo.
2. **Talks** — a Pipecat voice pipeline (speech-to-text → LLM → text-to-speech) over a
   serverless WebRTC connection, with barge-in.
3. **Drives the app** — an LLM agent navigates a real browser via the DOM (Playwright),
   with a synthetic on-screen cursor, narrating as it goes.
4. **Captures the outcome** — a post-demo summary and structured lead insights.

## Layout

```
src/            application code
docs/SPEC.md    design spec + open decisions
_research/      working notes (gitignored — not part of the deliverable)
```

## Quickstart

_TBD once the stack is locked (single `setup` script + `.env.example` + one run command)._
