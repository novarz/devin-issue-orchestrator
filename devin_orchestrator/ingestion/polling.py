"""Polling ingestion adapter.

Polls the GitHub Issues API, dedupes already-seen issue IDs, and emits internal
:class:`IssueEvent` objects. Requires no inbound public URL.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

from devin_orchestrator.ingestion.base import IngestionAdapter
from devin_orchestrator.models import IssueEvent

logger = logging.getLogger(__name__)


class _IssueSource(Protocol):
    async def list_open_issues(
        self, repo: str, since: Optional[str] = None, labels: Optional[str] = None
    ) -> list[dict[str, Any]]: ...


class SeenStore(Protocol):
    """Persistence boundary for dedupe state."""

    def is_seen(self, issue_id: str) -> bool: ...

    def mark_seen(self, issue_id: str) -> None: ...


class InMemorySeenStore:
    """Default in-process dedupe store."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def is_seen(self, issue_id: str) -> bool:
        return issue_id in self._seen

    def mark_seen(self, issue_id: str) -> None:
        self._seen.add(issue_id)


def to_issue_event(repo: str, payload: dict[str, Any]) -> IssueEvent:
    """Map a raw GitHub issue payload to an internal event."""
    labels = tuple(
        str(label["name"])
        for label in payload.get("labels", []) or []
        if isinstance(label, dict) and label.get("name")
    )
    return IssueEvent(
        repo=repo,
        number=int(payload["number"]),
        title=str(payload.get("title") or ""),
        body=str(payload.get("body") or ""),
        url=str(payload.get("html_url") or ""),
        labels=labels,
        created_at=payload.get("created_at"),
    )


class PollingIngestionAdapter(IngestionAdapter):
    """Emits new-issue events by polling the GitHub Issues API."""

    name = "polling"

    def __init__(
        self,
        github: _IssueSource,
        repo: str,
        seen: Optional[SeenStore] = None,
        label_filter: str = "",
        skip_label: str = "",
    ) -> None:
        self._github = github
        self._repo = repo
        self._seen: SeenStore = seen or InMemorySeenStore()
        self._label_filter = label_filter
        self._skip_label = skip_label
        self._since: Optional[str] = None

    async def fetch_new_events(self) -> list[IssueEvent]:
        issues = await self._github.list_open_issues(
            self._repo, since=self._since, labels=self._label_filter or None
        )
        events: list[IssueEvent] = []
        for payload in issues:
            try:
                event = to_issue_event(self._repo, payload)
            except (KeyError, ValueError, TypeError):
                logger.warning("Skipping malformed issue payload")
                continue

            self._advance_since(payload.get("updated_at"))

            if self._seen.is_seen(event.id):
                continue
            if self._skip_label and self._skip_label in event.labels:
                self._seen.mark_seen(event.id)
                continue

            self._seen.mark_seen(event.id)
            events.append(event)
            logger.info("New issue detected: %s", event.id)
        return events

    def _advance_since(self, updated_at: Optional[Any]) -> None:
        if isinstance(updated_at, str) and (
            self._since is None or updated_at > self._since
        ):
            self._since = updated_at
