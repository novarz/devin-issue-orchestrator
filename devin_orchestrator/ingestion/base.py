"""Ingestion adapter interface.

The orchestrator consumes :class:`IssueEvent` objects from an adapter without
caring how they were produced. A polling adapter ships as the default; a webhook
handler can implement the same interface later by draining its own queue inside
``fetch_new_events`` -- no public inbound URL is required by the default.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from devin_orchestrator.models import IssueEvent


class IngestionAdapter(ABC):
    """Source of new-issue events at the edge of the system."""

    name: str = "base"

    async def start(self) -> None:  # noqa: B027 - optional no-op hook
        """Optional hook for adapters that need to set up resources."""

    async def stop(self) -> None:  # noqa: B027 - optional no-op hook
        """Optional hook for adapters that need to release resources."""

    @abstractmethod
    async def fetch_new_events(self) -> list[IssueEvent]:
        """Return issue events not yet seen. Must be idempotent across calls.

        Implementations are responsible for their own deduplication so the
        orchestrator never processes the same issue twice.
        """
        raise NotImplementedError
