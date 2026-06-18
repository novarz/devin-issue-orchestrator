"""Unit tests for ingestion dedupe and event mapping."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from devin_orchestrator.ingestion.polling import (
    InMemorySeenStore,
    PollingIngestionAdapter,
    to_issue_event,
)


class FakeGitHub:
    """Returns a scripted sequence of issue payload batches."""

    def __init__(self, batches: list[list[dict[str, Any]]]) -> None:
        self._batches = batches
        self.calls = 0

    async def list_open_issues(
        self, repo: str, since: Optional[str] = None, labels: Optional[str] = None
    ) -> list[dict[str, Any]]:
        batch = self._batches[min(self.calls, len(self._batches) - 1)]
        self.calls += 1
        return batch


def _issue(number: int, **extra: Any) -> dict[str, Any]:
    payload = {
        "number": number,
        "title": f"Issue {number}",
        "body": "body",
        "html_url": f"https://github.com/novarz/superset/issues/{number}",
        "updated_at": "2024-01-01T00:00:00Z",
        "labels": [],
    }
    payload.update(extra)
    return payload


@pytest.mark.asyncio
async def test_new_issue_emitted_once() -> None:
    github = FakeGitHub([[_issue(1)], [_issue(1)]])
    adapter = PollingIngestionAdapter(github, "novarz/superset")

    first = await adapter.fetch_new_events()
    second = await adapter.fetch_new_events()

    assert [e.number for e in first] == [1]
    assert second == []


@pytest.mark.asyncio
async def test_distinct_issues_each_emitted() -> None:
    github = FakeGitHub([[_issue(1), _issue(2)], [_issue(2), _issue(3)]])
    adapter = PollingIngestionAdapter(github, "novarz/superset")

    first = await adapter.fetch_new_events()
    second = await adapter.fetch_new_events()

    assert {e.number for e in first} == {1, 2}
    assert {e.number for e in second} == {3}


@pytest.mark.asyncio
async def test_pull_requests_are_not_emitted_by_source_filter() -> None:
    # list_open_issues is responsible for filtering PRs; here we ensure the
    # adapter passes through whatever the source returns (already filtered).
    github = FakeGitHub([[_issue(5)]])
    adapter = PollingIngestionAdapter(github, "novarz/superset")
    events = await adapter.fetch_new_events()
    assert [e.number for e in events] == [5]


@pytest.mark.asyncio
async def test_skip_label_is_ignored_and_marked_seen() -> None:
    github = FakeGitHub([[_issue(9, labels=[{"name": "needs-human"}])], [_issue(9)]])
    adapter = PollingIngestionAdapter(
        github, "novarz/superset", skip_label="needs-human"
    )
    first = await adapter.fetch_new_events()
    second = await adapter.fetch_new_events()
    assert first == []
    assert second == []  # already marked seen, never re-emitted


def test_seen_store_roundtrip() -> None:
    store = InMemorySeenStore()
    assert not store.is_seen("a")
    store.mark_seen("a")
    assert store.is_seen("a")


def test_to_issue_event_maps_labels() -> None:
    event = to_issue_event(
        "novarz/superset", _issue(3, labels=[{"name": "bug"}, {"name": "ui"}])
    )
    assert event.labels == ("bug", "ui")
    assert event.id == "novarz/superset#3"
