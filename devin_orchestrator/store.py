"""In-memory persistence of tracked issues and session mappings.

The store doubles as the dedupe :class:`SeenStore` for ingestion adapters, so a
single source of truth records which issues have been observed.
"""

from __future__ import annotations

from typing import Optional

from .models import IssueEvent, TrackedIssue


class IssueStore:
    """Maps issue IDs to their orchestration state and session IDs.

    Also serves as the dedupe ``SeenStore`` for ingestion adapters so that a
    single object is the source of truth for which issues have been observed.
    """

    def __init__(self) -> None:
        self._issues: dict[str, TrackedIssue] = {}
        self._seen: set[str] = set()

    # --- SeenStore protocol (used by ingestion dedupe) ---
    def is_seen(self, issue_id: str) -> bool:
        return issue_id in self._seen or issue_id in self._issues

    def mark_seen(self, issue_id: str) -> None:
        self._seen.add(issue_id)

    # --- Tracking API ---
    def track(self, event: IssueEvent) -> TrackedIssue:
        tracked = TrackedIssue(event=event)
        self._issues[event.id] = tracked
        return tracked

    def get(self, issue_id: str) -> Optional[TrackedIssue]:
        return self._issues.get(issue_id)

    def by_session(self, session_id: str) -> Optional[TrackedIssue]:
        for tracked in self._issues.values():
            if tracked.session_id == session_id:
                return tracked
        return None

    def all(self) -> list[TrackedIssue]:
        return list(self._issues.values())
