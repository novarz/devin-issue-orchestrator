"""Background loop that drives ingestion -> orchestration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .ingestion.base import IngestionAdapter
from .orchestrator import Orchestrator

logger = logging.getLogger(__name__)


class PollerLoop:
    """Periodically pulls events from an adapter and dispatches remediation."""

    def __init__(
        self,
        adapter: IngestionAdapter,
        orchestrator: Orchestrator,
        interval_seconds: float,
    ) -> None:
        self._adapter = adapter
        self._orchestrator = orchestrator
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._inflight: set[asyncio.Task[Any]] = set()
        self._stopping = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="orchestrator-poller")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for task in list(self._inflight):
            task.cancel()
        await self._adapter.stop()

    async def _run(self) -> None:
        await self._adapter.start()
        logger.info(
            "\U0001f6f0\ufe0f  Poller started via %r adapter (interval=%ss)",
            self._adapter.name,
            self._interval,
        )
        while not self._stopping.is_set():
            await self._poll_once()
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue

    async def _poll_once(self) -> None:
        try:
            events = await self._adapter.fetch_new_events()
        except Exception:  # noqa: BLE001 - a bad poll must not kill the loop
            logger.exception("Ingestion poll failed")
            return
        if events:
            logger.info(
                "\U0001f50d Poll cycle: %s new issue(s) \u2192 dispatching",
                len(events),
            )
        else:
            logger.debug("Poll cycle: no new issues")
        for event in events:
            task = asyncio.create_task(self._orchestrator.handle_event(event))
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)
