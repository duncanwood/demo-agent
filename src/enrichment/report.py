"""Post-demo enrichment sink (BUILD_PLAN B7 — T2).

On session end, summarize the conversation into a lead report + structured insights
and write out/session-<ts>.json (a local mock-CRM sink). Schema mirrors the
qualification fields observed in the real product (brain teardown):
lead_status, prospect_context, icp_classification, current_state, pain_points,
use_case, questions_and_answers, next_step, plus a free-text summary.

Extraction is one LLM call (src.llm_oneshot.complete, R4) prompted for strict JSON
over REPORT_FIELDS. Parsing is defensive -- raw json.loads, then a fence/prose-
stripped retry, then one corrective LLM call, then a parse_error fallback -- a
malformed completion should never lose the session's transcript.

Contract:
    path = await write_report(transcript, out_dir="out", complete=None) -> str
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.llm_oneshot import complete as _default_complete

REPORT_FIELDS = [
    "lead_status", "prospect_context", "icp_classification", "current_state",
    "pain_points", "use_case", "questions_and_answers", "next_step", "summary",
]

SYSTEM_PROMPT = (
    "You are a sales-ops analyst extracting lead-qualification data from a live "
    "product-demo transcript. Base every field strictly on what the transcript shows "
    "-- never invent facts, names, numbers, or intent that isn't there. Respond with "
    "a single JSON object containing exactly these keys:\n"
    '- "lead_status": one of "qualified", "interested", "neutral", "not_a_fit", "unknown"\n'
    '- "prospect_context", "icp_classification", "current_state", "use_case", '
    '"next_step", "summary": strings ("" if unknown -- never invent)\n'
    '- "pain_points": a list of strings\n'
    '- "questions_and_answers": a list of {"question": ..., "answer": ...} pairs '
    "actually asked during the demo\n"
    "Respond with ONLY the JSON object -- no prose, no markdown code fences, no commentary."
)


def _format_transcript(turns: list[dict]) -> str:
    lines = [f"{'USER' if t['role'] == 'user' else 'AGENT'}: {t['content']}" for t in turns]
    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    """json.loads the raw text; on failure, retry on the slice between the outermost
    braces (strips markdown fences and any leading/trailing prose)."""
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1]):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _fill_defaults(report: dict) -> dict:
    """Guarantee every REPORT_FIELDS key is present, filling gaps with ""/[]."""
    filled = dict(report)
    for field in REPORT_FIELDS:
        if not filled.get(field):
            filled[field] = [] if field in ("pain_points", "questions_and_answers") else ""
    return filled


async def write_report(transcript: list[dict], out_dir: str = "out", *, complete=None) -> str:
    """Turn a demo transcript into a lead report and write out/session-<ts>.json.

    Returns the path to the written file.
    """
    complete = complete or _default_complete
    turns = [t for t in transcript if t.get("role") in ("user", "assistant")]

    if not turns:
        report = _fill_defaults({"lead_status": "unknown", "summary": "No conversation captured."})
    else:
        user_content = _format_transcript(turns)
        raw = await complete(SYSTEM_PROMPT, user_content)
        parsed = _extract_json(raw)
        if parsed is None:
            raw = await complete(SYSTEM_PROMPT, user_content + "\n\nReturn ONLY the valid JSON object.")
            parsed = _extract_json(raw)
        if parsed is None:
            parsed = {"summary": raw, "parse_error": True}
        report = _fill_defaults(parsed)

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    path = Path(out_dir) / f"session-{now.strftime('%Y%m%d-%H%M%S')}.json"
    payload = {
        "generated_at": now.isoformat(),
        "transcript_turns": len(turns),
        "report": report,
        "transcript": turns,
    }
    path.write_text(json.dumps(payload, indent=2))
    return str(path)
