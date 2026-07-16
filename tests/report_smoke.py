"""Smoke test for the B7 enrichment sink (BUILD_PLAN B7).

Plain asyncio script (no pytest), style-matched to tests/browser_smoke.py. No API
keys needed -- stubs src.llm_oneshot.complete via write_report's injectable
`complete` kwarg. Exercises: happy-path parse, fenced+prose parse (no retry),
garbage -> fallback (single retry), and the empty-transcript short-circuit.

Run: cd demo-agent && .venv/bin/python tests/report_smoke.py
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.enrichment.report import REPORT_FIELDS, write_report  # noqa: E402

TRANSCRIPT = [
    {"role": "system", "content": "You are demoing the metrics dashboard product."},
    {"role": "assistant", "content": "Hi! Today I'll show you our live metrics dashboard."},
    {"role": "user", "content": "Thanks -- we're trying to replace our spreadsheet-based reporting."},
    {"role": "assistant", "content": "Let me pull up the live revenue chart for you."},
    {"role": "user", "content": "Can this dashboard support custom date ranges?"},
    {"role": "assistant", "content": "Yes, you can pick any custom range from the filter panel."},
    {"role": "user", "content": "That looks promising -- can you send over pricing info?"},
]

VALID_REPORT = {
    "lead_status": "interested",
    "prospect_context": "Currently reports off spreadsheets, evaluating a dashboard replacement.",
    "icp_classification": "mid-market",
    "current_state": "Manual spreadsheet-based reporting.",
    "pain_points": ["Manual spreadsheet reporting is slow"],
    "use_case": "Live revenue metrics dashboard",
    "questions_and_answers": [
        {
            "question": "Can this dashboard support custom date ranges?",
            "answer": "Yes, you can pick any custom range from the filter panel.",
        }
    ],
    "next_step": "Send pricing information",
    "summary": "Prospect wants to replace spreadsheet reporting, asked about custom date ranges, requested pricing.",
}


def make_stub(*responses: str):
    """Returns (stub_complete, calls) -- calls["n"] counts invocations; each call
    returns the next canned response (repeats the last once exhausted)."""
    calls = {"n": 0}

    async def stub(system: str, user: str, **kwargs) -> str:
        i = calls["n"]
        calls["n"] += 1
        return responses[min(i, len(responses) - 1)]

    return stub, calls


async def test_happy_path(out_dir: str) -> dict:
    stub, calls = make_stub(json.dumps(VALID_REPORT))
    path = await write_report(TRANSCRIPT, out_dir=out_dir, complete=stub)
    assert calls["n"] == 1, f"expected 1 stub call, got {calls['n']}"

    data = json.loads(Path(path).read_text())
    for field in REPORT_FIELDS:
        assert field in data["report"], f"missing field {field!r}"
    assert data["transcript_turns"] == 6, data["transcript_turns"]
    assert len(data["transcript"]) == 6
    assert all(t["role"] in ("user", "assistant") for t in data["transcript"])

    qa = data["report"]["questions_and_answers"]
    assert isinstance(qa, list) and len(qa) == 1, qa
    assert set(qa[0].keys()) == {"question", "answer"}, qa[0]
    print("OK: happy path -- all REPORT_FIELDS present, transcript embedded, questions_and_answers well-formed")
    return data["report"]


async def test_fenced_path(out_dir: str) -> None:
    fenced = "Sure thing! Here's the extracted lead report:\n```json\n" + json.dumps(VALID_REPORT, indent=2) + "\n```\n"
    stub, calls = make_stub(fenced)
    path = await write_report(TRANSCRIPT, out_dir=out_dir, complete=stub)
    assert calls["n"] == 1, f"expected 1 stub call (no retry needed), got {calls['n']}"

    data = json.loads(Path(path).read_text())
    assert data["report"]["lead_status"] == "interested", data["report"]
    assert not data["report"].get("parse_error"), data["report"]
    print("OK: fenced + prose response parsed on first attempt, no retry")


async def test_garbage_path(out_dir: str) -> None:
    stub, calls = make_stub("I cannot help with that.", "I cannot help with that.")
    path = await write_report(TRANSCRIPT, out_dir=out_dir, complete=stub)
    assert calls["n"] == 2, f"expected exactly 2 stub calls, got {calls['n']}"

    data = json.loads(Path(path).read_text())
    assert data["report"]["parse_error"] is True, data["report"]
    assert data["report"]["summary"] == "I cannot help with that.", data["report"]["summary"]
    for field in REPORT_FIELDS:
        assert field in data["report"], f"missing field {field!r}"
    print("OK: garbage response -> fallback report (parse_error=true), exactly 2 stub calls")


async def test_empty_transcript(out_dir: str) -> None:
    stub, calls = make_stub("should never be called")
    path = await write_report([], out_dir=out_dir, complete=stub)
    assert calls["n"] == 0, f"expected 0 stub calls for empty transcript, got {calls['n']}"

    data = json.loads(Path(path).read_text())
    assert data["report"]["lead_status"] == "unknown", data["report"]
    assert data["report"]["summary"] == "No conversation captured.", data["report"]
    assert data["transcript_turns"] == 0
    assert data["transcript"] == []
    print("OK: empty transcript -> minimal report written, stub never called")


async def main() -> None:
    out_dir = tempfile.mkdtemp(prefix="report-smoke-")
    try:
        happy_report = await test_happy_path(out_dir)
        await test_fenced_path(out_dir)
        await test_garbage_path(out_dir)
        await test_empty_transcript(out_dir)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)

    print("\n=== happy-path report JSON ===")
    print(json.dumps(happy_report, separators=(",", ":")))
    print("\nREPORT SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
