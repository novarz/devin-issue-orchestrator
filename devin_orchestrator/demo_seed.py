"""Pre-populate metrics and store with realistic demo data.

Activated by ``DEMO_SEED=true``.  The seed issues use negative numbers
so they never collide with real GitHub issues ingested by the poller.
"""

from __future__ import annotations

import time

from .metrics import Metrics
from .models import IssueEvent, IssueState, TrackedIssue
from .store import IssueStore

_SEED_ISSUES: list[dict[str, object]] = [
    {
        "number": -1,
        "title": "Add type hints to BaseStatsLogger methods",
        "state": IssueState.VERIFIED_PASSED,
        "attempts": 1,
        "retries": 0,
        "acus": 0.8,
        "time_to_pr": 97.0,
        "pr_url": "https://github.com/novarz/superset/pull/10",
        "session_url": "https://app.devin.ai/sessions/demo-seed-001",
    },
    {
        "number": -2,
        "title": "Replace hardcoded '<NULL>' with constant in utils",
        "state": IssueState.VERIFIED_PASSED,
        "attempts": 2,
        "retries": 1,
        "acus": 2.1,
        "time_to_pr": 184.0,
        "pr_url": "https://github.com/novarz/superset/pull/11",
        "session_url": "https://app.devin.ai/sessions/demo-seed-002",
    },
    {
        "number": -3,
        "title": "Add __repr__ to AnnotationLayer model",
        "state": IssueState.VERIFIED_PASSED,
        "attempts": 1,
        "retries": 0,
        "acus": 0.5,
        "time_to_pr": 141.0,
        "pr_url": "https://github.com/novarz/superset/pull/12",
        "session_url": "https://app.devin.ai/sessions/demo-seed-003",
    },
    {
        "number": -4,
        "title": "Fix missing return type in CacheManager.get()",
        "state": IssueState.VERIFIED_PASSED,
        "attempts": 1,
        "retries": 0,
        "acus": 0.6,
        "time_to_pr": 112.0,
        "pr_url": "https://github.com/novarz/superset/pull/13",
        "session_url": "https://app.devin.ai/sessions/demo-seed-004",
    },
    {
        "number": -5,
        "title": "Improve error messages in SQLAlchemy connection handler",
        "state": IssueState.VERIFIED_PASSED,
        "attempts": 2,
        "retries": 1,
        "acus": 1.9,
        "time_to_pr": 203.0,
        "pr_url": "https://github.com/novarz/superset/pull/14",
        "session_url": "https://app.devin.ai/sessions/demo-seed-005",
    },
    {
        "number": -6,
        "title": "Implement real-time collaborative editing for SQL Lab",
        "state": IssueState.ESCALATED,
        "attempts": 3,
        "retries": 2,
        "acus": 4.7,
        "time_to_pr": None,
        "pr_url": None,
        "session_url": "https://app.devin.ai/sessions/demo-seed-006",
    },
    {
        "number": -7,
        "title": "Add docstrings to all public methods in security manager",
        "state": IssueState.VERIFIED_PASSED,
        "attempts": 1,
        "retries": 0,
        "acus": 1.2,
        "time_to_pr": 158.0,
        "pr_url": "https://github.com/novarz/superset/pull/16",
        "session_url": "https://app.devin.ai/sessions/demo-seed-007",
    },
]


def seed(repo: str, metrics: Metrics, store: IssueStore) -> int:
    """Inject demo data and return the number of seeded issues."""
    now = time.time()
    for item in _SEED_ISSUES:
        number = int(str(item["number"]))
        event = IssueEvent(
            repo=repo,
            number=number,
            title=str(item["title"]),
            body="(demo seed)",
            url=f"https://github.com/{repo}/issues/{abs(number)}",
        )
        state: IssueState = item["state"]  # type: ignore[assignment]
        attempts: int = int(str(item["attempts"]))
        retries: int = int(str(item["retries"]))
        acus: float = float(str(item["acus"]))
        time_to_pr = item["time_to_pr"]
        ttp_float: float | None = (
            float(str(time_to_pr)) if time_to_pr is not None else None
        )

        tracked = TrackedIssue(
            event=event,
            state=state,
            session_id=f"demo-seed-{abs(number):03d}",
            session_url=str(item["session_url"]),
            pr_url=str(item["pr_url"]) if item["pr_url"] else None,
            attempts=attempts,
            retries=retries,
            acus_consumed=acus,
            created_at=now - 3600 + (abs(number) * 300),
            session_started_at=now - 3600 + (abs(number) * 300) + 5,
            pr_opened_at=(
                now - 3600 + (abs(number) * 300) + 5 + ttp_float
                if ttp_float is not None
                else None
            ),
            completed_at=now - 3600 + (abs(number) * 300) + 600,
        )
        store._issues[event.id] = tracked
        store._seen.add(event.id)

        metrics.record_issue()
        metrics.record_session_created()
        if tracked.pr_url:
            metrics.record_pr_opened(ttp_float)
        for _ in range(retries):
            metrics.record_retry()
        if state == IssueState.VERIFIED_PASSED:
            metrics.record_verification(passed=True)
            metrics.record_issue_completed(acus, retries)
        elif state == IssueState.ESCALATED:
            metrics.record_escalation()
            metrics.record_issue_completed(acus, retries)
        elif state == IssueState.VERIFIED_FAILED:
            metrics.record_verification(passed=False)
            metrics.record_failure()

    return len(_SEED_ISSUES)
