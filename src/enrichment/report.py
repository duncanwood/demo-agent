"""Post-demo enrichment sink (BUILD_PLAN B7 — T2).

On session end, summarize the conversation into a lead report + structured insights
and write out/session-<ts>.json (a local mock-CRM sink). Schema mirrors the
qualification fields observed in the real product (brain teardown):
lead_status, prospect_context, icp_classification, current_state, pain_points,
use_case, questions_and_answers, next_step, plus a free-text summary.

Contract:
    path = await write_report(transcript, out_dir="out") -> str
"""
from __future__ import annotations

REPORT_FIELDS = [
    "lead_status", "prospect_context", "icp_classification", "current_state",
    "pain_points", "use_case", "questions_and_answers", "next_step", "summary",
]


async def write_report(transcript: list[dict], out_dir: str = "out") -> str:
    raise NotImplementedError("B7: LLM-extract REPORT_FIELDS from transcript, write JSON.")
