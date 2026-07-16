"""Post-call report page — render a session's lead report as one HTML file.

Usage:
    python -m src.enrichment.view [out/session-<ts>.json] [--no-open]

Defaults to the newest out/session-*.json; writes the .html next to the .json
and opens it. app.py also renders (and opens) this automatically when a session
ends, mirroring the qualification card the real product shows after a call.
Self-contained: inline CSS, no JS, everything HTML-escaped.
"""
from __future__ import annotations

import html
import json
import sys
import webbrowser
from pathlib import Path

_STATUS_COLORS = {
    "qualified": "#1a7f37",
    "interested": "#0969da",
    "neutral": "#57606a",
    "not_a_fit": "#cf222e",
    "unknown": "#57606a",
}

_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f6f8fa; color: #1f2328; margin: 0; padding: 2rem 1rem; }
.card { max-width: 780px; margin: 0 auto; background: #fff; border: 1px solid #d0d7de;
        border-radius: 12px; padding: 2rem 2.2rem; }
h1 { font-size: 1.25rem; margin: 0 0 .2rem; }
.meta { color: #57606a; font-size: .85rem; margin-bottom: 1.4rem; }
.pill { display: inline-block; color: #fff; border-radius: 999px; padding: .15rem .7rem;
        font-size: .8rem; font-weight: 600; vertical-align: middle; margin-left: .5rem; }
h2 { font-size: .8rem; text-transform: uppercase; letter-spacing: .06em; color: #57606a;
     margin: 1.6rem 0 .5rem; border-top: 1px solid #eaeef2; padding-top: 1.2rem; }
.summary { font-size: .98rem; line-height: 1.55; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: .8rem 1.4rem; }
.cell .k { font-size: .75rem; color: #57606a; text-transform: capitalize; }
.cell .v { font-size: .92rem; }
ul { margin: .3rem 0; padding-left: 1.2rem; }
.qa { margin-bottom: .8rem; }
.qa .q { font-weight: 600; font-size: .92rem; }
.qa .a { color: #424a53; font-size: .92rem; }
.next { background: #ddf4ff; border: 1px solid #b6e3ff; border-radius: 8px;
        padding: .7rem 1rem; font-size: .95rem; }
.turn { margin: .45rem 0; font-size: .9rem; line-height: 1.45; }
.turn .who { display: inline-block; min-width: 3.4rem; font-weight: 600; color: #57606a;
             font-size: .75rem; text-transform: uppercase; }
.turn.user .who { color: #0969da; }
.empty { color: #8c959f; font-style: italic; }
"""


def _esc(x) -> str:
    return html.escape(str(x or ""))


def render(path: Path) -> Path:
    data = json.loads(path.read_text())
    r = data.get("report", {})
    status = r.get("lead_status") or "unknown"
    color = _STATUS_COLORS.get(status, "#57606a")

    fields = "".join(
        f"<div class='cell'><div class='k'>{_esc(k.replace('_', ' '))}</div>"
        f"<div class='v'>{_esc(r.get(k)) or '&mdash;'}</div></div>"
        for k in ("prospect_context", "icp_classification", "current_state", "use_case")
    )
    pains = "".join(f"<li>{_esc(p)}</li>" for p in r.get("pain_points") or []) \
        or "<li class='empty'>None captured.</li>"
    qa = "".join(
        f"<div class='qa'><div class='q'>{_esc(p.get('question'))}</div>"
        f"<div class='a'>{_esc(p.get('answer'))}</div></div>"
        for p in r.get("questions_and_answers") or [] if isinstance(p, dict)
    ) or "<p class='empty'>None captured.</p>"
    transcript = "".join(
        f"<div class='turn {_esc(t.get('role'))}'>"
        f"<span class='who'>{'You' if t.get('role') == 'user' else 'Agent'}</span> "
        f"{_esc(t.get('content'))}</div>"
        for t in data.get("transcript") or []
    ) or "<p class='empty'>No conversation captured.</p>"

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Demo report — {_esc(data.get('generated_at', path.stem))}</title>
<style>{_CSS}</style></head><body><div class="card">
<h1>Post-demo lead report
  <span class="pill" style="background:{color}">{_esc(status.replace('_', ' '))}</span></h1>
<div class="meta">{_esc(data.get('generated_at', ''))} &middot;
  {data.get('transcript_turns', 0)} turns</div>
<div class="summary">{_esc(r.get('summary')) or "<span class='empty'>No summary.</span>"}</div>
<h2>Prospect</h2><div class="grid">{fields}</div>
<h2>Pain points</h2><ul>{pains}</ul>
<h2>Questions &amp; answers</h2>{qa}
<h2>Suggested next step</h2><div class="next">{_esc(r.get('next_step')) or '&mdash;'}</div>
<h2>Transcript</h2>{transcript}
</div></body></html>"""

    out = path.with_suffix(".html")
    out.write_text(doc)
    return out


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if args:
        path = Path(args[0])
    else:
        candidates = sorted(Path("out").glob("session-*.json"))
        if not candidates:
            print("no session reports in out/ — run a demo first")
            return 1
        path = candidates[-1]
    out = render(path)
    print(f"post-call report: {out}")
    if "--no-open" not in argv:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
