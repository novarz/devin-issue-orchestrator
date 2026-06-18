"""Minimal HTML dashboard rendering for the orchestrator."""

from __future__ import annotations

from html import escape
from typing import Any

from .models import TrackedIssue


def _card(label: str, value: Any) -> str:
    return (
        '<div class="card"><div class="value">'
        f"{escape(str(value))}</div>"
        f'<div class="label">{escape(label)}</div></div>'
    )


def _row(issue: TrackedIssue) -> str:
    pr = f'<a href="{escape(issue.pr_url)}">PR</a>' if issue.pr_url else "&mdash;"
    session = (
        f'<a href="{escape(issue.session_url)}">session</a>'
        if issue.session_url
        else "&mdash;"
    )
    ttp = (
        f"{issue.time_to_pr_seconds:.0f}s"
        if issue.time_to_pr_seconds is not None
        else "&mdash;"
    )
    return (
        "<tr>"
        f"<td>#{issue.event.number}</td>"
        f"<td>{escape(issue.event.title)}</td>"
        f"<td><span class='pill'>{escape(issue.state.value)}</span></td>"
        f"<td>{issue.attempts}</td>"
        f"<td>{issue.retries}</td>"
        f"<td>{issue.acus_consumed:.2f}</td>"
        f"<td>{ttp}</td>"
        f"<td>{session}</td>"
        f"<td>{pr}</td>"
        "</tr>"
    )


def render_dashboard(
    repo: str, metrics: dict[str, Any], issues: list[TrackedIssue]
) -> str:
    cards = "".join(
        [
            _card("Issues ingested", metrics["issues_ingested"]),
            _card("Sessions created", metrics["sessions_created"]),
            _card("PRs opened", metrics["prs_opened"]),
            _card("Success rate", f"{metrics['success_rate'] * 100:.0f}%"),
            _card("Verifications passed", metrics["verifications_passed"]),
            _card("Verifications failed", metrics["verifications_failed"]),
            _card("Escalations", metrics["escalations"]),
            _card("Retries (total)", metrics["retries_total"]),
            _card("Avg time-to-PR", f"{metrics['avg_time_to_pr_seconds']:.0f}s"),
            _card("Total ACU cost", metrics["total_acu_cost"]),
        ]
    )
    rows = "".join(_row(i) for i in issues) or (
        '<tr><td colspan="9" class="empty">No issues processed yet.</td></tr>'
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta http-equiv="refresh" content="10"/>
<title>Devin Issue Orchestrator</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1b1b2f;
         background: #f6f7fb; }}
  h1 {{ font-size: 1.4rem; }}
  .repo {{ color: #555; margin-bottom: 1.5rem; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fill,
            minmax(160px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
  .card {{ background: #fff; border-radius: 10px; padding: 1rem;
           box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  .card .value {{ font-size: 1.6rem; font-weight: 700; }}
  .card .label {{ color: #667; font-size: .8rem; margin-top: .25rem; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border-radius: 10px; overflow: hidden;
           box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  th, td {{ text-align: left; padding: .6rem .8rem; border-bottom: 1px solid
            #eee; font-size: .9rem; }}
  th {{ background: #fafafe; }}
  .pill {{ background: #eef; border-radius: 999px; padding: .1rem .6rem;
           font-size: .8rem; }}
  .empty {{ text-align: center; color: #999; padding: 1.5rem; }}
  a {{ color: #3b5bdb; }}
</style>
</head>
<body>
  <h1>Devin Issue Orchestrator</h1>
  <div class="repo">Repository: <strong>{escape(repo)}</strong>
    &middot; auto-refreshes every 10s</div>
  <div class="cards">{cards}</div>
  <table>
    <thead><tr>
      <th>Issue</th><th>Title</th><th>State</th><th>Attempts</th>
      <th>Retries</th><th>ACUs</th><th>Time-to-PR</th><th>Session</th><th>PR</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>"""
